"""Testes do probe de áudio sem executar ffprobe real."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stream_audio import (  # noqa: E402
    AUDIO_MODE_SOURCE,
    AUDIO_PROBE_FAILED_MESSAGE,
    NO_AUDIO_AVAILABLE_MESSAGE,
    apply_audio_mode_to_config,
    build_ffprobe_input_args,
    probe_input_has_audio,
)


@dataclass
class _Config:
    input_args: list[str]
    output_args: list[str]
    camera_probe: object


def test_ffprobe_args_remove_ffmpeg_flags_and_lavfi() -> None:
    path = "/tmp/demo-praia-surfistas.mp4"
    assert build_ffprobe_input_args(
        ["-stream_loop", "-1", "-re", "-i", path, "-f", "lavfi", "-i", "anullsrc"]
    ) == ["-i", path]


def test_probe_detects_aac_audio() -> None:
    result = probe_input_has_audio(
        "ffprobe",
        ["-i", "demo.mp4"],
        run=lambda *_a, **_kw: SimpleNamespace(
            returncode=0,
            stdout='{"streams":[{"codec_type":"audio","codec_name":"aac"}]}',
            stderr="",
        ),
    )
    assert result.ok and result.has_audio and result.error_kind is None


def test_probe_no_audio_and_apply_raises(monkeypatch) -> None:
    result = probe_input_has_audio(
        "ffprobe",
        ["-i", "demo.mp4"],
        run=lambda *_a, **_kw: SimpleNamespace(
            returncode=0, stdout='{"streams":[]}', stderr=""
        ),
    )
    assert result.ok and not result.has_audio and result.error_kind == "no_audio"
    config = _Config(
        ["-i", "demo.mp4"], [], SimpleNamespace(ffprobe="ffprobe", timeout=2.0)
    )
    monkeypatch.setattr("stream_audio.probe_input_has_audio", lambda *_a, **_kw: result)
    with pytest.raises(ValueError, match=NO_AUDIO_AVAILABLE_MESSAGE):
        apply_audio_mode_to_config(config, AUDIO_MODE_SOURCE)


@pytest.mark.parametrize(
    "run",
    [
        lambda *_a, **_kw: SimpleNamespace(
            returncode=1, stdout="", stderr="connection failed"
        ),
        lambda *_a, **_kw: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("ffprobe", 1)
        ),
    ],
)
def test_probe_failure_is_not_no_audio(monkeypatch, run) -> None:
    result = probe_input_has_audio("ffprobe", ["-i", "rtsp://cam/stream"], run=run)
    assert not result.ok and result.error_kind != "no_audio"
    config = _Config(
        ["-i", "rtsp://cam/stream"], [], SimpleNamespace(ffprobe="ffprobe", timeout=2.0)
    )
    monkeypatch.setattr("stream_audio.probe_input_has_audio", lambda *_a, **_kw: result)
    with pytest.raises(ValueError, match=AUDIO_PROBE_FAILED_MESSAGE):
        apply_audio_mode_to_config(config, AUDIO_MODE_SOURCE)


def test_probe_error_masks_rtsp_password() -> None:
    result = probe_input_has_audio(
        "ffprobe",
        ["-i", "rtsp://user:segredo@camera/stream"],
        run=lambda *_a, **_kw: SimpleNamespace(
            returncode=1, stdout="", stderr="failed rtsp://user:segredo@camera/stream"
        ),
    )
    assert result.sanitized_detail is not None
    assert "segredo" not in result.sanitized_detail
