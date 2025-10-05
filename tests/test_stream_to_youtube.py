import importlib.util
import signal
import sys
import threading
import time
import types
from pathlib import Path

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
