"""Pré-visualização RTSP via FFmpeg independente (sem PySide6)."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from typing import Callable, List, Optional, Sequence

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

PREVIEW_WIDTH = 640
PREVIEW_FPS = 2.0
PREVIEW_RESTART_DELAY_SECONDS = 5.0
PREVIEW_FRAME_TIMEOUT_SECONDS = 10.0
STATUS_CONNECTING = "A ligar à câmara…"
STATUS_NO_IMAGE = "Sem imagem da câmara"

_RTSP_CREDENTIAL_RE = re.compile(
    r"(?i)\b(rtsps?://)([^/@\s]+):([^/@\s]+)@",
)
_PASSWORD_QUERY_RE = re.compile(
    r"(?i)\b(password|pass|pwd)=([^&\s]+)",
)


def sanitize_preview_text(text: str) -> str:
    """Remove credenciais RTSP / passwords de mensagens de diagnóstico."""

    sanitized = _RTSP_CREDENTIAL_RE.sub(r"\1\2:***@", text)
    sanitized = _PASSWORD_QUERY_RE.sub(r"\1=***", sanitized)
    return sanitized


def build_preview_command(
    ffmpeg: str,
    input_args: Sequence[str],
    *,
    width: int = PREVIEW_WIDTH,
    fps: float = PREVIEW_FPS,
) -> List[str]:
    """Constrói o comando FFmpeg de preview (MJPEG em stdout)."""

    executable = (ffmpeg or "").strip() or "ffmpeg"
    return [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        *list(input_args),
        "-an",
        "-vf",
        f"scale={int(width)}:-2,fps={fps}",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]


class JpegFrameParser:
    """Extrai frames JPEG a partir de um fluxo contínuo (blocos parciais)."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> List[bytes]:
        if not chunk:
            return []
        self._buffer.extend(chunk)
        frames: List[bytes] = []

        while True:
            start = self._buffer.find(SOI)
            if start < 0:
                if self._buffer and self._buffer[-1] == 0xFF:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break

            if start > 0:
                del self._buffer[:start]

            end = self._buffer.find(EOI, 2)
            if end < 0:
                break

            frame_end = end + 2
            frames.append(bytes(self._buffer[:frame_end]))
            del self._buffer[:frame_end]

        return frames

    def reset(self) -> None:
        self._buffer.clear()


FrameCallback = Callable[[bytes], None]
StatusCallback = Callable[[str], None]


class PreviewSession:
    """Sessão de preview FFmpeg com reinício automático após falha."""

    def __init__(
        self,
        *,
        ffmpeg: str,
        input_args: Sequence[str],
        on_frame: Optional[FrameCallback] = None,
        on_status: Optional[StatusCallback] = None,
        width: int = PREVIEW_WIDTH,
        fps: float = PREVIEW_FPS,
        restart_delay: float = PREVIEW_RESTART_DELAY_SECONDS,
        frame_timeout: float = PREVIEW_FRAME_TIMEOUT_SECONDS,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self._ffmpeg = ffmpeg
        self._input_args = list(input_args)
        self._on_frame = on_frame
        self._on_status = on_status
        self._width = width
        self._fps = fps
        self._restart_delay = restart_delay
        self._frame_timeout = frame_timeout
        self._popen_factory = popen_factory

        self._lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._parser = JpegFrameParser()
        self._received_frame = False
        self._session_started_mono: Optional[float] = None
        self._last_frame_mono: Optional[float] = None
        self._watchdog_triggered = False

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._parser.reset()
            with self._frame_lock:
                self._received_frame = False
                self._session_started_mono = None
                self._last_frame_mono = None
            self._thread = threading.Thread(
                target=self._run_loop,
                name="RtspPreviewSession",
                daemon=True,
            )
            self._thread.start()
        self._emit_status(STATUS_CONNECTING)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._terminate_process()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _emit_status(self, message: str) -> None:
        callback = self._on_status
        if callback is None:
            return
        try:
            callback(sanitize_preview_text(message))
        except Exception:  # noqa: BLE001
            pass

    def _emit_frame(self, jpeg: bytes) -> None:
        callback = self._on_frame
        if callback is None:
            return
        try:
            callback(jpeg)
        except Exception:  # noqa: BLE001
            pass

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._parser.reset()
            with self._frame_lock:
                self._received_frame = False
                self._last_frame_mono = None
                self._session_started_mono = None
            self._emit_status(STATUS_CONNECTING)
            command = build_preview_command(
                self._ffmpeg,
                self._input_args,
                width=self._width,
                fps=self._fps,
            )

            try:
                process = self._popen_factory(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except OSError as exc:
                self._emit_status(
                    f"Não foi possível iniciar o preview da câmara ({exc})."
                )
                if self._stop_event.wait(self._restart_delay):
                    break
                continue

            with self._lock:
                self._process = process
            with self._frame_lock:
                self._session_started_mono = time.monotonic()
                self._last_frame_mono = None
                self._received_frame = False
            self._watchdog_triggered = False

            self._start_io_threads(process)
            exit_code = self._wait_process(process)
            self._stop_io_threads()

            with self._lock:
                if self._process is process:
                    self._process = None

            if self._stop_event.is_set():
                break

            if self._watchdog_triggered or not self._received_frame:
                if not self._watchdog_triggered:
                    self._emit_status(STATUS_NO_IMAGE)
            else:
                detail = (
                    f"código {exit_code}"
                    if exit_code not in (None, 0)
                    else "processo terminou"
                )
                self._emit_status(
                    f"Pré-visualização interrompida ({detail}); a tentar novamente…"
                )

            if self._stop_event.wait(self._restart_delay):
                break

    def _start_io_threads(self, process: subprocess.Popen) -> None:
        stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(process,),
            name="RtspPreviewStdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(process,),
            name="RtspPreviewStderr",
            daemon=True,
        )
        with self._lock:
            self._stdout_thread = stdout_thread
            self._stderr_thread = stderr_thread
        stdout_thread.start()
        stderr_thread.start()

    def _read_stdout(self, process: subprocess.Popen) -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            while not self._stop_event.is_set():
                chunk = stream.read(4096)
                if not chunk:
                    break
                for frame in self._parser.feed(chunk):
                    with self._frame_lock:
                        self._received_frame = True
                        self._last_frame_mono = time.monotonic()
                    self._emit_frame(frame)
        except (OSError, ValueError):
            pass

    def _read_stderr(self, process: subprocess.Popen) -> None:
        stream = process.stderr
        if stream is None:
            return
        try:
            while not self._stop_event.is_set():
                chunk = stream.read(1024)
                if not chunk:
                    break
                try:
                    text = chunk.decode("utf-8", errors="replace").strip()
                except Exception:  # noqa: BLE001
                    continue
                if text:
                    self._emit_status(
                        f"Erro no preview da câmara: {sanitize_preview_text(text)}"
                    )
        except (OSError, ValueError):
            pass

    def _wait_process(self, process: subprocess.Popen) -> Optional[int]:
        while True:
            try:
                return process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                if self._stop_event.is_set():
                    self._terminate_process()
                    try:
                        return process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        return None

                if self._frame_timeout_exceeded():
                    self._watchdog_triggered = True
                    self._emit_status(STATUS_NO_IMAGE)
                    self._terminate_process()
                    try:
                        return process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        return None

    def _frame_timeout_exceeded(self) -> bool:
        now = time.monotonic()
        with self._frame_lock:
            last_frame = self._last_frame_mono
            started = self._session_started_mono
            timeout = self._frame_timeout
        if timeout <= 0:
            return False
        if last_frame is not None:
            return (now - last_frame) >= timeout
        if started is None:
            return False
        return (now - started) >= timeout

    def _terminate_process(self) -> None:
        with self._lock:
            process = self._process
        if process is None:
            return

        if process.poll() is None:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    process.wait(timeout=2.0)
                except Exception:  # noqa: BLE001
                    pass

        self._close_pipes(process)
        self._stop_io_threads(timeout=1.0)
        with self._lock:
            if self._process is process:
                self._process = None

    def _close_pipes(self, process: subprocess.Popen) -> None:
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def _stop_io_threads(self, timeout: float = 2.0) -> None:
        with self._lock:
            threads = [
                thread
                for thread in (self._stdout_thread, self._stderr_thread)
                if thread is not None
            ]
            self._stdout_thread = None
            self._stderr_thread = None
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=timeout)
