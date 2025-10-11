#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BASH_VERSION:-}" ]]; then
    echo "[post_deploy] Este script requer bash para executar." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_FILE="${SCRIPT_DIR}/lib/post_deploy/common.sh"

if [[ ! -r "${LIB_FILE}" ]]; then
    echo "[post_deploy] Erro: biblioteca comum em falta (${LIB_FILE})." >&2
    exit 1
fi

LOG_FILE="/var/log/bwb_post_deploy.log"
mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

source "${LIB_FILE}"

main() {
    log "Registando saída completa em ${LOG_FILE}"

    remove_legacy_components

    local repo_dir
    repo_dir="$(cd "${SCRIPT_DIR}/.." && pwd)"
    local secondary_dir="${repo_dir}/secondary-droplet"

    log "Instalando dependências base do fallback"
    pip3 install --no-cache-dir -r "${secondary_dir}/requirements.txt"

    ensure_installed_file "${secondary_dir}/bin/youtube_fallback.sh" /usr/local/bin/youtube_fallback.sh 755
    ensure_installed_file "${secondary_dir}/systemd/youtube-fallback.service" /etc/systemd/system/youtube-fallback.service 644
    ensure_installed_file "${secondary_dir}/bin/ensure_broadcast.py" /usr/local/bin/ensure_broadcast.py 755
    ensure_installed_file "${secondary_dir}/systemd/ensure-broadcast.service" /etc/systemd/system/ensure-broadcast.service 644
    ensure_installed_file "${secondary_dir}/systemd/ensure-broadcast.timer" /etc/systemd/system/ensure-broadcast.timer 644

    log "Instalando utilitários administrativos no /usr/local/bin"

    ensure_installed_file_optional "${SCRIPT_DIR}/reset_secondary_droplet.sh" /usr/local/bin/reset_secondary_droplet.sh 755
    ensure_installed_file_optional "${SCRIPT_DIR}/status-monitor-debug.sh" /usr/local/bin/status-monitor-debug.sh 755

    local ENV_FILE="/etc/youtube-fallback.env"
    local DEFAULTS_FILE="${secondary_dir}/config/youtube-fallback.defaults"

    local existing_key=""
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

    local tmp_env
    tmp_env="$(mktemp)"
    trap 'rm -f "${tmp_env}"' RETURN
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
    trap - RETURN
    rm -f "${tmp_env}"

    maybe_systemctl_daemon_reload
    systemctl stop youtube-fallback.service || true
    systemctl disable youtube-fallback.service || true
    systemctl enable --now ensure-broadcast.timer

    setup_status_monitor "${secondary_dir}"

    log "youtube-fallback atualizado e env sincronizado."

    log "Preparando backend do ytc-web via secondary-droplet/bin/ytc_web_backend_setup.sh..."
    ensure_python_venv
    bash "${secondary_dir}/bin/ytc_web_backend_setup.sh"

    ensure_swap

    log "Operação concluída."
    print_available_scripts

    if command -v deactivate >/dev/null 2>&1; then
        deactivate
    fi
}

main "$@"
