#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[post_deploy] $*"
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

cd /root/bwb-stream2yt/secondary-droplet

log "Instalando dependências base do fallback"
pip3 install --no-cache-dir -r requirements.txt

install -m 755 -o root -g root bin/youtube_fallback.sh /usr/local/bin/youtube_fallback.sh
install -m 644 -o root -g root systemd/youtube-fallback.service /etc/systemd/system/youtube-fallback.service

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

log "youtube-fallback atualizado e env sincronizado."

log "Preparando backend do ytc-web via secondary-droplet/bin/ytc_web_backend_setup.sh..."
ensure_python_venv
bash bin/ytc_web_backend_setup.sh

log "Operação concluída."

if command -v deactivate >/dev/null 2>&1; then
    deactivate
fi
