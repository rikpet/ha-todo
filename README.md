# ha-todo

Todo app for Home Assistant on a Raspberry Pi 5 (or any HA OS box):

- **Core**: FastAPI + SQLite, packaged as a Home Assistant add-on
- **Web UI**: server-rendered HTMX app, embedded in the HA sidebar via Ingress
- **CLI**: `todo` command for your laptop, talks to the same API over LAN
- **REST API**: `/api/v1` (OpenAPI docs at `/docs`)
- **My Day**: star what you plan to do today; due-today tasks join automatically, unfinished ones carry over in red
- **Recurring tasks**: daily/weekly/monthly rules that create tasks automatically
- **Workspaces**: tasks are split into *Private* and *Work*

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
todo tags add hushall errands     # tags are curated: configure before use
todo add "Sprint review"          # CLI defaults to the work workspace
todo add "Buy milk" -w private --due 2026-08-10 -p high -t errands
todo list                         # both workspaces; -w to filter
todo edit 1                       # no flags = interactive walkthrough
todo done 1
todo rm 1
```

### Updating the CLI

```bash
todo upgrade
```

It pulls the clone it was installed from, reinstalls through pipx, and prints
the old and new version. `todo upgrade --check` compares versions without
installing; `--no-pull` skips the git pull.

If the upgrade cannot replace a running executable (Windows locks it
occasionally), it says so and prints the one command to finish the job from a
terminal where `todo` is not running.

`todo --version` shows the CLI version alongside the server's and warns when the
two have drifted apart. The web UI shows its version in the page footer.

**Microsoft Store Python note:** pip's git-URL installs can fail with
`fatal: Unable to read current working directory` (the Store Python's
filesystem virtualization confuses git). Install from a local clone instead:

```bash
git clone https://github.com/rikpet/ha-todo.git
pipx install ./ha-todo/todo/app
```

## Layout

```
repository.yaml     HA add-on repository manifest
todo/               the add-on: config.yaml, Dockerfile, run.sh
todo/app/           Python package (server + CLI) and tests
```
