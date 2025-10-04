#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/youtube-fallback.env"
[ -r "$ENV_FILE" ] && . "$ENV_FILE"
# expand ${YT_KEY} if present in URL template environments
if [ -n "${YT_URL_BACKUP:-}" ] && printf "%s" "$YT_URL_BACKUP" | grep -q "${YT_KEY:-}"; then 
  YT_URL_BACKUP="${YT_URL_BACKUP//${YT_KEY}/$YT_KEY}"
fi

: "${YT_KEY:=YOUR_STREAM_KEY_HERE}"
: "${YT_URL_BACKUP:=rtmps://b.rtmps.youtube.com/live2?backup=1/${YT_KEY}}"

: "${FALLBACK_IMG:=/usr/local/share/youtube-fallback/SignalLost.jpg}"
: "${FALLBACK_WIDTH:=1280}"
: "${FALLBACK_HEIGHT:=720}"
: "${FALLBACK_FPS:=30}"
: "${FALLBACK_VBITRATE:=1500k}"
: "${FALLBACK_MAXRATE:=1800k}"
: "${FALLBACK_BUFSIZE:=3000k}"
: "${FALLBACK_ABITRATE:=128k}"
: "${FALLBACK_AR:=48000}"
: "${FALLBACK_PRESET:=veryfast}"
: "${FALLBACK_GOP:=60}"
: "${FALLBACK_KEYINT_MIN:=60}"
: "${FALLBACK_DELAY_SEC:=3.0}"
: "${FALLBACK_FONT:=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf}"
: "${FALLBACK_SCROLL_TEXT:=BEACHCAM | CABO LEDO | ANGOLA}"
: "${FALLBACK_STATIC_TEXT:=VOLTAREMOS DENTRO DE MOMENTOS}"

if [ -z "${YT_KEY// }" ]; then
  echo "[youtube_fallback] ERRO: YT_KEY vazio (env: $ENV_FILE)." >&2
  exit 1
fi

echo "[youtube_fallback] Envio contínuo → ${YT_URL_BACKUP}"
echo "[youtube_fallback] ${FALLBACK_WIDTH}x${FALLBACK_HEIGHT}@${FALLBACK_FPS} | V=${FALLBACK_VBITRATE}/${FALLBACK_MAXRATE}/${FALLBACK_BUFSIZE} | A=${FALLBACK_ABITRATE}@${FALLBACK_AR} | Delay=${FALLBACK_DELAY_SEC}s | GOP=${FALLBACK_GOP}"

exec ffmpeg -progress /run/youtube-fallback.progress -hide_banner -loglevel warning -nostats \
  -re -stream_loop -1 -framerate "${FALLBACK_FPS}" -i "${FALLBACK_IMG}" \
  -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${FALLBACK_AR}" \
  -filter_complex "[0:v]scale=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:force_original_aspect_ratio=decrease,pad=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p,setpts=PTS+${FALLBACK_DELAY_SEC}/TB,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_SCROLL_TEXT}':fontsize=36:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=w-mod(t*30*8\,w+text_w):y=H-60,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_STATIC_TEXT}':fontsize=28:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=(w-text_w)/2:y=60[vb];[1:a]asetpts=PTS+${FALLBACK_DELAY_SEC}/TB[ab]" \
  -map "[vb]" -map "[ab]" \
  -c:v libx264 -preset "${FALLBACK_PRESET}" -pix_fmt yuv420p -profile:v high -level 4.1 \
  -b:v "${FALLBACK_VBITRATE}" -maxrate "${FALLBACK_MAXRATE}" -bufsize "${FALLBACK_BUFSIZE}" \
  -g "${FALLBACK_GOP}" -keyint_min "${FALLBACK_KEYINT_MIN}" -sc_threshold 0 \
  -c:a aac -b:a "${FALLBACK_ABITRATE}" -ar "${FALLBACK_AR}" -ac 2 \
  -f flv "${YT_URL_BACKUP}"
