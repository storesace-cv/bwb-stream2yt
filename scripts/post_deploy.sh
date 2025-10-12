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
    ensure_installed_file "${secondary_dir}/bin/yt-fallback" /usr/local/bin/yt-fallback 755
    ensure_installed_file "${secondary_dir}/bin/yt-comm-watcher.sh" /usr/local/bin/yt-comm-watcher.sh 755
    ensure_installed_file "${secondary_dir}/systemd/youtube-fallback.service" /etc/systemd/system/youtube-fallback.service 644
    ensure_installed_file "${secondary_dir}/systemd/yt-comm-watcher.service" /etc/systemd/system/yt-comm-watcher.service 644
    ensure_installed_file "${secondary_dir}/bin/ensure_broadcast.py" /usr/local/bin/ensure_broadcast.py 755
    ensure_installed_file "${secondary_dir}/systemd/ensure-broadcast.service" /etc/systemd/system/ensure-broadcast.service 644
    ensure_installed_file "${secondary_dir}/systemd/ensure-broadcast.timer" /etc/systemd/system/ensure-broadcast.timer 644

    log "Instalando utilitários administrativos no /usr/local/bin"

    ensure_installed_file_optional "${SCRIPT_DIR}/reset_secondary_droplet.sh" /usr/local/bin/reset_secondary_droplet.sh 755
    ensure_installed_file_optional "${SCRIPT_DIR}/status-monitor-debug.sh" /usr/local/bin/status-monitor-debug.sh 755

    prepare_fallback_env "${secondary_dir}"

    maybe_systemctl_daemon_reload

    # ==== Controle seguro do youtube-fallback.service ====
    : "${TOUCH_YT_FALLBACK:=0}"          # 0 = não mexer (default)
    : "${YT_FALLBACK_ACTION:=none}"      # none|restart|stop|start
    local svc="youtube-fallback.service"

    if [[ "${TOUCH_YT_FALLBACK}" == "1" ]]; then
        case "${YT_FALLBACK_ACTION}" in
            restart)
                systemctl enable "${svc}" || true
                systemctl restart "${svc}" || true
                ;;
            start)
                systemctl enable "${svc}" || true
                systemctl start "${svc}" || true
                ;;
            stop)
                systemctl stop "${svc}" || true
                ;;
            none|*)
                ;;
        esac
    fi

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

clean_env_value() {
    local value="$1"
    value="$(printf '%s' "$value" | tr -d '\r\n\t')"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    echo "$value"
}

sanitize_stream_key() {
    local key
    key="$(clean_env_value "$1")"
    key="${key// /}"
    key="${key//\?backup=1\/}"
    key="${key//backup=1\/}"
    key="${key//\?backup=1/}"
    key="${key##*live2/}"
    key="${key##*/}"
    key="${key%%\?*}"
    echo "$key"
}

prepare_fallback_env() {
    local secondary_dir="$1"
    local env_link="/etc/youtube-fallback.env"
    local env_dir="/etc/youtube-fallback.d"
    local src_dir="${secondary_dir}/config/youtube-fallback.d"
    local drop_in_dir="/etc/systemd/system/youtube-fallback.service.d"
    local existing_url=""
    local existing_key=""
    local current_target=""

    if [[ -d "${drop_in_dir}" ]]; then
        local legacy_removed=0
        if [[ -f "${drop_in_dir}/override.conf" ]]; then
            rm -f "${drop_in_dir}/override.conf"
            log "Removido drop-in legacy ${drop_in_dir}/override.conf."
            legacy_removed=1
        fi
        if rmdir "${drop_in_dir}" 2>/dev/null; then
            log "Removido diretório vazio ${drop_in_dir}."
        elif (( legacy_removed == 1 )); then
            log "Drop-in legacy removido mas diretório ${drop_in_dir} mantido (continha outros ficheiros)."
        fi
    fi

    if [[ -L "${env_link}" ]]; then
        current_target="$(readlink -f "${env_link}" || true)"
    fi

    if [[ -f "${env_link}" && ! -L "${env_link}" ]]; then
        while IFS= read -r line; do
            case "${line}" in
                YT_URL=*|YT_URL_BACKUP=*)
                    if [[ -z "${existing_url}" ]]; then
                        existing_url="$(clean_env_value "${line#*=}")"
                    fi
                    ;;
                YT_KEY=*)
                    if [[ -z "${existing_key}" ]]; then
                        existing_key="$(clean_env_value "${line#*=}")"
                    fi
                    ;;
            esac
        done < "${env_link}"
    fi

    if [[ -n "${existing_key}" ]]; then
        existing_key="$(sanitize_stream_key "${existing_key}")"
    fi

    if [[ -n "${existing_key}" && -z "${existing_url}" ]]; then
        existing_url="rtmps://b.rtmps.youtube.com/live2?backup=1/${existing_key}"
    fi

    if [[ -f "${env_link}" && ! -L "${env_link}" ]]; then
        local backup="${env_link}.legacy.$(date +%Y%m%d%H%M%S)"
        mv "${env_link}" "${backup}"
        log "Env legacy detetado; copiado para ${backup}."
    fi

    install -d -m 755 -o root -g root "${env_dir}"

    for profile_path in "${src_dir}"/*.env; do
        [[ -e "${profile_path}" ]] || continue
        local profile_name
        profile_name="$(basename "${profile_path}")"
        local tmp_profile
        tmp_profile="$(mktemp)"
        cp "${profile_path}" "${tmp_profile}"
        if [[ -n "${existing_url}" ]]; then
            local escaped
            escaped="${existing_url//\\/\\\\}"
            escaped="${escaped//&/\\&}"
            if grep -q '^YT_URL=' "${tmp_profile}"; then
                sed -i "s#^YT_URL=.*#YT_URL=\"${escaped}\"#" "${tmp_profile}"
            else
                printf '\nYT_URL="%s"\n' "${existing_url}" >> "${tmp_profile}"
            fi
        fi
        if [[ -n "${existing_key}" ]]; then
            local escaped_key
            escaped_key="${existing_key//\\/\\\\}"
            escaped_key="${escaped_key//&/\\&}"
            if grep -q '^YT_KEY=' "${tmp_profile}"; then
                sed -i "s#^YT_KEY=.*#YT_KEY=\"${escaped_key}\"#" "${tmp_profile}"
            else
                printf 'YT_KEY="%s"\n' "${existing_key}" >> "${tmp_profile}"
            fi
        fi
        install -m 644 -o root -g root "${tmp_profile}" "${env_dir}/${profile_name}"
        rm -f "${tmp_profile}"
    done

    if [[ -z "${current_target}" || ! -e "${current_target}" ]]; then
        current_target="${env_dir}/life.env"
    fi

    ln -sfn "${current_target}" "${env_link}"

    local active_profile="life"
    case "${current_target}" in
        "${env_dir}/bars.env")
            active_profile="bars"
            ;;
        "${env_dir}/life.env")
            active_profile="life"
            ;;
    esac

    log "Perfis do fallback instalados em ${env_dir} (ativo: ${active_profile})."
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
