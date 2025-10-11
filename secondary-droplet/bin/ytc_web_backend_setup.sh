#!/usr/bin/env bash
set -euo pipefail

APP_SRC="/root/bwb-stream2yt/secondary-droplet/ytc-web-backend"
APP_DEST="/opt/ytc-web-service"
VENV_DIR="${APP_DEST}/venv"
SYSTEMD_SRC="/root/bwb-stream2yt/secondary-droplet/systemd/ytc-web-backend.service"
SYSTEMD_DEST="/etc/systemd/system/ytc-web-backend.service"
ENV_FILE="/etc/ytc-web-backend.env"
BACKEND_PORT="${YTC_WEB_BACKEND_PORT:-8081}"
FIREWALL_IP="${YTC_WEB_ALLOWED_IP:-}"

log() {
    echo "[ytc-web-backend-setup] $*"
}

if [[ -z "${FIREWALL_IP}" ]]; then
    log "Variável YTC_WEB_ALLOWED_IP ausente; defina um IP ou '0.0.0.0/0' para aceitar qualquer origem."
    exit 1
fi

install -d -m 755 "${APP_DEST}" "${APP_DEST}/app"

log "Preparando diretório da aplicação em ${APP_DEST}"
rsync -a --delete "${APP_SRC}/" "${APP_DEST}/app/"

if [[ -d "${VENV_DIR}" && ! -x "${VENV_DIR}/bin/pip" ]]; then
    log "pip ausente ou não executável; removendo virtualenv corrompido em ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
    log "Reconstruindo virtualenv em ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}" || {
        log "Falha ao criar virtualenv em ${VENV_DIR}"
        exit 1
    }
else
    log "Reaproveitando virtualenv existente em ${VENV_DIR}"
fi

log "Actualizando pip e instalando dependências"
export PIP_NO_CACHE_DIR=1
"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check --upgrade pip
"${VENV_DIR}/bin/python" -m pip install --disable-pip-version-check -r "${APP_SRC}/requirements.txt"
unset PIP_NO_CACHE_DIR

if [[ ! -f "${ENV_FILE}" ]]; then
    log "Criando ficheiro de ambiente em ${ENV_FILE}"
    cat <<EOT > "${ENV_FILE}"
# Variáveis consumidas por ytc-web-backend.service
YT_OAUTH_TOKEN_PATH=/root/token.json
YTC_WEB_CACHE_TTL=30
YTC_WEB_HTTP_CACHE=10
YTC_WEB_BACKEND_HOST=127.0.0.1
YTC_WEB_BACKEND_PORT=${BACKEND_PORT}
EOT
    chmod 640 "${ENV_FILE}"
else
    log "Ficheiro de ambiente existente preservado em ${ENV_FILE}"
fi

log "Instalando unit do systemd"
install -m 644 "${SYSTEMD_SRC}" "${SYSTEMD_DEST}"
systemctl daemon-reload
systemctl enable --now ytc-web-backend.service
systemctl restart ytc-web-backend.service || true

configure_firewall() {
    log "Configurando firewall (ufw) para ${FIREWALL_IP}:${BACKEND_PORT}/tcp"

    if ! command -v ufw >/dev/null 2>&1; then
        log "ufw não encontrado; instalando pacote"
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y ufw
    fi

    # garantir que o ufw está activo
    ufw --force enable >/dev/null 2>&1 || true

    # remover quaisquer regras ALLOW IN pré-existentes para esta porta
    ufw status numbered \
        | awk -v port="${BACKEND_PORT}" '$0 ~ (" " port "/tcp") && /ALLOW IN/ {print $1}' \
        | tr -d "[] " \
        | sort -rn \
        | while read -r rule_number; do
            [[ -z "${rule_number}" ]] && continue
            ufw --force delete "${rule_number}" >/dev/null 2>&1 || true
        done

    # Verifica se deve abrir a porta a qualquer origem
    if [[ "${FIREWALL_IP}" == "0.0.0.0/0" || "${FIREWALL_IP}" == "any" || "${FIREWALL_IP}" == "*" ]]; then
        log "Configurando firewall para aceitar conexões de qualquer origem (modo global)."
        ufw allow "${BACKEND_PORT}"/tcp
        log "Firewall configurada no modo global (IP dinâmico detectado)"
    else
        log "Configurando firewall restrita a ${FIREWALL_IP}:${BACKEND_PORT}/tcp"
        ufw allow from "${FIREWALL_IP}" to any port "${BACKEND_PORT}" proto tcp
    fi
    ufw reload >/dev/null 2>&1 || true
}

configure_firewall

log "Configuração do backend concluída"
