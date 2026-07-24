"""Áudio por fonte no failover: nunca bloqueia o arranque."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stream_audio import (  # noqa: E402
    AUDIO_MODE_SILENT,
    AUDIO_MODE_SOURCE,
    AUDIO_PROBE_MAX_TIMEOUT_S,
    AudioProbeResult,
    apply_audio_mode_to_config,
    build_effective_ffmpeg_input_args,
    resolve_audio_for_source,
)


def _load_stream_module():
    path = SRC / "stream_to_youtube.py"
    name = "_stream_failover_audio_resolve_test"
    if name in sys.modules:
        return sys.modules[name]
    if "autotune" not in sys.modules:
        stub = types.ModuleType("autotune")
        stub.estimate_upload_bitrate = lambda *_a, **_k: (_ for _ in ()).throw(  # type: ignore
            NotImplementedError
        )
        stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
        stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
        sys.modules["autotune"] = stub
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


module = _load_stream_module()


def _base_config(**overrides):
    cfg = module.StreamingConfig(
        yt_url="rtmps://a.rtmps.youtube.com/live2/EXEMPLO",
        input_args=["-rtsp_transport", "tcp", "-i", "rtsp://cam/stream"],
        output_args=["-c:v", "libx264", "-c:a", "aac", "-b:a", "64k"],
        resolution="1080p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=5000,
        autotune_interval=8.0,
        autotune_safety_margin=0.5,
        heartbeat=module.HeartbeatConfig(
            enabled=False,
            endpoint=None,
            interval=20.0,
            timeout=5.0,
            machine_id="TEST",
            token=None,
            log_path=Path("/tmp/hb.jsonl"),
            log_retention_seconds=3600,
        ),
        camera_probe=module.CameraProbeConfig(
            ffprobe="ffprobe", interval=5.0, timeout=7.0, required=False
        ),
    )
    if overrides:
        cfg = replace(cfg, **overrides)
    return cfg


def test_resolve_silent_skips_probe(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("probe não deve correr em silent")

    monkeypatch.setattr("stream_audio.probe_input_has_audio", boom)
    resolution = resolve_audio_for_source(_base_config(), AUDIO_MODE_SILENT)
    assert called["n"] == 0
    assert resolution.effective_audio_mode == AUDIO_MODE_SILENT
    assert "anullsrc=" in " ".join(build_effective_ffmpeg_input_args(resolution.config))


def test_resolve_source_with_audio_keeps_original(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    resolution = resolve_audio_for_source(_base_config(), AUDIO_MODE_SOURCE)
    assert resolution.effective_audio_mode == AUDIO_MODE_SOURCE
    assert resolution.audio_detected is True
    assert resolution.config.output_args[:4] == ["-map", "0:v:0", "-map", "0:a:0"]
    assert "anullsrc=" not in " ".join(
        build_effective_ffmpeg_input_args(resolution.config)
    )


def test_resolve_source_without_audio_or_error_falls_back_silent(monkeypatch):
    for probe in (
        AudioProbeResult(ok=True, has_audio=False, error_kind="no_audio"),
        AudioProbeResult(ok=False, has_audio=False, error_kind="timeout"),
        AudioProbeResult(ok=False, has_audio=False, error_kind="connect_failed"),
    ):

        def _probe(*_a, _p=probe, **_k):
            return _p

        monkeypatch.setattr("stream_audio.probe_input_has_audio", _probe)
        resolution = resolve_audio_for_source(_base_config(), AUDIO_MODE_SOURCE)
        assert resolution.effective_audio_mode == AUDIO_MODE_SILENT
        assert resolution.used_silent_fallback is True
        assert "anullsrc=" in " ".join(
            build_effective_ffmpeg_input_args(resolution.config)
        )


def test_resolve_respects_exhausted_deadline(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("sem tempo → sem probe")

    monkeypatch.setattr("stream_audio.probe_input_has_audio", boom)
    resolution = resolve_audio_for_source(
        _base_config(), AUDIO_MODE_SOURCE, deadline_remaining=0.0
    )
    assert called["n"] == 0
    assert resolution.effective_audio_mode == AUDIO_MODE_SILENT
    assert resolution.probe.error_kind == "timeout"
    assert resolution.used_silent_fallback is True


def test_apply_audio_mode_no_longer_raises(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(
            ok=True, has_audio=False, error_kind="no_audio"
        ),
    )
    updated = apply_audio_mode_to_config(_base_config(), AUDIO_MODE_SOURCE)
    assert updated.audio_mode == AUDIO_MODE_SILENT


def test_failover_startup_does_not_probe_camera(monkeypatch, tmp_path):
    demo = tmp_path / "demo.mp4"
    demo.write_bytes(b"fake")
    probed = {"n": 0}

    def counting_probe(*_a, **_k):
        probed["n"] += 1
        return AudioProbeResult(ok=False, has_audio=False, error_kind="connect_failed")

    monkeypatch.setattr("stream_audio.probe_input_has_audio", counting_probe)
    monkeypatch.setattr(module, "demo_video_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module, "resolve_demo_video_path", lambda explicit=None, **_k: str(demo)
    )

    config = _base_config(
        camera_failover_to_demo=True,
        contingency_demo_path=str(demo),
        requested_audio_mode=AUDIO_MODE_SOURCE,
        audio_mode=None,
    )
    worker = module.StreamingWorker(
        config, failover_enabled=True, contingency_demo_path=str(demo)
    )
    assert probed["n"] == 0
    assert worker._camera_config is not None
    assert worker._camera_config.audio_mode is None
    assert worker._contingency_demo_config is not None
    assert worker._contingency_demo_config.demo_mode is True
    assert worker._contingency_demo_config.audio_mode is None
    assert worker._requested_audio_mode == AUDIO_MODE_SOURCE


def test_switch_to_demo_resolves_audio_from_mp4(monkeypatch, tmp_path):
    demo = tmp_path / "demo-praia.mp4"
    demo.write_bytes(b"fake")
    monkeypatch.setattr(module, "demo_video_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module, "resolve_demo_video_path", lambda explicit=None, **_k: str(demo)
    )
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    config = _base_config(
        camera_failover_to_demo=True,
        contingency_demo_path=str(demo),
        requested_audio_mode=AUDIO_MODE_SOURCE,
        audio_mode=None,
    )
    worker = module.StreamingWorker(
        config, failover_enabled=True, contingency_demo_path=str(demo)
    )
    assert worker._contingency_demo_config is not None
    prepared = worker._resolve_active_audio(worker._contingency_demo_config)
    assert prepared.effective_audio_mode == AUDIO_MODE_SOURCE
    assert prepared.audio_detected is True


def test_switch_to_demo_without_audio_uses_silent(monkeypatch, tmp_path):
    demo = tmp_path / "demo.mp4"
    demo.write_bytes(b"fake")
    monkeypatch.setattr(module, "demo_video_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module, "resolve_demo_video_path", lambda explicit=None, **_k: str(demo)
    )
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(
            ok=True, has_audio=False, error_kind="no_audio"
        ),
    )
    worker = module.StreamingWorker(
        _base_config(
            camera_failover_to_demo=True,
            contingency_demo_path=str(demo),
            requested_audio_mode=AUDIO_MODE_SOURCE,
            audio_mode=None,
        ),
        failover_enabled=True,
        contingency_demo_path=str(demo),
    )
    prepared = worker._resolve_active_audio(worker._contingency_demo_config)
    assert prepared.effective_audio_mode == AUDIO_MODE_SILENT
    assert "anullsrc=" in " ".join(build_effective_ffmpeg_input_args(prepared.config))


def test_camera_recovery_audio_paths(monkeypatch, tmp_path):
    demo = tmp_path / "demo.mp4"
    demo.write_bytes(b"fake")
    monkeypatch.setattr(module, "demo_video_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module, "resolve_demo_video_path", lambda explicit=None, **_k: str(demo)
    )
    worker = module.StreamingWorker(
        _base_config(
            camera_failover_to_demo=True,
            contingency_demo_path=str(demo),
            requested_audio_mode=AUDIO_MODE_SOURCE,
            audio_mode=None,
        ),
        failover_enabled=True,
        contingency_demo_path=str(demo),
    )

    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    with_audio = worker._resolve_active_audio(worker._camera_config)
    assert with_audio.effective_audio_mode == AUDIO_MODE_SOURCE

    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(
            ok=True, has_audio=False, error_kind="no_audio"
        ),
    )
    without = worker._resolve_active_audio(worker._camera_config)
    assert without.effective_audio_mode == AUDIO_MODE_SILENT

    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(
            ok=False, has_audio=False, error_kind="timeout"
        ),
    )
    failed = worker._resolve_active_audio(worker._camera_config)
    assert failed.effective_audio_mode == AUDIO_MODE_SILENT


def test_direct_demo_still_gets_aac(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    demo_cfg = _base_config(
        input_args=["-stream_loop", "-1", "-re", "-i", "/tmp/demo-praia-surfistas.mp4"],
        demo_mode=True,
    )
    resolution = resolve_audio_for_source(demo_cfg, AUDIO_MODE_SOURCE)
    assert resolution.effective_audio_mode == AUDIO_MODE_SOURCE
    assert resolution.audio_detected is True


def test_audio_probe_timeout_budget_constant():
    assert AUDIO_PROBE_MAX_TIMEOUT_S == 3.0
    assert AUDIO_PROBE_MAX_TIMEOUT_S <= 32.0


def test_failover_audio_never_writes_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("YT_URL=rtmps://example/live2/x\n", encoding="utf-8")
    before = env_path.read_text(encoding="utf-8")
    monkeypatch.setenv("YT_DAY_START_HOUR", "8")
    demo = tmp_path / "demo.mp4"
    demo.write_bytes(b"x")
    monkeypatch.setattr(module, "demo_video_exists", lambda *_a, **_k: True)
    monkeypatch.setattr(
        module, "resolve_demo_video_path", lambda explicit=None, **_k: str(demo)
    )
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    worker = module.StreamingWorker(
        _base_config(
            camera_failover_to_demo=True,
            contingency_demo_path=str(demo),
            requested_audio_mode=AUDIO_MODE_SOURCE,
            audio_mode=None,
        ),
        failover_enabled=True,
        contingency_demo_path=str(demo),
    )
    worker._resolve_active_audio(worker._contingency_demo_config)
    assert env_path.read_text(encoding="utf-8") == before
    assert os.environ["YT_DAY_START_HOUR"] == "8"
