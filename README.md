# ha-todo

Todo app for Home Assistant on a Raspberry Pi 5 (or any HA OS box):

- **Core**: FastAPI + SQLite, packaged as a Home Assistant add-on
- **Web UI**: server-rendered HTMX app, embedded in the HA sidebar via Ingress
- **CLI**: `todo` command for your laptop, talks to the same API over LAN
- **REST API**: `/api/v1` (OpenAPI docs at `/docs`)

No authentication on the LAN port — the app trusts your home network. Ingress access goes through your normal HA login. If you don't want LAN access, remove the port mapping in the add-on's network settings (the CLI needs it, though).

## Install as a Home Assistant add-on

1. In HA: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add this repository's GitHub URL
3. Install **Todo** and start it
4. Open **Todo** in the sidebar

Data lives in the add-on's `/data/todo.db` and survives updates and restarts.

## CLI on your laptop

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config                       # prompts for the server URL
todo tags add home errands        # tags are curated: configure before use
todo add "Buy milk" --due 2026-08-10 -p high -t home
todo add "Sprint review" -w work  # workspaces: home (default) / work
todo list                         # both workspaces; -w to filter
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

The CLI works against a local dev server with `TODO_URL=http://127.0.0.1:8099 todo list`.

## Layout

```
repository.yaml     HA add-on repository manifest
todo/               the add-on: config.yaml, Dockerfile, run.sh
todo/app/           Python package (server + CLI) and tests
```
