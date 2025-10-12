#!/usr/bin/env bash
# youtube_fallback.sh — robusto e tolerante a vars vazias; alterna cenas automaticamente.
# Saída controlada, logs úteis, parsing seguro de SCENES_TXT.

set -Eeuo pipefail

log() { printf '[youtube-fallback] %s\n' "$*" >&2; }

# 1) Variáveis obrigatórias/optativas
: "${YT_URL:?Defina YT_URL em /etc/youtube-fallback.env}"
DURATION_PER_SCENE="${DURATION_PER_SCENE:-30}"
PROGRESS_FILE="${PROGRESS_FILE:-/run/youtube-fallback.progress}"

# 2) Construção da lista de cenas
#   - Se SCENES_TXT estiver definida, cada linha (não vazia e sem #) é uma cena.
#   - Caso contrário, usa o conjunto por omissão.
declare -a SCENES
if [[ "${SCENES_TXT-}" != "" ]]; then
  # Normaliza finais de linha e remove vazias/comentários
  mapfile -t SCENES < <(printf '%s\n' "$SCENES_TXT" | sed $'s/\r$//;/^\\s*#/d;/^\\s*$/d')
else
  SCENES=(
    "smptehdbars=s=1280x720:rate=30"
    "testsrc2=size=1280x720:rate=30"
    "color=c=black:size=1280x720:rate=30,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='INTERVALO':x=(w-tw)/2:y=(h/2):fontsize=48:fontcolor=white"
  )
fi

# Sanidade mínima da duração
if ! [[ "$DURATION_PER_SCENE" =~ ^[0-9]+$ ]] || [[ "$DURATION_PER_SCENE" -le 0 ]]; then
  log "DURATION_PER_SCENE inválido: '$DURATION_PER_SCENE' (use inteiro > 0)."
  exit 2
fi

# 3) Cadeias de filtros/codificação padronizadas
VF_CHAIN='fps=30,scale=1280:720:flags=bicubic,format=yuv420p'
AUD_IN=(-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000)
ENC_AV=(-c:v libx264 -preset veryfast -b:v 2500k -maxrate 2500k -bufsize 2M -g 60 -sc_threshold 0 -pix_fmt yuv420p -c:a aac -b:a 128k -ar 48000 -ac 2 -f flv)

# 4) Encerramento limpo
ffmpeg_pid=""
term_handler() {
  log "Sinal recebido, a terminar FFmpeg…"
  [[ -n "${ffmpeg_pid}" ]] && kill -TERM "${ffmpeg_pid}" 2>/dev/null || true
  wait "${ffmpeg_pid:-}" 2>/dev/null || true
  exit 0
}
trap term_handler INT TERM

# 5) Função para detetar se a cena é ficheiro (existente) ou filtro lavfi
is_file_scene() {
  local s="$1"
  # Se começa por '/', './', '../' ou existir no FS → tratamos como ficheiro
  if [[ "$s" == /* || "$s" == ./* || "$s" == ../* || -e "$s" ]]; then
    return 0
  fi
  return 1
}

# 6) Loop infinito: percorre a lista de cenas
log "Iniciar fallback para '$YT_URL' | cenas=${#SCENES[@]} | duração=${DURATION_PER_SCENE}s"
while true; do
  for SCENE in "${SCENES[@]}"; do
    # Protege contra linhas vazias residuais
    [[ -z "$SCENE" ]] && continue

    if is_file_scene "$SCENE"; then
      VID_IN=(-re -stream_loop -1 -i "$SCENE")
      SRC_DESC="file:$SCENE"
    else
      VID_IN=(-re -f lavfi -i "$SCENE")
      SRC_DESC="lavfi:$SCENE"
    fi

    FILTER_COMPLEX=(-filter_complex "[0:v]${VF_CHAIN}[vout]")

    log "▶ cena=${SRC_DESC} (dur=${DURATION_PER_SCENE}s)"
    ffmpeg -progress "${PROGRESS_FILE}" -hide_banner -loglevel warning -nostats \
      "${VID_IN[@]}" "${AUD_IN[@]}" \
      "${FILTER_COMPLEX[@]}" -map "[vout]" -map 1:a:0 \
      "${ENC_AV[@]}" "${YT_URL}" \
      -t "${DURATION_PER_SCENE}" &
    ffmpeg_pid="$!"
    wait "$ffmpeg_pid" || log "FFmpeg terminou com código $?"
    ffmpeg_pid=""
  done

done
