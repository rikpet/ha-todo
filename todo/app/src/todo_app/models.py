"""Pydantic models for the API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Priority = Literal["low", "normal", "high"]
Status = Literal["open", "done"]


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

    _check_due = field_validator("due_date")(_validate_iso_date)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    status: Status | None = None
    priority: Priority | None = None
    due_date: str | None = None
    clear_due_date: bool = False
    tags: list[str] | None = None

    _check_due = field_validator("due_date")(_validate_iso_date)


class Task(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    priority: Priority
    due_date: str | None
    tags: list[str]
    created_at: str
    updated_at: str
    completed_at: str | None
