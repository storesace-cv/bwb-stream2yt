"""Helpers for dynamic bitrate tuning based on network throughput measurements."""

from __future__ import annotations

import time
from typing import Optional

try:  # pragma: no cover - optional dependency on psutil.
    import psutil
except ImportError:  # pragma: no cover - psutil may not be available in all environments.
    psutil = None  # type: ignore[assignment]


def estimate_upload_bitrate(
    interval: float,
    min_kbps: int,
    max_kbps: int,
    *,
    safety_margin: float = 0.75,
) -> Optional[int]:
    """Estimate a safe upload bitrate in kbps.

    The function samples the total number of bytes sent on all interfaces via
    :func:`psutil.net_io_counters` separated by ``interval`` seconds. The
    measured throughput is multiplied by ``safety_margin`` (expected to be in
    the ``0.0``-``1.0`` range) and then clamped between ``min_kbps`` and
    ``max_kbps``.

    Returns ``None`` when psutil is unavailable or a measurement cannot be
    obtained.
    """

    if not psutil or interval <= 0:
        return None

    if min_kbps <= 0 or max_kbps <= 0:
        return None

    if min_kbps > max_kbps:
        min_kbps, max_kbps = max_kbps, min_kbps

    if safety_margin <= 0:
        return min(max(min_kbps, 1), max_kbps)

    safety_margin = min(safety_margin, 1.0)

    try:
        start = psutil.net_io_counters()
    except Exception:
        return None

    if not start:
        return None

    start_bytes = getattr(start, "bytes_sent", None)
    if start_bytes is None:
        return None

    time.sleep(interval)

    try:
        end = psutil.net_io_counters()
    except Exception:
        return None

    if not end:
        return None

    end_bytes = getattr(end, "bytes_sent", None)
    if end_bytes is None or end_bytes < start_bytes:
        return None

    bytes_sent = end_bytes - start_bytes
    if bytes_sent <= 0:
        return None

    bits_per_second = (bytes_sent * 8) / interval
    kbps = bits_per_second / 1000.0
    safe_kbps = int(kbps * safety_margin)
    if safe_kbps <= 0:
        return min(max(min_kbps, 1), max_kbps)

    safe_kbps = max(min_kbps, min(int(safe_kbps), max_kbps))
    return safe_kbps
