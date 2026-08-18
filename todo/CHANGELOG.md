# Changelog

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
