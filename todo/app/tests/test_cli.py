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
    "priority": "normal", "due_date": None, "tags": ["private"], "workspace": "private",
    "created_at": "2026-08-04T10:00:00+00:00", "updated_at": "2026-08-04T10:00:00+00:00",
    "completed_at": None,
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TODO_URL", "http://pi:8099")


@respx.mock
def test_add_with_args():
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["private"]))
    route = respx.post(f"{BASE}/tasks").mock(return_value=Response(201, json=TASK))
    result = runner.invoke(app, ["add", "Buy milk", "--tag", "private"])
    assert result.exit_code == 0
    assert "Added" in result.output
    body = json.loads(route.calls[0].request.content)
    assert body["title"] == "Buy milk"
    assert body["tags"] == ["private"]
    assert body["workspace"] == "work"  # CLI defaults to the work workspace


@respx.mock
def test_add_private_workspace_override():
    route = respx.post(f"{BASE}/tasks").mock(
        return_value=Response(201, json={**TASK, "tags": []})
    )
    result = runner.invoke(app, ["add", "Water plants", "-w", "private"])
    assert result.exit_code == 0
    assert json.loads(route.calls[0].request.content)["workspace"] == "private"


@respx.mock
def test_add_unknown_tag_fails():
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["private"]))
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
    respx.get(f"{BASE}/tags").mock(return_value=Response(200, json=["errands", "work"]))
    result = runner.invoke(app, ["tags"])
    assert result.exit_code == 0
    assert "#errands" in result.output
    assert "#work" in result.output


@respx.mock
def test_tags_add_and_rm():
    add_route = respx.post(f"{BASE}/tags").mock(return_value=Response(201, json=["x"]))
    rm_route = respx.delete(f"{BASE}/tags/x").mock(return_value=Response(204))
    assert runner.invoke(app, ["tags", "add", "x"]).exit_code == 0
    assert add_route.called
    assert runner.invoke(app, ["tags", "rm", "x"]).exit_code == 0
    assert rm_route.called


@respx.mock
def test_version_flag_shows_cli_and_server():
    from todo_app import __version__

    respx.get("http://pi:8099/health").mock(
        return_value=Response(200, json={"status": "ok", "version": __version__})
    )
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
    assert "server" in result.output


@respx.mock
def test_version_flag_flags_mismatch():
    respx.get("http://pi:8099/health").mock(
        return_value=Response(200, json={"status": "ok", "version": "0.0.1"})
    )
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "mismatch" in result.output


@respx.mock
def test_version_flag_survives_unreachable_server():
    respx.get("http://pi:8099/health").mock(side_effect=__import__("httpx").ConnectError("nope"))
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "unreachable" in result.output


@respx.mock
@pytest.mark.parametrize(
    "error",
    [
        __import__("httpx").ConnectError("refused"),
        __import__("httpx").ConnectTimeout("timed out"),
        __import__("httpx").ReadTimeout("slow"),
    ],
)
def test_unreachable_server_gives_a_message_not_a_traceback(error):
    respx.get(f"{BASE}/tasks", params={"status": "open"}).mock(side_effect=error)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Cannot reach the todo server" in result.output
    assert "Traceback" not in result.output


def test_url_without_scheme_is_accepted(monkeypatch):
    from todo_app.cli import normalize_url

    assert normalize_url("10.150.1.89:8099") == "http://10.150.1.89:8099"
    assert normalize_url("http://pi:8099/") == "http://pi:8099"
    assert normalize_url("https://pi:8099") == "https://pi:8099"


@respx.mock
def test_bare_host_config_still_talks_to_the_server(monkeypatch):
    monkeypatch.setenv("TODO_URL", "pi:8099")  # no scheme
    respx.get(f"{BASE}/tasks", params={"status": "open"}).mock(
        return_value=Response(200, json=[TASK])
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Buy milk" in result.output


def test_no_config(monkeypatch):
    monkeypatch.delenv("TODO_URL")
    monkeypatch.setattr("todo_app.cli.CONFIG_PATH", __import__("pathlib").Path("nonexistent.toml"))
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "todo config" in result.output


# ---------- self-upgrade ----------

def test_upgrade_check_reports_versions(tmp_path, monkeypatch):
    """--check compares the installed version against the source, installing nothing."""
    from todo_app import __version__, cli

    src = tmp_path / "app"
    src.mkdir()
    (src / "pyproject.toml").write_text('[project]\nname = "ha-todo"\nversion = "9.9.9"\n')
    monkeypatch.setattr(cli, "_pipx_source", lambda: str(src))
    called = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: called.append(a) or None)

    result = runner.invoke(app, ["upgrade", "--check", "--no-pull"])
    assert result.exit_code == 0
    assert __version__ in result.output
    assert "9.9.9" in result.output
    assert called == []  # nothing installed


def test_upgrade_skips_when_current(tmp_path, monkeypatch):
    from todo_app import __version__, cli

    src = tmp_path / "app"
    src.mkdir()
    (src / "pyproject.toml").write_text(f'[project]\nversion = "{__version__}"\n')
    monkeypatch.setattr(cli, "_pipx_source", lambda: str(src))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "pipx")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: calls.append(a))

    result = runner.invoke(app, ["upgrade", "--no-pull"])
    assert result.exit_code == 0
    assert "Already up to date" in result.output
    assert calls == []


def test_upgrade_without_pipx_metadata_explains(monkeypatch):
    from todo_app import cli

    monkeypatch.setattr(cli, "_pipx_source", lambda: None)
    result = runner.invoke(app, ["upgrade"])
    assert result.exit_code == 1
    assert "pipx install --force" in result.output


def test_upgrade_reports_failure_with_manual_fallback(tmp_path, monkeypatch):
    """A locked executable must produce advice, not a traceback."""
    from todo_app import cli

    src = tmp_path / "app"
    src.mkdir()
    (src / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')
    monkeypatch.setattr(cli, "_pipx_source", lambda: str(src))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "pipx")

    class Failed:
        returncode = 1
        stderr = "PermissionError: [WinError 5] Access is denied"
        stdout = ""

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: Failed())
    result = runner.invoke(app, ["upgrade", "--no-pull"])
    assert result.exit_code == 1
    assert "Upgrade failed" in result.output
    assert "where todo is not running" in result.output
