#!/usr/bin/env python3
# stream_to_youtube.py — Windows primary sender (one-file capable)
# - Keeps process alive 24/7 but only transmits during day-part window if desired.
# - Robust ffmpeg process handling and auto-restarts on error.
# - Default input is RTSP; change to dshow as needed.

import atexit
import datetime
import json
import os
import platform
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from autotune import estimate_upload_bitrate


DEFAULT_STATUS_ENDPOINT = "http://104.248.134.44:8080/status"
APP_VERSION = "2024.09"
HEARTBEAT_USER_AGENT = f"BWBPrimary/{APP_VERSION}"
HEARTBEAT_DEFAULT_LOG_RELATIVE = "logs/heartbeat-status.jsonl"


ENV_TEMPLATE_CONTENT = """# Configurações para stream_to_youtube.py
# Copie este arquivo para ".env" ou deixe que o script gere um automaticamente e depois personalize.

# Chave do YouTube Live. Se preenchida, a URL final será gerada automaticamente.
#YT_KEY=SEU_CODIGO_DO_YOUTUBE

# URL completa do ingest RTMP. Use se preferir definir manualmente em vez da chave.
#YT_URL=rtmps://a.rtmps.youtube.com/live2/SEU_CODIGO_DO_YOUTUBE

# Parâmetros de entrada para o ffmpeg. Ajuste o endereço RTSP conforme necessário.
#YT_INPUT_ARGS=-rtsp_transport tcp -rtsp_flags prefer_tcp -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 -i rtsp://USUARIO:SenhaFort3@10.0.254.50:554/Streaming/Channels/101

# Também é possível deixar `YT_INPUT_ARGS` vazio e informar as variáveis abaixo para montar
# automaticamente a URL RTSP. Todas são opcionais e só são utilizadas quando `YT_INPUT_ARGS`
# permanecer em branco.
#RTSP_HOST=10.0.254.50
#RTSP_PORT=554
#RTSP_PATH=Streaming/Channels/101
#RTSP_USERNAME=USUARIO
#RTSP_PASSWORD=SenhaFort3

# Parâmetros de saída para o ffmpeg. Utilize para alterar codec, bitrate ou filtros.
#YT_OUTPUT_ARGS=-vf scale=1920:1080:flags=bicubic:in_range=pc:out_range=tv,format=yuv420p -r 30 -c:v libx264 -preset veryfast -profile:v high -level 4.2 -b:v 4500k -pix_fmt yuv420p -g 60 -c:a aac -b:a 128k -ar 44100 -f flv

# Ative o ajuste automático de bitrate (requer psutil) para medir a banda de upload.
#YT_AUTOTUNE=1
# Intervalo, em segundos, entre medições consecutivas.
#YT_AUTOTUNE_INTERVAL=8
# Limites (em kbps) utilizados pelo ajuste automático de bitrate.
#YT_BITRATE_MIN=2500
#YT_BITRATE_MAX=6000
# Margem de segurança aplicada sobre a banda medida (0.0 a 1.0).
#YT_AUTOTUNE_SAFETY=0.75

# Caminho para o executável ffmpeg. Deixe vazio para usar o ffmpeg no PATH.
#FFMPEG=C:\\caminho\\para\\ffmpeg.exe

# Configurações do heartbeat/status para comunicar com a droplet secundária.
#BWB_STATUS_ENABLED=1
#BWB_STATUS_ENDPOINT=http://104.248.134.44:8080/status
#BWB_STATUS_INTERVAL=20
#BWB_STATUS_TIMEOUT=5
#BWB_STATUS_MACHINE_ID=BEACHCAM-PRIMARY
#BWB_STATUS_TOKEN=
#BWB_STATUS_LOG_FILE=logs/heartbeat-status.jsonl
#BWB_STATUS_LOG_RETENTION_SECONDS=3600
"""


def _script_base_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller one-file executables
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _minimize_console_window() -> None:
    """Minimize the Windows console without stealing focus."""

    if os.name != "nt":
        return

    with suppress(Exception):
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return

        SW_SHOWMINNOACTIVE = 7
        user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)

        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        width, height = 320, 200
        HWND_TOP = 0
        user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            0,
            0,
            width,
            height,
            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOZORDER,
        )


def _resolve_log_target() -> tuple[Path, str, str]:
    """Determine the directory, stem and suffix for daily log files."""

    script_dir = _script_base_dir()
    raw_path = os.environ.get("BWB_LOG_FILE", "").strip()

    if raw_path:
        expanded = os.path.expandvars(raw_path)
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = (script_dir / candidate).resolve()
    else:
        candidate = script_dir / "logs" / "bwb_services.log"

    directory = candidate.parent if candidate.parent else script_dir / "logs"
    suffix = candidate.suffix or ".log"
    stem = candidate.stem or "bwb_services"
    return directory, stem, suffix


def _resolve_custom_path(env_name: str, default_relative: str) -> Path:
    script_dir = _script_base_dir()
    raw_path = os.environ.get(env_name, "").strip()

    if raw_path:
        expanded = os.path.expandvars(raw_path)
        candidate = Path(expanded).expanduser()
        if not candidate.is_absolute():
            candidate = (script_dir / candidate).resolve()
        return candidate

    return (script_dir / default_relative).resolve()


LOG_DIR, LOG_STEM, LOG_SUFFIX = _resolve_log_target()
LOG_PATTERN = f"{LOG_STEM}-*.log"
LOG_RETENTION_DAYS = 7

_PID_FILE_NAME = "stream_to_youtube.pid"
_STOP_SENTINEL_NAME = "stream_to_youtube.stop"
_SIGNAL_HANDLERS_INSTALLED = False
_ACTIVE_WORKER: Optional["StreamingWorker"] = None
_CTRL_HANDLER_REF = None


def _pid_file_path() -> Path:
    return _script_base_dir() / _PID_FILE_NAME


def _stop_sentinel_path() -> Path:
    return _script_base_dir() / _STOP_SENTINEL_NAME


def _read_pid_file(path: Optional[Path] = None) -> Optional[int]:
    if path is None:
        path = _pid_file_path()
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        return int(content)
    except ValueError:
        return None


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        with suppress(Exception):
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            error_code = ctypes.get_last_error()
            if error_code == 5:  # ACCESS_DENIED
                return True
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _claim_pid_file() -> None:
    path = _pid_file_path()
    existing_pid = _read_pid_file(path)
    if existing_pid and _is_pid_running(existing_pid):
        raise RuntimeError(
            f"Já existe uma instância ativa (PID {existing_pid}). Utilize /stop antes de reiniciar."
        )

    with suppress(OSError):
        path.unlink()

    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(str(os.getpid()), encoding="utf-8")
    os.replace(tmp_path, path)
    log_event("primary", f"Registrado PID {os.getpid()} em {path}")


def _release_pid_file(expected_pid: Optional[int] = None) -> None:
    path = _pid_file_path()
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return

    try:
        recorded_pid = int(content)
    except ValueError:
        recorded_pid = None

    if expected_pid is None:
        expected_pid = os.getpid()

    if recorded_pid is not None and recorded_pid != expected_pid:
        return

    with suppress(OSError):
        path.unlink()
        log_event("primary", f"Registro de PID removido de {path}")


def _handle_shutdown_signal(signum, _frame) -> None:
    log_event("primary", f"Sinal {signum} recebido; encerrando worker.")
    worker = _ACTIVE_WORKER
    if worker:
        worker.stop()


def _install_console_control_guards() -> None:
    global _CTRL_HANDLER_REF

    sigint = getattr(signal, "SIGINT", None)
    if sigint is not None:
        try:
            signal.signal(sigint, signal.SIG_IGN)
        except (OSError, RuntimeError, ValueError):
            pass

    if os.name != "nt":
        return

    try:
        import ctypes

        HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        ignored_events = {0, 2}  # CTRL_C_EVENT, CTRL_CLOSE_EVENT

        def handler(ctrl_type: int) -> bool:
            return ctrl_type in ignored_events

        handler_ref = HandlerRoutine(handler)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not kernel32.SetConsoleCtrlHandler(handler_ref, True):
            raise ctypes.WinError()
        _CTRL_HANDLER_REF = handler_ref
    except Exception:
        _CTRL_HANDLER_REF = None


def _ensure_signal_handlers() -> None:
    global _SIGNAL_HANDLERS_INSTALLED
    if _SIGNAL_HANDLERS_INSTALLED:
        return

    _install_console_control_guards()

    handled = [sig for sig in (getattr(signal, "SIGTERM", None),) if sig]
    if os.name == "nt" and hasattr(signal, "SIGBREAK"):
        handled.append(signal.SIGBREAK)  # type: ignore[attr-defined]

    for sig in handled:
        signal.signal(sig, _handle_shutdown_signal)

    _SIGNAL_HANDLERS_INSTALLED = True


atexit.register(_release_pid_file)


def _stop_request_active() -> bool:
    path = _stop_sentinel_path()
    try:
        return path.exists()
    except OSError:
        return False


def _clear_stop_request() -> None:
    path = _stop_sentinel_path()
    with suppress(OSError):
        path.unlink()


def _request_stop_via_sentinel() -> bool:
    path = _stop_sentinel_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    try:
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        return False
    return True


def _current_log_file(now: datetime.datetime | None = None) -> Path:
    if now is None:
        now = datetime.datetime.utcnow()
    filename = f"{LOG_STEM}-{now.strftime('%Y-%m-%d')}{LOG_SUFFIX}"
    return LOG_DIR / filename


def prune_old_logs(active_file: Path | None = None) -> None:
    """Remove log files older than the retention window."""

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    cutoff_ts = time.time() - (LOG_RETENTION_DAYS * 24 * 60 * 60)
    try:
        candidates = list(LOG_DIR.glob(LOG_PATTERN))
    except OSError:
        return

    for path in candidates:
        try:
            if active_file is not None and path.resolve() == active_file.resolve():
                continue
            if path.stat().st_mtime < cutoff_ts:
                path.unlink()
        except OSError:
            continue


def log_event(component: str, message: str) -> None:
    """Append a timestamped entry to the shared services log."""

    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} [{component}] {message}\n"
    log_file = _current_log_file()

    prune_old_logs(active_file=log_file)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    try:
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        # Logging should never interrupt the streaming loop.
        pass


def _load_env_template(base_dir: Path) -> str:
    template_path = base_dir / ".env.example"
    try:
        content = template_path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        return content
    except OSError:
        content = ENV_TEMPLATE_CONTENT
        if not content.endswith("\n"):
            content += "\n"
        return content


def _ensure_env_file() -> None:
    base_dir = _script_base_dir()
    env_path = base_dir / ".env"

    if env_path.exists():
        return

    template_content = _load_env_template(base_dir)

    try:
        env_path.write_text(template_content, encoding="utf-8")
    except OSError as exc:
        error_message = f"Falha ao criar .env automaticamente ({exc})."
        print(f"[primary] {error_message}", file=sys.stderr)
        log_event("primary", error_message)
        return

    message = (
        f"Arquivo .env criado automaticamente em {env_path}. "
        "Edite os campos destacados antes de transmitir."
    )
    print(f"[primary] {message}")
    log_event("primary", message)


def _load_env_files():
    """Populate os.environ with values from nearby .env files."""
    script_dir = _script_base_dir()
    env_paths = [
        script_dir / ".env",
        script_dir.parent / ".env",
        Path.cwd() / ".env",
    ]

    seen = set()
    for path in env_paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if len(value) >= 2 and (
                        (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
                    ):
                        value = value[1:-1]
                    os.environ.setdefault(key, value)
        except OSError:
            continue


def _resolve_yt_url() -> Optional[str]:
    url = os.environ.get("YT_URL", "").strip()
    if url:
        return url

    key = os.environ.get("YT_KEY", "").strip()
    if key:
        return f"rtmps://a.rtmps.youtube.com/live2/{key}"

    return None


# === CONFIG (edit if needed) ===
# FFmpeg input/output (example: RTSP)


_DEFAULT_INPUT_ARGS = [
    "-rtsp_transport",
    "tcp",
    "-rtsp_flags",
    "prefer_tcp",
    "-fflags",
    "nobuffer",
    "-flags",
    "low_delay",
    "-use_wallclock_as_timestamps",
    "1",
    "-i",
    "rtsp://BEACHCAM:QueriasEntrar123@10.0.254.50:554/Streaming/Channels/101",
]


def _default_input_args() -> list[str]:
    return list(_DEFAULT_INPUT_ARGS)


@dataclass(frozen=True)
class ResolutionPreset:
    width: int
    height: int
    bitrate_kbps: int
    maxrate_kbps: int
    bufsize_kbps: int


_RESOLUTION_PRESETS: dict[str, ResolutionPreset] = {
    "360p": ResolutionPreset(
        width=640, height=360, bitrate_kbps=1000, maxrate_kbps=1500, bufsize_kbps=3000
    ),
    "720p": ResolutionPreset(
        width=1280, height=720, bitrate_kbps=3500, maxrate_kbps=4500, bufsize_kbps=9000
    ),
    "1080p": ResolutionPreset(
        width=1920,
        height=1080,
        bitrate_kbps=5000,
        maxrate_kbps=6000,
        bufsize_kbps=12000,
    ),
}

_DEFAULT_RESOLUTION = "1080p"


def _normalize_resolution(value: str) -> Optional[str]:
    normalized = value.strip().lower()
    if normalized in _RESOLUTION_PRESETS:
        return normalized
    return None


def _apply_resolution_preset(args: list[str], resolution: str) -> list[str]:
    preset = _RESOLUTION_PRESETS[resolution]
    updated = list(args)
    filter_value = (
        f"scale={preset.width}:{preset.height}:"
        "flags=bicubic:in_range=pc:out_range=tv,format=yuv420p"
    )
    _set_arg_value(updated, "-vf", filter_value)
    _set_arg_value(updated, "-r", "30")
    _set_arg_value(updated, "-b:v", f"{preset.bitrate_kbps}k")
    _set_arg_value(updated, "-maxrate", f"{preset.maxrate_kbps}k")
    _set_arg_value(updated, "-bufsize", f"{preset.bufsize_kbps}k")
    return updated


def _split_args(value: str, default: list[str]) -> list[str]:
    value = value.strip()
    if not value:
        return default
    return shlex.split(value)


def _build_rtsp_url_from_env() -> Optional[str]:
    host = os.environ.get("RTSP_HOST", "").strip()
    path = os.environ.get("RTSP_PATH", "").strip()

    if not host or not path:
        return None

    username = os.environ.get("RTSP_USERNAME", "").strip()
    password = os.environ.get("RTSP_PASSWORD", "").strip()
    port = os.environ.get("RTSP_PORT", "").strip()

    credentials = ""
    if username:
        credentials = username
        if password:
            credentials += f":{password}"
        credentials += "@"
    elif password:
        # Não é possível utilizar senha sem usuário; caia para o padrão.
        return None

    authority = host
    if port:
        authority = f"{authority}:{port}"

    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"rtsp://{credentials}{authority}{normalized_path}"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _parse_bitrate_from_args(args: list[str], flag: str) -> Optional[int]:
    try:
        index = args.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    value = args[index + 1].strip()
    if value.endswith("k"):
        value = value[:-1]
    try:
        return int(value)
    except ValueError:
        return None


def _extract_arg_value(args: list[str], flag: str) -> Optional[str]:
    try:
        index = args.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _set_arg_value(args: list[str], flag: str, value: str) -> None:
    try:
        index = args.index(flag)
    except ValueError:
        args.extend([flag, value])
        return
    if index + 1 >= len(args):
        args.append(value)
    else:
        args[index + 1] = value


_PRESET_ORDER = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]


def _recommended_preset(bitrate_kbps: int) -> Optional[str]:
    if bitrate_kbps >= 5500:
        return "veryfast"
    if bitrate_kbps >= 4000:
        return "veryfast"
    if bitrate_kbps >= 3000:
        return "faster"
    if bitrate_kbps >= 2200:
        return "fast"
    if bitrate_kbps >= 1600:
        return "medium"
    return "slow"


def _select_preset(base_preset: Optional[str], bitrate_kbps: int) -> Optional[str]:
    recommended = _recommended_preset(bitrate_kbps)
    if recommended is None:
        return base_preset

    if base_preset is None:
        return recommended

    try:
        base_index = _PRESET_ORDER.index(base_preset)
    except ValueError:
        return recommended

    try:
        recommended_index = _PRESET_ORDER.index(recommended)
    except ValueError:
        return base_preset

    if recommended_index <= base_index:
        return base_preset

    allowed_index = min(recommended_index, base_index + 2)
    return _PRESET_ORDER[allowed_index]


@dataclass(frozen=True)
class HeartbeatConfig:
    enabled: bool
    endpoint: Optional[str]
    interval: float
    timeout: float
    machine_id: str
    token: Optional[str]
    log_path: Path
    log_retention_seconds: int


@dataclass(frozen=True)
class StreamingConfig:
    yt_url: Optional[str]
    input_args: list[str]
    output_args: list[str]
    resolution: str
    ffmpeg: str
    day_start_hour: int
    day_end_hour: int
    tz_offset_hours: int
    autotune_enabled: bool
    bitrate_min_kbps: int
    bitrate_max_kbps: int
    autotune_interval: float
    autotune_safety_margin: float
    heartbeat: HeartbeatConfig


def _resolve_heartbeat_config(base_dir: Path) -> HeartbeatConfig:
    enabled_flag = _env_flag("BWB_STATUS_ENABLED", True)
    endpoint_raw = os.environ.get("BWB_STATUS_ENDPOINT")
    endpoint = (endpoint_raw or DEFAULT_STATUS_ENDPOINT).strip()

    if not endpoint:
        enabled_flag = False
        endpoint_value: Optional[str] = None
    else:
        endpoint_value = endpoint

    interval = _env_float("BWB_STATUS_INTERVAL", 20.0)
    if interval < 5.0:
        interval = 5.0

    timeout = _env_float("BWB_STATUS_TIMEOUT", 5.0)
    if timeout <= 0:
        timeout = 5.0
    if timeout >= interval:
        timeout = max(1.0, interval / 2)

    retention = _env_int("BWB_STATUS_LOG_RETENTION_SECONDS", 3600)
    if retention <= 0:
        retention = 3600
    retention = max(retention, int(interval * 4))

    machine_id_raw = os.environ.get("BWB_STATUS_MACHINE_ID", "").strip()
    if machine_id_raw:
        machine_id = machine_id_raw
    else:
        node = platform.node().strip()
        machine_id = node or "primary-sender"

    token_raw = os.environ.get("BWB_STATUS_TOKEN", "").strip()
    log_path = _resolve_custom_path(
        "BWB_STATUS_LOG_FILE", HEARTBEAT_DEFAULT_LOG_RELATIVE
    )

    return HeartbeatConfig(
        enabled=enabled_flag and endpoint_value is not None,
        endpoint=endpoint_value if enabled_flag else None,
        interval=interval,
        timeout=timeout,
        machine_id=machine_id,
        token=token_raw or None,
        log_path=log_path,
        log_retention_seconds=retention,
    )


def load_config(resolution: Optional[str] = None) -> StreamingConfig:
    _ensure_env_file()
    _load_env_files()

    raw_input_args = os.environ.get("YT_INPUT_ARGS", "")
    if raw_input_args.strip():
        input_args = shlex.split(raw_input_args)
    else:
        default_input_args = _default_input_args()
        rtsp_url = _build_rtsp_url_from_env()
        if rtsp_url:
            input_args = default_input_args[:-1] + [rtsp_url]
        else:
            input_args = default_input_args
    output_args = _split_args(
        os.environ.get("YT_OUTPUT_ARGS", ""),
        [
            "-vf",
            "scale=1920:1080:flags=bicubic:in_range=pc:out_range=tv,format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-profile:v",
            "high",
            "-level",
            "4.2",
            "-b:v",
            "5000k",
            "-maxrate",
            "6000k",
            "-bufsize",
            "12000k",
            "-g",
            "60",
            "-sc_threshold",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-filter:a",
            (
                "aresample=async=1:first_pts=0,"
                " aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
            ),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
        ],
    )

    resolved_resolution: Optional[str] = None
    if resolution is not None:
        normalized_resolution = _normalize_resolution(resolution)
        if normalized_resolution is None:
            log_event(
                "primary",
                f"Resolução inválida solicitada ({resolution}); aplicando {_DEFAULT_RESOLUTION}.",
            )
        else:
            resolved_resolution = normalized_resolution

    if resolved_resolution is None:
        env_resolution = os.environ.get("YT_RESOLUTION")
        if env_resolution:
            normalized_env = _normalize_resolution(env_resolution)
            if normalized_env is None:
                log_event(
                    "primary",
                    f"Valor inválido em YT_RESOLUTION ({env_resolution}); aplicando {_DEFAULT_RESOLUTION}.",
                )
            else:
                resolved_resolution = normalized_env

    if resolved_resolution is None:
        resolved_resolution = _DEFAULT_RESOLUTION

    output_args = _apply_resolution_preset(output_args, resolved_resolution)

    default_bitrate = _parse_bitrate_from_args(output_args, "-b:v") or 5000
    default_maxrate = _parse_bitrate_from_args(output_args, "-maxrate") or max(
        default_bitrate, 6000
    )

    bitrate_min = _env_int("YT_BITRATE_MIN", default_bitrate)
    bitrate_max = _env_int("YT_BITRATE_MAX", default_maxrate)
    if bitrate_min > bitrate_max:
        bitrate_min, bitrate_max = bitrate_max, bitrate_min

    safety_margin = _env_float("YT_AUTOTUNE_SAFETY", 0.75)
    if safety_margin < 0.0:
        safety_margin = 0.0
    elif safety_margin > 1.0:
        safety_margin = 1.0

    return StreamingConfig(
        yt_url=_resolve_yt_url(),
        input_args=input_args,
        output_args=output_args,
        resolution=resolved_resolution,
        ffmpeg=os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe"),
        day_start_hour=int(os.environ.get("YT_DAY_START_HOUR", "8")),
        day_end_hour=int(os.environ.get("YT_DAY_END_HOUR", "19")),
        tz_offset_hours=int(os.environ.get("YT_TZ_OFFSET_HOURS", "1")),
        autotune_enabled=_env_flag("YT_AUTOTUNE", False),
        bitrate_min_kbps=bitrate_min,
        bitrate_max_kbps=bitrate_max,
        autotune_interval=_env_float("YT_AUTOTUNE_INTERVAL", 8.0),
        autotune_safety_margin=safety_margin,
        heartbeat=_resolve_heartbeat_config(_script_base_dir()),
    )


def in_day_window(config: StreamingConfig, now_utc=None):
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()
    local = now_utc + datetime.timedelta(hours=config.tz_offset_hours)
    return config.day_start_hour <= local.hour < config.day_end_hour


class HeartbeatReporter:
    """Send periodic status reports to the secondary droplet."""

    def __init__(
        self,
        config: HeartbeatConfig,
        status_provider: Callable[[], Dict[str, Any]],
    ) -> None:
        self._config = config
        self._status_provider = status_provider
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self) -> None:
        if not self._config.enabled or not self._config.endpoint:
            return
        if self.is_running:
            return
        self._stop_event.clear()
        thread = threading.Thread(
            target=self._run_loop, name="HeartbeatReporter", daemon=True
        )
        self._thread = thread
        log_event(
            "primary-heartbeat",
            (
                "Heartbeat iniciado para %s (intervalo %.1fs, timeout %.1fs)."
                % (self._config.endpoint, self._config.interval, self._config.timeout)
            ),
        )
        thread.start()

    def stop(self, timeout: Optional[float] = 5.0) -> None:
        thread = self._thread
        if not thread:
            return
        self._stop_event.set()
        if timeout is not None:
            thread.join(timeout=timeout)
        else:
            thread.join()
        if thread.is_alive():
            log_event(
                "primary-heartbeat",
                "Heartbeat não finalizou dentro do timeout configurado.",
            )
        else:
            log_event("primary-heartbeat", "Heartbeat finalizado.")
        self._thread = None

    def _run_loop(self) -> None:
        delay = 0.0
        while not self._stop_event.wait(delay):
            try:
                self._send_once()
            except Exception as exc:  # noqa: BLE001
                log_event("primary-heartbeat", f"Erro inesperado no heartbeat: {exc}")
            delay = self._config.interval

    def _build_payload(self) -> Dict[str, Any]:
        now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        try:
            status = self._status_provider() or {}
        except Exception as exc:  # noqa: BLE001
            status = {
                "provider_error": f"{exc.__class__.__name__}: {exc}",
            }

        return {
            "machine_id": self._config.machine_id,
            "timestamp": now.isoformat(),
            "software": "stream_to_youtube.py",
            "version": APP_VERSION,
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "pid": os.getpid(),
            "status": status,
        }

    def _send_once(self) -> None:
        endpoint = self._config.endpoint
        if not endpoint:
            return

        payload = self._build_payload()
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": HEARTBEAT_USER_AGENT,
            },
            method="POST",
        )
        if self._config.token:
            request.add_header("Authorization", f"Bearer {self._config.token}")

        started = time.monotonic()
        status_code: Optional[int] = None
        error_text: Optional[str] = None
        response_excerpt = ""
        success = False

        try:
            with urllib.request.urlopen(
                request, timeout=self._config.timeout
            ) as response:
                status_code = response.getcode()
                body_bytes = response.read()
                response_excerpt = body_bytes.decode("utf-8", errors="replace")[:512]
                success = 200 <= status_code < 300
                if not success:
                    error_text = f"HTTP {status_code}"
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            body_bytes = exc.read()
            response_excerpt = body_bytes.decode("utf-8", errors="replace")[:512]
            error_text = f"HTTP {exc.code} {exc.reason}"
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            error_text = f"URLError: {reason}"
        except Exception as exc:  # noqa: BLE001
            error_text = f"{exc.__class__.__name__}: {exc}"

        latency_ms = int((time.monotonic() - started) * 1000)
        entry = {
            "timestamp": payload["timestamp"],
            "endpoint": endpoint,
            "machine_id": self._config.machine_id,
            "success": success,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "error": error_text,
            "response_excerpt": response_excerpt,
            "payload": payload,
        }

        self._append_log_entry(entry)

        if not success:
            detail = error_text or (
                f"HTTP {status_code}"
                if status_code is not None
                else "erro desconhecido"
            )
            log_event("primary-heartbeat", f"Falha ao enviar status: {detail}")

    def _append_log_entry(self, entry: Dict[str, Any]) -> None:
        path = self._config.log_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        try:
            current_ts = datetime.datetime.fromisoformat(
                entry["timestamp"].replace("Z", "+00:00")
            )
        except ValueError:
            current_ts = datetime.datetime.utcnow().replace(
                tzinfo=datetime.timezone.utc
            )

        cutoff = current_ts - datetime.timedelta(
            seconds=self._config.log_retention_seconds
        )
        retained: list[Dict[str, Any]] = []

        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for raw_line in handle:
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts_text = data.get("timestamp")
                        if not isinstance(ts_text, str):
                            continue
                        try:
                            ts_value = datetime.datetime.fromisoformat(
                                ts_text.replace("Z", "+00:00")
                            )
                        except ValueError:
                            continue
                        if ts_value.tzinfo is None:
                            ts_value = ts_value.replace(tzinfo=datetime.timezone.utc)
                        if ts_value >= cutoff:
                            retained.append(data)
            except OSError:
                retained = []

        retained.append(entry)

        tmp_path = path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                for item in retained:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            tmp_path.replace(path)
        except OSError:
            with suppress(OSError):
                tmp_path.unlink()


class StreamingWorker:
    """Background controller that keeps ffmpeg alive while streaming."""

    def __init__(self, config: StreamingConfig) -> None:
        if not config.yt_url:
            raise ValueError("Streaming worker requires a resolved YouTube ingest URL.")
        self._config = config
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._process_lock = threading.Lock()
        self._process: Optional[subprocess.Popen[str]] = None
        self._base_output_args = list(config.output_args)
        self._base_preset = _extract_arg_value(self._base_output_args, "-preset")
        self._last_autotune_bitrate: Optional[int] = None
        self._last_autotune_preset: Optional[str] = None
        self._autotune_failed_once = False
        self._started_at: Optional[float] = None
        self._last_launch_time: Optional[float] = None
        self._restart_count = 0
        self._last_exit_code: Optional[int] = None

    def start(self) -> None:
        if self.is_running:
            return

        self._stop_event.clear()
        self._started_at = time.time()
        self._last_launch_time = None
        self._restart_count = 0
        self._last_exit_code = None
        self._thread = threading.Thread(
            target=self._run_loop, name="StreamingWorker", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: Optional[float] = 10.0) -> None:
        if not self._thread:
            return

        self._stop_event.set()
        self._terminate_process()

        if timeout is not None:
            self._thread.join(timeout=timeout)
        else:
            self._thread.join()

        if self._thread.is_alive():
            log_event("primary", "Streaming worker thread did not stop within timeout")
        self._thread = None

    def join(self, timeout: Optional[float] = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def status_snapshot(self) -> Dict[str, Any]:
        with self._process_lock:
            proc = self._process
            running = bool(proc and proc.poll() is None)
            pid = proc.pid if running and proc else None

        now = time.time()
        started = self._started_at
        uptime = now - started if started else 0.0
        launch_age = now - self._last_launch_time if self._last_launch_time else None

        snapshot: Dict[str, Any] = {
            "thread_running": self.is_running,
            "ffmpeg_running": running,
            "ffmpeg_pid": pid,
            "stop_requested": self._stop_event.is_set(),
            "restarts": self._restart_count,
            "last_exit_code": self._last_exit_code,
            "uptime_seconds": round(uptime, 1) if started else 0.0,
            "seconds_since_launch": (
                round(launch_age, 1) if launch_age is not None else None
            ),
            "in_day_window": in_day_window(self._config),
            "autotune_enabled": self._config.autotune_enabled,
            "resolution": self._config.resolution,
            "yt_url_present": bool(self._config.yt_url),
            "heartbeat_configured": self._config.heartbeat.enabled,
        }
        return snapshot

    def _run_loop(self) -> None:
        print(
            "===== START {} =====".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        print(
            "CMD:",
            self._config.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            *self._config.input_args,
            *self._config.output_args,
            "-f",
            "flv",
            self._config.yt_url,
        )
        log_event("primary", "Streaming loop started")

        try:
            while not self._stop_event.is_set():
                if not in_day_window(self._config):
                    print("[primary] Night period — holding (no transmit).")
                    if self._stop_event.wait(30):
                        break
                    continue

                output_args = self._prepare_output_args()
                cmd = [
                    self._config.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    *self._config.input_args,
                    *output_args,
                    "-f",
                    "flv",
                    self._config.yt_url,
                ]
                print(
                    "CMD:",
                    self._config.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    *self._config.input_args,
                    *output_args,
                    "-f",
                    "flv",
                    self._config.yt_url,
                )
                log_event("primary", "Launching ffmpeg process")

                with self._process_lock:
                    try:
                        self._process = subprocess.Popen(cmd)
                        self._last_launch_time = time.time()
                        self._last_exit_code = None
                    except OSError as exc:
                        log_event("primary", f"Falha ao iniciar ffmpeg: {exc}")
                        if self._stop_event.wait(5):
                            break
                        continue

                code = self._wait_process()
                if code is None:
                    break

                print(f"[primary] ffmpeg exited code {code}; reiniciando em 5s.")
                log_event(
                    "primary",
                    f"ffmpeg exited with code {code}; retrying in 5s",
                )
                if self._stop_event.wait(5):
                    break
        finally:
            self._terminate_process()
            log_event("primary", "Streaming loop finished")

    def _prepare_output_args(self) -> list[str]:
        output_args = list(self._base_output_args)

        if (
            not self._config.autotune_enabled
            or self._config.autotune_interval <= 0
            or self._stop_event.is_set()
        ):
            self._autotune_failed_once = False
            self._last_autotune_bitrate = None
            self._last_autotune_preset = None
            self._sync_output_args(output_args)
            return output_args

        bitrate = estimate_upload_bitrate(
            interval=self._config.autotune_interval,
            min_kbps=self._config.bitrate_min_kbps,
            max_kbps=self._config.bitrate_max_kbps,
            safety_margin=self._config.autotune_safety_margin,
        )

        if bitrate is None:
            if not self._autotune_failed_once:
                log_event(
                    "primary",
                    "Autotune indisponível ou falhou na medição; mantendo bitrate estático.",
                )
                self._autotune_failed_once = True
            self._sync_output_args(output_args)
            return output_args

        self._autotune_failed_once = False
        adjusted_args, metadata = self._apply_autotune_settings(output_args, bitrate)
        self._sync_output_args(adjusted_args)

        preset = metadata.get("preset")
        if (
            self._last_autotune_bitrate != metadata["bitrate"]
            or self._last_autotune_preset != preset
        ):
            log_event(
                "primary",
                (
                    "Autotune definiu bitrate {bitrate} kbps, maxrate {maxrate} kbps, "
                    "bufsize {bufsize} kbps e preset '{preset}'."
                ).format(
                    bitrate=metadata["bitrate"],
                    maxrate=metadata["maxrate"],
                    bufsize=metadata["bufsize"],
                    preset=preset or self._base_preset or "desconhecido",
                ),
            )
            self._last_autotune_bitrate = metadata["bitrate"]
            self._last_autotune_preset = preset

        return adjusted_args

    def _apply_autotune_settings(
        self, output_args: list[str], measured_bitrate: int
    ) -> tuple[list[str], dict[str, int | Optional[str]]]:
        bitrate = max(
            self._config.bitrate_min_kbps,
            min(measured_bitrate, self._config.bitrate_max_kbps),
        )

        computed_maxrate = max(int(bitrate * 1.15), bitrate + 250)
        maxrate = min(max(computed_maxrate, bitrate), self._config.bitrate_max_kbps)
        bufsize = min(max(maxrate * 2, bitrate * 2), self._config.bitrate_max_kbps * 2)

        _set_arg_value(output_args, "-b:v", f"{bitrate}k")
        _set_arg_value(output_args, "-maxrate", f"{maxrate}k")
        _set_arg_value(output_args, "-bufsize", f"{bufsize}k")

        preset = _select_preset(self._base_preset, bitrate)
        if preset:
            _set_arg_value(output_args, "-preset", preset)

        metadata: dict[str, int | Optional[str]] = {
            "bitrate": bitrate,
            "maxrate": maxrate,
            "bufsize": bufsize,
            "preset": preset,
        }
        return output_args, metadata

    def _sync_output_args(self, new_args: list[str]) -> None:
        config_args = self._config.output_args
        config_args.clear()
        config_args.extend(new_args)

    def _wait_process(self) -> Optional[int]:
        with self._process_lock:
            proc = self._process

        if proc is None:
            return None

        while True:
            try:
                code = proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if self._stop_event.is_set():
                    self._terminate_process()
                    return None

        with self._process_lock:
            self._process = None

        if code is None:
            return None

        self._last_exit_code = code
        if not self._stop_event.is_set():
            self._restart_count += 1

        return code

    def _terminate_process(self) -> None:
        with self._process_lock:
            proc = self._process

        if proc is None:
            return

        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                else:
                    proc.wait()

        with self._process_lock:
            self._process = None
            self._last_launch_time = None


def run_forever(
    config: Optional[StreamingConfig] = None,
    existing_worker: Optional["StreamingWorker"] = None,
) -> None:
    global _ACTIVE_WORKER
    if existing_worker is not None:
        worker = existing_worker
        active_config = (
            worker._config
        )  # noqa: SLF001 - internal access acceptable within module
    else:
        if config is None:
            config = load_config()
        worker = StreamingWorker(config)
        active_config = config
    _ACTIVE_WORKER = worker
    if not worker.is_running and not _stop_request_active():
        worker.start()
    stop_logged = False
    reporter: Optional[HeartbeatReporter] = None
    if active_config.heartbeat.enabled and active_config.heartbeat.endpoint:

        def _heartbeat_status() -> Dict[str, Any]:
            snapshot = worker.status_snapshot()
            snapshot.update(
                {
                    "stop_request_active": _stop_request_active(),
                    "bitrate_min_kbps": active_config.bitrate_min_kbps,
                    "bitrate_max_kbps": active_config.bitrate_max_kbps,
                    "autotune_interval": active_config.autotune_interval,
                    "autotune_safety_margin": active_config.autotune_safety_margin,
                    "day_window": {
                        "start_hour": active_config.day_start_hour,
                        "end_hour": active_config.day_end_hour,
                        "tz_offset_hours": active_config.tz_offset_hours,
                    },
                }
            )
            return snapshot

        reporter = HeartbeatReporter(active_config.heartbeat, _heartbeat_status)
        reporter.start()
    try:
        while True:
            if _stop_request_active():
                if not stop_logged:
                    log_event(
                        "primary", "Stop sentinel detected; shutting down worker."
                    )
                    stop_logged = True
                worker.stop()
                _clear_stop_request()
            if not worker.is_running:
                break
            worker.join(timeout=0.5)
    finally:
        if reporter is not None:
            reporter.stop()
        worker.stop()
        _ACTIVE_WORKER = None
        _clear_stop_request()


def _start_streaming_instance(resolution: Optional[str] = None) -> int:
    try:
        _claim_pid_file()
    except RuntimeError as exc:
        message = str(exc)
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        return 1
    except OSError as exc:
        message = f"Falha ao registrar PID: {exc}"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        return 1

    try:
        _ensure_signal_handlers()
        config = load_config(resolution=resolution)
        if not config.yt_url:
            message = "Credenciais YT_URL/YT_KEY ausentes; streaming worker finalizado."
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            return 2

        log_event("primary", f"Resolução selecionada: {config.resolution}")
        print(f"[primary] Resolução selecionada: {config.resolution}")
        log_event("primary", f"Iniciando worker (PID {os.getpid()})")
        run_forever(config=config)
        log_event("primary", "Worker finalizado")
        return 0
    finally:
        _release_pid_file()


def _stop_streaming_instance(timeout: float = 30.0) -> int:
    path = _pid_file_path()
    pid = _read_pid_file(path)
    if pid is None:
        message = "Nenhuma instância ativa encontrada."
        print(f"[primary] {message}")
        log_event("primary", message)
        _clear_stop_request()
        return 0

    if not _is_pid_running(pid):
        message = f"Registro de PID obsoleto ({pid}); removendo arquivo."
        print(f"[primary] {message}")
        log_event("primary", message)
        _release_pid_file(expected_pid=pid)
        _clear_stop_request()
        return 0

    if not _request_stop_via_sentinel():
        message = "Falha ao registrar solicitação de parada (sentinela)."
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        return 1

    message = (
        f"Solicitação de parada registrada para PID {pid}; aguardando finalização."
    )
    print(f"[primary] {message}")
    log_event("primary", message)

    deadline = time.time() + timeout
    sentinel_acknowledged = False
    while time.time() < deadline:
        if not sentinel_acknowledged and not _stop_request_active():
            log_event("primary", "Sentinela de parada reconhecida pelo worker")
            sentinel_acknowledged = True
        if not _is_pid_running(pid):
            _release_pid_file(expected_pid=pid)
            _clear_stop_request()
            message = "Instância interrompida com sucesso."
            print(f"[primary] {message}")
            log_event("primary", message)
            return 0
        time.sleep(0.5)

    message = "Timeout ao aguardar a parada do worker."
    print(f"[primary] {message}", file=sys.stderr)
    log_event("primary", message)
    _clear_stop_request()
    return 1


def main() -> None:
    _minimize_console_window()

    raw_args = sys.argv[1:]
    normalized_args = [arg.lower() for arg in raw_args]

    command = normalized_args[0] if normalized_args else "/start"
    if command not in {"/start", "/stop"}:
        message = f"Flag desconhecida: {raw_args[0]}"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        sys.exit(1)

    resolution_arg: Optional[str] = None

    if command == "/stop":
        if len(normalized_args) > 1:
            message = "A flag /stop não aceita parâmetros adicionais."
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)
        exit_code = _stop_streaming_instance()
        sys.exit(exit_code)

    if len(normalized_args) > 2:
        message = "Utilize no máximo um parâmetro para /start (360p, 720p ou 1080p)."
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        sys.exit(1)

    if len(normalized_args) == 2:
        resolution_candidate = normalized_args[1]
        normalized_resolution = _normalize_resolution(resolution_candidate)
        if normalized_resolution is None:
            message = f"Resolução desconhecida: {raw_args[1]}"
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)
        resolution_arg = normalized_resolution

    exit_code = _start_streaming_instance(resolution=resolution_arg)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
