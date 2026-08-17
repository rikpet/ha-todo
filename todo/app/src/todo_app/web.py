"""Server-rendered web UI (Jinja2 + HTMX partials)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from . import db

from . import __version__

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
# cache-buster for static assets: browsers cache CSS/JS across add-on updates
templates.env.globals["app_version"] = __version__


def _conn(request: Request):
    return request.app.state.db


def _norm_workspace(workspace: str) -> str:
    return workspace if workspace in db.WORKSPACES else db.WORKSPACES[0]


def _render_table(
    request: Request, workspace: str, status: str, tag: str, search: str, template: str
):
    conn = _conn(request)
    workspace = _norm_workspace(workspace)
    tasks = db.list_tasks(
        conn,
        workspace=workspace,
        status=status if status in ("open", "done") else None,
        tag=tag or None,
        search=search or None,
    )
    context = {
        "tasks": tasks,
        "open_count": sum(1 for t in tasks if t["status"] == "open"),
        "all_tags": db.allowed_tags(conn),
        "workspaces": db.WORKSPACES,
        "workspace": workspace,
        "status": status,
        "tag": tag,
        "search": search,
        "today": date.today().isoformat(),
    }
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    workspace: str = "home",
    status: str = "open",
    tag: str = "",
    search: str = "",
):
    return _render_table(request, workspace, status, tag, search, "index.html")


@router.get("/tasks/table", response_class=HTMLResponse)
def task_table(
    request: Request,
    workspace: str = "home",
    status: str = "open",
    tag: str = "",
    search: str = "",
):
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


@router.post("/tasks/new", response_class=HTMLResponse)
def create(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    tags: list[str] = Form([]),
    task_workspace: str = Form(""),
    workspace: str = Form("home"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    title = title.strip()
    if title:
        try:
            db.create_task(
                _conn(request),
                title=title,
                description=description.strip(),
                priority=priority if priority in ("low", "normal", "high") else "normal",
                due_date=due_date or None,
                tags=tags,
                # fall back to the workspace being viewed, never a fixed default
                workspace=_norm_workspace(task_workspace or workspace),
            )
        except ValueError:
            pass  # stale tag checkbox after tag removal — just re-render
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


def _task_or_404(request: Request, task_id: int) -> dict:
    task = db.get_task(_conn(request), task_id)
    if task is None:
        raise HTTPException(status_code=404)
    return task


@router.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
def toggle(
    request: Request,
    task_id: int,
    workspace: str = Form("home"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    task = _task_or_404(request, task_id)
    new_status = "open" if task["status"] == "done" else "done"
    db.update_task(_conn(request), task_id, status=new_status)
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, task_id: int):
    task = _task_or_404(request, task_id)
    return templates.TemplateResponse(
        request,
        "_task_edit.html",
        {"task": task, "all_tags": db.allowed_tags(_conn(request)), "workspaces": db.WORKSPACES},
    )


@router.post("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_save(
    request: Request,
    task_id: int,
    title: str = Form(""),
    description: str = Form(""),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    tags: list[str] = Form([]),
    task_workspace: str = Form("home"),
    workspace: str = Form("home"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    _task_or_404(request, task_id)
    try:
        db.update_task(
            _conn(request),
            task_id,
            title=title.strip() or None,
            description=description.strip(),
            priority=priority if priority in ("low", "normal", "high") else "normal",
            due_date=due_date or None,
            clear_due_date=not due_date,
            tags=tags,
            workspace=_norm_workspace(task_workspace),
        )
    except ValueError:
        pass
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


@router.post("/tasks/{task_id}/delete", response_class=HTMLResponse)
def delete(
    request: Request,
    task_id: int,
    workspace: str = Form("home"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    db.delete_task(_conn(request), task_id)
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


# ---------- tag management (responds with HX-Refresh: tag lists appear in
# several places on the page, a full reload is the simplest correct update) ----------

@router.post("/tags/new")
def tag_new(request: Request, name: str = Form("")):
    if name.strip():
        db.add_allowed_tag(_conn(request), name)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/tags/{name}/delete")
def tag_delete(request: Request, name: str):
    db.remove_allowed_tag(_conn(request), name)
    return Response(status_code=204, headers={"HX-Refresh": "true"})
