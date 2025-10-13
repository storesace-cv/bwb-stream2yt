import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "youtube_fallback_watcher.py"
SPEC = importlib.util.spec_from_file_location("youtube_fallback_watcher", MODULE_PATH)
assert SPEC and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

WatcherConfig = module.WatcherConfig
FetcherResult = module.FetcherResult
APIWatcher = module.APIWatcher
EnvManager = module.EnvManager
ModeFileManager = module.ModeFileManager
Mode = module.Mode


class DummyService:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0
        self.restart_calls = 0
        self.active = False

    def is_active(self) -> bool:
        return self.active

    def ensure_started(self) -> bool:
        self.start_calls += 1
        self.active = True
        return True

    def ensure_stopped(self) -> bool:
        self.stop_calls += 1
        self.active = False
        return True

    def restart(self) -> bool:
        self.restart_calls += 1
        self.active = True
        return True


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture()
def config(tmp_path: Path) -> WatcherConfig:
    return WatcherConfig(
        api_url="https://example.test/status",
        check_interval=1,
        heartbeat_stale_sec=5,
        scene_life="life=size=1280x720:rate=30",
        scene_bars="smptehdbars=s=1280x720:rate=30",
        env_file=tmp_path / "fallback.env",
        mode_file=tmp_path / "fallback.mode",
        service_name="youtube-fallback.service",
        request_timeout=1,
    )


def make_watcher(
    config: WatcherConfig, fetch_results: list[FetcherResult], clock: FakeClock
) -> SimpleNamespace:
    service = DummyService()
    env_manager = EnvManager(config.env_file)
    mode_manager = ModeFileManager(config.mode_file)

    def fetcher(_url: str, _timeout: float) -> FetcherResult:
        assert fetch_results, "fetcher called without available results"
        return fetch_results.pop(0)

    watcher = APIWatcher(
        config=config,
        service=service,
        env_manager=env_manager,
        mode_manager=mode_manager,
        fetcher=fetcher,
        clock=clock,
    )
    return SimpleNamespace(
        watcher=watcher, service=service, env=config.env_file, mode=config.mode_file
    )


def test_watcher_transitions_between_modes(config: WatcherConfig) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(True, {"internet": True, "camera": True}),
        FetcherResult(True, {"internet": True, "camera": False}),
        FetcherResult(True, {"internet": True, "camera": False}),
        FetcherResult(True, {"internet": True, "camera": True}),
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.OFF
    assert bundle.service.stop_calls == 1
    assert (
        bundle.env.read_text(encoding="utf-8").strip()
        == "SCENE=life=size=1280x720:rate=30"
    )
    assert bundle.mode.read_text(encoding="utf-8").strip() == "off"

    clock.advance(1)
    assert bundle.watcher.process_once() is Mode.BARS
    assert bundle.service.start_calls == 1
    assert (
        bundle.env.read_text(encoding="utf-8").strip()
        == "SCENE=smptehdbars=s=1280x720:rate=30"
    )
    assert bundle.mode.read_text(encoding="utf-8").strip() == "smptehdbars"

    clock.advance(1)
    assert bundle.watcher.process_once() is Mode.BARS
    assert bundle.service.restart_calls == 0

    clock.advance(1)
    assert bundle.watcher.process_once() is Mode.OFF
    assert bundle.service.stop_calls == 2


def test_watcher_handles_internet_loss(config: WatcherConfig) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(True, {"internet": True, "camera": True}),
        FetcherResult(True, {"internet": False, "camera": True}),
    ]
    bundle = make_watcher(config, results, clock)

    bundle.watcher.process_once()
    clock.advance(1)
    assert bundle.watcher.process_once() is Mode.LIFE
    assert bundle.service.start_calls == 1
    assert (
        bundle.env.read_text(encoding="utf-8").strip()
        == "SCENE=life=size=1280x720:rate=30"
    )
    assert bundle.mode.read_text(encoding="utf-8").strip() == "life"


def test_watcher_triggers_life_on_stale_api(config: WatcherConfig) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(True, {"internet": True, "camera": True}),
        FetcherResult(False, error="timeout"),
        FetcherResult(False, error="timeout"),
    ]
    bundle = make_watcher(config, results, clock)

    bundle.watcher.process_once()
    clock.advance(3)
    assert bundle.watcher.process_once() is Mode.OFF
    clock.advance(5)
    assert bundle.watcher.process_once() is Mode.LIFE
    assert bundle.service.start_calls == 1
    assert (
        bundle.env.read_text(encoding="utf-8").strip()
        == "SCENE=life=size=1280x720:rate=30"
    )
    assert bundle.mode.read_text(encoding="utf-8").strip() == "life"


def test_watcher_understands_status_monitor_snapshot_off(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": False,
                "fallback_reason": None,
                "last_camera_signal": {"present": True},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.OFF
    assert bundle.service.stop_calls == 1


def test_watcher_uses_camera_snapshot_when_api_reports_inactive(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": False,
                "fallback_reason": None,
                "last_camera_signal": {"present": False},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.BARS
    assert bundle.service.start_calls == 1


def test_watcher_understands_status_monitor_camera_loss(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": True,
                "fallback_reason": "no_camera_signal",
                "last_camera_signal": {"present": False},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.BARS
    assert bundle.service.start_calls == 1


def test_watcher_understands_status_monitor_no_heartbeats(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": True,
                "fallback_reason": "no_heartbeats",
                "last_camera_signal": {"present": True},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.LIFE
    assert bundle.service.start_calls == 1


def test_watcher_uses_camera_snapshot_when_reason_missing(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": True,
                "fallback_reason": None,
                "last_camera_signal": {"present": False},
            },
        ),
        FetcherResult(
            True,
            {
                "fallback_active": True,
                "fallback_reason": None,
                "last_camera_signal": {"present": True},
            },
        ),
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.BARS
    assert bundle.service.start_calls == 1

    clock.advance(1)
    assert bundle.watcher.process_once() is Mode.LIFE
    assert bundle.service.restart_calls == 1


def test_watcher_triggers_missing_heartbeats_override(
    config: WatcherConfig,
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "fallback_active": False,
                "fallback_reason": None,
                "seconds_since_last_heartbeat": 120.0,
                "missed_threshold": 40,
                "last_camera_signal": {"present": True},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    assert bundle.watcher.process_once() is Mode.LIFE
    assert bundle.service.start_calls == 1


def test_watcher_does_not_warn_when_snapshot_payload_has_string_internet(
    config: WatcherConfig, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    results = [
        FetcherResult(
            True,
            {
                "internet": "unknown",
                "fallback_active": True,
                "fallback_reason": None,
                "last_camera_signal": {"present": True},
            },
        )
    ]
    bundle = make_watcher(config, results, clock)

    caplog.set_level(logging.WARNING, logger="youtube_fallback_watcher")

    assert bundle.watcher.process_once() is Mode.LIFE
    assert "internet' não é booleano" not in caplog.text
