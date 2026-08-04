# ha-todo

Todo app for Home Assistant on a Raspberry Pi 5 (or any HA OS box):

- **Core**: FastAPI + SQLite, packaged as a Home Assistant add-on
- **Web UI**: server-rendered HTMX app, embedded in the HA sidebar via Ingress
- **CLI**: `todo` command for your laptop, talks to the same API over LAN
- **REST API**: `/api/v1` with bearer-token auth (OpenAPI docs at `/docs`)

## Install as a Home Assistant add-on

1. In HA: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add this repository's GitHub URL
3. Install **Todo**, set an `api_token` in the add-on options (needed for LAN/CLI access), start it
4. Open **Todo** in the sidebar

Data lives in the add-on's `/data/todo.db` and survives updates and restarts.

## CLI on your laptop

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config                       # prompts for URL + token
todo add "Buy milk" --due 2026-08-10 -p high -t home
todo list
todo edit 1                       # no flags = interactive walkthrough
todo done 1
todo rm 1
```

Every command prompts for whatever you leave out (TTY only — in scripts, missing input is a clean error instead).

## Development

```bash
cd todo/app
python -m venv .venv && .venv/Scripts/activate     # or bin/activate on Linux
pip install -e ".[dev]"
pytest
uvicorn todo_app.main:app --port 8099              # web UI on http://127.0.0.1:8099
```

Without `TODO_API_TOKEN` set, the server refuses non-ingress requests; for local dev:

```bash
TODO_API_TOKEN=dev uvicorn todo_app.main:app --port 8099
```

then open http://127.0.0.1:8099/?token=dev — the token is required once when not accessed via Ingress (it's stored as a cookie afterwards). Same on the LAN: `http://<pi>:8099/?token=YOUR_TOKEN`. The CLI works with `TODO_URL=http://127.0.0.1:8099 TODO_TOKEN=dev todo list`.

## Layout

```
repository.yaml     HA add-on repository manifest
todo/               the add-on: config.yaml, Dockerfile, run.sh
todo/app/           Python package (server + CLI) and tests
```
