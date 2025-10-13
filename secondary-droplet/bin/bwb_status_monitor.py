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
import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

LOGGER = logging.getLogger("bwb_status_monitor")


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
    mode_file: Path = Path("/run/youtube-fallback.mode")

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
        base_cmd = ["/bin/systemctl", "--no-ask-password", *args, self.name]
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


class StatusMonitor:
    def __init__(
        self, settings: MonitorSettings, service_manager: ServiceManager
    ) -> None:
        self._settings = settings
        self._service_manager = service_manager
        self._lock = threading.Lock()
        self._last_timestamp: Optional[dt.datetime] = None
        self._started_at = utc_now()
        self._fallback_active = False
        self._fallback_reason: Optional[str] = None
        self._last_camera_status: Optional[Dict[str, Any]] = None
        self._mode_file = settings.mode_file
        self._stop_event = threading.Event()
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

    def _stop_fallback(self, message: str) -> None:
        LOGGER.info(message)
        if self._service_manager.ensure_stopped():
            with self._lock:
                self._fallback_active = False
                self._fallback_reason = None
            self._write_mode_file("life")
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
