import json

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from todo_app.cli import app

runner = CliRunner()
BASE = "http://pi:8099/api/v1"

TASK = {
    "id": 1, "title": "Buy milk", "description": "", "status": "open",
    "priority": "normal", "due_date": None, "tags": ["home"], "workspace": "home",
    "created_at": "2026-08-04T10:00:00+00:00", "updated_at": "2026-08-04T10:00:00+00:00",
    "completed_at": None,
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TODO_URL", "http://pi:8099")


@respx.mock
def test_add_with_args():
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["home"]))
    route = respx.post(f"{BASE}/tasks").mock(return_value=Response(201, json=TASK))
    result = runner.invoke(app, ["add", "Buy milk", "--tag", "home"])
    assert result.exit_code == 0
    assert "Added" in result.output
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "Buy milk"
    assert body["tags"] == ["home"]
    assert body["workspace"] == "work"  # CLI defaults to the work workspace


@respx.mock
def test_add_home_workspace_override():
    route = respx.post(f"{BASE}/tasks").mock(
        return_value=Response(201, json={**TASK, "tags": []})
    )
    result = runner.invoke(app, ["add", "Water plants", "-w", "home"])
    assert result.exit_code == 0
    assert json.loads(route.calls[0].request.content)["workspace"] == "home"


@respx.mock
def test_add_unknown_tag_fails():
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["home"]))
    result = runner.invoke(app, ["add", "X", "--tag", "random"])
    assert result.exit_code == 1
    assert "Unknown tag" in result.output


def test_add_missing_title_non_interactive():
    # CliRunner stdin is not a TTY → must fail with usage hint, not hang
    result = runner.invoke(app, ["add"])
    assert result.exit_code == 1
    assert "Missing title" in result.output


def test_add_bad_workspace():
    result = runner.invoke(app, ["add", "X", "-w", "garage"])
    assert result.exit_code == 1
    assert "Workspace" in result.output


@respx.mock
def test_list():
    respx.get(f"{BASE}/tasks", params={"status": "open"}).mock(
        return_value=Response(200, json=[TASK])
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Buy milk" in result.output


@respx.mock
def test_list_workspace_filter():
    route = respx.get(f"{BASE}/tasks", params={"status": "open", "workspace": "work"}).mock(
        return_value=Response(200, json=[])
    )
    result = runner.invoke(app, ["list", "-w", "work"])
    assert result.exit_code == 0
    assert route.called


@respx.mock
def test_done():
    respx.post(f"{BASE}/tasks/1/complete").mock(
        return_value=Response(200, json={**TASK, "status": "done"})
    )
    result = runner.invoke(app, ["done", "1"])
    assert result.exit_code == 0
    assert "Done" in result.output


@respx.mock
def test_edit_with_flags():
    respx.patch(f"{BASE}/tasks/1").mock(
        return_value=Response(200, json={**TASK, "title": "New"})
    )
    result = runner.invoke(app, ["edit", "1", "--title", "New", "--due", ""])
    assert result.exit_code == 0
    assert "Updated" in result.output


@respx.mock
def test_edit_move_workspace():
    route = respx.patch(f"{BASE}/tasks/1").mock(
        return_value=Response(200, json={**TASK, "workspace": "work"})
    )
    result = runner.invoke(app, ["edit", "1", "-w", "work"])
    assert result.exit_code == 0
    assert json.loads(route.calls[0].request.content)["workspace"] == "work"


@respx.mock
def test_rm_requires_yes_non_interactive():
    respx.get(f"{BASE}/tasks/1").mock(return_value=Response(200, json=TASK))
    result = runner.invoke(app, ["rm", "1"])
    assert result.exit_code == 1
    assert "--yes" in result.output


@respx.mock
def test_rm_with_yes():
    respx.get(f"{BASE}/tasks/1").mock(return_value=Response(200, json=TASK))
    respx.delete(f"{BASE}/tasks/1").mock(return_value=Response(204))
    result = runner.invoke(app, ["rm", "1", "--yes"])
    assert result.exit_code == 0
    assert "Removed" in result.output


@respx.mock
def test_tags_list():
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["home", "work"]))
    result = runner.invoke(app, ["tags"])
    assert result.exit_code == 0
    assert "#home" in result.output
    assert "#work" in result.output


@respx.mock
def test_tags_add_and_rm():
    add_route = respx.post(f"{BASE}/tags").mock(return_value=Response(201, json=["x"]))
    rm_route = respx.delete(f"{BASE}/tags/x").mock(return_value=Response(204))
    assert runner.invoke(app, ["tags", "add", "x"]).exit_code == 0
    assert add_route.called
    assert runner.invoke(app, ["tags", "rm", "x"]).exit_code == 0
    assert rm_route.called


def test_no_config(monkeypatch):
    monkeypatch.delenv("TODO_URL")
    monkeypatch.setattr("todo_app.cli.CONFIG_PATH", __import__("pathlib").Path("nonexistent.toml"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "todo config" in result.output
