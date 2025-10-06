#!/usr/bin/env bash
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

if systemctl is-active --quiet yt-decider-daemon.service 2>/dev/null; then
    log "Parando yt-decider-daemon.service (dependência do ytc-web)"
    systemctl stop yt-decider-daemon.service || log "Aviso: falha ao parar yt-decider-daemon.service"
fi

if systemctl list-unit-files | grep -q '^yt-decider-daemon.service'; then
    log "Desativando arranque automático do yt-decider-daemon.service"
    systemctl disable yt-decider-daemon.service || log "Aviso: falha ao desativar yt-decider-daemon.service"
fi

if systemctl is-active --quiet youtube-fallback.service 2>/dev/null; then
    log "Parando youtube-fallback.service para isolar o fallback secundário"
    systemctl stop youtube-fallback.service || log "Aviso: falha ao parar youtube-fallback.service"
fi

if systemctl list-unit-files | grep -q '^youtube-fallback.service'; then
    log "Desativando arranque automático do youtube-fallback.service"
    systemctl disable youtube-fallback.service || log "Aviso: falha ao desativar youtube-fallback.service"
fi

log "Serviços relacionados ao ytc-web desligados (sem remoção de ficheiros)."
