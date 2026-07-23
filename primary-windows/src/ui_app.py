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
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from preview_rtsp import (
    STATUS_CONNECTING,
    STATUS_NO_IMAGE,
    sanitize_preview_text,
)
from demo_video import (
    DEMO_CAMERA_STATUS,
    build_demo_input_args,
    demo_video_exists,
    demo_video_missing_message,
    resolve_demo_video_path,
)
from send_quality import (
    DEFAULT_SEND_QUALITY,
    format_quality_status,
    get_send_quality_profile,
    iter_send_quality_profiles,
    normalize_send_quality,
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
APP_ICON_FILENAME = "stream2yt-ui.ico"


def resolve_app_icon_path() -> Optional[Path]:
    """Localiza o ícone da UI em desenvolvimento ou no bundle PyInstaller."""

    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        candidates.append(base / "assets" / APP_ICON_FILENAME)
        candidates.append(base / APP_ICON_FILENAME)

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "assets" / APP_ICON_FILENAME)
        candidates.append(exe_dir / APP_ICON_FILENAME)

    src_dir = Path(__file__).resolve().parent
    candidates.append(src_dir.parent / "assets" / APP_ICON_FILENAME)
    candidates.append(src_dir / "assets" / APP_ICON_FILENAME)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


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


def derive_camera_status(
    snapshot: Optional[Dict[str, Any]], *, demo_mode: bool = False
) -> str:
    if demo_mode or (snapshot and snapshot.get("demo_mode")):
        return DEMO_CAMERA_STATUS
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


def replace_active_preview(
    lock: threading.Lock,
    holder: Dict[str, Any],
    *,
    build_session: Callable[[], Any],
    stop_timeout: float = 5.0,
) -> Any:
    """Troca o preview sob lock: ler, None, parar, criar, iniciar, guardar.

    O holder deve ser a fonte de verdade da sessão ativa. A leitura de
    ``holder['session']`` ocorre apenas dentro do ``lock``.
    """

    with lock:
        previous = holder.get("session")
        holder["session"] = None
        if previous is not None:
            stop = getattr(previous, "stop", None)
            if callable(stop):
                stop(timeout=stop_timeout)
        session = build_session()
        if session is not None:
            start = getattr(session, "start", None)
            if callable(start):
                start()
        holder["session"] = session
        return session


def run_ui_app(*, resolution: Optional[str] = None) -> int:
    """Arranca a janela Qt. Devolve código de saída do QApplication."""

    try:
        from PySide6.QtCore import Qt, QTimer, Signal
        from PySide6.QtGui import QIcon, QImage, QPixmap
        from PySide6.QtWidgets import (
            QApplication,
            QButtonGroup,
            QCheckBox,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QMainWindow,
            QMessageBox,
            QPushButton,
            QRadioButton,
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
            self._preview_switch_lock = threading.RLock()
            self._latest_preview_jpeg: Optional[bytes] = None
            self._preview_frame_dirty = False
            self._demo_enabled = False
            self._demo_path = resolve_demo_video_path()
            self._quality_key = DEFAULT_SEND_QUALITY
            self._quality_restart_lock = threading.Lock()

            self.setWindowTitle("stream2yt — Primary")
            self.resize(720, 680)

            root = QWidget(self)
            self.setCentralWidget(root)
            layout = QVBoxLayout(root)

            self._preview = QLabel(STATUS_CONNECTING)
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumHeight(180)
            self._preview.setStyleSheet("border: 1px solid #888; padding: 8px;")
            layout.addWidget(self._preview)

            demo_row = QHBoxLayout()
            self._demo_checkbox = QCheckBox("Usar vídeo de demonstração")
            self._demo_checkbox.setChecked(False)
            self._demo_checkbox.toggled.connect(self._on_demo_toggled)
            self._demo_path_label = QLabel(self._demo_path)
            self._demo_path_label.setStyleSheet("color: #666;")
            self._demo_path_label.setWordWrap(True)
            demo_row.addWidget(self._demo_checkbox)
            demo_row.addWidget(self._demo_path_label, stretch=1)
            layout.addLayout(demo_row)

            quality_row = QHBoxLayout()
            quality_row.addWidget(QLabel("Qualidade de envio:"))
            self._quality_group = QButtonGroup(self)
            self._quality_group.setExclusive(True)
            self._quality_buttons: Dict[str, QRadioButton] = {}
            for profile in iter_send_quality_profiles():
                button = QRadioButton(profile.label)
                button.setProperty("quality_key", profile.key)
                if profile.key == self._quality_key:
                    button.setChecked(True)
                self._quality_group.addButton(button)
                self._quality_buttons[profile.key] = button
                quality_row.addWidget(button)
            quality_row.addStretch(1)
            self._quality_group.buttonClicked.connect(self._on_quality_button_clicked)
            layout.addLayout(quality_row)

            self._quality_status = QLabel(
                format_quality_status(get_send_quality_profile(self._quality_key))
            )
            layout.addWidget(self._quality_status)

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
            self._demo_checkbox.setEnabled(not self._busy and not session_alive)
            quality_enabled = not self._busy
            for button in self._quality_buttons.values():
                button.setEnabled(quality_enabled)

        def _set_busy(self, busy: bool) -> None:
            self._busy = busy
            self._refresh_button_states()

        def _sync_quality_buttons(self) -> None:
            button = self._quality_buttons.get(self._quality_key)
            if button is None:
                return
            self._quality_group.blockSignals(True)
            button.setChecked(True)
            self._quality_group.blockSignals(False)

        def _update_quality_status_label(self) -> None:
            profile = get_send_quality_profile(self._quality_key)
            self._quality_status.setText(format_quality_status(profile))

        def _on_quality_button_clicked(self, button) -> None:
            key = normalize_send_quality(str(button.property("quality_key") or ""))
            if key == self._quality_key:
                return

            previous = self._quality_key
            self._quality_key = key
            self._update_quality_status_label()

            if not self._session_thread_alive():
                return

            if self._busy or not self._quality_restart_lock.acquire(blocking=False):
                self._quality_key = previous
                self._sync_quality_buttons()
                self._update_quality_status_label()
                return

            self._set_busy(True)
            self._message.setText(
                f"A aplicar qualidade {get_send_quality_profile(key).label}…"
            )
            threading.Thread(
                target=self._quality_restart_worker_thread,
                name="UiQualityRestart",
                daemon=True,
            ).start()

        def _quality_restart_worker_thread(self) -> None:
            try:
                stop_active_worker(timeout=15.0)
                if self._start_thread is not None and self._start_thread.is_alive():
                    self._start_thread.join(timeout=25.0)
                time.sleep(0.3)
            except Exception as exc:  # noqa: BLE001
                self._post("message", f"Falha ao mudar qualidade: {exc}")
                self._post("busy", False)
                self._quality_restart_lock.release()
                return

            self._post("busy", False)
            self._post("message", "A iniciar transmissão…")
            self._post("start_requested", True)
            self._quality_restart_lock.release()

        def _post(self, kind: str, payload: Any = None) -> None:
            self._ui_queue.put((kind, payload))

        def _on_demo_toggled(self, checked: bool) -> None:
            if self._busy or self._session_thread_alive():
                self._demo_checkbox.blockSignals(True)
                self._demo_checkbox.setChecked(self._demo_enabled)
                self._demo_checkbox.blockSignals(False)
                return

            self._demo_path = resolve_demo_video_path()
            self._demo_path_label.setText(self._demo_path)

            if checked and not demo_video_exists(self._demo_path):
                self._message.setText(demo_video_missing_message(self._demo_path))
                self._demo_checkbox.blockSignals(True)
                self._demo_checkbox.setChecked(False)
                self._demo_checkbox.blockSignals(False)
                self._demo_enabled = False
                return

            self._demo_enabled = bool(checked)
            if checked:
                self._message.setText("A mudar preview para vídeo de demonstração…")
            else:
                self._message.setText("A mudar preview para a câmara RTSP…")
            threading.Thread(
                target=self._restart_preview_source,
                name="UiPreviewSwitch",
                daemon=True,
            ).start()

        def _boot_preview(self) -> None:
            self._replace_preview_locked()

        def _restart_preview_source(self) -> None:
            self._replace_preview_locked()

        def _replace_preview_locked(self) -> None:
            window = self

            class _Holder(dict):
                def get(self, key, default=None):  # type: ignore[no-untyped-def]
                    if key == "session":
                        return window._preview_session
                    return super().get(key, default)

                def __setitem__(self, key, value):  # type: ignore[no-untyped-def]
                    if key == "session":
                        window._preview_session = value
                    else:
                        super().__setitem__(key, value)

            def build_session():
                if self._closing:
                    return None
                return self._create_preview_session()

            replace_active_preview(
                self._preview_switch_lock,
                _Holder(),
                build_session=build_session,
            )

        def _create_preview_session(self):
            try:
                config = load_config(resolution=self._resolution)
                if self._demo_enabled:
                    path = resolve_demo_video_path()
                    self._demo_path = path
                    if not demo_video_exists(path):
                        self._post("preview_status", demo_video_missing_message(path))
                        return None
                    input_args = build_demo_input_args(path)
                else:
                    input_args = list(config.input_args)
                return PreviewSession(
                    ffmpeg=config.ffmpeg,
                    input_args=input_args,
                    on_frame=self._post_preview_frame,
                    on_status=lambda message: self._post("preview_status", message),
                )
            except Exception as exc:  # noqa: BLE001
                self._post(
                    "preview_status",
                    sanitize_preview_text(f"{STATUS_NO_IMAGE} ({exc})"),
                )
                return None

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
            demo_active = self._demo_enabled or bool(
                snapshot and snapshot.get("demo_mode")
            )
            self._camera_value.setText(
                derive_camera_status(snapshot, demo_mode=demo_active)
            )
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
            if self._demo_enabled:
                path = resolve_demo_video_path()
                self._demo_path = path
                self._demo_path_label.setText(path)
                if not demo_video_exists(path):
                    self._message.setText(demo_video_missing_message(path))
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
            demo_path = resolve_demo_video_path() if self._demo_enabled else None
            try:
                code = start_streaming_instance(
                    resolution=self._resolution,
                    demo_video_path=demo_path,
                    send_quality=self._quality_key,
                )
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
            elif code == 3:
                self._post(
                    "message",
                    demo_video_missing_message(demo_path),
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
    icon_path = resolve_app_icon_path()
    if icon_path is not None:
        try:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                app.setWindowIcon(icon)
                window.setWindowIcon(icon)
        except Exception:  # noqa: BLE001
            pass
    window.shutdown_finished.connect(app.quit)
    window.show()
    return int(app.exec())
