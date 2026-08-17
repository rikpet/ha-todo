# Changelog

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
