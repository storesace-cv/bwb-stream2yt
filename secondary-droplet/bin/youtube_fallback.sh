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

clean_env_value() {
  local value="$1"
  value="$(printf '%s' "$value" | tr -d '\r\n\t')"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

sanitize_stream_key() {
  local key
  key="$(clean_env_value "$1")"
  key="${key// /}"
  key="${key//\?backup=1\/}"
  key="${key//backup=1\/}"
  key="${key//\?backup=1/}"
  key="${key##*live2/}"
  key="${key##*/}"
  key="${key%%\?*}"
  printf '%s' "$key"
}

normalize_backup_url() {
  local url="$1" key="$2" default_base="rtmps://b.rtmps.youtube.com/live2"
  url="$(clean_env_value "$url")"
  key="$(clean_env_value "$key")"

  if [[ -z "$key" ]]; then
    printf '%s' ""
    return 0
  fi

  if [[ -z "$url" ]]; then
    printf '%s?backup=1/%s' "$default_base" "$key"
    return 0
  fi

  url="${url%%\?*}"
  url="${url%/${key}}"
  url="${url%/}"

  if [[ -z "$url" || "$url" != *"://"* ]]; then
    url="$default_base"
  fi

  printf '%s?backup=1/%s' "$url" "$key"
}

resolve_stream_url() {
  local raw_url="$(clean_env_value "${YT_URL:-}")"
  local raw_key="$(clean_env_value "${YT_KEY:-}")"
  local backup_base="${YT_URL_BACKUP:-}"

  if [[ -n "$raw_url" ]]; then
    printf '%s' "$raw_url"
    return 0
  fi

  local sanitized_key
  sanitized_key="$(sanitize_stream_key "$raw_key")"

  if [[ -z "$sanitized_key" ]]; then
    echo "[youtube_fallback] ERRO: defina YT_URL ou YT_KEY no ambiente." >&2
    exit 1
  fi

  local normalized
  normalized="$(normalize_backup_url "$backup_base" "$sanitized_key")"

  if [[ -z "$normalized" ]]; then
    echo "[youtube_fallback] ERRO: não foi possível derivar URL do backup." >&2
    exit 1
  fi

  printf '%s' "$normalized"
}

: "${PROGRESS:=/run/youtube-fallback.progress}"

VIDEO_SRC_DEFAULT="smptehdbars=s=${WIDTH}x${HEIGHT}:rate=${FPS}"
AUDIO_SRC_DEFAULT="anullsrc=channel_layout=stereo:sample_rate=${AR}"

VIDEO_SRC="${VIDEO_SRC:-${VIDEO_SRC_DEFAULT}}"
AUDIO_SRC="${AUDIO_SRC:-${AUDIO_SRC_DEFAULT}}"

TARGET_URL="$(resolve_stream_url)"

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
  -f flv "${TARGET_URL}"
