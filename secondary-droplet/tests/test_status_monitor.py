import datetime as dt
import errno
import http.client
import importlib.util
import json
import sys
import threading
from types import SimpleNamespace
from pathlib import Path
from typing import Dict, Optional

import pytest


MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "bwb_status_monitor.py"
SPEC = importlib.util.spec_from_file_location("bwb_status_monitor", MODULE_PATH)
assert SPEC and SPEC.loader is not None
status_monitor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = status_monitor
SPEC.loader.exec_module(status_monitor)

MonitorSettings = status_monitor.MonitorSettings
StatusEntry = status_monitor.StatusEntry
StatusMonitor = status_monitor.StatusMonitor
utc_now = status_monitor.utc_now
run_server = status_monitor.run_server


class DummyFallbackController:
    def __init__(self) -> None:
        self.mode_calls: list[str] = []
        self.force_flags: list[bool] = []
        self.stop_calls = 0
        self.current: Optional[str] = None

    def set_mode(self, mode: str, *, force: bool = False) -> bool:
        if not force and self.current == mode:
            return True
        self.mode_calls.append(mode)
        self.force_flags.append(force)
        self.current = mode
        return True

    def ensure_stopped(self) -> bool:
        self.stop_calls += 1
        self.current = None
        return True


@pytest.fixture()
def monitor(tmp_path: Path) -> StatusMonitor:
    settings = MonitorSettings(
        missed_threshold=2,
        check_interval=1,
        log_file=tmp_path / "monitor.log",
        mode_file=tmp_path / "fallback.mode",
    )
    return StatusMonitor(settings=settings, fallback_controller=DummyFallbackController())


def make_entry(
    machine: str = "pc-1", camera_signal: Optional[Dict[str, object]] = None
) -> StatusEntry:
    now = utc_now()
    payload = {"machine_id": machine, "status": {"ffmpeg_running": True}}
    if camera_signal is not None:
        payload["status"]["camera_signal"] = camera_signal
    return StatusEntry(
        timestamp=now,
        machine_id=machine,
        payload=payload,
        remote_addr="127.0.0.1",
        raw_body="{}",
    )


def test_triggers_fallback_after_threshold(monitor: StatusMonitor) -> None:
    # simulate that we have not received heartbeats for longer than the threshold
    monitor._last_timestamp = utc_now() - dt.timedelta(seconds=5)  # noqa: SLF001
    controller = monitor._fallback  # type: ignore[attr-defined]  # noqa: SLF001

    monitor._evaluate_threshold()  # noqa: SLF001

    assert controller.mode_calls == ["life"]
    assert monitor.fallback_active is True
    assert monitor.snapshot()["fallback_reason"] == "no_heartbeats"
    assert monitor.settings.mode_file.read_text(encoding="utf-8").strip() == "life"


def test_stops_fallback_after_single_heartbeat(monitor: StatusMonitor) -> None:
    monitor._last_timestamp = utc_now() - dt.timedelta(seconds=5)  # noqa: SLF001
    controller = monitor._fallback  # type: ignore[attr-defined]  # noqa: SLF001
    monitor._evaluate_threshold()  # noqa: SLF001

    assert monitor.fallback_active is True
    assert controller.mode_calls == ["life"]

    monitor.record_status(make_entry(camera_signal={"present": True}))
    assert monitor.fallback_active is False
    assert controller.stop_calls == 1
    assert monitor.settings.mode_file.read_text(encoding="utf-8").strip() == "life"


def test_camera_absence_triggers_smpte(monitor: StatusMonitor) -> None:
    monitor.record_status(
        make_entry(camera_signal={"present": False, "last_error": "timeout"})
    )

    assert monitor.fallback_active is True
    controller = monitor._fallback  # type: ignore[attr-defined]  # noqa: SLF001
    assert controller.mode_calls[-1] == "bars"
    snapshot = monitor.snapshot()
    assert snapshot["fallback_reason"] == "no_camera_signal"
    assert snapshot["last_camera_signal"]["present"] is False
    assert (
        monitor.settings.mode_file.read_text(encoding="utf-8").strip()
        == "smptehdbars"
    )


def test_camera_absence_forces_restart_after_connection_loss(monitor: StatusMonitor) -> None:
    monitor._fallback_active = True  # noqa: SLF001
    monitor._fallback_reason = "no_heartbeats"  # noqa: SLF001
    monitor.settings.mode_file.write_text("life\n", encoding="utf-8")

    monitor.record_status(make_entry(camera_signal={"present": False}))

    controller = monitor._fallback  # type: ignore[attr-defined]  # noqa: SLF001
    assert controller.force_flags[-1] is True
    assert controller.mode_calls[-1] == "bars"
    assert monitor.fallback_active is True
    assert (
        monitor.settings.mode_file.read_text(encoding="utf-8").strip()
        == "smptehdbars"
    )
    assert monitor.snapshot()["fallback_reason"] == "no_camera_signal"


def test_camera_absence_keeps_service_confirmed(monitor: StatusMonitor) -> None:
    monitor.record_status(make_entry(camera_signal={"present": False}))

    controller = monitor._fallback  # type: ignore[attr-defined]  # noqa: SLF001
    first_call_count = len(controller.mode_calls)

    monitor.record_status(make_entry(camera_signal={"present": False}))

    assert monitor.fallback_active is True
    assert len(controller.mode_calls) == first_call_count


def test_camera_recovery_stops_fallback(monitor: StatusMonitor) -> None:
    monitor.record_status(make_entry(camera_signal={"present": False}))
    assert monitor.fallback_active is True

    monitor.record_status(make_entry(camera_signal={"present": True}))
    assert monitor.fallback_active is False
    snapshot = monitor.snapshot()
    assert snapshot["fallback_reason"] is None
    assert monitor.settings.mode_file.read_text(encoding="utf-8").strip() == "life"


def test_run_server_handles_address_in_use(tmp_path: Path, monkeypatch, caplog):
    caplog.set_level("ERROR")

    settings = MonitorSettings(
        bind="127.0.0.1",
        port=8080,
        missed_threshold=2,
        check_interval=1,
        log_file=tmp_path / "monitor.log",
        mode_file=tmp_path / "fallback.mode",
    )

    args = SimpleNamespace(bind="127.0.0.1", port=9090, graceful_timeout=10)

    class FailingServer:
        def __init__(self, *_args, **_kwargs):  # noqa: D401 - simple stub
            raise OSError(errno.EADDRINUSE, "Address already in use")

    monkeypatch.setattr(status_monitor, "StatusHTTPServer", FailingServer)

    with pytest.raises(SystemExit) as excinfo:
        run_server(settings, args)

    assert excinfo.value.code == 1
    assert any("já está em uso" in message for message in caplog.messages)


def test_monitor_settings_accepts_ytr_env(monkeypatch):
    monkeypatch.setenv("YTR_TOKEN", "supersecret")
    monkeypatch.setenv("YTR_REQUIRE_TOKEN", "1")
    monkeypatch.setenv("YTR_PORT", "9090")
    monkeypatch.setenv("YTR_SECONDARY_SERVICE", "custom.service")
    monkeypatch.setenv("YTR_FALLBACK_MODE_FILE", "/tmp/custom.mode")
    monkeypatch.setenv("YTR_FALLBACK_CLI", "/opt/bin/yt-fallback")

    settings = MonitorSettings.from_env()

    assert settings.auth_token == "supersecret"
    assert settings.require_token is True
    assert settings.port == 9090
    assert settings.secondary_service == "custom.service"
    assert settings.mode_file == Path("/tmp/custom.mode")
    assert settings.fallback_cli == Path("/opt/bin/yt-fallback")


def test_post_requires_bearer_token(tmp_path: Path):
    settings = MonitorSettings(
        missed_threshold=2,
        check_interval=1,
        log_file=tmp_path / "monitor.log",
        auth_token="topsecret",
        require_token=True,
        mode_file=tmp_path / "fallback.mode",
    )
    monitor = StatusMonitor(settings=settings, fallback_controller=DummyFallbackController())
    server = status_monitor.StatusHTTPServer(
        ("127.0.0.1", 0), status_monitor.StatusHTTPRequestHandler, monitor
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST",
            "/status",
            body=json.dumps({"machine_id": "PC-1"}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        assert response.status == 403
        response.read()
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request(
            "POST",
            "/status",
            body=json.dumps({"machine_id": "PC-1"}),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer topsecret",
            },
        )
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["ok"] is True
        assert "seconds_since_last_heartbeat" in payload
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=1)
        monitor.shutdown()
