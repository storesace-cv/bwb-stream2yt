#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BASH_VERSION:-}" ]]; then
    echo "[post_deploy] Este script requer bash para executar." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/post_deploy/common.sh
source "${SCRIPT_DIR}/lib/post_deploy/common.sh"

REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SECONDARY_DIR="${REPO_DIR}/secondary-droplet"
LOG_FILE="/var/log/bwb_post_deploy.log"
STATE_DIR="/var/lib/bwb-post-deploy"

mkdir -p "$(dirname "${LOG_FILE}")"
mkdir -p "${STATE_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

declare -i NEED_SYSTEMD_RELOAD=0
declare -i RESTART_YOUTUBE_FALLBACK=0
declare -i RESTART_ENSURE_BROADCAST=0
declare -i RESTART_STATUS_MONITOR=0
declare -i RESTART_WATCHER=0

declare -a INFO_ITEMS=()
declare -a USER_ACTIONS=()

record_info() {
    INFO_ITEMS+=("$1")
}

record_user_action() {
    USER_ACTIONS+=("$1")
}

sync_and_track() {
    local source=$1
    local destination=$2
    local mode=$3
    local info_message=${4:-}
    local reload_flag=${5:-}
    local restart_flag=${6:-}
    local owner=${7:-root}
    local group=${8:-root}

    pd_sync_file "${source}" "${destination}" "${mode}" "${owner}" "${group}"

    if (( PD_LAST_SYNC_CHANGED )); then
        if [[ -n "${reload_flag}" ]]; then
            printf -v "${reload_flag}" 1
        fi
        if [[ -n "${restart_flag}" ]]; then
            printf -v "${restart_flag}" 1
        fi
        if [[ -n "${info_message}" ]]; then
            record_info "${info_message}"
        fi
    fi
}

sync_optional_and_track() {
    local source=$1
    local destination=$2
    local mode=$3
    local info_message=${4:-}
    local reload_flag=${5:-}
    local restart_flag=${6:-}
    local owner=${7:-root}
    local group=${8:-root}

    pd_sync_optional_file "${source}" "${destination}" "${mode}" "${owner}" "${group}"

    if (( PD_LAST_SYNC_CHANGED )); then
        if [[ -n "${reload_flag}" ]]; then
            printf -v "${reload_flag}" 1
        fi
        if [[ -n "${restart_flag}" ]]; then
            printf -v "${restart_flag}" 1
        fi
        if [[ -n "${info_message}" ]]; then
            record_info "${info_message}"
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
    record_info "Dependências Python do fallback atualizadas."
}

install_secondary_services() {
    log "Sincronizando serviço principal de fallback"
    sync_and_track "${SECONDARY_DIR}/bin/youtube_fallback.sh" \
        /usr/local/bin/youtube_fallback.sh 755 \
        "/usr/local/bin/youtube_fallback.sh atualizado." "" RESTART_YOUTUBE_FALLBACK

    sync_and_track "${SECONDARY_DIR}/systemd/youtube-fallback.service" \
        /etc/systemd/system/youtube-fallback.service 644 \
        "/etc/systemd/system/youtube-fallback.service atualizado." NEED_SYSTEMD_RELOAD RESTART_YOUTUBE_FALLBACK

    log "Sincronizando verificação automática de broadcast"
    sync_and_track "${SECONDARY_DIR}/bin/ensure_broadcast.py" \
        /usr/local/bin/ensure_broadcast.py 755 \
        "/usr/local/bin/ensure_broadcast.py atualizado." "" RESTART_ENSURE_BROADCAST

    sync_and_track "${SECONDARY_DIR}/systemd/ensure-broadcast.service" \
        /etc/systemd/system/ensure-broadcast.service 644 \
        "/etc/systemd/system/ensure-broadcast.service atualizado." NEED_SYSTEMD_RELOAD RESTART_ENSURE_BROADCAST

    sync_and_track "${SECONDARY_DIR}/systemd/ensure-broadcast.timer" \
        /etc/systemd/system/ensure-broadcast.timer 644 \
        "/etc/systemd/system/ensure-broadcast.timer atualizado." NEED_SYSTEMD_RELOAD RESTART_ENSURE_BROADCAST
}

install_utilities() {
    log "Instalando utilitários administrativos"
    sync_optional_and_track "${SCRIPT_DIR}/reset_secondary_droplet.sh" \
        /usr/local/bin/reset_secondary_droplet.sh 755 \
        "/usr/local/bin/reset_secondary_droplet.sh atualizado."
    sync_optional_and_track "${SCRIPT_DIR}/status-monitor-debug.sh" \
        /usr/local/bin/status-monitor-debug.sh 755 \
        "/usr/local/bin/status-monitor-debug.sh atualizado."
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

    sync_and_track "${tmp_env}" "${env_file}" 644 \
        "/etc/youtube-fallback.env atualizado." "" RESTART_YOUTUBE_FALLBACK

    trap - RETURN
    rm -f "${tmp_env}"
}

install_status_monitor() {
    log "Instalando monitor HTTP de status"
    sync_and_track "${SECONDARY_DIR}/bin/bwb_status_monitor.py" \
        /usr/local/bin/bwb_status_monitor.py 755 \
        "/usr/local/bin/bwb_status_monitor.py atualizado." "" RESTART_STATUS_MONITOR

    sync_and_track "${SECONDARY_DIR}/systemd/yt-restapi.service" \
        /etc/systemd/system/yt-restapi.service 644 \
        "/etc/systemd/system/yt-restapi.service atualizado." NEED_SYSTEMD_RELOAD RESTART_STATUS_MONITOR

    if ! id -u yt-restapi >/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin yt-restapi
        log "Utilizador yt-restapi criado"
        record_info "Conta de sistema yt-restapi criada."
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
        record_info "/etc/yt-restapi.env criado."
    fi

    install_yt_restapi_sudoers
}

install_yt_restapi_sudoers() {
    local sudoers_file="/etc/sudoers.d/yt-restapi"
    local tmp
    tmp="$(mktemp)"

    cat <<'SUDOEOF' > "${tmp}"
yt-restapi ALL=(root) NOPASSWD: /usr/bin/systemctl start youtube-fallback.service, /usr/bin/systemctl stop youtube-fallback.service, /usr/bin/systemctl status youtube-fallback.service, /usr/bin/systemctl restart youtube-fallback.service, /usr/bin/systemctl reload youtube-fallback.service
SUDOEOF

    pd_sync_file "${tmp}" "${sudoers_file}" 440
    local sudoers_changed=$(( PD_LAST_SYNC_CHANGED ))
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
        record_info "/etc/sudoers.d/yt-restapi atualizado."
    fi
}

install_watcher() {
    log "Instalando watcher de fallback do YouTube"
    sync_and_track "${SECONDARY_DIR}/bin/youtube_fallback_watcher.py" \
        /usr/local/bin/youtube_fallback_watcher.py 755 \
        "/usr/local/bin/youtube_fallback_watcher.py atualizado." "" RESTART_WATCHER

    sync_and_track "${SECONDARY_DIR}/systemd/youtube-fallback-watcher.service" \
        /etc/systemd/system/youtube-fallback-watcher.service 644 \
        "/etc/systemd/system/youtube-fallback-watcher.service atualizado." NEED_SYSTEMD_RELOAD RESTART_WATCHER

    local config_file="/etc/youtube-fallback-watcher.conf"
    if [[ ! -f "${config_file}" ]]; then
        pd_sync_file "${SECONDARY_DIR}/config/youtube-fallback-watcher.conf" "${config_file}" 644
        log "Configuração padrão criada em ${config_file}"
        record_info "/etc/youtube-fallback-watcher.conf criado."
    fi
}

update_backend() {
    local backend_dir="${SECONDARY_DIR}/ytc-web-backend"
    local state_file="${STATE_DIR}/ytc_web_backend.sha256"

    local current_hash
    if ! current_hash=$(pd_directory_hash "${backend_dir}"); then
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
    record_info "Backend do ytc-web atualizado."
}

apply_systemd_changes() {
    if (( NEED_SYSTEMD_RELOAD )); then
        pd_systemd_reload
    fi

    pd_ensure_service_if_needed youtube-fallback.service ${RESTART_YOUTUBE_FALLBACK}
    pd_ensure_service_if_needed ensure-broadcast.timer ${RESTART_ENSURE_BROADCAST}
    pd_ensure_service_if_needed yt-restapi.service ${RESTART_STATUS_MONITOR}

    if ! pd_systemctl_available; then
        return
    fi

    if (( RESTART_YOUTUBE_FALLBACK )); then
        pd_restart_if_running youtube-fallback.service
    fi

    if (( RESTART_ENSURE_BROADCAST )); then
        pd_restart_if_running ensure-broadcast.timer
    fi

    if (( RESTART_STATUS_MONITOR )); then
        pd_restart_if_running yt-restapi.service
    fi

    if (( RESTART_WATCHER )); then
        if systemctl is-enabled --quiet youtube-fallback-watcher.service; then
            pd_restart_if_running youtube-fallback-watcher.service
        else
            log "Watcher youtube-fallback-watcher.service atualizado; ative manualmente se necessário."
            record_user_action "Ativar youtube-fallback-watcher.service caso pretenda executar o watcher automaticamente."
        fi
    fi
}

print_summary_block() {
    local title=$1
    shift || true

    echo
    echo "${title}"
    local underline=""
    local title_len=${#title}
    for ((i = 0; i < title_len; i++)); do
        underline+='='
    done
    printf '%s\n' "${underline}"

    if (($# == 0)); then
        if [[ "${title}" == "BLOCO INFORMATIVO" ]]; then
            echo "- Nenhuma alteração aplicada nesta execução."
        else
            echo "- Nenhuma ação pendente para o utilizador."
        fi
        return
    fi

    local item
    for item in "$@"; do
        echo "- ${item}"
    done
}

print_summary_blocks() {
    print_summary_block "BLOCO INFORMATIVO" "${INFO_ITEMS[@]}"
    print_summary_block "ACÇÕES A TOMAR POR PARTE DO UTILIZADOR:" "${USER_ACTIONS[@]}"
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
    print_summary_blocks
}

main "$@"
