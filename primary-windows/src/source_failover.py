"""Failover câmara ↔ vídeo de contingência (sessão UI), sem PySide6."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

# Orçamento interno (não exposto na UI).
STALL_DETECT_S = 6.0
CAMERA_PROBE_TIMEOUT_S = 3.0
INTERNET_TIMEOUT_S = 2.0
RECOVERY_PROBE_INTERVAL_S = 4.0
RECOVERY_SUCCESSES_REQUIRED = 2
FFMPEG_STOP_TIMEOUT_S = 3.0
FIRST_PROGRESS_WAIT_S = 7.0
SWITCH_DEADLINE_S = 32.0
FAILOVER_COOLDOWN_S = 12.0
CLOUD_GRACE_HINT_S = 35.0


class FailoverState(str, Enum):
    CAMERA_ACTIVE = "CAMERA_ACTIVE"
    CAMERA_FAILURE_PENDING = "CAMERA_FAILURE_PENDING"
    DEMO_ACTIVE = "DEMO_ACTIVE"
    CAMERA_RECOVERY_PENDING = "CAMERA_RECOVERY_PENDING"
    FAILOVER_TRANSITION = "FAILOVER_TRANSITION"
    INTERNET_OFFLINE = "INTERNET_OFFLINE"
    STOPPED = "STOPPED"


class FailoverAction(str, Enum):
    KEEP = "KEEP"
    BEGIN_CONFIRM = "BEGIN_CONFIRM"
    ENTER_TRANSITION_TO_DEMO = "ENTER_TRANSITION_TO_DEMO"
    ENTER_TRANSITION_TO_CAMERA = "ENTER_TRANSITION_TO_CAMERA"
    ACTIVATE_DEMO = "ACTIVATE_DEMO"
    ACTIVATE_CAMERA = "ACTIVATE_CAMERA"
    ROLLBACK_TO_DEMO = "ROLLBACK_TO_DEMO"
    ROLLBACK_TRY_CAMERA = "ROLLBACK_TRY_CAMERA"
    MARK_OFFLINE = "MARK_OFFLINE"
    ABORT_TO_CLOUD = "ABORT_TO_CLOUD"
    STOP = "STOP"


@dataclass
class TransitionInfo:
    active: bool = False
    transition_id: Optional[str] = None
    started_at: Optional[float] = None
    deadline: Optional[float] = None
    target: Optional[str] = None  # camera | contingency_demo
    event_at: Optional[float] = None


@dataclass
class FailoverSnapshot:
    state: FailoverState
    effective_source: str
    configured_source: str = "camera"
    transition: TransitionInfo = field(default_factory=TransitionInfo)
    last_camera_ok_at: Optional[float] = None
    last_failover_reason: Optional[str] = None
    last_failover_duration_ms: Optional[int] = None
    failover_switch_count: int = 0
    ui_message: Optional[str] = None
    recovery_successes: int = 0


@dataclass
class FailoverDecision:
    action: FailoverAction
    snapshot: FailoverSnapshot
    reason: Optional[str] = None


class SourceFailoverController:
    """Decide trocas Câmara↔demo com deadline absoluto de 32s."""

    def __init__(
        self,
        *,
        enabled: bool,
        demo_path: str,
        demo_exists: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
        new_transition_id: Optional[Callable[[], str]] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.demo_path = demo_path
        self._demo_exists = demo_exists
        self._monotonic = monotonic
        self._new_id = new_transition_id or (lambda: uuid.uuid4().hex)
        self.state = FailoverState.STOPPED
        self.configured_source = "camera"
        self.effective_source = "camera"
        self.transition = TransitionInfo()
        self.last_camera_ok_at: Optional[float] = None
        self.last_failover_reason: Optional[str] = None
        self.last_failover_duration_ms: Optional[int] = None
        self.failover_switch_count = 0
        self.ui_message: Optional[str] = None
        self._recovery_successes = 0
        self._last_recovery_probe_at: Optional[float] = None
        self._cooldown_until: float = 0.0
        self._failure_event_at: Optional[float] = None
        self._recovery_event_at: Optional[float] = None

    def start_camera_session(self) -> FailoverSnapshot:
        self.state = FailoverState.CAMERA_ACTIVE
        self.configured_source = "camera"
        self.effective_source = "camera"
        self.transition = TransitionInfo()
        self.ui_message = None
        self._recovery_successes = 0
        return self.snapshot()

    def stop(self) -> FailoverSnapshot:
        self.state = FailoverState.STOPPED
        self.transition = TransitionInfo()
        self.ui_message = None
        return self.snapshot()

    def snapshot(self) -> FailoverSnapshot:
        return FailoverSnapshot(
            state=self.state,
            effective_source=self.effective_source,
            configured_source=self.configured_source,
            transition=TransitionInfo(
                active=self.transition.active,
                transition_id=self.transition.transition_id,
                started_at=self.transition.started_at,
                deadline=self.transition.deadline,
                target=self.transition.target,
                event_at=self.transition.event_at,
            ),
            last_camera_ok_at=self.last_camera_ok_at,
            last_failover_reason=self.last_failover_reason,
            last_failover_duration_ms=self.last_failover_duration_ms,
            failover_switch_count=self.failover_switch_count,
            ui_message=self.ui_message,
            recovery_successes=self._recovery_successes,
        )

    def _begin_transition(self, *, target: str, event_at: float) -> None:
        now = self._monotonic()
        self.state = FailoverState.FAILOVER_TRANSITION
        self.transition = TransitionInfo(
            active=True,
            transition_id=self._new_id(),
            started_at=now,
            deadline=event_at + SWITCH_DEADLINE_S,
            target=target,
            event_at=event_at,
        )

    def _clear_transition(self) -> None:
        self.transition = TransitionInfo()

    def _finish_switch(self, *, reason: str, event_at: float) -> None:
        now = self._monotonic()
        duration_ms = int(max(0.0, (now - event_at) * 1000.0))
        self.last_failover_reason = reason
        self.last_failover_duration_ms = duration_ms
        self.failover_switch_count += 1
        self._cooldown_until = now + FAILOVER_COOLDOWN_S
        self._clear_transition()

    def note_camera_ok(self, now: Optional[float] = None) -> None:
        self.last_camera_ok_at = self._monotonic() if now is None else float(now)

    def evaluate(
        self,
        *,
        ffmpeg_running: bool,
        rtmps_state: str,
        last_exit_code: Optional[int],
        internet_online: bool,
        camera_present: Optional[bool],
        seconds_since_progress: Optional[float],
        stop_requested: bool,
    ) -> FailoverDecision:
        now = self._monotonic()
        if stop_requested or self.state == FailoverState.STOPPED:
            snap = self.stop()
            return FailoverDecision(FailoverAction.STOP, snap, reason="stop_requested")

        if not self.enabled:
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        # --- transição em curso ---
        if self.state == FailoverState.FAILOVER_TRANSITION:
            event_at = self.transition.event_at or now
            target = self.transition.target
            if now - event_at > SWITCH_DEADLINE_S:
                self.last_failover_reason = "switch_deadline_exceeded"
                self.ui_message = "A troca de fonte excedeu o tempo limite."
                self._clear_transition()
                if target == "camera" or self.effective_source == "contingency_demo":
                    if self._demo_exists():
                        self.state = FailoverState.DEMO_ACTIVE
                        self.effective_source = "contingency_demo"
                        self.ui_message = "Falha ao recuperar a câmara; a manter vídeo de contingência."
                        return FailoverDecision(
                            FailoverAction.ROLLBACK_TO_DEMO,
                            self.snapshot(),
                            reason="deadline_rollback_demo",
                        )
                self.state = FailoverState.CAMERA_FAILURE_PENDING
                return FailoverDecision(
                    FailoverAction.ABORT_TO_CLOUD,
                    self.snapshot(),
                    reason="switch_deadline_exceeded",
                )

            if (
                ffmpeg_running
                and rtmps_state == "A enviar"
                and target == "contingency_demo"
            ):
                self.state = FailoverState.DEMO_ACTIVE
                self.effective_source = "contingency_demo"
                self.ui_message = "Vídeo de contingência — câmara indisponível"
                self._finish_switch(reason="camera_to_demo", event_at=event_at)
                return FailoverDecision(
                    FailoverAction.ACTIVATE_DEMO, self.snapshot(), reason="demo_sending"
                )
            if ffmpeg_running and rtmps_state == "A enviar" and target == "camera":
                self.state = FailoverState.CAMERA_ACTIVE
                self.effective_source = "camera"
                self.ui_message = None
                self._finish_switch(reason="demo_to_camera", event_at=event_at)
                self.note_camera_ok(now)
                return FailoverDecision(
                    FailoverAction.ACTIVATE_CAMERA,
                    self.snapshot(),
                    reason="camera_sending",
                )
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        # --- Internet offline ---
        if not internet_online and self.state in {
            FailoverState.CAMERA_ACTIVE,
            FailoverState.CAMERA_FAILURE_PENDING,
        }:
            # Não tratar como offline definitivo se ainda estiver a enviar.
            if not (ffmpeg_running and rtmps_state == "A enviar"):
                self.state = FailoverState.INTERNET_OFFLINE
                self.ui_message = "Sem ligação à Internet"
                return FailoverDecision(
                    FailoverAction.MARK_OFFLINE,
                    self.snapshot(),
                    reason="internet_offline",
                )

        if self.state == FailoverState.INTERNET_OFFLINE:
            if internet_online:
                self.state = FailoverState.CAMERA_FAILURE_PENDING
                self.ui_message = "A verificar a câmara…"
                return FailoverDecision(
                    FailoverAction.BEGIN_CONFIRM,
                    self.snapshot(),
                    reason="internet_back",
                )
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        # --- câmara ativa ---
        if self.state == FailoverState.CAMERA_ACTIVE:
            stalled = (
                seconds_since_progress is not None
                and seconds_since_progress >= STALL_DETECT_S
            )
            exited = (not ffmpeg_running) and last_exit_code not in (None, 0)
            stopped_unexpected = not ffmpeg_running
            if stalled or exited or stopped_unexpected:
                self.state = FailoverState.CAMERA_FAILURE_PENDING
                self._failure_event_at = now
                self.ui_message = "A confirmar falha da câmara…"
                return FailoverDecision(
                    FailoverAction.BEGIN_CONFIRM,
                    self.snapshot(),
                    reason="camera_suspect",
                )
            if ffmpeg_running and rtmps_state == "A enviar":
                self.note_camera_ok(now)
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        # --- confirmar falha ---
        if self.state == FailoverState.CAMERA_FAILURE_PENDING:
            if now < self._cooldown_until:
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())
            if camera_present is True and ffmpeg_running and rtmps_state == "A enviar":
                self.state = FailoverState.CAMERA_ACTIVE
                self.ui_message = None
                self.note_camera_ok(now)
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())
            if not internet_online:
                self.state = FailoverState.INTERNET_OFFLINE
                self.ui_message = "Sem ligação à Internet"
                return FailoverDecision(
                    FailoverAction.MARK_OFFLINE,
                    self.snapshot(),
                    reason="internet_offline",
                )
            if camera_present is False:
                if not self._demo_exists():
                    self.ui_message = "Vídeo de contingência indisponível"
                    return FailoverDecision(
                        FailoverAction.KEEP, self.snapshot(), reason="demo_missing"
                    )
                event_at = self._failure_event_at or now
                self._begin_transition(target="contingency_demo", event_at=event_at)
                self.ui_message = "A mudar para vídeo de contingência…"
                return FailoverDecision(
                    FailoverAction.ENTER_TRANSITION_TO_DEMO,
                    self.snapshot(),
                    reason="camera_failed",
                )
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        # --- demo ativo / recuperação ---
        if self.state == FailoverState.DEMO_ACTIVE:
            self.effective_source = "contingency_demo"
            self.ui_message = "Vídeo de contingência — câmara indisponível"
            due = (
                self._last_recovery_probe_at is None
                or (now - self._last_recovery_probe_at) >= RECOVERY_PROBE_INTERVAL_S
            )
            if not due:
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())
            self.state = FailoverState.CAMERA_RECOVERY_PENDING
            self.ui_message = "A recuperar câmara"
            # Continua para avaliar a sonda neste mesmo ciclo se já estiver disponível.

        if self.state == FailoverState.CAMERA_RECOVERY_PENDING:
            self.effective_source = "contingency_demo"
            due = (
                self._last_recovery_probe_at is None
                or (now - self._last_recovery_probe_at) >= RECOVERY_PROBE_INTERVAL_S
            )
            if not due:
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())
            if camera_present is None:
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())

            self._last_recovery_probe_at = now
            if camera_present is True:
                if self._recovery_event_at is None:
                    self._recovery_event_at = now
                self._recovery_successes += 1
                self.ui_message = "A recuperar câmara"
                if self._recovery_successes >= RECOVERY_SUCCESSES_REQUIRED:
                    if now < self._cooldown_until:
                        return FailoverDecision(FailoverAction.KEEP, self.snapshot())
                    event_at = self._recovery_event_at or now
                    self._begin_transition(target="camera", event_at=event_at)
                    self._recovery_successes = 0
                    self.ui_message = "A regressar à câmara…"
                    return FailoverDecision(
                        FailoverAction.ENTER_TRANSITION_TO_CAMERA,
                        self.snapshot(),
                        reason="camera_recovered",
                    )
                return FailoverDecision(FailoverAction.KEEP, self.snapshot())

            self._recovery_successes = 0
            self._recovery_event_at = None
            self.state = FailoverState.DEMO_ACTIVE
            self.ui_message = "Vídeo de contingência — câmara indisponível"
            return FailoverDecision(FailoverAction.KEEP, self.snapshot())

        return FailoverDecision(FailoverAction.KEEP, self.snapshot())

    def mark_demo_started_failed(
        self, *, camera_present: Optional[bool]
    ) -> FailoverDecision:
        """Rollback quando o demo não arranca após matar a câmara."""

        if camera_present is True:
            # Mantém transição ativa (novo id) para a tentativa de regresso à câmara.
            self._begin_transition(
                target="camera", event_at=self._failure_event_at or self._monotonic()
            )
            self.ui_message = "Falha no vídeo de contingência; a tentar a câmara…"
            return FailoverDecision(
                FailoverAction.ROLLBACK_TRY_CAMERA,
                self.snapshot(),
                reason="demo_start_failed_try_camera",
            )
        self._clear_transition()
        self.state = FailoverState.CAMERA_FAILURE_PENDING
        self.ui_message = "Falha no vídeo de contingência."
        self._cooldown_until = self._monotonic() + FAILOVER_COOLDOWN_S
        return FailoverDecision(
            FailoverAction.ABORT_TO_CLOUD, self.snapshot(), reason="demo_start_failed"
        )

    def mark_camera_start_failed(self) -> FailoverDecision:
        """Rollback para demo se a câmara não arrancar."""

        event_at = self.transition.event_at or self._monotonic()
        self._begin_transition(target="contingency_demo", event_at=event_at)
        self.ui_message = (
            "Falha ao regressar à câmara; a restaurar vídeo de contingência…"
        )
        return FailoverDecision(
            FailoverAction.ROLLBACK_TO_DEMO,
            self.snapshot(),
            reason="camera_start_failed",
        )


def effective_source_ui_label(snapshot: FailoverSnapshot) -> str:
    if snapshot.state == FailoverState.INTERNET_OFFLINE:
        return "Sem ligação à Internet"
    if snapshot.ui_message == "Vídeo de contingência indisponível":
        return "Vídeo de contingência indisponível"
    if snapshot.state == FailoverState.CAMERA_RECOVERY_PENDING:
        return "A recuperar câmara"
    if snapshot.effective_source == "contingency_demo":
        return "Vídeo de contingência — câmara indisponível"
    if snapshot.effective_source == "demo":
        return "Vídeo de demonstração"
    return "Câmara"
