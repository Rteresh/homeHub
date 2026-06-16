#!/usr/bin/env bash
# Перезапускает сайт и Telegram-бота после изменений в коде.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Останавливаем HomeHub..."
"$ROOT_DIR/stop_homehub.sh"

sleep 1

echo "Запускаем HomeHub..."
"$ROOT_DIR/start_homehub.sh"
