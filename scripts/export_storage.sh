#!/usr/bin/env bash
# Копирует всё содержимое HOMEHUB_STORAGE_ROOT на съёмный носитель: $TARGET/homehub/.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck disable=SC1091
source "$ROOT_DIR/scripts/load-host-env.sh"
load_host_env "$ROOT_DIR"

HOMEHUB_STORAGE_ROOT="${HOMEHUB_STORAGE_ROOT:-/srv/storage/homehub}"
PROJECT_NAME="${PROJECT_NAME:-homehub}"
DRY_RUN=false

usage() {
  cat <<EOF
Использование: $(basename "$0") [-n] TARGET_DIR

  TARGET_DIR   Точка монтирования съёмного носителя (например /media/usb)
  -n           Dry-run (rsync --dry-run)
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

while getopts ":nh" opt; do
  case "${opt}" in
    n) DRY_RUN=true ;;
    h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
done
shift $((OPTIND - 1))

TARGET_ROOT="${1:-}"
if [[ -z "${TARGET_ROOT}" ]]; then
  usage
  exit 1
fi

if [[ ! -d "${TARGET_ROOT}" ]]; then
  log "ERROR: каталог назначения не найден: ${TARGET_ROOT}"
  exit 1
fi

if [[ ! -w "${TARGET_ROOT}" ]]; then
  log "ERROR: нет прав записи в ${TARGET_ROOT}"
  exit 1
fi

if [[ ! -d "${HOMEHUB_STORAGE_ROOT}" ]]; then
  log "ERROR: storage не найден: ${HOMEHUB_STORAGE_ROOT}"
  exit 1
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "ERROR: команда '$1' не найдена"
    exit 1
  fi
}

require_command rsync

DEST_DIR="${TARGET_ROOT%/}/${PROJECT_NAME}"
LOG_FILE="${HOMEHUB_STORAGE_ROOT}/logs/export-storage.log"
mkdir -p "${HOMEHUB_STORAGE_ROOT}/logs" "${DEST_DIR}"

RSYNC_OPTS=(-a --human-readable --stats)
if [[ "${DRY_RUN}" == true ]]; then
  RSYNC_OPTS+=(--dry-run)
fi

log "Источник: ${HOMEHUB_STORAGE_ROOT}/"
log "Назначение: ${DEST_DIR}/"

{
  log "Старт export storage"
  rsync "${RSYNC_OPTS[@]}" --delete "${HOMEHUB_STORAGE_ROOT}/" "${DEST_DIR}/"
  log "Export storage завершён"
} | tee -a "${LOG_FILE}"
