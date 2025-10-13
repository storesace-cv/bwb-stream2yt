"""Windows service wrapper for the primary streaming application."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from stream_to_youtube import (
    log_event,
    start_streaming_instance,
    stop_active_worker,
)

SERVICE_NAME = "stream2yt-service"
DISPLAY_NAME = "stream2yt-service"
DESCRIPTION = (
    "Windows service wrapper that keeps the BeachCam primary feed streaming to YouTube."
)

_CONFIG_FILENAME = "stream2yt-service.config.json"
_KNOWN_SERVICE_COMMANDS = {
    "install",
    "update",
    "remove",
    "start",
    "stop",
    "restart",
    "debug",
    "status",
}
_RESOLUTION_TOKENS = {"360p", "720p", "1080p"}


def _service_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _service_config_path() -> Path:
    return _service_base_dir() / _CONFIG_FILENAME


def _persist_resolution_choice(resolution: str) -> None:
    path = _service_config_path()
    payload = {"resolution": resolution}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_configured_resolution() -> tuple[Optional[str], Optional[str]]:
    path = _service_config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"Falha ao ler configuração de resolução ({exc})."

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Arquivo de configuração inválido ({exc})."

    value = data.get("resolution")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            return normalized, None

    return None, None


def _normalize_resolution_token(token: str) -> Optional[str]:
    normalized = token.strip().lower()
    if not normalized:
        return None

    while normalized.startswith("-") or normalized.startswith("/"):
        normalized = normalized[1:]

    if normalized in _RESOLUTION_TOKENS:
        return normalized

    return None


def _extract_resolution_argument(args: list[str]) -> tuple[list[str], Optional[str]]:
    cleaned: list[str] = []
    selected: Optional[str] = None

    for token in args:
        normalized = _normalize_resolution_token(token)
        if normalized is None:
            cleaned.append(token)
            continue

        if selected is not None and normalized != selected:
            raise ValueError(
                "Informe no máximo uma flag de resolução (--360p, --720p ou --1080p)."
            )

        selected = normalized

    return cleaned, selected


def _detect_service_command(args: list[str]) -> Optional[str]:
    for token in args:
        lowered = token.lower()
        if lowered in _KNOWN_SERVICE_COMMANDS:
            return lowered
    return None


if os.name == "nt":  # pragma: no cover - tested on Windows hosts
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class StreamToYouTubeService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self._worker_thread: Optional[threading.Thread] = None
            self._exit_code: int = 0
            self._configured_resolution: Optional[str] = None

        # --- lifecycle callbacks -------------------------------------------------
        def SvcDoRun(self) -> None:  # noqa: N802 - pywin32 naming convention
            servicemanager.LogInfoMsg(f"{self._svc_name_} starting")
            log_event("service", "Windows service wrapper iniciado.")

            self._worker_thread = threading.Thread(
                target=self._run_streaming_worker,
                name="BWBStreamService",
                daemon=True,
            )
            self._worker_thread.start()

            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
            self._finalize_shutdown()

        def SvcStop(self) -> None:  # noqa: N802 - pywin32 naming convention
            servicemanager.LogInfoMsg(f"{self._svc_name_} stop requested")
            log_event("service", "Solicitação de parada recebida do SCM.")
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            stop_active_worker(timeout=20.0)
            win32event.SetEvent(self.hWaitStop)

        # --- worker helpers ------------------------------------------------------
        def _run_streaming_worker(self) -> None:
            resolution, warning = _load_configured_resolution()
            self._configured_resolution = resolution

            if warning:
                servicemanager.LogErrorMsg(f"{self._svc_name_} config warning: {warning}")
                log_event("service", warning)

            if resolution:
                message = f"Resolução configurada para o serviço: {resolution}"
                servicemanager.LogInfoMsg(f"{self._svc_name_} {message}")
                log_event("service", message)
            else:
                log_event(
                    "service",
                    "Nenhuma resolução específica definida; aplicando padrão do aplicativo.",
                )

            try:
                self._exit_code = start_streaming_instance(resolution=resolution)
            except Exception as exc:  # pragma: no cover - defensive logging
                self._exit_code = 1
                log_event("service", f"Exceção não tratada no worker do serviço: {exc}")
                servicemanager.LogErrorMsg(
                    f"{self._svc_name_} exception: {exc}"
                )
            finally:
                win32event.SetEvent(self.hWaitStop)

        def _finalize_shutdown(self) -> None:
            stop_active_worker(timeout=20.0)

            thread = self._worker_thread
            if thread is not None:
                thread.join(timeout=30.0)
                self._worker_thread = None

            if self._exit_code == 0:
                servicemanager.LogInfoMsg(f"{self._svc_name_} stopped cleanly")
                log_event("service", "Serviço encerrado com sucesso.")
            else:
                servicemanager.LogErrorMsg(
                    f"{self._svc_name_} stopped with exit code {self._exit_code}"
                )
                log_event(
                    "service",
                    f"Serviço encerrado com código {self._exit_code}. Consulte os logs.",
                )


    def main() -> None:
        """Entrypoint used by `python windows_service.py install/start` commands."""

        raw_args = sys.argv[1:]

        try:
            cleaned_args, resolution = _extract_resolution_argument(raw_args)
        except ValueError as exc:
            print(f"[service] {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

        command = _detect_service_command(cleaned_args)

        if resolution and command not in {"install", "update"}:
            print(
                "[service] A resolução só pode ser definida durante os comandos install/update.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        if resolution:
            try:
                _persist_resolution_choice(resolution)
            except OSError as exc:
                print(
                    f"[service] Falha ao gravar a configuração de resolução: {exc}",
                    file=sys.stderr,
                )
                raise SystemExit(1) from exc
            else:
                print(f"[service] Resolução configurada para {resolution}.")

        original_argv = sys.argv
        try:
            sys.argv = [sys.argv[0], *cleaned_args]
            win32serviceutil.HandleCommandLine(StreamToYouTubeService)
        finally:
            sys.argv = original_argv


else:  # pragma: no cover - module is Windows-only
    class StreamToYouTubeService:  # type: ignore[no-redef]
        """Placeholder used when importing on non-Windows environments."""

        def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - simple notice
            raise RuntimeError(
                "StreamToYouTubeService só está disponível em hosts Windows."
            )

    def main() -> None:  # type: ignore[no-redef]
        raise SystemExit(
            "O wrapper de serviço do Windows só pode ser utilizado em sistemas Windows."
        )


__all__ = [
    "DESCRIPTION",
    "DISPLAY_NAME",
    "SERVICE_NAME",
    "StreamToYouTubeService",
    "main",
]
