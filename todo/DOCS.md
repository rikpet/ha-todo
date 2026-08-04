# Todo add-on

Simple todo list running entirely on your Home Assistant box. SQLite storage in `/data` (survives add-on updates and restarts).

## Web UI

Open **Todo** from the Home Assistant sidebar (Ingress — no separate login), or browse to `http://<host>:8099` on your LAN if you configured an `api_token`.

## Options

| Option | Description |
|--------|-------------|
| `api_token` | Bearer token for LAN access (web UI on port 8099 and the CLI). Leave empty to disable LAN access entirely — Ingress keeps working. Pick a long random string, e.g. `openssl rand -hex 24`. |
| `log_level` | `debug` / `info` / `warning` / `error` |

## CLI

On your laptop:

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config --url http://homeassistant.local:8099 --token YOUR_TOKEN
todo add "Buy milk" --due 2026-08-10 --priority high --tag home
todo list
todo done 1
```

Run any command without arguments (`todo add`, `todo edit`, `todo done`) to be prompted interactively.

## REST API

Full JSON API under `/api/v1` — see `GET /docs` (OpenAPI) on the LAN port. Authenticate with `Authorization: Bearer <api_token>`.
