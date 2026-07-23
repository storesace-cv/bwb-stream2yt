from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import connectivity  # noqa: E402


def test_connectivity_result_is_structured_and_timeout_is_two_seconds() -> None:
    result = connectivity.ConnectivityResult(online=True, checked_at=12.5)
    assert result.online and result.checked_at == 12.5
    assert result.ui_label() == "Ligada"
    assert (
        connectivity.ConnectivityResult(False, 1, "network").ui_label() == "Sem ligação"
    )
    assert connectivity.FAILOVER_INTERNET_TIMEOUT_SECONDS == 2.0


def test_urlopen_success_and_failure(monkeypatch) -> None:
    class Response:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        connectivity.urllib.request, "urlopen", lambda *_a, **_kw: Response()
    )
    assert connectivity.check_internet_connectivity(now=3.0).online

    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(connectivity.urllib.request, "urlopen", fail)
    result = connectivity.check_internet_connectivity(now=4.0)
    assert not result.online and result.error_kind == "network"
