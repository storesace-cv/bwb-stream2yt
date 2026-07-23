"""Testes da lógica de estado da UI sem depender de PySide6."""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui_app import (  # noqa: E402
    INTERNET_OFFLINE,
    INTERNET_OFFLINE_MESSAGE,
    INTERNET_ONLINE,
    YOUTUBE_CONFIRMED_STATUS,
    check_internet_connectivity,
    derive_camera_status,
    derive_encoder_status,
    derive_rtmps_status,
    extract_recent_event_lines,
    format_metric,
)
from demo_video import DEMO_CAMERA_STATUS  # noqa: E402


def test_derive_camera_status_values():
    assert derive_camera_status(None) == "A verificar"
    assert derive_camera_status({"camera_signal": {"present": True}}) == "OK"
    assert derive_camera_status({"camera_signal": {"present": False}}) == "Sem sinal"
    assert (
        derive_camera_status(
            {"camera_signal": {"present": False, "last_error": "timeout"}}
        )
        == "Erro"
    )
    assert derive_camera_status(None, demo_mode=True) == DEMO_CAMERA_STATUS
    assert derive_camera_status({"demo_mode": True}) == DEMO_CAMERA_STATUS


def test_derive_encoder_and_rtmps_status():
    assert derive_encoder_status(None) == "Parado"
    assert derive_encoder_status({"ffmpeg_running": True}) == "A correr"
    assert derive_encoder_status({"thread_running": True}) == "A iniciar"
    assert (
        derive_encoder_status(
            {
                "ffmpeg_running": False,
                "thread_running": False,
                "ffmpeg_progress": {"rtmps_send_state": "Erro"},
            }
        )
        == "Erro"
    )
    assert (
        derive_rtmps_status({"ffmpeg_progress": {"rtmps_send_state": "A iniciar"}})
        == "A iniciar"
    )
    assert YOUTUBE_CONFIRMED_STATUS == "Não verificado"


def test_format_metric_and_events():
    assert format_metric(None) == "—"
    assert format_metric(12.5) == "12.5"
    lines = extract_recent_event_lines(
        {
            "ffmpeg_progress": {
                "recent_events": [
                    {"component": "primary", "message": "hello"},
                    {"component": "ffmpeg", "message": "warn"},
                ]
            }
        }
    )
    assert lines == ["[primary] hello", "[ffmpeg] warn"]


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_check_internet_connectivity_204(monkeypatch):
    def fake_urlopen(request, timeout=None):
        assert timeout == 3.0
        return _FakeResponse(204)

    monkeypatch.setattr("connectivity.urllib.request.urlopen", fake_urlopen)
    assert check_internet_connectivity() == INTERNET_ONLINE


def test_check_internet_connectivity_http_below_500(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            url="https://www.youtube.com/generate_204",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("connectivity.urllib.request.urlopen", fake_urlopen)
    assert check_internet_connectivity() == INTERNET_ONLINE


def test_check_internet_connectivity_urlerror_timeout(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr("connectivity.urllib.request.urlopen", fake_urlopen)
    assert check_internet_connectivity() == INTERNET_OFFLINE


def test_internet_status_labels_for_ui():
    assert INTERNET_ONLINE == "Ligada"
    assert INTERNET_OFFLINE == "Sem ligação"
    assert INTERNET_OFFLINE_MESSAGE == (
        "Sem ligação à Internet. Não é possível enviar a transmissão para o YouTube."
    )
