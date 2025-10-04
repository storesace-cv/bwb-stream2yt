#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/root/bwb_services.log"
exec >>"$LOG_FILE" 2>&1

timestamp() {
  date -u '+%Y-%m-%d %H:%M:%S'
}

log_line() {
  printf '%s [youtube_fallback] %s\n' "$(timestamp)" "$*"
}

trap 'status=$?; log_line "Serviço terminou (exit ${status})"' EXIT

log_line "Serviço iniciado (PID $$)"

ENV_FILE="/etc/youtube-fallback.env"
[ -r "$ENV_FILE" ] && . "$ENV_FILE"

# Expand ${YT_KEY} if it leaked into URL
: "${YT_KEY:=}"
if [ -z "${YT_KEY:-}" ]; then
  echo "[youtube_fallback] ERRO: YT_KEY vazio (env: $ENV_FILE)."; exit 1
fi

: "${YT_URL_BACKUP:=rtmps://b.rtmps.youtube.com/live2/${YT_KEY}?backup=1}"

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
: "${FALLBACK_LOGLEVEL:=warning}"
: "${FALLBACK_FONT:=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf}"
: "${FALLBACK_SCROLL_TEXT:=BEACHCAM | CABO LEDO | ANGOLA}"
: "${FALLBACK_STATIC_TEXT:=VOLTAREMOS DENTRO DE MOMENTOS}"

echo "[youtube_fallback] Envio contínuo → ${YT_URL_BACKUP}"
echo "[youtube_fallback] ${FALLBACK_WIDTH}x${FALLBACK_HEIGHT}@${FALLBACK_FPS} | V=${FALLBACK_VBITRATE}/${FALLBACK_MAXRATE}/${FALLBACK_BUFSIZE} | A=${FALLBACK_ABITRATE}@${FALLBACK_AR} | Delay=${FALLBACK_DELAY_SEC}s | GOP=${FALLBACK_GOP} | LogLevel=${FALLBACK_LOGLEVEL}"

handle_signal() {
  local sig="$1"
  log_line "Recebido SIG${sig}, encerrando"
  trap - "$sig"
  kill -s "$sig" "$$"
}

trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal QUIT' QUIT
trap 'handle_signal PIPE' PIPE
trap 'handle_signal TERM' TERM

log_line "Iniciando ffmpeg (loglevel=${FALLBACK_LOGLEVEL})"

if ffmpeg -progress /run/youtube-fallback.progress -hide_banner -loglevel "${FALLBACK_LOGLEVEL}" -nostats \
  -re -stream_loop -1 -framerate "${FALLBACK_FPS}" -i "${FALLBACK_IMG}" \
  -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${FALLBACK_AR}" \
  -filter_complex "[0:v]scale=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:force_original_aspect_ratio=decrease,pad=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p,setpts=PTS+${FALLBACK_DELAY_SEC}/TB,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_SCROLL_TEXT}':fontsize=36:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=w-mod(t*30*8\,w+text_w):y=H-60,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_STATIC_TEXT}':fontsize=28:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=(w-text_w)/2:y=60[vb];[1:a]asetpts=PTS+${FALLBACK_DELAY_SEC}/TB[ab]" \
  -map "[vb]" -map "[ab]" \
  -c:v libx264 -preset "${FALLBACK_PRESET}" -pix_fmt yuv420p -profile:v high -level 4.1 \
  -b:v "${FALLBACK_VBITRATE}" -maxrate "${FALLBACK_MAXRATE}" -bufsize "${FALLBACK_BUFSIZE}" \
  -g "${FALLBACK_GOP}" -keyint_min "${FALLBACK_KEYINT_MIN}" -sc_threshold 0 \
  -c:a aac -b:a "${FALLBACK_ABITRATE}" -ar "${FALLBACK_AR}" -ac 2 \
  -f flv "${YT_URL_BACKUP}"; then
  status=0
else
  status=$?
fi

if [ "$status" -ge 128 ]; then
  signal=$((status - 128))
  if [ "$signal" -gt 0 ] 2>/dev/null; then
    if name=$(kill -l "$signal" 2>/dev/null); then
      log_line "ffmpeg terminou por SIG${name} (exit ${status})"
    else
      log_line "ffmpeg terminou por sinal ${signal} (exit ${status})"
    fi
  else
    log_line "ffmpeg terminou (exit ${status})"
  fi
else
  log_line "ffmpeg terminou (exit ${status})"
fi
exit ${status}
