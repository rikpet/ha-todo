"""JSON REST API under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from . import db
from .models import Task, TagCreate, TaskCreate, TaskUpdate

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
