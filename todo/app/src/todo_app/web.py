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


MY_DAY = "myday"
VIEWS = (MY_DAY,) + db.WORKSPACES


def _norm_workspace(workspace: str) -> str:
    """A real workspace to file a task in - never the My Day pseudo-view."""
    return workspace if workspace in db.WORKSPACES else db.WORKSPACES[0]


def _norm_view(view: str) -> str:
    return view if view in VIEWS else db.WORKSPACES[0]


def _render_table(
    request: Request, workspace: str, status: str, tag: str, search: str, template: str
):
    conn = _conn(request)
    view = _norm_view(workspace)
    today = db.today_iso()
    if view == MY_DAY:
        # My Day spans both workspaces; its membership rules replace the
        # status filter, but text/tag search still narrow the list.
        tasks = db.list_my_day(conn, today)
        if tag:
            tasks = [t for t in tasks if tag in t["tags"]]
        if search:
            needle = search.lower()
            tasks = [
                t for t in tasks
                if needle in t["title"].lower() or needle in t["description"].lower()
            ]
    else:
        tasks = db.list_tasks(
            conn,
            workspace=view,
            status=status if status in ("open", "done") else None,
            tag=tag or None,
            search=search or None,
        )
    context = {
        "tasks": tasks,
        "open_count": sum(1 for t in tasks if t["status"] == "open"),
        "late_count": sum(1 for t in tasks if db.is_late(t, today)),
        "all_tags": db.allowed_tags(conn),
        "workspaces": db.WORKSPACES,
        "views": VIEWS,
        "my_day": MY_DAY,
        "workspace": view,
        "is_my_day": view == MY_DAY,
        "status": status,
        "tag": tag,
        "search": search,
        "today": today,
        "recurring": db.list_recurring(conn, workspace=None if view == MY_DAY else view),
        "weekday_names": db.WEEKDAY_NAMES,
        "describe": db.describe_recurring,
        "is_late": db.is_late,
        "is_carried_over": db.is_carried_over,
        "in_my_day": db.in_my_day,
    }
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    workspace: str = "private",
    status: str = "open",
    tag: str = "",
    search: str = "",
):
    return _render_table(request, workspace, status, tag, search, "index.html")


@router.get("/tasks/table", response_class=HTMLResponse)
def task_table(
    request: Request,
    workspace: str = "private",
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
    workspace: str = Form("private"),
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
                # typed while looking at My Day -> it is for today
                planned_for=db.today_iso() if _norm_view(workspace) == MY_DAY else None,
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
    workspace: str = Form("private"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    task = _task_or_404(request, task_id)
    new_status = "open" if task["status"] == "done" else "done"
    db.update_task(_conn(request), task_id, status=new_status)
    return _render_table(request, workspace, status, tag, search, "_task_table.html")


@router.post("/tasks/{task_id}/plan-toggle", response_class=HTMLResponse)
def plan_toggle(
    request: Request,
    task_id: int,
    workspace: str = Form("private"),
    status: str = Form("open"),
    tag: str = Form(""),
    search: str = Form(""),
):
    """Star / unstar a task for My Day."""
    task = _task_or_404(request, task_id)
    db.set_planned(
        _conn(request), task_id, None if task["planned_for"] else db.today_iso()
    )
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
    task_workspace: str = Form("private"),
    workspace: str = Form("private"),
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
    workspace: str = Form("private"),
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


# ---------- recurring rules (also HX-Refresh: a new rule can spawn a task
# immediately, so the list, the rules section and the counts all change) ----------

@router.post("/recurring/new")
def recurring_new(
    request: Request,
    title: str = Form(""),
    freq: str = Form("weekly"),
    interval_n: int = Form(1),
    weekday: int = Form(0),
    monthday: int = Form(1),
    priority: str = Form("normal"),
    tags: list[str] = Form([]),
    task_workspace: str = Form(""),
    workspace: str = Form("private"),
):
    if title.strip():
        try:
            db.create_recurring(
                _conn(request),
                title=title.strip(),
                freq=freq if freq in db.FREQUENCIES else "weekly",
                priority=priority if priority in ("low", "normal", "high") else "normal",
                tags=tags,
                workspace=_norm_workspace(task_workspace or workspace),
                interval_n=max(1, interval_n),
                weekday=weekday if freq == "weekly" else None,
                monthday=monthday if freq == "monthly" else None,
            )
            db.spawn_due_tasks(_conn(request))
        except ValueError:
            pass
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/recurring/{rule_id}/toggle")
def recurring_toggle(request: Request, rule_id: int):
    rule = db.get_recurring(_conn(request), rule_id)
    if rule is not None:
        db.set_recurring_active(_conn(request), rule_id, not rule["active"])
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/recurring/{rule_id}/delete")
def recurring_delete(request: Request, rule_id: int):
    db.delete_recurring(_conn(request), rule_id)
    return Response(status_code=204, headers={"HX-Refresh": "true"})
