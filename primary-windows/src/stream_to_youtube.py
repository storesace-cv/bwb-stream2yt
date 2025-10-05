#!/usr/bin/env python3
# stream_to_youtube.py — Windows primary sender (one-file capable)
# - Keeps process alive 24/7 but only transmits during day-part window if desired.
# - Robust ffmpeg process handling and auto-restarts on error.
# - Default input is RTSP; change to dshow as needed.

import atexit
import datetime
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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
#YT_OUTPUT_ARGS=-vf scale=1920:1080:flags=bicubic,format=yuv420p -r 30 -c:v libx264 -preset veryfast -profile:v high -level 4.2 -b:v 4500k -pix_fmt yuv420p -g 60 -c:a aac -b:a 128k -ar 44100 -f flv

# Caminho para o executável ffmpeg. Deixe vazio para usar o ffmpeg no PATH.
#FFMPEG=C:\\caminho\\para\\ffmpeg.exe
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


@dataclass(frozen=True)
class StreamingConfig:
    yt_url: Optional[str]
    input_args: list[str]
    output_args: list[str]
    ffmpeg: str
    day_start_hour: int
    day_end_hour: int
    tz_offset_hours: int


def load_config() -> StreamingConfig:
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
            "scale=1920:1080:flags=bicubic,format=yuv420p",
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

    return StreamingConfig(
        yt_url=_resolve_yt_url(),
        input_args=input_args,
        output_args=output_args,
        ffmpeg=os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe"),
        day_start_hour=int(os.environ.get("YT_DAY_START_HOUR", "8")),
        day_end_hour=int(os.environ.get("YT_DAY_END_HOUR", "19")),
        tz_offset_hours=int(os.environ.get("YT_TZ_OFFSET_HOURS", "1")),
    )


def in_day_window(config: StreamingConfig, now_utc=None):
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()
    local = now_utc + datetime.timedelta(hours=config.tz_offset_hours)
    return config.day_start_hour <= local.hour < config.day_end_hour


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

    def start(self) -> None:
        if self.is_running:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="StreamingWorker", daemon=True)
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

                cmd = [
                    self._config.ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    *self._config.input_args,
                    *self._config.output_args,
                    "-f",
                    "flv",
                    self._config.yt_url,
                ]
                log_event("primary", "Launching ffmpeg process")

                with self._process_lock:
                    try:
                        self._process = subprocess.Popen(cmd)
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


def run_forever(
    config: Optional[StreamingConfig] = None,
    existing_worker: Optional["StreamingWorker"] = None,
) -> None:
    global _ACTIVE_WORKER
    if existing_worker is not None:
        worker = existing_worker
    else:
        if config is None:
            config = load_config()
        worker = StreamingWorker(config)
    _ACTIVE_WORKER = worker
    if not worker.is_running and not _stop_request_active():
        worker.start()
    stop_logged = False
    try:
        while True:
            if _stop_request_active():
                if not stop_logged:
                    log_event("primary", "Stop sentinel detected; shutting down worker.")
                    stop_logged = True
                worker.stop()
                _clear_stop_request()
            if not worker.is_running:
                break
            worker.join(timeout=0.5)
    finally:
        worker.stop()
        _ACTIVE_WORKER = None
        _clear_stop_request()


def _start_streaming_instance() -> int:
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
        config = load_config()
        if not config.yt_url:
            message = "Credenciais YT_URL/YT_KEY ausentes; streaming worker finalizado."
            print(f"[primary] {message}", file=sys.stderr)
            log_event("primary", message)
            return 2

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

    message = f"Solicitação de parada registrada para PID {pid}; aguardando finalização."
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
    if len(normalized_args) > 1:
        message = "Utilize no máximo uma flag (/start ou /stop)."
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        sys.exit(1)

    command = normalized_args[0] if normalized_args else "/start"
    if command not in {"/start", "/stop"}:
        message = f"Flag desconhecida: {raw_args[0]}"
        print(f"[primary] {message}", file=sys.stderr)
        log_event("primary", message)
        sys.exit(1)

    if command == "/stop":
        exit_code = _stop_streaming_instance()
        sys.exit(exit_code)

    exit_code = _start_streaming_instance()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
