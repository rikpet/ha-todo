#!/usr/bin/env bashio
set -e

export TODO_DB_PATH=/data/todo.db

TOKEN="$(bashio::config 'api_token')"
if [ "${TOKEN}" = "null" ]; then
    TOKEN=""
fi
export TODO_API_TOKEN="${TOKEN}"
export TODO_LOG_LEVEL="$(bashio::config 'log_level')"

if [ -z "${TODO_API_TOKEN}" ]; then
    bashio::log.warning "No api_token configured - LAN API is disabled, only Ingress works."
fi
bashio::log.info "Starting todo server on port 8099"

exec python3 -m uvicorn todo_app.main:app --host 0.0.0.0 --port 8099 --log-level "${TODO_LOG_LEVEL}"
