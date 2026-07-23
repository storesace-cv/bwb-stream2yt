"""Testes do preview RTSP via FFmpeg (sem PySide6)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from preview_rtsp import (  # noqa: E402
    EOI,
    SOI,
    JpegFrameParser,
    PreviewSession,
    build_preview_command,
    sanitize_preview_text,
)


def test_build_preview_command_uses_input_args_and_mjpeg_pipe():
    command = build_preview_command(
        r"C:\bwb\ffmpeg\bin\ffmpeg.exe",
        ["-rtsp_transport", "tcp", "-i", "rtsp://cam/stream"],
        width=640,
        fps=2.0,
    )
    assert command[0].endswith("ffmpeg.exe")
    assert "-rtsp_transport" in command
    assert "rtsp://cam/stream" in command
    assert command[command.index("-vf") + 1] == "scale=640:-2,fps=2.0"
    assert "-f" in command and "image2pipe" in command
    assert "-vcodec" in command and "mjpeg" in command
    assert command[-1] == "-"


def test_jpeg_parser_complete_frame():
    parser = JpegFrameParser()
    frame = SOI + b"abc" + EOI
    assert parser.feed(frame) == [frame]


def test_jpeg_parser_split_across_chunks():
    parser = JpegFrameParser()
    frame = SOI + b"hello-world" + EOI
    assert parser.feed(frame[:3]) == []
    assert parser.feed(frame[3:8]) == []
    assert parser.feed(frame[8:]) == [frame]


def test_jpeg_parser_multiple_frames_same_chunk_and_leading_garbage():
    parser = JpegFrameParser()
    first = SOI + b"one" + EOI
    second = SOI + b"two" + EOI
    payload = b"junk" + first + second
    assert parser.feed(payload) == [first, second]


def test_sanitize_preview_text_hides_rtsp_credentials():
    raw = "Erro rtsp://user:secret@10.0.0.5:554/stream password=topsecret"
    cleaned = sanitize_preview_text(raw)
    assert "secret" not in cleaned
    assert "topsecret" not in cleaned
    assert "user:***@" in cleaned
    assert "password=***" in cleaned


class _FakePipe:
    def __init__(self, chunks: List[bytes]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self.closed or not self._chunks:
            return b""
        return self._chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class _BlockingPipe:
    """Pipe that blocks until closed — simula FFmpeg sem frames."""

    def __init__(self) -> None:
        self.closed = False
        self._closed = threading.Event()

    def read(self, size: int = -1) -> bytes:
        self._closed.wait()
        return b""

    def close(self) -> None:
        self.closed = True
        self._closed.set()


class _FakeProcess:
    def __init__(
        self,
        stdout_chunks: Optional[List[bytes]] = None,
        stderr_chunks: Optional[List[bytes]] = None,
        *,
        block_stdout: bool = False,
    ):
        if block_stdout:
            self.stdout = _BlockingPipe()
        else:
            self.stdout = _FakePipe(stdout_chunks or [])
        self.stderr = _FakePipe(stderr_chunks or [])
        self._exit_code = 0
        self._alive = True
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else self._exit_code

    def wait(self, timeout=None):
        deadline = time.time() + (timeout if timeout is not None else 30)
        while self._alive and time.time() < deadline:
            time.sleep(0.01)
        if self._alive:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout or 0)
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False
        try:
            self.stdout.close()
        except Exception:
            pass
        try:
            self.stderr.close()
        except Exception:
            pass

    def kill(self) -> None:
        self.killed = True
        self._alive = False
        try:
            self.stdout.close()
        except Exception:
            pass
        try:
            self.stderr.close()
        except Exception:
            pass


def test_preview_session_start_stop_with_mocked_popen():
    frame = SOI + b"frame-data" + EOI
    process = _FakeProcess([frame, b""])
    frames: List[bytes] = []
    statuses: List[str] = []
    created = threading.Event()

    def factory(*args, **kwargs):
        created.set()
        return process

    session = PreviewSession(
        ffmpeg="ffmpeg",
        input_args=["-i", "rtsp://demo/stream"],
        on_frame=frames.append,
        on_status=statuses.append,
        restart_delay=0.05,
        popen_factory=factory,
    )
    session.start()
    assert created.wait(timeout=2.0)
    deadline = time.time() + 2.0
    while not frames and time.time() < deadline:
        time.sleep(0.01)
    session.stop(timeout=2.0)

    assert frames == [frame]
    assert session.is_running is False
    assert process.terminated or process.poll() is not None
    assert any("A ligar" in item for item in statuses)


def test_preview_watchdog_terminates_when_no_frames():
    from preview_rtsp import STATUS_NO_IMAGE

    process = _FakeProcess(block_stdout=True)
    statuses: List[str] = []
    created = threading.Event()

    def factory(*args, **kwargs):
        created.set()
        return process

    session = PreviewSession(
        ffmpeg="ffmpeg",
        input_args=["-i", "rtsp://demo/stream"],
        on_status=statuses.append,
        restart_delay=30.0,
        frame_timeout=0.3,
        popen_factory=factory,
    )
    session.start()
    assert created.wait(timeout=2.0)
    deadline = time.time() + 3.0
    while not process.terminated and time.time() < deadline:
        time.sleep(0.05)
    session.stop(timeout=2.0)

    assert process.terminated is True
    assert STATUS_NO_IMAGE in statuses


def test_preview_status_messages_never_include_credentials():
    statuses: List[str] = []
    stderr_line = b"Failed rtsp://admin:p%40ss@10.1.2.3/h264"

    class FlappingProcess(_FakeProcess):
        def __init__(self):
            super().__init__([b""], [stderr_line, b""])
            self._alive = False
            self._exit_code = 1

    def factory(*args, **kwargs):
        return FlappingProcess()

    session = PreviewSession(
        ffmpeg="ffmpeg",
        input_args=["-i", "rtsp://admin:p%40ss@10.1.2.3/h264"],
        on_status=statuses.append,
        restart_delay=30.0,
        popen_factory=factory,
    )
    session.start()
    deadline = time.time() + 2.0
    while len(statuses) < 2 and time.time() < deadline:
        time.sleep(0.01)
    session.stop(timeout=2.0)

    joined = "\n".join(statuses)
    assert "p%40ss" not in joined
    assert "admin:***@" in joined or "password" not in joined.lower() or "***" in joined
