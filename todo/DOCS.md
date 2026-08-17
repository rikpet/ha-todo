# Todo add-on

Simple todo list running entirely on your Home Assistant box. SQLite storage in `/data` (survives add-on updates and restarts).

## Web UI

Open **Todo** from the Home Assistant sidebar (Ingress), or browse to `http://<host>:8099` on your LAN.

**Note on access:** the LAN port is unauthenticated — anyone on your network can view and edit tasks. If you don't want that, remove the port mapping in the add-on's network settings; Ingress (behind your HA login) keeps working, but the CLI needs the port.

## Options

| Option | Description |
|--------|-------------|
| `log_level` | `debug` / `info` / `warning` / `error` |

## CLI

On your laptop:

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config --url http://homeassistant.local:8099
todo add "Buy milk" --due 2026-08-10 --priority high --tag home
todo list
todo done 1
```

Run any command without arguments (`todo add`, `todo edit`, `todo done`) to be prompted interactively.

## REST API

Full JSON API under `/api/v1` — see `GET /docs` (OpenAPI) on the LAN port.
