#!/usr/bin/with-contenv bashio
set -e

export TODO_DB_PATH=/data/todo.db

# Read options straight from /data/options.json — no Supervisor API dependency.
OPTIONS=/data/options.json
TOKEN="$(jq -r '.api_token // ""' "${OPTIONS}" 2>/dev/null || echo "")"
LOG_LEVEL="$(jq -r '.log_level // "info"' "${OPTIONS}" 2>/dev/null || echo "info")"

if [ "${TOKEN}" = "null" ]; then
    TOKEN=""
fi
if [ -z "${LOG_LEVEL}" ] || [ "${LOG_LEVEL}" = "null" ]; then
    LOG_LEVEL="info"
fi

export TODO_API_TOKEN="${TOKEN}"
export TODO_LOG_LEVEL="${LOG_LEVEL}"

if [ -z "${TODO_API_TOKEN}" ]; then
    bashio::log.warning "No api_token configured - LAN API is disabled, only Ingress works."
fi
bashio::log.info "Starting todo server on port 8099 (log level: ${TODO_LOG_LEVEL})"

exec python3 -m uvicorn todo_app.main:app --host 0.0.0.0 --port 8099 --log-level "${TODO_LOG_LEVEL}"
