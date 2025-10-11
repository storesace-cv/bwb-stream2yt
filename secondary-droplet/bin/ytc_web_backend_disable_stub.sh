#!/usr/bin/env bash
# Desliga apenas o backend ytc-web. Não afecta os serviços de fallback (bwb-status-monitor/youtube-fallback).
set -euo pipefail

log() {
    echo "[ytc-web-backend-disable] $*"
}

log "Iniciando desligamento do mini-projecto ytc-web"

if systemctl list-unit-files | grep -q '^ytc-web-backend.service'; then
    log "Parando ytc-web-backend.service"
    systemctl stop ytc-web-backend.service || log "Aviso: falha ao parar ytc-web-backend.service"

    log "Desativando arranque automático do ytc-web-backend.service"
    systemctl disable ytc-web-backend.service || log "Aviso: falha ao desativar ytc-web-backend.service"
else
    log "ytc-web-backend.service não encontrado no systemd"
fi

log "ytc-web-backend.service desligado (demais serviços permanecem activos)."
