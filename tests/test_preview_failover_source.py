"""A troca de preview deve parar a sessão anterior antes da seguinte."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ui_app import replace_active_preview  # noqa: E402


def test_replace_active_preview_never_keeps_two_sessions() -> None:
    active: set[str] = {"camera"}
    stops: list[str] = []

    class Session:
        def __init__(self, name: str) -> None:
            self.name = name

        def start(self) -> None:
            active.add(self.name)
            assert len(active) == 1

        def stop(self, timeout: float) -> None:
            stops.append(self.name)
            active.discard(self.name)

    holder = {"session": Session("camera")}
    result = replace_active_preview(
        threading.Lock(), holder, build_session=lambda: Session("contingency_demo")
    )
    assert stops == ["camera"]
    assert result is holder["session"]
    assert active == {"contingency_demo"}
