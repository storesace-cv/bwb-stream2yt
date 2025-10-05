#!/usr/bin/env bash
set -euo pipefail

cd /root/bwb-stream2yt/secondary-droplet

# Garante que o módulo venv esteja disponível antes de preparar o backend
ensure_python3_venv() {
    if python3 -m venv --help >/dev/null 2>&1; then
        echo "[post_deploy] python3 venv disponível; nenhum pacote adicional necessário."
        return
    fi

    echo "[post_deploy] python3 venv ausente; iniciando instalação do pacote python3-venv..."
    apt-get update

    if apt-get install -y python3-venv; then
        echo "[post_deploy] Pacote python3-venv instalado com sucesso."
    else
        python_minor_version="$(python3 -V 2>&1 | awk '{print $2}' | cut -d. -f1,2)"
        fallback_package="python${python_minor_version}-venv"
        echo "[post_deploy] python3-venv indisponível; tentando instalar ${fallback_package}..."
        apt-get install -y "${fallback_package}"
        echo "[post_deploy] Pacote ${fallback_package} instalado com sucesso."
    fi

    if python3 -m venv --help >/dev/null 2>&1; then
        echo "[post_deploy] python3 venv validado após instalação."
    else
        echo "[post_deploy] ERRO: python3 venv permanece indisponível após instalar dependências." >&2
        exit 1
    fi
}

# Instalar dependências (idempotente)
pip3 install -r requirements.txt

# Instalar/atualizar serviços
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

# Mantemos token.json intacto; /etc/youtube-fallback.env é regenerado preservando YT_KEY.
echo "[post_deploy] youtube-fallback atualizado e env sincronizado."

echo "[post_deploy] Preparando backend do ytc-web via secondary-droplet/bin/ytc_web_backend_setup.sh..."
ensure_python3_venv
/root/bwb-stream2yt/secondary-droplet/bin/ytc_web_backend_setup.sh

systemctl daemon-reload
systemctl enable --now ytc-web-backend.service
systemctl restart ytc-web-backend.service || true

echo "[post_deploy] ytc-web-backend implantado e serviço reiniciado."
