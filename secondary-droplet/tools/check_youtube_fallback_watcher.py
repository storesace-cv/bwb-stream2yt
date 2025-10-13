#!/usr/bin/env python3
"""Audit logs of youtube-fallback watcher for cadence and mode propagation."""

from __future__ import annotations

import argparse
import re
import datetime as dt
import statistics
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

TICK_PATTERN = re.compile(r"tick ok=")
TIMESTAMP_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d{3})?)")


def parse_timestamp(line: str) -> Optional[dt.datetime]:
    match = TIMESTAMP_RE.match(line)
    if not match:
        return None
    raw = match.group("ts")
    for fmt in ("%Y-%m-%d %H:%M:%S,%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        return None


def iter_ticks(lines: Iterable[str]) -> Sequence[Tuple[dt.datetime, str]]:
    entries: List[Tuple[dt.datetime, str]] = []
    for line in lines:
        if not TICK_PATTERN.search(line):
            continue
        ts = parse_timestamp(line)
        if ts is None:
            continue
        entries.append((ts, line.rstrip()))
    return entries


def summarize_deltas(timestamps: Sequence[dt.datetime]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if len(timestamps) < 2:
        return None, None, None
    deltas = [
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:])
    ]
    return (
        min(deltas),
        statistics.mean(deltas),
        max(deltas),
    )


def format_seconds(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}s"


def inspect_mode_file(path: Path) -> str:
    if not path.exists():
        return f"modo atual: ficheiro ausente ({path})"
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return f"modo atual: erro ao ler {path}: {exc}"
    try:
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError as exc:
        return f"modo atual: erro ao obter mtime de {path}: {exc}"
    return f"modo atual: {content or '(vazio)'} | mtime={mtime.isoformat()}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log_file",
        type=Path,
        help="Ficheiro de log extraído (ex.: journalctl -u youtube-fallback-watcher --since '-5m' --output cat)",
    )
    parser.add_argument(
        "--mode-file",
        type=Path,
        default=Path("/run/youtube-fallback.mode"),
        help="Caminho do ficheiro de modo (default: /run/youtube-fallback.mode)",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=5,
        help="Número de deltas recentes a apresentar (default: 5)",
    )
    args = parser.parse_args(argv)

    try:
        lines = args.log_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        parser.error(f"Não foi possível ler {args.log_file}: {exc}")

    ticks = iter_ticks(lines)
    timestamps = [ts for ts, _ in ticks]
    min_delta, avg_delta, max_delta = summarize_deltas(timestamps)

    print(f"Total de iterações analisadas: {len(ticks)}")
    print(f"Delta mínimo: {format_seconds(min_delta)}")
    print(f"Delta médio: {format_seconds(avg_delta)}")
    print(f"Delta máximo: {format_seconds(max_delta)}")

    if args.show > 0 and len(ticks) >= 2:
        print("\nÚltimos deltas:")
        for (prev_ts, _), (curr_ts, line) in zip(ticks[-(args.show + 1):-1], ticks[-args.show:]):
            delta = (curr_ts - prev_ts).total_seconds()
            print(f"  {curr_ts.isoformat()} Δ={delta:.3f}s :: {line}")

    print("\n" + inspect_mode_file(args.mode_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
