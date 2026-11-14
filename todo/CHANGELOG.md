# Changelog

## 0.9.0

- **Give a task to Claude.** The new ✦ button on a task hands it to Claude, with an optional note on what you want. Claude works on it and answers right on the task; the badge shows *queued*, *working*, *answered* or *failed*, and the list refreshes by itself while Claude is busy.
- Open the conversation to read the answer (tables, lists and links are formatted), **reply** to ask for changes, **accept** to mark the task done, or **take it back**. Claude never closes a task on its own.
- Claude runs on **your own computer or a Raspberry Pi** through Claude Code, logged in with **your Claude subscription** — no API key, no separate bill. Start it with `todo claude work`; see *Handing tasks to Claude* in the documentation for the one-time setup.
- Claude gets its own folder per task for files it makes, can search the web, and can suggest follow-up tasks. Use `--no-commands` if it should not run commands.
- From the terminal: `todo claude` lists what Claude has, `todo claude give 12 "what to do"` hands a task over (and replies), `todo claude show 12` shows the conversation.
- Mail with `@claude` in the subject goes straight to Claude.
- **Private and work on different Claude accounts**: run `todo claude work --workspace private` on the Pi with your own account and `todo claude work --workspace work` on your work computer with the work account. Each Claude only sees and answers tasks in its own workspace.
- `todo mcp` connects Claude Desktop or Claude Code to your list, so you can also say "work on my todos" in a normal chat.

## 0.8.0

- **Tasks from mail.** Point the add-on at a mail folder (IMAP) and every unread message there becomes a task: the subject is the title, the body the description. Set it up under *Configuration* in the add-on: server, username, app password, folder, and which senders may create tasks. See the add-on documentation for Gmail and iCloud settings.
- **Shortcuts in the subject**: `#tag`, `!high` / `!low`, `@work` / `@private`, `@today` for My Day, and `due:2026-11-02` (or `due:today`, `due:tomorrow`). Sending to `you+work@...` files the task under Work. "Re:", "Fwd:", "VB:" and email signatures are left out.
- A mail never turns into two tasks, even if it is marked unread again. Mail from senders not on your list is skipped and marked as read.
- `todo mail` shows the setup, the last check and recent imports; `todo mail check` fetches right away.
- The add-on log now shows what the app itself does — tasks created from mail or recurring rules, and why a mail check failed.

## 0.7.0

- **New task order**: highest priority first, then newest to oldest. Due dates no longer affect the order (they are still shown, and overdue ones stay red). Completed tasks remain at the bottom.
- **No accidental zoom on phones**: pinch and double-tap zoom are off, and every input is 16px so iOS stops zooming in when you tap a field.
- **No sideways scrolling on phones**: long titles, URLs and tag names wrap instead of widening the page.

## 0.6.2

- Fix the **All / Open / Done** filter being ignored in My Day — completed tasks showed up even with *Open* selected. The filter now works there like everywhere else, so My Day shows only open items by default and *Done* reviews what you finished today.
- `todo today` matches: open by default, `--all` to include what you finished, `--done` for only those.

## 0.6.1

- New `todo upgrade` command: updates the CLI itself. It reuses the source pipx recorded at install time (local clone or git URL), pulls the clone first when there is one, and reports the version before and after. `todo upgrade --check` just compares versions.

## 0.6.0

- **My Day.** A new tab showing what you plan to tackle today, across both workspaces. Star a task in the list (or `todo today add <id>`) to put it there; anything **due today lands automatically**.
- Anything you starred but did not finish **carries over to the next day**, marked *carried over* in red. **Overdue tasks are red too** — a red edge on the row plus an "N late" counter — in every view, not just My Day.
- A task typed while My Day is open is planned for today automatically. CLI: `todo today`, `todo today add/rm <id>`, and `todo add "..." --today`.

## 0.5.1

- On phones the **Private / Work** switch now sits in a fixed bar at the bottom of the screen, always within thumb reach, with room left for the iPhone home indicator. Desktop keeps the tabs at the top.

## 0.5.0

- The **Home** workspace is now called **Private**. Existing tasks and recurring rules move across automatically when the add-on starts.
- The CLI explains itself when the server cannot be reached — a clear message with what to check, instead of a Python traceback. Timeouts and malformed URLs are covered too, and `todo config` now accepts a bare `10.0.0.5:8099` (the `http://` is filled in).

## 0.4.0

- **Recurring tasks.** Define rules that create tasks automatically — daily, weekly on a chosen weekday, or monthly on a chosen day, each with an interval ("every 2 weeks"). Manage them in the web UI's *Recurring tasks* section or with `todo recur add/pause/resume/rm`.
- A built-in scheduler checks every 15 minutes and at startup, so tasks appear on time and missed runs are caught up after a reboot. Missed days collapse into a single task instead of a pile, and a rule won't stack a new task while the previous one is still open.

## 0.3.6

- See versions at a glance: `todo --version` prints the CLI version **and** the server's, warning when the two have drifted apart. The web UI shows its version in a small footer, and `/health` now reports it too.

## 0.3.5

- Fix the workspace selector reverting to *Home* after adding a task: on the Work tab, the next task you added silently went to Home and disappeared from the list. The selector now follows the active tab, and a task posted without an explicit workspace lands in the workspace you are viewing.

## 0.3.4

- Install as an iPhone/Android home-screen app: web manifest, app icons and Apple meta tags added. Open the LAN URL in Safari/Chrome and use "Add to Home Screen" — the UI runs standalone with its own blue checkmark icon.

## 0.3.3

- The web UI now hides done tasks by default — the status filter starts on **Open** instead of **All**. Tap *Done* or *All* to see completed tasks.

## 0.3.2

- The CLI now defaults new tasks to the **work** workspace (`-w home` to override); the web UI keeps *Home* as its default tab.
- Documented how to update the CLI (`pipx upgrade ha-todo`).

## 0.3.1

- Fix stale styling after updates: static CSS/JS links now carry a version query so browsers stop serving cached stylesheets from older versions. (If the 0.3.0 additions looked unstyled, this was why.)
- Style polish: the workspace selector in the add bar and the "Manage tags" controls now match the rest of the form elements.

## 0.3.0

- **Workspaces**: tasks now live in either *Home* or *Work*. The web UI has workspace tabs, and the add-form has its own workspace selector so you can file a task to the other workspace without switching. CLI: `-w/--workspace` on `add`, `list`, `edit`. Existing tasks land in *Home*.
- **Curated tags**: tags must be configured before use (web: "Manage tags" section; CLI: `todo tags add/rm`). Free-text tags are gone — task forms show the configured tags as toggle chips, and the API rejects unknown tags. Removing a tag strips it from all tasks.

## 0.2.0

- Removed token authentication entirely. The LAN port (8099) is now open to your local network; Ingress remains behind the Home Assistant login. The `api_token` option is gone and `todo config` only needs the server URL.

## 0.1.2

- Fix static files (CSS/htmx) returning 404 under Ingress — the UI now loads correctly inside the Home Assistant sidebar.
- Complete visual redesign: compact card layout, segmented status filter, custom checkboxes, badges, dark mode via system preference.

## 0.1.1

- Fix startup crash: read add-on options directly from `/data/options.json` instead of the Supervisor API, and default `log_level` to `info` when unset.

## 0.1.0

- Initial release: FastAPI + SQLite core, HTMX web UI with Ingress support, REST API with bearer-token LAN access, Typer CLI.
