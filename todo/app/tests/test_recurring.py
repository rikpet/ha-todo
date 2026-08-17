from datetime import date

import pytest

from todo_app import db


def rule(**kw):
    base = {"freq": "daily", "interval_n": 1, "weekday": None, "monthday": None}
    return {**base, **kw}


# ---------- date maths ----------

def test_daily_occurrences():
    r = rule(freq="daily")
    assert db.first_occurrence(r, date(2026, 8, 4)) == date(2026, 8, 4)
    assert db.next_occurrence(r, date(2026, 8, 4)) == date(2026, 8, 5)
    assert db.next_occurrence(rule(freq="daily", interval_n=3), date(2026, 8, 4)) == date(2026, 8, 7)


def test_weekly_occurrences():
    # 2026-08-04 is a Tuesday (weekday 1)
    monday = rule(freq="weekly", weekday=0)
    assert db.first_occurrence(monday, date(2026, 8, 4)) == date(2026, 8, 10)
    # a rule due today starts today, not next week
    tuesday = rule(freq="weekly", weekday=1)
    assert db.first_occurrence(tuesday, date(2026, 8, 4)) == date(2026, 8, 4)
    assert db.next_occurrence(tuesday, date(2026, 8, 4)) == date(2026, 8, 11)
    biweekly = rule(freq="weekly", weekday=1, interval_n=2)
    assert db.next_occurrence(biweekly, date(2026, 8, 4)) == date(2026, 8, 18)


def test_monthly_occurrences():
    r = rule(freq="monthly", monthday=15)
    assert db.first_occurrence(r, date(2026, 8, 4)) == date(2026, 8, 15)
    assert db.first_occurrence(r, date(2026, 8, 20)) == date(2026, 9, 15)
    assert db.next_occurrence(r, date(2026, 8, 15)) == date(2026, 9, 15)
    quarterly = rule(freq="monthly", monthday=1, interval_n=3)
    assert db.next_occurrence(quarterly, date(2026, 10, 1)) == date(2027, 1, 1)


def test_monthly_clamps_short_months():
    r = rule(freq="monthly", monthday=31)
    assert db.next_occurrence(r, date(2026, 1, 31)) == date(2026, 2, 28)
    assert db.next_occurrence(r, date(2028, 1, 31)) == date(2028, 2, 29)  # leap year
    # clamping must not permanently shorten the rule
    assert db.next_occurrence(r, date(2026, 2, 28)) == date(2026, 3, 31)


# ---------- rule management ----------

def test_create_and_list(conn):
    r = db.create_recurring(
        conn, title="Take out bins", freq="weekly", weekday=0, start_date="2026-08-04"
    )
    assert r["next_run"] == "2026-08-10"
    assert r["active"] is True
    assert db.describe_recurring(r) == "every week on Monday"
    assert [x["id"] for x in db.list_recurring(conn)] == [r["id"]]


def test_validation(conn):
    with pytest.raises(ValueError, match="Frequency"):
        db.create_recurring(conn, title="x", freq="hourly")
    with pytest.raises(ValueError, match="weekday"):
        db.create_recurring(conn, title="x", freq="weekly")
    with pytest.raises(ValueError, match="Interval"):
        db.create_recurring(conn, title="x", freq="daily", interval_n=0)
    with pytest.raises(ValueError, match="Unknown tag"):
        db.create_recurring(conn, title="x", freq="daily", tags=["nope"])


def test_describe(conn):
    assert db.describe_recurring(rule(freq="daily")) == "every day"
    assert db.describe_recurring(rule(freq="daily", interval_n=2)) == "every 2 days"
    assert db.describe_recurring(rule(freq="monthly", monthday=1)) == "every month on day 1"


# ---------- spawning ----------

def test_spawns_on_due_date(conn):
    db.create_recurring(conn, title="Water plants", freq="daily", start_date="2026-08-04")
    assert db.spawn_due_tasks(conn, today=date(2026, 8, 3)) == []  # not due yet

    created = db.spawn_due_tasks(conn, today=date(2026, 8, 4))
    assert [t["title"] for t in created] == ["Water plants"]
    assert created[0]["due_date"] == "2026-08-04"
    assert created[0]["recurring_id"] == 1

    # same day again: no duplicate
    assert db.spawn_due_tasks(conn, today=date(2026, 8, 4)) == []


def test_does_not_stack_while_previous_is_open(conn):
    db.create_recurring(conn, title="Daily standup", freq="daily", start_date="2026-08-04")
    db.spawn_due_tasks(conn, today=date(2026, 8, 4))
    # next day, yesterday's task still open -> skip
    assert db.spawn_due_tasks(conn, today=date(2026, 8, 5)) == []
    # complete it, then the following day spawns again
    db.update_task(conn, 1, status="done")
    created = db.spawn_due_tasks(conn, today=date(2026, 8, 6))
    assert len(created) == 1


def test_missed_runs_collapse_to_one(conn):
    """Add-on offline for a fortnight must not produce 14 copies."""
    db.create_recurring(conn, title="Feed the cat", freq="daily", start_date="2026-08-01")
    created = db.spawn_due_tasks(conn, today=date(2026, 8, 15))
    assert len(created) == 1
    rule_row = db.get_recurring(conn, 1)
    assert rule_row["next_run"] == "2026-08-16"  # advanced past today
    assert rule_row["last_spawned_on"] == "2026-08-15"


def test_paused_rules_do_not_spawn(conn):
    db.create_recurring(conn, title="Paused thing", freq="daily", start_date="2026-08-04")
    db.set_recurring_active(conn, 1, False)
    assert db.spawn_due_tasks(conn, today=date(2026, 8, 10)) == []
    db.set_recurring_active(conn, 1, True)
    assert len(db.spawn_due_tasks(conn, today=date(2026, 8, 10))) == 1


def test_spawn_copies_rule_fields(conn):
    db.add_allowed_tag(conn, "hushall")
    db.create_recurring(
        conn, title="Vacuum", freq="weekly", weekday=5, priority="high", tags=["hushall"],
        workspace="private", due_offset_days=2, start_date="2026-08-04",
    )
    task = db.spawn_due_tasks(conn, today=date(2026, 8, 8))[0]
    assert task["priority"] == "high"
    assert task["tags"] == ["hushall"]
    assert task["workspace"] == "private"
    assert task["due_date"] == "2026-08-10"  # run date + offset


def test_deleted_tag_does_not_break_spawning(conn):
    db.add_allowed_tag(conn, "temp")
    db.create_recurring(conn, title="Thing", freq="daily", tags=["temp"], start_date="2026-08-04")
    db.remove_allowed_tag(conn, "temp")
    task = db.spawn_due_tasks(conn, today=date(2026, 8, 4))[0]
    assert task["tags"] == []


def test_delete_rule_keeps_tasks(conn):
    db.create_recurring(conn, title="Keep me", freq="daily", start_date="2026-08-04")
    db.spawn_due_tasks(conn, today=date(2026, 8, 4))
    assert db.delete_recurring(conn, 1) is True
    assert db.delete_recurring(conn, 1) is False
    task = db.get_task(conn, 1)
    assert task["title"] == "Keep me"
    assert task["recurring_id"] is None


def test_weekly_rule_lands_on_the_right_weekday(conn):
    db.create_recurring(
        conn, title="Friday report", freq="weekly", weekday=4, start_date="2026-08-04"
    )
    first = db.spawn_due_tasks(conn, today=date(2026, 8, 7))[0]
    assert date.fromisoformat(first["due_date"]).weekday() == 4
    db.update_task(conn, first["id"], status="done")
    second = db.spawn_due_tasks(conn, today=date(2026, 8, 14))[0]
    assert date.fromisoformat(second["due_date"]).weekday() == 4
