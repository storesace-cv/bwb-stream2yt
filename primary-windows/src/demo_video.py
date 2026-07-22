"""Fonte de vídeo de demonstração (MP4 em loop) para a UI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Mapping, Optional

DEFAULT_DEMO_VIDEO_PATH = (
    r"C:\bwb\apps\youtube\demo\bbb_sunflower_1080p_30fps_normal.mp4"
)
DEMO_VIDEO_ENV = "BWB_DEMO_VIDEO"
DEMO_CAMERA_STATUS = "Vídeo de demonstração"


def resolve_demo_video_path(
    *,
    explicit: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve o caminho do MP4 de demonstração (explicit > env > default)."""

    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    env = environ if environ is not None else os.environ
    override = str(env.get(DEMO_VIDEO_ENV, "") or "").strip()
    if override:
        return override
    return DEFAULT_DEMO_VIDEO_PATH


def build_demo_input_args(video_path: Optional[str] = None) -> List[str]:
    """Argumentos FFmpeg de entrada para reproduzir o MP4 em loop a tempo real."""

    path = resolve_demo_video_path(explicit=video_path)
    return [
        "-stream_loop",
        "-1",
        "-re",
        "-i",
        path,
    ]


def demo_video_missing_message(video_path: Optional[str] = None) -> str:
    path = resolve_demo_video_path(explicit=video_path)
    return f"Vídeo de demonstração não encontrado: {path}"


def demo_video_exists(video_path: Optional[str] = None) -> bool:
    path = resolve_demo_video_path(explicit=video_path)
    try:
        return Path(path).is_file()
    except OSError:
        return False
