"""Opções de lançamento de subprocessos FFmpeg/FFprobe sem janela no Windows."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict


def hidden_process_kwargs(*, platform: str | None = None) -> Dict[str, Any]:
    """Devolve kwargs para ``subprocess.Popen``/``run`` sem consola no Windows.

    Fora do Windows devolve um dicionário vazio. No Windows prefere
    ``CREATE_NO_WINDOW`` e ``STARTUPINFO`` com ``SW_HIDE``.
    """

    current = sys.platform if platform is None else platform
    if not current.startswith("win"):
        return {}

    kwargs: Dict[str, Any] = {}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startf_use = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        sw_hide = getattr(subprocess, "SW_HIDE", 0)
        if startf_use:
            startupinfo.dwFlags |= startf_use
        # SW_HIDE = 0; atribuir explicitamente para garantir ocultação.
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo

    return kwargs
