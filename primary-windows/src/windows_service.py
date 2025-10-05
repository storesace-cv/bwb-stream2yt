"""Windows service integration for stream_to_youtube."""
from __future__ import annotations

import sys
from pathlib import Path
from subprocess import list2cmdline
from typing import Iterable

try:  # pragma: no cover - availability depends on platform
    import win32event  # type: ignore
    import win32service  # type: ignore
    import win32serviceutil  # type: ignore
except Exception:  # pragma: no cover - fall back for non-Windows dev
    win32event = None  # type: ignore
    win32service = None  # type: ignore
    win32serviceutil = None  # type: ignore

from stream_to_youtube import StreamingWorker, log_event

SERVICE_NAME = "BWBStreamToYouTube"
SERVICE_DISPLAY_NAME = "BWB Stream to YouTube"
SERVICE_DESCRIPTION = (
    "Mantém o streaming do Beach Weather Broadcast ativo via ffmpeg para o YouTube."
)
_SERVICE_CLASS_STRING = f"{__name__}.StreamToYouTubeService"


if win32serviceutil is not None:  # pragma: no branch - platform specific
    class StreamToYouTubeService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):  # pragma: no cover - executed by SCM
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._worker: StreamingWorker | None = None

        def SvcDoRun(self):  # pragma: no cover - executed by SCM
            log_event("service", "StreamToYouTubeService inicializando worker")
            self._worker = StreamingWorker()
            try:
                self._worker.start()
                win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)
            except Exception as exc:  # noqa: BLE001 - must log and continue shutdown
                log_event("service", f"Falha inesperada no serviço: {exc}")
                raise
            finally:
                if self._worker:
                    self._worker.stop(timeout=30)
                log_event("service", "StreamToYouTubeService finalizado")

        def SvcStop(self):  # pragma: no cover - executed by SCM
            log_event("service", "Solicitação de parada recebida do SCM")
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
else:  # pragma: no cover - allow imports on non-Windows hosts
    class StreamToYouTubeService:  # type: ignore[too-many-ancestors]
        """Placeholder para ambientes sem pywin32."""

        pass


def _ensure_win32() -> None:
    if win32serviceutil is None or win32service is None or win32event is None:
        raise RuntimeError(
            "Operações de serviço requerem pywin32 e execução em Windows."
        )


def _format_args(parts: Iterable[str]) -> str:
    return list2cmdline(list(parts))


def build_install_command() -> tuple[str, str]:
    """Return the executable and argument string used by the Windows service."""

    exe_path = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        exe_args = _format_args(["--service", SERVICE_NAME])
        return str(exe_path), exe_args

    script_path = Path(__file__).resolve().with_name("stream_to_youtube.py")
    exe_args = _format_args([str(script_path), "--service", SERVICE_NAME])
    return str(exe_path), exe_args


def install_service(exe_name: str, exe_args: str) -> None:
    _ensure_win32()
    log_event(
        "service",
        f"Registrando serviço {SERVICE_NAME} com comando: {exe_name} {exe_args}",
    )
    win32serviceutil.InstallService(  # type: ignore[arg-type]
        _SERVICE_CLASS_STRING,
        SERVICE_NAME,
        displayName=SERVICE_DISPLAY_NAME,
        startType=win32service.SERVICE_AUTO_START,
        exeName=exe_name,
        exeArgs=exe_args,
        description=SERVICE_DESCRIPTION,
    )
    log_event("service", "Serviço instalado com sucesso")


def remove_service() -> None:
    _ensure_win32()
    log_event("service", f"Removendo serviço {SERVICE_NAME}")
    win32serviceutil.RemoveService(SERVICE_NAME)
    log_event("service", "Serviço removido")


def start_service() -> None:
    _ensure_win32()
    log_event("service", f"Iniciando serviço {SERVICE_NAME}")
    win32serviceutil.StartService(SERVICE_NAME)
    log_event("service", "Serviço iniciado")


def stop_service() -> None:
    _ensure_win32()
    log_event("service", f"Parando serviço {SERVICE_NAME}")
    win32serviceutil.StopService(SERVICE_NAME)
    log_event("service", "Serviço parado")


def maybe_handle_service_invocation(argv: list[str] | None = None) -> bool:
    """Route pywin32 service execution (``--service``) when required."""

    if win32serviceutil is None:
        return False
    if argv is None:
        argv = sys.argv
    if any(arg.startswith("--") for arg in argv[1:]):
        win32serviceutil.HandleCommandLine(StreamToYouTubeService)
        return True
    return False
