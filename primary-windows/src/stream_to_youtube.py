#!/usr/bin/env python3
# stream_to_youtube.py — Windows primary sender (one-file capable)
# - Keeps process alive 24/7 but only transmits during day-part window if desired.
# - Robust ffmpeg process handling and auto-restarts on error.
# - Default input is RTSP; change to dshow as needed.

import os
import sys
import time
import subprocess
import datetime
import shlex
from pathlib import Path
import threading
from typing import Optional


ENV_TEMPLATE_CONTENT = """# Configurações para stream_to_youtube.py
# Copie este arquivo para ".env" ou deixe que o script gere um automaticamente e depois personalize.

# Chave do YouTube Live. Se preenchida, a URL final será gerada automaticamente.
#YT_KEY=SEU_CODIGO_DO_YOUTUBE

# URL completa do ingest RTMP. Use se preferir definir manualmente em vez da chave.
#YT_URL=rtmps://a.rtmps.youtube.com/live2/SEU_CODIGO_DO_YOUTUBE

# Parâmetros de entrada para o ffmpeg. Ajuste o endereço RTSP conforme necessário.
#YT_INPUT_ARGS=-rtsp_transport tcp -rtsp_flags prefer_tcp -fflags nobuffer -flags low_delay -use_wallclock_as_timestamps 1 -i rtsp://USUARIO:SenhaFort3@10.0.254.50:554/Streaming/Channels/101

# Parâmetros de saída para o ffmpeg. Utilize para alterar codec, bitrate ou filtros.
#YT_OUTPUT_ARGS=-vf scale=1920:1080:flags=bicubic,format=yuv420p -r 30 -c:v libx264 -preset veryfast -profile:v high -level 4.2 -b:v 4500k -pix_fmt yuv420p -g 60 -c:a aac -b:a 128k -ar 44100 -f flv

# Caminho para o executável ffmpeg. Deixe vazio para usar o ffmpeg no PATH.
#FFMPEG=C:\\caminho\\para\\ffmpeg.exe

# Credenciais RTSP padrão (exemplo). Substitua conforme o dispositivo utilizado.
#RTSP_USERNAME=USUARIO
#RTSP_PASSWORD=SenhaFort3
"""


def _script_base_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller one-file executables
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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


_ensure_env_file()
_load_env_files()


def _resolve_yt_url():
    url = os.environ.get("YT_URL", "").strip()
    if url:
        return url

    key = os.environ.get("YT_KEY", "").strip()
    if key:
        return f"rtmps://a.rtmps.youtube.com/live2/{key}"

    print("[primary] ERRO: defina YT_URL ou YT_KEY (consulte README).", file=sys.stderr)
    sys.exit(2)


# === CONFIG (edit if needed) ===
# YouTube Primary URL (lido de variáveis/env file)
YT_URL = _resolve_yt_url()

# Day window (Africa/Luanda time offset — overridable via env)
DAY_START_HOUR = int(os.environ.get("YT_DAY_START_HOUR", "8"))
DAY_END_HOUR = int(os.environ.get("YT_DAY_END_HOUR", "19"))
TZ_OFFSET_HOURS = int(
    os.environ.get("YT_TZ_OFFSET_HOURS", "1")
)  # Luanda currently UTC+1


# FFmpeg input/output (example: RTSP)
def _split_args(value: str, default: list[str]) -> list[str]:
    value = value.strip()
    if not value:
        return default
    return shlex.split(value)


INPUT_ARGS = _split_args(
    os.environ.get("YT_INPUT_ARGS", ""),
    [
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
    ],
)
OUTPUT_ARGS = _split_args(
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

FFMPEG = os.environ.get("FFMPEG", r"C:\bwb\ffmpeg\bin\ffmpeg.exe")


def in_day_window(now_utc=None):
    if now_utc is None:
        now_utc = datetime.datetime.utcnow()
    local = now_utc + datetime.timedelta(hours=TZ_OFFSET_HOURS)
    return DAY_START_HOUR <= local.hour < DAY_END_HOUR


class StreamingWorker:
    """Background controller that keeps ffmpeg alive while streaming."""

    def __init__(self) -> None:
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

    def join(self) -> None:
        thread = self._thread
        if thread:
            thread.join()

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
            FFMPEG,
            "-hide_banner -loglevel warning",
            *INPUT_ARGS,
            *OUTPUT_ARGS,
            "-f",
            "flv",
            YT_URL,
        )
        log_event("primary", "Streaming loop started")

        try:
            while not self._stop_event.is_set():
                if not in_day_window():
                    print("[primary] Night period — holding (no transmit).")
                    if self._stop_event.wait(30):
                        break
                    continue

                cmd = [
                    FFMPEG,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    *INPUT_ARGS,
                    *OUTPUT_ARGS,
                    "-f",
                    "flv",
                    YT_URL,
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


def run_forever() -> None:
    worker = StreamingWorker()
    worker.start()
    try:
        worker.join()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()


def main() -> None:
    from system_tray import TrayApplication

    worker = StreamingWorker()
    worker.start()
    tray = TrayApplication(worker)

    try:
        tray.run()
    finally:
        worker.stop()


if __name__ == "__main__":
    main()
