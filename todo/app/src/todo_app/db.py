"""SQLite storage layer with numbered migrations."""

from __future__ import annotations

import calendar
import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
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
    # 2: workspaces + curated tag list
    """
    ALTER TABLE tasks ADD COLUMN workspace TEXT NOT NULL DEFAULT 'home'
        CHECK (workspace IN ('home', 'work'));
    CREATE INDEX idx_tasks_workspace ON tasks(workspace);
    CREATE TABLE allowed_tags (name TEXT PRIMARY KEY) WITHOUT ROWID;
    """,
    # 3: recurring task rules
    """
    CREATE TABLE recurring (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        priority TEXT NOT NULL DEFAULT 'normal'
            CHECK (priority IN ('low', 'normal', 'high')),
        tags TEXT NOT NULL DEFAULT '[]',
        workspace TEXT NOT NULL DEFAULT 'home' CHECK (workspace IN ('home', 'work')),
        freq TEXT NOT NULL CHECK (freq IN ('daily', 'weekly', 'monthly')),
        interval_n INTEGER NOT NULL DEFAULT 1 CHECK (interval_n >= 1),
        weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
        monthday INTEGER CHECK (monthday BETWEEN 1 AND 31),
        due_offset_days INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        next_run TEXT NOT NULL,
        last_spawned_on TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    ALTER TABLE tasks ADD COLUMN recurring_id INTEGER;
    CREATE INDEX idx_tasks_recurring ON tasks(recurring_id);
    """,
    # 4: rename the 'home' workspace to 'private'. SQLite cannot alter a CHECK
    # constraint, so both tables are rebuilt and their rows carried across.
    """
    CREATE TABLE tasks_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
        priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
        due_date TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        workspace TEXT NOT NULL DEFAULT 'private' CHECK (workspace IN ('private', 'work')),
        recurring_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    );
    INSERT INTO tasks_new (id, title, description, status, priority, due_date, tags,
                           workspace, recurring_id, created_at, updated_at, completed_at)
        SELECT id, title, description, status, priority, due_date, tags,
               CASE workspace WHEN 'home' THEN 'private' ELSE workspace END,
               recurring_id, created_at, updated_at, completed_at
        FROM tasks;
    DROP TABLE tasks;
    ALTER TABLE tasks_new RENAME TO tasks;
    CREATE INDEX idx_tasks_status ON tasks(status);
    CREATE INDEX idx_tasks_due ON tasks(due_date);
    CREATE INDEX idx_tasks_workspace ON tasks(workspace);
    CREATE INDEX idx_tasks_recurring ON tasks(recurring_id);

    CREATE TABLE recurring_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        priority TEXT NOT NULL DEFAULT 'normal'
            CHECK (priority IN ('low', 'normal', 'high')),
        tags TEXT NOT NULL DEFAULT '[]',
        workspace TEXT NOT NULL DEFAULT 'private' CHECK (workspace IN ('private', 'work')),
        freq TEXT NOT NULL CHECK (freq IN ('daily', 'weekly', 'monthly')),
        interval_n INTEGER NOT NULL DEFAULT 1 CHECK (interval_n >= 1),
        weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
        monthday INTEGER CHECK (monthday BETWEEN 1 AND 31),
        due_offset_days INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        next_run TEXT NOT NULL,
        last_spawned_on TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    INSERT INTO recurring_new (id, title, description, priority, tags, workspace, freq,
                               interval_n, weekday, monthday, due_offset_days, active,
                               next_run, last_spawned_on, created_at, updated_at)
        SELECT id, title, description, priority, tags,
               CASE workspace WHEN 'home' THEN 'private' ELSE workspace END,
               freq, interval_n, weekday, monthday, due_offset_days, active,
               next_run, last_spawned_on, created_at, updated_at
        FROM recurring;
    DROP TABLE recurring;
    ALTER TABLE recurring_new RENAME TO recurring;
    """,
]

WORKSPACES = ("private", "work")
FREQUENCIES = ("daily", "weekly", "monthly")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


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


def _validate_tags(conn: sqlite3.Connection, tags: list[str]) -> None:
    allowed = set(allowed_tags(conn))
    unknown = sorted(set(tags) - allowed)
    if unknown:
        raise ValueError(
            f"Unknown tag(s): {', '.join(unknown)}. "
            f"Allowed tags: {', '.join(sorted(allowed)) or '(none configured)'}"
        )


def _validate_workspace(workspace: str) -> None:
    if workspace not in WORKSPACES:
        raise ValueError(f"Workspace must be one of: {', '.join(WORKSPACES)}")


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    description: str = "",
    priority: str = "normal",
    due_date: str | None = None,
    tags: list[str] | None = None,
    workspace: str = "private",
    recurring_id: int | None = None,
) -> dict[str, Any]:
    _validate_workspace(workspace)
    _validate_tags(conn, tags or [])
    now = _now()
    cur = conn.execute(
        """INSERT INTO tasks (title, description, priority, due_date, tags, workspace,
                              recurring_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, priority, due_date, json.dumps(tags or []), workspace,
         recurring_id, now, now),
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
    workspace: str | None = None,
    sort: str = "smart",
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
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
    allowed = {"title", "description", "status", "priority", "due_date", "tags", "workspace"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "workspace" in updates:
        _validate_workspace(updates["workspace"])
    if "tags" in updates:
        _validate_tags(conn, updates["tags"])
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


# ---------- recurring rules ----------


def _add_months(day: date, months: int, monthday: int) -> date:
    """Move `months` forward, landing on `monthday` (clamped to the month's length)."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(monthday, last))


def first_occurrence(rule: dict[str, Any], on_or_after: date) -> date:
    """The rule's first run date on or after the given day."""
    freq = rule["freq"]
    if freq == "daily":
        return on_or_after
    if freq == "weekly":
        weekday = rule["weekday"] if rule.get("weekday") is not None else on_or_after.weekday()
        return on_or_after + timedelta(days=(weekday - on_or_after.weekday()) % 7)
    monthday = rule.get("monthday") or on_or_after.day
    candidate = _add_months(on_or_after, 0, monthday)
    if candidate < on_or_after:
        candidate = _add_months(on_or_after, 1, monthday)
    return candidate


def next_occurrence(rule: dict[str, Any], previous: date) -> date:
    """The run date following `previous`, honouring the rule's interval."""
    interval = max(1, int(rule.get("interval_n") or 1))
    freq = rule["freq"]
    if freq == "daily":
        return previous + timedelta(days=interval)
    if freq == "weekly":
        return previous + timedelta(weeks=interval)
    return _add_months(previous, interval, rule.get("monthday") or previous.day)


def _row_to_rule(row: sqlite3.Row) -> dict[str, Any]:
    rule = dict(row)
    rule["tags"] = json.loads(rule["tags"])
    rule["active"] = bool(rule["active"])
    return rule


def create_recurring(
    conn: sqlite3.Connection,
    *,
    title: str,
    freq: str,
    description: str = "",
    priority: str = "normal",
    tags: list[str] | None = None,
    workspace: str = "private",
    interval_n: int = 1,
    weekday: int | None = None,
    monthday: int | None = None,
    due_offset_days: int = 0,
    start_date: str | None = None,
) -> dict[str, Any]:
    if freq not in FREQUENCIES:
        raise ValueError(f"Frequency must be one of: {', '.join(FREQUENCIES)}")
    if interval_n < 1:
        raise ValueError("Interval must be at least 1")
    if freq == "weekly" and weekday is None:
        raise ValueError("Weekly rules need a weekday (0=Monday .. 6=Sunday)")
    if freq == "weekly" and not 0 <= weekday <= 6:
        raise ValueError("Weekday must be between 0 (Monday) and 6 (Sunday)")
    if freq == "monthly" and monthday is not None and not 1 <= monthday <= 31:
        raise ValueError("Month day must be between 1 and 31")
    _validate_workspace(workspace)
    _validate_tags(conn, tags or [])

    start = date.fromisoformat(start_date) if start_date else date.today()
    draft = {"freq": freq, "weekday": weekday, "monthday": monthday, "interval_n": interval_n}
    next_run = first_occurrence(draft, start)
    now = _now()
    cur = conn.execute(
        """INSERT INTO recurring (title, description, priority, tags, workspace, freq,
                                  interval_n, weekday, monthday, due_offset_days,
                                  next_run, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, priority, json.dumps(tags or []), workspace, freq,
         interval_n, weekday, monthday, due_offset_days, next_run.isoformat(), now, now),
    )
    conn.commit()
    return get_recurring(conn, cur.lastrowid)


def get_recurring(conn: sqlite3.Connection, rule_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM recurring WHERE id = ?", (rule_id,)).fetchone()
    return _row_to_rule(row) if row else None


def list_recurring(
    conn: sqlite3.Connection, *, workspace: str | None = None, active_only: bool = False
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if active_only:
        clauses.append("active = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM recurring {where} ORDER BY next_run, id", params)
    return [_row_to_rule(r) for r in rows]


def set_recurring_active(
    conn: sqlite3.Connection, rule_id: int, active: bool
) -> dict[str, Any] | None:
    cur = conn.execute(
        "UPDATE recurring SET active = ?, updated_at = ? WHERE id = ?",
        (1 if active else 0, _now(), rule_id),
    )
    conn.commit()
    return get_recurring(conn, rule_id) if cur.rowcount else None


def delete_recurring(conn: sqlite3.Connection, rule_id: int) -> bool:
    cur = conn.execute("DELETE FROM recurring WHERE id = ?", (rule_id,))
    conn.commit()
    # already-created tasks stay, they just lose the link back to the rule
    conn.execute("UPDATE tasks SET recurring_id = NULL WHERE recurring_id = ?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


def describe_recurring(rule: dict[str, Any]) -> str:
    """Human-readable schedule, e.g. 'every 2 weeks on Monday'."""
    n = rule.get("interval_n") or 1
    freq = rule["freq"]
    if freq == "daily":
        return "every day" if n == 1 else f"every {n} days"
    if freq == "weekly":
        day = WEEKDAY_NAMES[rule["weekday"]] if rule.get("weekday") is not None else ""
        every = "every week" if n == 1 else f"every {n} weeks"
        return f"{every} on {day}" if day else every
    every = "every month" if n == 1 else f"every {n} months"
    return f"{every} on day {rule['monthday']}" if rule.get("monthday") else every


def _has_open_instance(conn: sqlite3.Connection, rule_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM tasks WHERE recurring_id = ? AND status = 'open' LIMIT 1", (rule_id,)
    ).fetchone()
    return row is not None


def spawn_due_tasks(
    conn: sqlite3.Connection, today: date | None = None
) -> list[dict[str, Any]]:
    """Create tasks for every rule that has come due. Safe to call repeatedly.

    Missed runs (add-on offline, HA rebooted) collapse into a single task rather
    than a backlog of copies, and a rule whose previous task is still open does
    not stack another one on top.
    """
    today = today or date.today()
    created: list[dict[str, Any]] = []
    for rule in list_recurring(conn, active_only=True):
        run_date = date.fromisoformat(rule["next_run"])
        if run_date > today:
            continue
        if not _has_open_instance(conn, rule["id"]):
            due = run_date + timedelta(days=rule["due_offset_days"])
            created.append(
                create_task(
                    conn,
                    title=rule["title"],
                    description=rule["description"],
                    priority=rule["priority"],
                    due_date=due.isoformat(),
                    tags=[t for t in rule["tags"] if t in set(allowed_tags(conn))],
                    workspace=rule["workspace"],
                    recurring_id=rule["id"],
                )
            )
        upcoming = run_date
        while upcoming <= today:
            upcoming = next_occurrence(rule, upcoming)
        conn.execute(
            "UPDATE recurring SET next_run = ?, last_spawned_on = ?, updated_at = ? WHERE id = ?",
            (upcoming.isoformat(), today.isoformat(), _now(), rule["id"]),
        )
        conn.commit()
    return created


def allowed_tags(conn: sqlite3.Connection) -> list[str]:
    return [row["name"] for row in conn.execute("SELECT name FROM allowed_tags ORDER BY name")]


def add_allowed_tag(conn: sqlite3.Connection, name: str) -> None:
    name = name.strip().lstrip("#")
    if not name:
        raise ValueError("Tag name cannot be empty")
    conn.execute("INSERT OR IGNORE INTO allowed_tags (name) VALUES (?)", (name,))
    conn.commit()


def remove_allowed_tag(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute("DELETE FROM allowed_tags WHERE name = ?", (name,))
    if cur.rowcount == 0:
        conn.commit()
        return False
    # strip the tag from any task still carrying it
    for row in conn.execute("SELECT id, tags FROM tasks WHERE tags LIKE ?", (f'%"{name}"%',)):
        tags = [t for t in json.loads(row["tags"]) if t != name]
        conn.execute(
            "UPDATE tasks SET tags = ?, updated_at = ? WHERE id = ?",
            (json.dumps(tags), _now(), row["id"]),
        )
    conn.commit()
    return True
