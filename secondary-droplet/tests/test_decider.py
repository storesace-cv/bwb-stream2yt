import sys
import types
from pathlib import Path

import pytest

# Stub minimal google modules so yt_decider_daemon can be imported without external deps
if "google" not in sys.modules:
    google_module = types.ModuleType("google")
    sys.modules["google"] = google_module
else:
    google_module = sys.modules["google"]

google_oauth2 = types.ModuleType("google.oauth2")
sys.modules["google.oauth2"] = google_oauth2
google_module.oauth2 = google_oauth2

google_credentials = types.ModuleType("google.oauth2.credentials")


class _DummyCredentials:
    @classmethod
    def from_authorized_user_file(
        cls, *args, **kwargs
    ):  # pragma: no cover - behaviour mocked in tests
        return object()


google_credentials.Credentials = _DummyCredentials
sys.modules["google.oauth2.credentials"] = google_credentials
google_oauth2.credentials = google_credentials

googleapiclient = types.ModuleType("googleapiclient")
sys.modules["googleapiclient"] = googleapiclient

discovery_module = types.ModuleType("googleapiclient.discovery")


def _dummy_build(*args, **kwargs):  # pragma: no cover - replaced in tests
    raise AssertionError("build() should be patched in tests")


discovery_module.build = _dummy_build
googleapiclient.discovery = discovery_module
sys.modules["googleapiclient.discovery"] = discovery_module

BIN_PATH = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_PATH) not in sys.path:
    sys.path.insert(0, str(BIN_PATH))

import yt_decider_daemon as decider  # noqa: E402


class StopLoop(Exception):
    """Helper exception to interrupt the infinite loop."""


def run_cycles(monkeypatch, scenarios):
    """Execute consecutive main loop iterations with controlled environment."""

    monkeypatch.setattr(decider, "build_api", lambda: object())

    scenario_iter = iter(scenarios)
    current = next(scenario_iter)

    fallback_state = current["fallback_active"]

    def _advance():
        nonlocal current, fallback_state
        current = next(scenario_iter)
        fallback_state = current.get("fallback_active", fallback_state)

    monkeypatch.setattr(decider, "get_state", lambda _api: current["state"])
    monkeypatch.setattr(decider, "local_hour", lambda: current["hour"])
    monkeypatch.setattr(decider, "is_active", lambda _unit: fallback_state)

    start_calls = []
    stop_calls = []

    def _start():
        nonlocal fallback_state
        start_calls.append(True)
        fallback_state = True

    def _stop():
        nonlocal fallback_state
        stop_calls.append(True)
        fallback_state = False

    monkeypatch.setattr(decider, "start_fallback", _start)
    monkeypatch.setattr(decider, "stop_fallback", _stop)

    logs = []

    def _log_event(component, message):
        logs.append((component, message))

    monkeypatch.setattr(decider, "log_event", _log_event)

    def _sleep(_seconds):
        try:
            _advance()
        except StopIteration as exc:
            raise StopLoop() from exc

    monkeypatch.setattr(decider.time, "sleep", _sleep)

    monkeypatch.setattr(decider, "context", decider.DeciderContext())

    with pytest.raises(StopLoop):
        decider.main()

    return {
        "logs": logs,
        "start_calls": len(start_calls),
        "stop_calls": len(stop_calls),
        "fallback_state": fallback_state,
    }


def _extract_decision_fields(result):
    decision_messages = [
        message for _component, message in result["logs"] if message.startswith("decision_csv=")
    ]
    assert decision_messages, "No decision log entry captured"
    payload = decision_messages[-1].split("=", 1)[1]
    parts = payload.split(",", 5)
    if len(parts) < 6:
        parts.extend([""] * (6 - len(parts)))
    return parts


def test_daytime_primary_ok_stops_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "good", "note": ""},
            "hour": 10,
            "fallback_active": True,
        }
        for _ in range(decider.STOP_OK_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["stop_calls"] == 1
    assert result["start_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "STOP secondary"
    assert fields[5] == "day primary OK"


def test_daytime_primary_warning_stops_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "warning", "note": ""},
            "hour": 9,
            "fallback_active": True,
        }
        for _ in range(decider.STOP_OK_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["stop_calls"] == 1
    assert result["start_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "STOP secondary"
    assert fields[5] == "day primary OK"


def test_daytime_without_primary_starts_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "?", "health": "bad", "note": "sem primário"},
            "hour": 11,
            "fallback_active": False,
        }
        for _ in range(decider.START_BAD_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["start_calls"] == 1
    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "START secondary"
    assert fields[5] == "day but no primary"


def test_daytime_stream_error_starts_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "error", "health": "bad", "note": ""},
            "hour": 10,
            "fallback_active": False,
        }
        for _ in range(decider.START_BAD_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["start_calls"] == 1
    fields = _extract_decision_fields(result)
    assert fields[4] == "START secondary"
    assert fields[5] == "day but no primary"


def test_daytime_health_revoked_starts_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "revoked", "note": ""},
            "hour": 10,
            "fallback_active": False,
        }
        for _ in range(decider.START_BAD_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["start_calls"] == 1
    fields = _extract_decision_fields(result)
    assert fields[4] == "START secondary"
    assert fields[5] == "day but no primary"


def test_daytime_warning_does_not_start_secondary(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "warning", "note": ""},
            "hour": 13,
            "fallback_active": False,
        }
        for _ in range(decider.START_BAD_STREAK)
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["start_calls"] == 0
    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "KEEP"
    assert "aguardar" in fields[5]


def test_night_without_primary_starts_secondary(monkeypatch):
    result = run_cycles(
        monkeypatch,
        [
            {
                "state": {"streamStatus": "inactive", "health": "noData", "note": ""},
                "hour": 2,
                "fallback_active": False,
            }
        ],
    )

    assert result["start_calls"] == 1
    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "START secondary"
    assert fields[5] == "night – force secondary on"


def test_night_with_healthy_primary_keeps_state(monkeypatch):
    result = run_cycles(
        monkeypatch,
        [
            {
                "state": {"streamStatus": "active", "health": "good", "note": ""},
                "hour": 22,
                "fallback_active": True,
            }
        ],
    )

    assert result["start_calls"] == 0
    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "KEEP"
    assert fields[5] == "night – force secondary on"


def test_daytime_primary_needs_hysteresis(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "good", "note": ""},
            "hour": 12,
            "fallback_active": True,
        },
        {
            "state": {"streamStatus": "active", "health": "good", "note": ""},
            "hour": 12,
        },
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "KEEP"
    assert "aguardar ok streak" in fields[5]


def test_primary_flap_does_not_toggle(monkeypatch):
    scenarios = [
        {
            "state": {"streamStatus": "active", "health": "good", "note": ""},
            "hour": 14,
            "fallback_active": False,
        },
        {
            "state": {"streamStatus": "?", "health": "bad", "note": "instável"},
            "hour": 14,
        },
        {
            "state": {"streamStatus": "active", "health": "ok", "note": ""},
            "hour": 14,
        },
    ]

    result = run_cycles(monkeypatch, scenarios)

    assert result["start_calls"] == 0
    assert result["stop_calls"] == 0
    fields = _extract_decision_fields(result)
    assert fields[4] == "KEEP"
    assert "aguardar" in fields[5]
