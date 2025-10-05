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
BACKEND_PORT="${YTC_WEB_BACKEND_PORT:-8081}"
ALLOWED_IP="94.46.15.210"

ensure_firewall_rule() {
  if ! command -v ufw >/dev/null 2>&1; then
    log "ufw não está instalado; saltando configuração de firewall"
    return
  fi

  local status
  status=$(ufw status | awk 'NR==1 {print $2}')
  if [ "${status}" != "active" ]; then
    log "Activando firewall (ufw)"
    ufw --force enable
  else
    log "Firewall já activo"
  fi

  local allow_pattern="${BACKEND_PORT}/tcp"
  if ufw status | grep -E "${allow_pattern}[[:space:]]+ALLOW[[:space:]]+${ALLOWED_IP}" >/dev/null 2>&1; then
    log "Regra restritiva existente para ${ALLOWED_IP}:${BACKEND_PORT}"
  else
    log "Aplicando regra restritiva: ufw allow from ${ALLOWED_IP} to any port ${BACKEND_PORT} proto tcp"
    ufw allow from "${ALLOWED_IP}" to any port "${BACKEND_PORT}" proto tcp
  fi

  local line number rule
  mapfile -t generic_rules < <(
    ufw status numbered | while IFS= read -r line; do
      if [ "${line:0:1}" != "[" ]; then
        continue
      fi
      number=${line:1}
      number=${number%%]*}
      rule=${line#*] }
      if [[ "${rule}" == *"${allow_pattern}"* && "${rule}" == *"ALLOW"* && "${rule}" == *"Anywhere"* ]]; then
        printf '%s\n' "${number}"
      fi
    done
  )

  if [ ${#generic_rules[@]} -gt 0 ]; then
    log "Removendo regras genéricas para ${BACKEND_PORT}/tcp"
    for (( idx=${#generic_rules[@]}-1; idx>=0; idx-- )); do
      ufw --force delete "${generic_rules[idx]}"
    done
  fi

  log "Firewall configurado. Verifique com: ufw status numbered | grep ${ALLOWED_IP}"
}

log "Preparando diretório da aplicação em ${INSTALL_DIR}"
install -d -m 755 -o root -g root "${INSTALL_DIR}"

if [[ -x "${VENV_DIR}/bin/pip" ]]; then
  log "Reaproveitando virtualenv existente em ${VENV_DIR}"
else
  if [[ -d "${VENV_DIR}" ]]; then
    log "pip ausente ou não executável; removendo virtualenv corrompido em ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
  fi

  log "Reconstruindo virtualenv em ${VENV_DIR}"
  if python3 -m venv "${VENV_DIR}"; then
    log "Virtualenv recriado com sucesso"
  else
    log "Falha ao criar virtualenv em ${VENV_DIR}" >&2
    exit 1
  fi
fi

log "Actualizando pip e instalando dependências"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
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

ensure_firewall_rule

log "Configuração do backend web concluída."
