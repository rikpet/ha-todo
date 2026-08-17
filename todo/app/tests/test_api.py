def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_tag_endpoints(client):
    assert client.get("/api/v1/tags").json() == []
    assert client.post("/api/v1/tags", json={"name": "home"}).status_code == 201
    assert client.post("/api/v1/tags", json={"name": "work"}).json() == ["home", "work"]
    assert client.delete("/api/v1/tags/home").status_code == 204
    assert client.delete("/api/v1/tags/home").status_code == 404
    assert client.get("/api/v1/tags").json() == ["work"]


def test_unknown_tag_rejected(client):
    response = client.post("/api/v1/tasks", json={"title": "x", "tags": ["random"]})
    assert response.status_code == 422
    assert "Unknown tag" in response.json()["detail"]


def test_workspaces(client):
    assert client.get("/api/v1/workspaces").json() == ["home", "work"]
    client.post("/api/v1/tasks", json={"title": "Home thing"})
    client.post("/api/v1/tasks", json={"title": "Work thing", "workspace": "work"})

    work = client.get("/api/v1/tasks", params={"workspace": "work"}).json()
    assert [t["title"] for t in work] == ["Work thing"]
    assert client.get("/api/v1/tasks", params={"workspace": "garage"}).status_code == 422
    assert client.post("/api/v1/tasks", json={"title": "x", "workspace": "garage"}).status_code == 422

    moved = client.patch("/api/v1/tasks/1", json={"workspace": "work"})
    assert moved.json()["workspace"] == "work"


def test_crud_roundtrip(client):
    c = client
    c.post("/api/v1/tags", json={"name": "x"})
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
    c.post("/api/v1/tags", json={"name": "home"})
    c.post("/api/v1/tags", json={"name": "work"})
    c.post("/api/v1/tasks", json={"title": "Alpha", "tags": ["home"]})
    c.post("/api/v1/tasks", json={"title": "Beta", "tags": ["work"]})
    assert len(c.get("/api/v1/tasks", params={"tag": "home"}).json()) == 1
    assert len(c.get("/api/v1/tasks", params={"search": "bet"}).json()) == 1


def test_web_ui_flow(client):
    c = client
    page = c.get("/")
    assert "Add a task" in page.text
    assert "No tags configured" in page.text

    # configure tags through the web endpoints (they ask htmx for a page refresh)
    r = c.post("/tags/new", data={"name": "a"})
    assert r.headers.get("HX-Refresh") == "true"
    c.post("/tags/new", data={"name": "b"})

    c.post("/tasks/new", data={"title": "From web", "priority": "high", "tags": ["a", "b"]})
    page = c.get("/")
    assert "From web" in page.text
    assert "#a" in page.text

    c.post("/tasks/1/toggle")
    # done tasks are hidden by default; visible under the All filter
    assert "task-done" not in c.get("/").text
    assert "task-done" in c.get("/", params={"status": "all"}).text

    edit = c.get("/tasks/1/edit")
    assert 'value="From web"' in edit.text

    c.post("/tasks/1/edit", data={"title": "Edited", "priority": "low", "due_date": ""})
    assert "Edited" in c.get("/", params={"status": "all"}).text

    # tag removal strips it everywhere
    c.post("/tags/a/delete")
    assert "#a" not in c.get("/", params={"status": "all"}).text

    c.post("/tasks/1/delete")
    assert "Edited" not in c.get("/", params={"status": "all"}).text


def test_web_hides_done_by_default(client):
    c = client
    c.post("/tasks/new", data={"title": "Stays open"})
    c.post("/tasks/new", data={"title": "Gets finished"})
    c.post("/tasks/2/toggle")
    page = c.get("/").text
    assert "Stays open" in page
    assert "Gets finished" not in page
    assert "Gets finished" in c.get("/", params={"status": "done"}).text


def test_web_add_to_other_workspace(client):
    c = client
    # active workspace is home, but the task goes to work
    c.post("/tasks/new", data={"title": "For the office", "task_workspace": "work",
                               "workspace": "home"})
    assert "For the office" not in c.get("/", params={"workspace": "home"}).text
    assert "For the office" in c.get("/", params={"workspace": "work"}).text


def test_static_links_are_cache_busted(client):
    from todo_app import __version__

    page = client.get("/")
    assert f"/static/app.css?v={__version__}" in page.text
    assert f"/static/htmx.min.js?v={__version__}" in page.text


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
