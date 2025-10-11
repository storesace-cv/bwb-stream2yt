#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BASH_VERSION:-}" ]]; then
    echo "[post_deploy] Este script requer bash para executar." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_FILE="${SCRIPT_DIR}/lib/post_deploy/common.sh"

if [[ -r "${LIB_FILE}" ]]; then
    # shellcheck source=./lib/post_deploy/common.sh
    source "${LIB_FILE}"
else
    echo "[post_deploy] Aviso: biblioteca comum em falta (${LIB_FILE}); a usar versão incorporada." >&2

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
        local source=$1
        if [[ ! -e "${source}" ]]; then
            log "Opcional ${source##*/} ausente; ignorando instalação."
            return 0
        fi

        ensure_installed_file "$@"
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
        if swapon --noheadings 2>/dev/null | grep -q '\\S'; then
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
        ensure_installed_file "${base_dir}/systemd/yt-restapi.service" /etc/systemd/system/yt-restapi.service 644

        if ! id -u yt-restapi >/dev/null 2>&1; then
            log "Criando utilizador de sistema yt-restapi"
            useradd --system --no-create-home --shell /usr/sbin/nologin yt-restapi
        fi

        local state_dir="/var/lib/bwb-status-monitor"
        install -d -m 750 -o yt-restapi -g yt-restapi "${state_dir}"
        if [[ ! -f "${state_dir}/status.json" ]]; then
            printf '[]\n' >"${state_dir}/status.json"
        fi
        chown yt-restapi:yt-restapi "${state_dir}/status.json"
        chmod 640 "${state_dir}/status.json"

        if [[ ! -f "/var/log/bwb_status_monitor.log" ]]; then
            touch /var/log/bwb_status_monitor.log
        fi
        chown yt-restapi:yt-restapi /var/log/bwb_status_monitor.log
        chmod 640 /var/log/bwb_status_monitor.log

        local env_file="/etc/yt-restapi.env"
        if [[ ! -f "${env_file}" ]]; then
            cat <<'ENVEOF' >"${env_file}"
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
        fi
        chmod 640 "${env_file}"
        chown yt-restapi:yt-restapi "${env_file}"

        ensure_yt_restapi_sudoers

        if command -v ufw >/dev/null 2>&1; then
            if ufw status 2>/dev/null | grep -qi "status: active"; then
                if ! ufw status 2>/dev/null | grep -qE '\\b8080/tcp\\b'; then
                    ufw allow 8080/tcp
                else
                    log "UFW já permite 8080/tcp; nenhum ajuste."
                fi
            else
                log "UFW inativo; nenhuma regra adicionada."
            fi
        else
            log "UFW não encontrado; ignorando configuração de firewall."
        fi

        maybe_systemctl_daemon_reload
        systemctl enable --now yt-restapi.service
    }
fi
LOG_FILE="/var/log/bwb_post_deploy.log"
mkdir -p "$(dirname "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

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

ensure_yt_restapi_sudoers() {
    local sudoers_file="/etc/sudoers.d/yt-restapi"
    local tmp
    tmp=$(mktemp)

    cat <<'SUDOEOF' >"${tmp}"
yt-restapi ALL=(root) NOPASSWD: /bin/systemctl start youtube-fallback.service, /bin/systemctl stop youtube-fallback.service, /bin/systemctl status youtube-fallback.service
SUDOEOF

    install -m 440 -o root -g root "${tmp}" "${sudoers_file}"
    rm -f "${tmp}"

    if command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf "${sudoers_file}" >/dev/null; then
            rm -f "${sudoers_file}"
            log "Erro: validação de ${sudoers_file} falhou via visudo"
            exit 1
        fi
        log "yt-restapi sudoers applied (systemctl start/stop/status youtube-fallback.service)"
    else
        log "Aviso: visudo não encontrado; não foi possível validar ${sudoers_file}"
    fi
}

main "$@"
