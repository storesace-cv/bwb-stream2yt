#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BASH_VERSION:-}" ]]; then
    echo "[post_deploy] Este script requer bash para executar." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SECONDARY_DIR="${REPO_DIR}/secondary-droplet"
LOG_FILE="/var/log/bwb_post_deploy.log"

mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
    echo "[post_deploy] $*"
}

systemctl_available() {
    command -v systemctl >/dev/null 2>&1
}

sync_file() {
    local source=$1
    local destination=$2
    local mode=$3
    local owner=${4:-root}
    local group=${5:-root}

    if [[ ! -e "${source}" ]]; then
        log "Aviso: ${source} não encontrado; a ignorar."
        return 1
    fi

    install -m "${mode}" -o "${owner}" -g "${group}" "${source}" "${destination}"
    log "Atualizado ${destination}"
}

sync_optional_file() {
    local source=$1
    if [[ -e "${source}" ]]; then
        sync_file "$@"
    else
        log "Opcional ${source##*/} ausente; ignorado."
    fi
}

systemd_reload() {
    if systemctl_available; then
        systemctl daemon-reload
    else
        log "Aviso: systemctl indisponível; a ignorar daemon-reload."
    fi
}

enable_service() {
    local unit=$1
    if ! systemctl_available; then
        log "Aviso: systemctl indisponível; ${unit} não foi ativado."
        return
    fi

    if systemctl enable --now "${unit}"; then
        log "Serviço ${unit} ativo."
    else
        log "Aviso: não foi possível ativar ${unit}; ver journalctl para detalhes."
    fi
}

restart_if_running() {
    local unit=$1
    if ! systemctl_available; then
        return
    fi

    if systemctl is-active --quiet "${unit}"; then
        if systemctl restart "${unit}"; then
            log "Serviço ${unit} reiniciado."
        else
            log "Aviso: falha ao reiniciar ${unit}."
        fi
    fi
}

install_python_dependencies() {
    log "Instalando dependências Python do fallback"
    pip3 install --no-cache-dir -r "${SECONDARY_DIR}/requirements.txt"
}

install_secondary_services() {
    log "Sincronizando serviço principal de fallback"
    sync_file "${SECONDARY_DIR}/bin/youtube_fallback.sh" /usr/local/bin/youtube_fallback.sh 755
    sync_file "${SECONDARY_DIR}/systemd/youtube-fallback.service" /etc/systemd/system/youtube-fallback.service 644

    log "Sincronizando verificação automática de broadcast"
    sync_file "${SECONDARY_DIR}/bin/ensure_broadcast.py" /usr/local/bin/ensure_broadcast.py 755
    sync_file "${SECONDARY_DIR}/systemd/ensure-broadcast.service" /etc/systemd/system/ensure-broadcast.service 644
    sync_file "${SECONDARY_DIR}/systemd/ensure-broadcast.timer" /etc/systemd/system/ensure-broadcast.timer 644
}

install_utilities() {
    log "Instalando utilitários administrativos"
    sync_optional_file "${SCRIPT_DIR}/reset_secondary_droplet.sh" /usr/local/bin/reset_secondary_droplet.sh 755
    sync_optional_file "${SCRIPT_DIR}/status-monitor-debug.sh" /usr/local/bin/status-monitor-debug.sh 755
}

update_fallback_env() {
    local env_file="/etc/youtube-fallback.env"
    local defaults_file="${SECONDARY_DIR}/config/youtube-fallback.defaults"
    local tmp_env
    tmp_env="$(mktemp)"
    trap 'rm -f "${tmp_env}"' RETURN

    local existing_key=""
    if [[ -f "${env_file}" ]]; then
        existing_key=$(grep -E '^YT_KEY=' "${env_file}" | tail -n1 | cut -d'=' -f2-)
    fi

    if [[ -z "${existing_key}" ]]; then
        existing_key='""'
    fi

    {
        echo "# /etc/youtube-fallback.env"
        echo "# Este ficheiro é gerido por post_deploy.sh – adicione apenas overrides."
        echo "YT_KEY=${existing_key}"
        echo
        echo "# Parâmetros por defeito para referência:"
        if [[ -f "${defaults_file}" ]]; then
            while IFS= read -r line; do
                [[ -z "${line}" || "${line}" =~ ^# ]] && continue
                echo "#${line}"
            done < "${defaults_file}"
        fi
    } > "${tmp_env}"

    install -m 644 -o root -g root "${tmp_env}" "${env_file}"
    trap - RETURN
    rm -f "${tmp_env}"
    log "Configuração /etc/youtube-fallback.env atualizada"
}

install_status_monitor() {
    log "Instalando monitor HTTP de status"
    sync_file "${SECONDARY_DIR}/bin/bwb_status_monitor.py" /usr/local/bin/bwb_status_monitor.py 755
    sync_file "${SECONDARY_DIR}/systemd/yt-restapi.service" /etc/systemd/system/yt-restapi.service 644

    if ! id -u yt-restapi >/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin yt-restapi
        log "Utilizador yt-restapi criado"
    fi

    local state_dir="/var/lib/bwb-status-monitor"
    install -d -m 750 -o yt-restapi -g yt-restapi "${state_dir}"
    if [[ ! -f "${state_dir}/status.json" ]]; then
        printf '[]\n' > "${state_dir}/status.json"
    fi
    chown yt-restapi:yt-restapi "${state_dir}/status.json"
    chmod 640 "${state_dir}/status.json"

    local log_file="/var/log/bwb_status_monitor.log"
    if [[ ! -f "${log_file}" ]]; then
        touch "${log_file}"
    fi
    chown yt-restapi:yt-restapi "${log_file}"
    chmod 640 "${log_file}"

    local env_file="/etc/yt-restapi.env"
    if [[ ! -f "${env_file}" ]]; then
        cat <<'ENVEOF' > "${env_file}"
# /etc/yt-restapi.env — configurações para o monitor HTTP de status.
# Ajuste as variáveis conforme necessário.
#YTR_BIND=0.0.0.0
#YTR_PORT=8080
#YTR_HISTORY_SECONDS=300
#YTR_MISSED_THRESHOLD=40
#YTR_RECOVERY_REPORTS=2
#YTR_CHECK_INTERVAL=5
#YTR_STATE_FILE=/var/lib/bwb-status-monitor/status.json
#YTR_LOG_FILE=/var/log/bwb_status_monitor.log
#YTR_SECONDARY_SERVICE=youtube-fallback.service
#YTR_TOKEN=
#YTR_REQUIRE_TOKEN=1
ENVEOF
        chmod 640 "${env_file}"
        chown yt-restapi:yt-restapi "${env_file}"
    fi

    install_yt_restapi_sudoers
}

install_yt_restapi_sudoers() {
    local sudoers_file="/etc/sudoers.d/yt-restapi"
    local tmp
    tmp="$(mktemp)"

    cat <<'SUDOEOF' > "${tmp}"
yt-restapi ALL=(root) NOPASSWD: /bin/systemctl start youtube-fallback.service, /bin/systemctl stop youtube-fallback.service, /bin/systemctl status youtube-fallback.service
SUDOEOF

    install -m 440 -o root -g root "${tmp}" "${sudoers_file}"
    rm -f "${tmp}"

    if command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf "${sudoers_file}" >/dev/null; then
            rm -f "${sudoers_file}"
            log "Erro: validação de ${sudoers_file} falhou"
            exit 1
        fi
    else
        log "Aviso: visudo não encontrado; sudoers não foi validado automaticamente."
    fi
}

install_watcher() {
    log "Instalando watcher de fallback do YouTube"
    sync_file "${SECONDARY_DIR}/bin/youtube_fallback_watcher.py" /usr/local/bin/youtube_fallback_watcher.py 755
    sync_file "${SECONDARY_DIR}/systemd/youtube-fallback-watcher.service" /etc/systemd/system/youtube-fallback-watcher.service 644

    local config_file="/etc/youtube-fallback-watcher.conf"
    if [[ ! -f "${config_file}" ]]; then
        sync_file "${SECONDARY_DIR}/config/youtube-fallback-watcher.conf" "${config_file}" 644
        log "Configuração padrão criada em ${config_file}"
    fi
}

update_backend() {
    log "Preparando backend do ytc-web"
    bash "${SECONDARY_DIR}/bin/ytc_web_backend_setup.sh"
}

apply_systemd_changes() {
    systemd_reload
    enable_service youtube-fallback.service
    enable_service ensure-broadcast.timer
    enable_service yt-restapi.service

    if systemctl_available; then
        if systemctl is-enabled --quiet youtube-fallback-watcher.service; then
            restart_if_running youtube-fallback-watcher.service
        else
            log "Watcher youtube-fallback-watcher.service instalado; ative manualmente se necessário."
        fi
    fi
}

main() {
    log "Registando saída em ${LOG_FILE}"

    install_python_dependencies
    install_secondary_services
    install_utilities
    update_fallback_env
    install_status_monitor
    install_watcher
    update_backend

    apply_systemd_changes

    log "Atualização concluída."
}

main "$@"
