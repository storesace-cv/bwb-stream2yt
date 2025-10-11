#!/usr/bin/env bash
# status-monitor-debug.sh
# Recolhe informação do monitor HTTP que coordena o fallback.
# Gera um relatório com logs recentes, estado do serviço e captura opcional do endpoint /status.

set -euo pipefail

SERVICE="bwb-status-monitor"
LOGFILE="/var/log/bwb_status_monitor.log"
STATE_FILE="/var/lib/bwb-status-monitor/status.json"
ENV_FILE="/etc/bwb-status-monitor.env"
WINDOW="${STATUS_MONITOR_WINDOW:-48 hours}"
ENDPOINT="${STATUS_MONITOR_ENDPOINT:-http://127.0.0.1:8080/status}"
TZ=UTC export TZ

now_utc_epoch()      { date -u +%s; }
since_utc_epoch()    { date -u -d "${WINDOW}" +%s; }
ts_utc()             { date -u +"%Y%m%dT%H%M%SZ"; }
out_file()           { echo "status-monitor-$(ts_utc).log"; }

info()  { printf "[info] %s\n" "$*"; }
warn()  { printf "[warn] %s\n" "$*" >&2; }
sect()  { printf "\n===== %s =====\n" "$*"; }

service_exists() {
  local svc="${1:-${SERVICE}}"
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl list-units --type=service --all 2>/dev/null | grep -Fq "${svc}"
}

sanitize_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "(${ENV_FILE} não existe)"
    return
  fi
  sed -E 's/(BWB_STATUS_TOKEN=).*/\1<redacted>/' "${ENV_FILE}"
}

fetch_endpoint() {
  if ! command -v curl >/dev/null 2>&1; then
    echo "(curl não disponível)"
    return 0
  fi
  local url="${1}"
  curl --max-time 5 --show-error --silent --location --head "${url}" || true
  curl --max-time 5 --show-error --silent --location "${url}" || true
}

OUT="$(out_file)"
SINCE_EPOCH="$(since_utc_epoch)"
NOW_EPOCH="$(now_utc_epoch)"

info "Destino: $OUT"
{
  sect "Contexto do host (UTC)"
  echo "host: $(hostname -f 2>/dev/null || hostname)"
  echo "uname: $(uname -a)"
  echo "janela: ${WINDOW} (desde $(date -u -d "@${SINCE_EPOCH}" +"%Y-%m-%d %H:%M:%S Z") até $(date -u -d "@${NOW_EPOCH}" +"%Y-%m-%d %H:%M:%S Z"))"
  echo "endpoint_alvo: ${ENDPOINT}"

  sect "${ENV_FILE} (com token oculto)"
  sanitize_env_file

  sect "journalctl -u ${SERVICE} (${WINDOW}, UTC)"
  if command -v journalctl >/dev/null 2>&1 && service_exists "${SERVICE}"; then
    journalctl -u "${SERVICE}" --since "${WINDOW} ago" --utc --no-pager || true
  else
    echo "(serviço ${SERVICE} não encontrado ou journalctl indisponível)"
  fi

  sect "systemctl status ${SERVICE} --no-pager"
  if service_exists "${SERVICE}"; then
    systemctl status "${SERVICE}" --no-pager || true
  else
    echo "(serviço ${SERVICE} não encontrado)"
  fi

  sect "${LOGFILE} (${WINDOW})"
  if [[ -f "${LOGFILE}" ]]; then
    TMP_MATCHED="$(mktemp)"
    trap 'rm -f "$TMP_MATCHED"' EXIT

    awk -v SINCE="$SINCE_EPOCH" -v NOW="$NOW_EPOCH" '
      {
        line = $0
        ts = ""
        if (match(line, /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?([Zz]|[+\-][0-9]{2}:[0-9]{2})?/)) {
          ts=substr(line, RSTART, RLENGTH)
        } else if (match(line, /^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?/)) {
          ts=substr(line, RSTART, RLENGTH)
        }
        if (ts != "") {
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
      echo "(não foi possível extrair por timestamp; fallback: tail -n 400)"
      tail -n 400 "${LOGFILE}" || true
    fi
  else
    echo "(${LOGFILE} não existe)"
  fi

  sect "${STATE_FILE}"
  if [[ -f "${STATE_FILE}" ]]; then
    cat "${STATE_FILE}"
  else
    echo "(${STATE_FILE} não existe)"
  fi

  sect "Consulta HTTP ao endpoint de status"
  fetch_endpoint "${ENDPOINT}"

} | tee "${OUT}" >/dev/null

info "Concluído. Log gerado: ${OUT}"
