# Reversão de 12/10/2025 às 14:00

O branch `work` foi alinhado ao conteúdo do commit `f6ac678`, restaurando o código ao estado existente por volta das 14:00 (horário local) do dia 12/10/2025.

As configurações de deploy da droplet foram verificadas e permanecem intactas, incluindo `deploy/deploy_config.json` com o mapeamento de sincronização para os scripts e arquivos de configuração do servidor secundário.

## Comandos executados manualmente na droplet
Caso seja necessário repetir a reversão até o estado confirmado às 14:00, os seguintes comandos foram executados manualmente no servidor (droplet) para restaurar o serviço `youtube-fallback` e as dependências relacionadas:

```
systemctl stop youtube-fallback.service
sleep 1
journalctl -u youtube-fallback.service -b -n 200 --no-pager
systemctl cat youtube-fallback.service
ls -l /usr/local/bin/youtube_fallback.sh
head -n 60 /usr/local/bin/youtube_fallback.sh
readlink -f /etc/youtube-fallback.env
nl -ba /etc/youtube-fallback.env
ffmpeg -hide_banner -version
tr '\0' ' ' </proc/$(pgrep -n ffmpeg 2>/dev/null)/cmdline || true

systemctl stop youtube-fallback.service
mkdir -p /usr/share/fonts/truetype/dejavu
apt-get update -y && apt-get install -y fonts-dejavu-core

cat >/etc/youtube-fallback.env <<'EOF'
YT_URL=rtmp://a.rtmp.youtube.com/live2/f4ex-ztrk-vc4h-2pvc-2kg4
FALLBACK_DEFAULT_MODE=life
FALLBACK_MODE_FILE=/run/youtube-fallback.mode
FALLBACK_WIDTH=1280
FALLBACK_HEIGHT=720
FALLBACK_FPS=30
FALLBACK_VBITRATE=2500k
FALLBACK_MAXRATE=2500k
FALLBACK_BUFSIZE=2M
FALLBACK_ABITRATE=128k
FALLBACK_AR=48000
FALLBACK_PRESET=veryfast
FALLBACK_GOP=60
FALLBACK_KEYINT_MIN=60
FALLBACK_LOGLEVEL=warning
FALLBACK_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
EOF

systemctl daemon-reload
systemctl reset-failed youtube-fallback.service
systemctl start youtube-fallback.service
sleep 2
systemctl status youtube-fallback.service --no-pager
tail -n 120 /root/bwb_services.log
tr '\0' ' ' </proc/$(pgrep -n ffmpeg 2>/dev/null)/cmdline || true
tail -n 80 /run/youtube-fallback.progress 2>/dev/null || true

systemctl stop youtube-fallback.service

cat >/etc/youtube-fallback.env <<'EOF'
YT_KEY=f4ex-ztrk-vc4h-2pvc-2kg4
YT_RTMP_BASE=rtmp://a.rtmp.youtube.com/live2
FALLBACK_DEFAULT_MODE=life
FALLBACK_MODE_FILE=/run/youtube-fallback.mode
FALLBACK_WIDTH=1280
FALLBACK_HEIGHT=720
FALLBACK_FPS=30
FALLBACK_VBITRATE=2500k
FALLBACK_MAXRATE=2500k
FALLBACK_BUFSIZE=2M
FALLBACK_ABITRATE=128k
FALLBACK_AR=48000
FALLBACK_PRESET=veryfast
FALLBACK_GOP=60
FALLBACK_KEYINT_MIN=60
FALLBACK_LOGLEVEL=warning
FALLBACK_FONT=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
EOF

systemctl daemon-reload
systemctl reset-failed youtube-fallback.service
systemctl start youtube-fallback.service
sleep 2
systemctl status youtube-fallback.service --no-pager
tail -n 120 /root/bwb_services.log
tr '\0' ' ' </proc/$(pgrep -n ffmpeg 2>/dev/null)/cmdline || true
tail -n 80 /run/youtube-fallback.progress 2>/dev/null || true
```
