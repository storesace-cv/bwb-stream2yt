#!/usr/bin/env bash
set -euo pipefail
# Sincroniza secondary-droplet/ e scripts/ para o droplet

DEST_USER="${DEST_USER:-root}"
DEST_IP="${DEST_IP:-104.248.134.44}"
DEST_PORT="${DEST_PORT:-2202}"
DEST_DIR="${DEST_DIR:-/root/bwb-stream2yt}"

CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-10}"
SSH_CMD=(ssh -p "${DEST_PORT}" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout="${CONNECT_TIMEOUT}")

"${SSH_CMD[@]}" "${DEST_USER}@${DEST_IP}" "mkdir -p '${DEST_DIR}/secondary-droplet' '${DEST_DIR}/scripts' '${DEST_DIR}/diags'"

rsync -avz --delete -e "${SSH_CMD[*]}" \
  --exclude '*.env' --exclude 'token.json' --exclude 'client_secret.json' \
  "$(dirname "$0")/../secondary-droplet/" "${DEST_USER}@${DEST_IP}:${DEST_DIR}/secondary-droplet/"
rsync -avz --delete -e "${SSH_CMD[*]}" \
  "$(dirname "$0")/../scripts/" "${DEST_USER}@${DEST_IP}:${DEST_DIR}/scripts/"
rsync -avz --delete -e "${SSH_CMD[*]}" \
  --exclude 'history/' \
  "$(dirname "$0")/../diags/" "${DEST_USER}@${DEST_IP}:${DEST_DIR}/diags/"

echo "[deploy] Sincronização concluída. Execute manualmente:"
echo "  ssh -p ${DEST_PORT} ${DEST_USER}@${DEST_IP} 'bash ${DEST_DIR}/scripts/post_deploy.sh'"
