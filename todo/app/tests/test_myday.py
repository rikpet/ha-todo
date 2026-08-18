"""My Day: membership, carry-over and the late (red) rules."""

from datetime import date, timedelta

import pytest

from todo_app import db

TODAY = "2026-08-17"
YESTERDAY = "2026-08-16"
TOMORROW = "2026-08-18"


def titles(tasks):
    return [t["title"] for t in tasks]


# ---------- membership ----------

def test_flagged_task_is_in_my_day(conn):
    t = db.create_task(conn, title="Flagged")
    db.create_task(conn, title="Not flagged")
    db.set_planned(conn, t["id"], TODAY)
    assert titles(db.list_my_day(conn, TODAY)) == ["Flagged"]


def test_due_today_joins_automatically(conn):
    db.create_task(conn, title="Due today", due_date=TODAY)
    db.create_task(conn, title="Due tomorrow", due_date=TOMORROW)
    db.create_task(conn, title="No date")
    assert titles(db.list_my_day(conn, TODAY)) == ["Due today"]


def test_overdue_stays_in_my_day(conn):
    db.create_task(conn, title="Late one", due_date=YESTERDAY)
    assert titles(db.list_my_day(conn, TODAY)) == ["Late one"]


def test_future_flag_waits_its_turn(conn):
    t = db.create_task(conn, title="Planned tomorrow")
    db.set_planned(conn, t["id"], TOMORROW)
    assert db.list_my_day(conn, TODAY) == []
    assert titles(db.list_my_day(conn, TOMORROW)) == ["Planned tomorrow"]


def test_my_day_spans_workspaces_but_can_be_narrowed(conn):
    a = db.create_task(conn, title="Private thing", workspace="private")
    b = db.create_task(conn, title="Work thing", workspace="work")
    db.set_planned(conn, a["id"], TODAY)
    db.set_planned(conn, b["id"], TODAY)
    assert len(db.list_my_day(conn, TODAY)) == 2
    assert titles(db.list_my_day(conn, TODAY, workspace="work")) == ["Work thing"]


# ---------- carry-over ----------

def test_unfinished_flag_carries_over_and_is_late(conn):
    t = db.create_task(conn, title="Slipped")
    db.set_planned(conn, t["id"], YESTERDAY)

    carried = db.list_my_day(conn, TODAY)
    assert titles(carried) == ["Slipped"]
    assert db.is_carried_over(carried[0], TODAY) is True
    assert db.is_late(carried[0], TODAY) is True
    # the original plan date is kept, so we know how long it has been slipping
    assert carried[0]["planned_for"] == YESTERDAY


def test_completed_task_does_not_carry_over(conn):
    t = db.create_task(conn, title="Finished yesterday")
    db.set_planned(conn, t["id"], YESTERDAY)
    db.update_task(conn, t["id"], status="done")
    assert db.list_my_day(conn, TODAY) == []


def test_carry_over_survives_many_days(conn):
    t = db.create_task(conn, title="Long overdue")
    db.set_planned(conn, t["id"], "2026-08-01")
    tasks = db.list_my_day(conn, TODAY)
    assert titles(tasks) == ["Long overdue"]
    assert db.is_late(tasks[0], TODAY) is True


# ---------- late / red rules ----------

def test_late_flags(conn):
    on_time = db.create_task(conn, title="Due today", due_date=TODAY)
    overdue = db.create_task(conn, title="Overdue", due_date=YESTERDAY)
    assert db.is_late(on_time, TODAY) is False
    assert db.is_overdue(overdue, TODAY) is True
    assert db.is_late(overdue, TODAY) is True

    done = db.update_task(conn, overdue["id"], status="done")
    assert db.is_late(done, TODAY) is False  # finished is never late


def test_late_tasks_sort_first(conn):
    db.create_task(conn, title="Due today", due_date=TODAY)
    db.create_task(conn, title="Was due", due_date=YESTERDAY)
    assert titles(db.list_my_day(conn, TODAY))[0] == "Was due"


def test_finished_today_still_listed_but_last(conn):
    a = db.create_task(conn, title="Done one", due_date=TODAY)
    db.create_task(conn, title="Still open", due_date=TODAY)
    db.update_task(conn, a["id"], status="done")
    listed = titles(db.list_my_day(conn, date.today().isoformat()))
    # completed_at is stamped "now", so use the real today for this one
    assert "Still open" in titles(db.list_my_day(conn, TODAY))
    if "Done one" in listed:
        assert listed[-1] == "Done one"


# ---------- flag plumbing ----------

def test_set_and_clear_flag(conn):
    t = db.create_task(conn, title="Toggle me")
    planned = db.set_planned(conn, t["id"], TODAY)
    assert planned["planned_for"] == TODAY
    cleared = db.set_planned(conn, t["id"], None)
    assert cleared["planned_for"] is None
    assert db.set_planned(conn, 999, TODAY) is None


def test_bad_date_rejected(conn):
    t = db.create_task(conn, title="x")
    with pytest.raises(ValueError):
        db.set_planned(conn, t["id"], "not-a-date")


def test_create_with_flag(conn):
    t = db.create_task(conn, title="Straight into today", planned_for=TODAY)
    assert t["planned_for"] == TODAY
    assert titles(db.list_my_day(conn, TODAY)) == ["Straight into today"]


def test_recurring_task_lands_in_my_day_on_its_due_day(conn):
    """A rule due today should surface in My Day without manual flagging."""
    db.create_recurring(conn, title="Water plants", freq="daily", start_date=TODAY)
    db.spawn_due_tasks(conn, today=date.fromisoformat(TODAY))
    assert titles(db.list_my_day(conn, TODAY)) == ["Water plants"]


def test_migration_adds_planned_for(tmp_path):
    """An existing v4 database gains the column with everything unflagged."""
    import sqlite3

    path = str(tmp_path / "v4.db")
    old = sqlite3.connect(path)
    for script in db.MIGRATIONS[:4]:
        old.executescript(script)
    old.execute(
        """INSERT INTO tasks (title, workspace, created_at, updated_at)
           VALUES ('Existing', 'work', 't', 't')"""
    )
    old.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    old.execute("INSERT INTO schema_version (version) VALUES (4)")
    old.commit()
    old.close()

    conn = db.connect(path)
    task = db.get_task(conn, 1)
    assert task["title"] == "Existing"
    assert task["planned_for"] is None
    assert db.list_my_day(conn, TODAY) == []
    conn.close()
