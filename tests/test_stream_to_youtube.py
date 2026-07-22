import importlib.util
import os
import signal
import sys
import json
import threading
import time
import types
from pathlib import Path
from typing import Optional

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "primary-windows" / "src" / "stream_to_youtube.py"
SRC_DIR = MODULE_PATH.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

SPEC = importlib.util.spec_from_file_location("_stream_to_youtube_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_to_youtube_test"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
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


def _build_streaming_config(tmp_path: Path, yt_url: Optional[str] = "rtmp://example"):
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
    camera_probe = module.CameraProbeConfig(
        ffprobe="ffprobe",
        interval=5.0,
        timeout=2.0,
        required=False,
    )
    return module.StreamingConfig(
        yt_url=yt_url,
        input_args=[],
        output_args=[],
        resolution="720p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=2000,
        autotune_interval=10.0,
        autotune_safety_margin=0.2,
        heartbeat=heartbeat,
        camera_probe=camera_probe,
    )


def test_status_snapshot_includes_ffmpeg_progress(tmp_path):
    config = _build_streaming_config(tmp_path)
    worker = module.StreamingWorker(config)
    snapshot = worker.status_snapshot()
    assert "ffmpeg_progress" in snapshot
    progress = snapshot["ffmpeg_progress"]
    assert progress["rtmps_send_state"] == "Parado"
    assert "frame" in progress
    assert "fps" in progress
    assert "bitrate" in progress
    assert "total_size" in progress
    assert "out_time_ms" in progress
    assert "speed" in progress
    assert "recent_events" in progress


class _CloseableStream:
    def __init__(self) -> None:
        self.closed = False
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._has_data = threading.Event()
        self._ended = threading.Event()

    def __iter__(self):
        while True:
            with self._lock:
                if self._lines:
                    yield self._lines.pop(0)
                    continue
                if self.closed or self._ended.is_set():
                    return
            self._has_data.wait(timeout=0.05)
            self._has_data.clear()

    def close(self) -> None:
        self.closed = True
        self._ended.set()
        self._has_data.set()


class _FakePopen:
    def __init__(self) -> None:
        self.stdout = _CloseableStream()
        self.stderr = _CloseableStream()
        self.pid = 4242

    def poll(self):
        return None


def test_start_io_threads_does_not_close_new_process_streams(tmp_path):
    config = _build_streaming_config(tmp_path)
    worker = module.StreamingWorker(config)
    proc = _FakePopen()
    worker._process = proc  # noqa: SLF001 - regressão da limpeza prematura

    worker._start_io_threads(proc)  # noqa: SLF001

    assert proc.stdout.closed is False
    assert proc.stderr.closed is False
    assert worker._progress_thread is not None  # noqa: SLF001
    assert worker._stderr_thread is not None  # noqa: SLF001
    assert worker._progress_thread.is_alive()  # noqa: SLF001
    assert worker._stderr_thread.is_alive()  # noqa: SLF001

    progress_thread = worker._progress_thread  # noqa: SLF001
    stderr_thread = worker._stderr_thread  # noqa: SLF001
    worker._stop_io_threads(timeout=1.0)  # noqa: SLF001

    assert proc.stdout.closed is True
    assert proc.stderr.closed is True
    assert progress_thread.is_alive() is False
    assert stderr_thread.is_alive() is False
    assert worker._progress_thread is None  # noqa: SLF001
    assert worker._stderr_thread is None  # noqa: SLF001


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


def test_clear_stale_stop_request_discards_old_flag_even_with_active_pid(
    tmp_path, monkeypatch
):
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"
    sentinel.write_text("", encoding="utf-8")
    pid_path.write_text("7777", encoding="utf-8")

    old_mtime = time.time() - (module._STOP_SENTINEL_STALE_AFTER_SECONDS + 5)
    os.utime(sentinel, (old_mtime, old_mtime))

    events = []
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: events.append(args))
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_is_pid_running", lambda pid: True)

    module._clear_stale_stop_request()

    assert not sentinel.exists()
    assert any("Sentinela de parada antiga" in message for _, message in events)


def test_startup_log_removed_after_successful_launch(tmp_path, monkeypatch):
    startup_log = tmp_path / "startup.log"
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"

    monkeypatch.setenv("BWB_SERVICE_STARTUP_LOG", str(startup_log))
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)
    def _fake_run_forever(*args, **kwargs):
        callback = kwargs.get("startup_confirmed_callback")
        if callback:
            callback()

    monkeypatch.setattr(module, "run_forever", _fake_run_forever)

    config = _build_streaming_config(tmp_path)
    monkeypatch.setattr(module, "load_config", lambda resolution=None: config)

    exit_code = module._start_streaming_instance()
    assert exit_code == 0
    assert not startup_log.exists()
    assert not pid_path.exists()


def test_startup_log_preserved_when_credentials_missing(tmp_path, monkeypatch):
    startup_log = tmp_path / "startup.log"
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"

    monkeypatch.setenv("BWB_SERVICE_STARTUP_LOG", str(startup_log))
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)

    config = _build_streaming_config(tmp_path, yt_url=None)
    monkeypatch.setattr(module, "load_config", lambda resolution=None: config)

    exit_code = module._start_streaming_instance()
    assert exit_code == 2
    assert startup_log.exists()
    contents = startup_log.read_text(encoding="utf-8")
    assert "Credenciais YT_URL/YT_KEY ausentes" in contents


def test_startup_log_preserved_when_worker_quits_early(tmp_path, monkeypatch):
    startup_log = tmp_path / "startup.log"
    sentinel = tmp_path / "stop.flag"
    pid_path = tmp_path / "stream_to_youtube.pid"

    monkeypatch.setenv("BWB_SERVICE_STARTUP_LOG", str(startup_log))
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_stop_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(module, "_pid_file_path", lambda: pid_path)
    monkeypatch.setattr(module, "_clear_stale_stop_request", lambda: None)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)

    def _fake_run_forever(*args, **kwargs):
        callback = kwargs.get("startup_confirmed_callback")
        assert callback is not None
        # Simulate worker ending before grace period elapses by skipping callback
        return None

    monkeypatch.setattr(module, "run_forever", _fake_run_forever)

    config = _build_streaming_config(tmp_path)
    monkeypatch.setattr(module, "load_config", lambda resolution=None: config)

    exit_code = module._start_streaming_instance()
    assert exit_code == 0
    assert startup_log.exists()


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


def test_get_active_worker_snapshot_none_without_worker():
    previous = module._ACTIVE_WORKER
    module._ACTIVE_WORKER = None
    try:
        assert module.get_active_worker_snapshot() is None
    finally:
        module._ACTIVE_WORKER = previous


def test_get_active_worker_snapshot_returns_status(tmp_path):
    config = _build_streaming_config(tmp_path)
    worker = module.StreamingWorker(config)
    previous = module._ACTIVE_WORKER
    module._ACTIVE_WORKER = worker
    try:
        snapshot = module.get_active_worker_snapshot()
        assert snapshot is not None
        assert snapshot["ffmpeg_running"] is False
        assert "ffmpeg_progress" in snapshot
    finally:
        module._ACTIVE_WORKER = previous


def test_main_accepts_ui_flag(monkeypatch):
    calls = []

    fake_ui = types.ModuleType("ui_app")

    def fake_run_ui_app(*, resolution=None):
        calls.append(resolution)
        return 0

    fake_ui.run_ui_app = fake_run_ui_app  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ui_app", fake_ui)
    monkeypatch.setattr(module, "_minimize_console_window", lambda: None)
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_ensure_signal_handlers", lambda: None)

    original_argv = sys.argv
    sys.argv = ["stream_to_youtube.py", "--ui", "--720p"]
    try:
        with pytest.raises(SystemExit) as exc:
            module.main()
    finally:
        sys.argv = original_argv

    assert exc.value.code == 0
    assert calls == ["720p"]


def test_main_ui_installs_signal_handlers_before_run_ui(monkeypatch):
    order: list[str] = []

    def fake_ensure_signal_handlers() -> None:
        order.append("signals")
        module._SIGNAL_HANDLERS_INSTALLED = True

    fake_ui = types.ModuleType("ui_app")

    def fake_run_ui_app(*, resolution=None):
        order.append("ui")
        return 0

    fake_ui.run_ui_app = fake_run_ui_app  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ui_app", fake_ui)
    monkeypatch.setattr(module, "_ensure_signal_handlers", fake_ensure_signal_handlers)
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)

    original_argv = sys.argv
    module._SIGNAL_HANDLERS_INSTALLED = False
    sys.argv = ["stream_to_youtube.py", "--ui"]
    try:
        with pytest.raises(SystemExit) as exc:
            module.main()
    finally:
        sys.argv = original_argv

    assert exc.value.code == 0
    assert order == ["signals", "ui"]


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


def _active_env_assignments(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        parsed = module._parse_env_assignment(line)
        if not parsed:
            continue
        key, value, commented = parsed
        if commented:
            continue
        values[key] = value
    return values


def test_sync_env_preserves_active_day_window_settings(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "YT_URL=rtmps://a.rtmps.youtube.com/live2/KEY",
                "YT_DAY_START_HOUR=0",
                "YT_DAY_END_HOUR=24",
                "YT_TZ_OFFSET_HOURS=0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module._sync_env_against_template(env_path, module.ENV_TEMPLATE_CONTENT)

    updated = env_path.read_text(encoding="utf-8")
    active = _active_env_assignments(updated)

    assert active["YT_DAY_START_HOUR"] == "0"
    assert active["YT_DAY_END_HOUR"] == "24"
    assert active["YT_TZ_OFFSET_HOURS"] == "0"
    assert "desactualizados" not in updated
    assert "YT_DAY_START_HOUR=0" in updated
    assert "YT_DAY_END_HOUR=24" in updated
    assert "YT_TZ_OFFSET_HOURS=0" in updated
    assert "# YT_DAY_START_HOUR=" not in updated
    assert "# YT_DAY_END_HOUR=" not in updated
    assert "# YT_TZ_OFFSET_HOURS=" not in updated
    assert active["YT_DAY_START_HOUR"] != "8"
    assert active["YT_DAY_END_HOUR"] != "19"
    assert active["YT_TZ_OFFSET_HOURS"] != "1"

    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1


def test_sync_env_adds_day_window_options_to_legacy_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "YT_URL=rtmps://a.rtmps.youtube.com/live2/KEY",
                "YT_AUTOTUNE=0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module._sync_env_against_template(env_path, module.ENV_TEMPLATE_CONTENT)

    updated = env_path.read_text(encoding="utf-8")
    active = _active_env_assignments(updated)

    assert "YT_DAY_START_HOUR" in updated
    assert "YT_DAY_END_HOUR" in updated
    assert "YT_TZ_OFFSET_HOURS" in updated
    assert "Janela diária de transmissão" in updated
    assert active["YT_URL"] == "rtmps://a.rtmps.youtube.com/live2/KEY"
    assert active["YT_AUTOTUNE"] == "0"
    assert active["YT_DAY_START_HOUR"] == "8"
    assert active["YT_DAY_END_HOUR"] == "19"
    assert active["YT_TZ_OFFSET_HOURS"] == "1"

    if "desactualizados" in updated:
        outdated_section = updated.split("desactualizados", 1)[-1]
        assert "YT_DAY_START_HOUR" not in outdated_section
        assert "YT_DAY_END_HOUR" not in outdated_section
        assert "YT_TZ_OFFSET_HOURS" not in outdated_section

    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1


def test_sync_env_day_keys_present_in_example_and_embedded_templates():
    example = (SRC_DIR / ".env.example").read_text(encoding="utf-8")
    for key in ("YT_DAY_START_HOUR", "YT_DAY_END_HOUR", "YT_TZ_OFFSET_HOURS"):
        assert key in example
        assert key in module.ENV_TEMPLATE_CONTENT
    assert "#YT_DAY_START_HOUR=8" in example
    assert "#YT_DAY_END_HOUR=19" in example
    assert "#YT_TZ_OFFSET_HOURS=1" in example
    assert "#YT_DAY_START_HOUR=8" in module.ENV_TEMPLATE_CONTENT
    assert "#YT_DAY_END_HOUR=19" in module.ENV_TEMPLATE_CONTENT
    assert "#YT_TZ_OFFSET_HOURS=1" in module.ENV_TEMPLATE_CONTENT
