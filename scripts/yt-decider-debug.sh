#!/usr/bin/env bash
# yt-decider-debug.sh
# Recolhe logs [yt_decider] das últimas 48h (UTC) a partir de:
#  - journalctl -u yt-decider-daemon
#  - /root/bwb_services.log
# Guarda em: yt-decider-<UTC timestamp>.log

set -euo pipefail

# --- Config ---
SERVICE="yt-decider-daemon"
TAG="\[yt_decider\]"
LOGFILE="/root/bwb_services.log"
TZ=UTC export TZ

# --- Helpers ---
now_utc_epoch()      { date -u +%s; }
since_utc_epoch()    { date -u -d "48 hours ago" +%s; }
ts_utc()             { date -u +"%Y%m%dT%H%M%SZ"; }
out_file()           { echo "yt-decider-$(ts_utc).log"; }

info()  { printf "[info] %s\n" "$*"; }
warn()  { printf "[warn] %s\n" "$*" >&2; }
sect()  { printf "\n===== %s =====\n" "$*"; }

service_exists() {
  local svc="${1:-${SERVICE}}"
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl list-units --type=service --all 2>/dev/null | grep -Fq "${svc}"
}

OUT="$(out_file)"
SINCE_EPOCH="$(since_utc_epoch)"
NOW_EPOCH="$(now_utc_epoch)"

info "Destino: $OUT"
{
  sect "Contexto do host (UTC)"
  echo "host: $(hostname -f 2>/dev/null || hostname)"
  echo "uname: $(uname -a)"
  echo "agora_utc: $(date -u +"%Y-%m-%d %H:%M:%S Z")"
  echo "janela: últimas 48h (desde $(date -u -d "@$SINCE_EPOCH" +"%Y-%m-%d %H:%M:%S Z") até $(date -u -d "@$NOW_EPOCH" +"%Y-%m-%d %H:%M:%S Z"))"

  # --- journalctl ---
  sect "journalctl -u ${SERVICE} (últimas 48h, UTC) | filtro ${TAG}"
  if command -v journalctl >/dev/null 2>&1 && service_exists "${SERVICE}"; then
    journalctl -u "${SERVICE}" --since "48 hours ago" --utc --no-pager 2>&1 | grep -E "${TAG}" || echo "(sem linhas a reportar)"
  else
    echo "(serviço ${SERVICE} não encontrado ou journalctl indisponível)"
  fi

  # Estado atual do serviço
  sect "systemctl status ${SERVICE} --no-pager (snapshot)"
  if service_exists "${SERVICE}"; then
    systemctl status "${SERVICE}" --no-pager || true
  else
    echo "(serviço ${SERVICE} não encontrado)"
  fi

  # --- bwb_services.log ---
  sect "${LOGFILE} (últimas 48h) | filtro ${TAG}"
  if [[ -f "${LOGFILE}" ]]; then
    # Tenta filtrar por timestamp (ISO 8601 ou 'YYYY-MM-DD HH:MM:SS').
    # Se não conseguir interpretar a data da linha, cai no fallback de últimas 10000 linhas.
    TMP_MATCHED="$(mktemp)"
    trap 'rm -f "$TMP_MATCHED"' EXIT

    # Filtra primeiro por TAG para reduzir custo
    # Depois tenta extrair timestamp inicial da linha e comparar em epoch.
    # Suporta formatos: "YYYY-MM-DDTHH:MM:SS", "YYYY-MM-DD HH:MM:SS", com/sem milissegundos e timezone.
    awk -v SINCE="$SINCE_EPOCH" -v NOW="$NOW_EPOCH" -v tag="${TAG}" '
      BEGIN {
        # nada
      }
      index($0, tag) {
        line = $0
        # tenta apanhar um timestamp no início da linha
        # 1) ISO com T: 2025-10-09T14:13:22(.123)?(Z|+00:00)?
        if (match(line, /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+\-][0-9]{2}:[0-9]{2})?/)) {
          ts=substr(line, RSTART, RLENGTH)
        }
        # 2) Espaço: 2025-10-09 14:13:22(.123)?
        else if (match(line, /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?/)) {
          ts=substr(line, RSTART, RLENGTH)
        } else {
          ts=""
        }

        if (ts != "") {
          # Passa para shell para converter com date -d (GNU date); grava linha se dentro da janela
          cmd = "date -u -d \"" ts "\" +%s 2>/dev/null"
          cmd | getline epoch
          close(cmd)
          if (epoch != "" && epoch >= SINCE && epoch <= NOW) {
            print line
          }
        }
      }
    ' "${LOGFILE}" > "${TMP_MATCHED}" || true

    if [[ -s "${TMP_MATCHED}" ]]; then
      cat "${TMP_MATCHED}"
    else
      echo "(não consegui interpretar timestamps; fallback: últimas 10000 linhas contendo ${TAG})"
      grep -E "${TAG}" "${LOGFILE}" | tail -n 10000 || echo "(sem linhas a reportar)"
    fi
  else
    echo "(${LOGFILE} não existe)"
  fi

} | tee "${OUT}" >/dev/null

info "Concluído. Log gerado: ${OUT}"
