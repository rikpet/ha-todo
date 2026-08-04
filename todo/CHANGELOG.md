# Changelog

## 0.1.2

- Fix static files (CSS/htmx) returning 404 under Ingress — the UI now loads correctly inside the Home Assistant sidebar.
- Complete visual redesign: compact card layout, segmented status filter, custom checkboxes, badges, dark mode via system preference.

## 0.1.1

- Fix startup crash: read add-on options directly from `/data/options.json` instead of the Supervisor API, and default `log_level` to `info` when unset.

## 0.1.0

- Initial release: FastAPI + SQLite core, HTMX web UI with Ingress support, REST API with bearer-token LAN access, Typer CLI.
