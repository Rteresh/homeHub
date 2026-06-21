#!/bin/sh
set -eu

# Ждём PostgreSQL и применяем миграции перед запуском gunicorn
python manage.py migrate --noinput

exec gunicorn homehub.wsgi:application \
    --bind "0.0.0.0:8000" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}"
