# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A todo app that runs on a Raspberry Pi 5 as a **Home Assistant add-on**. One
FastAPI service serves three things: a JSON REST API, a server-rendered HTMX web
UI, and the backend for a Typer CLI installed on the user's laptop. Storage is
SQLite. Personal project of Rikard Pettersson; GitHub `rikpet/ha-todo`.

## Layout

```
repository.yaml            HA add-on repository manifest
todo/                      the add-on: config.yaml, build.yaml, Dockerfile, run.sh, DOCS.md, CHANGELOG.md
todo/app/                  the Python package
  src/todo_app/db.py       SQLite layer: migrations, tasks, tags, recurring, My Day
  src/todo_app/models.py   Pydantic request/response models
  src/todo_app/api.py      JSON API under /api/v1
  src/todo_app/web.py      HTMX web routes (returns HTML fragments)
  src/todo_app/main.py     app factory, /health, background scheduler + mail poller
  src/todo_app/mail.py     IMAP polling: mail -> task (parsing, subject syntax, import log)
  src/todo_app/mcp_server.py  stdio MCP server (`todo mcp`) over the REST API
  src/todo_app/worker.py   `todo claude work`: runs Claude Code on tasks handed to Claude
  src/todo_app/markdown.py safe Markdown subset for Claude's answers in the web UI
  src/todo_app/cli.py      the `todo` command
  templates/ static/       Jinja2 + vendored htmx/CSS (no build step, no CDN)
  tests/                   pytest (214 tests)
```

## Development

```bash
cd todo/app
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest tests -q
```

Run the server with `uvicorn todo_app.main:app --port 8099` (set `TODO_DB_PATH`
to a scratch file). Prefer driving the real UI in a browser over trusting tests
alone — several bugs here were only visible in a live page (see Gotchas).

## Conventions

**Versioning.** The version lives in three files and they must agree:
`todo/config.yaml`, `todo/app/pyproject.toml`, `todo/app/src/todo_app/__init__.py`.
Bump all three, add a user-facing entry to `todo/CHANGELOG.md`, then commit. HA
only offers an update when `config.yaml` changes, and the CHANGELOG is what the
user sees in the update dialog.

**Migrations are append-only.** `db.MIGRATIONS` is a list; the index is the
schema version. Never edit an existing entry — users have live databases. Add a
new one. SQLite cannot alter a CHECK constraint, so changing an enum means
rebuilding the table and copying rows (migration 4 is the worked example,
including recreating the indexes).

**Changelog voice.** Written for the user, not the developer: what changed and
what it means for them. Implementation detail belongs in the commit message.

**Commits** are GPG-signed. If signing fails with "No passphrase given", the
agent's cache expired — the user must run the commit themselves; do not bypass
with `--no-gpg-sign`.

## Design decisions worth knowing

**My Day stores a date, not a flag.** `tasks.planned_for` holds the day a task
was planned for. A task is in My Day when `planned_for <= today` or
`due_date <= today`. Carry-over and the "late" red styling therefore fall out of
the data with no nightly job: an unfinished task keeps yesterday's date, which
makes it both still-in-My-Day and late. Don't replace this with a boolean.

**`myday` is a view, not a workspace.** It travels in the same `workspace`
request param as `private`/`work`, but is not a valid value for a task's
workspace column. `_norm_view()` accepts it; `_norm_workspace()` never does.

**The recurring scheduler is deliberately conservative.** Missed runs collapse
into one task (offline for a fortnight must not create 14 copies), and a rule
will not spawn while its previous task is still open. Both are tested — keep
them.

**Mail import keys on Message-ID, not the read flag.** `mail_imports` logs
every message handled (created or rejected). The `\Seen` flag only decides what
gets fetched; another client can clear it, and the log keeps that from creating
a duplicate. Messages are fetched with `BODY.PEEK[]` and flagged only after the
task exists, so a crash mid-pass retries instead of losing mail. Mail options
are read from `/data/options.json` in Python (`TODO_OPTIONS_PATH` overrides it
for local runs), not passed through `run.sh`, so the password never sits in the
environment.

**Claude work bills the subscription, never an API key.** The add-on only
holds the queue (`tasks.claude_state`, `task_notes`); `worker.py` runs
`claude -p` on the user's own machine. Keep its guards: strip
`API_BILLING_VARS` from Claude's env (but keep `CLAUDE_CODE_OAUTH_TOKEN`, a
subscription token), refuse when `claude auth status` reports API-key or cloud
auth, never pass `--bare` (it accepts only `ANTHROPIC_API_KEY`), and use
`--restricted` when available (ignores settings files, so no `apiKeyHelper`,
and confines file tools to the task folder). The prompt goes in on stdin so
Windows `.cmd` quoting cannot mangle it. Claims are atomic SQL updates;
a claim older than `CLAUDE_STALE_MINUTES` is offered again. Claude never sets
a task done: `finish` leaves it in `review`, and completing a task clears
`claude_state` while keeping the notes.

**Tasks Claude adds are marked, never mixed with yours.** `tasks.created_by`
(`me`/`claude`, migration 8) and `origin_task_id` (the task Claude was working
on). The MCP `create_task` always sends `created_by: claude`; its origin is
`from_task_id`, else `TODO_TASK_ID`, which the worker sets per run. Deleting the
origin only clears the link. `my_day` sets `planned_for` to today.

**One Claude account per workspace is soft separation.** `--workspace` on
the worker scopes the queue and the claim (the API checks the claim too), and
`TODO_WORKSPACE` confines every MCP tool, with an out-of-scope task answered as
"not found". The worker also denies `WebFetch(domain:<add-on host>)`. Bash can
still reach the unauthenticated LAN API; that is accepted and documented. The
worker refuses add-ons older than `MIN_SERVER_VERSION`, which would ignore the
workspace parameter.

**The MCP server has no dependencies on purpose.** It is ~100 lines of
newline-delimited JSON-RPC (initialize, ping, tools/list, tools/call) so the
add-on image and Windows installs need no `mcp` package. `claude mcp list`
checks the handshake without spending any usage.

**Web routes return HTML fragments** for htmx to swap, except tag and recurring
mutations, which return `204` + `HX-Refresh: true` because those change several
regions of the page at once.

## Gotchas (each one cost a real bug)

- **Ingress path.** Do *not* set `scope["root_path"]` from `X-Ingress-Path`. The
  HA proxy strips the prefix from the path, so a root_path that isn't a genuine
  path prefix breaks Starlette's `Mount`, and every static file 404s. Templates
  read the header directly to build prefixed URLs.
- **Static caching.** All asset links carry `?v={{ app_version }}`. Without it,
  browsers serve the previous version's CSS after an add-on update and the UI
  looks broken/unstyled.
- **CSS specificity beats media queries.** Media queries add no specificity. A
  bare `input { font-size: 16px }` loses to `.filters select { font-size: .85rem }`,
  and the `hidden` attribute loses to `.segmented { display: inline-flex }`.
  Both needed `!important`; both shipped broken first.
- **iOS auto-zoom** happens when a focused field is under 16px. That, not pinch
  zoom, is usually the "it zoomed in" complaint.
- **Windows console is cp1252.** CLI output must not contain raw unicode — use
  the `_safe()` helper (`CHECK`, `CROSS`, `STAR`, `DONE_MARK`). Em dashes and
  ellipses in CLI strings render as `?`.
- **SQLite across threads.** FastAPI runs sync endpoints in a threadpool, so the
  shared connection is opened with `check_same_thread=False` (WAL mode, one
  connection on `app.state.db`).
- **App logging.** uvicorn configures only its own loggers, so `todo_app`
  INFO lines used to vanish. `main._use_uvicorn_logging()` borrows the handler
  of the `uvicorn` logger (not `uvicorn.error`, which has none of its own).
- **Bash heredocs eat a backslash level.** Writing Python that contains `\n`
  escapes via a heredoc silently produces real newlines and a syntax error.
  Prefer messages without embedded newlines, or patch with a script that avoids
  escapes.

## Deployment

The user installs the add-on in HA from this repo's GitHub URL. After pushing,
HA needs `ha store reload` (or Add-on Store → ⋮ → Check for updates) before it
offers the new version.

The CLI is installed with pipx **from a local clone path**, because Microsoft
Store Python breaks pip's git-URL installs. `todo upgrade` reuses whatever
source pipx recorded and handles the pull + reinstall.
