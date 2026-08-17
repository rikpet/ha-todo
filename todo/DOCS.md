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

## Recurring tasks

Open **Recurring tasks** at the bottom of the web UI to add a rule — daily,
weekly on a given weekday, or monthly on a given day, repeating every N periods.
The add-on creates the task automatically on schedule (checked at startup and
every 15 minutes), so nothing depends on you having the app open.

Two behaviours worth knowing:

- If the previous task from a rule is **still open**, no new copy is created — no pile-ups.
- If the add-on was **offline** over several due dates, you get **one** task, not a backlog.

Deleting a rule keeps the tasks it already created. Pausing stops new ones without losing the rule.

From the CLI:

```bash
todo recur add "Ta ut soporna" -f weekly --on monday -w home
todo recur add "Månadsrapport" -f monthly --day 1
todo recur add "Vattna blommorna" -f daily -n 3      # every 3 days
todo recur                                           # list rules
todo recur pause 2 / todo recur resume 2 / todo recur rm 2
```

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
