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
MASTER_LOG="${HISTORY_DIR}/${TIMESTAMP}-full-snapshot.log"
touch "${MASTER_LOG}"

echo "# full_snapshot_log: ${MASTER_LOG}" | tee -a "${MASTER_LOG}"
echo "# started_at_utc: $(date -u +"%Y-%m-%dT%H:%M:%SZ")" | tee -a "${MASTER_LOG}"
echo | tee -a "${MASTER_LOG}"

run_in_dir_and_log() {
  local label="$1"
  local workdir="$2"
  shift 2
  local logfile="${MASTER_LOG}"
  echo "[info] A executar ${label} (log: ${logfile})"
  (
    set -euo pipefail
    cd "${workdir}"
    {
      echo "===== ${label} ====="
      echo "# timestamp_utc: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      echo "# working_dir: ${workdir}"
      printf '# comando:'
      printf ' %q' "$@"
      printf '\n\n'
      "$@"
      echo
    } 2>&1
  ) | tee -a "${logfile}"
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

echo "[info] Sequência de diagnósticos concluída. Log consolidado: ${MASTER_LOG}."
