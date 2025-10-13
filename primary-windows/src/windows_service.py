"""Windows service wrapper for the primary streaming application."""

from __future__ import annotations

import os
import threading
from typing import Optional

from stream_to_youtube import (
    log_event,
    start_streaming_instance,
    stop_active_worker,
)

SERVICE_NAME = "BWBStream2YT"
DISPLAY_NAME = "BWB Stream2YT Primary"
DESCRIPTION = (
    "Windows service wrapper that keeps the BeachCam primary feed streaming to YouTube."
)


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
            try:
                self._exit_code = start_streaming_instance()
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

        win32serviceutil.HandleCommandLine(StreamToYouTubeService)


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
