"""System tray integration for the Windows primary streaming worker."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - handled via docs/runtime
    pystray = None  # type: ignore[assignment]
    Image = ImageDraw = None  # type: ignore[assignment]
    TRAY_AVAILABLE = False
else:
    TRAY_AVAILABLE = True

from stream_to_youtube import LOG_DIR, log_event

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from stream_to_youtube import StreamingWorker


if not TRAY_AVAILABLE:

    class TrayApplication:
        """Fallback placeholder when tray dependencies are missing."""

        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - runtime safeguard
            raise RuntimeError(
                "pystray/pillow não estão disponíveis; modo bandeja desativado."
            )

        def run(self) -> None:  # pragma: no cover - runtime safeguard
            raise RuntimeError(
                "pystray/pillow não estão disponíveis; modo bandeja desativado."
            )

        def stop(self) -> None:  # pragma: no cover - runtime safeguard
            return

else:

    class TrayApplication:
        """Wrapper that exposes the streaming worker controls on the system tray."""

        def __init__(self, worker: "StreamingWorker") -> None:
            self._worker = worker
            self._icon = pystray.Icon(
                "bwb_stream_to_youtube",
                self._create_image(),
                "BWB Stream2YT",
                self._build_menu(),
            )

        def run(self) -> None:
            """Start the tray icon loop (blocking)."""

            log_event("tray", "Tray icon iniciado")
            self._icon.run()

        def stop(self) -> None:
            """Stop the tray icon loop."""

            self._icon.stop()

        # Menu helpers -------------------------------------------------
        def _build_menu(self) -> "pystray.Menu":
            return pystray.Menu(
                pystray.MenuItem("Abrir logs…", self._on_open_logs),
                pystray.MenuItem(self._toggle_label, self._on_toggle_stream, default=False),
                pystray.MenuItem("Sair", self._on_exit),
            )

        def _toggle_label(self, item: "pystray.MenuItem") -> str:
            return "Parar transmissão" if self._worker.is_running else "Iniciar transmissão"

        def _refresh_menu(self) -> None:
            self._icon.update_menu()

        # Actions ------------------------------------------------------
        def _on_open_logs(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            target = LOG_DIR if LOG_DIR.is_dir() else LOG_DIR.parent
            log_event("tray", f"Abrindo pasta de logs em {target}")
            self._open_path(target)

        def _on_toggle_stream(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
            if self._worker.is_running:
                log_event("tray", "Solicitado stop do streaming via bandeja")
                self._worker.stop()
            else:
                log_event("tray", "Solicitado start do streaming via bandeja")
                self._worker.start()
            self._refresh_menu()

        def _on_exit(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
            log_event("tray", "Encerrando aplicação via bandeja")
            self._worker.stop()
            self.stop()

        # Utilities ----------------------------------------------------
        def _open_path(self, path: Path) -> None:
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except AttributeError:
                if os.name == "posix":
                    subprocess.Popen(["xdg-open", str(path)])
                elif os.name == "darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    raise
            except OSError as exc:
                log_event("tray", f"Não foi possível abrir os logs: {exc}")

        def _create_image(self) -> "Image.Image":
            size = 64
            image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((4, 4, size - 4, size - 4), fill=(220, 0, 0, 255))
            draw.rectangle(
                (size // 3, size // 3, size * 2 // 3, size * 2 // 3),
                fill=(255, 255, 255, 255),
            )
            return image
