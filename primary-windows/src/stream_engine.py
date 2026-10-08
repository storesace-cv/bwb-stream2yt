"""Contrato de motor de envio: FFmpeg (transcode) e GStreamer (cópia)."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from effective_config import (
    ENGINE_FFMPEG,
    ENGINE_GSTREAMER,
    EffectiveConfig,
    load_effective_config,
    record_successful_engine,
    save_effective_config,
    shared_bin_dir,
)
from engine_compat import (
    MODE_COPY,
    MODE_TRANSCODE,
    EngineSelection,
    resolve_engine_for_session,
)
from send_quality import SEND_QUALITY_SOURCE, normalize_send_quality


class StreamEmitter(Protocol):
    def start(self) -> None: ...

    def stop(self, timeout: float | None = None) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    @property
    def is_running(self) -> bool: ...

    def status_snapshot(self) -> dict[str, Any]: ...


class FFmpegEmitter:
    """Wrapper fino sobre StreamingWorker (comportamento actual)."""

    def __init__(self, worker: Any, selection: EngineSelection) -> None:
        self._worker = worker
        self._selection = selection
        self._config = worker._config  # noqa: SLF001
        self._progress_confirmed = False

    def start(self) -> None:
        self._worker.start()

    def stop(self, timeout: float | None = None) -> None:
        self._worker.stop(timeout=timeout)

    def join(self, timeout: float | None = None) -> None:
        self._worker.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return bool(self._worker.is_running)

    def status_snapshot(self) -> dict[str, Any]:
        snap = dict(self._worker.status_snapshot())
        snap.update(
            {
                "engine": ENGINE_FFMPEG,
                "engine_mode": MODE_TRANSCODE,
                "engine_reason": self._selection.reason,
            }
        )
        # Evidência de progresso RTMPS (reutilizar campos existentes).
        if snap.get("rtmps_sending") or snap.get("bytes_sent"):
            if not self._progress_confirmed:
                self._progress_confirmed = True
                try:
                    record_successful_engine(ENGINE_FFMPEG)
                except Exception:
                    pass
        return snap


class GStreamerEmitter:
    """Emissor via auxiliar empacotado (cópia H.264)."""

    def __init__(
        self,
        *,
        config: Any,
        selection: EngineSelection,
        source_uri: str,
        rtmps_url: str,
        is_file: bool,
        silent_audio: bool,
        helper_path: Optional[Path] = None,
    ) -> None:
        self._config = config
        self._selection = selection
        self._source_uri = source_uri
        self._rtmps_url = rtmps_url
        self._is_file = is_file
        self._silent_audio = silent_audio
        self._helper_path = helper_path or _resolve_gst_helper()
        self._proc: Optional[subprocess.Popen[str]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._started_at: Optional[float] = None
        self._progress_confirmed = False
        self._last_error: Optional[str] = None

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="GStreamerEmitter", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        helper = self._helper_path
        if helper is None or not Path(helper).exists():
            self._last_error = "Auxiliar GStreamer ausente."
            return
        cmd = [
            str(helper) if str(helper).endswith((".exe", ".py")) else str(helper),
        ]
        if str(helper).endswith(".py"):
            cmd = [os.environ.get("PYTHON", "python3"), str(helper)]
        cmd.extend(["--source", self._source_uri, "--rtmps", self._rtmps_url])
        if self._is_file:
            cmd.append("--file")
        if self._silent_audio:
            cmd.append("--silent-audio")
        else:
            cmd.append("--with-source-audio")

        env = os.environ.copy()
        gst_root = shared_bin_dir() / "gstreamer"
        if gst_root.is_dir():
            env["GST_PLUGIN_PATH"] = str(gst_root / "lib" / "gstreamer-1.0")
            env["PATH"] = str(gst_root / "bin") + os.pathsep + env.get("PATH", "")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            self._started_at = time.monotonic()
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if self._stop.is_set():
                    break
                # Sem chave nos logs: o helper já omite a URL.
                if "pipeline" in line.lower() or "playing" in line.lower():
                    if not self._progress_confirmed and (
                        time.monotonic() - (self._started_at or 0) > 3.0
                    ):
                        self._progress_confirmed = True
                        try:
                            record_successful_engine(ENGINE_GSTREAMER)
                        except Exception:
                            pass
            self._proc.wait(timeout=5)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{exc.__class__.__name__}"
        finally:
            self._proc = None

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=timeout or 10.0)
            except Exception:
                proc.kill()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout or 10.0)

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "engine": ENGINE_GSTREAMER,
            "engine_mode": MODE_COPY,
            "engine_reason": self._selection.reason,
            "running": self.is_running,
            "error": self._last_error,
            "rtmps_sending": self._progress_confirmed,
            "yt_url_present": bool(getattr(self._config, "yt_url", None)),
        }


def _resolve_gst_helper() -> Optional[Path]:
    packaged = shared_bin_dir() / "gst_rtmps_helper.exe"
    if packaged.is_file():
        return packaged
    local = Path(__file__).with_name("gst_rtmps_helper.py")
    if local.is_file():
        return local
    return None


def _extract_source_uri(input_args: list[str]) -> tuple[str, bool]:
    try:
        idx = input_args.index("-i")
        uri = input_args[idx + 1]
    except (ValueError, IndexError):
        raise ValueError("Fonte de entrada ausente para o motor GStreamer.")
    is_file = not uri.lower().startswith(("rtsp://", "rtsps://", "http://", "https://"))
    return uri, is_file


def prepare_config_for_engine(config: Any, selection: EngineSelection) -> Any:
    """Ajusta qualidade efectiva (Gst → qualidade da fonte)."""

    if selection.engine == ENGINE_GSTREAMER:
        from stream_to_youtube import apply_send_quality

        return apply_send_quality(config, SEND_QUALITY_SOURCE)
    return config


def resolve_and_build_emitter(
    config: Any,
    *,
    worker_factory: Callable[[Any], Any],
    effective: Optional[EffectiveConfig] = None,
    send_quality: Optional[str] = None,
    skip_probe: bool = False,
) -> tuple[StreamEmitter, EngineSelection, Any]:
    """Resolve motor uma vez por sessão e cria o emissor único."""

    cfg = effective or load_effective_config()
    ui_quality = getattr(config, "send_quality", None)
    quality = normalize_send_quality(
        send_quality or ui_quality or cfg.send_quality or "alta"
    )

    selection = resolve_engine_for_session(
        effective=cfg,
        send_quality=quality if quality != "source" else SEND_QUALITY_SOURCE,
        audio_mode=str(
            getattr(config, "audio_mode", None) or cfg.audio_mode or "silent"
        ),
        contingency_on=bool(getattr(config, "camera_failover_to_demo", False)),
        mp4_path=str(
            getattr(config, "contingency_demo_path", None) or cfg.demo_video_path or ""
        ),
        input_args=list(getattr(config, "input_args", []) or []),
        ffmpeg_path=str(getattr(config, "ffmpeg", "") or ""),
        ffprobe_path=str(
            getattr(getattr(config, "camera_probe", None), "ffprobe", "") or ""
        ),
        skip_probe=skip_probe,
    )

    config = prepare_config_for_engine(config, selection)
    # Persistir motor efectivo (metadados; aplica no próximo restart a preferência já gravada).
    cfg.effective_engine = selection.engine
    cfg.effective_mode = selection.mode
    cfg.selection_reason = selection.reason
    try:
        save_effective_config(cfg)
    except Exception:
        pass

    if selection.engine == ENGINE_GSTREAMER:
        uri, is_file = _extract_source_uri(list(config.input_args))
        if not config.yt_url:
            raise ValueError("Destino YouTube ausente.")
        silent = str(getattr(config, "audio_mode", "silent") or "silent") != "source"
        emitter: StreamEmitter = GStreamerEmitter(
            config=config,
            selection=selection,
            source_uri=uri,
            rtmps_url=str(config.yt_url),
            is_file=is_file,
            silent_audio=silent,
        )
        return emitter, selection, config

    worker = worker_factory(config)
    return FFmpegEmitter(worker, selection), selection, config
