from datetime import datetime, timedelta, timezone

import pytest

from todo_app import db


def make(conn, title="Compare power contracts"):
    return db.create_task(conn, title=title)


# ---------- db ----------

def test_give_to_claude_queues_and_records_instructions(conn):
    task = make(conn)
    queued = db.give_to_claude(conn, task["id"], "Only fixed-price offers")
    assert queued["claude_state"] == "queued"
    [note] = db.list_notes(conn, task["id"])
    assert note["author"] == "me" and note["body"] == "Only fixed-price offers"
    assert db.claude_queue(conn)[0]["id"] == task["id"]


def test_give_without_instructions_adds_no_note(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"], "   ")
    assert db.list_notes(conn, task["id"]) == []


def test_claim_is_exclusive(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    first = db.claim_for_claude(conn, task["id"])
    assert first["claude_state"] == "working" and first["claude_claimed_at"]
    assert db.claim_for_claude(conn, task["id"]) is None  # a second worker loses
    assert db.claude_queue(conn) == []


def test_abandoned_claim_is_offered_again(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    db.claim_for_claude(conn, task["id"])
    long_ago = (datetime.now(timezone.utc) - timedelta(minutes=db.CLAUDE_STALE_MINUTES + 1))
    conn.execute("UPDATE tasks SET claude_claimed_at = ? WHERE id = ?",
                 (long_ago.isoformat(timespec="seconds"), task["id"]))
    assert [t["id"] for t in db.claude_queue(conn)] == [task["id"]]
    assert db.claim_for_claude(conn, task["id"]) is not None


def test_finish_puts_answer_on_thread_and_waits_for_review(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"], "Go")
    db.claim_for_claude(conn, task["id"])
    done = db.finish_for_claude(conn, task["id"], "Tibber is cheapest.")
    assert done["claude_state"] == "review"
    assert done["status"] == "open"  # Claude never closes a task itself
    assert [(n["author"], n["body"]) for n in db.list_notes(conn, task["id"])] == [
        ("me", "Go"), ("claude", "Tibber is cheapest."),
    ]


def test_finish_as_failed(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    assert db.finish_for_claude(conn, task["id"], "No access", "failed")["claude_state"] == "failed"


def test_finish_refused_after_take_back(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    db.claim_for_claude(conn, task["id"])
    db.take_back_from_claude(conn, task["id"])
    with pytest.raises(ValueError, match="not handed to Claude"):
        db.finish_for_claude(conn, task["id"], "late answer")
    assert db.list_notes(conn, task["id"]) == []


def test_reply_requeues_review_task(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    db.finish_for_claude(conn, task["id"], "Draft 1")
    again = db.give_to_claude(conn, task["id"], "Shorter please")
    assert again["claude_state"] == "queued"
    assert len(db.list_notes(conn, task["id"])) == 2


def test_cannot_give_done_or_in_progress_task(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    db.claim_for_claude(conn, task["id"])
    with pytest.raises(ValueError, match="working on this task"):
        db.give_to_claude(conn, task["id"], "more")
    done = make(conn, "Done already")
    db.update_task(conn, done["id"], status="done")
    with pytest.raises(ValueError, match="reopen it"):
        db.give_to_claude(conn, done["id"])


def test_completing_a_task_ends_the_hand_over_but_keeps_notes(conn):
    task = make(conn)
    db.give_to_claude(conn, task["id"])
    db.finish_for_claude(conn, task["id"], "Answer")
    closed = db.update_task(conn, task["id"], status="done")
    assert closed["claude_state"] is None
    assert len(db.list_notes(conn, task["id"])) == 1


def test_deleting_a_task_deletes_its_notes(conn):
    task = make(conn)
    db.add_note(conn, task["id"], "me", "hello")
    db.delete_task(conn, task["id"])
    assert conn.execute("SELECT COUNT(*) FROM task_notes").fetchone()[0] == 0


def test_list_tasks_filters_on_claude_state(conn):
    a, b, _ = make(conn, "a"), make(conn, "b"), make(conn, "c")
    db.give_to_claude(conn, a["id"])
    db.give_to_claude(conn, b["id"])
    db.finish_for_claude(conn, b["id"], "x")
    assert {t["title"] for t in db.list_tasks(conn, claude="any")} == {"a", "b"}
    assert [t["title"] for t in db.list_tasks(conn, claude="review")] == ["b"]


def test_queue_is_oldest_hand_over_first(conn):
    first, second = make(conn, "first"), make(conn, "second")
    db.give_to_claude(conn, second["id"])
    conn.execute("UPDATE tasks SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                 (second["id"],))
    db.give_to_claude(conn, first["id"])
    assert [t["title"] for t in db.claude_queue(conn)] == ["second", "first"]


# ---------- API ----------

def test_api_round_trip(client):
    task = client.post("/api/v1/tasks", json={"title": "Plan the trip"}).json()
    tid = task["id"]
    r = client.post(f"/api/v1/tasks/{tid}/claude", json={"instructions": "Budget 10k"})
    assert r.status_code == 200 and r.json()["claude_state"] == "queued"
    assert [t["id"] for t in client.get("/api/v1/claude/queue").json()] == [tid]

    assert client.post(f"/api/v1/tasks/{tid}/claude/claim").json()["claude_state"] == "working"
    assert client.post(f"/api/v1/tasks/{tid}/claude/claim").status_code == 409

    r = client.post(f"/api/v1/tasks/{tid}/claude/finish", json={"result": "Itinerary..."})
    assert r.json()["claude_state"] == "review"
    notes = client.get(f"/api/v1/tasks/{tid}/notes").json()
    assert [(n["author"], n["body"]) for n in notes] == [("me", "Budget 10k"),
                                                         ("claude", "Itinerary...")]
    assert client.get("/api/v1/tasks", params={"claude": "review"}).json()[0]["id"] == tid

    assert client.delete(f"/api/v1/tasks/{tid}/claude").json()["claude_state"] is None


def test_api_give_without_body(client):
    tid = client.post("/api/v1/tasks", json={"title": "x"}).json()["id"]
    assert client.post(f"/api/v1/tasks/{tid}/claude").json()["claude_state"] == "queued"


def test_api_errors(client):
    assert client.post("/api/v1/tasks/999/claude").status_code == 404
    assert client.post("/api/v1/tasks/999/claude/claim").status_code == 404
    assert client.get("/api/v1/tasks/999/notes").status_code == 404
    tid = client.post("/api/v1/tasks", json={"title": "x"}).json()["id"]
    r = client.post(f"/api/v1/tasks/{tid}/claude/finish", json={"result": "nobody asked"})
    assert r.status_code == 409
    assert client.get("/api/v1/tasks", params={"claude": "bogus"}).status_code == 422
    r = client.post(f"/api/v1/tasks/{tid}/notes", json={"body": "hi", "author": "robot"})
    assert r.status_code == 422


def test_api_notes(client):
    tid = client.post("/api/v1/tasks", json={"title": "x"}).json()["id"]
    r = client.post(f"/api/v1/tasks/{tid}/notes", json={"body": "Progress: halfway",
                                                        "author": "claude"})
    assert r.status_code == 201 and r.json()["author"] == "claude"
    assert len(client.get(f"/api/v1/tasks/{tid}/notes").json()) == 1


# ---------- web UI ----------

def test_web_give_reply_accept(conn, client):
    task = make(conn, "Plan the trip")
    panel = client.get(f"/tasks/{task['id']}/claude")
    assert panel.status_code == 200 and "Give to Claude" in panel.text

    table = client.post(f"/tasks/{task['id']}/claude/give",
                        data={"instructions": "Budget 10k", "workspace": "private"})
    assert "Claude: queued" in table.text
    assert 'hx-trigger="every 15s' in table.text  # polls while Claude has work

    db.claim_for_claude(conn, task["id"])
    working = client.get(f"/tasks/{task['id']}/claude").text
    assert "working on this right now" in working and "Give to Claude" not in working

    db.finish_for_claude(conn, task["id"], "See https://example.com/trip. <b>Day 1</b>")
    review = client.get(f"/tasks/{task['id']}/claude").text
    assert "Accept &amp; mark done" in review and "Send reply" in review
    assert '<a href="https://example.com/trip"' in review  # trailing dot left out
    assert "&lt;b&gt;Day 1&lt;/b&gt;" in review  # answers are escaped, not rendered as HTML
    table = client.get("/tasks/table", params={"workspace": "private"}).text
    assert "Claude answered" in table and "every 15s" not in table

    client.post(f"/tasks/{task['id']}/claude/give", data={"instructions": "Cheaper"})
    assert db.get_task(conn, task["id"])["claude_state"] == "queued"
    db.finish_for_claude(conn, task["id"], "Cheaper plan")
    client.post(f"/tasks/{task['id']}/claude/accept", data={"workspace": "private"})
    done = db.get_task(conn, task["id"])
    assert done["status"] == "done" and done["claude_state"] is None


def test_web_take_back_and_done_task(conn, client):
    task = make(conn)
    client.post(f"/tasks/{task['id']}/claude/give", data={})
    client.post(f"/tasks/{task['id']}/claude/back", data={})
    assert db.get_task(conn, task["id"])["claude_state"] is None
    db.update_task(conn, task["id"], status="done")
    assert "Reopen it" in client.get(f"/tasks/{task['id']}/claude").text
    # a stale form post on a done task changes nothing
    client.post(f"/tasks/{task['id']}/claude/give", data={"instructions": "x"})
    assert db.get_task(conn, task["id"])["claude_state"] is None
    assert client.get("/tasks/999/claude").status_code == 404


# ---------- workspaces ----------

def test_queue_and_claim_respect_workspace(conn, client):
    private = make(conn, "private one")
    work = db.create_task(conn, title="work one", workspace="work")
    db.give_to_claude(conn, private["id"])
    db.give_to_claude(conn, work["id"])
    assert [t["id"] for t in db.claude_queue(conn, workspace="work")] == [work["id"]]
    assert db.claim_for_claude(conn, private["id"], workspace="work") is None

    r = client.post(f"/api/v1/tasks/{private['id']}/claude/claim", params={"workspace": "work"})
    assert r.status_code == 409 and "is in private" in r.json()["detail"]
    q = client.get("/api/v1/claude/queue", params={"workspace": "private"}).json()
    assert [t["id"] for t in q] == [private["id"]]
    assert client.get("/api/v1/claude/queue", params={"workspace": "home"}).status_code == 422
    ok = client.post(f"/api/v1/tasks/{work['id']}/claude/claim", params={"workspace": "work"})
    assert ok.json()["claude_state"] == "working"


# ---------- tasks Claude adds ----------

def test_claude_created_task_links_to_its_origin(conn):
    origin = make(conn, "Compare power contracts")
    added = db.create_task(conn, title="Cancel Fortum", created_by="claude",
                           origin_task_id=origin["id"])
    assert added["created_by"] == "claude" and added["origin_task_id"] == origin["id"]
    assert make(conn, "mine")["created_by"] == "me"
    assert [t["id"] for t in db.list_followups(conn, origin["id"])] == [added["id"]]
    with pytest.raises(ValueError, match="Task 999 not found"):
        db.create_task(conn, title="x", origin_task_id=999)
    with pytest.raises(ValueError, match="created_by"):
        db.create_task(conn, title="x", created_by="robot")


def test_deleting_the_origin_keeps_the_follow_up(conn):
    origin = make(conn)
    added = db.create_task(conn, title="Follow-up", created_by="claude",
                           origin_task_id=origin["id"])
    db.delete_task(conn, origin["id"])
    kept = db.get_task(conn, added["id"])
    assert kept["created_by"] == "claude" and kept["origin_task_id"] is None


def test_api_create_and_list_followups(client):
    origin = client.post("/api/v1/tasks", json={"title": "Plan trip"}).json()
    r = client.post("/api/v1/tasks", json={"title": "Book train", "created_by": "claude",
                                           "origin_task_id": origin["id"]})
    assert r.status_code == 201 and r.json()["created_by"] == "claude"
    assert client.post("/api/v1/tasks", json={"title": "x", "origin_task_id": 999}).status_code == 422
    followups = client.get(f"/api/v1/tasks/{origin['id']}/followups").json()
    assert [f["title"] for f in followups] == ["Book train"]
    assert client.get("/api/v1/tasks/999/followups").status_code == 404


def test_web_shows_who_added_a_task(conn, client):
    origin = make(conn, "Compare power contracts")
    db.create_task(conn, title="Cancel Fortum", created_by="claude",
                   origin_task_id=origin["id"], planned_for=db.today_iso())
    db.create_task(conn, title="Asked for in chat", created_by="claude")
    table = client.get("/tasks/table", params={"workspace": "private"}).text
    assert "✦ Claude · Compare power contracts" in table
    assert table.count("badge-from-claude") == 2
    panel = client.get(f"/tasks/{origin['id']}/claude").text
    assert "Claude added 1 task" in panel and "Cancel Fortum" in panel and "My Day" in panel
