import io
import json

import pytest
from fastapi.testclient import TestClient

from todo_app import db, mcp_server


@pytest.fixture
def api(app):
    return TestClient(app, base_url="http://testserver/api/v1")


def rpc(api, *messages):
    """Feed messages through serve() and return the decoded replies."""
    stdin = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
    stdout = io.BytesIO()
    mcp_server.serve(api, stdin, stdout, log=lambda _: None)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def call(api, name, **arguments):
    [reply] = rpc(api, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}})
    return reply["result"]


def text(result):
    return result["content"][0]["text"]


def test_handshake_and_tool_list(api):
    replies = rpc(
        api,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "claude-code", "version": "2"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    )
    assert [r["id"] for r in replies] == [1, 2, 3]  # no reply to the notification
    init = replies[0]["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["capabilities"] == {"tools": {}}
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"list_claude_tasks", "get_task", "start_task", "finish_task", "create_task"} <= names
    assert replies[2]["result"] == {}


def test_unknown_protocol_version_gets_ours(api):
    [reply] = rpc(api, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "1999-01-01"}})
    assert reply["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]


def test_unknown_method_and_bad_json(api):
    stdin = io.BytesIO(b"not json\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}).encode() + b"\n")
    stdout = io.BytesIO()
    mcp_server.serve(api, stdin, stdout, log=lambda _: None)
    parse_error, not_found = [json.loads(x) for x in stdout.getvalue().splitlines()]
    assert parse_error["error"]["code"] == -32700
    assert not_found["id"] == 7 and not_found["error"]["code"] == -32601


def test_full_hand_over_through_tools(conn, api):
    task = db.create_task(conn, title="Compare power contracts")
    db.give_to_claude(conn, task["id"], "Fixed price only")

    queue = json.loads(text(call(api, "list_claude_tasks")))
    assert [t["id"] for t in queue] == [task["id"]]

    detail = json.loads(text(call(api, "get_task", task_id=task["id"])))
    assert detail["notes"][0]["text"] == "Fixed price only"
    assert detail["notes"][0]["author"] == "me"

    assert json.loads(text(call(api, "start_task", task_id=task["id"])))["claude_state"] == "working"
    second = call(api, "start_task", task_id=task["id"])
    assert second["isError"] and "not waiting" in text(second)

    call(api, "post_progress", task_id=task["id"], text="Looking at 4 suppliers")
    result = call(api, "finish_task", task_id=task["id"], result="**Tibber** wins.")
    assert "review" in text(result)
    notes = db.list_notes(conn, task["id"])
    assert [n["body"] for n in notes] == ["Fixed price only", "Looking at 4 suppliers",
                                          "**Tibber** wins."]
    assert db.get_task(conn, task["id"])["status"] == "open"

    review = json.loads(text(call(api, "list_claude_tasks", state="review")))
    assert [t["id"] for t in review] == [task["id"]]


def test_finish_failed(conn, api):
    task = db.create_task(conn, title="x")
    db.give_to_claude(conn, task["id"])
    call(api, "finish_task", task_id=task["id"], result="No login to that site", failed=True)
    assert db.get_task(conn, task["id"])["claude_state"] == "failed"


def test_create_and_search(conn, api):
    db.add_allowed_tag(conn, "hushall")
    created = json.loads(text(call(api, "create_task", title="Call Tibber", tags=["hushall"],
                                   due_date="2026-12-01", description="")))
    assert created["tags"] == ["hushall"] and created["due_date"] == "2026-12-01"
    bad = call(api, "create_task", title="x", tags=["nope"])
    assert bad["isError"] and "Unknown tag" in text(bad)
    found = json.loads(text(call(api, "search_tasks", search="tibber")))
    assert [t["title"] for t in found] == ["Call Tibber"]
    assert json.loads(text(call(api, "list_tags"))) == ["hushall"]


def test_tool_errors_are_results_not_crashes(api):
    assert call(api, "get_task", task_id=404)["isError"]
    assert call(api, "get_task")["isError"]  # missing argument
    assert call(api, "no_such_tool")["isError"]


def test_unreachable_server_is_a_tool_error():
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:9/api/v1", timeout=2) as dead:
        result = call(dead, "list_tags")
    assert result["isError"] and "Cannot reach" in text(result)
