#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"

stop_process() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name не запущен: PID-файл не найден."
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "$name остановлен: PID $pid"
  else
    echo "$name уже остановлен: PID $pid не найден."
  fi
  rm -f "$pid_file"
}

stop_process "Telegram-бот" "$RUN_DIR/bot.pid"
stop_process "Сайт" "$RUN_DIR/web.pid"

for pattern in \
  "homeHub/.venv/bin/python -m bot.main" \
  "homeHub/.venv/bin/python .*bot/main.py" \
  "homeHub/.venv/bin/python .*manage.py runserver"
do
  while read -r pid; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      sleep 0.2
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    fi
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
done
