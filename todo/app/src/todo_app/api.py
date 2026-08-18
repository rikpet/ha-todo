"""JSON REST API under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import db
from .models import Recurring, RecurringCreate, TagCreate, Task, TaskCreate, TaskUpdate

router = APIRouter(prefix="/api/v1")


def get_conn(request: Request):
    return request.app.state.db


@router.get("/tasks", response_model=list[Task])
def list_tasks(
    request: Request,
    status: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    due_before: str | None = None,
    workspace: str | None = None,
    sort: str = "smart",
):
    if status not in (None, "open", "done"):
        raise HTTPException(status_code=422, detail="status must be 'open' or 'done'")
    if workspace is not None and workspace not in db.WORKSPACES:
        raise HTTPException(
            status_code=422, detail=f"workspace must be one of: {', '.join(db.WORKSPACES)}"
        )
    return db.list_tasks(
        get_conn(request), status=status, tag=tag, search=search,
        due_before=due_before, workspace=workspace, sort=sort,
    )


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(request: Request, payload: TaskCreate):
    try:
        return db.create_task(get_conn(request), **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(request: Request, task_id: int):
    task = db.get_task(get_conn(request), task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(request: Request, task_id: int, payload: TaskUpdate):
    fields = payload.model_dump(exclude_unset=True)
    try:
        task = db.update_task(get_conn(request), task_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("/tasks/{task_id}/complete", response_model=Task)
def complete_task(request: Request, task_id: int):
    task = db.update_task(get_conn(request), task_id, status="done")
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("/tasks/{task_id}/reopen", response_model=Task)
def reopen_task(request: Request, task_id: int):
    task = db.update_task(get_conn(request), task_id, status="open")
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(request: Request, task_id: int):
    if not db.delete_task(get_conn(request), task_id):
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")


# ---------- My Day ----------


@router.get("/myday", response_model=list[Task])
def my_day(request: Request, workspace: str | None = None, day: str | None = None):
    """Tasks to deal with today: flagged for today or earlier, or due by today."""
    if workspace is not None and workspace not in db.WORKSPACES:
        raise HTTPException(
            status_code=422, detail=f"workspace must be one of: {', '.join(db.WORKSPACES)}"
        )
    return db.list_my_day(get_conn(request), day, workspace=workspace)


@router.post("/tasks/{task_id}/plan", response_model=Task)
def plan_task(request: Request, task_id: int, day: str | None = None):
    """Add a task to My Day (defaults to today)."""
    try:
        task = db.set_planned(get_conn(request), task_id, day or db.today_iso())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.post("/tasks/{task_id}/unplan", response_model=Task)
def unplan_task(request: Request, task_id: int):
    """Remove a task from My Day."""
    task = db.set_planned(get_conn(request), task_id, None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.get("/tags", response_model=list[str])
def list_tags(request: Request):
    return db.allowed_tags(get_conn(request))


@router.post("/tags", response_model=list[str], status_code=201)
def add_tag(request: Request, payload: TagCreate):
    try:
        db.add_allowed_tag(get_conn(request), payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return db.allowed_tags(get_conn(request))


@router.delete("/tags/{name}", status_code=204)
def remove_tag(request: Request, name: str):
    if not db.remove_allowed_tag(get_conn(request), name):
        raise HTTPException(status_code=404, detail=f"Tag '{name}' not found")


@router.get("/workspaces", response_model=list[str])
def list_workspaces():
    return list(db.WORKSPACES)


# ---------- recurring rules ----------


@router.get("/recurring", response_model=list[Recurring])
def list_recurring(request: Request, workspace: str | None = None):
    return db.list_recurring(get_conn(request), workspace=workspace)


@router.post("/recurring", response_model=Recurring, status_code=201)
def create_recurring(request: Request, payload: RecurringCreate):
    try:
        return db.create_recurring(get_conn(request), **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/recurring/{rule_id}", response_model=Recurring)
def get_recurring(request: Request, rule_id: int):
    rule = db.get_recurring(get_conn(request), rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Recurring rule {rule_id} not found")
    return rule


@router.post("/recurring/{rule_id}/pause", response_model=Recurring)
def pause_recurring(request: Request, rule_id: int):
    rule = db.set_recurring_active(get_conn(request), rule_id, False)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Recurring rule {rule_id} not found")
    return rule


@router.post("/recurring/{rule_id}/resume", response_model=Recurring)
def resume_recurring(request: Request, rule_id: int):
    rule = db.set_recurring_active(get_conn(request), rule_id, True)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Recurring rule {rule_id} not found")
    return rule


@router.delete("/recurring/{rule_id}", status_code=204)
def delete_recurring(request: Request, rule_id: int):
    if not db.delete_recurring(get_conn(request), rule_id):
        raise HTTPException(status_code=404, detail=f"Recurring rule {rule_id} not found")


@router.post("/recurring/run", response_model=list[Task])
def run_recurring_now(request: Request):
    """Materialise any due recurring tasks immediately (the scheduler also does this hourly)."""
    return db.spawn_due_tasks(get_conn(request))
