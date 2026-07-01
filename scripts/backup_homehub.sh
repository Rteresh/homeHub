#!/usr/bin/env bash
# Создаёт бэкап PostgreSQL и конфигурации проекта в $HOMEHUB_STORAGE_ROOT/backup/YYYY-MM-DD/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-host-env.sh"
load_host_env "$ROOT_DIR"

HOMEHUB_STORAGE_ROOT="${HOMEHUB_STORAGE_ROOT:-/srv/storage/homehub}"
PROJECT_NAME="${PROJECT_NAME:-homehub}"
POSTGRES_DB="${POSTGRES_DB:-homehub}"
POSTGRES_USER="${POSTGRES_USER:-homehub}"
POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
MIN_FREE_MB="${MIN_FREE_MB:-256}"

BACKUP_DATE="$(date +%Y-%m-%d)"
BACKUP_DIR="${HOMEHUB_STORAGE_ROOT}/backup/${BACKUP_DATE}"
CONFIG_DIR="${BACKUP_DIR}/config"
SQL_FILE="${BACKUP_DIR}/${PROJECT_NAME}.sql.gz"
MANIFEST_FILE="${BACKUP_DIR}/manifest.txt"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: команда '$1' не найдена"
    exit 1
  fi
}

check_free_space() {
  require_command df
  local available_kb
  available_kb="$(df -Pk "${HOMEHUB_STORAGE_ROOT}" | awk 'NR==2 {print $4}')"
  local available_mb=$((available_kb / 1024))
  if (( available_mb < MIN_FREE_MB )); then
    log "ERROR: мало места в ${HOMEHUB_STORAGE_ROOT}: ${available_mb} МБ (нужно >= ${MIN_FREE_MB} МБ)"
    exit 1
  fi
}

dump_via_docker() {
  require_command docker
  docker compose exec -T db pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip -c > "${SQL_FILE}"
}

dump_via_local_pg_dump() {
  require_command pg_dump
  require_command gzip
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    "${POSTGRES_DB}" | gzip -c > "${SQL_FILE}"
}

dump_database() {
  if [[ -f "${ROOT_DIR}/docker-compose.yml" ]] && docker compose ps --services --status running 2>/dev/null | grep -qx db; then
    log "Дамп БД через docker compose (db)..."
    dump_via_docker
    return
  fi

  log "Дамп БД через локальный pg_dump (${POSTGRES_HOST}:${POSTGRES_PORT})..."
  dump_via_local_pg_dump
}

copy_config_files() {
  mkdir -p "${CONFIG_DIR}"
  local files=(.env docker-compose.yml Dockerfile)
  local name
  for name in "${files[@]}"; do
    if [[ -f "${ROOT_DIR}/${name}" ]]; then
      cp "${ROOT_DIR}/${name}" "${CONFIG_DIR}/${name}"
    fi
  done
  if [[ -f "${CONFIG_DIR}/.env" ]]; then
    chmod 600 "${CONFIG_DIR}/.env"
  fi
}

write_manifest() {
  {
    echo "project=${PROJECT_NAME}"
    echo "backup_date=${BACKUP_DATE}"
    echo "created_at=$(date -Iseconds)"
    echo "hostname=$(hostname)"
    if command -v git >/dev/null 2>&1 && git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "git_commit=$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
    fi
    echo "storage_root=${HOMEHUB_STORAGE_ROOT}"
    echo "database=${POSTGRES_DB}"
    if [[ -f "${SQL_FILE}" ]]; then
      echo "sql_bytes=$(wc -c < "${SQL_FILE}" | tr -d ' ')"
    fi
  } > "${MANIFEST_FILE}"
}

main() {
  require_command gzip
  mkdir -p "${BACKUP_DIR}" "${HOMEHUB_STORAGE_ROOT}/logs"
  check_free_space

  log "Бэкап в ${BACKUP_DIR}"
  dump_database

  if [[ ! -s "${SQL_FILE}" ]]; then
    log "ERROR: файл дампа пуст или не создан: ${SQL_FILE}"
    exit 1
  fi

  copy_config_files
  write_manifest
  log "Готово: ${SQL_FILE}"
}

main "$@"
