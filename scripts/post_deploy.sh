#!/usr/bin/env bash
set -euo pipefail

cd /root/bwb-stream2yt/secondary-droplet

# Instalar dependências (idempotente)
pip3 install -r requirements.txt

# Instalar/atualizar serviços
install -m 755 -o root -g root bin/youtube_fallback.sh /usr/local/bin/youtube_fallback.sh
install -m 644 -o root -g root systemd/youtube-fallback.service /etc/systemd/system/youtube-fallback.service

systemctl daemon-reload
systemctl enable --now youtube-fallback.service
systemctl restart youtube-fallback.service || true

# Não tocamos em /etc/youtube-fallback.env nem em token.json (segredos)
echo "[post_deploy] youtube-fallback atualizado."
