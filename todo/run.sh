#!/usr/bin/with-contenv bashio
set -e

export TODO_DB_PATH=/data/todo.db

# Read options straight from /data/options.json — no Supervisor API dependency.
LOG_LEVEL="$(jq -r '.log_level // "info"' /data/options.json 2>/dev/null || echo "info")"
if [ -z "${LOG_LEVEL}" ] || [ "${LOG_LEVEL}" = "null" ]; then
    LOG_LEVEL="info"
fi
export TODO_LOG_LEVEL="${LOG_LEVEL}"

bashio::log.info "Starting todo server on port 8099 (log level: ${TODO_LOG_LEVEL})"

exec python3 -m uvicorn todo_app.main:app --host 0.0.0.0 --port 8099 --log-level "${TODO_LOG_LEVEL}"
