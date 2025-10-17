#!/usr/bin/env python3
"""HTTP status monitor for the secondary droplet.

Receives heartbeat reports from the Windows primary sender and toggles the
YouTube fallback service depending on the presence of those heartbeats.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import pwd
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

LOGGER = logging.getLogger("bwb_status_monitor")

DEFAULT_MODE_FILE = Path("/run/youtube-fallback/mode")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(ts: dt.datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc).isoformat()


@dataclass
class MonitorSettings:
    """Configuration for the heartbeat monitor."""

    bind: str = "0.0.0.0"
    port: int = 8080
    missed_threshold: int = 40
    check_interval: int = 5
    log_file: Path = Path("/var/log/bwb_status_monitor.log")
    secondary_service: str = "youtube-fallback.service"
    auth_token: Optional[str] = None
    require_token: bool = False
    mode_file: Path = DEFAULT_MODE_FILE
    camera_ping_host: Optional[str] = None
    camera_ping_interval: int = 30
    camera_ping_count: int = 1
    camera_ping_timeout: float = 1.2
    camera_ping_command: Optional[str] = None
    refresh_on_stop: bool = False
    refresh_token_path: Path = Path("/root/token.json")
    refresh_cooldown: int = 120

    @classmethod
    def from_env(cls) -> "MonitorSettings":
        def _get_env(*names: str) -> Optional[str]:
            for name in names:
                value = os.environ.get(name)
                if value is not None:
                    return value
            return None

        def _int(names: tuple[str, ...], default: int) -> int:
            source = None
            raw = None
            for name in names:
                value = os.environ.get(name)
                if value is not None:
                    source = name
                    raw = value
                    break
            if raw is None:
                return default
            try:
                value = int(raw)
            except (TypeError, ValueError):
                LOGGER.warning(
                    "Valor inválido em %s=%r; utilizando %s",
                    source,
                    raw,
                    default,
                )
                return default
            if value <= 0:
                LOGGER.warning(
                    "Valor não positivo em %s=%r; utilizando %s",
                    source,
                    raw,
                    default,
                )
                return default
            return value

        def _float(names: tuple[str, ...], default: float) -> float:
            source = None
            raw = None
            for name in names:
                value = os.environ.get(name)
                if value is not None:
                    source = name
                    raw = value
                    break
            if raw is None:
                return default
            try:
                value = float(raw)
            except (TypeError, ValueError):
                LOGGER.warning(
                    "Valor inválido em %s=%r; utilizando %s",
                    source,
                    raw,
                    default,
                )
                return default
            if value <= 0:
                LOGGER.warning(
                    "Valor não positivo em %s=%r; utilizando %s",
                    source,
                    raw,
                    default,
                )
                return default
            return value

        bind = _get_env("YTR_BIND", "BWB_STATUS_BIND") or "0.0.0.0"
        port = _int(("YTR_PORT", "BWB_STATUS_PORT"), 8080)
        missed_threshold = _int(("YTR_MISSED_THRESHOLD", "BWB_STATUS_MISSED_THRESHOLD"), 40)
        check_interval = _int(("YTR_CHECK_INTERVAL", "BWB_STATUS_CHECK_INTERVAL"), 5)

        log_override = _get_env("YTR_LOG_FILE", "BWB_STATUS_LOG_FILE")
        secondary_override = _get_env("YTR_SECONDARY_SERVICE", "BWB_STATUS_SECONDARY_SERVICE")
        mode_override = _get_env(
            "YTR_FALLBACK_MODE_FILE", "BWB_STATUS_FALLBACK_MODE_FILE"
        )

        log_path = Path(log_override or cls.log_file.as_posix())
        secondary_service = secondary_override or cls.secondary_service
        if mode_override:
            mode_file = Path(mode_override).expanduser()
        else:
            mode_file = cls.mode_file
        token = _get_env("YTR_TOKEN", "BWB_STATUS_TOKEN")
        camera_ping_host = _get_env(
            "YTR_CAMERA_PING_HOST", "BWB_STATUS_CAMERA_PING_HOST"
        )
        camera_ping_command = _get_env(
            "YTR_CAMERA_PING_COMMAND", "BWB_STATUS_CAMERA_PING_COMMAND"
        )
        camera_ping_interval = _int(
            ("YTR_CAMERA_PING_INTERVAL", "BWB_STATUS_CAMERA_PING_INTERVAL"),
            cls.camera_ping_interval,
        )
        camera_ping_count = _int(
            ("YTR_CAMERA_PING_COUNT", "BWB_STATUS_CAMERA_PING_COUNT"),
            cls.camera_ping_count,
        )
        camera_ping_timeout = _float(
            ("YTR_CAMERA_PING_TIMEOUT", "BWB_STATUS_CAMERA_PING_TIMEOUT"),
            cls.camera_ping_timeout,
        )

        def _maybe_bool(name: str) -> Optional[bool]:
            raw = os.environ.get(name)
            if raw is None:
                return None
            normalized = raw.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            LOGGER.warning(
                "Valor inválido em %s=%r; utilizando predefinição", name, raw
            )
            return None

        ytr_require = _maybe_bool("YTR_REQUIRE_TOKEN")
        bwb_require = (
            _maybe_bool("BWB_STATUS_REQUIRE_TOKEN") if ytr_require is None else None
        )
        require_token = (
            ytr_require
            if ytr_require is not None
            else bwb_require if bwb_require is not None else bool(token)
        )
        if require_token is None:
            require_token = bool(token)

        if require_token and not token:
            LOGGER.warning(
                "Autenticação Bearer exigida, mas nenhuma variável YTR_TOKEN/BWB_STATUS_TOKEN foi definida."
            )

        if camera_ping_interval <= 0:
            camera_ping_interval = cls.camera_ping_interval
        if camera_ping_count <= 0:
            camera_ping_count = cls.camera_ping_count
        if camera_ping_timeout <= 0:
            camera_ping_timeout = cls.camera_ping_timeout

        refresh_flag = _maybe_bool("YTR_REFRESH_ON_STOP")
        refresh_on_stop = (
            refresh_flag
            if refresh_flag is not None
            else cls.refresh_on_stop
        )

        refresh_token_raw = _get_env(
            "YTR_REFRESH_TOKEN_PATH",
            "YT_OAUTH_TOKEN_PATH",
        )
        refresh_token_path = (
            Path(refresh_token_raw).expanduser()
            if refresh_token_raw
            else cls.refresh_token_path
        )

        refresh_cooldown = _int(("YTR_REFRESH_COOLDOWN",), cls.refresh_cooldown)

        return cls(
            bind=bind,
            port=port,
            missed_threshold=missed_threshold,
            check_interval=check_interval,
            log_file=log_path,
            secondary_service=secondary_service,
            auth_token=token if token else None,
            require_token=require_token,
            mode_file=mode_file,
            camera_ping_host=camera_ping_host or None,
            camera_ping_interval=camera_ping_interval,
            camera_ping_count=camera_ping_count,
            camera_ping_timeout=camera_ping_timeout,
            camera_ping_command=camera_ping_command or None,
            refresh_on_stop=bool(refresh_on_stop),
            refresh_token_path=refresh_token_path,
            refresh_cooldown=refresh_cooldown,
        )


@dataclass
class StatusEntry:
    timestamp: dt.datetime
    machine_id: str
    payload: Dict[str, Any]
    remote_addr: str
    raw_body: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": isoformat(self.timestamp),
            "machine_id": self.machine_id,
            "remote_addr": self.remote_addr,
            "payload": self.payload,
        }


@dataclass
class ServiceManager:
    name: str
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _systemctl_cmd(self, *args: str) -> list[str]:
        base_cmd = ["/usr/bin/systemctl", "--no-ask-password", *args, self.name]
        if os.geteuid() == 0:
            return base_cmd
        return ["/usr/bin/sudo", "-n", *base_cmd]

    def _run_systemctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = self._systemctl_cmd(*args)
        LOGGER.debug("Executando: %s", " ".join(cmd))
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    @staticmethod
    def _systemctl_message(result: subprocess.CompletedProcess[str]) -> str:
        message = result.stderr.strip() or result.stdout.strip()
        if not message:
            message = f"systemctl retornou código {result.returncode}"
        return message

    def _log_failure(
        self, action: str, result: subprocess.CompletedProcess[str]
    ) -> None:
        message = self._systemctl_message(result)
        LOGGER.error("Falha ao %s %s: %s", action, self.name, message)
        if "no new privileges" in message.lower():
            LOGGER.error(
                "A conta actual não consegue usar sudo devido a NoNewPrivileges=true; "
                "revise a unit yt-restapi.service para permitir o fallback."
            )

    def ensure_started(self) -> bool:
        with self._lock:
            status = subprocess.run(
                self._systemctl_cmd("is-active"),
                check=False,
                capture_output=True,
                text=True,
            )
            if status.returncode == 0 and status.stdout.strip() == "active":
                LOGGER.debug("Serviço %s já está ativo", self.name)
                return True

            result = self._run_systemctl("start")
            if result.returncode != 0:
                self._log_failure("iniciar", result)
                return False

            LOGGER.info("Serviço %s iniciado", self.name)
            return True

    def ensure_stopped(self) -> bool:
        with self._lock:
            status = subprocess.run(
                self._systemctl_cmd("is-active"),
                check=False,
                capture_output=True,
                text=True,
            )
            if status.returncode != 0 or status.stdout.strip() == "inactive":
                LOGGER.debug("Serviço %s já está inativo", self.name)
                return True

            result = self._run_systemctl("stop")
            if result.returncode != 0:
                self._log_failure("parar", result)
                return False

            LOGGER.info("Serviço %s parado", self.name)
            return True


class YouTubeRefresher:
    """Refresh the primary YouTube ingest via the Live Streaming API."""

    SCOPES: tuple[str, ...] = (
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.readonly",
    )

    def __init__(
        self,
        token_path: Path,
        cooldown_seconds: int = 120,
        transitions: Iterable[str] = ("testing", "live"),
    ) -> None:
        self._token_path = Path(token_path)
        self._cooldown = max(int(cooldown_seconds), 0)
        normalized = [str(value).strip().lower() for value in transitions if value]
        self._transitions = tuple(normalized) or ("live",)
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._current_thread: Optional[threading.Thread] = None
        self._token_missing_logged = False
        self._import_error_logged = False

    @classmethod
    def from_settings(cls, settings: MonitorSettings) -> Optional["YouTubeRefresher"]:
        if not settings.refresh_on_stop:
            return None
        return cls(
            token_path=settings.refresh_token_path,
            cooldown_seconds=settings.refresh_cooldown,
        )

    def request_refresh(self) -> None:
        with self._lock:
            now = time.monotonic()
            if self._current_thread and self._current_thread.is_alive():
                LOGGER.debug(
                    "Refresh da ingestão primária já em andamento; ignorando novo pedido."
                )
                return
            if self._cooldown and now - self._last_request < self._cooldown:
                remaining = self._cooldown - (now - self._last_request)
                LOGGER.debug(
                    "Ignorando refresh da ingestão primária (cooldown %.1fs restante).",
                    remaining,
                )
                return
            self._last_request = now
            thread = threading.Thread(
                target=self._run, name="yt-refresh", daemon=True
            )
            self._current_thread = thread

        thread.start()

    def _run(self) -> None:
        try:
            LOGGER.info(
                "Solicitando refresh da ingestão primária via API do YouTube."
            )
            self._perform_refresh()
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception(
                "Erro ao executar refresh da ingestão primária: %s", exc
            )
        finally:
            with self._lock:
                self._current_thread = None

    def _perform_refresh(self) -> None:
        client = self._build_client()
        if client is None:
            return

        broadcast = self._select_broadcast(client)
        if not broadcast:
            LOGGER.warning(
                "Nenhuma transmissão activa encontrada para refresh da ingestão primária."
            )
            return

        broadcast_id = broadcast.get("id")
        if not broadcast_id:
            LOGGER.warning("Transmissão activa sem ID; refresh ignorado.")
            return

        lifecycle = str(
            broadcast.get("status", {}).get("lifeCycleStatus", "")
        ).lower()

        targets: list[str] = []
        for target in self._transitions:
            if target == "testing" and lifecycle == "testing":
                continue
            targets.append(target)
        if not targets:
            targets.append("live")

        for target in targets:
            self._attempt_transition(client, broadcast_id, target)

    def _build_client(self) -> Optional[Any]:
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            if not self._import_error_logged:
                LOGGER.warning(
                    "Bibliotecas google-api indisponíveis; refresh primário ignorado."
                )
                self._import_error_logged = True
            return None

        if not self._token_path.exists():
            if not self._token_missing_logged:
                LOGGER.warning(
                    "Token OAuth %s não encontrado; refresh ignorado.",
                    self._token_path,
                )
                self._token_missing_logged = True
            return None

        try:
            credentials = Credentials.from_authorized_user_file(
                str(self._token_path), self.SCOPES
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Não foi possível carregar credenciais do OAuth %s: %s",
                self._token_path,
                exc,
            )
            return None

        try:
            return build(
                "youtube", "v3", credentials=credentials, cache_discovery=False
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Falha ao construir cliente YouTube: %s", exc)
            return None

    @staticmethod
    def _select_broadcast(client: Any) -> Optional[Dict[str, Any]]:
        try:
            response = (
                client.liveBroadcasts()
                .list(
                    part="id,status",
                    broadcastStatus="active",
                    mine=True,
                    maxResults=25,
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Falha ao listar transmissões activas: %s", exc)
            return None

        items = response.get("items", [])
        if not items:
            return None

        order = {"live": 0, "testing": 1, "ready": 2, "created": 3, "scheduled": 4}

        def _priority(entry: Dict[str, Any]) -> int:
            lifecycle = str(
                entry.get("status", {}).get("lifeCycleStatus", "")
            ).lower()
            return order.get(lifecycle, 99)

        return min(items, key=_priority)

    def _attempt_transition(self, client: Any, broadcast_id: str, target: str) -> None:
        try:
            from googleapiclient.errors import HttpError
        except ImportError:
            LOGGER.warning(
                "Biblioteca googleapiclient indisponível; não foi possível transicionar transmissão %s.",
                broadcast_id,
            )
            return

        try:
            (
                client.liveBroadcasts()
                .transition(part="status", broadcastStatus=target, id=broadcast_id)
                .execute()
            )
            LOGGER.info(
                "Transmissão %s transicionada para estado %s via API.",
                broadcast_id,
                target,
            )
        except HttpError as exc:
            LOGGER.warning(
                "YouTube rejeitou transição %s→%s: %s",
                broadcast_id,
                target,
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Erro inesperado ao transicionar %s→%s: %s",
                broadcast_id,
                target,
                exc,
            )


class StatusMonitor:
    def __init__(
        self,
        settings: MonitorSettings,
        service_manager: ServiceManager,
        refresher: Optional[YouTubeRefresher] = None,
    ) -> None:
        self._settings = settings
        self._service_manager = service_manager
        self._refresher = refresher or YouTubeRefresher.from_settings(settings)
        self._lock = threading.Lock()
        self._last_timestamp: Optional[dt.datetime] = None
        self._started_at = utc_now()
        self._fallback_active = False
        self._fallback_reason: Optional[str] = None
        self._last_camera_status: Optional[Dict[str, Any]] = None
        self._mode_file = settings.mode_file
        self._stop_event = threading.Event()
        self._camera_ping_host = settings.camera_ping_host
        self._camera_ping_interval = max(1, int(settings.camera_ping_interval))
        self._camera_ping_count = max(1, int(settings.camera_ping_count))
        self._camera_ping_timeout = max(0.5, float(settings.camera_ping_timeout))
        self._ping_command = self._resolve_ping_command(settings.camera_ping_command)
        self._ping_unavailable_logged = False
        self._last_ping_result: Optional[bool] = None
        self._last_ping_checked: Optional[dt.datetime] = None
        self._last_ping_success: Optional[dt.datetime] = None
        self._last_ping_failure: Optional[dt.datetime] = None
        self._last_ping_error: Optional[str] = None
        self._last_ping_rtt_ms: Optional[float] = None
        self._watcher_thread = threading.Thread(
            target=self._watchdog_loop, name="bwb-status-watchdog", daemon=True
        )
        LOGGER.debug("StatusMonitor inicializado com %s", self._settings)

    def start(self) -> None:
        if not self._watcher_thread.is_alive():
            self._watcher_thread.start()
            LOGGER.info(
                "Watchdog iniciado (limite=%ss, verificação=%ss)",
                self._settings.missed_threshold,
                self._settings.check_interval,
            )

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._watcher_thread.is_alive():
            self._watcher_thread.join(timeout=self._settings.check_interval + 1)

    @property
    def settings(self) -> MonitorSettings:
        return self._settings

    @property
    def fallback_active(self) -> bool:
        with self._lock:
            return self._fallback_active

    def record_status(self, entry: StatusEntry) -> None:
        camera_present, camera_snapshot = self._extract_camera_status(entry.payload)
        ping_result = self._refresh_camera_ping()
        if ping_result is False:
            camera_present = False
            camera_snapshot["present"] = False
            camera_snapshot["ping_override"] = True
        elif ping_result is True:
            camera_snapshot["ping_override"] = False
        ping_snapshot = self._build_ping_snapshot()
        if ping_snapshot is not None:
            camera_snapshot["network_ping"] = ping_snapshot

        with self._lock:
            self._last_timestamp = entry.timestamp
            self._last_camera_status = camera_snapshot
            fallback_active = self._fallback_active
            fallback_reason = self._fallback_reason

        if not camera_present:
            self._ensure_camera_fallback(fallback_active, fallback_reason)
            return

        if fallback_active:
            self._stop_fallback("Heartbeat recebido; solicitando parada do fallback.")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            reference = self._last_timestamp or self._started_at
            now = utc_now()
            elapsed = (now - reference).total_seconds()
            raw_snapshot = (
                dict(self._last_camera_status)
                if isinstance(self._last_camera_status, dict)
                else {}
            )
            fallback_reason = self._fallback_reason
            fallback_active = self._fallback_active
            last_timestamp = (
                isoformat(self._last_timestamp) if self._last_timestamp else None
            )

        stale = elapsed >= self._settings.missed_threshold
        age_seconds = round(elapsed, 1)

        snapshot: Dict[str, Any] = {}
        for key, value in raw_snapshot.items():
            if isinstance(key, str):
                snapshot[key] = value

        present_value = snapshot.get("present")
        last_known = snapshot.get("last_known_present")
        if isinstance(present_value, bool):
            last_known = present_value
        elif isinstance(last_known, bool):
            snapshot.setdefault("last_known_present", last_known)
        else:
            last_known = None

        snapshot["age_seconds"] = age_seconds
        snapshot["stale"] = stale
        if last_known is not None:
            snapshot["last_known_present"] = last_known

        if stale:
            snapshot["present"] = False
        elif isinstance(present_value, bool):
            snapshot["present"] = present_value
        elif isinstance(last_known, bool):
            snapshot["present"] = last_known
        else:
            snapshot["present"] = False

        ping_snapshot = self._build_ping_snapshot()
        if ping_snapshot is not None:
            snapshot["network_ping"] = ping_snapshot
            reachable = ping_snapshot.get("reachable")
            if reachable is False:
                snapshot["present"] = False

        return {
            "last_timestamp": last_timestamp,
            "fallback_active": fallback_active,
            "seconds_since_last_heartbeat": elapsed,
            "missed_threshold": self._settings.missed_threshold,
            "fallback_reason": fallback_reason,
            "mode_file": self._mode_file.as_posix(),
            "last_camera_signal": snapshot,
        }

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            self._evaluate_threshold()
            self._stop_event.wait(timeout=self._settings.check_interval)

    def _evaluate_threshold(self) -> None:
        with self._lock:
            reference = self._last_timestamp or self._started_at
            elapsed = (utc_now() - reference).total_seconds()
            fallback_active = self._fallback_active
            fallback_reason = self._fallback_reason

        if elapsed >= self._settings.missed_threshold:
            if fallback_reason == "no_camera_signal":
                return
            if not fallback_active or fallback_reason != "no_heartbeats":
                self._activate_missing_heartbeats(int(elapsed))
        else:
            LOGGER.debug(
                "Heartbeat recente ha %.1fs; fallback desnecessario", elapsed
            )

    def _write_mode_file(self, mode: str) -> None:
        path = self._mode_file
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOGGER.warning(
                "Não foi possível preparar diretório para %s: %s", path, exc
            )
            return
        try:
            path.write_text(f"{mode.strip().lower()}\n", encoding="utf-8")
        except OSError as exc:
            LOGGER.warning(
                "Não foi possível escrever modo de fallback em %s: %s", path, exc
            )
            if exc.errno in {errno.EACCES, errno.EROFS}:
                LOGGER.error(
                    "A conta atual (%s) não tem permissões para escrever em %s. "
                    "Garanta que yt-restapi.service pré-cria /run/youtube-fallback/mode "
                    "com permissões de escrita para a conta yt-restapi ou defina "
                    "YTR_FALLBACK_MODE_FILE para um caminho acessível.",
                    pwd.getpwuid(os.geteuid()).pw_name if hasattr(pwd, "getpwuid") else os.geteuid(),
                    path,
                )

    @staticmethod
    def _extract_camera_status(payload: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
        status = payload.get("status")
        snapshot: Dict[str, Any] = {}
        present: Optional[bool] = None
        stale = False

        if isinstance(status, dict):
            camera_info = status.get("camera_signal")
            if isinstance(camera_info, dict):
                for key, value in camera_info.items():
                    if isinstance(key, str):
                        snapshot[key] = value
                raw_present = snapshot.get("present")
                if isinstance(raw_present, bool):
                    present = raw_present
                last_known = snapshot.get("last_known_present")
                if present is None and isinstance(last_known, bool):
                    present = last_known
                raw_stale = snapshot.get("stale")
                if isinstance(raw_stale, bool):
                    stale = raw_stale
            elif isinstance(camera_info, bool):
                present = camera_info
                snapshot["present"] = present

        if stale:
            present = False

        if present is None:
            present = False

        snapshot["present"] = present
        snapshot.setdefault("stale", stale)

        return present, snapshot

    def _resolve_ping_command(self, explicit: Optional[str]) -> Optional[str]:
        candidates: list[str] = []
        if explicit:
            candidates.append(explicit)
        candidates.extend(["/bin/ping", "/usr/bin/ping", "ping"])
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists() and os.access(path, os.X_OK):
                return path.as_posix()
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    def _build_ping_snapshot(self) -> Optional[Dict[str, Any]]:
        host = self._camera_ping_host
        if not host:
            return None

        with self._lock:
            last_checked = self._last_ping_checked
            last_result = self._last_ping_result
            last_success = self._last_ping_success
            last_failure = self._last_ping_failure
            last_error = self._last_ping_error
            last_rtt = self._last_ping_rtt_ms

        snapshot: Dict[str, Any] = {
            "host": host,
            "reachable": last_result,
            "interval_seconds": self._camera_ping_interval,
            "timeout_seconds": self._camera_ping_timeout,
            "count": self._camera_ping_count,
            "last_checked": isoformat(last_checked) if last_checked else None,
            "last_success": isoformat(last_success) if last_success else None,
            "last_failure": isoformat(last_failure) if last_failure else None,
            "last_error": last_error,
            "rtt_ms": last_rtt,
        }
        if last_checked:
            snapshot["age_seconds"] = round(
                (utc_now() - last_checked).total_seconds(), 1
            )
        return snapshot

    def _refresh_camera_ping(self) -> Optional[bool]:
        host = self._camera_ping_host
        if not host:
            return None

        now = utc_now()
        with self._lock:
            last_checked = self._last_ping_checked
            last_result = self._last_ping_result
        if last_checked is not None:
            elapsed = (now - last_checked).total_seconds()
            if elapsed < self._camera_ping_interval:
                return last_result

        reachable, rtt_ms, error = self._ping_host(host)
        timestamp = utc_now()

        with self._lock:
            self._last_ping_checked = timestamp
            self._last_ping_result = reachable
            self._last_ping_error = error
            self._last_ping_rtt_ms = rtt_ms
            if reachable:
                self._last_ping_success = timestamp
            elif reachable is False:
                self._last_ping_failure = timestamp

        if reachable is None:
            if error and not self._ping_unavailable_logged:
                LOGGER.warning("Ping para %s indisponível: %s", host, error)
                self._ping_unavailable_logged = True
            return None

        if reachable:
            if rtt_ms is not None:
                LOGGER.debug("Ping à câmara %s bem sucedido (%.2f ms).", host, rtt_ms)
            else:
                LOGGER.debug("Ping à câmara %s bem sucedido.", host)
        else:
            if error:
                LOGGER.warning("Ping à câmara %s falhou: %s", host, error)
            else:
                LOGGER.warning("Ping à câmara %s falhou sem mensagem de erro.", host)

        return reachable

    def _ping_host(self, host: str) -> tuple[Optional[bool], Optional[float], Optional[str]]:
        command = self._ping_command
        if not command:
            return None, None, "comando ping não encontrado"

        timeout = max(self._camera_ping_timeout, 0.5)
        count = max(self._camera_ping_count, 1)
        deadline = timeout * count + 1.0
        args = [
            command,
            "-n",
            "-c",
            str(count),
            "-W",
            str(int(math.ceil(timeout))),
            host,
        ]
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=deadline,
            )
        except subprocess.TimeoutExpired:
            return False, None, f"timeout após {deadline:.1f}s"
        except FileNotFoundError as exc:
            return None, None, f"comando ping ausente: {exc}"
        except Exception as exc:  # noqa: BLE001
            return False, None, f"{exc.__class__.__name__}: {exc}"

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        reachable = completed.returncode == 0

        error: Optional[str] = None
        if not reachable:
            error = stderr or stdout or f"exit {completed.returncode}"

        rtt_ms: Optional[float] = None
        if stdout:
            for line in stdout.splitlines():
                match = re.search(r"time[=<]([0-9]+(?:\.[0-9]+)?)\s*ms", line)
                if match:
                    try:
                        rtt_ms = float(match.group(1))
                    except ValueError:
                        rtt_ms = None
                    break

        return reachable, rtt_ms, error

    def _stop_fallback(self, message: str) -> None:
        LOGGER.info(message)
        if self._service_manager.ensure_stopped():
            with self._lock:
                self._fallback_active = False
                self._fallback_reason = None
            self._write_mode_file("life")
            if self._refresher:
                self._refresher.request_refresh()
        else:
            LOGGER.warning(
                "Falha ao parar fallback; nova tentativa ocorrerá no próximo heartbeat."
            )
            with self._lock:
                self._fallback_active = True

    def _ensure_camera_fallback(
        self, fallback_active: bool, fallback_reason: Optional[str]
    ) -> None:
        if fallback_active and fallback_reason == "no_camera_signal":
            return

        restart_required = fallback_active and fallback_reason != "no_camera_signal"
        if restart_required:
            LOGGER.info(
                "Heartbeat indica ausência de sinal da câmara; reiniciando fallback em modo SMPTE."
            )
            if not self._service_manager.ensure_stopped():
                LOGGER.warning(
                    "Falha ao reiniciar fallback em modo SMPTE; nova tentativa ocorrerá no próximo heartbeat."
                )
                with self._lock:
                    self._fallback_active = True
                    self._fallback_reason = fallback_reason
                return
        else:
            LOGGER.info(
                "Heartbeat indica ausência de sinal da câmara; ativando fallback em modo SMPTE."
            )

        self._write_mode_file("smptehdbars")
        if self._service_manager.ensure_started():
            with self._lock:
                self._fallback_active = True
                self._fallback_reason = "no_camera_signal"
            if restart_required:
                LOGGER.info(
                    "Fallback reiniciado em modo SMPTE devido à ausência de sinal da câmara."
                )
            else:
                LOGGER.info(
                    "Fallback ativado em modo SMPTE devido à ausência de sinal da câmara."
                )
        else:
            LOGGER.warning(
                "Não foi possível iniciar o fallback em modo SMPTE; nova tentativa ocorrerá no próximo heartbeat."
            )
            with self._lock:
                self._fallback_active = False
                self._fallback_reason = None

    def _activate_missing_heartbeats(self, elapsed: int) -> None:
        LOGGER.warning(
            "Sem heartbeats há %s segundos; solicitando fallback.", elapsed
        )
        self._write_mode_file("life")
        if self._service_manager.ensure_started():
            with self._lock:
                self._fallback_active = True
                self._fallback_reason = "no_heartbeats"
            LOGGER.info("Fallback ativado por ausência de heartbeats.")
        else:
            LOGGER.warning(
                "Não foi possível iniciar o fallback; nova tentativa ocorrerá se o silêncio persistir."
            )
            with self._lock:
                self._fallback_active = False
                self._fallback_reason = None


class StatusHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "BWBStatusMonitor/1.0"
    protocol_version = "HTTP/1.1"

    def _authenticate(self) -> bool:
        settings = self.server.monitor.settings  # type: ignore[attr-defined]
        token = settings.auth_token
        if not token:
            return not settings.require_token
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        candidate = header.removeprefix("Bearer ").strip()
        return candidate == token

    def _send_json(
        self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(
        self,
    ) -> None:  # noqa: N802 - method name mandated by BaseHTTPRequestHandler
        if self.path.rstrip("/") != "/status":
            self._send_json(
                {"error": "recurso desconhecido"}, status=HTTPStatus.NOT_FOUND
            )
            return

        if not self._authenticate():
            self._send_json(
                {"error": "token ausente ou inválido"}, status=HTTPStatus.FORBIDDEN
            )
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "json inválido"}, status=HTTPStatus.BAD_REQUEST)
            return

        machine_id = payload.get("machine_id")
        if not isinstance(machine_id, str) or not machine_id:
            self._send_json(
                {"error": "machine_id ausente"}, status=HTTPStatus.BAD_REQUEST
            )
            return

        entry = StatusEntry(
            timestamp=utc_now(),
            machine_id=machine_id,
            payload=payload,
            remote_addr=self.client_address[0],
            raw_body=raw_body.decode("utf-8", errors="replace"),
        )
        LOGGER.debug("Heartbeat recebido de %s", machine_id)
        self.server.monitor.record_status(entry)  # type: ignore[attr-defined]

        snapshot = self.server.monitor.snapshot()  # type: ignore[attr-defined]
        response = {
            "ok": True,
            "server_time": isoformat(utc_now()),
            "fallback_active": snapshot["fallback_active"],
            "seconds_since_last_heartbeat": snapshot["seconds_since_last_heartbeat"],
            "missed_threshold": snapshot["missed_threshold"],
        }
        self._send_json(response)

    def do_GET(self) -> None:  # noqa: N802
        normalized_path = self.path.rstrip("/") or "/"
        if normalized_path in {"/", "/healthz"}:
            self._send_json({"status": "ok", "server_time": isoformat(utc_now())})
            return
        if normalized_path == "/status":
            snapshot = self.server.monitor.snapshot()  # type: ignore[attr-defined]
            self._send_json(snapshot)
            return
        self._send_json({"error": "recurso desconhecido"}, status=HTTPStatus.NOT_FOUND)

    def log_message(
        self, format: str, *args: Any
    ) -> None:  # noqa: A003 - signature defined upstream
        LOGGER.info("%s - %s", self.client_address[0], format % args)


class StatusHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, monitor: StatusMonitor):
        super().__init__(server_address, RequestHandlerClass)
        self.monitor = monitor


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BWB status monitor service")
    parser.add_argument(
        "--bind", default=None, help="Endereço de bind (default: env ou 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Porta TCP (default: env ou 8080)"
    )
    parser.add_argument(
        "--graceful-timeout",
        type=int,
        default=10,
        help="Tempo para aguardar o encerramento após SIGTERM",
    )
    return parser.parse_args()


def run_server(settings: MonitorSettings, args: argparse.Namespace) -> None:
    bind = args.bind or settings.bind
    port = args.port or settings.port

    configure_logging(settings.log_file)

    LOGGER.info("Iniciando monitor em %s:%s", bind, port)
    LOGGER.info(
        "Limiar de ausência configurado para %ss; verificação a cada %ss",
        settings.missed_threshold,
        settings.check_interval,
    )
    if settings.require_token:
        LOGGER.info("Autenticação Bearer obrigatória para /status")
    elif settings.auth_token:
        LOGGER.info("Token Bearer definido; aceitando também requisições sem token")

    monitor = StatusMonitor(
        settings=settings, service_manager=ServiceManager(settings.secondary_service)
    )

    try:
        httpd = StatusHTTPServer((bind, port), StatusHTTPRequestHandler, monitor)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            LOGGER.error(
                "Porta %s já está em uso em %s:%s; verifique se outra instância está ativa.",
                port,
                bind,
                port,
            )
            LOGGER.error(
                "Libere a porta ou ajuste BWB_STATUS_PORT/--port antes de reiniciar o monitor."
            )
        else:
            LOGGER.exception(
                "Falha ao iniciar servidor HTTP em %s:%s", bind, port
            )
        monitor.shutdown()
        raise SystemExit(1) from exc

    monitor.start()

    def _handle_signal(signum, _frame) -> None:
        LOGGER.info("Sinal %s recebido; encerrando.", signum)
        httpd.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _handle_signal)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Interrupção manual recebida; encerrando.")
    finally:
        LOGGER.info("Encerrando servidor HTTP...")
        monitor.shutdown()
        httpd.server_close()
        LOGGER.info("Servidor encerrado.")


def main() -> int:
    args = parse_args()
    settings = MonitorSettings.from_env()
    run_server(settings, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
