"""Server-rendered web UI (Jinja2 + HTMX partials)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import db
from .auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _conn(request: Request):
    return request.app.state.db


def _parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def _render_table(request: Request, status: str, tag: str, search: str, template: str):
    conn = _conn(request)
    tasks = db.list_tasks(
        conn,
        status=status if status in ("open", "done") else None,
        tag=tag or None,
        search=search or None,
    )
    context = {
        "tasks": tasks,
        "open_count": sum(1 for t in tasks if t["status"] == "open"),
        "all_tags": db.all_tags(conn),
        "status": status,
        "tag": tag,
        "search": search,
        "today": date.today().isoformat(),
    }
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, status: str = "all", tag: str = "", search: str = ""):
    return _render_table(request, status, tag, search, "index.html")


@router.get("/tasks/table", response_class=HTMLResponse)
def task_table(request: Request, status: str = "all", tag: str = "", search: str = ""):
    return _render_table(request, status, tag, search, "_task_table.html")


@router.post("/tasks/new", response_class=HTMLResponse)
def create(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    tags: str = Form(""),
    status: str = Form("all"),
    tag: str = Form(""),
    search: str = Form(""),
):
    title = title.strip()
    if title:
        db.create_task(
            _conn(request),
            title=title,
            description=description.strip(),
            priority=priority if priority in ("low", "normal", "high") else "normal",
            due_date=due_date or None,
            tags=_parse_tags(tags),
        )
    return _render_table(request, status, tag, search, "_task_table.html")


def _task_or_404(request: Request, task_id: int) -> dict:
    task = db.get_task(_conn(request), task_id)
    if task is None:
        raise HTTPException(status_code=404)
    return task


@router.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
def toggle(
    request: Request,
    task_id: int,
    status: str = Form("all"),
    tag: str = Form(""),
    search: str = Form(""),
):
    task = _task_or_404(request, task_id)
    new_status = "open" if task["status"] == "done" else "done"
    db.update_task(_conn(request), task_id, status=new_status)
    return _render_table(request, status, tag, search, "_task_table.html")


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, task_id: int):
    task = _task_or_404(request, task_id)
    return templates.TemplateResponse(request, "_task_edit.html", {"task": task})


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_save(
    request: Request,
    task_id: int,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    tags: str = Form(""),
    status: str = Form("all"),
    tag: str = Form(""),
    search: str = Form(""),
):
    _task_or_404(request, task_id)
    db.update_task(
        _conn(request),
        task_id,
        title=title.strip() or None,
        description=description.strip(),
        priority=priority if priority in ("low", "normal", "high") else "normal",
        due_date=due_date or None,
        clear_due_date=not due_date,
        tags=_parse_tags(tags),
    )
    return _render_table(request, status, tag, search, "_task_table.html")


@router.post("/tasks/{task_id}/delete", response_class=HTMLResponse)
def delete(
    request: Request,
    task_id: int,
    status: str = Form("all"),
    tag: str = Form(""),
    search: str = Form(""),
):
    db.delete_task(_conn(request), task_id)
    return _render_table(request, status, tag, search, "_task_table.html")
