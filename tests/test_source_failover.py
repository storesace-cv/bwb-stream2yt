"""Testes determinísticos do controlador de failover."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from source_failover import (  # noqa: E402
    FAILOVER_COOLDOWN_S,
    RECOVERY_PROBE_INTERVAL_S,
    SWITCH_DEADLINE_S,
    FailoverAction,
    FailoverState,
    SourceFailoverController,
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _controller(clock: Clock, *, exists: bool = True) -> SourceFailoverController:
    ids = iter(["one", "two", "three", "four"])
    controller = SourceFailoverController(
        enabled=True,
        demo_path="/tmp/demo.mp4",
        demo_exists=lambda: exists,
        monotonic=clock,
        new_transition_id=lambda: next(ids),
    )
    controller.start_camera_session()
    return controller


def _evaluate(controller: SourceFailoverController, **overrides):
    values = {
        "ffmpeg_running": True,
        "rtmps_state": "A enviar",
        "last_exit_code": None,
        "internet_online": True,
        "camera_present": True,
        "seconds_since_progress": 0.0,
        "stop_requested": False,
    }
    values.update(overrides)
    return controller.evaluate(**values)


def _reach_demo_transition(controller: SourceFailoverController):
    assert (
        _evaluate(controller, ffmpeg_running=False, last_exit_code=1).action
        == FailoverAction.BEGIN_CONFIRM
    )
    return _evaluate(
        controller, ffmpeg_running=False, last_exit_code=1, camera_present=False
    )


def test_stall_or_exit_enters_failure_pending() -> None:
    clock = Clock()
    for values in (
        {"seconds_since_progress": 6.0},
        {"ffmpeg_running": False, "last_exit_code": 1},
    ):
        controller = _controller(clock)
        decision = _evaluate(controller, **values)
        assert decision.action == FailoverAction.BEGIN_CONFIRM
        assert decision.snapshot.state == FailoverState.CAMERA_FAILURE_PENDING


def test_offline_never_starts_demo_and_missing_demo_never_transitions() -> None:
    clock = Clock()
    offline = _controller(clock)
    assert (
        _evaluate(offline, internet_online=False, ffmpeg_running=False).action
        == FailoverAction.MARK_OFFLINE
    )
    assert offline.snapshot().state == FailoverState.INTERNET_OFFLINE

    missing = _controller(clock, exists=False)
    _evaluate(missing, ffmpeg_running=False)
    decision = _evaluate(missing, ffmpeg_running=False, camera_present=False)
    assert decision.action != FailoverAction.ENTER_TRANSITION_TO_DEMO
    assert decision.reason == "demo_missing"


def test_transition_metadata_deadline_and_unique_ids() -> None:
    clock = Clock()
    controller = _controller(clock)
    decision = _reach_demo_transition(controller)
    transition = decision.snapshot.transition
    assert decision.action == FailoverAction.ENTER_TRANSITION_TO_DEMO
    assert transition.active and transition.transition_id == "one"
    assert transition.started_at == clock.now
    assert transition.target == "contingency_demo"
    assert (
        transition.deadline is not None
        and transition.deadline - transition.event_at <= SWITCH_DEADLINE_S
    )

    controller.mark_demo_started_failed(camera_present=True)
    assert controller.snapshot().transition.transition_id == "two"


def test_recovery_requires_two_consecutive_successes_and_resets_on_failure() -> None:
    clock = Clock()
    controller = _controller(clock)
    _reach_demo_transition(controller)
    _evaluate(controller, ffmpeg_running=True, rtmps_state="A enviar")
    assert controller.snapshot().state == FailoverState.DEMO_ACTIVE

    clock.advance(FAILOVER_COOLDOWN_S + RECOVERY_PROBE_INTERVAL_S)
    _evaluate(controller, camera_present=True)
    assert controller.snapshot().recovery_successes == 1
    clock.advance(RECOVERY_PROBE_INTERVAL_S)
    _evaluate(controller, camera_present=False)
    assert controller.snapshot().recovery_successes == 0
    clock.advance(RECOVERY_PROBE_INTERVAL_S)
    _evaluate(controller, camera_present=True)
    clock.advance(RECOVERY_PROBE_INTERVAL_S)
    assert (
        _evaluate(controller, camera_present=True).action
        == FailoverAction.ENTER_TRANSITION_TO_CAMERA
    )


def test_stop_and_rollbacks_clear_or_replace_transition() -> None:
    clock = Clock()
    controller = _controller(clock)
    _reach_demo_transition(controller)
    decision = controller.mark_demo_started_failed(camera_present=False)
    assert decision.action == FailoverAction.ABORT_TO_CLOUD
    assert not decision.snapshot.transition.active

    controller = _controller(clock)
    _reach_demo_transition(controller)
    decision = controller.mark_camera_start_failed()
    assert decision.action == FailoverAction.ROLLBACK_TO_DEMO
    assert decision.snapshot.transition.active
    controller.stop()
    assert controller.snapshot().state == FailoverState.STOPPED
    assert not controller.snapshot().transition.active


def test_cooldown_blocks_immediate_recovery_transition() -> None:
    clock = Clock()
    controller = _controller(clock)
    _reach_demo_transition(controller)
    _evaluate(controller, ffmpeg_running=True, rtmps_state="A enviar")
    _evaluate(controller, camera_present=True)
    clock.advance(RECOVERY_PROBE_INTERVAL_S)
    assert _evaluate(controller, camera_present=True).action == FailoverAction.KEEP
