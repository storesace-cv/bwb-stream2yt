"""Verificação de conectividade HTTP (UI e failover), sem depender de Qt."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

INTERNET_CHECK_URL = "https://www.youtube.com/generate_204"
INTERNET_CHECK_TIMEOUT_SECONDS = 3.0
FAILOVER_INTERNET_TIMEOUT_SECONDS = 2.0

INTERNET_ONLINE_LABEL = "Ligada"
INTERNET_OFFLINE_LABEL = "Sem ligação"


@dataclass(frozen=True)
class ConnectivityResult:
    online: bool
    checked_at: float
    error_kind: Optional[str] = None

    def ui_label(self) -> str:
        return INTERNET_ONLINE_LABEL if self.online else INTERNET_OFFLINE_LABEL


def check_internet_connectivity(
    *,
    timeout: float = INTERNET_CHECK_TIMEOUT_SECONDS,
    url: str = INTERNET_CHECK_URL,
    now: Optional[float] = None,
) -> ConnectivityResult:
    """Probe HTTP mínimo. Devolve resultado estruturado."""

    checked_at = time.monotonic() if now is None else float(now)
    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "BWBPrimary/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, "status", None)
            if status_code is None:
                status_code = response.getcode()
            if status_code is not None and int(status_code) >= 500:
                return ConnectivityResult(
                    online=False, checked_at=checked_at, error_kind="http_5xx"
                )
            return ConnectivityResult(
                online=True, checked_at=checked_at, error_kind=None
            )
    except urllib.error.HTTPError as exc:
        if int(exc.code) < 500:
            return ConnectivityResult(
                online=True, checked_at=checked_at, error_kind=None
            )
        return ConnectivityResult(
            online=False, checked_at=checked_at, error_kind="http_5xx"
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        kind = "timeout" if isinstance(exc, TimeoutError) else "network"
        return ConnectivityResult(online=False, checked_at=checked_at, error_kind=kind)
