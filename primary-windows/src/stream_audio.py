"""Modos de áudio da transmissão principal (UI), sem alterar .env."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from typing import Any, Callable, List, Optional, Sequence

from process_launch import hidden_process_kwargs

AUDIO_MODE_SILENT = "silent"
AUDIO_MODE_SOURCE = "source"
DEFAULT_AUDIO_MODE = AUDIO_MODE_SILENT

NO_AUDIO_AVAILABLE_MESSAGE = "A fonte selecionada não tem áudio disponível."

_ANULLSRC = "anullsrc=channel_layout=stereo:sample_rate=44100"


def normalize_audio_mode(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in {AUDIO_MODE_SOURCE, "com", "com_audio", "source", "with"}:
        return AUDIO_MODE_SOURCE
    return AUDIO_MODE_SILENT


def audio_mode_label(mode: Optional[str]) -> str:
    if normalize_audio_mode(mode) == AUDIO_MODE_SOURCE:
        return "Com áudio"
    return "Sem áudio"


def build_silent_audio_input_args() -> List[str]:
    return ["-f", "lavfi", "-i", _ANULLSRC]


def build_audio_map_args(*, silent: bool) -> List[str]:
    if silent:
        return ["-map", "0:v:0", "-map", "1:a:0"]
    return ["-map", "0:v:0", "-map", "0:a:0"]


def _strip_flag_and_value(args: List[str], flag: str) -> None:
    while True:
        try:
            index = args.index(flag)
        except ValueError:
            return
        del args[index]
        if index < len(args) and not str(args[index]).startswith("-"):
            del args[index]


def strip_map_args(args: Sequence[str]) -> List[str]:
    updated = list(args)
    _strip_flag_and_value(updated, "-map")
    return updated


def ensure_aac_audio_output_args(output_args: Sequence[str]) -> List[str]:
    """Garante AAC 44.1 kHz stereo 128k nos argumentos de saída."""

    updated = list(output_args)

    def _set(flag: str, value: str) -> None:
        try:
            index = updated.index(flag)
        except ValueError:
            updated.extend([flag, value])
            return
        if index + 1 < len(updated):
            updated[index + 1] = value
        else:
            updated.append(value)

    _set("-c:a", "aac")
    _set("-b:a", "128k")
    _set("-ar", "44100")
    _set("-ac", "2")
    return updated


def build_audio_aware_output_args(
    output_args: Sequence[str], *, silent: bool
) -> List[str]:
    cleaned = strip_map_args(output_args)
    if silent:
        _strip_flag_and_value(cleaned, "-filter:a")
        _strip_flag_and_value(cleaned, "-af")
    maps = build_audio_map_args(silent=silent)
    return maps + ensure_aac_audio_output_args(cleaned)


def probe_input_has_audio(
    ffprobe: str,
    input_args: Sequence[str],
    *,
    timeout: float = 10.0,
    run: Callable[..., Any] = subprocess.run,
) -> bool:
    """Devolve True se ffprobe reportar pelo menos uma faixa de áudio."""

    probe = (ffprobe or "").strip() or "ffprobe"
    cmd = [
        probe,
        "-v",
        "error",
        *list(input_args),
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
    ]
    try:
        completed = run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            **hidden_process_kwargs(),
        )
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return False

    if int(getattr(completed, "returncode", 1) or 0) != 0:
        return False
    try:
        payload = json.loads(getattr(completed, "stdout", None) or "{}")
    except json.JSONDecodeError:
        return False
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return False
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            return True
    return False


def apply_audio_mode_to_config(config: Any, mode: Optional[str]) -> Any:
    """Aplica modo de áudio a StreamingConfig (output/maps), sem alterar a fonte.

    ``config.input_args`` continua a representar apenas a câmara ou o MP4.
    O ``anullsrc`` é acrescentado só em ``build_effective_ffmpeg_input_args``.

    Em modo fonte, exige faixa de áudio na entrada; caso contrário levanta
    ``ValueError`` com mensagem orientada ao utilizador.
    """

    normalized = normalize_audio_mode(mode)
    if normalized == AUDIO_MODE_SOURCE:
        has_audio = probe_input_has_audio(
            getattr(getattr(config, "camera_probe", None), "ffprobe", "") or "",
            list(config.input_args),
            timeout=float(
                getattr(getattr(config, "camera_probe", None), "timeout", 7.0) or 7.0
            ),
        )
        if not has_audio:
            raise ValueError(NO_AUDIO_AVAILABLE_MESSAGE)
        output_args = build_audio_aware_output_args(config.output_args, silent=False)
        return replace(
            config,
            output_args=output_args,
            audio_mode=normalized,
            audio_detected=True,
        )

    output_args = build_audio_aware_output_args(config.output_args, silent=True)
    return replace(
        config,
        output_args=output_args,
        audio_mode=normalized,
        audio_detected=False,
    )


def build_effective_ffmpeg_input_args(config: Any) -> List[str]:
    """Entradas efetivas do FFmpeg principal (fonte + anullsrc se silent)."""

    args = list(getattr(config, "input_args", []) or [])
    mode = getattr(config, "audio_mode", None)
    if mode is None:
        return args
    if normalize_audio_mode(mode) == AUDIO_MODE_SILENT:
        return args + build_silent_audio_input_args()
    return args
