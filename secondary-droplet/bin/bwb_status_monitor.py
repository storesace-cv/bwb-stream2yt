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
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Optional

LOGGER = logging.getLogger("bwb_status_monitor")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def isoformat(ts: dt.datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts.astimezone(dt.timezone.utc).isoformat()


@dataclass
class MonitorSettings:
    bind: str = "0.0.0.0"
    port: int = 8080
    history_seconds: int = 300
    missed_threshold: int = 40
    recovery_reports: int = 2
    check_interval: int = 5
    state_file: Path = Path("/var/lib/bwb-status-monitor/status.json")
    log_file: Path = Path("/var/log/bwb_status_monitor.log")
    secondary_service: str = "youtube-fallback.service"
    auth_token: Optional[str] = None

    @classmethod
    def from_env(cls) -> "MonitorSettings":
        def _int(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except (TypeError, ValueError):
                LOGGER.warning(
                    "Valor inválido em %s=%r; utilizando %s", name, raw, default
                )
                return default
            if value <= 0:
                LOGGER.warning(
                    "Valor não positivo em %s=%r; utilizando %s", name, raw, default
                )
                return default
            return value

        bind = os.environ.get("BWB_STATUS_BIND", "0.0.0.0")
        port = _int("BWB_STATUS_PORT", 8080)
        history_seconds = _int("BWB_STATUS_HISTORY_SECONDS", 300)
        missed_threshold = _int("BWB_STATUS_MISSED_THRESHOLD", 40)
        recovery_reports = _int("BWB_STATUS_RECOVERY_REPORTS", 2)
        check_interval = _int("BWB_STATUS_CHECK_INTERVAL", 5)

        state_path = Path(
            os.environ.get("BWB_STATUS_STATE_FILE", cls.state_file.as_posix())
        )
        log_path = Path(os.environ.get("BWB_STATUS_LOG_FILE", cls.log_file.as_posix()))
        secondary_service = os.environ.get(
            "BWB_STATUS_SECONDARY_SERVICE", cls.secondary_service
        )
        token = os.environ.get("BWB_STATUS_TOKEN")

        return cls(
            bind=bind,
            port=port,
            history_seconds=history_seconds,
            missed_threshold=missed_threshold,
            recovery_reports=recovery_reports,
            check_interval=check_interval,
            state_file=state_path,
            log_file=log_path,
            secondary_service=secondary_service,
            auth_token=token if token else None,
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

    def _run_systemctl(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = ["/bin/systemctl", *args, self.name]
        LOGGER.debug("Executando: %s", " ".join(cmd))
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    def ensure_started(self) -> bool:
        with self._lock:
            status = subprocess.run(
                ["/bin/systemctl", "is-active", self.name],
                check=False,
                capture_output=True,
                text=True,
            )
            if status.returncode == 0 and status.stdout.strip() == "active":
                LOGGER.debug("Serviço %s já está ativo", self.name)
                return True

            result = self._run_systemctl("start")
            if result.returncode != 0:
                LOGGER.error(
                    "Falha ao iniciar %s: %s",
                    self.name,
                    result.stderr.strip() or result.stdout.strip(),
                )
                return False

            LOGGER.info("Serviço %s iniciado", self.name)
            return True

    def ensure_stopped(self) -> bool:
        with self._lock:
            status = subprocess.run(
                ["/bin/systemctl", "is-active", self.name],
                check=False,
                capture_output=True,
                text=True,
            )
            if status.returncode != 0 or status.stdout.strip() == "inactive":
                LOGGER.debug("Serviço %s já está inativo", self.name)
                return True

            result = self._run_systemctl("stop")
            if result.returncode != 0:
                LOGGER.error(
                    "Falha ao parar %s: %s",
                    self.name,
                    result.stderr.strip() or result.stdout.strip(),
                )
                return False

            LOGGER.info("Serviço %s parado", self.name)
            return True


class StatusMonitor:
    def __init__(
        self, settings: MonitorSettings, service_manager: ServiceManager
    ) -> None:
        self._settings = settings
        self._service_manager = service_manager
        self._history: Deque[StatusEntry] = deque()
        self._lock = threading.Lock()
        self._last_timestamp: Optional[dt.datetime] = None
        self._fallback_active = False
        self._recovery_reports = 0
        self._stop_event = threading.Event()
        self._watcher_thread = threading.Thread(
            target=self._watchdog_loop, name="bwb-status-watchdog", daemon=True
        )

        self._ensure_directories()
        LOGGER.debug("StatusMonitor inicializado com %s", self._settings)

    def start(self) -> None:
        if not self._watcher_thread.is_alive():
            self._watcher_thread.start()
            LOGGER.info(
                "Watchdog iniciado (threshold=%ss, recuperacao=%s reports)",
                self._settings.missed_threshold,
                self._settings.recovery_reports,
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
        trigger_stop = False
        with self._lock:
            self._history.append(entry)
            self._prune_history_locked(entry.timestamp)
            self._last_timestamp = entry.timestamp
            if self._fallback_active:
                self._recovery_reports += 1
                LOGGER.debug(
                    "Heartbeat recebido durante fallback (contagem %s/%s)",
                    self._recovery_reports,
                    self._settings.recovery_reports,
                )
                if self._recovery_reports >= self._settings.recovery_reports:
                    trigger_stop = True

        if trigger_stop:
            LOGGER.info("Heartbeats restabelecidos; solicitando parada do fallback.")
            if self._service_manager.ensure_stopped():
                with self._lock:
                    self._fallback_active = False
                    self._recovery_reports = 0
            else:
                LOGGER.warning(
                    "Falha ao parar fallback; mantendo flag ativo para nova tentativa."
                )
                with self._lock:
                    self._fallback_active = True
                    self._recovery_reports = 0

        self._write_state_file()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "last_timestamp": (
                    isoformat(self._last_timestamp) if self._last_timestamp else None
                ),
                "fallback_active": self._fallback_active,
                "history": [item.to_dict() for item in list(self._history)],
                "history_window_seconds": self._settings.history_seconds,
            }

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            self._evaluate_threshold()
            self._stop_event.wait(timeout=self._settings.check_interval)

    def _evaluate_threshold(self) -> None:
        action = False
        with self._lock:
            if self._last_timestamp is None:
                elapsed = None
            else:
                elapsed = (utc_now() - self._last_timestamp).total_seconds()

            if elapsed is None or elapsed > self._settings.missed_threshold:
                if not self._fallback_active:
                    LOGGER.warning(
                        "Sem heartbeats há %s segundos; solicitando fallback.",
                        "desconhecido" if elapsed is None else int(elapsed),
                    )
                    self._recovery_reports = 0
                    action = True
            else:
                LOGGER.debug(
                    "Heartbeat recente ha %.1fs; fallback desnecessario", elapsed
                )

        if action:
            if self._service_manager.ensure_started():
                with self._lock:
                    self._fallback_active = True
                LOGGER.info("Fallback ativado por ausência de heartbeats.")
            else:
                with self._lock:
                    self._fallback_active = False
                LOGGER.warning(
                    "Não foi possível iniciar o fallback; nova tentativa ocorrerá se o silêncio persistir."
                )

    def _prune_history_locked(self, reference: dt.datetime) -> None:
        cutoff = reference - dt.timedelta(seconds=self._settings.history_seconds)
        while self._history and self._history[0].timestamp < cutoff:
            self._history.popleft()

    def _write_state_file(self) -> None:
        try:
            data = [entry.to_dict() for entry in list(self._history)]
            tmp_path = self._settings.state_file.with_suffix(".tmp")
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self._settings.state_file)
            os.chmod(self._settings.state_file, 0o640)
        except Exception as exc:  # noqa: BLE001
            LOGGER.error(
                "Falha ao atualizar ficheiro de estado %s: %s",
                self._settings.state_file,
                exc,
            )

    def _ensure_directories(self) -> None:
        try:
            self._settings.state_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            LOGGER.error(
                "Falha ao criar diretório de estado %s: %s",
                self._settings.state_file.parent,
                exc,
            )
        try:
            self._settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


class StatusHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "BWBStatusMonitor/1.0"
    protocol_version = "HTTP/1.1"

    def _authenticate(self) -> bool:
        token = self.server.monitor.settings.auth_token  # type: ignore[attr-defined]
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return header.removeprefix("Bearer ") == token

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
            self._send_json({"error": "não autorizado"}, status=HTTPStatus.UNAUTHORIZED)
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
            "history_size": len(snapshot["history"]),
            "history_window_seconds": snapshot["history_window_seconds"],
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
        "Janela historial=%ss, limite ausência=%ss, relatórios recuperação=%s",
        settings.history_seconds,
        settings.missed_threshold,
        settings.recovery_reports,
    )

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
