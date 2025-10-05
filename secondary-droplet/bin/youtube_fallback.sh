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

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULTS_FILE="${SCRIPT_DIR%/bin}/config/youtube-fallback.defaults"

if [ -r "$DEFAULTS_FILE" ]; then
  # shellcheck source=../config/youtube-fallback.defaults
  . "$DEFAULTS_FILE"
else
  FALLBACK_WIDTH=1280
  FALLBACK_HEIGHT=720
  FALLBACK_FPS=30
  FALLBACK_LIFE_ARGS=""
  FALLBACK_VBITRATE="1500k"
  FALLBACK_MAXRATE="1800k"
  FALLBACK_BUFSIZE="3000k"
  FALLBACK_ABITRATE="128k"
  FALLBACK_AR=48000
  FALLBACK_PRESET="veryfast"
  FALLBACK_GOP=60
  FALLBACK_KEYINT_MIN=60
  FALLBACK_DELAY_SEC=3.0
  FALLBACK_LOGLEVEL="warning"
  FALLBACK_FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
  FALLBACK_SCROLL_TEXT="BEACHCAM | CABO LEDO | ANGOLA"
  FALLBACK_STATIC_TEXT="VOLTAREMOS DENTRO DE MOMENTOS"
fi

ENV_FILE="/etc/youtube-fallback.env"
[ -r "$ENV_FILE" ] && . "$ENV_FILE"

# Expand ${YT_KEY} if it leaked into URL
: "${YT_KEY:=}"
if [ -z "${YT_KEY:-}" ]; then
  echo "[youtube_fallback] ERRO: YT_KEY vazio (env: $ENV_FILE)."; exit 1
fi

sanitize_stream_key() {
  local key="$1"
  # Remove carriage returns / newlines that may have leaked from env files
  key="${key//$'\r'/}"
  key="${key//$'\n'/}"
  key="${key//$'\t'/}"

  # Remove duplicated backup query fragments that may appear anywhere
  key="${key//\?backup=1\//\/}"
  key="${key//backup=1\//\/}"
  key="${key//\?backup=1/}"

  # Drop prefixes that accidentally included the RTMP URL
  key="${key##*live2/}"

  # Remove any lingering query string and leading slashes
  key="${key%%\?*}"
  key="${key##*/}"

  printf '%s' "$key"
}

normalize_backup_url() {
  local url="$1"
  local key="$2"
  local default_base="rtmps://b.rtmps.youtube.com/live2"

  if [ -z "$url" ]; then
    printf '%s?backup=1/%s' "$default_base" "$key"
    return
  fi

  # Trim newlines that may exist in env vars
  url="${url//$'\r'/}"
  url="${url//$'\n'/}"
  url="${url//$'\t'/}"

  # Drop anything after the first '?'
  local base="${url%%\?*}"

  # Remove the key or trailing slashes accidentally appended to the base
  base="${base%/${key}}"
  base="${base%/}"

  if [ -z "$base" ] || [[ "$base" != *"://"* ]]; then
    base="$default_base"
  fi

  printf '%s?backup=1/%s' "$base" "$key"
}

YT_KEY="$(sanitize_stream_key "$YT_KEY")"

if [ -z "$YT_KEY" ]; then
  echo "[youtube_fallback] ERRO: YT_KEY inválido após sanitização (env: $ENV_FILE)."; exit 1
fi

YT_URL_BACKUP="$(normalize_backup_url "${YT_URL_BACKUP-}" "$YT_KEY")"

echo "[youtube_fallback] Envio contínuo → ${YT_URL_BACKUP}"
echo "[youtube_fallback] ${FALLBACK_WIDTH}x${FALLBACK_HEIGHT}@${FALLBACK_FPS} | V=${FALLBACK_VBITRATE}/${FALLBACK_MAXRATE}/${FALLBACK_BUFSIZE} | A=${FALLBACK_ABITRATE}@${FALLBACK_AR} | Delay=${FALLBACK_DELAY_SEC}s | GOP=${FALLBACK_GOP} | LogLevel=${FALLBACK_LOGLEVEL}"

handle_signal() {
  local sig="$1"
  log_line "Recebido SIG${sig}, encerrando"

  if [ -n "${FFMPEG_PID:-}" ] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
    kill -s "$sig" "$FFMPEG_PID" 2>/dev/null || true
  fi

  trap - "$sig"
  kill -s "$sig" "$$"
}

trap 'handle_signal HUP' HUP
trap 'handle_signal INT' INT
trap 'handle_signal QUIT' QUIT
trap 'handle_signal PIPE' PIPE
trap 'handle_signal TERM' TERM

PROGRESS_FILE="/run/youtube-fallback.progress"
PROGRESS_LOG_INTERVAL=${PROGRESS_LOG_INTERVAL:-30}

log_line "Iniciando ffmpeg (loglevel=${FALLBACK_LOGLEVEL})"

rm -f "$PROGRESS_FILE"

FFMPEG_PID=""

progress_value() {
  local key="$1" file="$2"

  [ -f "$file" ] || return

  awk -F'=' -v key="$key" '($1 == key) {value=$2} END {if (value != "") print value}' "$file" 2>/dev/null
}

log_progress_snapshot() {
  local file="$1"
  [ -s "$file" ] || return

  local frame fps bitrate drop_frames out_time total_size out_time_ms
  frame=$(progress_value frame "$file")
  fps=$(progress_value fps "$file")
  bitrate=$(progress_value bitrate "$file")
  drop_frames=$(progress_value drop_frames "$file")
  total_size=$(progress_value total_size "$file")
  out_time=$(progress_value out_time "$file")
  out_time_ms=$(progress_value out_time_ms "$file")

  if [ -z "$out_time" ] && [ -n "$out_time_ms" ]; then
    local seconds=$((out_time_ms / 1000000))
    local hours=$((seconds / 3600))
    local minutes=$(((seconds % 3600) / 60))
    local secs=$((seconds % 60))
    out_time=$(printf '%02d:%02d:%02d' "$hours" "$minutes" "$secs")
  fi

  local human_size=""
  if [ -n "$total_size" ]; then
    human_size=$(numfmt --to=iec --suffix=B --padding=0 "$total_size" 2>/dev/null || printf '%sB' "$total_size")
  fi

  log_line "Progresso ffmpeg: frame=${frame:-?} fps=${fps:-?} bitrate=${bitrate:-?} drop=${drop_frames:-0} tamanho=${human_size:-?} tempo=${out_time:-?}"
}

progress_watcher() {
  local file="$1" interval="$2" pid="$3"
  local last_log=0

  if ! [[ "$interval" =~ ^[0-9]+$ ]] || (( interval <= 0 )); then
    interval=30
  fi

  while kill -0 "$pid" 2>/dev/null; do
    local now
    now=$(date +%s)
    if (( now - last_log >= interval )); then
      log_progress_snapshot "$file"
      last_log=$now
    fi
    sleep 1
  done

  # Emit a final snapshot if we have data but didn't log recently
  if [ -s "$file" ]; then
    log_progress_snapshot "$file"
  fi
}

set +e
ffmpeg -progress "$PROGRESS_FILE" -hide_banner -loglevel "${FALLBACK_LOGLEVEL}" -nostats \
  -re -f lavfi -i "life=s=${FALLBACK_WIDTH}x${FALLBACK_HEIGHT}:rate=${FALLBACK_FPS}${FALLBACK_LIFE_ARGS:+:${FALLBACK_LIFE_ARGS}}" \
  -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=${FALLBACK_AR}" \
  -filter_complex "[0:v]scale=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:force_original_aspect_ratio=decrease,pad=${FALLBACK_WIDTH}:${FALLBACK_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,format=yuv420p,setpts=PTS+${FALLBACK_DELAY_SEC}/TB,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_SCROLL_TEXT}':fontsize=36:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=w-mod(t*30*8\,w+text_w):y=H-60,drawtext=fontfile=${FALLBACK_FONT}:text='${FALLBACK_STATIC_TEXT}':fontsize=28:fontcolor=white:shadowcolor=black@0.85:shadowx=2:shadowy=2:x=(w-text_w)/2:y=60[vb];[1:a]asetpts=PTS+${FALLBACK_DELAY_SEC}/TB[ab]" \
  -map "[vb]" -map "[ab]" \
  -c:v libx264 -preset "${FALLBACK_PRESET}" -pix_fmt yuv420p -profile:v high -level 4.1 \
  -b:v "${FALLBACK_VBITRATE}" -maxrate "${FALLBACK_MAXRATE}" -bufsize "${FALLBACK_BUFSIZE}" \
  -g "${FALLBACK_GOP}" -keyint_min "${FALLBACK_KEYINT_MIN}" -sc_threshold 0 \
  -c:a aac -b:a "${FALLBACK_ABITRATE}" -ar "${FALLBACK_AR}" -ac 2 \
  -f flv "${YT_URL_BACKUP}" &
FFMPEG_PID=$!
set -e

progress_watcher "$PROGRESS_FILE" "$PROGRESS_LOG_INTERVAL" "$FFMPEG_PID" &
WATCHER_PID=$!

set +e
wait "$FFMPEG_PID"
status=$?
set -e

if [ -n "${WATCHER_PID:-}" ]; then
  set +e
  wait "$WATCHER_PID"
  set -e
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
