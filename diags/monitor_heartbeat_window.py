#!/usr/bin/env python3
"""Monitoriza heartbeats enviados pelo primário durante uma janela temporária.

Executa um "snapshot" do monitor de status (porta 8080 por defeito) e
acompanha os próximos N segundos. No fim apresenta um relatório simples sobre:

- Quantos heartbeats chegaram e a sua cadência média.
- Qual foi o último heartbeat e há quanto tempo ocorreu.
- Se o fallback (URL secundária) foi marcado como activo pelo monitor.
- Qual o estado real do serviço ``youtube-fallback`` no systemd.
- Se o comportamento está alinhado com a presença/ausência de heartbeats.

O objectivo é dar uma visão rápida, em linha de comandos, sem necessidade de
abrir ``tcpdump`` ou analisar manualmente ``.pcap``.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/status"
DEFAULT_SERVICE = "youtube-fallback.service"
DEFAULT_DURATION = 60
DEFAULT_TIMEOUT = 5
DEFAULT_MISSED_THRESHOLD = 40


@dataclass
class HeartbeatEntry:
    timestamp: dt.datetime
    machine_id: str
    raw: Dict[str, Any]

    @property
    def status(self) -> Dict[str, Any]:
        return self.raw.get("payload", {}).get("status", {})


def parse_iso8601(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    # ``datetime.fromisoformat`` aceita ``±HH:MM`` mas não ``Z`` puro.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def fetch_snapshot(endpoint: str, timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Resposta inválida do monitor: {exc}") from exc


def extract_entries(
    snapshot: Dict[str, Any], start: dt.datetime, end: dt.datetime
) -> List[HeartbeatEntry]:
    entries: List[HeartbeatEntry] = []
    for item in snapshot.get("history", []):
        if not isinstance(item, dict):
            continue
        ts = parse_iso8601(item.get("timestamp"))
        if ts is None:
            continue
        if ts < start or ts > end:
            continue
        machine_id = item.get("machine_id", "")
        if not isinstance(machine_id, str):
            machine_id = str(machine_id)
        entries.append(HeartbeatEntry(timestamp=ts, machine_id=machine_id, raw=item))
    entries.sort(key=lambda entry: entry.timestamp)
    return entries


def summarise_intervals(
    entries: Sequence[HeartbeatEntry],
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(entries) < 2:
        return None, None, None
    deltas = [
        (entries[idx].timestamp - entries[idx - 1].timestamp).total_seconds()
        for idx in range(1, len(entries))
    ]
    if not deltas:
        return None, None, None
    return min(deltas), mean(deltas), max(deltas)


def systemctl_state(service: str) -> Tuple[str, Optional[int]]:
    result = subprocess.run(
        ["/bin/systemctl", "is-active", service],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout.strip() or result.stderr.strip() or "unknown"
    return output, result.returncode if result.returncode != 0 else None


def determine_expectation(
    entries: Sequence[HeartbeatEntry],
    window_end: dt.datetime,
    missed_threshold: int,
) -> Tuple[str, bool]:
    """Return a human readable expectation string and whether fallback should be active."""
    if not entries:
        return "Esperado: fallback ATIVO (sem heartbeats).", True
    last = entries[-1].timestamp
    silence = (window_end - last).total_seconds()
    if silence > missed_threshold:
        return (
            "Esperado: fallback ATIVO (último heartbeat há %.1fs, acima do limiar de %ss)."
            % (silence, missed_threshold),
            True,
        )
    return (
        "Esperado: fallback DESATIVADO (último heartbeat há %.1fs, dentro do limiar de %ss)."
        % (silence, missed_threshold),
        False,
    )


def format_secondary_state(monitor_flag: bool, systemctl_output: str) -> str:
    monitor_label = "ATIVO" if monitor_flag else "INATIVO"
    service_label = "ATIVO" if systemctl_output == "active" else "INATIVO"
    return (
        "Monitor reporta fallback: %s | systemd: %s (%s)."
        % (monitor_label, service_label, systemctl_output)
    )


def is_service_active(systemctl_output: str, systemctl_rc: Optional[int]) -> bool:
    """Interpret the systemd status string/return code as a boolean."""
    if systemctl_rc is not None:
        return False
    normalized = systemctl_output.strip().lower()
    return normalized in {"active", "activating", "reloading"}


def final_verdict(
    monitor_flag: bool,
    service_active: bool,
    expect_active: bool,
) -> str:
    if expect_active:
        if monitor_flag and service_active:
            return "✅ URL secundária a emitir (comportamento alinhado com o esperado)."
        if monitor_flag and not service_active:
            return "⚠️ Monitor activou fallback, mas o serviço systemd está parado."
        if (not monitor_flag) and service_active:
            return "⚠️ Serviço systemd activo, mas monitor ainda aponta para o primário."
        return "⚠️ Heartbeats ausentes sugerem fallback activo, mas nem monitor nem serviço estão a emitir."
    if (not monitor_flag) and (not service_active):
        return "✅ URL secundária parada conforme esperado."
    if (not monitor_flag) and service_active:
        return "⚠️ Serviço systemd activo apesar de o monitor indicar fallback desligado."
    if monitor_flag and (not service_active):
        return "⚠️ Monitor sinaliza fallback activo, mas o serviço systemd está parado."
    return "⚠️ Heartbeats presentes sugerem fallback desligado, mas tudo indica que continua activo."


def pretty_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analisa heartbeats recebidos pelo monitor da URL secundária."
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Endpoint HTTP a consultar (default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--service",
        default=DEFAULT_SERVICE,
        help=f"Nome do serviço systemd da URL secundária (default: {DEFAULT_SERVICE})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help="Janela de observação em segundos (default: 60).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Timeout em segundos para as chamadas HTTP (default: 5).",
    )
    parser.add_argument(
        "--missed-threshold",
        type=int,
        default=DEFAULT_MISSED_THRESHOLD,
        help="Limiar (s) usado pelo monitor para considerar heartbeats em falta (default: 40).",
    )
    args = parser.parse_args(argv)

    duration = max(1, args.duration)
    missed_threshold = max(1, args.missed_threshold)

    print("== Monitorização dos próximos %s ==" % pretty_duration(duration))
    print(f"Endpoint: {args.endpoint}")
    print(f"Serviço systemd: {args.service}")

    start_time = dt.datetime.now(dt.timezone.utc)
    try:
        fetch_snapshot(args.endpoint, args.timeout)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"Erro ao contactar o monitor: {exc}", file=sys.stderr)
        return 2

    print("Ligação ao monitor bem sucedida. A guardar amostras...")
    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep_chunk = 5 if remaining > 5 else max(1, int(remaining))
        time.sleep(sleep_chunk)
    end_time = dt.datetime.now(dt.timezone.utc)

    try:
        final_snapshot = fetch_snapshot(args.endpoint, args.timeout)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"Erro ao obter snapshot final: {exc}", file=sys.stderr)
        return 3

    entries = extract_entries(final_snapshot, start_time, end_time)
    total = len(entries)
    machines = sorted({entry.machine_id for entry in entries})
    last_ts = entries[-1].timestamp if entries else None
    intervals = summarise_intervals(entries)
    fallback_flag = bool(final_snapshot.get("fallback_active"))
    systemctl_output, systemctl_rc = systemctl_state(args.service)
    service_active = is_service_active(systemctl_output, systemctl_rc)

    print()
    print("== Resultados ==")
    print(
        "Janela analisada: %s -> %s" % (start_time.isoformat(), end_time.isoformat())
    )
    print(f"Heartbeats recebidos: {total}")
    if machines:
        print("Máquinas de origem: %s" % ", ".join(machines))
    if total and last_ts:
        print(
            "Último heartbeat: %s (há %.1fs)"
            % (last_ts.isoformat(), (end_time - last_ts).total_seconds())
        )
    if intervals[0] is not None:
        print(
            "Intervalos entre heartbeats: mínimo %.1fs | médio %.1fs | máximo %.1fs"
            % intervals
        )

    expectation, expect_active = determine_expectation(entries, end_time, missed_threshold)
    print(expectation)

    print(format_secondary_state(fallback_flag, systemctl_output))
    if systemctl_rc is not None:
        print(
            "Aviso: 'systemctl is-active' devolveu código %s; saída completa acima."
            % systemctl_rc
        )

    verdict = final_verdict(fallback_flag, service_active, expect_active)
    print(verdict)

    if total:
        sample_status = entries[-1].status
        if sample_status:
            print("\nResumo do último payload de status:")
            for key, value in sample_status.items():
                print(f"  - {key}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
