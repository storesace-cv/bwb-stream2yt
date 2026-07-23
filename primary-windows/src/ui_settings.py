"""Definições da UI stream2yt (QSettings), separadas do .env."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, MutableMapping, Optional, Protocol

from demo_video import DEFAULT_DEMO_VIDEO_PATH, resolve_demo_video_path
from send_quality import DEFAULT_SEND_QUALITY, normalize_send_quality
from stream_audio import (
    AUDIO_MODE_SOURCE,
    DEFAULT_AUDIO_MODE,
    normalize_audio_mode,
)

SETTINGS_ORG = "BWB"
SETTINGS_APP = "stream2yt-ui"

VIDEO_SOURCE_CAMERA = "camera"
VIDEO_SOURCE_DEMO = "demo"

KEY_VIDEO_SOURCE = "video_source"
KEY_DEMO_PATH = "demo_video_path"
KEY_QUALITY = "send_quality"
KEY_AUDIO_MODE = "audio_mode"
KEY_SCHEDULE_LIMITED = "schedule_limited"
KEY_DAY_START = "day_start_hour"
KEY_DAY_END = "day_end_hour"
KEY_TZ_OFFSET = "tz_offset_hours"


class SettingsStore(Protocol):
    def value(self, key: str, default: Any = None) -> Any: ...

    def setValue(self, key: str, value: Any) -> None: ...

    def sync(self) -> None: ...


class DictSettingsStore:
    """Armazenamento em memória para testes (API compatível com QSettings)."""

    def __init__(self, initial: Optional[Mapping[str, Any]] = None) -> None:
        self._data: MutableMapping[str, Any] = dict(initial or {})

    def value(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def setValue(self, key: str, value: Any) -> None:
        self._data[key] = value

    def sync(self) -> None:
        return None


@dataclass(frozen=True)
class UiSettings:
    video_source: str = VIDEO_SOURCE_CAMERA
    demo_video_path: str = DEFAULT_DEMO_VIDEO_PATH
    send_quality: str = DEFAULT_SEND_QUALITY
    audio_mode: str = DEFAULT_AUDIO_MODE
    schedule_limited: bool = False
    day_start_hour: int = 0
    day_end_hour: int = 24
    tz_offset_hours: int = 0

    @property
    def demo_enabled(self) -> bool:
        return self.video_source == VIDEO_SOURCE_DEMO

    def effective_day_window(self) -> tuple[int, int, int]:
        if not self.schedule_limited:
            return 0, 24, self.tz_offset_hours
        return self.day_start_hour, self.day_end_hour, self.tz_offset_hours


def default_ui_settings() -> UiSettings:
    return UiSettings(
        video_source=VIDEO_SOURCE_CAMERA,
        demo_video_path=resolve_demo_video_path(),
        send_quality=DEFAULT_SEND_QUALITY,
        audio_mode=DEFAULT_AUDIO_MODE,
        schedule_limited=False,
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
    )


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_video_source(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in {VIDEO_SOURCE_DEMO, "demo", "demonstracao", "demonstração"}:
        return VIDEO_SOURCE_DEMO
    return VIDEO_SOURCE_CAMERA


def validate_ui_settings(settings: UiSettings) -> UiSettings:
    source = normalize_video_source(settings.video_source)
    quality = normalize_send_quality(settings.send_quality)
    audio = normalize_audio_mode(settings.audio_mode)
    demo_path = str(settings.demo_video_path or "").strip() or resolve_demo_video_path()

    start = _as_int(settings.day_start_hour, 0)
    end = _as_int(settings.day_end_hour, 24)
    tz = _as_int(settings.tz_offset_hours, 0)

    if start < 0 or start > 23:
        start = 0
    if end < 1 or end > 24:
        end = 24
    if tz < -12 or tz > 14:
        tz = 0

    return UiSettings(
        video_source=source,
        demo_video_path=demo_path,
        send_quality=quality,
        audio_mode=audio,
        schedule_limited=bool(settings.schedule_limited),
        day_start_hour=start,
        day_end_hour=end,
        tz_offset_hours=tz,
    )


def load_ui_settings(store: SettingsStore) -> UiSettings:
    defaults = default_ui_settings()
    loaded = UiSettings(
        video_source=str(
            store.value(KEY_VIDEO_SOURCE, defaults.video_source)
            or defaults.video_source
        ),
        demo_video_path=str(
            store.value(KEY_DEMO_PATH, defaults.demo_video_path)
            or defaults.demo_video_path
        ),
        send_quality=str(
            store.value(KEY_QUALITY, defaults.send_quality) or defaults.send_quality
        ),
        audio_mode=str(
            store.value(KEY_AUDIO_MODE, defaults.audio_mode) or defaults.audio_mode
        ),
        schedule_limited=_as_bool(
            store.value(KEY_SCHEDULE_LIMITED, defaults.schedule_limited),
            defaults.schedule_limited,
        ),
        day_start_hour=_as_int(
            store.value(KEY_DAY_START, defaults.day_start_hour),
            defaults.day_start_hour,
        ),
        day_end_hour=_as_int(
            store.value(KEY_DAY_END, defaults.day_end_hour), defaults.day_end_hour
        ),
        tz_offset_hours=_as_int(
            store.value(KEY_TZ_OFFSET, defaults.tz_offset_hours),
            defaults.tz_offset_hours,
        ),
    )
    return validate_ui_settings(loaded)


def save_ui_settings(store: SettingsStore, settings: UiSettings) -> UiSettings:
    validated = validate_ui_settings(settings)
    store.setValue(KEY_VIDEO_SOURCE, validated.video_source)
    store.setValue(KEY_DEMO_PATH, validated.demo_video_path)
    store.setValue(KEY_QUALITY, validated.send_quality)
    store.setValue(KEY_AUDIO_MODE, validated.audio_mode)
    store.setValue(KEY_SCHEDULE_LIMITED, validated.schedule_limited)
    store.setValue(KEY_DAY_START, validated.day_start_hour)
    store.setValue(KEY_DAY_END, validated.day_end_hour)
    store.setValue(KEY_TZ_OFFSET, validated.tz_offset_hours)
    store.sync()
    return validated


def create_qsettings_store() -> Any:
    """Cria QSettings(BWB, stream2yt-ui). Import local para testes sem Qt."""

    from PySide6.QtCore import QSettings

    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def format_source_status(settings: UiSettings) -> str:
    if settings.demo_enabled:
        return f"Fonte: Vídeo de demonstração ({settings.demo_video_path})"
    return "Fonte: Câmara"


def format_audio_status(settings: UiSettings) -> str:
    label = "Com áudio" if settings.audio_mode == AUDIO_MODE_SOURCE else "Sem áudio"
    return f"Áudio: {label}"


def format_schedule_status(settings: UiSettings) -> str:
    start, end, tz = settings.effective_day_window()
    sign = "+" if tz >= 0 else ""
    if not settings.schedule_limited:
        return f"Horário: 24 horas (UTC{sign}{tz})"
    return f"Horário: {start:02d}h–{end:02d}h (UTC{sign}{tz})"


def with_demo_path(settings: UiSettings, path: str) -> UiSettings:
    return validate_ui_settings(replace(settings, demo_video_path=path))
