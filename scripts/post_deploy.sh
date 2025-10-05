#!/usr/bin/env bash
set -euo pipefail

cd /root/bwb-stream2yt/secondary-droplet

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

# Se algum passo anterior activou um virtualenv, garantimos que a shell
# regressa ao ambiente global ao terminar o script. Isto evita que sessões
# interactivas fiquem "presas" num venv quando o operador executa o
# `post_deploy.sh` manualmente.
if command -v deactivate >/dev/null 2>&1; then
    deactivate
fi
