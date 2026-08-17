import pytest

from todo_app import db


def _allow(conn, *names):
    for name in names:
        db.add_allowed_tag(conn, name)


def test_create_and_get(conn):
    _allow(conn, "private")
    task = db.create_task(conn, title="Buy milk", tags=["private"], due_date="2026-08-10")
    assert task["id"] == 1
    assert task["status"] == "open"
    assert task["tags"] == ["private"]
    assert task["workspace"] == "private"
    assert db.get_task(conn, 1)["title"] == "Buy milk"
    assert db.get_task(conn, 999) is None


def test_unknown_tag_rejected(conn):
    with pytest.raises(ValueError, match="Unknown tag"):
        db.create_task(conn, title="A", tags=["nope"])
    _allow(conn, "ok")
    task = db.create_task(conn, title="A", tags=["ok"])
    with pytest.raises(ValueError, match="Unknown tag"):
        db.update_task(conn, task["id"], tags=["ok", "nope"])


def test_workspaces(conn):
    db.create_task(conn, title="Home thing")
    db.create_task(conn, title="Work thing", workspace="work")
    assert [t["title"] for t in db.list_tasks(conn, workspace="work")] == ["Work thing"]
    assert [t["title"] for t in db.list_tasks(conn, workspace="private")] == ["Home thing"]
    with pytest.raises(ValueError, match="Workspace"):
        db.create_task(conn, title="X", workspace="garage")

    moved = db.update_task(conn, 1, workspace="work")
    assert moved["workspace"] == "work"
    assert len(db.list_tasks(conn, workspace="work")) == 2


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
    _allow(conn, "private", "work")
    db.create_task(conn, title="Fix bike", tags=["private"], due_date="2026-01-01")
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


def test_allowed_tags_crud(conn):
    _allow(conn, "b", "a", "  #c  ")
    assert db.allowed_tags(conn) == ["a", "b", "c"]
    db.add_allowed_tag(conn, "a")  # idempotent
    assert db.allowed_tags(conn) == ["a", "b", "c"]
    with pytest.raises(ValueError):
        db.add_allowed_tag(conn, "   ")


def test_remove_tag_strips_from_tasks(conn):
    _allow(conn, "keep", "drop")
    task = db.create_task(conn, title="A", tags=["keep", "drop"])
    assert db.remove_allowed_tag(conn, "drop") is True
    assert db.remove_allowed_tag(conn, "drop") is False
    assert db.get_task(conn, task["id"])["tags"] == ["keep"]
    assert db.allowed_tags(conn) == ["keep"]


def test_migration_is_idempotent(conn):
    db.migrate(conn)  # second run must not fail or duplicate
    assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == len(
        db.MIGRATIONS
    )


def test_migration_from_v1(tmp_path):
    # simulate a database created before workspaces/allowed_tags existed
    import sqlite3

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.row_factory = sqlite3.Row
    old.executescript(db.MIGRATIONS[0])
    old.execute(
        "INSERT INTO tasks (title, created_at, updated_at) VALUES ('legacy', 't', 't')"
    )
    old.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    old.execute("INSERT INTO schema_version (version) VALUES (1)")
    old.commit()
    old.close()

    conn = db.connect(path)
    task = db.get_task(conn, 1)
    assert task["title"] == "legacy"
    assert task["workspace"] == "private"
    assert db.allowed_tags(conn) == []
    conn.close()


def test_migration_v3_renames_home_to_private(tmp_path):
    """A live database (tasks + rules in 'home') must carry over to 'private'."""
    import sqlite3

    path = str(tmp_path / "v3.db")
    old = sqlite3.connect(path)
    for script in db.MIGRATIONS[:3]:
        old.executescript(script)
    old.execute(
        """INSERT INTO tasks (title, workspace, status, priority, tags, created_at, updated_at)
           VALUES ('Old home task', 'home', 'done', 'high', '["x"]', 't', 't')"""
    )
    old.execute(
        """INSERT INTO tasks (title, workspace, created_at, updated_at)
           VALUES ('Old work task', 'work', 't', 't')"""
    )
    old.execute(
        """INSERT INTO recurring (title, workspace, freq, next_run, created_at, updated_at)
           VALUES ('Old home rule', 'home', 'daily', '2026-09-01', 't', 't')"""
    )
    old.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    old.execute("INSERT INTO schema_version (version) VALUES (3)")
    old.commit()
    old.close()

    conn = db.connect(path)
    tasks = {t["title"]: t for t in db.list_tasks(conn)}
    assert tasks["Old home task"]["workspace"] == "private"
    assert tasks["Old work task"]["workspace"] == "work"
    # unrelated columns survive the table rebuild
    assert tasks["Old home task"]["status"] == "done"
    assert tasks["Old home task"]["priority"] == "high"
    assert tasks["Old home task"]["tags"] == ["x"]
    assert db.get_recurring(conn, 1)["workspace"] == "private"
    # and the new constraint is in force
    with pytest.raises(ValueError):
        db.create_task(conn, title="nope", workspace="home")
    conn.close()
