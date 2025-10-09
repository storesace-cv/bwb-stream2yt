#!/usr/bin/env bash
# Reinicia serviços críticos da droplet secundária e limpa caches de memória.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "[erro] Este script deve ser executado como root." >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "[erro] systemctl não encontrado. Este script requer systemd." >&2
  exit 1
fi

SERVICES=(
  "youtube-fallback.service"
  "yt-decider-daemon.service"
  "ytc-web-backend.service"
)

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

log "Estado da memória antes da limpeza:"
free -h || true

log "Sincronizando dados antes de limpar caches..."
sync

log "Limpando caches de página, dentries e inodes..."
echo 3 > /proc/sys/vm/drop_caches

if command -v swapon >/dev/null 2>&1 && swapon --summary >/dev/null 2>&1; then
  log "Reiniciando swap (swapoff + swapon)..."
  swapoff -a
  swapon -a
fi

log "Estado da memória após a limpeza:"
free -h || true

for service in "${SERVICES[@]}"; do
  log "Reiniciando ${service}..."
  systemctl restart "${service}"
  systemctl status "${service}" --no-pager -l | sed -n '1,6p'
done

log "Executando ensure-broadcast.service para garantir programação da live..."
systemctl start ensure-broadcast.service
systemctl status ensure-broadcast.service --no-pager -l | sed -n '1,6p'

log "Todos os serviços processados."
