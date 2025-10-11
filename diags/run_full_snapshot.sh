#!/usr/bin/env bash
# Executa a sequência completa de diagnósticos descrita no runbook.
#
# O objectivo é replicar os comandos habitualmente executados manualmente
# (status-monitor duas vezes, monitorização de heartbeats e relatório
# completo) e garantir que todos os logs são guardados em diags/history.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
HISTORY_DIR="${SCRIPT_DIR}/history"
mkdir -p "${HISTORY_DIR}"

TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"

run_in_dir_and_log() {
  local label="$1"
  local workdir="$2"
  shift 2
  local logfile="${HISTORY_DIR}/${TIMESTAMP}-${label}.log"
  echo "[info] A executar ${label} (log: ${logfile})"
  (
    set -euo pipefail
    cd "${workdir}"
    {
      echo "# timestamp_utc: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      echo "# working_dir: ${workdir}"
      printf '# comando:'
      printf ' %q' "$@"
      printf '\n\n'
      "$@"
    } 2>&1
  ) | tee "${logfile}"
  local exit_code=${PIPESTATUS[0]}
  if [[ ${exit_code} -ne 0 ]]; then
    echo "[erro] ${label} terminou com código ${exit_code}. Consulte ${logfile}." >&2
    return ${exit_code}
  fi
  echo "[info] ${label} concluído com sucesso."
}

run_in_dir_and_log "status-monitor-1" "${ROOT_DIR}/scripts" env STATUS_MONITOR_OUTPUT_DIR="${HISTORY_DIR}" ./status-monitor-debug.sh
run_in_dir_and_log "status-monitor-2" "${ROOT_DIR}/scripts" env STATUS_MONITOR_OUTPUT_DIR="${HISTORY_DIR}" ./status-monitor-debug.sh
run_in_dir_and_log "monitor-heartbeat-before" "${SCRIPT_DIR}" ./monitor_heartbeat_window.py
run_in_dir_and_log "diagnostics" "${SCRIPT_DIR}" ./run_diagnostics.py
run_in_dir_and_log "monitor-heartbeat-after" "${SCRIPT_DIR}" ./monitor_heartbeat_window.py

echo "[info] Sequência de diagnósticos concluída. Logs disponíveis em ${HISTORY_DIR}."
