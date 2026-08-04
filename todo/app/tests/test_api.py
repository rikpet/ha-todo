from fastapi.testclient import TestClient


def test_health_needs_no_auth(app):
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_lan_requires_token(app, monkeypatch):
    monkeypatch.setenv("TODO_API_TOKEN", "secret-token")
    client = TestClient(app)
    assert client.get("/api/v1/tasks").status_code == 401
    bad = client.get("/api/v1/tasks", headers={"Authorization": "Bearer wrong"})
    assert bad.status_code == 401


def test_lan_disabled_without_token_option(app, monkeypatch):
    monkeypatch.delenv("TODO_API_TOKEN", raising=False)
    response = TestClient(app).get("/api/v1/tasks")
    assert response.status_code == 403


def test_browser_token_query_param_sets_cookie(app, monkeypatch):
    monkeypatch.setenv("TODO_API_TOKEN", "secret-token")
    client = TestClient(app)
    first = client.get("/", params={"token": "secret-token"})
    assert first.status_code == 200
    assert client.cookies.get("todo_token") == "secret-token"
    # follow-up requests authenticate via the cookie alone
    assert client.get("/").status_code == 200
    assert TestClient(app).get("/", params={"token": "wrong"}).status_code == 401


def test_ingress_is_trusted(ingress_client):
    assert ingress_client.get("/api/v1/tasks").status_code == 200
    assert ingress_client.get("/").status_code == 200


def test_crud_roundtrip(client_with_token):
    c = client_with_token
    created = c.post(
        "/api/v1/tasks",
        json={"title": "Test task", "priority": "high", "due_date": "2026-09-01", "tags": ["x"]},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    assert c.get(f"/api/v1/tasks/{task_id}").json()["title"] == "Test task"

    patched = c.patch(f"/api/v1/tasks/{task_id}", json={"title": "Renamed"})
    assert patched.json()["title"] == "Renamed"
    assert patched.json()["priority"] == "high"

    done = c.post(f"/api/v1/tasks/{task_id}/complete")
    assert done.json()["status"] == "done"
    reopened = c.post(f"/api/v1/tasks/{task_id}/reopen")
    assert reopened.json()["status"] == "open"

    assert c.delete(f"/api/v1/tasks/{task_id}").status_code == 204
    assert c.get(f"/api/v1/tasks/{task_id}").status_code == 404


def test_validation(client_with_token):
    c = client_with_token
    assert c.post("/api/v1/tasks", json={"title": ""}).status_code == 422
    assert c.post("/api/v1/tasks", json={"title": "x", "due_date": "not-a-date"}).status_code == 422
    assert c.post("/api/v1/tasks", json={"title": "x", "priority": "urgent"}).status_code == 422
    assert c.get("/api/v1/tasks", params={"status": "bogus"}).status_code == 422


def test_filters_via_api(client_with_token):
    c = client_with_token
    c.post("/api/v1/tasks", json={"title": "Alpha", "tags": ["home"]})
    c.post("/api/v1/tasks", json={"title": "Beta", "tags": ["work"]})
    assert len(c.get("/api/v1/tasks", params={"tag": "home"}).json()) == 1
    assert len(c.get("/api/v1/tasks", params={"search": "bet"}).json()) == 1
    assert c.get("/api/v1/tags").json() == ["home", "work"]


def test_web_ui_flow(ingress_client):
    c = ingress_client
    page = c.get("/")
    assert "Add a task" in page.text

    c.post("/tasks/new", data={"title": "From web", "priority": "high", "tags": "a, b"})
    page = c.get("/")
    assert "From web" in page.text

    c.post("/tasks/1/toggle")
    assert "task-done" in c.get("/").text

    edit = c.get("/tasks/1/edit")
    assert 'value="From web"' in edit.text

    c.post("/tasks/1/edit", data={"title": "Edited", "priority": "low", "tags": "", "due_date": ""})
    assert "Edited" in c.get("/").text

    c.post("/tasks/1/delete")
    assert "Edited" not in c.get("/").text


def test_ingress_path_header_sets_root_path(ingress_client):
    page = ingress_client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert '/api/hassio_ingress/abc/static/htmx.min.js' in page.text
    assert '/api/hassio_ingress/abc/tasks/new' in page.text
