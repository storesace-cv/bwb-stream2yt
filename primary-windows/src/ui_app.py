"""UI mínima PySide6 para monitorização e controlo do primary Windows.

PySide6 é importado apenas em ``run_ui_app`` para não afetar CLI/serviço.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from preview_rtsp import (
    STATUS_CONNECTING,
    STATUS_NO_IMAGE,
    sanitize_preview_text,
)

YOUTUBE_CONFIRMED_STATUS = "Não verificado"
INSTANCE_ACTIVE_HINT = (
    "Já existe uma instância ativa (serviço ou aplicação). "
    "Pare o serviço stream2yt-service ou a outra instância antes de transmitir pela interface."
)

INTERNET_CHECKING = "A verificar"
INTERNET_ONLINE = "Ligada"
INTERNET_OFFLINE = "Sem ligação"
INTERNET_OFFLINE_MESSAGE = (
    "Sem ligação à Internet. Não é possível enviar a transmissão para o YouTube."
)
INTERNET_CHECK_URL = "https://www.youtube.com/generate_204"
INTERNET_CHECK_TIMEOUT_SECONDS = 3.0
INTERNET_CHECK_INTERVAL_SECONDS = 15.0


def check_internet_connectivity(
    *,
    timeout: float = INTERNET_CHECK_TIMEOUT_SECONDS,
    url: str = INTERNET_CHECK_URL,
) -> str:
    """Verifica conectividade HTTP mínima. Devolve Ligada ou Sem ligação."""

    try:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "BWBPrimary-UI/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = getattr(response, "status", None)
            if status_code is None:
                status_code = response.getcode()
            if status_code is not None and int(status_code) >= 500:
                return INTERNET_OFFLINE
            return INTERNET_ONLINE
    except urllib.error.HTTPError as exc:
        if exc.code < 500:
            return INTERNET_ONLINE
        return INTERNET_OFFLINE
    except (urllib.error.URLError, TimeoutError, OSError):
        return INTERNET_OFFLINE


def derive_camera_status(snapshot: Optional[Dict[str, Any]]) -> str:
    if not snapshot:
        return "A verificar"
    camera = snapshot.get("camera_signal") or {}
    present = camera.get("present")
    if present is True:
        return "OK"
    if present is False:
        return "Erro" if camera.get("last_error") else "Sem sinal"
    return "A verificar"


def derive_encoder_status(snapshot: Optional[Dict[str, Any]]) -> str:
    if not snapshot:
        return "Parado"
    progress = snapshot.get("ffmpeg_progress") or {}
    rtmps_state = progress.get("rtmps_send_state")
    if snapshot.get("ffmpeg_running"):
        return "A correr"
    if rtmps_state == "Erro":
        return "Erro"
    if snapshot.get("thread_running"):
        return "A iniciar"
    exit_code = snapshot.get("last_exit_code")
    if exit_code not in (None, 0):
        return "Erro"
    return "Parado"


def derive_rtmps_status(snapshot: Optional[Dict[str, Any]]) -> str:
    if not snapshot:
        return "Parado"
    progress = snapshot.get("ffmpeg_progress") or {}
    return str(progress.get("rtmps_send_state") or "Parado")


def format_metric(value: Any, *, suffix: str = "") -> str:
    if value is None or value == "":
        return "—"
    text = str(value)
    return f"{text}{suffix}" if suffix else text


def extract_recent_event_lines(
    snapshot: Optional[Dict[str, Any]], *, limit: int = 30
) -> List[str]:
    if not snapshot:
        return []
    progress = snapshot.get("ffmpeg_progress") or {}
    events = progress.get("recent_events") or []
    lines: List[str] = []
    for event in events[-limit:]:
        message = event.get("message") or ""
        component = event.get("component") or "primary"
        lines.append(f"[{component}] {message}")
    return lines


def run_ui_app(*, resolution: Optional[str] = None) -> int:
    """Arranca a janela Qt. Devolve código de saída do QApplication."""

    try:
        from PySide6.QtCore import Qt, QTimer, Signal
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print(
            "[primary] PySide6 não está instalado; o modo --ui não pode ser iniciado.",
            file=sys.stderr,
        )
        return 1

    from preview_rtsp import PreviewSession
    from stream_to_youtube import (
        collect_diagnostics_text,
        get_active_worker_snapshot,
        load_config,
        start_streaming_instance,
        stop_active_worker,
    )

    class PrimaryMainWindow(QMainWindow):
        shutdown_finished = Signal()

        def __init__(self, chosen_resolution: Optional[str]) -> None:
            super().__init__()
            self._resolution = chosen_resolution
            self._busy = False
            self._closing = False
            self._start_thread: Optional[threading.Thread] = None
            self._ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
            self._internet_status = INTERNET_CHECKING
            self._internet_check_lock = threading.Lock()
            self._internet_check_running = False
            self._last_internet_check_at = 0.0
            self._preview_session: Optional[PreviewSession] = None
            self._preview_frame_lock = threading.Lock()
            self._latest_preview_jpeg: Optional[bytes] = None
            self._preview_frame_dirty = False

            self.setWindowTitle("stream2yt — Primary")
            self.resize(720, 640)

            root = QWidget(self)
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)

            self._preview = QLabel(STATUS_CONNECTING)
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumHeight(180)
            self._preview.setStyleSheet("border: 1px solid #888; padding: 8px;")
            layout.addWidget(self._preview)

            status_grid = QGridLayout()
            self._camera_value = QLabel("A verificar")
            self._encoder_value = QLabel("Parado")
            self._rtmps_value = QLabel("Parado")
            self._youtube_value = QLabel(YOUTUBE_CONFIRMED_STATUS)
            self._internet_value = QLabel(INTERNET_CHECKING)
            rows = (
                ("Câmara", self._camera_value),
                ("Codificador", self._encoder_value),
                ("Envio RTMPS", self._rtmps_value),
                ("YouTube confirmado", self._youtube_value),
                ("Internet", self._internet_value),
            )
            for row, (title, value_label) in enumerate(rows):
                status_grid.addWidget(QLabel(title), row, 0)
                status_grid.addWidget(value_label, row, 1)
            layout.addLayout(status_grid)

            metrics_grid = QGridLayout()
            self._fps_value = QLabel("—")
            self._bitrate_value = QLabel("—")
            self._frames_value = QLabel("—")
            self._bytes_value = QLabel("—")
            self._out_time_value = QLabel("—")
            self._speed_value = QLabel("—")
            metric_rows = (
                ("FPS", self._fps_value),
                ("Bitrate", self._bitrate_value),
                ("Frames", self._frames_value),
                ("Bytes enviados", self._bytes_value),
                ("out_time", self._out_time_value),
                ("speed", self._speed_value),
            )
            for row, (title, value_label) in enumerate(metric_rows):
                metrics_grid.addWidget(QLabel(title), row, 0)
                metrics_grid.addWidget(value_label, row, 1)
            layout.addLayout(metrics_grid)

            layout.addWidget(QLabel("Eventos recentes"))
            self._events = QListWidget()
            self._events.setMinimumHeight(140)
            layout.addWidget(self._events)

            self._message = QLabel("")
            self._message.setWordWrap(True)
            layout.addWidget(self._message)

            buttons = QHBoxLayout()
            self._btn_start = QPushButton("Iniciar")
            self._btn_stop = QPushButton("Parar")
            self._btn_restart = QPushButton("Reiniciar")
            self._btn_diag = QPushButton("Diagnóstico")
            self._btn_start.clicked.connect(self._on_start)
            self._btn_stop.clicked.connect(self._on_stop)
            self._btn_restart.clicked.connect(self._on_restart)
            self._btn_diag.clicked.connect(self._on_diagnostics)
            for button in (
                self._btn_start,
                self._btn_stop,
                self._btn_restart,
                self._btn_diag,
            ):
                buttons.addWidget(button)
            layout.addLayout(buttons)

            self._timer = QTimer(self)
            self._timer.setInterval(500)
            self._timer.timeout.connect(self._on_timer)
            self._timer.start()
            self._maybe_schedule_internet_check()
            threading.Thread(
                target=self._boot_preview,
                name="UiPreviewBoot",
                daemon=True,
            ).start()

        def _session_thread_alive(self) -> bool:
            thread = self._start_thread
            return bool(thread and thread.is_alive())

        def _refresh_button_states(self) -> None:
            session_alive = self._session_thread_alive()
            self._btn_start.setEnabled(not self._busy and not session_alive)
            self._btn_restart.setEnabled(not self._busy)
            self._btn_stop.setEnabled(not self._busy)
            self._btn_diag.setEnabled(not self._busy)

        def _set_busy(self, busy: bool) -> None:
            self._busy = busy
            self._refresh_button_states()

        def _post(self, kind: str, payload: Any = None) -> None:
            self._ui_queue.put((kind, payload))

        def _on_timer(self) -> None:
            while True:
                try:
                    kind, payload = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "message":
                    self._message.setText(str(payload))
                elif kind == "busy":
                    self._set_busy(bool(payload))
                elif kind == "start_requested":
                    self._on_start()
                elif kind == "diagnostics":
                    self._show_diagnostics(str(payload))
                elif kind == "internet":
                    self._apply_internet_status(str(payload))
                elif kind == "preview_frame":
                    self._preview_frame_dirty = True
                elif kind == "preview_status":
                    self._apply_preview_status(str(payload))

            if self._preview_frame_dirty:
                self._preview_frame_dirty = False
                with self._preview_frame_lock:
                    jpeg = self._latest_preview_jpeg
                if jpeg:
                    self._apply_preview_frame(jpeg)

            snapshot = get_active_worker_snapshot()
            self._apply_snapshot(snapshot)
            self._refresh_button_states()
            self._maybe_schedule_internet_check()

        def _post_preview_frame(self, jpeg: bytes) -> None:
            with self._preview_frame_lock:
                self._latest_preview_jpeg = jpeg
            self._post("preview_frame", True)

        def _boot_preview(self) -> None:
            if self._closing:
                return
            try:
                config = load_config(resolution=self._resolution)
                session = PreviewSession(
                    ffmpeg=config.ffmpeg,
                    input_args=config.input_args,
                    on_frame=self._post_preview_frame,
                    on_status=lambda message: self._post("preview_status", message),
                )
                self._preview_session = session
                if self._closing:
                    session.stop(timeout=2.0)
                    return
                session.start()
            except Exception as exc:  # noqa: BLE001
                self._post(
                    "preview_status",
                    sanitize_preview_text(f"{STATUS_NO_IMAGE} ({exc})"),
                )

        def _apply_preview_status(self, message: str) -> None:
            text = sanitize_preview_text(message) or STATUS_NO_IMAGE
            self._preview.setPixmap(QPixmap())
            self._preview.setText(text)

        def _apply_preview_frame(self, jpeg: bytes) -> None:
            image = QImage.fromData(jpeg, "JPG")
            if image.isNull():
                self._apply_preview_status(STATUS_NO_IMAGE)
                return
            pixmap = QPixmap.fromImage(image)
            target = self._preview.size()
            if target.width() < 2 or target.height() < 2:
                target = self._preview.minimumSize()
            scaled = pixmap.scaled(
                target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._preview.setText("")
            self._preview.setPixmap(scaled)

        def _maybe_schedule_internet_check(self) -> None:
            if self._closing:
                return
            now = time.monotonic()
            with self._internet_check_lock:
                if self._internet_check_running:
                    return
                if (
                    self._last_internet_check_at > 0
                    and (now - self._last_internet_check_at)
                    < INTERNET_CHECK_INTERVAL_SECONDS
                ):
                    return
                self._internet_check_running = True

            threading.Thread(
                target=self._internet_check_thread,
                name="UiInternetCheck",
                daemon=True,
            ).start()

        def _internet_check_thread(self) -> None:
            try:
                status = check_internet_connectivity()
            except Exception:  # noqa: BLE001
                status = INTERNET_OFFLINE
            finally:
                with self._internet_check_lock:
                    self._internet_check_running = False
                    self._last_internet_check_at = time.monotonic()
            if not self._closing:
                self._post("internet", status)

        def _apply_internet_status(self, status: str) -> None:
            self._internet_status = status
            self._internet_value.setText(status)
            if status == INTERNET_OFFLINE:
                self._message.setText(INTERNET_OFFLINE_MESSAGE)
            elif (
                status == INTERNET_ONLINE
                and self._message.text() == INTERNET_OFFLINE_MESSAGE
            ):
                self._message.setText("")

        def _apply_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> None:
            self._camera_value.setText(derive_camera_status(snapshot))
            self._encoder_value.setText(derive_encoder_status(snapshot))
            self._rtmps_value.setText(derive_rtmps_status(snapshot))
            self._youtube_value.setText(YOUTUBE_CONFIRMED_STATUS)
            self._internet_value.setText(self._internet_status)

            progress = (snapshot or {}).get("ffmpeg_progress") or {}
            self._fps_value.setText(format_metric(progress.get("fps")))
            bitrate = progress.get("bitrate") or progress.get("bitrate_kbps")
            self._bitrate_value.setText(format_metric(bitrate))
            self._frames_value.setText(format_metric(progress.get("frame")))
            self._bytes_value.setText(format_metric(progress.get("total_size")))
            out_time = progress.get("out_time")
            if out_time is None and progress.get("out_time_ms") is not None:
                out_time = f"{progress.get('out_time_ms')} ms"
            self._out_time_value.setText(format_metric(out_time))
            self._speed_value.setText(format_metric(progress.get("speed")))

            lines = extract_recent_event_lines(snapshot)
            current = [self._events.item(i).text() for i in range(self._events.count())]
            if lines != current:
                self._events.clear()
                self._events.addItems(lines)
                if lines:
                    self._events.scrollToBottom()

        def _on_start(self) -> None:
            if self._busy or self._session_thread_alive():
                if self._session_thread_alive():
                    self._message.setText(INSTANCE_ACTIVE_HINT)
                return
            self._message.setText("A iniciar transmissão…")
            thread = threading.Thread(
                target=self._start_worker_thread,
                name="UiStartStreaming",
                daemon=True,
            )
            self._start_thread = thread
            self._refresh_button_states()
            thread.start()

        def _start_worker_thread(self) -> None:
            try:
                code = start_streaming_instance(resolution=self._resolution)
            except Exception as exc:  # noqa: BLE001
                self._post("message", f"Falha ao iniciar: {exc}")
                return
            if code == 1:
                self._post("message", INSTANCE_ACTIVE_HINT)
            elif code == 2:
                self._post(
                    "message",
                    "Credenciais YT_URL/YT_KEY ausentes; configure o .env antes de iniciar.",
                )
            elif code != 0:
                self._post("message", f"Arranque terminou com código {code}.")
            else:
                self._post("message", "Transmissão terminada.")

        def _on_stop(self) -> None:
            if self._busy:
                return
            self._set_busy(True)
            self._message.setText("A parar transmissão…")
            threading.Thread(
                target=self._stop_worker_thread,
                name="UiStopStreaming",
                daemon=True,
            ).start()

        def _stop_worker_thread(self) -> None:
            try:
                stop_active_worker(timeout=15.0)
                if self._start_thread is not None and self._start_thread.is_alive():
                    self._start_thread.join(timeout=20.0)
            except Exception as exc:  # noqa: BLE001
                self._post("message", f"Falha ao parar: {exc}")
            else:
                self._post("message", "Transmissão parada.")
            self._post("busy", False)

        def _on_restart(self) -> None:
            if self._busy:
                return
            self._set_busy(True)
            self._message.setText("A reiniciar transmissão…")
            threading.Thread(
                target=self._restart_worker_thread,
                name="UiRestartStreaming",
                daemon=True,
            ).start()

        def _restart_worker_thread(self) -> None:
            try:
                stop_active_worker(timeout=15.0)
                if self._start_thread is not None and self._start_thread.is_alive():
                    self._start_thread.join(timeout=25.0)
                time.sleep(0.3)
            except Exception as exc:  # noqa: BLE001
                self._post("message", f"Falha ao reiniciar: {exc}")
                self._post("busy", False)
                return

            self._post("busy", False)
            self._post("message", "A iniciar transmissão…")
            self._post("start_requested", True)

        def _on_diagnostics(self) -> None:
            if self._busy:
                return
            self._set_busy(True)
            self._message.setText("A gerar diagnóstico…")
            threading.Thread(
                target=self._diagnostics_thread,
                name="UiDiagnostics",
                daemon=True,
            ).start()

        def _diagnostics_thread(self) -> None:
            try:
                report = collect_diagnostics_text(resolution=self._resolution)
            except Exception as exc:  # noqa: BLE001
                self._post("message", f"Falha no diagnóstico: {exc}")
            else:
                self._post("diagnostics", report)
                self._post("message", "Diagnóstico concluído.")
            self._post("busy", False)

        def _show_diagnostics(self, report: str) -> None:
            box = QMessageBox(self)
            box.setWindowTitle("Diagnóstico técnico")
            box.setIcon(QMessageBox.Information)
            box.setText("Relatório de diagnóstico técnico")
            box.setDetailedText(report)
            box.exec()

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
            if self._closing:
                event.accept()
                return

            self._closing = True
            event.ignore()
            self._timer.stop()
            self.setEnabled(False)
            self.hide()

            def _shutdown_worker() -> None:
                try:
                    preview = self._preview_session
                    if preview is not None:
                        preview.stop(timeout=5.0)
                    stop_active_worker(timeout=5.0)
                    start_thread = self._start_thread
                    if start_thread is not None and start_thread.is_alive():
                        start_thread.join(timeout=5.0)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self.shutdown_finished.emit()

            threading.Thread(
                target=_shutdown_worker,
                name="UiCloseShutdown",
                daemon=True,
            ).start()

    app = QApplication.instance() or QApplication(sys.argv)
    window = PrimaryMainWindow(resolution)
    window.shutdown_finished.connect(app.quit)
    window.show()
    return int(app.exec())
