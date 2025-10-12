#!/usr/bin/env bash
set -euo pipefail

: "${YT_URL:?Defina YT_URL em /etc/youtube-fallback.env}"

DURATION_PER_SCENE="${DURATION_PER_SCENE:-30}"
SCENES_DEFAULT=(
  "smptehdbars=s=1280x720:rate=30"
  "testsrc2=size=1280x720:rate=30"
  "color=c=black:size=1280x720:rate=30,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='INTERVALO':x=(w-tw)/2:y=(h/2):fontsize=48:fontcolor=white"
)
VIDEO_SRC="${VIDEO_SRC:-${SCENES_DEFAULT[0]}}"

if [[ -n "${SCENES_TXT:-}" ]]; then
  mapfile -t SCENES < <(printf '%s\n' "${SCENES_TXT}")
else
  SCENES=("${VIDEO_SRC}" "${SCENES_DEFAULT[@]:1}")
fi

# Remove entradas vazias que possam ter sido fornecidas pelo utilizador.
FILTERED_SCENES=()
for scene in "${SCENES[@]}"; do
  if [[ -n "${scene}" ]]; then
    FILTERED_SCENES+=("${scene}")
  fi
fi
SCENES=("${FILTERED_SCENES[@]}")

if [[ ${#SCENES[@]} -eq 0 ]]; then
  echo "[youtube_fallback] ERRO: Nenhuma cena definida." >&2
  exit 1
fi

VF_CHAIN='fps=30,scale=1280:720:flags=bicubic,format=yuv420p'
AUD_IN=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000)
ENC_AV=(
  -c:v libx264
  -preset veryfast
  -b:v 2500k
  -maxrate 2500k
  -bufsize 2M
  -g 60
  -sc_threshold 0
  -c:a aac
  -b:a 128k
  -ar 48000
  -ac 2
  -f flv
)
PROGRESS_FILE="${PROGRESS_FILE:-/run/youtube-fallback.progress}"

mkdir -p "$(dirname "${PROGRESS_FILE}")"

ffmpeg_pid=""
term_handler() {
  if [[ -n "${ffmpeg_pid}" ]]; then
    kill -TERM "${ffmpeg_pid}" 2>/dev/null || true
    wait "${ffmpeg_pid}" 2>/dev/null || true
  fi
  exit 0
}
trap term_handler INT TERM

while true; do
  for SCENE in "${SCENES[@]}"; do
    if [[ "${SCENE}" == /* || -e "${SCENE}" ]]; then
      VID_IN=(-re -stream_loop -1 -i "${SCENE}")
    else
      VID_IN=(-re -f lavfi -i "${SCENE}")
    fi

    FILTER_COMPLEX=(-filter_complex "[0:v]${VF_CHAIN}[vout]")

    ffmpeg \
      -progress "${PROGRESS_FILE}" \
      -hide_banner \
      -loglevel warning \
      -nostats \
      "${VID_IN[@]}" \
      "${AUD_IN[@]}" \
      "${FILTER_COMPLEX[@]}" \
      -map "[vout]" \
      -map 1:a:0 \
      -t "${DURATION_PER_SCENE}" \
      "${ENC_AV[@]}" \
      "${YT_URL}" &

    ffmpeg_pid=$!
    wait "${ffmpeg_pid}" || true
    ffmpeg_pid=""
  done

done
