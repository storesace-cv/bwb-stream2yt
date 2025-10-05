import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "secondary-droplet"
    / "bin"
    / "yt_decider_daemon.py"
)
SPEC = importlib.util.spec_from_file_location("_yt_decider_daemon_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_yt_decider_daemon_test"] = module
SPEC.loader.exec_module(module)


def test_night_cycle_forces_secondary_start(monkeypatch):
    module.context.primary_ok_streak = 0
    module.context.primary_bad_streak = 0

    fallback_state = {"active": False}
    actions: list[str] = []
    decisions: list[dict[str, str]] = []

    monkeypatch.setattr(module, "build_api", lambda: object())
    monkeypatch.setattr(
        module,
        "get_state",
        lambda yt: {"streamStatus": "active", "health": "good", "note": ""},
    )
    monkeypatch.setattr(module, "local_hour", lambda: 2)
    monkeypatch.setattr(module, "log_event", lambda *args, **kwargs: None)

    def fake_is_active(unit: str) -> bool:
        assert unit == "youtube-fallback.service"
        return fallback_state["active"]

    def fake_start_fallback() -> None:
        actions.append("start")
        fallback_state["active"] = True

    def fake_log_cycle_decision(**kwargs) -> None:
        decisions.append(kwargs)

    monkeypatch.setattr(module, "is_active", fake_is_active)
    monkeypatch.setattr(module, "start_fallback", fake_start_fallback)
    monkeypatch.setattr(module, "log_cycle_decision", fake_log_cycle_decision)

    def raise_on_sleep(_seconds: float) -> None:
        raise SystemExit

    monkeypatch.setattr(module.time, "sleep", raise_on_sleep)

    with pytest.raises(SystemExit):
        module.main()

    assert actions == ["start"]
    assert decisions
    assert decisions[-1]["action"] == "START secondary"
    assert decisions[-1]["detail"] == "night – force secondary on"
