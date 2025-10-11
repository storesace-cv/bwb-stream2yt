#!/usr/bin/env bash
# shellcheck shell=bash

POST_DEPLOY_PREFIX="[post_deploy]"

log() {
    echo "${POST_DEPLOY_PREFIX} $*"
}

warn_missing() {
    local label=$1
    local path=$2
    log "Aviso: ${label} não encontrado em ${path}; instalação ignorada."
}

ensure_installed_file() {
    local source=$1
    local destination=$2
    local mode=$3
    local owner=${4:-root}
    local group=${5:-root}

    if [[ -e "${source}" ]]; then
        install -m "${mode}" -o "${owner}" -g "${group}" "${source}" "${destination}"
        log "Instalado ${destination}"
        return 0
    fi

    warn_missing "${source##*/}" "${source}"
    return 1
}

ensure_installed_file_optional() {
    if ! ensure_installed_file "$@"; then
        return 0
    fi
}

maybe_systemctl_daemon_reload() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload
    else
        log "Aviso: systemctl indisponível; ignorando daemon-reload."
    fi
}

remove_legacy_components() {
    if ! command -v systemctl >/dev/null 2>&1; then
        log "Aviso: systemctl não encontrado; ignorando remoção de serviços legados."
        return
    fi

    local -a legacy_services=(
        "yt-decider-daemon.service"
        "yt-decider.service"
    )

    for service in "${legacy_services[@]}"; do
        if systemctl list-unit-files "${service}" >/dev/null 2>&1; then
            log "Desativando serviço legado ${service}"
            systemctl disable --now "${service}" >/dev/null 2>&1 || true
        fi
    done

    local -a legacy_paths=(
        "/etc/systemd/system/yt-decider-daemon.service"
        "/etc/systemd/system/yt-decider.service"
        "/usr/local/bin/yt_decider_daemon.py"
        "/usr/local/bin/yt-decider-daemon.py"
        "/usr/local/bin/yt-decider-debug.sh"
    )

    for path in "${legacy_paths[@]}"; do
        if [[ -e "${path}" ]]; then
            log "Removendo artefacto legado ${path}"
            rm -f "${path}"
        fi
    done

    maybe_systemctl_daemon_reload
}

print_available_scripts() {
    log "Scripts disponíveis para diagnóstico e recuperação:"
    log "  reset_secondary_droplet.sh — limpa caches e reinicia serviços críticos (fallback, monitor, backend)."
    log "    Comando: sudo /usr/local/bin/reset_secondary_droplet.sh"
    log "  status-monitor-debug.sh — recolhe evidências do monitor HTTP (últimas 48h) e gera ficheiro de análise."
    log "    Comando: sudo /usr/local/bin/status-monitor-debug.sh"
    log "  ensure_broadcast.py — valida se existe live do YouTube pronta e ligada ao stream correto."
    log "    Comando: sudo /usr/local/bin/ensure_broadcast.py"
    log "  bwb_status_monitor.py — servidor HTTP que recebe heartbeats do primário; ver --help para opções."
    log "    Comando: sudo /usr/local/bin/bwb_status_monitor.py --help"
}

ensure_swap() {
    if swapon --noheadings 2>/dev/null | grep -q '\S'; then
        log "Swap já configurado; nenhuma ação necessária."
        return
    fi

    local swapfile="/swapfile"
    if [[ ! -f "${swapfile}" ]]; then
        log "Criando swapfile de 512 MiB em ${swapfile}."
        if ! fallocate -l 512M "${swapfile}" 2>/dev/null; then
            log "fallocate indisponível; usando dd para criar swapfile."
            dd if=/dev/zero of="${swapfile}" bs=1M count=512 status=none
        fi
        chmod 600 "${swapfile}"
        mkswap "${swapfile}" >/dev/null
    else
        log "Swapfile existente encontrado; reutilizando ${swapfile}."
    fi

    if ! swapon "${swapfile}" >/dev/null 2>&1; then
        log "Falha ao ativar swapfile ${swapfile}."
        return
    fi

    if ! grep -q "^${swapfile} " /etc/fstab; then
        log "Persistindo swapfile em /etc/fstab."
        printf '%s\n' "${swapfile} none swap sw 0 0" >> /etc/fstab
    fi

    log "Swapfile ${swapfile} ativo."
}

ensure_python_venv() {
    local python_bin=${PYTHON_BIN:-python3}
    if "${python_bin}" -m ensurepip --help >/dev/null 2>&1; then
        log "python3 venv disponível; nenhum pacote adicional necessário."
        return
    fi

    log "python3 venv indisponível; instalando pacotes do sistema."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update

    local version
    version=$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local pkg="python${version}-venv"
    if ! apt-get install -y "${pkg}"; then
        log "Pacote ${pkg} indisponível; tentando python3-venv."
        apt-get install -y python3-venv
    fi

    if ! "${python_bin}" -m ensurepip --help >/dev/null 2>&1; then
        log "Falha ao preparar python3-venv mesmo após instalação."
        exit 1
    fi

    log "python${version} ensurepip validado após instalação."
}

setup_status_monitor() {
    local base_dir=$1

    log "Instalando monitor HTTP de status do primário"

    ensure_installed_file "${base_dir}/bin/bwb_status_monitor.py" /usr/local/bin/bwb_status_monitor.py 755
    ensure_installed_file "${base_dir}/systemd/bwb-status-monitor.service" /etc/systemd/system/bwb-status-monitor.service 644

    local state_dir="/var/lib/bwb-status-monitor"
    install -d -m 755 -o root -g root "${state_dir}"
    if [[ ! -f "${state_dir}/status.json" ]]; then
        printf '[]\n' >"${state_dir}/status.json"
        chown root:root "${state_dir}/status.json"
        chmod 640 "${state_dir}/status.json"
    fi

    if [[ ! -f "/var/log/bwb_status_monitor.log" ]]; then
        touch /var/log/bwb_status_monitor.log
        chmod 640 /var/log/bwb_status_monitor.log
    fi

    local env_file="/etc/bwb-status-monitor.env"
    if [[ ! -f "${env_file}" ]]; then
        cat <<'ENVEOF' >"${env_file}"
# /etc/bwb-status-monitor.env — configurações para o monitor HTTP de status.
# Descomente e ajuste as variáveis conforme necessário.
#BWB_STATUS_BIND=0.0.0.0
#BWB_STATUS_PORT=8080
#BWB_STATUS_HISTORY_SECONDS=300
#BWB_STATUS_MISSED_THRESHOLD=40
#BWB_STATUS_RECOVERY_REPORTS=2
#BWB_STATUS_CHECK_INTERVAL=5
#BWB_STATUS_STATE_FILE=/var/lib/bwb-status-monitor/status.json
#BWB_STATUS_LOG_FILE=/var/log/bwb_status_monitor.log
#BWB_STATUS_SECONDARY_SERVICE=youtube-fallback.service
#BWB_STATUS_TOKEN=
ENVEOF
        chmod 640 "${env_file}"
    fi

    if command -v ufw >/dev/null 2>&1; then
        if ufw status 2>/dev/null | grep -qi "status: active"; then
            if ! ufw status 2>/dev/null | grep -qE '\b8080/tcp\b'; then
                if ! ufw allow 8080/tcp; then
                    log "Aviso: não foi possível abrir a porta 8080 no ufw"
                fi
            fi
        fi
    fi

    maybe_systemctl_daemon_reload
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable --now bwb-status-monitor.service
    else
        log "Aviso: systemctl indisponível; não foi possível ativar bwb-status-monitor.service"
    fi

    log "Monitor de status ativo em ${state_dir}"
}
