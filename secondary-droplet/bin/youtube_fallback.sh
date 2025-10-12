#!/usr/bin/env bash
set -euo pipefail

# Variáveis esperadas a partir de /etc/youtube-fallback.env (via symlink).
# Consulte secondary-droplet/config/youtube-fallback.d/ para perfis de exemplo.

: "${WIDTH:=1280}"
: "${HEIGHT:=720}"
: "${FPS:=30}"
: "${VBITRATE:=1200k}"
: "${ABITRATE:=96k}"
: "${AR:=48000}"
: "${PROGRESS:=/run/youtube-fallback.progress}"

VIDEO_SRC_DEFAULT="smptehdbars=s=${WIDTH}x${HEIGHT}:rate=${FPS}"
AUDIO_SRC_DEFAULT="anullsrc=channel_layout=stereo:sample_rate=${AR}"

VIDEO_SRC="${VIDEO_SRC:-${VIDEO_SRC_DEFAULT}}"
AUDIO_SRC="${AUDIO_SRC:-${AUDIO_SRC_DEFAULT}}"

if [[ -z "${YT_URL:-}" ]]; then
  echo "[youtube_fallback] ERRO: variável YT_URL não definida no ambiente." >&2
  exit 1
fi

calc_bufsize() {
  local raw="$1"
  if [[ "$raw" =~ ^([0-9]+)[kK]$ ]]; then
    local value=${BASH_REMATCH[1]}
    printf '%sk' $(( value * 2 ))
    return 0
  fi
  echo "$raw"
}

BUFSIZE="$(calc_bufsize "${VBITRATE}")"

GOP=$(( FPS * 2 ))

exec ffmpeg \
  -progress "${PROGRESS}" \
  -hide_banner \
  -loglevel warning \
  -nostats \
  -re \
  -f lavfi -i "${VIDEO_SRC}" \
  -f lavfi -i "${AUDIO_SRC}" \
  -filter_complex "[0:v]format=yuv420p[vout]" \
  -map "[vout]" -map 1:a \
  -c:v libx264 \
  -preset veryfast \
  -tune zerolatency \
  -profile:v high \
  -pix_fmt yuv420p \
  -g "${GOP}" \
  -sc_threshold 0 \
  -b:v "${VBITRATE}" \
  -maxrate "${VBITRATE}" \
  -bufsize "${BUFSIZE}" \
  -c:a aac \
  -b:a "${ABITRATE}" \
  -ar "${AR}" \
  -ac 2 \
  -f flv "${YT_URL}"
