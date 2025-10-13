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
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
import textwrap
import re
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

# Caminho para o executável ffprobe. Se vazio, o script tenta localizar
# automaticamente na mesma pasta do ffmpeg.
#FFPROBE=C:\\caminho\\para\\ffprobe.exe

# Controla a verificação periódica do sinal da câmara (via ffprobe).
#BWB_CAMERA_PROBE_INTERVAL=30
#BWB_CAMERA_PROBE_TIMEOUT=7
#BWB_CAMERA_SIGNAL_REQUIRED=1

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


def _resolve_ffprobe_path(ffmpeg_path: str) -> str:
    configured = os.environ.get("FFPROBE", "").strip()
    if configured:
        return configured

    if ffmpeg_path:
        candidate = Path(ffmpeg_path)
        name = candidate.name.lower()
        if name == "ffmpeg.exe":
            return str(candidate.with_name("ffprobe.exe"))
        if name == "ffmpeg":
            return str(candidate.with_name("ffprobe"))
        suffix = candidate.suffix.lower()
        replacement = "ffprobe.exe" if suffix == ".exe" else "ffprobe"
        return str(candidate.with_name(replacement))

    return "ffprobe"


LOG_DIR, LOG_STEM, LOG_SUFFIX = _resolve_log_target()
LOG_PATTERN = f"{LOG_STEM}-*.log"
LOG_RETENTION_DAYS = 7
_SHOW_ON_SCREEN = False

_PID_FILE_NAME = "stream_to_youtube.pid"
_STOP_SENTINEL_NAME = "stream_to_youtube.stop"
_SIGNAL_HANDLERS_INSTALLED = False
_ACTIVE_WORKER: Optional["StreamingWorker"] = None
_CTRL_HANDLER_REF = None
_FULL_DIAGNOSTICS_REQUESTED = False


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
            f"Já existe uma instância ativa (PID {existing_pid}). Utilize --stop antes de reiniciar."
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

    directory_ready = True

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory_ready = False

    if directory_ready:
        try:
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            # Logging should never interrupt the streaming loop.
            pass

    if _SHOW_ON_SCREEN:
        try:
            print(line.rstrip("\n"), flush=True)
        except OSError:
            pass


def _mask_sensitive_arg(value: str) -> str:
    sanitized = value
    if "://" in sanitized and "@" in sanitized:
        prefix, _, remainder = sanitized.partition("://")
        credentials, sep, tail = remainder.partition("@")
        if sep:
            user, colon, _password = credentials.partition(":")
            if colon:
                masked_credentials = f"{user}:***" if user else "***"
            else:
                masked_credentials = f"{credentials}:***" if credentials else "***"
            sanitized = f"{prefix}://{masked_credentials}@{tail}"
        else:
            sanitized = f"{prefix}://{remainder}"

    lowered = sanitized.lower()
    for marker in ("password=", "pass=", "pwd="):
        idx = lowered.find(marker)
        if idx == -1:
            continue
        end = sanitized.find("&", idx)
        if end == -1:
            end = len(sanitized)
        sanitized = sanitized[: idx + len(marker)] + "***" + sanitized[end:]
        lowered = sanitized.lower()
    return sanitized


def _describe_executable(candidate: str) -> str:
    value = candidate.strip()
    if not value:
        return "não configurado"

    path_candidate = Path(value)
    try:
        if path_candidate.exists():
            try:
                stats = path_candidate.stat()
            except OSError as exc:
                return f"{path_candidate} (inacessível: {exc})"
            size = stats.st_size
            return f"{path_candidate} (encontrado, tamanho={size} bytes)"

        contains_sep = path_candidate.is_absolute() or any(
            sep in value for sep in ("/", "\\")
        )
        if contains_sep:
            return f"{path_candidate} (não encontrado)"
    except OSError as exc:
        return f"{value} (erro ao aceder: {exc})"

    resolved = shutil.which(value)
    if resolved:
        return f"{value} (resolvido via PATH: {resolved})"
    return f"{value} (não encontrado)"


def _extract_camera_host(input_args: list[str]) -> Optional[str]:
    for raw in reversed(input_args):
        if not isinstance(raw, str):
            continue
        candidate = raw.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if not (lowered.startswith("rtsp://") or lowered.startswith("rtsps://")):
            continue
        try:
            parsed = urllib.parse.urlsplit(candidate)
        except Exception:  # noqa: BLE001 - diagnostics should not abort
            parsed = None
        if parsed and parsed.hostname:
            return parsed.hostname
        try:
            remainder = candidate.split("://", 1)[1]
        except IndexError:
            continue
        authority = remainder.split("/", 1)[0]
        host_part = authority.split("@")[-1]
        host_only = host_part.split(":", 1)[0].strip("[] ")
        if host_only:
            return host_only
    return None


def _resolve_ping_command() -> Optional[str]:
    candidates = ["ping.exe", "ping"]
    for candidate in candidates:
        if not candidate:
            continue
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _parse_ping_rtt(output: str) -> Optional[float]:
    patterns = [
        r"Average\s*=\s*(\d+(?:[\.,]\d+)?)\s*ms",
        r"M[ée]dia\s*=\s*(\d+(?:[\.,]\d+)?)\s*ms",
        r"Avg\s*=\s*(\d+(?:[\.,]\d+)?)\s*ms",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).replace(",", ".")
        try:
            return float(value)
        except ValueError:
            continue
    return None


def _collect_camera_ping_snapshot(host: str) -> Dict[str, Any]:
    timestamp = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    iso_timestamp = timestamp.isoformat().replace("+00:00", "Z")
    command = _resolve_ping_command()
    count = 1
    timeout = 1.5

    if not command:
        return {
            "host": host,
            "reachable": None,
            "last_checked": iso_timestamp,
            "last_error": "ping não disponível no sistema",
        }

    ping_args = [command, "-n", str(count), "-w", str(int(timeout * 1000)), host]
    exec_timeout = max(timeout * count + 2.0, 5.0)

    try:
        completed = subprocess.run(
            ping_args,
            capture_output=True,
            text=True,
            timeout=exec_timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "host": host,
            "reachable": None,
            "last_checked": iso_timestamp,
            "last_error": "comando ping não encontrado",
        }
    except subprocess.TimeoutExpired:
        return {
            "host": host,
            "reachable": False,
            "last_checked": iso_timestamp,
            "last_failure": iso_timestamp,
            "last_error": f"ping excedeu timeout de {exec_timeout:.1f}s",
            "timeout_seconds": timeout,
            "count": count,
        }

    combined_output = "\n".join(
        part for part in (completed.stdout or "", completed.stderr or "") if part
    )
    reachable = completed.returncode == 0
    rtt_ms = _parse_ping_rtt(combined_output)

    snapshot: Dict[str, Any] = {
        "host": host,
        "reachable": reachable,
        "last_checked": iso_timestamp,
        "timeout_seconds": timeout,
        "count": count,
        "command": command,
        "rtt_ms": rtt_ms,
        "age_seconds": 0.0,
    }
    if reachable:
        snapshot["last_success"] = iso_timestamp
    else:
        snapshot["last_failure"] = iso_timestamp

    if not reachable:
        lines = [line.strip() for line in combined_output.splitlines() if line.strip()]
        if lines:
            snapshot["last_error"] = lines[-1][:200]
        elif completed.stderr:
            snapshot["last_error"] = completed.stderr.strip()[:200]
        else:
            snapshot["last_error"] = "sem resposta"

    if combined_output:
        snapshot["raw_output"] = combined_output[-2000:]

    return snapshot


def _collect_full_diagnostics(config: "StreamingConfig") -> str:
    generated_at = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    timestamp_text = generated_at.isoformat().replace("+00:00", "Z")

    sanitized_input = [_mask_sensitive_arg(arg) for arg in config.input_args]
    sanitized_output = [_mask_sensitive_arg(arg) for arg in config.output_args]

    camera_snapshot: Dict[str, Any] = {}
    camera_result: Optional[bool] = None
    camera_error: Optional[str] = None
    ping_snapshot: Optional[Dict[str, Any]] = None
    try:
        monitor = CameraSignalMonitor(
            config.camera_probe.ffprobe,
            config.input_args,
            config.camera_probe.interval,
            config.camera_probe.timeout,
            config.camera_probe.required,
            log_fn=lambda *_args, **_kwargs: None,
        )
        camera_result = monitor.confirm_signal(force=True)
        camera_snapshot = monitor.snapshot()
        camera_error = camera_snapshot.get("last_error")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never abort
        camera_snapshot = {"error": f"{exc.__class__.__name__}: {exc}"}
        camera_error = str(exc)

    camera_host = _extract_camera_host(config.input_args)
    if camera_host:
        try:
            ping_snapshot = _collect_camera_ping_snapshot(camera_host)
        except Exception as exc:  # noqa: BLE001 - diagnostics must never abort
            ping_snapshot = {
                "host": camera_host,
                "reachable": None,
                "last_error": f"{exc.__class__.__name__}: {exc}",
            }
        if ping_snapshot:
            camera_snapshot["network_ping"] = ping_snapshot

    ffmpeg_status = _describe_executable(config.ffmpeg)
    ffprobe_status = _describe_executable(config.camera_probe.ffprobe)
    inside_day_window = in_day_window(config)
    stop_active = _stop_request_active()

    active_worker = _ACTIVE_WORKER
    worker_snapshot: Optional[Dict[str, Any]] = None
    worker_error: Optional[str] = None
    if active_worker is not None:
        try:
            worker_snapshot = active_worker.status_snapshot()
        except Exception as exc:  # noqa: BLE001
            worker_error = f"{exc.__class__.__name__}: {exc}"

    summary_lines = [
        f"- YT ingest configurado: {'sim' if config.yt_url else 'não'}",
        f"- ffmpeg: {ffmpeg_status}",
        f"- ffprobe: {ffprobe_status}",
        f"- Janela diurna neste instante: {'sim' if inside_day_window else 'não'}",
        f"- Autotune: {'ativo' if config.autotune_enabled else 'desativado'}",
        f"- Sentinela de paragem ativa: {'sim' if stop_active else 'não'}",
    ]

    if worker_snapshot is not None:
        running = bool(worker_snapshot.get("thread_running")) or bool(
            worker_snapshot.get("ffmpeg_running")
        )
        summary_lines.append(f"- Worker em execução: {'sim' if running else 'não'}")
    elif active_worker is None:
        summary_lines.append("- Worker em execução: não inicializado")
    elif worker_error:
        summary_lines.append(
            f"- Worker em execução: desconhecido ({worker_error})"
        )

    if camera_result is True:
        detail = camera_snapshot.get("last_success") or "último probe bem-sucedido desconhecido"
        summary_lines.append(f"- Sinal da câmara: disponível (último sucesso: {detail})")
    elif camera_result is False:
        detail = camera_error or "motivo desconhecido"
        summary_lines.append(f"- Sinal da câmara: indisponível ({detail})")
    else:
        detail = camera_error or "ver secção abaixo"
        summary_lines.append(f"- Sinal da câmara: não foi possível determinar ({detail})")

    if ping_snapshot:
        reachable = ping_snapshot.get("reachable")
        if reachable is True:
            rtt_ms = ping_snapshot.get("rtt_ms")
            if isinstance(rtt_ms, (int, float)):
                summary_lines.append(
                    f"- Ping da câmara: alcançável ({rtt_ms:.1f} ms)"
                )
            else:
                summary_lines.append("- Ping da câmara: alcançável")
        elif reachable is False:
            detail = ping_snapshot.get("last_error") or "sem resposta"
            summary_lines.append(
                f"- Ping da câmara: sem resposta ({detail})"
            )
        else:
            detail = ping_snapshot.get("last_error") or "não executado"
            summary_lines.append(
                f"- Ping da câmara: não foi possível executar ({detail})"
            )
    elif camera_host:
        summary_lines.append("- Ping da câmara: host identificado mas sem dados")
    else:
        summary_lines.append("- Ping da câmara: host não identificado nos argumentos")

    heartbeat_status = config.heartbeat
    heartbeat_token_present = bool(heartbeat_status.token)

    pid_path = _pid_file_path()
    sentinel_path = _stop_sentinel_path()
    log_path = _current_log_file()

    lines: list[str] = [
        "# Diagnóstico stream_to_youtube",
        f"Gerado em: {timestamp_text}",
        f"Versão da aplicação: {APP_VERSION}",
        "",
        "## Resumo",
        *summary_lines,
        "",
        "## Configuração carregada",
        f"- Resolução atual: {config.resolution}",
        f"- Intervalo diário: {config.day_start_hour:02d}h–{config.day_end_hour:02d}h (UTC{'+' if config.tz_offset_hours >= 0 else ''}{config.tz_offset_hours})",
        f"- Bitrate mínimo/máximo (kbps): {config.bitrate_min_kbps}/{config.bitrate_max_kbps}",
        f"- Intervalo do autotune (s): {config.autotune_interval:.1f}",
        f"- Margem de segurança do autotune: {config.autotune_safety_margin:.2f}",
        f"- URL do YouTube presente: {'sim' if bool(config.yt_url) else 'não'}",
        "- Argumentos de entrada (ffmpeg):",
    ]

    if sanitized_input:
        lines.extend(f"  - {item}" for item in sanitized_input)
    else:
        lines.append("  - (nenhum argumento configurado)")

    lines.append("- Argumentos de saída (ffmpeg):")
    if sanitized_output:
        lines.extend(f"  - {item}" for item in sanitized_output)
    else:
        lines.append("  - (nenhum argumento configurado)")

    lines.extend(
        [
            "",
            "## Caminhos e ficheiros",
            f"- Ficheiro de log ativo: {log_path}",
            f"- PID file: {pid_path} ({'existe' if pid_path.exists() else 'inexistente'})",
            f"- Sentinela de paragem: {sentinel_path} ({'existe' if sentinel_path.exists() else 'inexistente'})",
            f"- Heartbeat ativo: {'sim' if heartbeat_status.enabled else 'não'}",
            f"- Endpoint do heartbeat: {heartbeat_status.endpoint or 'não configurado'}",
            f"- Intervalo/timeout do heartbeat: {heartbeat_status.interval:.1f}s / {heartbeat_status.timeout:.1f}s",
            f"- Machine ID configurado: {heartbeat_status.machine_id}",
            f"- Token do heartbeat presente: {'sim' if heartbeat_token_present else 'não'}",
            f"- Ficheiro de log do heartbeat: {heartbeat_status.log_path}",
            "",
            "## Sinal da câmara",
            f"- Verificação obrigatória: {'sim' if config.camera_probe.required else 'não'}",
            f"- Intervalo do probe (s): {config.camera_probe.interval:.1f}",
            f"- Timeout do probe (s): {config.camera_probe.timeout:.1f}",
            f"- Último erro registado: {camera_error or 'nenhum'}",
            "Estado detalhado:",
        ]
    )

    try:
        snapshot_json = json.dumps(camera_snapshot, indent=2, ensure_ascii=False)
    except TypeError:
        snapshot_json = str(camera_snapshot)
    lines.append("```")
    lines.append(snapshot_json)
    lines.append("```")

    if ping_snapshot:
        lines.extend(["", "## Ping da câmara", "Estado atual:"])
        try:
            ping_json = json.dumps(ping_snapshot, indent=2, ensure_ascii=False)
        except TypeError:
            ping_json = str(ping_snapshot)
        lines.append("```")
        lines.append(ping_json)
        lines.append("```")

    if worker_snapshot is not None:
        lines.extend(["", "## Estado do worker ativo", "Estado detalhado:"])
        try:
            worker_json = json.dumps(worker_snapshot, indent=2, ensure_ascii=False)
        except TypeError:
            worker_json = str(worker_snapshot)
        lines.append("```")
        lines.append(worker_json)
        lines.append("```")
    elif worker_error:
        lines.extend(
            [
                "",
                "## Estado do worker ativo",
                f"- Não foi possível recolher snapshot: {worker_error}",
            ]
        )

    report = "\n".join(lines)
    if not report.endswith("\n"):
        report += "\n"
    return report


def _write_full_diagnostics(config: "StreamingConfig") -> None:
    path = _script_base_dir() / "stream2yt-diags.txt"
    try:
        content = _collect_full_diagnostics(config)
    except Exception as exc:  # noqa: BLE001
        message = f"Falha ao gerar diagnóstico completo: {exc}"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        return

    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        message = f"Falha ao gravar diagnóstico completo ({exc})"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        return

    message = f"Diagnóstico completo registado em {path}"
    print(f"[primary] {message}")
    log_event("primary", message)


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

    def _resolve_override(raw: str) -> Optional[Path]:
        cleaned = raw.strip()
        if not cleaned:
            return None

        expanded = os.path.expandvars(cleaned)
        candidate = Path(expanded).expanduser()
        if candidate.suffix:
            return candidate
        return candidate / ".env"

    override_candidates: list[Path] = []
    for env_name in ("BWB_ENV_FILE", "BWB_ENV_PATH"):
        raw_value = os.environ.get(env_name, "")
        candidate = _resolve_override(raw_value)
        if candidate is not None:
            override_candidates.append(candidate)

    dir_override = os.environ.get("BWB_ENV_DIR", "").strip()
    if dir_override:
        expanded_dir = Path(os.path.expandvars(dir_override)).expanduser()
        override_candidates.append(expanded_dir / ".env")

    env_paths = override_candidates + env_paths

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
class CameraProbeConfig:
    ffprobe: str
    interval: float
    timeout: float
    required: bool


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
    camera_probe: CameraProbeConfig


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

    ffmpeg_path = os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe")
    camera_interval = _env_float("BWB_CAMERA_PROBE_INTERVAL", 30.0)
    if camera_interval < 5.0:
        camera_interval = 5.0
    camera_timeout = _env_float("BWB_CAMERA_PROBE_TIMEOUT", 7.0)
    if camera_timeout < 1.0:
        camera_timeout = 1.0
    camera_required = _env_flag("BWB_CAMERA_SIGNAL_REQUIRED", True)
    ffprobe_path = _resolve_ffprobe_path(ffmpeg_path)

    return StreamingConfig(
        yt_url=_resolve_yt_url(),
        input_args=input_args,
        output_args=output_args,
        resolution=resolved_resolution,
        ffmpeg=ffmpeg_path,
        day_start_hour=int(os.environ.get("YT_DAY_START_HOUR", "8")),
        day_end_hour=int(os.environ.get("YT_DAY_END_HOUR", "19")),
        tz_offset_hours=int(os.environ.get("YT_TZ_OFFSET_HOURS", "1")),
        autotune_enabled=_env_flag("YT_AUTOTUNE", False),
        bitrate_min_kbps=bitrate_min,
        bitrate_max_kbps=bitrate_max,
        autotune_interval=_env_float("YT_AUTOTUNE_INTERVAL", 8.0),
        autotune_safety_margin=safety_margin,
        heartbeat=_resolve_heartbeat_config(_script_base_dir()),
        camera_probe=CameraProbeConfig(
            ffprobe=ffprobe_path,
            interval=camera_interval,
            timeout=camera_timeout,
            required=camera_required,
        ),
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


class CameraSignalMonitor:
    """Probe the camera input with ffprobe and expose availability status."""

    def __init__(
        self,
        ffprobe: str,
        input_args: list[str],
        interval: float,
        timeout: float,
        required: bool,
        log_fn: Callable[[str, str], None] = log_event,
    ) -> None:
        self._ffprobe = ffprobe.strip() or "ffprobe"
        self._input_args = list(input_args)
        self._interval = interval if interval >= 5.0 else 5.0
        self._timeout = timeout if timeout >= 1.0 else 1.0
        self._required = required
        self._log = log_fn
        self._lock = threading.Lock()
        self._last_result: Optional[bool] = None
        self._last_checked: Optional[datetime.datetime] = None
        self._last_success: Optional[datetime.datetime] = None
        self._last_failure: Optional[datetime.datetime] = None
        self._last_error: Optional[str] = None
        self._consecutive_failures = 0
        self._state_reported: Optional[bool] = None
        self._ffprobe_available = bool(self._ffprobe)
        self._ffprobe_warning_emitted = False

    @staticmethod
    def _utc_now() -> datetime.datetime:
        return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    @property
    def retry_delay(self) -> float:
        return self._interval

    def confirm_signal(self, force: bool = False) -> bool:
        result = self._probe_if_needed(force)
        if result:
            return True
        return not self._required

    def snapshot(self) -> Dict[str, Any]:
        def _iso(ts: Optional[datetime.datetime]) -> Optional[str]:
            return ts.isoformat() if ts else None

        with self._lock:
            present = self._last_result
            return {
                "present": present if isinstance(present, bool) else None,
                "last_probe": _iso(self._last_checked),
                "last_success": _iso(self._last_success),
                "last_failure": _iso(self._last_failure),
                "consecutive_failures": self._consecutive_failures,
                "required": self._required,
                "ffprobe": self._ffprobe,
                "probe_interval_seconds": self._interval,
                "probe_timeout_seconds": self._timeout,
                "last_error": self._last_error,
                "ffprobe_available": self._ffprobe_available,
            }

    def _probe_if_needed(self, force: bool) -> bool:
        with self._lock:
            last_checked = self._last_checked
            interval = self._interval
            last_result = self._last_result

        if not force and last_checked is not None:
            elapsed = (self._utc_now() - last_checked).total_seconds()
            if elapsed < interval and last_result is not None:
                return last_result

        return self._probe_once()

    def _probe_once(self) -> bool:
        with self._lock:
            ffprobe = self._ffprobe
            timeout = self._timeout
            input_args = list(self._input_args)

        if not ffprobe:
            timestamp = self._utc_now()
            return self._update_state(True, timestamp, None)

        cmd = [
            ffprobe,
            "-v",
            "error",
            *input_args,
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
        ]
        timestamp = self._utc_now()
        error_text: Optional[str] = None

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            error_text = f"ffprobe não encontrado: {exc}"
            self._handle_missing_ffprobe(error_text)
            return True
        except subprocess.TimeoutExpired:
            error_text = f"ffprobe excedeu timeout de {timeout:.1f}s"
            return self._update_state(False, timestamp, error_text)
        except Exception as exc:  # noqa: BLE001
            error_text = f"{exc.__class__.__name__}: {exc}"
            return self._update_state(False, timestamp, error_text)

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            error_text = stderr or stdout or f"exit {completed.returncode}"
            return self._update_state(False, timestamp, error_text)

        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            error_text = f"json inválido: {exc}"
            return self._update_state(False, timestamp, error_text)

        present = False
        streams = payload.get("streams")
        if isinstance(streams, list):
            for stream in streams:
                if isinstance(stream, dict) and stream.get("codec_type") == "video":
                    present = True
                    break

        if not present:
            error_text = "sem streams de vídeo reportadas"
            return self._update_state(False, timestamp, error_text)

        return self._update_state(True, timestamp, None)

    def _handle_missing_ffprobe(self, error_text: str) -> None:
        with self._lock:
            self._ffprobe_available = False
            if not self._ffprobe_warning_emitted:
                message = (
                    f"ffprobe ausente em {self._ffprobe}; desativando verificação do sinal da câmara."
                )
                self._ffprobe_warning_emitted = True
            else:
                message = ""
            self._required = False
            timestamp = self._utc_now()
            self._last_checked = timestamp
            self._last_success = timestamp
            self._last_result = True
            self._last_error = error_text

        if message:
            self._log("primary", message)
            try:
                print(f"[primary] {message}")
            except Exception:  # noqa: BLE001
                pass

    def _update_state(
        self, present: bool, timestamp: datetime.datetime, error_text: Optional[str]
    ) -> bool:
        with self._lock:
            self._last_checked = timestamp
            if present:
                self._last_result = True
                self._last_success = timestamp
                self._consecutive_failures = 0
                self._last_error = None
            else:
                self._last_result = False
                self._last_failure = timestamp
                self._consecutive_failures += 1
                if error_text:
                    self._last_error = error_text
            last_error = self._last_error
            previous = self._state_reported

        if previous != present:
            self._log_state_change(present, last_error)

        return present

    def _log_state_change(self, present: bool, error_text: Optional[str]) -> None:
        if present:
            message = (
                "Sinal da câmara restabelecido; retomando transmissão principal assim que possível."
            )
        else:
            detail = error_text or "sem vídeo detectado"
            message = (
                "Sinal da câmara indisponível (%s); aguardando antes de transmitir." % detail
            )

        self._log("primary", message)
        try:
            print(f"[primary] {message}")
        except Exception:  # noqa: BLE001
            pass

        with self._lock:
            self._state_reported = present


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
        self._camera_monitor = CameraSignalMonitor(
            config.camera_probe.ffprobe,
            config.input_args,
            config.camera_probe.interval,
            config.camera_probe.timeout,
            config.camera_probe.required,
        )

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
        snapshot["camera_signal"] = self._camera_monitor.snapshot()
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

                if not self._camera_monitor.confirm_signal():
                    wait_seconds = max(self._camera_monitor.retry_delay, 5.0)
                    if self._stop_event.wait(wait_seconds):
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


def _start_streaming_instance(
    resolution: Optional[str] = None, full_diagnostics: bool = False
) -> int:
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
        if full_diagnostics:
            _write_full_diagnostics(config)
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


def start_streaming_instance(
    resolution: Optional[str] = None, full_diagnostics: bool = False
) -> int:
    """Public wrapper used by alternate launchers (e.g., Windows service)."""

    return _start_streaming_instance(
        resolution=resolution, full_diagnostics=full_diagnostics
    )


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


def stop_streaming_instance(timeout: float = 30.0) -> int:
    """Public wrapper for stopping instances via alternate launchers."""

    return _stop_streaming_instance(timeout=timeout)


def stop_active_worker(timeout: Optional[float] = 10.0) -> None:
    """Signal the in-process worker loop to stop (used by the service wrapper)."""

    worker = _ACTIVE_WORKER
    if worker is None:
        return

    try:
        worker.stop(timeout=timeout)
    except Exception as exc:  # pragma: no cover - best-effort shutdown
        log_event("primary", f"Erro ao parar worker ativo: {exc}")


def main() -> None:
    raw_args = sys.argv[1:]
    normalized_pairs: list[tuple[str, str]] = []
    for arg in raw_args:
        lowered = arg.lower()
        if lowered.startswith("/"):
            normalized = f"--{lowered[1:]}"
        elif lowered.startswith("--"):
            normalized = lowered
        else:
            normalized = f"--{lowered}"
        normalized_pairs.append((normalized, arg))

    command = "--start"
    extra_pairs = normalized_pairs

    if normalized_pairs and normalized_pairs[0][0] in {"--start", "--stop"}:
        command = normalized_pairs[0][0]
        extra_pairs = normalized_pairs[1:]
    elif normalized_pairs and normalized_pairs[0][0] not in {"--showonscreen", "--fulldiags"}:
        message = f"Flag desconhecida: {normalized_pairs[0][1]}"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        sys.exit(1)

    show_on_screen = False
    resolution_arg: Optional[str] = None
    full_diagnostics = False

    if command == "--stop":
        if extra_pairs:
            message = "A flag --stop não aceita parâmetros adicionais."
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)
        _minimize_console_window()
        exit_code = _stop_streaming_instance()
        sys.exit(exit_code)

    for normalized, raw in extra_pairs:
        if normalized == "--showonscreen":
            show_on_screen = True
            continue

        if normalized == "--fulldiags":
            full_diagnostics = True
            continue

        if not normalized.startswith("--"):
            message = f"Flag desconhecida: {raw}"
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)

        normalized_resolution = _normalize_resolution(normalized[2:])
        if normalized_resolution is None:
            message = f"Resolução desconhecida: {raw}"
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)

        if resolution_arg is not None:
            message = (
                "Utilize no máximo uma flag de resolução junto com --start "
                "(--360p, --720p ou --1080p)."
            )
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            sys.exit(1)

        resolution_arg = normalized_resolution

    global _SHOW_ON_SCREEN, _FULL_DIAGNOSTICS_REQUESTED
    _SHOW_ON_SCREEN = show_on_screen
    _FULL_DIAGNOSTICS_REQUESTED = full_diagnostics

    if not show_on_screen:
        _minimize_console_window()
    else:
        log_event(
            "primary",
            "Flag --showonscreen ativa; exibindo logs em tempo real no console.",
        )

    if full_diagnostics:
        log_event(
            "primary",
            "Flag --fulldiags ativa; relatório completo será gerado antes do arranque.",
        )

    exit_code = _start_streaming_instance(
        resolution=resolution_arg, full_diagnostics=full_diagnostics
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
