"""Testes do modo de vídeo de demonstração (sem PySide6 / sem MP4 real)."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from demo_video import (  # noqa: E402
    DEFAULT_DEMO_VIDEO_PATH,
    DEMO_CAMERA_STATUS,
    build_demo_input_args,
    demo_video_exists,
    demo_video_missing_message,
    resolve_demo_video_path,
)
from preview_rtsp import build_preview_command  # noqa: E402
from ui_app import derive_camera_status, replace_active_preview  # noqa: E402

MODULE_PATH = SRC_DIR / "stream_to_youtube.py"
SPEC = importlib.util.spec_from_file_location("_stream_to_youtube_demo_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_to_youtube_demo_test"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune_stub

SPEC.loader.exec_module(module)


def test_default_demo_path():
    assert resolve_demo_video_path(environ={}) == DEFAULT_DEMO_VIDEO_PATH
    assert DEFAULT_DEMO_VIDEO_PATH.endswith(
        "bbb_sunflower_1080p_30fps_normal.mp4"
    )


def test_demo_path_env_override(monkeypatch):
    monkeypatch.setenv("BWB_DEMO_VIDEO", r"D:\videos\demo.mp4")
    assert resolve_demo_video_path() == r"D:\videos\demo.mp4"


def test_build_demo_input_args_loop_realtime():
    path = r"C:\bwb\apps\youtube\demo\bbb_sunflower_1080p_30fps_normal.mp4"
    assert build_demo_input_args(path) == [
        "-stream_loop",
        "-1",
        "-re",
        "-i",
        path,
    ]


def test_missing_demo_file_message_and_exists(tmp_path):
    missing = tmp_path / "absent.mp4"
    assert demo_video_exists(str(missing)) is False
    assert str(missing) in demo_video_missing_message(str(missing))


def test_apply_demo_does_not_mutate_original_config(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    original_args = ["-rtsp_transport", "tcp", "-i", "rtsp://cam/stream"]
    config = module.StreamingConfig(
        yt_url="rtmps://example/live2/key",
        input_args=list(original_args),
        output_args=["-c:v", "libx264"],
        resolution="720p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=2000,
        autotune_interval=8.0,
        autotune_safety_margin=0.2,
        heartbeat=module.HeartbeatConfig(
            enabled=False,
            endpoint=None,
            interval=20.0,
            timeout=5.0,
            machine_id="TEST",
            token=None,
            log_path=tmp_path / "hb.jsonl",
            log_retention_seconds=3600,
        ),
        camera_probe=module.CameraProbeConfig(
            ffprobe="ffprobe",
            interval=5.0,
            timeout=2.0,
            required=True,
        ),
    )
    demo = module.apply_demo_video_source(config, str(video))
    assert config.input_args == original_args
    assert config.demo_mode is False
    assert config.camera_probe.required is True
    assert demo.demo_mode is True
    assert demo.camera_probe.required is False
    assert demo.input_args == build_demo_input_args(str(video))
    assert demo.input_args != original_args


def test_preview_command_uses_demo_mp4(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    args = build_demo_input_args(str(video))
    command = build_preview_command("ffmpeg", args)
    assert "-stream_loop" in command
    assert str(video) in command
    assert command[-1] == "-"


def test_ui_status_shows_demo_label():
    assert derive_camera_status(None, demo_mode=True) == DEMO_CAMERA_STATUS
    assert (
        derive_camera_status({"demo_mode": True, "camera_signal": {"present": True}})
        == DEMO_CAMERA_STATUS
    )
    assert (
        derive_camera_status({"camera_signal": {"present": True}}, demo_mode=False)
        == "OK"
    )


def test_replace_preview_stops_previous_before_starting_new():
    events: list[str] = []
    alive_sessions: set[str] = set()

    class FakeSession:
        def __init__(self, name: str) -> None:
            self.name = name
            self.alive = False

        def start(self) -> None:
            events.append(f"start:{self.name}")
            self.alive = True
            alive_sessions.add(self.name)
            assert len(alive_sessions) == 1

        def stop(self, timeout: float = 5.0) -> None:
            events.append(f"stop:{self.name}")
            self.alive = False
            alive_sessions.discard(self.name)

    first = FakeSession("a")
    first.alive = True
    alive_sessions.add("a")
    holder: dict = {"session": first}
    lock = threading.Lock()
    counter = {"n": 0}

    def build_session():
        assert holder["session"] is None
        assert first.alive is False
        counter["n"] += 1
        return FakeSession(f"b{counter['n']}")

    result = replace_active_preview(lock, holder, build_session=build_session)
    assert result is holder["session"]
    assert events == ["stop:a", "start:b1"]
    assert first.alive is False
    assert holder["session"].alive is True
    assert alive_sessions == {"b1"}


def test_replace_preview_never_two_active_under_contention():
    alive_count = {"max": 0, "current": 0}
    barrier = threading.Barrier(3)
    lock = threading.RLock()
    holder: dict = {"session": None}
    counter = {"n": 0}
    counter_lock = threading.Lock()

    class FakeSession:
        def __init__(self, name: str) -> None:
            self.name = name
            self.alive = False

        def start(self) -> None:
            self.alive = True
            alive_count["current"] += 1
            alive_count["max"] = max(alive_count["max"], alive_count["current"])
            time.sleep(0.02)

        def stop(self, timeout: float = 5.0) -> None:
            time.sleep(0.02)
            if self.alive:
                self.alive = False
                alive_count["current"] -= 1

    def build_session():
        with counter_lock:
            counter["n"] += 1
            name = f"s{counter['n']}"
        time.sleep(0.01)
        return FakeSession(name)

    def worker() -> None:
        barrier.wait()
        replace_active_preview(lock, holder, build_session=build_session)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert alive_count["max"] == 1
    assert holder["session"] is not None
    assert holder["session"].alive is True
    assert alive_count["current"] == 1


def test_start_streaming_demo_missing_file_returns_3(tmp_path, monkeypatch):
    missing = tmp_path / "nope.mp4"
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_acquire_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "_claim_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_pid_file", lambda: None)
    monkeypatch.setattr(module, "_release_single_instance_mutex", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *a, **k: None)

    code = module.start_streaming_instance(demo_video_path=str(missing))
    assert code == 3


def test_start_streaming_without_demo_keeps_rtsp_path(tmp_path, monkeypatch):
    captured = {}

    def fake_load_config(resolution=None):
        return module.StreamingConfig(
            yt_url="rtmps://example/live2/key",
            input_args=["-i", "rtsp://cam/stream"],
            output_args=[],
            resolution="720p",
            ffmpeg="ffmpeg",
            day_start_hour=0,
            day_end_hour=24,
            tz_offset_hours=0,
            autotune_enabled=False,
            bitrate_min_kbps=1000,
            bitrate_max_kbps=2000,
            autotune_interval=8.0,
            autotune_safety_margin=0.2,
            heartbeat=module.HeartbeatConfig(
                enabled=False,
                endpoint=None,
                interval=20.0,
                timeout=5.0,
                machine_id="TEST",
                token=None,
                log_path=tmp_path / "hb.jsonl",
                log_retention_seconds=3600,
            ),
            camera_probe=module.CameraProbeConfig(
                ffprobe="ffprobe",
                interval=5.0,
                timeout=2.0,
                required=False,
            ),
        )

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
    assert captured["config"].demo_mode is False
    assert captured["config"].input_args == ["-i", "rtsp://cam/stream"]


def test_start_streaming_demo_uses_mp4_without_changing_env(tmp_path, monkeypatch):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"data")
    captured = {}

    def fake_load_config(resolution=None):
        return module.StreamingConfig(
            yt_url="rtmps://example/live2/key",
            input_args=["-i", "rtsp://cam/stream"],
            output_args=[],
            resolution="720p",
            ffmpeg="ffmpeg",
            day_start_hour=0,
            day_end_hour=24,
            tz_offset_hours=0,
            autotune_enabled=False,
            bitrate_min_kbps=1000,
            bitrate_max_kbps=2000,
            autotune_interval=8.0,
            autotune_safety_margin=0.2,
            heartbeat=module.HeartbeatConfig(
                enabled=False,
                endpoint=None,
                interval=20.0,
                timeout=5.0,
                machine_id="TEST",
                token=None,
                log_path=tmp_path / "hb.jsonl",
                log_retention_seconds=3600,
            ),
            camera_probe=module.CameraProbeConfig(
                ffprobe="ffprobe",
                interval=5.0,
                timeout=2.0,
                required=True,
            ),
        )

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
    monkeypatch.delenv("YT_INPUT_ARGS", raising=False)

    code = module.start_streaming_instance(demo_video_path=str(video))
    assert code == 0
    assert captured["config"].demo_mode is True
    assert captured["config"].input_args == build_demo_input_args(str(video))
    assert "YT_INPUT_ARGS" not in __import__("os").environ
