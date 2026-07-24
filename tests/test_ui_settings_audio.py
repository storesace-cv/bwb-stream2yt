"""Testes das definições da UI e modos de áudio (sem PySide6)."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from demo_video import demo_video_missing_message  # noqa: E402
from send_quality import DEFAULT_SEND_QUALITY  # noqa: E402
from stream_audio import (  # noqa: E402
    AUDIO_MODE_SILENT,
    AUDIO_MODE_SOURCE,
    AudioProbeResult,
    apply_audio_mode_to_config,
    build_audio_map_args,
    build_effective_ffmpeg_input_args,
    build_silent_audio_input_args,
    ensure_aac_audio_output_args,
    normalize_audio_mode,
    probe_input_has_audio,
)
from ui_settings import (  # noqa: E402
    VIDEO_SOURCE_CAMERA,
    VIDEO_SOURCE_DEMO,
    DictSettingsStore,
    UiSettings,
    default_ui_settings,
    format_schedule_status,
    load_ui_settings,
    save_ui_settings,
    validate_ui_settings,
)


def _load_stream_module():
    path = SRC / "stream_to_youtube.py"
    name = "_stream_ui_settings_audio_test"
    if name in sys.modules:
        return sys.modules[name]
    if "autotune" not in sys.modules:
        stub = types.ModuleType("autotune")
        stub.estimate_upload_bitrate = lambda *_a, **_k: (_ for _ in ()).throw(  # type: ignore
            NotImplementedError
        )
        stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
        stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
        sys.modules["autotune"] = stub
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


module = _load_stream_module()


def _base_config(**overrides):
    cfg = module.StreamingConfig(
        yt_url="rtmps://a.rtmps.youtube.com/live2/EXEMPLO",
        input_args=["-rtsp_transport", "tcp", "-i", "rtsp://cam/stream"],
        output_args=[
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-filter:a",
            "aresample=async=1",
        ],
        resolution="1080p",
        ffmpeg="ffmpeg",
        day_start_hour=8,
        day_end_hour=19,
        tz_offset_hours=1,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=5000,
        autotune_interval=8.0,
        autotune_safety_margin=0.5,
        heartbeat=module.HeartbeatConfig(
            enabled=False,
            endpoint=None,
            interval=20.0,
            timeout=5.0,
            machine_id="TEST",
            token=None,
            log_path=Path("hb.jsonl"),
            log_retention_seconds=3600,
        ),
        camera_probe=module.CameraProbeConfig(
            ffprobe="ffprobe",
            interval=5.0,
            timeout=2.0,
            required=False,
        ),
    )
    if overrides:
        cfg = replace(cfg, **overrides)
    return cfg


def test_default_ui_settings():
    settings = default_ui_settings()
    assert settings.video_source == VIDEO_SOURCE_CAMERA
    assert settings.send_quality == DEFAULT_SEND_QUALITY
    assert settings.audio_mode == AUDIO_MODE_SILENT
    assert settings.schedule_limited is False
    assert settings.effective_day_window() == (0, 24, 0)


def test_qsettings_persistence_via_dict_store():
    store = DictSettingsStore()
    original = validate_ui_settings(
        UiSettings(
            video_source=VIDEO_SOURCE_DEMO,
            demo_video_path=r"C:\demo\custom.mp4",
            send_quality="media",
            audio_mode=AUDIO_MODE_SOURCE,
            schedule_limited=True,
            day_start_hour=22,
            day_end_hour=6,
            tz_offset_hours=1,
        )
    )
    saved = save_ui_settings(store, original)
    loaded = load_ui_settings(store)
    assert loaded == saved
    assert loaded.demo_video_path.endswith("custom.mp4")
    assert loaded.audio_mode == AUDIO_MODE_SOURCE


def test_cancel_semantics_do_not_require_save():
    store = DictSettingsStore()
    before = load_ui_settings(store)
    draft = validate_ui_settings(
        replace(before, send_quality="baixa", audio_mode=AUDIO_MODE_SOURCE)
    )
    # Simula Cancelar: não chama save_ui_settings
    after = load_ui_settings(store)
    assert after == before
    assert draft != before


def test_demo_path_is_persisted():
    store = DictSettingsStore()
    settings = validate_ui_settings(
        replace(
            default_ui_settings(),
            video_source=VIDEO_SOURCE_DEMO,
            demo_video_path="/tmp/chosen-demo.mp4",
        )
    )
    save_ui_settings(store, settings)
    assert load_ui_settings(store).demo_video_path == "/tmp/chosen-demo.mp4"


def test_missing_demo_message_and_exists(tmp_path):
    missing = tmp_path / "ausente.mp4"
    assert demo_video_missing_message(str(missing)) == (
        "O vídeo de demonstração selecionado não foi encontrado."
    )


def test_quality_reaches_worker_via_prepare(monkeypatch):
    monkeypatch.setattr(module, "_ensure_env_file", lambda: None)
    monkeypatch.setattr(module, "_load_env_files", lambda: None)
    monkeypatch.setenv("YT_INPUT_ARGS", "-i rtsp://cam/stream")
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    config = module.prepare_ui_session_config(
        send_quality="media",
        audio_mode=AUDIO_MODE_SILENT,
        apply_audio=True,
    )
    assert "720" in " ".join(config.output_args) or config.resolution == "720p"
    assert config.bitrate_max_kbps == 3000


def test_schedule_override_does_not_touch_environ(monkeypatch):
    monkeypatch.setenv("YT_DAY_START_HOUR", "8")
    monkeypatch.setenv("YT_DAY_END_HOUR", "19")
    monkeypatch.setenv("YT_TZ_OFFSET_HOURS", "1")
    env_before = dict(os.environ)
    config = module.apply_schedule_override(
        _base_config(),
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
    )
    assert config.day_start_hour == 0
    assert config.day_end_hour == 24
    assert os.environ["YT_DAY_START_HOUR"] == env_before["YT_DAY_START_HOUR"]
    assert os.environ["YT_DAY_END_HOUR"] == env_before["YT_DAY_END_HOUR"]


def test_schedule_disabled_equals_0_24():
    settings = validate_ui_settings(
        replace(
            default_ui_settings(),
            schedule_limited=False,
            day_start_hour=9,
            day_end_hour=18,
        )
    )
    assert settings.effective_day_window()[:2] == (0, 24)
    assert "24 horas" in format_schedule_status(settings)


def test_midnight_crossing_window():
    config = _base_config(day_start_hour=22, day_end_hour=6, tz_offset_hours=0)
    night = __import__("datetime").datetime(2026, 7, 23, 23, 0, 0)
    morning = __import__("datetime").datetime(2026, 7, 23, 5, 0, 0)
    afternoon = __import__("datetime").datetime(2026, 7, 23, 12, 0, 0)
    assert module.in_day_window(config, now_utc=night) is True
    assert module.in_day_window(config, now_utc=morning) is True
    assert module.in_day_window(config, now_utc=afternoon) is False


def test_cli_still_reads_env_for_day_window(monkeypatch):
    monkeypatch.setattr(module, "_ensure_env_file", lambda: None)
    monkeypatch.setattr(module, "_load_env_files", lambda: None)
    monkeypatch.setenv("YT_INPUT_ARGS", "-i rtsp://cam/stream")
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    monkeypatch.setenv("YT_DAY_START_HOUR", "7")
    monkeypatch.setenv("YT_DAY_END_HOUR", "20")
    monkeypatch.setenv("YT_TZ_OFFSET_HOURS", "2")
    config = module.load_config()
    assert config.day_start_hour == 7
    assert config.day_end_hour == 20
    assert config.tz_offset_hours == 2
    assert config.audio_mode is None


def test_silent_audio_generates_anullsrc_and_maps():
    silent_in = build_silent_audio_input_args()
    assert silent_in[:2] == ["-f", "lavfi"]
    assert "anullsrc=" in silent_in[3]
    assert build_audio_map_args(silent=True) == ["-map", "0:v:0", "-map", "1:a:0"]
    updated = apply_audio_mode_to_config(_base_config(), AUDIO_MODE_SILENT)
    assert "anullsrc=" not in " ".join(updated.input_args)
    effective = build_effective_ffmpeg_input_args(updated)
    assert "anullsrc=" in " ".join(effective)
    assert updated.output_args[:4] == ["-map", "0:v:0", "-map", "1:a:0"]
    assert "-filter:a" not in updated.output_args
    assert ensure_aac_audio_output_args([])[1::2] == ["aac", "128k", "44100", "2"]


def test_silent_mode_ignores_original_mp4_audio():
    config = _base_config(
        input_args=["-stream_loop", "-1", "-re", "-i", "/tmp/demo.mp4"],
        demo_mode=True,
    )
    updated = apply_audio_mode_to_config(config, AUDIO_MODE_SILENT)
    assert updated.input_args == config.input_args
    assert updated.output_args[2:4] == ["-map", "1:a:0"]
    assert "0:a:0" not in updated.output_args
    effective = build_effective_ffmpeg_input_args(updated)
    assert effective[:5] == config.input_args
    assert effective[-4:-1] == ["-f", "lavfi", "-i"]


def test_source_audio_uses_original_track(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    updated = apply_audio_mode_to_config(_base_config(), AUDIO_MODE_SOURCE)
    assert updated.output_args[:4] == ["-map", "0:v:0", "-map", "0:a:0"]
    assert "anullsrc=" not in " ".join(updated.input_args)
    assert "anullsrc=" not in " ".join(build_effective_ffmpeg_input_args(updated))
    assert updated.audio_detected is True


def test_source_audio_without_track_falls_back_silent(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(
            ok=True, has_audio=False, error_kind="no_audio"
        ),
    )
    updated = apply_audio_mode_to_config(_base_config(), AUDIO_MODE_SOURCE)
    assert updated.audio_mode == AUDIO_MODE_SILENT
    assert updated.audio_detected is False
    assert "anullsrc=" in " ".join(build_effective_ffmpeg_input_args(updated))


def test_camera_video_only_works_with_silent():
    updated = apply_audio_mode_to_config(_base_config(), "sem")
    assert normalize_audio_mode("sem") == AUDIO_MODE_SILENT
    assert "anullsrc=" not in " ".join(updated.input_args)
    assert "anullsrc=" in " ".join(build_effective_ffmpeg_input_args(updated))


def test_camera_silent_keeps_monitor_on_rtsp_only():
    source_args = [
        "-rtsp_transport",
        "tcp",
        "-i",
        "rtsp://user:segredo@10.1.2.3/stream",
    ]
    config = apply_audio_mode_to_config(
        _base_config(input_args=list(source_args)), AUDIO_MODE_SILENT
    )
    assert config.input_args == source_args
    assert "anullsrc=" not in " ".join(config.input_args)
    monitor = module.CameraSignalMonitor(
        "ffprobe",
        config.input_args,
        5.0,
        2.0,
        False,
        log_fn=lambda *_a, **_k: None,
    )
    assert monitor._input_args == source_args
    effective = build_effective_ffmpeg_input_args(config)
    assert effective[:4] == source_args
    assert effective[4:6] == ["-f", "lavfi"]
    assert "anullsrc=" in effective[7]
    assert config.output_args[:4] == ["-map", "0:v:0", "-map", "1:a:0"]


def test_demo_silent_orders_mp4_then_anullsrc():
    demo_args = ["-stream_loop", "-1", "-re", "-i", r"C:\demo\video.mp4"]
    config = apply_audio_mode_to_config(
        _base_config(input_args=list(demo_args), demo_mode=True),
        AUDIO_MODE_SILENT,
    )
    effective = build_effective_ffmpeg_input_args(config)
    assert effective[4] == r"C:\demo\video.mp4"
    assert effective[5:8] == ["-f", "lavfi", "-i"]
    assert config.output_args[:4] == ["-map", "0:v:0", "-map", "1:a:0"]


def test_camera_source_audio_has_no_anullsrc(monkeypatch):
    monkeypatch.setattr(
        "stream_audio.probe_input_has_audio",
        lambda *a, **k: AudioProbeResult(ok=True, has_audio=True),
    )
    source_args = ["-rtsp_transport", "tcp", "-i", "rtsp://cam/stream"]
    config = apply_audio_mode_to_config(
        _base_config(input_args=list(source_args)), AUDIO_MODE_SOURCE
    )
    assert config.input_args == source_args
    assert build_effective_ffmpeg_input_args(config) == source_args
    assert config.output_args[:4] == ["-map", "0:v:0", "-map", "0:a:0"]


def test_diagnostics_effective_cmd_hides_rtsp_password():
    source_args = [
        "-rtsp_transport",
        "tcp",
        "-i",
        "rtsp://user:segredo-secreto@10.1.2.3/stream",
    ]
    config = apply_audio_mode_to_config(
        _base_config(input_args=list(source_args)), AUDIO_MODE_SILENT
    )
    report = module._collect_full_diagnostics(config)
    assert "segredo-secreto" not in report
    assert "anullsrc=" in report
    assert "rtsp://user:***@" in report or "***" in report


def test_probe_helper_parses_ffprobe_json():
    class _Result:
        returncode = 0
        stdout = '{"streams":[{"codec_type":"audio"}]}'
        stderr = ""

    result = probe_input_has_audio(
        "ffprobe",
        ["-i", "file.mp4"],
        run=lambda *a, **k: _Result(),
    )
    assert result.ok and result.has_audio


def test_ui_settings_never_write_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("YT_URL=rtmps://example/live2/x\n", encoding="utf-8")
    before = env_path.read_text(encoding="utf-8")
    monkeypatch.setenv("YT_DAY_START_HOUR", "8")
    store = DictSettingsStore()
    save_ui_settings(
        store,
        validate_ui_settings(
            replace(default_ui_settings(), day_start_hour=1, schedule_limited=True)
        ),
    )
    assert env_path.read_text(encoding="utf-8") == before
    assert os.environ["YT_DAY_START_HOUR"] == "8"


def test_fallback_script_keeps_anullsrc():
    script = (ROOT / "secondary-droplet" / "bin" / "youtube_fallback.sh").read_text(
        encoding="utf-8"
    )
    assert "anullsrc" in script
    assert "-map" in script
    assert "aac" in script
