#!/bin/sh
set -eu

# Ждём PostgreSQL и применяем миграции перед запуском gunicorn
python manage.py migrate --noinput

LOG_DIR="${HOMEHUB_STORAGE_ROOT:-/app/storage}/logs"
mkdir -p "$LOG_DIR"

exec gunicorn homehub.wsgi:application \
    --bind "0.0.0.0:8000" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile "$LOG_DIR/gunicorn-access.log" \
    --error-logfile "$LOG_DIR/gunicorn-error.log" \
    --capture-output
