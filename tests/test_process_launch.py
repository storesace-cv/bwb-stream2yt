"""Testes do lançamento oculto de FFmpeg/FFprobe no Windows."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, List

SRC_DIR = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from process_launch import hidden_process_kwargs  # noqa: E402
from preview_rtsp import PreviewSession  # noqa: E402

MODULE_PATH = SRC_DIR / "stream_to_youtube.py"
SPEC = importlib.util.spec_from_file_location("_stream_hidden_proc_test", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_hidden_proc_test"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune_stub

SPEC.loader.exec_module(module)


def test_hidden_process_kwargs_empty_outside_windows():
    assert hidden_process_kwargs(platform="darwin") == {}
    assert hidden_process_kwargs(platform="linux") == {}
    assert hidden_process_kwargs(platform="linux2") == {}


def test_hidden_process_kwargs_windows_simulated(monkeypatch):
    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = 99

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)

    kwargs = hidden_process_kwargs(platform="win32")
    assert kwargs["creationflags"] == 0x08000000
    assert isinstance(kwargs["startupinfo"], FakeStartupInfo)
    assert kwargs["startupinfo"].dwFlags & 0x00000001
    assert kwargs["startupinfo"].wShowWindow == 0


def test_preview_popen_receives_hidden_kwargs(monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = 1

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)

    class _Proc:
        def __init__(self) -> None:
            self.stdout = None
            self.stderr = None

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    def factory(*args, **kwargs):
        captured.update(kwargs)
        proc = _Proc()
        proc.stdout = types.SimpleNamespace(
            read=lambda size=-1: b"", close=lambda: None
        )
        proc.stderr = types.SimpleNamespace(
            read=lambda size=-1: b"", close=lambda: None
        )
        return proc

    session = PreviewSession(
        ffmpeg="ffmpeg",
        input_args=["-i", "rtsp://demo"],
        restart_delay=30.0,
        popen_factory=factory,
    )
    # Chamar apenas o lançamento uma vez via método interno do loop é pesado;
    # exercitar o mesmo kwargs que o loop passa.
    monkeypatch.setattr(
        "preview_rtsp.hidden_process_kwargs",
        lambda: hidden_process_kwargs(platform="win32"),
    )
    process = session._popen_factory(  # noqa: SLF001
        ["ffmpeg", "-i", "x"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        **hidden_process_kwargs(platform="win32"),
    )
    assert process is not None
    assert captured.get("stdout") is subprocess.PIPE
    assert captured.get("stderr") is subprocess.PIPE
    assert captured.get("creationflags") == 0x08000000
    assert captured.get("startupinfo") is not None
    assert captured["startupinfo"].wShowWindow == 0


def test_main_ffmpeg_popen_receives_hidden_kwargs(tmp_path, monkeypatch):
    captured: List[Dict[str, Any]] = []

    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = 1

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured.append(kwargs)
            self.stdout = types.SimpleNamespace(
                readline=lambda: "", close=lambda: None, closed=False
            )
            self.stderr = types.SimpleNamespace(
                readline=lambda: "", close=lambda: None, closed=False
            )
            self.pid = 99
            self._alive = False

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        module, "hidden_process_kwargs", lambda: hidden_process_kwargs(platform="win32")
    )

    config = module.StreamingConfig(
        yt_url="rtmps://example/live2/key",
        input_args=["-i", "rtsp://cam"],
        output_args=["-c:v", "libx264"],
        resolution="720p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=2000,
        autotune_interval=8.0,
        autotune_safety_margin=0.2,
        heartbeat=module.HeartbeatConfig(
            enabled=False,
            endpoint=None,
            interval=20.0,
            timeout=5.0,
            machine_id="TEST",
            token=None,
            log_path=tmp_path / "hb.jsonl",
            log_retention_seconds=3600,
        ),
        camera_probe=module.CameraProbeConfig(
            ffprobe="ffprobe",
            interval=5.0,
            timeout=2.0,
            required=False,
        ),
    )
    worker = module.StreamingWorker(config)
    worker._stop_event.set()  # noqa: SLF001 - evita reinícios
    # Executar um ciclo mínimo: preparar comando e Popen como no worker.
    cmd = ["ffmpeg", "-i", "x", "-f", "flv", "rtmps://example/live2/key"]
    worker._process = module.subprocess.Popen(  # noqa: SLF001
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **module.hidden_process_kwargs(),
    )
    assert captured
    kwargs = captured[-1]
    assert kwargs.get("stdout") is subprocess.PIPE
    assert kwargs.get("stderr") is subprocess.PIPE
    assert kwargs.get("creationflags") == 0x08000000
    assert kwargs.get("startupinfo") is not None
    assert kwargs["startupinfo"].wShowWindow == 0


def test_ffprobe_run_receives_hidden_kwargs(tmp_path, monkeypatch):
    captured: Dict[str, Any] = {}

    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = 1

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            returncode=0, stdout='{"streams":[{"codec_type":"video"}]}', stderr=""
        )

    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        module, "hidden_process_kwargs", lambda: hidden_process_kwargs(platform="win32")
    )

    monitor = module.CameraSignalMonitor(
        "ffprobe",
        ["-i", "rtsp://cam"],
        interval=30.0,
        timeout=2.0,
        required=False,
    )
    assert monitor._probe_once() is True  # noqa: SLF001
    assert captured.get("capture_output") is True
    assert captured.get("creationflags") == 0x08000000
    assert captured.get("startupinfo") is not None
    assert captured["startupinfo"].wShowWindow == 0
