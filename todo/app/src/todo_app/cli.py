"""Typer CLI for the todo server. Prompts interactively for anything missing."""

from __future__ import annotations

import os
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

app = typer.Typer(help="Todo CLI — talks to the ha-todo server.", no_args_is_help=True)
console = Console()

CONFIG_PATH = Path.home() / ".config" / "todo" / "config.toml"
PRIORITIES = ["low", "normal", "high"]


def _safe(char: str, fallback: str) -> str:
    """Fall back to ASCII on consoles that cannot encode unicode (e.g. cp1252)."""
    try:
        char.encode(sys.stdout.encoding or "utf-8")
        return char
    except (UnicodeEncodeError, LookupError):
        return fallback


CHECK = _safe("✓", "+")
CROSS = _safe("✗", "x")
DONE_MARK = _safe("✔", "x")


# ---------- config / client ----------

def load_config() -> dict:
    config: dict = {}
    if CONFIG_PATH.exists():
        config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if os.environ.get("TODO_URL"):
        config["url"] = os.environ["TODO_URL"]
    return config


def save_config(url: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(f'url = "{url}"\n', encoding="utf-8")


def client() -> httpx.Client:
    config = load_config()
    url = config.get("url")
    if not url:
        _fail("No server configured. Run [bold]todo config[/bold] first.")
    return httpx.Client(base_url=f"{url.rstrip('/')}/api/v1", timeout=10)


def _fail(message: str) -> None:
    console.print(f"[red]{CROSS}[/red] {message}")
    raise typer.Exit(code=1)


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def request(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        with client() as c:
            response = c.request(method, path, **kwargs)
    except httpx.ConnectError:
        _fail(f"Cannot reach server at {load_config().get('url')}. Is the add-on running?")
    if response.status_code == 404:
        _fail("Task not found.")
    if response.is_error:
        _fail(f"Server error {response.status_code}: {response.text}")
    return response


# ---------- helpers ----------

def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def _validate_due(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(f"Invalid date '{value}' — use YYYY-MM-DD.")
    return value


def _task_table(tasks: list[dict], title: str = "") -> Table:
    table = Table(title=title or None, header_style="bold")
    table.add_column("ID", justify="right", style="cyan")
    table.add_column("", width=2)
    table.add_column("Title")
    table.add_column("Due")
    table.add_column("Prio")
    table.add_column("Tags")
    today = date.today().isoformat()
    for t in tasks:
        done = t["status"] == "done"
        overdue = not done and t["due_date"] and t["due_date"] < today
        prio_style = {"high": "red", "low": "dim"}.get(t["priority"], "")
        table.add_row(
            str(t["id"]),
            DONE_MARK if done else "",
            f"[dim strike]{t['title']}[/dim strike]" if done else t["title"],
            f"[red bold]{t['due_date']}[/red bold]" if overdue else (t["due_date"] or ""),
            f"[{prio_style}]{t['priority']}[/{prio_style}]" if prio_style else t["priority"],
            ", ".join(t["tags"]),
        )
    return table


def _pick_task_id(action: str, status: str | None = "open") -> int:
    """When no id was given: list tasks and prompt for a pick (TTY only)."""
    if not _interactive():
        _fail(f"Missing task id. Usage: todo {action} <id>")
    params = {"status": status} if status else {}
    tasks = request("GET", "/tasks", params=params).json()
    if not tasks:
        _fail("No matching tasks.")
    console.print(_task_table(tasks))
    valid = {str(t["id"]) for t in tasks}
    choice = Prompt.ask(f"Which task do you want to {action}?", choices=sorted(valid, key=int))
    return int(choice)


def _show_task(t: dict) -> None:
    console.print(f"[bold cyan]#{t['id']}[/bold cyan] [bold]{t['title']}[/bold]")
    console.print(f"  status:   {t['status']}")
    console.print(f"  priority: {t['priority']}")
    console.print(f"  due:      {t['due_date'] or '-'}")
    console.print(f"  tags:     {', '.join(t['tags']) or '-'}")
    if t["description"]:
        console.print(f"  notes:    {t['description']}")
    console.print(f"  created:  {t['created_at']}")
    if t["completed_at"]:
        console.print(f"  done at:  {t['completed_at']}")


# ---------- commands ----------

@app.command()
def config(
    url: Optional[str] = typer.Option(None, "--url", help="Server URL, e.g. http://pi:8099"),
):
    """Configure the server URL (prompts if omitted)."""
    existing = load_config()
    if url is None:
        if not _interactive():
            _fail("Missing --url (non-interactive shell).")
        url = Prompt.ask("Server URL", default=existing.get("url", "http://homeassistant.local:8099"))
    save_config(url)
    console.print(f"[green]{CHECK}[/green] Saved to {CONFIG_PATH}")
    try:
        with client() as c:
            c.get("/tasks")
        console.print(f"[green]{CHECK}[/green] Server reachable.")
    except httpx.HTTPError:
        console.print("[yellow]![/yellow] Could not reach the server (saved anyway).")


@app.command()
def add(
    title: Optional[str] = typer.Argument(None, help="Task title"),
    due: Optional[str] = typer.Option(None, "--due", help="Due date YYYY-MM-DD"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Repeatable"),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
):
    """Add a task. With no arguments, prompts for everything."""
    prompted = title is None
    if title is None:
        if not _interactive():
            _fail('Missing title. Usage: todo add "Buy milk"')
        title = Prompt.ask("Title")
        if not title.strip():
            _fail("Title cannot be empty.")
    if prompted and due is None:
        due = Prompt.ask("Due date (YYYY-MM-DD, Enter to skip)", default="") or None
    if prompted and priority is None:
        priority = Prompt.ask("Priority", choices=PRIORITIES, default="normal")
    tags = [t for raw in tag for t in _parse_tags(raw)]
    if prompted and not tags:
        tags = _parse_tags(Prompt.ask("Tags (comma separated, Enter to skip)", default=""))
    if prompted and description is None:
        description = Prompt.ask("Description (Enter to skip)", default="")
    if due:
        _validate_due(due)
    payload = {
        "title": title.strip(),
        "due_date": due,
        "priority": priority or "normal",
        "tags": tags,
        "description": description or "",
    }
    task = request("POST", "/tasks", json=payload).json()
    console.print(f"[green]{CHECK}[/green] Added [cyan]#{task['id']}[/cyan] {task['title']}")


@app.command("list")
def list_cmd(
    all_: bool = typer.Option(False, "--all", "-a", help="Include done tasks"),
    done: bool = typer.Option(False, "--done", help="Only done tasks"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t"),
    search: Optional[str] = typer.Option(None, "--search", "-s"),
):
    """List tasks (open by default)."""
    params: dict = {}
    if done:
        params["status"] = "done"
    elif not all_:
        params["status"] = "open"
    if tag:
        params["tag"] = tag
    if search:
        params["search"] = search
    tasks = request("GET", "/tasks", params=params).json()
    if not tasks:
        console.print("[dim]No tasks.[/dim]")
        return
    console.print(_task_table(tasks))


@app.command()
def show(task_id: Optional[int] = typer.Argument(None, metavar="ID")):
    """Show one task in full."""
    if task_id is None:
        task_id = _pick_task_id("show", status=None)
    _show_task(request("GET", f"/tasks/{task_id}").json())


@app.command()
def edit(
    task_id: Optional[int] = typer.Argument(None, metavar="ID"),
    title: Optional[str] = typer.Option(None, "--title"),
    due: Optional[str] = typer.Option(None, "--due", help="YYYY-MM-DD, or '' to clear"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma separated, replaces all"),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
):
    """Edit a task. With no flags, walks through every field interactively."""
    if task_id is None:
        task_id = _pick_task_id("edit", status=None)
    no_flags = all(v is None for v in (title, due, priority, tags, description))
    if no_flags:
        if not _interactive():
            _fail("No changes given. Use --title/--due/--priority/--tags/--desc.")
        current = request("GET", f"/tasks/{task_id}").json()
        title = Prompt.ask("Title", default=current["title"])
        due = Prompt.ask("Due date (YYYY-MM-DD, '-' to clear)", default=current["due_date"] or "")
        if due == "-":
            due = ""
        priority = Prompt.ask("Priority", choices=PRIORITIES, default=current["priority"])
        tags = Prompt.ask("Tags (comma separated)", default=", ".join(current["tags"]))
        description = Prompt.ask("Description", default=current["description"])
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if due is not None:
        if due == "":
            payload["clear_due_date"] = True
        else:
            payload["due_date"] = _validate_due(due)
    if priority is not None:
        if priority not in PRIORITIES:
            _fail(f"Priority must be one of: {', '.join(PRIORITIES)}")
        payload["priority"] = priority
    if tags is not None:
        payload["tags"] = _parse_tags(tags)
    if description is not None:
        payload["description"] = description
    task = request("PATCH", f"/tasks/{task_id}", json=payload).json()
    console.print(f"[green]{CHECK}[/green] Updated [cyan]#{task['id']}[/cyan]")
    _show_task(task)


@app.command()
def done(task_ids: Optional[list[int]] = typer.Argument(None, metavar="ID...")):
    """Mark task(s) as done."""
    if not task_ids:
        task_ids = [_pick_task_id("complete")]
    for task_id in task_ids:
        task = request("POST", f"/tasks/{task_id}/complete").json()
        console.print(f"[green]{CHECK}[/green] Done: [cyan]#{task['id']}[/cyan] {task['title']}")


@app.command()
def reopen(task_ids: Optional[list[int]] = typer.Argument(None, metavar="ID...")):
    """Reopen completed task(s)."""
    if not task_ids:
        task_ids = [_pick_task_id("reopen", status="done")]
    for task_id in task_ids:
        task = request("POST", f"/tasks/{task_id}/reopen").json()
        console.print(f"[green]{CHECK}[/green] Reopened: [cyan]#{task['id']}[/cyan] {task['title']}")


@app.command()
def rm(
    task_ids: Optional[list[int]] = typer.Argument(None, metavar="ID..."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove task(s)."""
    if not task_ids:
        task_ids = [_pick_task_id("remove", status=None)]
    for task_id in task_ids:
        task = request("GET", f"/tasks/{task_id}").json()
        if not yes:
            if not _interactive():
                _fail("Refusing to delete without --yes in a non-interactive shell.")
            if not Confirm.ask(f"Delete [cyan]#{task['id']}[/cyan] “{task['title']}”?"):
                continue
        request("DELETE", f"/tasks/{task_id}")
        console.print(f"[green]{CHECK}[/green] Removed [cyan]#{task_id}[/cyan]")


@app.command()
def tags():
    """List all tags in use."""
    for t in request("GET", "/tags").json():
        console.print(f"#{t}")


if __name__ == "__main__":
    app()
