#!/usr/bin/env bash
# Дамп PostgreSQL HomeHub: локально через docker compose или напрямую pg_dump.
# Запуск из корня проекта:
#   ./scripts/backup-db.sh
# С Mac на сервер:
#   ssh home-server 'cd ~/homeHub && ./scripts/backup-db.sh'
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-host-env.sh"
load_host_env "$ROOT_DIR"

HOMEHUB_STORAGE_ROOT="${HOMEHUB_STORAGE_ROOT:-/srv/storage/homehub}"
BACKUP_DIR="${BACKUP_DIR:-$HOMEHUB_STORAGE_ROOT/backup/db-dumps}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

POSTGRES_DB="${POSTGRES_DB:-homehub}"
POSTGRES_USER="${POSTGRES_USER:-homehub}"
POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT_FILE="$BACKUP_DIR/homehub-${STAMP}.sql.gz"

run_pg_dump() {
  if docker compose ps --status running db >/dev/null 2>&1; then
    echo "==> pg_dump через docker compose (service: db)" >&2
    docker compose exec -T db pg_dump -U "$POSTGRES_USER" --no-owner --no-acl "$POSTGRES_DB"
    return
  fi

  if command -v pg_dump >/dev/null 2>&1; then
    echo "==> pg_dump напрямую ($POSTGRES_HOST:$POSTGRES_PORT)" >&2
    PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
      -h "$POSTGRES_HOST" \
      -p "$POSTGRES_PORT" \
      -U "$POSTGRES_USER" \
      --no-owner --no-acl \
      "$POSTGRES_DB"
    return
  fi

  echo "Не удалось сделать backup: контейнер db не запущен и pg_dump не найден." >&2
  echo "На сервере: cd ~/homeHub && docker compose up -d db" >&2
  exit 1
}

run_pg_dump | gzip > "$OUT_FILE"

BYTES="$(wc -c < "$OUT_FILE" | tr -d ' ')"
echo "==> Backup: $OUT_FILE ($BYTES bytes)"

if [[ "$KEEP_DAYS" =~ ^[0-9]+$ ]] && (( KEEP_DAYS > 0 )); then
  find "$BACKUP_DIR" -maxdepth 1 -name 'homehub-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
  echo "==> Удалены backup старше ${KEEP_DAYS} дн. (если были)"
fi
