import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from todo_app import db, worker


@pytest.fixture
def api(app):
    return TestClient(app, base_url="http://testserver/api/v1")


def make_worker(api, tmp_path, runner, **config):
    w = worker.Worker(
        worker.WorkerConfig(server_url="http://pi:8099", workdir=tmp_path, **config),
        api, log=lambda _: None, runner=runner,
    )
    w.claude, w.env, w.restricted = "claude", {"PATH": "/bin"}, True
    return w


def completed(result="Done.", returncode=0, is_error=False):
    out = json.dumps({"type": "result", "is_error": is_error, "result": result})
    return subprocess.CompletedProcess([], returncode, stdout=out, stderr="")


def queued(conn, title="Compare power contracts", instructions="Fixed price only"):
    task = db.create_task(conn, title=title)
    db.give_to_claude(conn, task["id"], instructions)
    return task


# ---------- billing guard ----------

def test_claude_env_strips_api_billing_but_keeps_subscription_token():
    env, removed = worker.claude_env({
        "PATH": "/bin", "ANTHROPIC_API_KEY": "sk-ant-x", "CLAUDE_CODE_USE_BEDROCK": "1",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-x",
    })
    assert removed == ["ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK"]
    assert env == {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-x"}


@pytest.mark.parametrize("status, message", [
    ({"loggedIn": False}, "not logged in"),
    ({"loggedIn": True, "apiProvider": "bedrock", "authMethod": "x"}, "bedrock"),
    ({"loggedIn": True, "apiProvider": "firstParty", "authMethod": "api_key"}, "API key"),
    ({"loggedIn": True, "apiProvider": "firstParty", "authMethod": "apiKeyHelper"}, "API key"),
])
def test_check_subscription_refuses_non_subscription_auth(status, message):
    with pytest.raises(worker.WorkerError, match=message):
        worker.check_subscription(status)


@pytest.mark.parametrize("method", ["claude.ai", "oauth_token"])
def test_check_subscription_accepts_claude_login(method):
    status = {"loggedIn": True, "apiProvider": "firstParty", "authMethod": method}
    assert worker.check_subscription(status) == method


def test_command_never_uses_bare_and_restricts_tools(tmp_path):
    cfg = worker.WorkerConfig(server_url="http://pi:8099")
    cmd = worker.build_command(cfg, "claude", tmp_path / "mcp.json", restricted=True)
    assert "--bare" not in cmd
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    assert cmd[cmd.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")
    assert "--strict-mcp-config" in cmd and "--restricted" in cmd
    assert "Bash" in cmd[cmd.index("--tools") + 1].split(",")
    assert "mcp__todo" in cmd[cmd.index("--allowedTools") + 1].split(",")


def test_command_without_shell_commands(tmp_path):
    cfg = worker.WorkerConfig(server_url="http://pi:8099", allow_commands=False, model="sonnet")
    cmd = worker.build_command(cfg, "claude", tmp_path / "m.json", restricted=True)
    assert "Bash" not in cmd[cmd.index("--tools") + 1].split(",")
    assert "Bash" not in cmd[cmd.index("--allowedTools") + 1].split(",")
    assert cmd[-2:] == ["--model", "sonnet"]
    old = worker.build_command(cfg, "claude", tmp_path / "m.json", restricted=False)
    assert "--restricted" not in old
    assert "Bash" in old[old.index("--disallowedTools") + 1].split(",")


def test_mcp_config_runs_this_python():
    import sys

    server = worker.mcp_config("http://pi:8099")["mcpServers"]["todo"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-m", "todo_app.cli", "mcp"]
    assert server["env"] == {"TODO_URL": "http://pi:8099"}


def test_prepare_refuses_api_key_login(api, tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "find_claude", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(worker, "auth_status", lambda claude, env: {
        "loggedIn": True, "apiProvider": "firstParty", "authMethod": "api_key"})
    w = worker.Worker(worker.WorkerConfig(server_url="http://testserver"), api,
                      log=lambda _: None)
    with pytest.raises(worker.WorkerError, match="API key"):
        w.prepare()


def test_prepare_passes_a_clean_env_to_auth_check(api, monkeypatch):
    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-123")
    monkeypatch.setattr(worker, "find_claude", lambda name: "/usr/bin/claude")

    def status(claude, env):
        seen["env"] = env
        return {"loggedIn": True, "apiProvider": "firstParty", "authMethod": "claude.ai"}

    monkeypatch.setattr(worker, "auth_status", status)
    monkeypatch.setattr(worker, "supports_restricted", lambda claude, env: True)
    logs = []
    w = worker.Worker(worker.WorkerConfig(server_url="http://testserver"), api, log=logs.append)
    w.prepare()
    assert "ANTHROPIC_API_KEY" not in seen["env"] and "ANTHROPIC_API_KEY" not in w.env
    assert any("Ignoring ANTHROPIC_API_KEY" in line for line in logs)


# ---------- output parsing ----------

def test_parse_output():
    assert worker.parse_output(0, completed("All good").stdout, "") == worker.RunResult(True,
                                                                                       "All good")
    bad = worker.parse_output(1, completed("Invalid API key", 1, True).stdout, "")
    assert not bad.ok and bad.text == "Invalid API key"
    assert worker.parse_output(1, "", "claude: crashed").text == "claude: crashed"
    assert not worker.parse_output(0, "not json", "").ok


# ---------- running tasks ----------

def test_claude_hands_back_itself(conn, api, tmp_path):
    task = queued(conn)
    calls = []

    def runner(cmd, **kw):
        calls.append(kw)
        # what Claude does through the MCP server
        db.finish_for_claude(conn, task["id"], "Tibber is cheapest.")
        return completed("Handed back.")

    w = make_worker(api, tmp_path, runner)
    assert w.run_once() == 1
    [kw] = calls
    assert "task_id=" + str(task["id"]) in kw["input"]
    assert kw["cwd"] == tmp_path / f"task-{task['id']}" and kw["cwd"].is_dir()
    assert kw["env"] == {"PATH": "/bin"}
    notes = db.list_notes(conn, task["id"])
    assert [n["body"] for n in notes] == ["Fixed price only", "Tibber is cheapest."]
    assert db.get_task(conn, task["id"])["claude_state"] == "review"


def test_final_message_is_used_when_claude_did_not_hand_back(conn, api, tmp_path):
    task = queued(conn)
    w = make_worker(api, tmp_path, lambda cmd, **kw: completed("Here is the comparison."))
    w.run_once()
    assert db.get_task(conn, task["id"])["claude_state"] == "review"
    assert db.list_notes(conn, task["id"])[-1]["body"] == "Here is the comparison."


def test_failed_run_marks_task_failed(conn, api, tmp_path):
    task = queued(conn)
    w = make_worker(api, tmp_path,
                    lambda cmd, **kw: completed("Please run /login", returncode=1, is_error=True))
    w.run_once()
    assert db.get_task(conn, task["id"])["claude_state"] == "failed"
    assert "/login" in db.list_notes(conn, task["id"])[-1]["body"]


def test_timeout_marks_task_failed(conn, api, tmp_path):
    task = queued(conn)

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    make_worker(api, tmp_path, runner, timeout_minutes=5).run_once()
    assert db.get_task(conn, task["id"])["claude_state"] == "failed"
    assert "5 minutes" in db.list_notes(conn, task["id"])[-1]["body"]


def test_task_taken_back_during_run_gets_no_answer(conn, api, tmp_path):
    task = queued(conn)

    def runner(cmd, **kw):
        db.take_back_from_claude(conn, task["id"])
        return completed("Too late")

    make_worker(api, tmp_path, runner).run_once()
    assert db.get_task(conn, task["id"])["claude_state"] is None
    assert [n["author"] for n in db.list_notes(conn, task["id"])] == ["me"]


def test_already_claimed_task_is_skipped(conn, api, tmp_path):
    task = queued(conn)
    w = make_worker(api, tmp_path, lambda cmd, **kw: pytest.fail("must not run"))
    db.claim_for_claude(conn, task["id"])
    assert w.run_task(task) is False


def test_tasks_run_one_after_another(conn, api, tmp_path):
    first, second = queued(conn, "first"), queued(conn, "second")
    order = []

    def runner(cmd, **kw):
        order.append(Path(kw["cwd"]).name)
        return completed("ok")

    assert make_worker(api, tmp_path, runner).run_once() == 2
    assert order == [f"task-{first['id']}", f"task-{second['id']}"]


def test_interrupt_hands_task_back_as_failed(conn, api, tmp_path):
    task = queued(conn)

    def runner(cmd, **kw):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        make_worker(api, tmp_path, runner).run_once()
    assert db.get_task(conn, task["id"])["claude_state"] == "failed"


# ---------- one Claude account per workspace ----------

def test_claude_cannot_fetch_the_todo_api_directly(tmp_path):
    cfg = worker.WorkerConfig(server_url="http://10.150.1.89:8099")
    cmd = worker.build_command(cfg, "claude", tmp_path / "m.json", restricted=True)
    assert cmd[cmd.index("--disallowedTools") + 1] == "WebFetch(domain:10.150.1.89)"


def test_mcp_config_carries_the_workspace():
    env = worker.mcp_config("http://pi:8099", "work")["mcpServers"]["todo"]["env"]
    assert env == {"TODO_URL": "http://pi:8099", "TODO_WORKSPACE": "work"}


def test_worker_takes_only_its_workspace(conn, api, tmp_path):
    private = queued(conn, "Book dentist")
    work = db.create_task(conn, title="Sprint report", workspace="work")
    db.give_to_claude(conn, work["id"])
    ran = []

    def runner(cmd, **kw):
        ran.append(Path(kw["cwd"]).name)
        return completed("ok")

    assert make_worker(api, tmp_path, runner, workspace="work").run_once() == 1
    assert ran == [f"task-{work['id']}"]
    assert db.get_task(conn, private["id"])["claude_state"] == "queued"  # left for the other


def test_worker_refuses_a_task_from_another_workspace(conn, api, tmp_path):
    task = queued(conn)  # private
    w = make_worker(api, tmp_path, lambda cmd, **kw: pytest.fail("must not run"),
                    workspace="work")
    assert w.run_task(task) is False
    assert db.get_task(conn, task["id"])["claude_state"] == "queued"


def test_old_add_on_is_refused(api, monkeypatch):
    from fastapi.testclient import TestClient

    from todo_app import main

    monkeypatch.setattr(main, "__version__", "0.8.0")
    old = TestClient(main.create_app(), base_url="http://testserver/api/v1")
    w = worker.Worker(worker.WorkerConfig(server_url="http://testserver"), old,
                      log=lambda _: None)
    with pytest.raises(worker.WorkerError, match="version 0.8.0.*Update the add-on"):
        w.check_server()


def test_parse_version():
    assert worker.parse_version("0.10.2") > worker.parse_version("0.9.0")
    assert worker.parse_version("dev") == (0,)


def test_claude_is_told_which_task_it_was_handed(conn, api, tmp_path):
    task = queued(conn)
    seen = {}

    def runner(cmd, **kw):
        config = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text())
        seen.update(config["mcpServers"]["todo"]["env"])
        return completed("ok")

    make_worker(api, tmp_path, runner).run_once()
    assert seen["TODO_TASK_ID"] == str(task["id"])
