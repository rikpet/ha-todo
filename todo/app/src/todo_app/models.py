"""Pydantic models for the API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["low", "normal", "high"]
Status = Literal["open", "done"]
Workspace = Literal["private", "work"]
ClaudeState = Literal["queued", "working", "review", "failed"]


def _validate_iso_date(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    date.fromisoformat(value)
    return value


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    priority: Priority = "normal"
    due_date: str | None = None
    tags: list[str] = []
    workspace: Workspace = "private"
    planned_for: str | None = None
    created_by: Literal["me", "claude"] = "me"
    origin_task_id: int | None = None

    _check_due = field_validator("due_date")(_validate_iso_date)
    _check_planned = field_validator("planned_for")(_validate_iso_date)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: Status | None = None
    priority: Priority | None = None
    due_date: str | None = None
    clear_due_date: bool = False
    tags: list[str] | None = None
    workspace: Workspace | None = None
    planned_for: str | None = None
    clear_planned_for: bool = False

    _check_due = field_validator("due_date")(_validate_iso_date)
    _check_planned = field_validator("planned_for")(_validate_iso_date)


class Task(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    priority: Priority
    due_date: str | None
    tags: list[str]
    workspace: Workspace
    planned_for: str | None = None
    recurring_id: int | None = None
    claude_state: ClaudeState | None = None
    claude_claimed_at: str | None = None
    created_by: Literal["me", "claude"] = "me"
    origin_task_id: int | None = None
    created_at: str
    updated_at: str
    completed_at: str | None


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)


Frequency = Literal["daily", "weekly", "monthly"]


class RecurringCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    freq: Frequency
    description: str = ""
    priority: Priority = "normal"
    tags: list[str] = []
    workspace: Workspace = "private"
    interval_n: int = Field(default=1, ge=1, le=365)
    weekday: int | None = Field(default=None, ge=0, le=6)
    monthday: int | None = Field(default=None, ge=1, le=31)
    due_offset_days: int = Field(default=0, ge=0, le=365)
    start_date: str | None = None

    _check_start = field_validator("start_date")(_validate_iso_date)


class Recurring(BaseModel):
    id: int
    title: str
    description: str
    priority: Priority
    tags: list[str]
    workspace: Workspace
    freq: Frequency
    interval_n: int
    weekday: int | None
    monthday: int | None
    due_offset_days: int
    active: bool
    next_run: str
    last_spawned_on: str | None
    created_at: str
    updated_at: str


class MailImport(BaseModel):
    message_id: str
    task_id: int | None
    sender: str
    subject: str
    outcome: Literal["created", "rejected"]
    imported_at: str


class MailStatus(BaseModel):
    enabled: bool
    active: bool
    missing: list[str]
    host: str
    username: str
    folder: str
    poll_minutes: int
    allowed_senders: list[str]
    default_workspace: Workspace
    last_check: str | None
    last_error: str | None
    recent: list[MailImport]


class Note(BaseModel):
    id: int
    task_id: int
    author: Literal["me", "claude"]
    body: str
    created_at: str


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=100_000)
    author: Literal["me", "claude"] = "me"


class ClaudeHandOver(BaseModel):
    instructions: str = Field(default="", max_length=20_000)


class ClaudeFinish(BaseModel):
    result: str = Field(min_length=1, max_length=200_000)
    state: Literal["review", "failed"] = "review"
