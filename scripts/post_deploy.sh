#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/var/log/bwb_post_deploy.log"
mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
    echo "[post_deploy] $*"
}

remove_legacy_components() {
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

    systemctl daemon-reload
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

log "Registando saída completa em ${LOG_FILE}"

remove_legacy_components

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
    log "Instalando monitor HTTP de status do primário"

    install -m 755 -o root -g root bin/bwb_status_monitor.py /usr/local/bin/bwb_status_monitor.py
    install -m 644 -o root -g root systemd/bwb-status-monitor.service /etc/systemd/system/bwb-status-monitor.service

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

    systemctl daemon-reload
    systemctl enable --now bwb-status-monitor.service
    log "Monitor de status ativo em ${state_dir}"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SECONDARY_DIR="${REPO_DIR}/secondary-droplet"

cd "${SECONDARY_DIR}"

log "Instalando dependências base do fallback"
pip3 install --no-cache-dir -r requirements.txt

install -m 755 -o root -g root bin/youtube_fallback.sh /usr/local/bin/youtube_fallback.sh
install -m 644 -o root -g root systemd/youtube-fallback.service /etc/systemd/system/youtube-fallback.service
install -m 755 -o root -g root bin/ensure_broadcast.py /usr/local/bin/ensure_broadcast.py
install -m 644 -o root -g root systemd/ensure-broadcast.service /etc/systemd/system/ensure-broadcast.service
install -m 644 -o root -g root systemd/ensure-broadcast.timer /etc/systemd/system/ensure-broadcast.timer

log "Instalando utilitários administrativos no /usr/local/bin"

reset_secondary_source="${SCRIPT_DIR}/reset_secondary_droplet.sh"
if [[ -f "${reset_secondary_source}" ]]; then
    install -m 755 -o root -g root "${reset_secondary_source}" /usr/local/bin/reset_secondary_droplet.sh
else
    log "Aviso: reset_secondary_droplet.sh não encontrado em ${reset_secondary_source}; instalação ignorada."
fi

status_monitor_debug_source="${SCRIPT_DIR}/status-monitor-debug.sh"
if [[ -f "${status_monitor_debug_source}" ]]; then
    install -m 755 -o root -g root "${status_monitor_debug_source}" /usr/local/bin/status-monitor-debug.sh
else
    log "Aviso: status-monitor-debug.sh não encontrado em ${status_monitor_debug_source}; instalação ignorada."
fi

ENV_FILE="/etc/youtube-fallback.env"
DEFAULTS_FILE="config/youtube-fallback.defaults"

existing_key=""
if [[ -f "${ENV_FILE}" ]]; then
    while IFS= read -r line; do
        case "${line}" in
            YT_KEY=*)
                existing_key="${line#YT_KEY=}"
                ;;
        esac
    done < "${ENV_FILE}"
fi

if [[ -z "${existing_key}" ]]; then
    existing_key='""'
fi

tmp_env="$(mktemp)"
trap 'rm -f "'"${tmp_env}"'"' EXIT
{
    echo "# /etc/youtube-fallback.env (managed by post_deploy.sh)"
    echo "# Defaults live in /usr/local/config/youtube-fallback.defaults. Override only what you need here."
    echo "YT_KEY=${existing_key}"
    echo
    echo "# Default parameters for reference:"
    while IFS= read -r default_line; do
        [[ -z "${default_line}" ]] && continue
        [[ "${default_line}" =~ ^# ]] && continue
        echo "#${default_line}"
    done < "${DEFAULTS_FILE}"
} > "${tmp_env}"

install -m 644 -o root -g root "${tmp_env}" "${ENV_FILE}"
rm -f "${tmp_env}"
trap - EXIT

systemctl daemon-reload
systemctl stop youtube-fallback.service || true
systemctl disable youtube-fallback.service || true
systemctl enable --now ensure-broadcast.timer

setup_status_monitor

log "youtube-fallback atualizado e env sincronizado."

log "Preparando backend do ytc-web via secondary-droplet/bin/ytc_web_backend_setup.sh..."
ensure_python_venv
bash bin/ytc_web_backend_setup.sh

ensure_swap

log "Operação concluída."
print_available_scripts

if command -v deactivate >/dev/null 2>&1; then
    deactivate
fi
