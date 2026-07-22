"""Observabilidade FFmpeg: progresso, estados RTMPS e eventos humanos."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


PROGRESS_GRACE_SECONDS = 5.0
PROGRESS_STALL_SECONDS = 8.0
EVENT_BUFFER_SIZE = 100

STATE_STOPPED = "Parado"
STATE_STARTING = "A iniciar"
STATE_SENDING = "A enviar"
STATE_NO_PROGRESS = "Sem progresso"
STATE_ERROR = "Erro"

HUMAN_MESSAGES = {
    "session_started": "Codificador iniciado; a preparar envio RTMPS.",
    "session_stopped": "Envio RTMPS parado.",
    "sending": "Dados a serem enviados para o destino RTMPS.",
    "no_progress": "O codificador está a correr, mas não há progresso de envio.",
    "ffmpeg_start_failed": "Não foi possível iniciar o FFmpeg.",
    "ffmpeg_exit_error": "O FFmpeg terminou com erro.",
    "ffmpeg_missing": "FFmpeg não encontrado ou inacessível.",
    "camera_no_signal": "Sinal da câmara indisponível.",
    "yt_url_missing": "Destino RTMPS / chave YouTube não configurados.",
}


def _safe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    text = value.strip()
    if not text or text.lower() in {"n/a", "nan"}:
        return None
    # FFmpeg bitrate often looks like "1234.5kbits/s"
    cleaned = text
    for suffix in ("kbits/s", "Kbits/s", "bits/s", "x"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    cleaned = cleaned.strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


@dataclass
class ProgressMetrics:
    frame: Optional[int] = None
    fps: Optional[float] = None
    bitrate: Optional[str] = None
    bitrate_kbps: Optional[float] = None
    total_size: Optional[int] = None
    out_time: Optional[str] = None
    out_time_ms: Optional[int] = None
    speed: Optional[str] = None


@dataclass
class ObservabilityEvent:
    timestamp: float
    component: str
    message: str
    code: Optional[str] = None


@dataclass
class EventBus:
    """Ring buffer thread-safe de eventos recentes."""

    maxlen: int = EVENT_BUFFER_SIZE
    _events: Deque[ObservabilityEvent] = field(init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=self.maxlen)

    def emit(
        self,
        component: str,
        message: str,
        *,
        code: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> ObservabilityEvent:
        event = ObservabilityEvent(
            timestamp=time.time() if timestamp is None else timestamp,
            component=component,
            message=message,
            code=code,
        )
        with self._lock:
            self._events.append(event)
        return event

    def emit_human(
        self,
        code: str,
        *,
        component: str = "primary",
        detail: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> ObservabilityEvent:
        base = HUMAN_MESSAGES.get(code, code)
        message = f"{base} ({detail})" if detail else base
        return self.emit(component, message, code=code, timestamp=timestamp)

    def recent(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if limit is not None:
            items = items[-limit:]
        return [
            {
                "timestamp": event.timestamp,
                "component": event.component,
                "message": event.message,
                "code": event.code,
            }
            for event in items
        ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class FFmpegProgressTracker:
    """Parser thread-safe da saída ``-progress`` do FFmpeg."""

    def __init__(
        self,
        *,
        grace_seconds: float = PROGRESS_GRACE_SECONDS,
        stall_seconds: float = PROGRESS_STALL_SECONDS,
        event_bus: Optional[EventBus] = None,
        monotonic: Optional[Any] = None,
    ) -> None:
        self._grace_seconds = grace_seconds
        self._stall_seconds = stall_seconds
        self._event_bus = event_bus or EventBus()
        self._monotonic = monotonic or time.monotonic
        self._lock = threading.Lock()
        self._metrics = ProgressMetrics()
        self._pending: Dict[str, str] = {}
        self._session_active = False
        self._error_active = False
        self._error_detail: Optional[str] = None
        self._session_started_mono: Optional[float] = None
        self._last_progress_mono: Optional[float] = None
        self._last_state: str = STATE_STOPPED
        self._stall_event_emitted = False
        self._sending_event_emitted = False

    @property
    def events(self) -> EventBus:
        return self._event_bus

    def mark_session_started(self, *, detail: Optional[str] = None) -> None:
        now = self._monotonic()
        with self._lock:
            self._session_active = True
            self._error_active = False
            self._error_detail = None
            self._session_started_mono = now
            self._last_progress_mono = None
            self._metrics = ProgressMetrics()
            self._pending.clear()
            self._stall_event_emitted = False
            self._sending_event_emitted = False
            self._last_state = STATE_STARTING
        self._event_bus.emit_human("session_started", detail=detail)

    def mark_session_stopped(self, *, detail: Optional[str] = None) -> None:
        with self._lock:
            self._session_active = False
            self._error_active = False
            self._error_detail = None
            self._session_started_mono = None
            self._last_state = STATE_STOPPED
        self._event_bus.emit_human("session_stopped", detail=detail)

    def mark_error(self, detail: Optional[str] = None, *, code: str = "ffmpeg_exit_error") -> None:
        with self._lock:
            self._session_active = False
            self._error_active = True
            self._error_detail = detail
            self._last_state = STATE_ERROR
        self._event_bus.emit_human(code, detail=detail)

    def feed_line(self, line: str) -> None:
        text = line.strip()
        if not text or "=" not in text:
            return
        key, _, value = text.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            return

        with self._lock:
            if key == "progress":
                block = dict(self._pending)
                self._pending.clear()
                self._apply_progress_block_locked(block)
                return
            self._pending[key] = value

    def feed_progress_block(self, block: Dict[str, str]) -> None:
        with self._lock:
            self._apply_progress_block_locked(dict(block))

    def _apply_progress_block_locked(self, block: Dict[str, str]) -> None:
        if not block:
            return

        previous = self._metrics
        frame = _safe_int(block.get("frame"))
        fps = _safe_float(block.get("fps"))
        total_size = _safe_int(block.get("total_size"))
        out_time_ms = _safe_int(block.get("out_time_ms"))
        if out_time_ms is None and "out_time_us" in block:
            out_time_us = _safe_int(block.get("out_time_us"))
            if out_time_us is not None:
                out_time_ms = out_time_us // 1000

        bitrate_raw = block.get("bitrate")
        if bitrate_raw is not None:
            parsed_bitrate = _safe_float(bitrate_raw)
            if parsed_bitrate is not None:
                next_bitrate = bitrate_raw
                next_bitrate_kbps = parsed_bitrate
            else:
                next_bitrate = previous.bitrate
                next_bitrate_kbps = previous.bitrate_kbps
        else:
            next_bitrate = previous.bitrate
            next_bitrate_kbps = previous.bitrate_kbps

        speed_raw = block.get("speed")
        if speed_raw is not None:
            cleaned_speed = speed_raw.strip()
            if cleaned_speed and cleaned_speed.lower() != "n/a":
                next_speed = speed_raw
            else:
                next_speed = previous.speed
        else:
            next_speed = previous.speed

        out_time = block.get("out_time")

        advanced = False
        if frame is not None and (previous.frame is None or frame > previous.frame):
            advanced = True
        if total_size is not None and (
            previous.total_size is None or total_size > previous.total_size
        ):
            advanced = True
        if out_time_ms is not None and (
            previous.out_time_ms is None or out_time_ms > previous.out_time_ms
        ):
            advanced = True

        self._metrics = ProgressMetrics(
            frame=frame if frame is not None else previous.frame,
            fps=fps if fps is not None else previous.fps,
            bitrate=next_bitrate,
            bitrate_kbps=next_bitrate_kbps,
            total_size=total_size if total_size is not None else previous.total_size,
            out_time=out_time if out_time is not None else previous.out_time,
            out_time_ms=(
                out_time_ms if out_time_ms is not None else previous.out_time_ms
            ),
            speed=next_speed,
        )

        if advanced and self._session_active:
            self._last_progress_mono = self._monotonic()
            self._error_active = False
            self._error_detail = None

    def rtmps_send_state(self, *, now: Optional[float] = None) -> str:
        current = self._monotonic() if now is None else now
        emit_sending = False
        emit_stall = False

        with self._lock:
            if self._error_active:
                state = STATE_ERROR
            elif not self._session_active:
                state = STATE_STOPPED
            else:
                started = self._session_started_mono
                last = self._last_progress_mono
                if started is None:
                    state = STATE_STOPPED
                elif last is not None and (current - last) <= self._stall_seconds:
                    state = STATE_SENDING
                    if not self._sending_event_emitted:
                        self._sending_event_emitted = True
                        emit_sending = True
                elif (current - started) < self._grace_seconds and last is None:
                    state = STATE_STARTING
                else:
                    state = STATE_NO_PROGRESS
                    if not self._stall_event_emitted:
                        self._stall_event_emitted = True
                        emit_stall = True

            self._last_state = state

        if emit_sending:
            self._event_bus.emit_human("sending")
        if emit_stall:
            self._event_bus.emit_human("no_progress")
        return state

    def metrics_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            metrics = self._metrics
            last_progress = self._last_progress_mono
            started = self._session_started_mono
            session_active = self._session_active
            error_detail = self._error_detail
        state = self.rtmps_send_state()
        return {
            "frame": metrics.frame,
            "fps": metrics.fps,
            "bitrate": metrics.bitrate,
            "bitrate_kbps": metrics.bitrate_kbps,
            "total_size": metrics.total_size,
            "out_time": metrics.out_time,
            "out_time_ms": metrics.out_time_ms,
            "speed": metrics.speed,
            "last_progress_mono": last_progress,
            "session_started_mono": started,
            "session_active": session_active,
            "rtmps_send_state": state,
            "error_detail": error_detail,
        }

    def snapshot_for_status(self) -> Dict[str, Any]:
        data = self.metrics_snapshot()
        data["recent_events"] = self._event_bus.recent(limit=20)
        return data
