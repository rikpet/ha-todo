def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_crud_roundtrip(client):
    c = client
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


def test_validation(client):
    c = client
    assert c.post("/api/v1/tasks", json={"title": ""}).status_code == 422
    assert c.post("/api/v1/tasks", json={"title": "x", "due_date": "not-a-date"}).status_code == 422
    assert c.post("/api/v1/tasks", json={"title": "x", "priority": "urgent"}).status_code == 422
    assert c.get("/api/v1/tasks", params={"status": "bogus"}).status_code == 422


def test_filters_via_api(client):
    c = client
    c.post("/api/v1/tasks", json={"title": "Alpha", "tags": ["home"]})
    c.post("/api/v1/tasks", json={"title": "Beta", "tags": ["work"]})
    assert len(c.get("/api/v1/tasks", params={"tag": "home"}).json()) == 1
    assert len(c.get("/api/v1/tasks", params={"search": "bet"}).json()) == 1
    assert c.get("/api/v1/tags").json() == ["home", "work"]


def test_web_ui_flow(client):
    c = client
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


def test_ingress_path_header_prefixes_urls(client):
    page = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"})
    assert '/api/hassio_ingress/abc/static/htmx.min.js' in page.text
    assert '/api/hassio_ingress/abc/tasks/new' in page.text


def test_static_files_served_under_ingress(client):
    # the ingress proxy strips the prefix from the path but sends the header;
    # static must still resolve (regression: root_path broke Mount routing)
    headers = {"X-Ingress-Path": "/api/hassio_ingress/abc"}
    assert client.get("/static/app.css", headers=headers).status_code == 200
    assert client.get("/static/htmx.min.js", headers=headers).status_code == 200
