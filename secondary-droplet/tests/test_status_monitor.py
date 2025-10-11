import datetime as dt
import errno
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

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


class DummyServiceManager:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.active = False

    def ensure_started(self) -> bool:
        self.start_calls += 1
        self.active = True
        return True

    def ensure_stopped(self) -> bool:
        self.stop_calls += 1
        self.active = False
        return True


@pytest.fixture()
def monitor(tmp_path: Path) -> StatusMonitor:
    settings = MonitorSettings(
        history_seconds=60,
        missed_threshold=2,
        recovery_reports=2,
        check_interval=1,
        state_file=tmp_path / "status.json",
        log_file=tmp_path / "monitor.log",
    )
    return StatusMonitor(settings=settings, service_manager=DummyServiceManager())


def make_entry(machine: str = "pc-1") -> StatusEntry:
    now = utc_now()
    payload = {"machine_id": machine, "status": {"ffmpeg_running": True}}
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
    service = monitor._service_manager  # type: ignore[attr-defined]  # noqa: SLF001

    monitor._evaluate_threshold()  # noqa: SLF001

    assert service.start_calls == 1
    assert monitor.fallback_active is True


def test_stops_fallback_after_recovery(monitor: StatusMonitor) -> None:
    monitor._last_timestamp = utc_now() - dt.timedelta(seconds=5)  # noqa: SLF001
    service = monitor._service_manager  # type: ignore[attr-defined]  # noqa: SLF001
    monitor._evaluate_threshold()  # noqa: SLF001

    assert monitor.fallback_active is True
    assert service.start_calls == 1

    monitor.record_status(make_entry())
    # ainda não atingiu os 2 relatórios necessários
    assert monitor.fallback_active is True
    assert service.stop_calls == 0

    monitor.record_status(make_entry())
    assert monitor.fallback_active is False
    assert service.stop_calls == 1

    history = monitor.snapshot()["history"]
    assert len(history) == 2


def test_run_server_handles_address_in_use(tmp_path: Path, monkeypatch, caplog):
    caplog.set_level("ERROR")

    settings = MonitorSettings(
        bind="127.0.0.1",
        port=8080,
        history_seconds=60,
        missed_threshold=2,
        recovery_reports=2,
        check_interval=1,
        state_file=tmp_path / "status.json",
        log_file=tmp_path / "monitor.log",
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
