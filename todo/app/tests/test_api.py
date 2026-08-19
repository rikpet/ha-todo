def test_health_reports_version(client):
    from todo_app import __version__

    assert client.get("/health").json() == {"status": "ok", "version": __version__}


def test_web_ui_shows_version(client):
    from todo_app import __version__

    assert f"v{__version__}" in client.get("/").text


def test_tag_endpoints(client):
    assert client.get("/api/v1/tags").json() == []
    assert client.post("/api/v1/tags", json={"name": "errands"}).status_code == 201
    assert client.post("/api/v1/tags", json={"name": "work"}).json() == ["errands", "work"]
    assert client.delete("/api/v1/tags/errands").status_code == 204
    assert client.delete("/api/v1/tags/errands").status_code == 404
    assert client.get("/api/v1/tags").json() == ["work"]


def test_unknown_tag_rejected(client):
    response = client.post("/api/v1/tasks", json={"title": "x", "tags": ["random"]})
    assert response.status_code == 422
    assert "Unknown tag" in response.json()["detail"]


def test_workspaces(client):
    assert client.get("/api/v1/workspaces").json() == ["private", "work"]
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
    c.post("/api/v1/tags", json={"name": "private"})
    c.post("/api/v1/tags", json={"name": "work"})
    c.post("/api/v1/tasks", json={"title": "Alpha", "tags": ["private"]})
    c.post("/api/v1/tasks", json={"title": "Beta", "tags": ["work"]})
    assert len(c.get("/api/v1/tasks", params={"tag": "private"}).json()) == 1
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
    # active workspace is private, but the task goes to work
    c.post("/tasks/new", data={"title": "For the office", "task_workspace": "work",
                               "workspace": "private"})
    assert "For the office" not in c.get("/", params={"workspace": "private"}).text
    assert "For the office" in c.get("/", params={"workspace": "work"}).text


def test_web_add_defaults_to_viewed_workspace(client):
    # no task_workspace field: the task must land in the workspace being viewed,
    # not a fixed default (regression: tasks vanished from the Work tab)
    c = client
    c.post("/tasks/new", data={"title": "Typed on the work tab", "workspace": "work"})
    assert "Typed on the work tab" in c.get("/", params={"workspace": "work"}).text
    assert "Typed on the work tab" not in c.get("/", params={"workspace": "private"}).text


def test_add_form_resyncs_workspace_selector(client):
    # the add form must re-point its selector at the active tab after reset()
    page = client.get("/").text
    assert "syncWorkspace()" in page
    assert "this.reset(); syncWorkspace();" in page


def test_pwa_manifest_and_icons(client):
    page = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc"}).text
    assert '/api/hassio_ingress/abc/static/manifest.json' in page
    assert '/api/hassio_ingress/abc/static/apple-touch-icon.png' in page
    assert 'apple-mobile-web-app-capable' in page
    assert client.get("/static/manifest.json").status_code == 200
    assert client.get("/static/apple-touch-icon.png").status_code == 200
    assert client.get("/static/icon-512.png").status_code == 200


def test_mobile_bottom_bar_styles(client):
    """The workspace tabs dock to the bottom on narrow screens (fixed bar)."""
    css = client.get("/static/app.css").text
    assert "@media (max-width: 640px)" in css
    mobile = css.split("@media (max-width: 640px)", 1)[1]
    assert "position: fixed" in mobile
    assert "env(safe-area-inset-bottom" in mobile  # clears the iPhone home indicator
    # the tabs must stay inside #filters so htmx keeps submitting the workspace
    page = client.get("/").text
    filters_form = page.split('id="filters"', 1)[1].split("</form>", 1)[0]
    assert "ws-tabs" in filters_form
    assert "viewport-fit=cover" in page


def test_mobile_zoom_is_disabled(client):
    page = client.get("/").text
    viewport = page.split('name="viewport" content="', 1)[1].split('"', 1)[0]
    assert "maximum-scale=1" in viewport
    assert "user-scalable=no" in viewport
    css = client.get("/static/app.css").text
    # iOS auto-zooms a focused field under 16px; !important is needed to beat
    # the class-scoped component rules
    assert "font-size: 16px !important;" in css
    assert "touch-action: manipulation" in css


def test_no_horizontal_scrolling(client):
    css = client.get("/static/app.css").text
    head = css.split("* { box-sizing", 1)[1][:400]
    assert "overflow-x: hidden" in head
    assert "max-width: 100%" in head


def test_static_links_are_cache_busted(client):
    from todo_app import __version__

    page = client.get("/")
    assert f"/static/app.css?v={__version__}" in page.text
    assert f"/static/htmx.min.js?v={__version__}" in page.text


def test_recurring_api(client):
    c = client
    assert c.get("/api/v1/recurring").json() == []

    created = c.post(
        "/api/v1/recurring",
        json={"title": "Take out bins", "freq": "weekly", "weekday": 0, "workspace": "private"},
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["active"] is True

    assert c.post("/api/v1/recurring/{}/pause".format(rule["id"])).json()["active"] is False
    assert c.post("/api/v1/recurring/{}/resume".format(rule["id"])).json()["active"] is True
    assert c.get(f"/api/v1/recurring/{rule['id']}").json()["title"] == "Take out bins"
    assert c.get("/api/v1/recurring/999").status_code == 404

    # bad rules are rejected
    assert c.post("/api/v1/recurring", json={"title": "x", "freq": "weekly"}).status_code == 422
    assert c.post("/api/v1/recurring", json={"title": "x", "freq": "hourly"}).status_code == 422

    assert c.delete(f"/api/v1/recurring/{rule['id']}").status_code == 204
    assert c.delete(f"/api/v1/recurring/{rule['id']}").status_code == 404


def test_recurring_run_endpoint_creates_tasks(client):
    c = client
    c.post("/api/v1/recurring", json={"title": "Daily thing", "freq": "daily"})
    created = c.post("/api/v1/recurring/run").json()
    assert [t["title"] for t in created] == ["Daily thing"]
    assert c.post("/api/v1/recurring/run").json() == []  # idempotent
    assert "Daily thing" in c.get("/").text


def test_recurring_web_flow(client):
    c = client
    assert "Nothing repeats yet" in c.get("/").text

    r = c.post("/recurring/new", data={"title": "Weekly review", "freq": "weekly",
                                       "weekday": "4", "interval_n": "1",
                                       "task_workspace": "work", "workspace": "work"})
    assert r.headers.get("HX-Refresh") == "true"
    page = c.get("/", params={"workspace": "work"}).text
    assert "Weekly review" in page
    assert "every week on Friday" in page

    rule_id = c.get("/api/v1/recurring").json()[0]["id"]
    c.post(f"/recurring/{rule_id}/toggle")
    assert c.get("/api/v1/recurring").json()[0]["active"] is False
    c.post(f"/recurring/{rule_id}/toggle")
    assert c.get("/api/v1/recurring").json()[0]["active"] is True

    c.post(f"/recurring/{rule_id}/delete")
    assert c.get("/api/v1/recurring").json() == []


def test_myday_api(client):
    c = client
    today = __import__("todo_app.db", fromlist=["db"]).today_iso()
    assert c.get("/api/v1/myday").json() == []

    flagged = c.post("/api/v1/tasks", json={"title": "Flag me"}).json()
    c.post("/api/v1/tasks", json={"title": "Ignore me"})
    c.post("/api/v1/tasks", json={"title": "Due today", "due_date": today})

    planned = c.post(f"/api/v1/tasks/{flagged['id']}/plan").json()
    assert planned["planned_for"] == today

    listed = [t["title"] for t in c.get("/api/v1/myday").json()]
    assert sorted(listed) == ["Due today", "Flag me"]

    # unflagging removes it again; the due-today one stays
    c.post(f"/api/v1/tasks/{flagged['id']}/unplan")
    assert [t["title"] for t in c.get("/api/v1/myday").json()] == ["Due today"]

    assert c.post("/api/v1/tasks/999/plan").status_code == 404
    assert c.post("/api/v1/tasks/999/unplan").status_code == 404
    assert c.post(f"/api/v1/tasks/{flagged['id']}/plan", params={"day": "nope"}).status_code == 422
    assert c.get("/api/v1/myday", params={"workspace": "garage"}).status_code == 422


def test_myday_web_view(client):
    c = client
    c.post("/tasks/new", data={"title": "Ordinary task", "workspace": "private"})
    # star it from the list
    r = c.post("/tasks/1/plan-toggle", data={"workspace": "private"})
    assert "star-on" in r.text

    page = c.get("/", params={"workspace": "myday"}).text
    assert "Ordinary task" in page
    assert "My Day" in page

    # unstar -> it leaves My Day
    c.post("/tasks/1/plan-toggle", data={"workspace": "private"})
    assert "Ordinary task" not in c.get("/", params={"workspace": "myday"}).text
    assert "Nothing planned for today" in c.get("/", params={"workspace": "myday"}).text


def test_myday_respects_the_status_filter(client):
    """Regression: My Day ignored the filter, so 'Open' still showed finished tasks."""
    c = client
    today = __import__("todo_app.db", fromlist=["db"]).today_iso()
    c.post("/api/v1/tasks", json={"title": "Still open", "due_date": today})
    finished = c.post("/api/v1/tasks", json={"title": "Already done", "due_date": today}).json()
    c.post(f"/api/v1/tasks/{finished['id']}/complete")

    open_view = c.get("/", params={"workspace": "myday", "status": "open"}).text
    assert "Still open" in open_view
    assert "Already done" not in open_view

    done_view = c.get("/", params={"workspace": "myday", "status": "done"}).text
    assert "Already done" in done_view
    assert "Still open" not in done_view

    all_view = c.get("/", params={"workspace": "myday", "status": "all"}).text
    assert "Still open" in all_view and "Already done" in all_view


def test_myday_status_filter_is_visible(client):
    """It must not be hidden - .segmented would override the hidden attribute."""
    page = client.get("/", params={"workspace": "myday"}).text
    filters = page.split('class="filters"', 1)[1].split("</div>", 1)[0]
    assert "hidden" not in filters
    # and the guard that makes [hidden] win is in place for other uses
    assert "[hidden] { display: none !important; }" in client.get("/static/app.css").text


def test_task_added_while_in_myday_is_flagged(client):
    c = client
    c.post("/tasks/new", data={"title": "Typed in My Day", "workspace": "myday",
                               "task_workspace": "work"})
    task = c.get("/api/v1/tasks").json()[0]
    assert task["planned_for"] is not None
    assert task["workspace"] == "work"  # myday is a view, not a workspace
    assert "Typed in My Day" in c.get("/", params={"workspace": "myday"}).text


def test_late_tasks_marked_red(client):
    c = client
    c.post("/api/v1/tasks", json={"title": "Overdue thing", "due_date": "2020-01-01"})
    page = c.get("/", params={"status": "all"}).text
    assert "task-late" in page          # red left accent on the row
    assert "count-late" in page         # "N late" in the counter


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
