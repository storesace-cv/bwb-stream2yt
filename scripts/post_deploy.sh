#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[post_deploy] $*"
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECONDARY_DIR="${SCRIPT_DIR}/../secondary-droplet"

cd "${SECONDARY_DIR}"

log "Instalando dependências base do fallback"
pip3 install --no-cache-dir -r requirements.txt

install -m 755 -o root -g root bin/youtube_fallback.sh /usr/local/bin/youtube_fallback.sh
install -m 644 -o root -g root systemd/youtube-fallback.service /etc/systemd/system/youtube-fallback.service
install -m 755 -o root -g root bin/ensure_broadcast.py /usr/local/bin/ensure_broadcast.py
install -m 644 -o root -g root systemd/ensure-broadcast.service /etc/systemd/system/ensure-broadcast.service
install -m 644 -o root -g root systemd/ensure-broadcast.timer /etc/systemd/system/ensure-broadcast.timer

log "Instalando utilitários administrativos no /usr/local/bin"

maybe_install_admin_script() {
    local label="$1"
    local source_path="$2"
    local dest_path="$3"

    if [[ -f "${source_path}" ]]; then
        install -m 755 -o root -g root "${source_path}" "${dest_path}"
    else
        log "Aviso: ${label} não encontrado em ${source_path}; instalação ignorada."
    fi
}

maybe_install_admin_script \
    "reset_secondary_droplet.sh" \
    "${SCRIPT_DIR}/reset_secondary_droplet.sh" \
    /usr/local/bin/reset_secondary_droplet.sh
maybe_install_admin_script \
    "yt-decider-debug.sh" \
    "${SCRIPT_DIR}/yt-decider-debug.sh" \
    /usr/local/bin/yt-decider-debug.sh

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
systemctl enable --now youtube-fallback.service
systemctl restart youtube-fallback.service || true
systemctl enable --now ensure-broadcast.timer

log "youtube-fallback atualizado e env sincronizado."

log "Preparando backend do ytc-web via secondary-droplet/bin/ytc_web_backend_setup.sh..."
ensure_python_venv
bash bin/ytc_web_backend_setup.sh

ensure_swap

log "Operação concluída."

if command -v deactivate >/dev/null 2>&1; then
    deactivate
fi
