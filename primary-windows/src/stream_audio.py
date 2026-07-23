"""Modos de áudio da transmissão principal (UI), sem alterar .env."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, replace
from typing import Any, Callable, List, Optional, Sequence

from process_launch import hidden_process_kwargs

AUDIO_MODE_SILENT = "silent"
AUDIO_MODE_SOURCE = "source"
DEFAULT_AUDIO_MODE = AUDIO_MODE_SILENT

NO_AUDIO_AVAILABLE_MESSAGE = "A fonte selecionada não tem áudio disponível."
AUDIO_PROBE_FAILED_MESSAGE = "Não foi possível analisar o áudio da fonte."

_ANULLSRC = "anullsrc=channel_layout=stereo:sample_rate=44100"
_FFMPEG_ONLY_FLAGS = {"-stream_loop", "-re"}
_LAVFI_MARKERS = ("lavfi", "anullsrc")
_RTSP_CREDENTIAL_RE = re.compile(r"(?i)(\w+://)([^:/\s@]+):([^@\s]+)@")


def _sanitize_detail(value: str) -> str:
    """Mascara credenciais que o ffprobe possa repetir no stderr."""

    return _RTSP_CREDENTIAL_RE.sub(r"\1\2:***@", value)


@dataclass(frozen=True)
class AudioProbeResult:
    ok: bool
    has_audio: bool
    error_kind: Optional[str] = None
    sanitized_detail: Optional[str] = None


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


def build_ffprobe_input_args(input_args: Sequence[str]) -> List[str]:
    """Argumentos aceites pelo ffprobe (sem flags exclusivas do FFmpeg)."""

    cleaned: List[str] = []
    skip_next = False
    for index, raw in enumerate(input_args):
        if skip_next:
            skip_next = False
            continue
        token = str(raw)
        lower = token.lower()
        if token in _FFMPEG_ONLY_FLAGS:
            if token == "-stream_loop" and index + 1 < len(input_args):
                skip_next = True
            continue
        if token == "-f" and index + 1 < len(input_args):
            nxt = str(input_args[index + 1]).lower()
            if any(marker in nxt for marker in _LAVFI_MARKERS) or nxt == "lavfi":
                skip_next = True
                continue
        if any(marker in lower for marker in _LAVFI_MARKERS):
            if cleaned and cleaned[-1] == "-i":
                cleaned.pop()
            continue
        cleaned.append(token)

    # Garantir que existe -i <fonte> e descartar entradas lavfi residuais após -i.
    result: List[str] = []
    i = 0
    while i < len(cleaned):
        token = cleaned[i]
        if token == "-i" and i + 1 < len(cleaned):
            target = cleaned[i + 1]
            if any(marker in target.lower() for marker in _LAVFI_MARKERS):
                i += 2
                continue
            result.extend(["-i", target])
            i += 2
            continue
        result.append(token)
        i += 1
    return result


def probe_input_has_audio(
    ffprobe: str,
    input_args: Sequence[str],
    *,
    timeout: float = 10.0,
    run: Callable[..., Any] = subprocess.run,
) -> AudioProbeResult:
    """Analisa a fonte com ffprobe e distingue ausência de áudio de erros."""

    probe = (ffprobe or "").strip() or "ffprobe"
    probe_args = build_ffprobe_input_args(input_args)
    if not probe_args or "-i" not in probe_args:
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind="bad_args",
            sanitized_detail="argumentos de entrada inválidos para ffprobe",
        )

    cmd = [
        probe,
        "-v",
        "error",
        *probe_args,
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
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind="ffprobe_missing",
            sanitized_detail="ffprobe não encontrado",
        )
    except subprocess.TimeoutExpired:
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind="timeout",
            sanitized_detail=f"ffprobe excedeu {timeout:.1f}s",
        )
    except Exception as exc:  # noqa: BLE001
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind="unknown",
            sanitized_detail=exc.__class__.__name__,
        )

    code = int(getattr(completed, "returncode", 1) or 0)
    stderr = (getattr(completed, "stderr", None) or "").strip()
    if code != 0:
        detail = _sanitize_detail(stderr[:160] if stderr else f"exit {code}")
        lowered = detail.lower()
        kind = (
            "connect_failed"
            if any(
                token in lowered
                for token in ("connection", "timed out", "401", "403", "404")
            )
            else "bad_args"
        )
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind=kind,
            sanitized_detail=detail,
        )

    try:
        payload = json.loads(getattr(completed, "stdout", None) or "{}")
    except json.JSONDecodeError:
        return AudioProbeResult(
            ok=False,
            has_audio=False,
            error_kind="unknown",
            sanitized_detail="json inválido do ffprobe",
        )

    streams = payload.get("streams")
    if not isinstance(streams, list):
        return AudioProbeResult(ok=True, has_audio=False, error_kind="no_audio")

    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            return AudioProbeResult(ok=True, has_audio=True, error_kind=None)
    return AudioProbeResult(ok=True, has_audio=False, error_kind="no_audio")


def apply_audio_mode_to_config(config: Any, mode: Optional[str]) -> Any:
    """Aplica modo de áudio a StreamingConfig (output/maps), sem alterar a fonte."""

    normalized = normalize_audio_mode(mode)
    if normalized == AUDIO_MODE_SOURCE:
        result = probe_input_has_audio(
            getattr(getattr(config, "camera_probe", None), "ffprobe", "") or "",
            list(config.input_args),
            timeout=min(
                3.0,
                float(
                    getattr(getattr(config, "camera_probe", None), "timeout", 7.0)
                    or 7.0
                ),
            ),
        )
        if result.ok and not result.has_audio:
            raise ValueError(NO_AUDIO_AVAILABLE_MESSAGE)
        if not result.ok:
            raise ValueError(AUDIO_PROBE_FAILED_MESSAGE)
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
