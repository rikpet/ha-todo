"""The Claude worker: picks up tasks handed to Claude and runs Claude Code on them.

Runs wherever Claude Code is installed and logged in - a Raspberry Pi, a Windows
laptop. Each task gets its own `claude -p` run with the todo MCP server attached;
Claude reads the task, does the work in a per-task folder and hands its answer
back with finish_task.

Billing: the run must use the Claude subscription you logged in with, never an
API key. So the worker strips API-key variables from Claude's environment,
refuses to start when `claude auth status` reports API-key or cloud-provider
auth, never passes --bare (which only accepts API keys), and uses --restricted
where available so a settings-file apiKeyHelper cannot slip one in either.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

# Variables that would make Claude Code bill an API account or a cloud provider
# instead of the subscription. CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)
# is a subscription token and is deliberately kept.
API_BILLING_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)

FILE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"]
COMMAND_TOOLS = ["Bash"]

PROMPT = """\
You are working through the user's todo list (the ha-todo app). Task #{task_id} has been \
handed to you.

1. Call the todo tool get_task with task_id={task_id}. Read the task and its note thread: \
the latest note from "me" is what the user wants now; earlier notes are history, including \
your own earlier answers.
2. Do the work. The folder {workdir} is yours for this task: put any files you create \
there and mention their paths in your answer.
3. Call finish_task with task_id={task_id} and your answer in Markdown, written in the \
language the task is written in. Lead with the outcome. If you cannot do it, call \
finish_task with failed=true and say what is missing.

You may use create_task for follow-up steps the user has to take themselves. Never mark \
tasks as done - the user does that after reviewing your answer."""


class WorkerError(Exception):
    """A problem with the worker's setup; the message tells the user what to fix."""


@dataclass
class WorkerConfig:
    server_url: str
    claude: str = "claude"
    workdir: Path = field(default_factory=lambda: Path.home() / "todo-claude")
    allow_commands: bool = True
    model: str | None = None
    timeout_minutes: int = 30


def claude_env(base: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Claude's environment without API-billing variables, and the names removed."""
    env = dict(os.environ if base is None else base)
    removed = [name for name in API_BILLING_VARS if env.pop(name, None) is not None]
    return env, removed


def find_claude(name: str = "claude") -> str:
    path = shutil.which(name)
    if not path:
        raise WorkerError(
            f"Claude Code ('{name}') is not on PATH. Install it first: "
            "https://code.claude.com/docs/en/setup"
        )
    return path


def check_subscription(status: dict[str, Any]) -> str:
    """Accept only a logged-in claude.ai account; return the auth method for the log."""
    if not status.get("loggedIn"):
        raise WorkerError("Claude Code is not logged in. Run `claude` once and use /login "
                          "with your Claude account (Pro/Max), or `claude setup-token`.")
    provider = str(status.get("apiProvider") or "firstParty")
    if provider != "firstParty":
        raise WorkerError(f"Claude Code is set up for {provider}, which is billed there, not "
                          "to your Claude subscription. Remove that configuration first.")
    method = str(status.get("authMethod") or "unknown")
    if "api" in method.lower().replace("_", "").replace("-", ""):
        raise WorkerError(f"Claude Code authenticates with an API key ({method}), which "
                          "bills your API account. Log in with your Claude account instead "
                          "(`claude auth login`), and remove any apiKeyHelper setting.")
    return method


def auth_status(claude: str, env: dict[str, str]) -> dict[str, Any]:
    try:
        done = subprocess.run([claude, "auth", "status", "--json"], env=env, capture_output=True,
                              text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkerError(f"Could not run `claude auth status`: {exc}") from exc
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise WorkerError("`claude auth status` gave no JSON - update Claude Code "
                          f"(output: {(done.stdout or done.stderr).strip()[:200]})") from exc


def supports_restricted(claude: str, env: dict[str, str]) -> bool:
    try:
        done = subprocess.run([claude, "--help"], env=env, capture_output=True, text=True,
                              timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "--restricted" in done.stdout


def mcp_config(server_url: str) -> dict[str, Any]:
    """Run the MCP server with the same Python as this CLI, so no PATH lookup is needed."""
    return {"mcpServers": {"todo": {
        "command": sys.executable,
        "args": ["-m", "todo_app.cli", "mcp"],
        "env": {"TODO_URL": server_url},
    }}}


def build_command(config: WorkerConfig, claude: str, mcp_path: Path,
                  restricted: bool) -> list[str]:
    tools = FILE_TOOLS + (COMMAND_TOOLS if config.allow_commands else [])
    command = [claude, "-p", "--output-format", "json",
               "--mcp-config", str(mcp_path), "--strict-mcp-config",
               "--allowedTools", ",".join(tools + ["mcp__todo"])]
    if restricted:
        # only these built-in tools exist, file tools stay inside the task folder,
        # and settings files (a possible apiKeyHelper among them) are not read
        command += ["--restricted", "--tools", ",".join(tools)]
    elif not config.allow_commands:
        command += ["--disallowedTools", "Bash"]
    if config.model:
        command += ["--model", config.model]
    return command


@dataclass
class RunResult:
    ok: bool
    text: str


def parse_output(returncode: int, stdout: str, stderr: str) -> RunResult:
    """Claude's final message from --output-format json, or the reason the run failed."""
    try:
        data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except ValueError:
        data = {}
    text = str(data.get("result") or "").strip()
    if returncode == 0 and data and not data.get("is_error"):
        return RunResult(True, text)
    reason = text or stderr.strip() or stdout.strip() or f"exit code {returncode}"
    return RunResult(False, reason[-4000:])


class Worker:
    def __init__(
        self,
        config: WorkerConfig,
        api: httpx.Client,
        *,
        log: Callable[[str], None] = print,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ):
        self.config = config
        self.api = api
        self.log = log
        self.runner = runner
        self.claude = ""
        self.env: dict[str, str] = {}
        self.restricted = False

    def prepare(self) -> None:
        """Find Claude Code and make sure it will bill the subscription."""
        self.claude = find_claude(self.config.claude)
        self.env, removed = claude_env()
        if removed:
            self.log(f"Ignoring {', '.join(removed)} so Claude uses your subscription login.")
        method = check_subscription(auth_status(self.claude, self.env))
        self.restricted = supports_restricted(self.claude, self.env)
        self.log(f"Claude Code: {self.claude} (login: {method}"
                 f"{', restricted mode' if self.restricted else ''})")
        if not self.restricted:
            self.log("This Claude Code has no --restricted mode; update it for tighter "
                     "limits on which files Claude can touch.")

    def queue(self) -> list[dict[str, Any]]:
        response = self.api.get("/claude/queue")
        response.raise_for_status()
        return response.json()

    def _claim(self, task_id: int) -> bool:
        response = self.api.post(f"/tasks/{task_id}/claude/claim")
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    def _still_ours(self, task_id: int) -> bool:
        response = self.api.get(f"/tasks/{task_id}")
        return response.status_code == 200 and response.json().get("claude_state") == "working"

    def _finish(self, task_id: int, text: str, failed: bool) -> None:
        response = self.api.post(f"/tasks/{task_id}/claude/finish", json={
            "result": text or "(Claude gave no answer)",
            "state": "failed" if failed else "review",
        })
        if response.status_code == 409:
            self.log(f"  #{task_id} was taken back meanwhile; answer dropped.")
        else:
            response.raise_for_status()

    def run_task(self, task: dict[str, Any]) -> bool:
        """Claim and work one task. False if another worker had it first."""
        task_id = task["id"]
        if not self._claim(task_id):
            return False
        workdir = self.config.workdir / f"task-{task_id}"
        workdir.mkdir(parents=True, exist_ok=True)
        self.log(f"Working on #{task_id} {task['title']} (in {workdir})")
        with tempfile.TemporaryDirectory(prefix="todo-claude-") as tmp:
            mcp_path = Path(tmp) / "mcp.json"
            mcp_path.write_text(json.dumps(mcp_config(self.config.server_url)), encoding="utf-8")
            command = build_command(self.config, self.claude, mcp_path, self.restricted)
            prompt = PROMPT.format(task_id=task_id, workdir=workdir)
            try:
                done = self.runner(command, input=prompt, cwd=workdir, env=self.env,
                                   capture_output=True, text=True, encoding="utf-8",
                                   timeout=self.config.timeout_minutes * 60)
                result = parse_output(done.returncode, done.stdout, done.stderr)
            except subprocess.TimeoutExpired:
                result = RunResult(False, f"Stopped after {self.config.timeout_minutes} "
                                          "minutes without finishing.")
            except KeyboardInterrupt:
                self._finish(task_id, "The worker was stopped while working on this task. "
                                      "Hand it to Claude again to retry.", failed=True)
                raise
        # Claude normally hands back itself via finish_task; cover the cases it did not
        if self._still_ours(task_id):
            self._finish(task_id, result.text, failed=not result.ok)
        self.log(f"  #{task_id} {'answered' if result.ok else 'failed: ' + result.text[:200]}")
        return True

    def run_once(self) -> int:
        """Work through everything queued right now; returns how many tasks were handled."""
        handled = 0
        for task in self.queue():
            if self.run_task(task):
                handled += 1
        return handled
