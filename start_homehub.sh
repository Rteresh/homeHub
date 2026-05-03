#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  source ".env"
  set +a
fi

SITE_HOST="${SITE_HOST:-127.0.0.1}"
SITE_PORT="${SITE_PORT:-8001}"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$ROOT_DIR/storage/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "TELEGRAM_BOT_TOKEN пустой. Вставьте токен в .env и повторите запуск."
  exit 1
fi

if [[ -f "$RUN_DIR/web.pid" ]] && kill -0 "$(cat "$RUN_DIR/web.pid")" 2>/dev/null; then
  echo "Сайт уже запущен: PID $(cat "$RUN_DIR/web.pid")"
else
  rm -f "$RUN_DIR/web.pid"
  "$ROOT_DIR/.venv/bin/python" manage.py migrate --noinput
  nohup "$ROOT_DIR/.venv/bin/python" manage.py runserver "$SITE_HOST:$SITE_PORT" --noreload > "$LOG_DIR/web.log" 2>&1 &
  echo "$!" > "$RUN_DIR/web.pid"
  sleep 1
  if ! kill -0 "$(cat "$RUN_DIR/web.pid")" 2>/dev/null; then
    echo "Сайт не запустился. Лог: $LOG_DIR/web.log"
    exit 1
  fi
  echo "Сайт запущен: http://$SITE_HOST:$SITE_PORT"
fi

if [[ -f "$RUN_DIR/bot.pid" ]] && kill -0 "$(cat "$RUN_DIR/bot.pid")" 2>/dev/null; then
  echo "Telegram-бот уже запущен: PID $(cat "$RUN_DIR/bot.pid")"
else
  rm -f "$RUN_DIR/bot.pid"
  nohup "$ROOT_DIR/.venv/bin/python" -m bot.main > "$LOG_DIR/bot.log" 2>&1 &
  echo "$!" > "$RUN_DIR/bot.pid"
  sleep 1
  if ! kill -0 "$(cat "$RUN_DIR/bot.pid")" 2>/dev/null; then
    echo "Telegram-бот не запустился. Лог: $LOG_DIR/bot.log"
    exit 1
  fi
  echo "Telegram-бот запущен: PID $(cat "$RUN_DIR/bot.pid")"
fi
