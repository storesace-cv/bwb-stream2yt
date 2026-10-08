"""Configuração efectiva partilhada (UI / serviço / headless)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

ENGINE_FFMPEG = "ffmpeg"
ENGINE_GSTREAMER = "gstreamer"
ENGINE_AUTOMATIC = "automatic"
DEFAULT_ENGINE_PREFERENCE = ENGINE_FFMPEG

DEFAULT_YT_BASE = "rtmps://a.rtmps.youtube.com/live2"
ALLOWED_YT_HOSTS = frozenset(
    {
        "a.rtmps.youtube.com",
        "b.rtmps.youtube.com",
    }
)


@dataclass
class EffectiveConfig:
    engine_preference: str = DEFAULT_ENGINE_PREFERENCE
    yt_ingest_base: str = DEFAULT_YT_BASE
    stream_key_ref: str = "default"
    camera_failover_to_demo: bool = False
    demo_video_path: str = ""
    send_quality: str = "source"
    audio_mode: str = "silent"
    last_successful_engine: Optional[str] = None
    # Metadados de resolução (preenchidos em runtime; persistidos opcionalmente)
    effective_engine: Optional[str] = None
    effective_mode: Optional[str] = None  # copy | transcode
    selection_reason: Optional[str] = None

    def to_public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def shared_data_dir() -> Path:
    override = os.environ.get("BWB_SHARED_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(r"C:\bwb\apps\youtube\data")
    return Path.home() / ".bwb-stream2yt" / "data"


def shared_bin_dir() -> Path:
    override = os.environ.get("BWB_SHARED_BIN_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(r"C:\bwb\apps\youtube\bin")
    return Path.home() / ".bwb-stream2yt" / "bin"


def config_path(data_dir: Optional[Path] = None) -> Path:
    return (data_dir or shared_data_dir()) / "effective_config.json"


def key_blob_path(data_dir: Optional[Path] = None, ref: str = "default") -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in ref) or "default"
    return (data_dir or shared_data_dir()) / f"stream_key_{safe}.dpapi"


def ensure_data_dir(data_dir: Optional[Path] = None) -> Path:
    path = data_dir or shared_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    try:
        from windows_acl import apply_data_dir_acls

        apply_data_dir_acls(path)
    except Exception:
        pass
    return path


def normalize_engine_preference(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in {ENGINE_AUTOMATIC, "auto"}:
        return ENGINE_AUTOMATIC
    if raw in {ENGINE_GSTREAMER, "gst"}:
        return ENGINE_GSTREAMER
    return ENGINE_FFMPEG


def load_effective_config(data_dir: Optional[Path] = None) -> EffectiveConfig:
    path = config_path(data_dir)
    if not path.is_file():
        return EffectiveConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Configuração efectiva inválida ou corrompida.")
    if not isinstance(payload, dict):
        raise ValueError("Configuração efectiva inválida ou corrompida.")
    return EffectiveConfig(
        engine_preference=normalize_engine_preference(
            payload.get("engine_preference")
        ),
        yt_ingest_base=str(payload.get("yt_ingest_base") or DEFAULT_YT_BASE).strip(),
        stream_key_ref=str(payload.get("stream_key_ref") or "default").strip()
        or "default",
        camera_failover_to_demo=bool(payload.get("camera_failover_to_demo")),
        demo_video_path=str(payload.get("demo_video_path") or "").strip(),
        send_quality=str(payload.get("send_quality") or "source").strip() or "source",
        audio_mode=str(payload.get("audio_mode") or "silent").strip() or "silent",
        last_successful_engine=(
            str(payload["last_successful_engine"]).strip().lower()
            if payload.get("last_successful_engine")
            else None
        ),
        effective_engine=(
            str(payload["effective_engine"]).strip().lower()
            if payload.get("effective_engine")
            else None
        ),
        effective_mode=(
            str(payload["effective_mode"]).strip().lower()
            if payload.get("effective_mode")
            else None
        ),
        selection_reason=(
            str(payload["selection_reason"]) if payload.get("selection_reason") else None
        ),
    )


def save_effective_config(
    config: EffectiveConfig, data_dir: Optional[Path] = None
) -> Path:
    root = ensure_data_dir(data_dir)
    path = config_path(root)
    payload = config.to_public_dict()
    # Não persistir razão/efective transitórios como obrigatórios — OK guardar.
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".effective_config.", suffix=".tmp", dir=str(root)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            from windows_acl import secure_file

            secure_file(path)
        except Exception:
            pass
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    return path


def record_successful_engine(
    engine: str, data_dir: Optional[Path] = None
) -> EffectiveConfig:
    cfg = load_effective_config(data_dir)
    normalized = normalize_engine_preference(engine)
    if normalized == ENGINE_AUTOMATIC:
        return cfg
    cfg.last_successful_engine = normalized
    save_effective_config(cfg, data_dir)
    return cfg
