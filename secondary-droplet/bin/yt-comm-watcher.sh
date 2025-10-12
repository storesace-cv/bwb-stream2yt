#!/usr/bin/env bash
set -euo pipefail

CHECK_INT=${CHECK_INT:-5}
FAIL_N=${FAIL_N:-3}
OK_N=${OK_N:-3}
HOST=${HOST:-b.rtmp.youtube.com}
PORT=${PORT:-1935}
CLI=${CLI:-/usr/local/bin/yt-fallback}
MODE_CACHE=""

nc_check() {
  if command -v nc >/dev/null 2>&1; then
    nc -z -w2 "${HOST}" "${PORT}" >/dev/null 2>&1
  else
    timeout 3 bash -c "</dev/tcp/${HOST}/${PORT}" >/dev/null 2>&1
  fi
}

set_mode() {
  local desired="$1"
  if [[ -n "${MODE_CACHE}" && "${MODE_CACHE}" == "${desired}" ]]; then
    return 0
  fi
  if "${CLI}" set "${desired}" >/dev/null 2>&1; then
    MODE_CACHE="${desired}"
    return 0
  fi
  return 1
}

current_mode() {
  MODE_CACHE="$("${CLI}" current 2>/dev/null | awk '{print $1}')"
}

current_mode

fail_count=0
ok_count=0

while true; do
  if nc_check; then
    ok_count=$((ok_count + 1))
    fail_count=0
    if (( ok_count >= OK_N )); then
      if set_mode life; then
        ok_count=0
      fi
    fi
  else
    fail_count=$((fail_count + 1))
    ok_count=0
    if (( fail_count >= FAIL_N )); then
      if set_mode bars; then
        fail_count=0
      fi
    fi
  fi
  sleep "${CHECK_INT}"
done
