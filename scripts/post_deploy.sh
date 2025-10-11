#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/var/log/bwb_post_deploy.log"
mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

log() {
    echo "[post_deploy] $*"
}

print_available_scripts() {
    log "Scripts disponíveis para diagnóstico e recuperação:"
    log "  reset_secondary_droplet.sh — limpa caches e reinicia serviços críticos (fallback, decider, backend)."
    log "    Comando: sudo /usr/local/bin/reset_secondary_droplet.sh"
    log "  yt-decider-debug.sh — recolhe logs do yt-decider das últimas 48h e gera ficheiro de análise."
    log "    Comando: sudo /usr/local/bin/yt-decider-debug.sh"
    log "  ensure_broadcast.py — valida se existe live do YouTube pronta e ligada ao stream correto."
    log "    Comando: sudo /usr/local/bin/ensure_broadcast.py"
    log "  bwb_status_monitor.py — servidor HTTP que recebe heartbeats do primário; ver --help para opções."
    log "    Comando: sudo /usr/local/bin/bwb_status_monitor.py --help"
}

STATE_DIR="/var/lib/bwb-post-deploy"
mkdir -p "${STATE_DIR}"
REQUIREMENTS_HASH_FILE="${STATE_DIR}/secondary_requirements.sha256"
NEED_DAEMON_RELOAD=false

maybe_systemctl_daemon_reload() {
    if [[ "${NEED_DAEMON_RELOAD}" == "true" ]]; then
        log "systemd recebeu alterações; executando daemon-reload."
        systemctl daemon-reload
        NEED_DAEMON_RELOAD=false
    fi
}

ensure_installed_file() {
    local src="$1"
    local dest="$2"
    local mode="$3"
    local owner="${4:-root}"
    local group="${5:-root}"
    local need_install=0

    if [[ ! -e "${dest}" ]]; then
        need_install=1
    else
        if ! cmp -s "${src}" "${dest}"; then
            need_install=1
        else
            local current_mode
            current_mode=$(stat -c '%a' "${dest}")
            if (( 8#${current_mode} != 8#${mode} )); then
                need_install=1
            else
                local current_owner
                local current_group
                current_owner=$(stat -c '%U' "${dest}")
                current_group=$(stat -c '%G' "${dest}")
                if [[ "${current_owner}" != "${owner}" || "${current_group}" != "${group}" ]]; then
                    need_install=1
                fi
            fi
        fi
    fi

    if (( need_install )); then
        install -m "${mode}" -o "${owner}" -g "${group}" "${src}" "${dest}"
        log "Atualizado ${dest} a partir de ${src}."
        if [[ "${dest}" == /etc/systemd/system/* ]]; then
            NEED_DAEMON_RELOAD=true
        fi
        return 0
    fi

    log "${dest} já está actualizado; sem alterações."
    return 1
}

systemctl_is_enabled() {
    systemctl is-enabled "$1" >/dev/null 2>&1
}

systemctl_is_active() {
    systemctl is-active "$1" >/dev/null 2>&1
}

ensure_service_disabled() {
    local unit="$1"
    if systemctl_is_enabled "${unit}"; then
        log "Desativando ${unit} (--now) para manter estado esperado."
        systemctl disable --now "${unit}"
    elif systemctl_is_active "${unit}"; then
        log "${unit} ativo mas não estava desativado; a parar."
        systemctl stop "${unit}"
    else
        log "${unit} já se encontra parado e desativado."
    fi
}

ensure_timer_enabled() {
    local timer="$1"
    if systemctl_is_enabled "${timer}"; then
        if systemctl_is_active "${timer}"; then
            log "${timer} já está ativo e habilitado."
        else
            log "${timer} estava habilitado mas parado; a iniciar."
            systemctl start "${timer}"
        fi
    else
        log "Ativando ${timer} (--now)."
        systemctl enable --now "${timer}"
    fi
}

log "Registando saída completa em ${LOG_FILE}"

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

ensure_secondary_requirements() {
    local force="${FORCE_REDEPLOY:-}"
    local requirements_path="${SECONDARY_DIR}/requirements.txt"
    local current_hash
    current_hash=$(sha256sum "${requirements_path}" | awk '{print $1}')
    local previous_hash=""
    if [[ -f "${REQUIREMENTS_HASH_FILE}" ]]; then
        previous_hash=$(<"${REQUIREMENTS_HASH_FILE}")
    fi

    if [[ "${force}" == "1" ]]; then
        log "FORCE_REDEPLOY=1 detectado; reinstalando dependências do fallback."
    fi

    if [[ "${current_hash}" != "${previous_hash}" || "${force}" == "1" ]]; then
        log "Instalando dependências base do fallback (requirements.txt actualizado)."
        pip3 install --no-cache-dir -r requirements.txt
        echo "${current_hash}" > "${REQUIREMENTS_HASH_FILE}"
    else
        log "Dependências base já instaladas; nenhuma ação necessária."
    fi
}

setup_status_monitor() {
    log "Instalando monitor HTTP de status do primário"

    local restart_required=false

    if ensure_installed_file \
        bin/bwb_status_monitor.py \
        /usr/local/bin/bwb_status_monitor.py \
        755 root root; then
        restart_required=true
    fi

    if ensure_installed_file \
        systemd/bwb-status-monitor.service \
        /etc/systemd/system/bwb-status-monitor.service \
        644 root root; then
        restart_required=true
    fi

    maybe_systemctl_daemon_reload

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
    local tmp_env
    tmp_env=$(mktemp)
    cat <<'ENVEOF' >"${tmp_env}"
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
    if ensure_installed_file "${tmp_env}" "${env_file}" 640 root root; then
        restart_required=true
    fi
    rm -f "${tmp_env}"

    if command -v ufw >/dev/null 2>&1; then
        if ufw status 2>/dev/null | grep -qi "status: active"; then
            if ! ufw status 2>/dev/null | grep -qE '\b8080/tcp\b'; then
                if ! ufw allow 8080/tcp; then
                    log "Aviso: não foi possível abrir a porta 8080 no ufw"
                fi
            fi
        fi
    fi

    if ! systemctl_is_enabled bwb-status-monitor.service; then
        log "Ativando bwb-status-monitor.service para arranque automático."
        systemctl enable bwb-status-monitor.service
    else
        log "bwb-status-monitor.service já está configurado para iniciar no arranque."
    fi

    if systemctl_is_active bwb-status-monitor.service; then
        if [[ "${restart_required}" == "true" ]]; then
            log "Reiniciando bwb-status-monitor.service para aplicar alterações."
            systemctl restart bwb-status-monitor.service
        else
            log "bwb-status-monitor.service já está em execução."
        fi
    else
        log "Iniciando bwb-status-monitor.service."
        systemctl start bwb-status-monitor.service
    fi

    log "Monitor de status ativo em ${state_dir}"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SECONDARY_DIR="${REPO_DIR}/secondary-droplet"

cd "${SECONDARY_DIR}"

log "Validando dependências base do fallback"
ensure_secondary_requirements

fallback_changed=false
if ensure_installed_file \
    bin/youtube_fallback.sh \
    /usr/local/bin/youtube_fallback.sh \
    755 root root; then
    fallback_changed=true
fi
if ensure_installed_file \
    systemd/youtube-fallback.service \
    /etc/systemd/system/youtube-fallback.service \
    644 root root; then
    fallback_changed=true
fi

ensure_broadcast_changed=false
if ensure_installed_file \
    bin/ensure_broadcast.py \
    /usr/local/bin/ensure_broadcast.py \
    755 root root; then
    ensure_broadcast_changed=true
fi
if ensure_installed_file \
    systemd/ensure-broadcast.service \
    /etc/systemd/system/ensure-broadcast.service \
    644 root root; then
    ensure_broadcast_changed=true
fi
if ensure_installed_file \
    systemd/ensure-broadcast.timer \
    /etc/systemd/system/ensure-broadcast.timer \
    644 root root; then
    ensure_broadcast_changed=true
fi

maybe_systemctl_daemon_reload

log "Instalando utilitários administrativos no /usr/local/bin"

reset_secondary_source="${SCRIPT_DIR}/reset_secondary_droplet.sh"
if [[ -f "${reset_secondary_source}" ]]; then
    ensure_installed_file "${reset_secondary_source}" /usr/local/bin/reset_secondary_droplet.sh 755 root root
else
    log "Aviso: reset_secondary_droplet.sh não encontrado em ${reset_secondary_source}; instalação ignorada."
fi

yt_decider_debug_source="${SCRIPT_DIR}/yt-decider-debug.sh"
if [[ -f "${yt_decider_debug_source}" ]]; then
    ensure_installed_file "${yt_decider_debug_source}" /usr/local/bin/yt-decider-debug.sh 755 root root
else
    log "Aviso: yt-decider-debug.sh não encontrado em ${yt_decider_debug_source}; instalação ignorada."
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
if ensure_installed_file "${tmp_env}" "${ENV_FILE}" 644 root root; then
    fallback_changed=true
fi
rm -f "${tmp_env}"
trap - EXIT

maybe_systemctl_daemon_reload

ensure_service_disabled youtube-fallback.service
if [[ "${fallback_changed}" == "true" ]]; then
    log "Conteúdo do youtube-fallback atualizado; próximo arranque refletirá alterações."
fi

ensure_timer_enabled ensure-broadcast.timer
if [[ "${ensure_broadcast_changed}" == "true" ]]; then
    if systemctl_is_active ensure-broadcast.service; then
        log "Reiniciando ensure-broadcast.service para aplicar novas versões."
        systemctl restart ensure-broadcast.service
    fi
fi

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
