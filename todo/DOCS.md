# Todo add-on

Simple todo list running entirely on your Home Assistant box. SQLite storage in `/data` (survives add-on updates and restarts).

## Web UI

Open **Todo** from the Home Assistant sidebar (Ingress), or browse to `http://<host>:8099` on your LAN.

**Note on access:** the LAN port is unauthenticated — anyone on your network can view and edit tasks. If you don't want that, remove the port mapping in the add-on's network settings; Ingress (behind your HA login) keeps working, but the CLI needs the port.

## Add to your iPhone home screen

The web UI installs as an app-like shortcut (standalone, no browser chrome):

1. Open **Safari** on the iPhone and go to `http://10.150.1.89:8099` (your HA box's IP — the LAN port, not the Ingress URL)
2. Tap the **Share** button → **Add to Home Screen** (Lägg till på hemskärmen)
3. Tap **Add** — a blue "Todo" icon appears on the home screen and opens full-screen

Works the same on Android (Chrome → menu → *Add to home screen*).

## Options

| Option | Description |
|--------|-------------|
| `log_level` | `debug` / `info` / `warning` / `error` |

## CLI

On your laptop:

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config --url http://10.150.1.89:8099   # your HA box's IP
todo tags add home errands            # tags must be configured before use
todo add "Sprint review"              # CLI defaults to the work workspace
todo add "Buy milk" -w home --due 2026-08-10 --priority high --tag home
todo list                             # both workspaces; -w work to filter
todo done 1
```

Run any command without arguments (`todo add`, `todo edit`, `todo done`) to be prompted interactively.

**Updating the CLI** after an add-on update:

```bash
pipx upgrade ha-todo
```

or, if pipx reports it is already up to date:

```bash
pipx install --force "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
```

## REST API

Full JSON API under `/api/v1` — see `GET /docs` (OpenAPI) on the LAN port.
