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
STATE_DIR="/var/lib/bwb-post-deploy"

mkdir -p "$(dirname "${LOG_FILE}")"
mkdir -p "${STATE_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
    echo "[post_deploy] $*"
}

systemctl_available() {
    command -v systemctl >/dev/null 2>&1
}

declare -i SYNC_LAST_CHANGED=0
declare -i NEED_SYSTEMD_RELOAD=0
declare -i RESTART_YOUTUBE_FALLBACK=0
declare -i RESTART_ENSURE_BROADCAST=0
declare -i RESTART_STATUS_MONITOR=0
declare -i RESTART_WATCHER=0

sync_file() {
    local source=$1
    local destination=$2
    local mode=$3
    local owner=${4:-root}
    local group=${5:-root}

    SYNC_LAST_CHANGED=0

    if [[ ! -e "${source}" ]]; then
        log "Aviso: ${source} não encontrado; a ignorar."
        return 0
    fi

    local needs_update=0
    if [[ ! -e "${destination}" ]]; then
        needs_update=1
    else
        if ! cmp -s "${source}" "${destination}"; then
            needs_update=1
        else
            local current_mode owner_name group_name
            current_mode=$(stat -c '%a' "${destination}")
            owner_name=$(stat -c '%U' "${destination}")
            group_name=$(stat -c '%G' "${destination}")
            if [[ "${current_mode}" != "${mode}" || "${owner_name}" != "${owner}" || "${group_name}" != "${group}" ]]; then
                needs_update=1
            fi
        fi
    fi

    if [[ "${needs_update}" -eq 1 ]]; then
        install -m "${mode}" -o "${owner}" -g "${group}" "${source}" "${destination}"
        log "Atualizado ${destination}"
        SYNC_LAST_CHANGED=1
    else
        log "Sem alterações em ${destination}"
    fi
}

sync_optional_file() {
    local source=$1
    if [[ -e "${source}" ]]; then
        sync_file "$@"
    else
        log "Opcional ${source##*/} ausente; ignorado."
    fi
}

directory_hash() {
    local dir=$1
    if [[ ! -d "${dir}" ]]; then
        return 1
    fi

    find "${dir}" -type f -print0 | sort -z | xargs -0 --no-run-if-empty sha256sum | sha256sum | awk '{print $1}'
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

    if systemctl is-enabled --quiet "${unit}"; then
        if systemctl is-active --quiet "${unit}"; then
            log "Serviço ${unit} já ativo; nenhuma alteração."
        else
            if systemctl start "${unit}"; then
                log "Serviço ${unit} iniciado."
            else
                log "Aviso: falha ao iniciar ${unit}; ver journalctl para detalhes."
            fi
        fi
        return
    fi

    if systemctl enable --now "${unit}"; then
        log "Serviço ${unit} ativado."
    else
        log "Aviso: não foi possível ativar ${unit}; ver journalctl para detalhes."
    fi
}

ensure_service_if_needed() {
    local unit=$1
    local requested=${2:-0}

    if ! systemctl_available; then
        return
    fi

    local needs_action=${requested}
    if ! systemctl is-enabled --quiet "${unit}"; then
        needs_action=1
    fi
    if ! systemctl is-active --quiet "${unit}"; then
        needs_action=1
    fi

    if (( needs_action )); then
        enable_service "${unit}"
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
    local requirements_file="${SECONDARY_DIR}/requirements.txt"
    local hash_file="${STATE_DIR}/secondary_requirements.sha256"

    if [[ ! -f "${requirements_file}" ]]; then
        log "Aviso: ficheiro de dependências ${requirements_file} não encontrado; a ignorar."
        return
    fi

    local current_hash previous_hash=""
    current_hash=$(sha256sum "${requirements_file}" | awk '{print $1}')
    if [[ -f "${hash_file}" ]]; then
        previous_hash=$(cat "${hash_file}")
    fi

    if [[ "${current_hash}" == "${previous_hash}" ]]; then
        log "Dependências do fallback inalteradas; instalação ignorada."
        return
    fi

    log "Instalando dependências Python do fallback"
    pip3 install --no-cache-dir -r "${requirements_file}"
    printf '%s' "${current_hash}" > "${hash_file}"
    log "Dependências Python atualizadas."
}

install_secondary_services() {
    log "Sincronizando serviço principal de fallback"
    sync_file "${SECONDARY_DIR}/bin/youtube_fallback.sh" /usr/local/bin/youtube_fallback.sh 755
    if (( SYNC_LAST_CHANGED )); then
        RESTART_YOUTUBE_FALLBACK=1
    fi

    sync_file "${SECONDARY_DIR}/systemd/youtube-fallback.service" /etc/systemd/system/youtube-fallback.service 644
    if (( SYNC_LAST_CHANGED )); then
        NEED_SYSTEMD_RELOAD=1
        RESTART_YOUTUBE_FALLBACK=1
    fi

    log "Sincronizando verificação automática de broadcast"
    sync_file "${SECONDARY_DIR}/bin/ensure_broadcast.py" /usr/local/bin/ensure_broadcast.py 755
    if (( SYNC_LAST_CHANGED )); then
        RESTART_ENSURE_BROADCAST=1
    fi

    sync_file "${SECONDARY_DIR}/systemd/ensure-broadcast.service" /etc/systemd/system/ensure-broadcast.service 644
    if (( SYNC_LAST_CHANGED )); then
        NEED_SYSTEMD_RELOAD=1
        RESTART_ENSURE_BROADCAST=1
    fi

    sync_file "${SECONDARY_DIR}/systemd/ensure-broadcast.timer" /etc/systemd/system/ensure-broadcast.timer 644
    if (( SYNC_LAST_CHANGED )); then
        NEED_SYSTEMD_RELOAD=1
        RESTART_ENSURE_BROADCAST=1
    fi
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

    sync_file "${tmp_env}" "${env_file}" 644
    if (( SYNC_LAST_CHANGED )); then
        RESTART_YOUTUBE_FALLBACK=1
    fi

    trap - RETURN
    rm -f "${tmp_env}"
}

install_status_monitor() {
    log "Instalando monitor HTTP de status"
    sync_file "${SECONDARY_DIR}/bin/bwb_status_monitor.py" /usr/local/bin/bwb_status_monitor.py 755
    if (( SYNC_LAST_CHANGED )); then
        RESTART_STATUS_MONITOR=1
    fi

    sync_file "${SECONDARY_DIR}/systemd/yt-restapi.service" /etc/systemd/system/yt-restapi.service 644
    if (( SYNC_LAST_CHANGED )); then
        NEED_SYSTEMD_RELOAD=1
        RESTART_STATUS_MONITOR=1
    fi

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
        log "Configuração padrão criada em ${env_file}"
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

    sync_file "${tmp}" "${sudoers_file}" 440
    local sudoers_changed=$(( SYNC_LAST_CHANGED ))
    rm -f "${tmp}"

    if (( sudoers_changed )); then
        if command -v visudo >/dev/null 2>&1; then
            if ! visudo -cf "${sudoers_file}" >/dev/null; then
                rm -f "${sudoers_file}"
                log "Erro: validação de ${sudoers_file} falhou"
                exit 1
            fi
        else
            log "Aviso: visudo não encontrado; sudoers não foi validado automaticamente."
        fi
    fi
}

install_watcher() {
    log "Instalando watcher de fallback do YouTube"
    sync_file "${SECONDARY_DIR}/bin/youtube_fallback_watcher.py" /usr/local/bin/youtube_fallback_watcher.py 755
    if (( SYNC_LAST_CHANGED )); then
        RESTART_WATCHER=1
    fi

    sync_file "${SECONDARY_DIR}/systemd/youtube-fallback-watcher.service" /etc/systemd/system/youtube-fallback-watcher.service 644
    if (( SYNC_LAST_CHANGED )); then
        NEED_SYSTEMD_RELOAD=1
        RESTART_WATCHER=1
    fi

    local config_file="/etc/youtube-fallback-watcher.conf"
    if [[ ! -f "${config_file}" ]]; then
        sync_file "${SECONDARY_DIR}/config/youtube-fallback-watcher.conf" "${config_file}" 644
        log "Configuração padrão criada em ${config_file}"
    fi
}

update_backend() {
    local backend_dir="${SECONDARY_DIR}/ytc-web-backend"
    local state_file="${STATE_DIR}/ytc_web_backend.sha256"

    local current_hash
    if ! current_hash=$(directory_hash "${backend_dir}"); then
        log "Aviso: diretório ${backend_dir} inexistente; configuração ignorada."
        return
    fi

    local previous_hash=""
    if [[ -f "${state_file}" ]]; then
        previous_hash=$(cat "${state_file}")
    fi

    if [[ "${current_hash}" == "${previous_hash}" ]]; then
        log "Backend do ytc-web sem alterações; configuração ignorada."
        return
    fi

    log "Preparando backend do ytc-web"
    bash "${SECONDARY_DIR}/bin/ytc_web_backend_setup.sh"
    printf '%s' "${current_hash}" > "${state_file}"
    log "Configuração do backend do ytc-web atualizada."
}

apply_systemd_changes() {
    if (( NEED_SYSTEMD_RELOAD )); then
        systemd_reload
    fi

    ensure_service_if_needed youtube-fallback.service ${RESTART_YOUTUBE_FALLBACK}
    ensure_service_if_needed ensure-broadcast.timer ${RESTART_ENSURE_BROADCAST}
    ensure_service_if_needed yt-restapi.service ${RESTART_STATUS_MONITOR}

    if ! systemctl_available; then
        return
    fi

    if (( RESTART_YOUTUBE_FALLBACK )); then
        restart_if_running youtube-fallback.service
    fi

    if (( RESTART_ENSURE_BROADCAST )); then
        restart_if_running ensure-broadcast.timer
    fi

    if (( RESTART_STATUS_MONITOR )); then
        restart_if_running yt-restapi.service
    fi

    if (( RESTART_WATCHER )); then
        if systemctl is-enabled --quiet youtube-fallback-watcher.service; then
            restart_if_running youtube-fallback-watcher.service
        else
            log "Watcher youtube-fallback-watcher.service atualizado; ative manualmente se necessário."
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
