"""Testes unitários da observabilidade FFmpeg (Fase 0)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from observability import (  # noqa: E402
    HUMAN_MESSAGES,
    STATE_ERROR,
    STATE_NO_PROGRESS,
    STATE_SENDING,
    STATE_STARTING,
    STATE_STOPPED,
    EventBus,
    FFmpegProgressTracker,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _feed_block(tracker: FFmpegProgressTracker, **fields: str) -> None:
    for key, value in fields.items():
        tracker.feed_line(f"{key}={value}")
    tracker.feed_line("progress=continue")


def test_parse_progress_block_metrics():
    tracker = FFmpegProgressTracker()
    tracker.mark_session_started()
    _feed_block(
        tracker,
        frame="120",
        fps="29.97",
        bitrate="1500.5kbits/s",
        total_size="4096",
        out_time_ms="4000",
        out_time="00:00:04.000000",
        speed="1.0x",
    )
    snap = tracker.metrics_snapshot()
    assert snap["frame"] == 120
    assert snap["fps"] == pytest.approx(29.97)
    assert snap["bitrate"] == "1500.5kbits/s"
    assert snap["bitrate_kbps"] == pytest.approx(1500.5)
    assert snap["total_size"] == 4096
    assert snap["out_time_ms"] == 4000
    assert snap["out_time"] == "00:00:04.000000"
    assert snap["speed"] == "1.0x"


def test_invalid_values_are_ignored_safely():
    tracker = FFmpegProgressTracker()
    tracker.mark_session_started()
    _feed_block(
        tracker,
        frame="10",
        fps="30",
        bitrate="1000.0kbits/s",
        total_size="100",
        out_time_ms="1000",
        speed="1.0x",
    )
    _feed_block(
        tracker,
        frame="not-a-number",
        fps="n/a",
        bitrate="N/A",
        total_size="",
        out_time_ms="oops",
        speed="N/A",
    )
    snap = tracker.metrics_snapshot()
    assert snap["frame"] == 10
    assert snap["fps"] == pytest.approx(30.0)
    assert snap["total_size"] == 100
    assert snap["out_time_ms"] == 1000
    assert snap["bitrate"] == "1000.0kbits/s"
    assert snap["bitrate_kbps"] == pytest.approx(1000.0)
    assert snap["speed"] == "1.0x"


def test_sending_state_after_progress():
    clock = FakeClock()
    tracker = FFmpegProgressTracker(monotonic=clock)
    tracker.mark_session_started()
    clock.advance(6.0)
    _feed_block(tracker, frame="1", total_size="10", out_time_ms="100")
    assert tracker.rtmps_send_state(now=clock()) == STATE_SENDING
    clock.advance(3.0)
    assert tracker.rtmps_send_state(now=clock()) == STATE_SENDING


def test_grace_period_reports_starting_without_progress():
    clock = FakeClock()
    tracker = FFmpegProgressTracker(monotonic=clock)
    tracker.mark_session_started()
    clock.advance(4.9)
    assert tracker.rtmps_send_state(now=clock()) == STATE_STARTING


def test_sending_during_grace_when_progress_arrives():
    clock = FakeClock()
    tracker = FFmpegProgressTracker(monotonic=clock)
    tracker.mark_session_started()
    clock.advance(2.0)
    _feed_block(tracker, frame="1", total_size="10", out_time_ms="100")
    assert tracker.rtmps_send_state(now=clock()) == STATE_SENDING


def test_no_progress_after_stall_timeout():
    clock = FakeClock()
    tracker = FFmpegProgressTracker(monotonic=clock)
    tracker.mark_session_started()
    clock.advance(6.0)
    _feed_block(tracker, frame="5", total_size="50", out_time_ms="500")
    assert tracker.rtmps_send_state(now=clock()) == STATE_SENDING
    clock.advance(8.1)
    assert tracker.rtmps_send_state(now=clock()) == STATE_NO_PROGRESS
    events = tracker.events.recent()
    assert any(event["code"] == "no_progress" for event in events)


def test_no_progress_when_grace_ends_without_any_progress():
    clock = FakeClock()
    tracker = FFmpegProgressTracker(monotonic=clock)
    tracker.mark_session_started()
    clock.advance(5.1)
    assert tracker.rtmps_send_state(now=clock()) == STATE_NO_PROGRESS


def test_stopped_state():
    tracker = FFmpegProgressTracker()
    assert tracker.rtmps_send_state() == STATE_STOPPED
    tracker.mark_session_started()
    tracker.mark_session_stopped()
    assert tracker.rtmps_send_state() == STATE_STOPPED


def test_error_state():
    tracker = FFmpegProgressTracker()
    tracker.mark_session_started()
    tracker.mark_error("código 1")
    assert tracker.rtmps_send_state() == STATE_ERROR
    snap = tracker.metrics_snapshot()
    assert snap["error_detail"] == "código 1"
    assert any(
        event["code"] == "ffmpeg_exit_error" for event in tracker.events.recent()
    )


def test_event_bus_ring_buffer_and_human_messages():
    bus = EventBus(maxlen=3)
    bus.emit_human("session_started")
    bus.emit_human("sending")
    bus.emit_human("no_progress")
    bus.emit_human("ffmpeg_exit_error", detail="código 2")
    recent = bus.recent()
    assert len(recent) == 3
    assert recent[0]["code"] == "sending"
    assert recent[-1]["code"] == "ffmpeg_exit_error"
    assert HUMAN_MESSAGES["ffmpeg_exit_error"] in recent[-1]["message"]
    assert "código 2" in recent[-1]["message"]


def test_out_time_us_converted_to_ms():
    tracker = FFmpegProgressTracker()
    tracker.mark_session_started()
    tracker.feed_progress_block({"out_time_us": "2500000", "frame": "3"})
    assert tracker.metrics_snapshot()["out_time_ms"] == 2500
