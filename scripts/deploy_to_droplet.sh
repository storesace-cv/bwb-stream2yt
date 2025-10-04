#!/usr/bin/env bash
set -euo pipefail
# Sincroniza linux-secondary/ e scripts/ para o droplet

DEST_USER="${DEST_USER:-root}"
DEST_IP="${DEST_IP:-104.248.134.44}"
DEST_DIR="${DEST_DIR:-/root/bwb-stream2yt}"

rsync -avz --delete \
  --exclude '*.env' --exclude 'token.json' --exclude 'client_secret.json' \
  "$(dirname "$0")/../linux-secondary/" "${DEST_USER}@${DEST_IP}:${DEST_DIR}/linux-secondary/"
rsync -avz --delete \
  "$(dirname "$0")/post_deploy.sh" "${DEST_USER}@${DEST_IP}:${DEST_DIR}/scripts/post_deploy.sh"

ssh -o StrictHostKeyChecking=accept-new "${DEST_USER}@${DEST_IP}" "bash '${DEST_DIR}/scripts/post_deploy.sh'"
echo "[deploy] Done."
