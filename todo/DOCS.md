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
