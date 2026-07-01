#!/usr/bin/env bash
# Копирует HomeHub на Debian-сервер и поднимает docker compose.
# Запуск с Mac/Linux из корня проекта:
#   ./scripts/deploy-to-server.sh
#   ./scripts/deploy-to-server.sh domo@192.168.1.34
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SSH_TARGET="${1:-home-server}"
REMOTE_DIR="${REMOTE_DIR:-homeHub}"
SERVER_IP="${SERVER_IP:-192.168.1.34}"
SITE_PORT="${SITE_PORT:-8001}"

echo "==> Цель: ${SSH_TARGET}:${REMOTE_DIR}"

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Нет .env в корне проекта. Скопируйте .env.example в .env и заполните TELEGRAM_BOT_TOKEN."
  exit 1
fi

echo "==> Копируем файлы на сервер (rsync)..."
rsync -avz --delete \
  --exclude '.venv/' \
  --exclude 'storage/' \
  --exclude '.run/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.git/' \
  --exclude 'staticfiles/' \
  "$ROOT_DIR/" "${SSH_TARGET}:${REMOTE_DIR}/"

echo "==> Готовим .env для Docker на сервере..."
ssh "$SSH_TARGET" "bash -s" <<EOF
set -euo pipefail
cd "\$HOME/${REMOTE_DIR}"
cp .env .env.bak 2>/dev/null || true

# Базовые production-настройки для LAN-сервера
grep -v '^POSTGRES_HOST=' .env > .env.tmp || true
mv .env.tmp .env

append_or_replace() {
  key="\$1"
  value="\$2"
  if grep -q "^\${key}=" .env; then
    sed -i "s|^\${key}=.*|\${key}=\${value}|" .env
  else
    printf '%s=%s\n' "\$key" "\$value" >> .env
  fi
}

append_or_replace DJANGO_DEBUG false
append_or_replace DJANGO_ALLOWED_HOSTS "localhost,127.0.0.1,${SERVER_IP}"
append_or_replace SITE_BASE_URL "http://${SERVER_IP}:${SITE_PORT}"
append_or_replace SITE_PORT "${SITE_PORT}"
append_or_replace HOMEHUB_STORAGE_ROOT /app/storage
EOF

echo "==> Проверяем Docker на сервере..."
ssh "$SSH_TARGET" "bash -s" <<'EOF'
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker не найден. Устанавливаем..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "Docker установлен. Если compose упадёт с permission denied — выйдите из SSH и зайдите снова, затем повторите скрипт."
fi

docker compose version
EOF

echo "==> Сборка и запуск контейнеров..."
ssh "$SSH_TARGET" "bash -s" <<EOF
set -euo pipefail
cd "\$HOME/${REMOTE_DIR}"
docker compose up -d --build
docker compose ps
echo ""
echo "HomeHub: http://${SERVER_IP}:${SITE_PORT}/"
echo "Логи: ssh ${SSH_TARGET} 'cd ~/${REMOTE_DIR} && docker compose logs -f web'"
EOF

echo "==> Готово."
