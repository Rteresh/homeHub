#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

# В Docker монтируется /app/storage; путь хоста из .env.host (/srv/storage/...) здесь недоступен.
if [ -f /.dockerenv ] && [ -d /app/storage ]; then
  STORAGE_ROOT="/app/storage"
else
  STORAGE_ROOT="${HOMEHUB_STORAGE_ROOT:-/app/storage}"
fi
LOG_DIR="${STORAGE_ROOT}/logs"
mkdir -p "$LOG_DIR"

exec gunicorn homehub.wsgi:application \
    --bind "0.0.0.0:8000" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile "$LOG_DIR/gunicorn-access.log" \
    --error-logfile "$LOG_DIR/gunicorn-error.log" \
    --capture-output
