#!/usr/bin/env python3
"""Launcher do executável Windows da interface stream2yt-ui."""

from __future__ import annotations

import sys

from stream_to_youtube import _ensure_signal_handlers
from ui_app import run_ui_app


def main() -> None:
    _ensure_signal_handlers()
    raise SystemExit(run_ui_app())


if __name__ == "__main__":
    main()
