"""SQLite storage layer with numbered migrations."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
        priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
        due_date TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    );
    CREATE INDEX idx_tasks_status ON tasks(status);
    CREATE INDEX idx_tasks_due ON tasks(due_date);
    """,
]


def default_db_path() -> str:
    return os.environ.get("TODO_DB_PATH", "todo.db")


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    # FastAPI runs sync endpoints in a threadpool; sqlite3 default build is
    # serialized (threadsafe), so sharing one connection across threads is fine.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row["version"] if row else 0
    for number, script in enumerate(MIGRATIONS, start=1):
        if number > current:
            conn.executescript(script)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (number,))
            conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    task["tags"] = json.loads(task["tags"])
    return task


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str = "",
    priority: str = "normal",
    due_date: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    now = _now()
    cur = conn.execute(
        """INSERT INTO tasks (title, description, priority, due_date, tags, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (title, description, priority, due_date, json.dumps(tags or []), now, now),
    )
    conn.commit()
    return get_task(conn, cur.lastrowid)


def get_task(conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    tag: str | None = None,
    search: str | None = None,
    due_before: str | None = None,
    sort: str = "smart",
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(title LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if due_before:
        clauses.append("due_date IS NOT NULL AND due_date <= ?")
        params.append(due_before)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = {
        # open before done; earliest due first (nulls last); high priority first; newest last
        "smart": """ORDER BY status = 'done',
                    due_date IS NULL, due_date,
                    CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    id""",
        "created": "ORDER BY id",
        "due": "ORDER BY due_date IS NULL, due_date, id",
        "priority": "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id",
    }.get(sort, "ORDER BY id")
    rows = conn.execute(f"SELECT * FROM tasks {where} {order}", params).fetchall()
    tasks = [_row_to_task(r) for r in rows]
    if tag:
        tasks = [t for t in tasks if tag in t["tags"]]
    return tasks


def update_task(conn: sqlite3.Connection, task_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {"title", "description", "status", "priority", "due_date", "tags"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    # due_date is nullable: allow explicit clearing via sentinel
    if fields.get("clear_due_date"):
        updates["due_date"] = None
    if not updates and "due_date" not in updates:
        return get_task(conn, task_id)
    if "tags" in updates:
        updates["tags"] = json.dumps(updates["tags"])
    if updates.get("status") == "done":
        updates["completed_at"] = _now()
    elif updates.get("status") == "open":
        updates["completed_at"] = None
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{k} = ?" for k in updates)
    cur = conn.execute(
        f"UPDATE tasks SET {assignments} WHERE id = ?", (*updates.values(), task_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return get_task(conn, task_id)


def delete_task(conn: sqlite3.Connection, task_id: int) -> bool:
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    return cur.rowcount > 0


def all_tags(conn: sqlite3.Connection) -> list[str]:
    tags: set[str] = set()
    for row in conn.execute("SELECT tags FROM tasks"):
        tags.update(json.loads(row["tags"]))
    return sorted(tags)
