"""MCP server (stdio) that lets Claude read and answer the tasks handed to it.

Run by `todo mcp`, or by the Claude worker for each task. It talks to the
add-on's REST API, so it runs wherever the CLI runs - a Raspberry Pi, a
Windows laptop - and needs no extra packages: the protocol is newline-delimited
JSON-RPC 2.0 over stdin/stdout, and only the tools part of MCP is used.
"""

from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO, Callable

import httpx

from . import __version__

# newest first; we answer with the client's version when we know it
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "Tools for the user's todo list (ha-todo). Tasks the user handed to Claude have a "
    "claude_state: queued (waiting), working, review (answered, waiting for the user) or "
    "failed. To work on one: get_task to read it and its note thread (the user's "
    "instructions and earlier answers), start_task if it is still queued, do the work, then "
    "finish_task with your answer. Never mark tasks done - the user does that after review."
)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [],
            "additionalProperties": False}


TASK_ID = {"type": "integer", "description": "The task's id"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_claude_tasks",
        "description": "List tasks the user has handed to Claude, oldest hand-over first.",
        "inputSchema": _schema({
            "state": {"type": "string", "enum": ["queued", "working", "review", "failed", "any"],
                      "description": "Which hand-overs to list (default: queued)"},
        }),
    },
    {
        "name": "get_task",
        "description": "Read one task with its full note thread (instructions and answers).",
        "inputSchema": _schema({"task_id": TASK_ID}, ["task_id"]),
    },
    {
        "name": "start_task",
        "description": "Mark a queued task as being worked on by Claude. Fails if another "
                       "worker already took it - then leave that task alone.",
        "inputSchema": _schema({"task_id": TASK_ID}, ["task_id"]),
    },
    {
        "name": "post_progress",
        "description": "Add a short progress note to a task's thread without handing it back.",
        "inputSchema": _schema({"task_id": TASK_ID, "text": {"type": "string"}},
                               ["task_id", "text"]),
    },
    {
        "name": "finish_task",
        "description": "Hand the task back to the user with your answer (Markdown). The task "
                       "then waits for their review. Set failed=true if you could not do it, "
                       "and explain why in result.",
        "inputSchema": _schema({
            "task_id": TASK_ID,
            "result": {"type": "string", "description": "Your answer or report for the user"},
            "failed": {"type": "boolean", "description": "True if the task could not be done"},
        }, ["task_id", "result"]),
    },
    {
        "name": "create_task",
        "description": "Create a new task for the user, e.g. a follow-up step you suggest. "
                       "Tags must be ones that exist (see list_tags).",
        "inputSchema": _schema({
            "title": {"type": "string"},
            "description": {"type": "string"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "workspace": {"type": "string", "enum": ["private", "work"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        }, ["title"]),
    },
    {
        "name": "search_tasks",
        "description": "Search the user's tasks by text, for context.",
        "inputSchema": _schema({
            "search": {"type": "string"},
            "status": {"type": "string", "enum": ["open", "done"]},
            "workspace": {"type": "string", "enum": ["private", "work"]},
        }),
    },
    {
        "name": "list_tags",
        "description": "The tags configured in the todo app.",
        "inputSchema": _schema({}),
    },
]


class ToolError(Exception):
    """Reported back to Claude as a tool result with isError set."""


def _call(client: httpx.Client, method: str, path: str, **kwargs) -> Any:
    try:
        response = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise ToolError(f"Cannot reach the todo server: {exc}") from exc
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ToolError(f"{response.status_code}: {detail}")
    return response.json() if response.content else None


def _compact(task: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "title", "status", "priority", "due_date", "tags", "workspace",
            "claude_state", "created_at")
    return {k: task.get(k) for k in keys}


def run_tool(client: httpx.Client, name: str, args: dict[str, Any]) -> Any:
    if name == "list_claude_tasks":
        state = args.get("state") or "queued"
        if state == "queued":
            tasks = _call(client, "GET", "/claude/queue")
        else:
            tasks = _call(client, "GET", "/tasks", params={"claude": state, "status": "open"})
        return [_compact(t) for t in tasks]
    if name == "get_task":
        task_id = int(args["task_id"])
        task = _call(client, "GET", f"/tasks/{task_id}")
        task["notes"] = [
            {"author": n["author"], "at": n["created_at"], "text": n["body"]}
            for n in _call(client, "GET", f"/tasks/{task_id}/notes")
        ]
        return task
    if name == "start_task":
        return _compact(_call(client, "POST", f"/tasks/{int(args['task_id'])}/claude/claim"))
    if name == "post_progress":
        _call(client, "POST", f"/tasks/{int(args['task_id'])}/notes",
              json={"author": "claude", "body": args["text"]})
        return "Noted."
    if name == "finish_task":
        state = "failed" if args.get("failed") else "review"
        task = _call(client, "POST", f"/tasks/{int(args['task_id'])}/claude/finish",
                     json={"result": args["result"], "state": state})
        return f"Handed back to the user (state: {task['claude_state']})."
    if name == "create_task":
        payload = {k: args[k] for k in ("title", "description", "due_date", "priority",
                                        "workspace", "tags") if args.get(k) not in (None, "")}
        return _compact(_call(client, "POST", "/tasks", json=payload))
    if name == "search_tasks":
        params = {k: args[k] for k in ("search", "status", "workspace") if args.get(k)}
        return [_compact(t) for t in _call(client, "GET", "/tasks", params=params)][:50]
    if name == "list_tags":
        return _call(client, "GET", "/tags")
    raise ToolError(f"Unknown tool: {name}")


def handle(client: httpx.Client, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, the response out (None for notifications)."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:  # a notification (notifications/initialized and friends)
        return None

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return ok({
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ha-todo", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = run_tool(client, params.get("name", ""), params.get("arguments") or {})
        except (ToolError, KeyError, ValueError, TypeError) as exc:
            text = str(exc) if isinstance(exc, ToolError) else f"Bad arguments: {exc!r}"
            return ok({"content": [{"type": "text", "text": text}], "isError": True})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                                 indent=1)
        return ok({"content": [{"type": "text", "text": text}]})
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(
    client: httpx.Client,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    log: Callable[[str], None] = lambda text: print(text, file=sys.stderr, flush=True),
) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for raw in stdin:
        if not raw.strip():
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "Parse error"}}
        else:
            if isinstance(message, list):  # batches are not used by Claude; answer each
                replies = [r for m in message if (r := handle(client, m))]
                reply = replies or None
            else:
                reply = handle(client, message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    log("ha-todo MCP server: stdin closed, exiting")


def main(base_url: str) -> None:
    with httpx.Client(base_url=f"{base_url}/api/v1", timeout=30) as client:
        serve(client)
