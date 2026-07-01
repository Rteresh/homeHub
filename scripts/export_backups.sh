#!/usr/bin/env bash
# Копирует бэкапы на съёмный носитель: $TARGET/backups/$PROJECT_NAME/$DATE/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-host-env.sh"
load_host_env "$ROOT_DIR"

HOMEHUB_STORAGE_ROOT="${HOMEHUB_STORAGE_ROOT:-/srv/storage/homehub}"
PROJECT_NAME="${PROJECT_NAME:-homehub}"
LATEST_ONLY=false
DRY_RUN=false

usage() {
  cat <<EOF
Использование: $(basename "$0") [-n] [--latest] TARGET_DIR

  TARGET_DIR   Точка монтирования съёмного носителя (например /media/usb)
  --latest     Копировать только последний каталог backup по дате
  -n           Dry-run (rsync --dry-run)
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)
      LATEST_ONLY=true
      shift
      ;;
    -n)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      log "ERROR: неизвестная опция: $1"
      usage
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

TARGET_ROOT="${1:-}"
if [[ -z "${TARGET_ROOT}" ]]; then
  usage
  exit 1
fi

BACKUP_ROOT="${HOMEHUB_STORAGE_ROOT}/backup"
EXPORT_DATE="$(date +%Y-%m-%d)"
DEST_DIR="${TARGET_ROOT%/}/backups/${PROJECT_NAME}/${EXPORT_DATE}"

if [[ ! -d "${TARGET_ROOT}" ]]; then
  log "ERROR: каталог назначения не найден: ${TARGET_ROOT}"
  exit 1
fi

if [[ ! -w "${TARGET_ROOT}" ]]; then
  log "ERROR: нет прав записи в ${TARGET_ROOT}"
  exit 1
fi

if [[ ! -d "${BACKUP_ROOT}" ]]; then
  log "ERROR: каталог backup не найден: ${BACKUP_ROOT}"
  exit 1
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: команда '$1' не найдена"
    exit 1
  fi
}

require_command rsync

RSYNC_OPTS=(-a --human-readable --stats)
if [[ "${DRY_RUN}" == true ]]; then
  RSYNC_OPTS+=(--dry-run)
fi

mkdir -p "${HOMEHUB_STORAGE_ROOT}/logs" "${DEST_DIR}"
LOG_FILE="${HOMEHUB_STORAGE_ROOT}/logs/export-backups.log"

if [[ "${LATEST_ONLY}" == true ]]; then
  latest_dir="$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1 || true)"
  if [[ -z "${latest_dir}" ]]; then
    log "ERROR: в ${BACKUP_ROOT} нет каталогов backup"
    exit 1
  fi
  log "Копирование последнего backup: ${latest_dir} -> ${DEST_DIR}/"
  {
    log "Старт export backups (--latest)"
    rsync "${RSYNC_OPTS[@]}" "${latest_dir}/" "${DEST_DIR}/$(basename "${latest_dir}")/"
    log "Export backups завершён"
  } | tee -a "${LOG_FILE}"
else
  log "Копирование всех backup: ${BACKUP_ROOT}/ -> ${DEST_DIR}/"
  {
    log "Старт export backups (all)"
    rsync "${RSYNC_OPTS[@]}" "${BACKUP_ROOT}/" "${DEST_DIR}/"
    log "Export backups завершён"
  } | tee -a "${LOG_FILE}"
fi
