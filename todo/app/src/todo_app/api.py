"""JSON REST API under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from . import db
from .auth import require_auth
from .models import Task, TaskCreate, TaskUpdate

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])


def get_conn(request: Request):
    return request.app.state.db


@router.get("/tasks", response_model=list[Task])
def list_tasks(
    request: Request,
    status: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    due_before: str | None = None,
    sort: str = "smart",
):
    if status not in (None, "open", "done"):
        raise HTTPException(status_code=422, detail="status must be 'open' or 'done'")
    return db.list_tasks(
        get_conn(request), status=status, tag=tag, search=search,
        due_before=due_before, sort=sort,
    )


@router.post("/tasks", response_model=Task, status_code=201)
def create_task(request: Request, payload: TaskCreate):
    return db.create_task(get_conn(request), **payload.model_dump())


@router.get("/tasks/{task_id}", response_model=Task)
def get_task(request: Request, task_id: int):
    task = db.get_task(get_conn(request), task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
def update_task(request: Request, task_id: int, payload: TaskUpdate):
    fields = payload.model_dump(exclude_unset=True)
    task = db.update_task(get_conn(request), task_id, **fields)
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
    return db.all_tags(get_conn(request))
