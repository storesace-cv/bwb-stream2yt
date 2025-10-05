#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[ytc-web-backend-setup] %s\n' "$*"
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT="${SCRIPT_DIR%/bin}"
APP_SRC="${PROJECT_ROOT}/ytc-web-backend"
INSTALL_DIR="/opt/ytc-web-service"
VENV_DIR="${INSTALL_DIR}/venv"
SYSTEMD_SRC="${PROJECT_ROOT}/systemd/ytc-web-backend.service"
SYSTEMD_DEST="/etc/systemd/system/ytc-web-backend.service"
ENV_FILE="/etc/ytc-web-backend.env"

log "Preparando diretório da aplicação em ${INSTALL_DIR}"
install -d -m 755 -o root -g root "${INSTALL_DIR}"

if [ ! -d "${VENV_DIR}" ]; then
  log "Criando virtualenv em ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi

log "Actualizando pip e instalando dependências"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${PROJECT_ROOT}/requirements.txt"
"${VENV_DIR}/bin/pip" install -r "${APP_SRC}/requirements.txt"

log "Sincronizando código da aplicação"
rsync -a --delete "${APP_SRC}/" "${INSTALL_DIR}/"

log "Instalando unit file em ${SYSTEMD_DEST}"
install -m 644 -o root -g root "${SYSTEMD_SRC}" "${SYSTEMD_DEST}"

if [ ! -f "${ENV_FILE}" ]; then
  log "Criando arquivo de ambiente ${ENV_FILE}"
  tmp_env=$(mktemp)
  {
    echo "# /etc/ytc-web-backend.env (gerido por ytc_web_backend_setup.sh)"
    echo "YT_OAUTH_TOKEN_PATH=${YT_OAUTH_TOKEN_PATH:-/root/token.json}"
    echo "YTC_WEB_BACKEND_CACHE_TTL_SECONDS=${YTC_WEB_BACKEND_CACHE_TTL_SECONDS:-30}"
  } > "${tmp_env}"
  install -m 600 -o root -g root "${tmp_env}" "${ENV_FILE}"
  rm -f "${tmp_env}"
else
  chmod 600 "${ENV_FILE}"
fi

log "Configuração do backend web concluída."
