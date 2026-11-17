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

## My Day

The **My Day** tab collects everything you mean to deal with today, from both
workspaces:

- tasks you **star** in the list (the star button on each row)
- tasks **due today**, added automatically
- anything **late** — overdue, or starred on an earlier day and still open

Late items are shown in red with a red edge, and starred leftovers carry the
*carried over* badge. Nothing is lost overnight: an unfinished star simply keeps
its original date and shows up again the next day.

Typing a task while My Day is open plans it for today.

```bash
todo today                 # show My Day
todo today add 12          # star task 12 for today
todo today rm 12           # take it out again
todo add "Ring plumber" --today
```

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
todo recur add "Ta ut soporna" -f weekly --on monday -w private
todo recur add "Månadsrapport" -f monthly --day 1
todo recur add "Vattna blommorna" -f daily -n 3      # every 3 days
todo recur                                           # list rules
todo recur pause 2 / todo recur resume 2 / todo recur rm 2
```

## Tasks from mail

The add-on can watch one mail folder and turn every **unread** message in it into
a task. The subject becomes the title and the body (signature removed) the
description, with the sender noted at the top. Each message is marked as read
once its task exists, and remembered, so it can never become two tasks.

**Use a dedicated folder, not your inbox** — every unread mail in the folder
becomes a task. A filter or rule in your mail account moves the right mail
there, for example everything sent to your plus address `you+todo@gmail.com`.

### Set up

1. Create the folder (Gmail: a label) and a filter that puts mail in it.
2. Create an **app password** for the add-on — your normal password usually
   does not work over IMAP:
   - Gmail: Google account → Security → 2-Step Verification → App passwords.
     IMAP must be enabled in Gmail settings.
   - iCloud: appleid.apple.com → Sign-In and Security → App-Specific Passwords.
   - Fastmail: Settings → Privacy & Security → App passwords.
3. In Home Assistant: **Settings → Add-ons → Todo → Configuration**, fill in
   the mail options below, save, and restart the add-on.
4. Send yourself a test mail, then check the add-on log or run `todo mail`.

| Provider | `imap_host` | `imap_port` |
|----------|-------------|-------------|
| Gmail | `imap.gmail.com` | 993 |
| iCloud | `imap.mail.me.com` | 993 |
| Fastmail | `imap.fastmail.com` | 993 |

**Outlook.com and Microsoft 365** no longer accept passwords over IMAP (they
require OAuth), so they cannot be used directly. Forward the mail to an account
that does — for example a Gmail address used only for this.

### Shortcuts in the subject

Put any of these anywhere in the subject; they are removed from the title.

| Write | Effect |
|-------|--------|
| `#hushall` | adds a tag (only tags configured in the app; others stay in the title) |
| `!high` / `!low` | priority |
| `@work` / `@private` | workspace |
| `@today` | puts the task in My Day |
| `due:2026-11-02`, `due:today`, `due:tomorrow` | due date (`idag` / `imorgon` work too) |

Example: `Fwd: Ring elektrikern #hushall !high due:tomorrow`.
"Re:", "Fwd:", "SV:" and "VB:" prefixes are dropped.

The workspace can also come from a plus address: mail to `you+work@gmail.com`
lands in Work, `you+private@gmail.com` in Private. A workspace in the subject
wins; otherwise `mail_default_workspace` applies.

### Who may create tasks

Set `mail_allowed_senders` to a comma-separated list of addresses and/or
`@domains`, e.g. `me@gmail.com, @mycompany.se`. Mail from anyone else is skipped
(marked read, and noted in the log). If it is empty, anything that reaches the
folder becomes a task. Sender addresses can be forged, so the folder filter is
your first line of defence and the list the second.

### Checking it works

```bash
todo mail          # settings, last check (and any error), recent imports
todo mail check    # check right now instead of waiting
```

The same is available over the API: `GET /api/v1/mail` and `POST /api/v1/mail/check`.
Each pass handles at most 20 messages; the rest follow on the next check.

## Handing tasks to Claude

Press **✦** on a task to give it to Claude. Optionally say what you want
("only fixed-price offers, as a table"); otherwise Claude goes by the title and
description. The task then shows where it is:

| Badge | Meaning |
|-------|---------|
| *Claude: queued* | waiting for the Claude worker |
| *Claude is working…* | Claude is on it |
| *Claude answered* | read the answer: **Accept & mark done**, **Send reply** to ask for changes, or **Take back** |
| *Claude failed* | the reason is in the conversation; **Try again** when fixed |

Claude never marks a task done; that is your call after reading the answer.

While working, Claude may add **follow-up tasks** for steps only you can take
("Cancel the current contract"), putting urgent ones straight into My Day.
Tasks Claude adds carry a *✦ Claude* badge with the task they came from, and
the conversation lists them under *Claude added …*. They are ordinary tasks:
edit, finish or delete them as usual. `todo list` marks them *(from Claude)*.
Mail with `@claude` in the subject is handed to Claude straight away.

### How it runs: on your machine, on your subscription

The add-on only keeps the queue. The work is done by **Claude Code** on a
computer you choose (a Raspberry Pi, your Windows PC, or both), logged in with
**your Claude account**. Every run counts towards your Claude plan's usage
limits, the same as using Claude Code yourself; nothing is billed per token.

The worker (`todo claude work`) makes sure of that: it removes
`ANTHROPIC_API_KEY` and similar variables before starting Claude, refuses to
run if Claude Code reports API-key or Bedrock/Vertex login, and starts Claude
in restricted mode so settings files cannot switch it to an API key either.

### Set up a Raspberry Pi (Raspberry Pi OS, 64-bit)

```bash
sudo apt install -y pipx git
pipx ensurepath && exec bash
git clone https://github.com/rikpet/ha-todo.git
pipx install ./ha-todo/todo/app
todo config --url http://10.150.1.89:8099      # your HA box

curl -fsSL https://claude.ai/install.sh | bash  # Claude Code
claude                                          # log in: /login, choose your Claude account
claude auth status --text                       # should say you are logged in with Claude
todo claude work --once                         # handle anything queued, then stop
```

On a Pi without a screen, `/login` prints a link: open it on your phone or PC
and paste the code back. Alternatively run `claude setup-token` on any computer
and give the Pi the token as `CLAUDE_CODE_OAUTH_TOKEN`. It is a subscription
token too.

Keep it running with a systemd user service,
`~/.config/systemd/user/todo-claude.service`:

```ini
[Unit]
Description=ha-todo Claude worker
After=network-online.target

[Service]
ExecStart=%h/.local/bin/todo claude work
Restart=on-failure
RestartSec=60

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now todo-claude
sudo loginctl enable-linger $USER     # keep running when you are logged out
journalctl --user -u todo-claude -f   # follow what Claude is doing
```

### Or run it on Windows

In PowerShell, with the CLI already installed (`todo upgrade` to get this version):

```powershell
irm https://claude.ai/install.ps1 | iex    # Claude Code
claude                                     # /login with your Claude account
todo claude work                           # Ctrl+C to stop
```

To start it at log-in, add a Task Scheduler task that runs
`%USERPROFILE%\.local\bin\todo.exe claude work`. The Pi and the PC can both run
a worker: a task is only ever picked up by one of them.

### Private and work on different Claude accounts

Give each workspace its own worker, each logged in to the Claude account
meant for it, for example:

```bash
todo claude work --workspace private    # on the Pi, logged in with your own Claude account
```

```powershell
todo claude work --workspace work       # on the work computer, logged in with the work account
```

A worker started with `--workspace` only picks up tasks from that workspace,
and the add-on refuses to hand it any other. Claude's todo tools are confined to
the same workspace: it cannot list, search, read or answer the other
workspace's tasks, and tasks it creates land in its own. A work task handed to
Claude waits in the queue until the work computer's worker is running.

This keeps each account to its own tasks in normal use. It is not a security
boundary: the add-on's LAN port has no login, and a Claude that is allowed to
run commands could still query it directly. (The worker does block Claude's web
fetch tool from the add-on's address.) If that matters for work data, start the
work worker with `--no-commands` as well.

### What Claude may do

Each task gets its own folder (`~/todo-claude/task-<id>`), and Claude's file
tools are limited to it. Claude may search and read the web, run commands
(for scripts or documents it is making), read and answer the task, and create
follow-up tasks. Start the worker with `--no-commands` to leave out commands.
Claude runs as the user that started the worker, so a separate user account on
the Pi is a good idea. Other options: `--model sonnet`, `--timeout 30`
(minutes per task), `--interval 60` (seconds between queue checks),
`--workdir PATH`.

### From the terminal and from Claude chats

```bash
todo claude                          # everything handed to Claude, with its state
todo claude give 12 "as a table"     # hand over task 12 (also how you reply)
todo claude show 12                  # the conversation
todo claude back 12                  # take it back
```

`todo mcp` is an MCP server for your todo list. Add it to Claude Code with
`claude mcp add todo -- todo mcp` (or to Claude Desktop's MCP settings) and you
can ask in an ordinary chat: "work on the todos I gave you", or "add a task to
call the plumber on Friday, put it in My Day". Add `--workspace work`
(or `private`) to give that Claude only one workspace.

## Options

| Option | Description |
|--------|-------------|
| `log_level` | `debug` / `info` / `warning` / `error` |
| `mail_enabled` | Turn tasks-from-mail on |
| `imap_host` / `imap_port` | Mail server; port 993 (SSL) or 143 (STARTTLS) |
| `imap_username` / `imap_password` | Usually your address and an app password |
| `imap_folder` | Folder or Gmail label to watch (default `Todo`) |
| `mail_allowed_senders` | Comma-separated addresses / `@domains`; empty allows anyone |
| `mail_default_workspace` | `private` or `work` |
| `mail_poll_minutes` | How often to check (default 5) |

## CLI

On your laptop:

```bash
pipx install "git+https://github.com/rikpet/ha-todo.git#subdirectory=todo/app"
todo config --url http://10.150.1.89:8099   # your HA box's IP
todo tags add hushall errands         # tags must be configured before use
todo add "Sprint review"              # CLI defaults to the work workspace
todo add "Buy milk" -w private --due 2026-08-10 --priority high --tag errands
todo list                             # both workspaces; -w work to filter
todo done 1
```

Run any command without arguments (`todo add`, `todo edit`, `todo done`) to be prompted interactively.

**Updating the CLI** after an add-on update:

```bash
todo upgrade
```

## REST API

Full JSON API under `/api/v1` — see `GET /docs` (OpenAPI) on the LAN port.
