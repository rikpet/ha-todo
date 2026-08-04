from todo_app import db


def test_create_and_get(conn):
    task = db.create_task(conn, title="Buy milk", tags=["home"], due_date="2026-08-10")
    assert task["id"] == 1
    assert task["status"] == "open"
    assert task["tags"] == ["home"]
    assert db.get_task(conn, 1)["title"] == "Buy milk"
    assert db.get_task(conn, 999) is None


def test_update_and_complete(conn):
    task = db.create_task(conn, title="A")
    updated = db.update_task(conn, task["id"], title="B", priority="high")
    assert updated["title"] == "B"
    assert updated["priority"] == "high"

    done = db.update_task(conn, task["id"], status="done")
    assert done["status"] == "done"
    assert done["completed_at"] is not None

    reopened = db.update_task(conn, task["id"], status="open")
    assert reopened["completed_at"] is None
    assert db.update_task(conn, 999, title="X") is None


def test_clear_due_date(conn):
    task = db.create_task(conn, title="A", due_date="2026-01-01")
    cleared = db.update_task(conn, task["id"], clear_due_date=True)
    assert cleared["due_date"] is None


def test_filters(conn):
    db.create_task(conn, title="Fix bike", tags=["home"], due_date="2026-01-01")
    db.create_task(conn, title="Write report", tags=["work"], priority="high")
    done_id = db.create_task(conn, title="Old thing")["id"]
    db.update_task(conn, done_id, status="done")

    assert len(db.list_tasks(conn)) == 3
    assert len(db.list_tasks(conn, status="open")) == 2
    assert [t["title"] for t in db.list_tasks(conn, tag="work")] == ["Write report"]
    assert [t["title"] for t in db.list_tasks(conn, search="bike")] == ["Fix bike"]
    assert [t["title"] for t in db.list_tasks(conn, due_before="2026-06-01")] == ["Fix bike"]
    # smart sort: open before done
    assert db.list_tasks(conn)[-1]["status"] == "done"


def test_delete(conn):
    task = db.create_task(conn, title="A")
    assert db.delete_task(conn, task["id"]) is True
    assert db.delete_task(conn, task["id"]) is False


def test_all_tags(conn):
    db.create_task(conn, title="A", tags=["b", "a"])
    db.create_task(conn, title="B", tags=["b", "c"])
    assert db.all_tags(conn) == ["a", "b", "c"]


def test_migration_is_idempotent(conn):
    db.migrate(conn)  # second run must not fail or duplicate
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == len(
        db.MIGRATIONS
    )
