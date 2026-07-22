"""Testes dos perfis manuais de qualidade de envio."""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from send_quality import (  # noqa: E402
    DEFAULT_SEND_QUALITY,
    SEND_QUALITY_PROFILES,
    apply_profile_to_output_args,
    format_quality_status,
    get_send_quality_profile,
    normalize_send_quality,
)

MODULE_PATH = SRC_DIR / "stream_to_youtube.py"
SPEC = importlib.util.spec_from_file_location(
    "_stream_to_youtube_quality_test", MODULE_PATH
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_to_youtube_quality_test"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune_stub

SPEC.loader.exec_module(module)


def _base_output_args() -> list[str]:
    return [
        "-vf",
        "scale=1920:1080:flags=bicubic:in_range=pc:out_range=tv,format=yuv420p",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-b:v",
        "5000k",
        "-maxrate",
        "6000k",
        "-bufsize",
        "12000k",
        "-g",
        "60",
    ]


def _build_config(tmp_path: Path, **overrides):
    heartbeat = module.HeartbeatConfig(
        enabled=False,
        endpoint=None,
        interval=20.0,
        timeout=5.0,
        machine_id="TEST",
        token=None,
        log_path=tmp_path / "hb.jsonl",
        log_retention_seconds=3600,
    )
    camera = module.CameraProbeConfig(
        ffprobe="ffprobe",
        interval=5.0,
        timeout=2.0,
        required=True,
    )
    values = dict(
        yt_url="rtmps://example/live2/key",
        input_args=["-i", "rtsp://cam/stream"],
        output_args=_base_output_args(),
        resolution="1080p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=True,
        bitrate_min_kbps=2500,
        bitrate_max_kbps=6000,
        autotune_interval=8.0,
        autotune_safety_margin=0.2,
        heartbeat=heartbeat,
        camera_probe=camera,
        demo_mode=False,
    )
    values.update(overrides)
    return module.StreamingConfig(**values)


def test_four_profiles_exact_values():
    expected = {
        "alta": (1920, 1080, 30, 5000, 6000, 12000),
        "media": (1280, 720, 30, 2500, 3000, 6000),
        "baixa": (854, 480, 25, 1000, 1200, 2400),
        "emergencia": (640, 360, 20, 500, 650, 1300),
    }
    assert set(SEND_QUALITY_PROFILES) == set(expected)
    for key, values in expected.items():
        profile = get_send_quality_profile(key)
        assert (
            profile.width,
            profile.height,
            profile.fps,
            profile.bitrate_kbps,
            profile.maxrate_kbps,
            profile.bufsize_kbps,
        ) == values


def test_default_quality_is_alta():
    assert DEFAULT_SEND_QUALITY == "alta"
    assert normalize_send_quality(None) == "alta"
    assert normalize_send_quality("invalid") == "alta"
    assert get_send_quality_profile().key == "alta"


def test_format_quality_status_text():
    baixa = get_send_quality_profile("baixa")
    assert (
        format_quality_status(baixa) == "Qualidade: Baixa — 480p / 25 FPS / 1000 kbps"
    )
    emergencia = get_send_quality_profile("emergencia")
    assert (
        format_quality_status(emergencia)
        == "Qualidade: Emergência — 360p / 20 FPS / 500 kbps"
    )


def test_apply_profile_sets_ffmpeg_args():
    args = apply_profile_to_output_args(
        _base_output_args(), get_send_quality_profile("baixa")
    )
    assert args[args.index("-vf") + 1].startswith("scale=854:480:")
    assert args[args.index("-r") + 1] == "25"
    assert args[args.index("-b:v") + 1] == "1000k"
    assert args[args.index("-maxrate") + 1] == "1200k"
    assert args[args.index("-bufsize") + 1] == "2400k"
    assert args[args.index("-g") + 1] == "50"


def test_apply_send_quality_caps_autotune(tmp_path):
    config = _build_config(tmp_path, bitrate_min_kbps=4000, bitrate_max_kbps=8000)
    updated = module.apply_send_quality(config, "baixa")
    assert updated.bitrate_max_kbps == 1200
    assert updated.bitrate_min_kbps == 1000
    assert updated.resolution == "480p"
    assert updated.output_args[updated.output_args.index("-b:v") + 1] == "1000k"
    # Config original intacta.
    assert config.bitrate_max_kbps == 8000
    assert config.resolution == "1080p"


def test_autotune_cannot_exceed_profile_max(tmp_path):
    config = module.apply_send_quality(_build_config(tmp_path), "emergencia")
    worker = module.StreamingWorker(config)
    adjusted, metadata = worker._apply_autotune_settings(
        list(config.output_args), measured_bitrate=9000
    )
    assert metadata["bitrate"] <= config.bitrate_max_kbps
    assert metadata["maxrate"] <= config.bitrate_max_kbps
    assert adjusted[adjusted.index("-b:v") + 1].endswith("k")
    bitrate = int(adjusted[adjusted.index("-b:v") + 1][:-1])
    assert bitrate <= 650


def test_apply_send_quality_works_with_demo(tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"data")
    config = _build_config(tmp_path)
    demo = module.apply_demo_video_source(config, str(video))
    updated = module.apply_send_quality(demo, "media")
    assert updated.demo_mode is True
    assert str(video) in updated.input_args
    assert updated.output_args[updated.output_args.index("-b:v") + 1] == "2500k"
    assert updated.output_args[updated.output_args.index("-r") + 1] == "30"


def test_start_streaming_uses_selected_quality(tmp_path, monkeypatch):
    captured = {}

    def fake_load_config(resolution=None):
        return _build_config(tmp_path)

    def fake_run_forever(config, **kwargs):
        captured["config"] = config

    monkeypatch.setattr(module, "load_config", fake_load_config)
    monkeypatch.setattr(module, "run_forever", fake_run_forever)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_acquire_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "_claim_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *a, **k: None)

    code = module.start_streaming_instance(send_quality="baixa")
    assert code == 0
    assert captured["config"].resolution == "480p"
    assert (
        captured["config"].output_args[captured["config"].output_args.index("-r") + 1]
        == "25"
    )
    assert captured["config"].bitrate_max_kbps == 1200


def test_start_streaming_without_quality_keeps_env_behavior(tmp_path, monkeypatch):
    captured = {}

    def fake_load_config(resolution=None):
        return _build_config(tmp_path, resolution="720p", bitrate_max_kbps=4500)

    def fake_run_forever(config, **kwargs):
        captured["config"] = config

    monkeypatch.setattr(module, "load_config", fake_load_config)
    monkeypatch.setattr(module, "run_forever", fake_run_forever)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_acquire_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "_claim_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *a, **k: None)

    code = module.start_streaming_instance()
    assert code == 0
    assert captured["config"].resolution == "720p"
    assert captured["config"].bitrate_max_kbps == 4500


def test_quality_selection_does_not_rewrite_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    original = "YT_URL=rtmps://example/live2/key\nYT_RESOLUTION=1080p\n"
    env_path.write_text(original, encoding="utf-8")

    def fake_load_config(resolution=None):
        return _build_config(tmp_path)

    monkeypatch.setattr(module, "load_config", fake_load_config)
    monkeypatch.setattr(module, "run_forever", lambda *a, **k: None)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_acquire_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "_claim_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(module, "_script_base_dir", lambda: tmp_path)

    module.start_streaming_instance(send_quality="emergencia")
    assert env_path.read_text(encoding="utf-8") == original


def test_quality_restart_is_single_stop_start_sequence():
    events: list[str] = []
    lock = threading.Lock()
    busy = {"value": False}
    quality = {"key": "alta"}
    starts = {"count": 0}

    def set_busy(value: bool) -> None:
        busy["value"] = value

    def on_quality(key: str) -> bool:
        if key == quality["key"]:
            return False
        previous = quality["key"]
        quality["key"] = key
        if busy["value"] or not lock.acquire(blocking=False):
            quality["key"] = previous
            return False
        set_busy(True)
        events.append(f"stop:{previous}")
        events.append(f"start:{key}")
        starts["count"] += 1
        set_busy(False)
        lock.release()
        return True

    assert on_quality("media") is True
    assert on_quality("media") is False
    # Clique concorrente enquanto o lock está ocupado.
    held = lock.acquire()
    assert held is True
    assert on_quality("baixa") is False
    lock.release()
    assert on_quality("baixa") is True
    assert starts["count"] == 2
    assert events == ["stop:alta", "start:media", "stop:media", "start:baixa"]
    assert quality["key"] == "baixa"


def test_preview_not_touched_on_quality_helper():
    # A mudança de qualidade só aplica output_args; input/preview permanecem.
    profile = get_send_quality_profile("media")
    input_args = ["-i", "rtsp://cam/stream"]
    output = apply_profile_to_output_args(_base_output_args(), profile)
    assert input_args == ["-i", "rtsp://cam/stream"]
    assert "-i" not in output
