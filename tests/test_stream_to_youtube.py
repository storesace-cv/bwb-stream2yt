import importlib.util
import signal
import sys
import json
import threading
import time
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "primary-windows" / "src" / "stream_to_youtube.py"
SPEC = importlib.util.spec_from_file_location("_stream_to_youtube_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_to_youtube_test"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune_stub

SPEC.loader.exec_module(module)


class DummyWorker:
    def __init__(self) -> None:
        self._running = False
        self.started = threading.Event()
        self.stop_called = threading.Event()
        self._config = types.SimpleNamespace(
            heartbeat=types.SimpleNamespace(enabled=False, endpoint=None),
            bitrate_min_kbps=0,
            bitrate_max_kbps=0,
            autotune_interval=0.0,
            autotune_safety_margin=0.0,
            day_start_hour=0,
            day_end_hour=0,
            tz_offset_hours=0,
        )

    def start(self) -> None:
        self._running = True
        self.started.set()

    def stop(self, timeout: float | None = None) -> None:  # pragma: no cover - timeout unused
        if self._running:
            self.stop_called.set()
        self._running = False

    def join(self, timeout: float | None = None) -> None:
        if timeout is None:
            while self._running:
                time.sleep(0.05)
        else:
            time.sleep(min(timeout, 0.05))

    @property
    def is_running(self) -> bool:
        return self._running


def test_ctrl_c_ignored_by_signal_handlers():
    sigint = getattr(signal, "SIGINT", None)
    sigterm = getattr(signal, "SIGTERM", None)
    original = {}
    if sigint is not None:
        original[sigint] = signal.getsignal(sigint)
    if sigterm is not None:
        original[sigterm] = signal.getsignal(sigterm)

    try:
        module._SIGNAL_HANDLERS_INSTALLED = False
        module._ensure_signal_handlers()
        if sigint is not None:
            assert signal.getsignal(sigint) == signal.SIG_IGN
    finally:
        for sig, handler in original.items():
            signal.signal(sig, handler)
        module._SIGNAL_HANDLERS_INSTALLED = False
        module._CTRL_HANDLER_REF = None


def test_run_forever_stops_when_sentinel_tripped(tmp_path, monkeypatch):
    sentinel = tmp_path / "stop.flag"
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    module._clear_stop_request()

    worker = DummyWorker()
    runner = threading.Thread(target=module.run_forever, kwargs={"existing_worker": worker})
    runner.start()
    try:
        assert worker.started.wait(1.0)
        assert not sentinel.exists()
        assert module._request_stop_via_sentinel()
        runner.join(timeout=5.0)
        assert not runner.is_alive()
        assert worker.stop_called.is_set()
        assert not sentinel.exists()
    finally:
        if runner.is_alive():
            worker.stop()
            runner.join(timeout=1.0)
        module._ACTIVE_WORKER = None
        module._clear_stop_request()


def test_clear_stale_stop_request_removes_obsolete_flag(tmp_path, monkeypatch):
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"
    sentinel.write_text("", encoding="utf-8")
    pid_path.write_text("9999", encoding="utf-8")

    events = []
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: events.append(args))
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_is_pid_running", lambda pid: False)

    module._clear_stale_stop_request()

    assert not sentinel.exists()
    assert any("Sentinela de parada obsoleta" in message for _, message in events)


def test_clear_stale_stop_request_keeps_flag_when_pid_active(tmp_path, monkeypatch):
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"
    sentinel.write_text("", encoding="utf-8")
    pid_path.write_text("8888", encoding="utf-8")

    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_is_pid_running", lambda pid: True)

    module._clear_stale_stop_request()

    assert sentinel.exists()


def test_stop_streaming_instance_waits_for_orderly_shutdown(tmp_path, monkeypatch):
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    module._clear_stop_request()

    worker = DummyWorker()
    runner = threading.Thread(target=module.run_forever, kwargs={"existing_worker": worker})
    runner.start()
    try:
        assert worker.started.wait(1.0)
        pid_path.write_text("4321", encoding="utf-8")

        monkeypatch.setattr(module, "_is_pid_running", lambda pid: runner.is_alive())

        exit_code = module._stop_streaming_instance(timeout=5.0)
        assert exit_code == 0
        runner.join(timeout=1.0)
        assert not runner.is_alive()
        assert worker.stop_called.is_set()
        assert not pid_path.exists()
        assert not sentinel.exists()
    finally:
        if runner.is_alive():
            worker.stop()
            runner.join(timeout=1.0)
        module._ACTIVE_WORKER = None
        module._clear_stop_request()


def test_camera_signal_monitor_success(monkeypatch):
    monitor = module.CameraSignalMonitor(
        "ffprobe", ["-i", "dummy"], interval=5.0, timeout=2.0, required=True
    )

    def fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"streams": [{"codec_type": "video"}]}),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert monitor.confirm_signal(force=True) is True
    snapshot = monitor.snapshot()
    assert snapshot["present"] is True
    assert snapshot["consecutive_failures"] == 0


def test_camera_signal_monitor_failure(monkeypatch):
    monitor = module.CameraSignalMonitor(
        "ffprobe", ["-i", "dummy"], interval=5.0, timeout=2.0, required=True
    )

    def fake_run(*_args, **_kwargs):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="no video")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert monitor.confirm_signal(force=True) is False
    snapshot = monitor.snapshot()
    assert snapshot["present"] is False
    assert snapshot["consecutive_failures"] == 1
    assert snapshot["last_error"]


def test_write_full_diagnostics_creates_file(tmp_path, monkeypatch):
    class DummyMonitor:
        def __init__(
            self,
            ffprobe: str,
            input_args,
            interval: float,
            timeout: float,
            required: bool,
            log_fn=None,
        ) -> None:
            self.snapshot_data = {
                "present": True,
                "last_success": "2025-01-01T00:00:00",
                "last_failure": None,
                "consecutive_failures": 0,
                "required": required,
                "ffprobe": ffprobe,
                "probe_interval_seconds": interval,
                "probe_timeout_seconds": timeout,
                "last_error": None,
                "ffprobe_available": True,
            }

        def confirm_signal(self, force: bool = False):  # noqa: D401 - signature matches real monitor
            return True

        def snapshot(self):
            return dict(self.snapshot_data)

    heartbeat = module.HeartbeatConfig(
        enabled=True,
        endpoint="http://example.test/status",
        interval=20.0,
        timeout=5.0,
        machine_id="TEST-NODE",
        token=None,
        log_path=tmp_path / "hb.jsonl",
        log_retention_seconds=3600,
    )

    config = module.StreamingConfig(
        yt_url="rtmps://a.rtmps.youtube.com/live2/KEY",
        input_args=["-i", "rtsp://user:pass@camera/stream"],
        output_args=["-c:v", "libx264", "-b:v", "4500k"],
        resolution="720p",
        ffmpeg="ffmpeg",
        day_start_hour=8,
        day_end_hour=20,
        tz_offset_hours=0,
        autotune_enabled=True,
        bitrate_min_kbps=3000,
        bitrate_max_kbps=4500,
        autotune_interval=8.0,
        autotune_safety_margin=0.75,
        heartbeat=heartbeat,
        camera_probe=module.CameraProbeConfig(
            ffprobe="ffprobe",
            interval=10.0,
            timeout=5.0,
            required=True,
        ),
    )

    monkeypatch.setattr(module, "_script_base_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "CameraSignalMonitor", DummyMonitor)
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "_collect_camera_ping_snapshot",
        lambda host: {
            "host": host,
            "reachable": True,
            "rtt_ms": 12.5,
            "last_checked": "2025-01-01T00:00:00Z",
        },
    )

    module._write_full_diagnostics(config)

    diagnostics_path = tmp_path / "stream2yt-diags.txt"
    assert diagnostics_path.exists()
    content = diagnostics_path.read_text(encoding="utf-8")
    assert "Diagnóstico stream_to_youtube" in content
    assert "Sinal da câmara" in content
    assert "Ping da câmara" in content
    assert "rtsp://user:***@camera/stream" in content


def test_main_accepts_fulldiags_flag(monkeypatch):
    calls = []

    def fake_start(*, resolution=None, full_diagnostics=False):
        calls.append((resolution, full_diagnostics))
        return 0

    monkeypatch.setattr(module, "_minimize_console_window", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_start_streaming_instance", fake_start)

    original_argv = sys.argv
    sys.argv = ["stream_to_youtube.py", "--fulldiags"]
    try:
        with pytest.raises(SystemExit) as exc:
            module.main()
    finally:
        sys.argv = original_argv

    assert exc.value.code == 0
    assert calls == [(None, True)]
