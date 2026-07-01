#!/usr/bin/env bash
# Подключает .env и .env.host для скриптов, запускаемых на хосте (не в контейнере).
# Использование из другого скрипта:
#   ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
#   # shellcheck disable=SC1091
#   source "$ROOT_DIR/scripts/load-host-env.sh"
#   load_host_env "$ROOT_DIR"

load_host_env() {
  local root_dir="${1:?load_host_env: нужен каталог корня проекта}"
  # ponytail: ops UI в Docker передаёт env целиком — не читаем .env/.env.host с путями хоста
  if [[ "${HOMEHUB_SKIP_HOST_ENV:-}" == "1" ]]; then
    return 0
  fi
  if [[ -f "$root_dir/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$root_dir/.env"
    set +a
  fi
  # ponytail: ops UI в Docker передаёт HOMEHUB_SKIP_HOST_ENV=1 — пути контейнера (/app/storage), не хоста
  if [[ -f "$root_dir/.env.host" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$root_dir/.env.host"
    set +a
  elif [[ ! -f "$root_dir/.env" ]]; then
    echo "WARN: нет .env и .env.host в $root_dir" >&2
  fi
}
