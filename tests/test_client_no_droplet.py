"""Testes dirigidos — Cliente sem droplet (incrementos A/B)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
INSTALLER = (
    Path(__file__).resolve().parents[1]
    / "primary-windows"
    / "via-windows"
    / "installer"
)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from effective_config import (  # noqa: E402
    ENGINE_AUTOMATIC,
    ENGINE_FFMPEG,
    ENGINE_GSTREAMER,
    EffectiveConfig,
    load_effective_config,
    save_effective_config,
)
from engine_compat import (  # noqa: E402
    ANALYSIS_INCOMPATIBLE,
    ANALYSIS_INDETERMINATE,
    MODE_COPY,
    MODE_TRANSCODE,
    EngineCapability,
    EngineEligibility,
    SourceProbeSummary,
    evaluate_eligibility,
    select_engine,
)
from send_quality import SEND_QUALITY_SOURCE, quality_requires_transcode  # noqa: E402
from yt_destination import (  # noqa: E402
    DestinationError,
    build_full_url,
    parse_full_rtmps_url,
    redact_secrets,
    resolve_destination,
    save_stream_key,
)


def _load_stream_module():
    path = SRC / "stream_to_youtube.py"
    spec = importlib.util.spec_from_file_location("_sty_nodroplet", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    if "autotune" not in sys.modules:
        stub = types.ModuleType("autotune")
        stub.estimate_upload_bitrate = lambda *_a, **_k: (_ for _ in ()).throw(
            NotImplementedError
        )
        stub.AUTOTUNE_AVAILABLE = False
        stub.AUTOTUNE_UNAVAILABLE_REASON = ""
        sys.modules["autotune"] = stub
    sys.modules["_sty_nodroplet"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_heartbeat_hard_off_ignores_legacy_env(monkeypatch, tmp_path):
    mod = _load_stream_module()
    monkeypatch.setenv("BWB_STATUS_ENDPOINT", "https://example.digitalocean.invalid/hb")
    monkeypatch.setenv("BWB_STATUS_TOKEN", "secret-token")
    monkeypatch.setenv("BWB_STATUS_ENABLED", "1")
    cfg = mod._resolve_heartbeat_config(tmp_path)
    assert cfg.enabled is False
    assert cfg.endpoint is None


def test_yt_url_precedes_yt_key_not_xor(monkeypatch, tmp_path):
    monkeypatch.setenv("BWB_SHARED_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "YT_URL", "rtmps://a.rtmps.youtube.com/live2/FROM_URL_KEY_123"
    )
    monkeypatch.setenv("YT_KEY", "FROM_KEY_ONLY_999")
    dest = resolve_destination(data_dir=tmp_path, allow_legacy_fallback=True)
    assert dest.stream_key == "FROM_URL_KEY_123"
    assert dest.source == "legacy_url"
    assert "FROM_KEY_ONLY" not in dest.full_url


def test_yt_key_only_builds_default_base(monkeypatch, tmp_path):
    monkeypatch.setenv("BWB_SHARED_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("YT_URL", raising=False)
    monkeypatch.setenv("YT_KEY", "ONLY_KEY_ABC_123")
    dest = resolve_destination(data_dir=tmp_path, allow_legacy_fallback=True)
    assert dest.stream_key == "ONLY_KEY_ABC_123"
    assert dest.ingest_base.endswith("/live2")


def test_invalid_saved_base_no_silent_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv("BWB_SHARED_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("YT_KEY", "LEGACY_SHOULD_NOT_APPLY_1")
    cfg = EffectiveConfig(yt_ingest_base="rtmp://evil.example/live")
    save_effective_config(cfg, tmp_path)
    save_stream_key("VALID_KEY_FOR_TEST_99", data_dir=tmp_path)
    with pytest.raises(DestinationError, match="inválida"):
        resolve_destination(data_dir=tmp_path, allow_legacy_fallback=True)


def test_reject_non_youtube_host():
    with pytest.raises(DestinationError):
        parse_full_rtmps_url("rtmps://evil.example.com/live2/ABCDE123")


def test_redact_secrets_hides_key():
    key = "SUPERSECRETKEY99"
    text = f"rtmps://a.rtmps.youtube.com/live2/{key} falhou"
    assert key not in redact_secrets(text, key)
    assert "***" in redact_secrets(text, key)


def test_default_engine_preference_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("BWB_SHARED_DATA_DIR", str(tmp_path))
    cfg = load_effective_config(tmp_path)
    assert cfg.engine_preference == ENGINE_FFMPEG


def test_manual_gstreamer_requires_eligibility():
    elig = [
        EngineEligibility(
            ENGINE_FFMPEG, MODE_TRANSCODE, True, "compatible", "ok"
        ),
        EngineEligibility(
            ENGINE_GSTREAMER,
            MODE_COPY,
            False,
            ANALYSIS_INCOMPATIBLE,
            "não H.264",
        ),
    ]
    with pytest.raises(ValueError, match="não pode iniciar"):
        select_engine(
            preference=ENGINE_GSTREAMER,
            eligibilities=elig,
            ffmpeg_available=True,
        )


def test_automatic_prefers_last_successful():
    elig = [
        EngineEligibility(
            ENGINE_FFMPEG, MODE_TRANSCODE, True, "compatible", "ff"
        ),
        EngineEligibility(
            ENGINE_GSTREAMER, MODE_COPY, True, "compatible", "gst"
        ),
    ]
    sel = select_engine(
        preference=ENGINE_AUTOMATIC,
        eligibilities=elig,
        last_successful=ENGINE_GSTREAMER,
        ffmpeg_available=True,
    )
    assert sel.engine == ENGINE_GSTREAMER


def test_automatic_without_history_ffmpeg_first():
    elig = [
        EngineEligibility(
            ENGINE_FFMPEG, MODE_TRANSCODE, True, "compatible", "ff"
        ),
        EngineEligibility(
            ENGINE_GSTREAMER, MODE_COPY, True, "compatible", "gst"
        ),
    ]
    sel = select_engine(
        preference=ENGINE_AUTOMATIC,
        eligibilities=elig,
        last_successful=None,
        ffmpeg_available=True,
    )
    assert sel.engine == ENGINE_FFMPEG


def test_indeterminate_does_not_override_known_incompatible():
    elig = [
        EngineEligibility(
            ENGINE_FFMPEG,
            MODE_TRANSCODE,
            False,
            ANALYSIS_INCOMPATIBLE,
            "sem vídeo",
        ),
        EngineEligibility(
            ENGINE_GSTREAMER,
            MODE_COPY,
            False,
            ANALYSIS_INDETERMINATE,
            "indeterminado",
        ),
    ]
    with pytest.raises(ValueError, match="Nenhum motor elegível"):
        select_engine(
            preference=ENGINE_AUTOMATIC,
            eligibilities=elig,
            ffmpeg_available=True,
        )


def test_gst_copy_ineligible_when_quality_requires_transcode():
    assert quality_requires_transcode("alta") is True
    assert quality_requires_transcode(SEND_QUALITY_SOURCE) is False
    probe = SourceProbeSummary(
        video_codec="h264",
        is_h264=True,
        analysis="compatible",
        reason="ok",
    )
    rows = evaluate_eligibility(
        preference=ENGINE_AUTOMATIC,
        send_quality="alta",
        contingency_on=False,
        mp4_ok=None,
        ffmpeg_cap=EngineCapability(ENGINE_FFMPEG, True, MODE_TRANSCODE),
        gst_cap=EngineCapability(ENGINE_GSTREAMER, True, MODE_COPY),
        probe=probe,
    )
    gst = next(r for r in rows if r.engine == ENGINE_GSTREAMER)
    assert gst.eligible is False


def test_contingency_mp4_blocks_gst_copy():
    probe = SourceProbeSummary(
        video_codec="h264", is_h264=True, analysis="compatible", reason="ok"
    )
    rows = evaluate_eligibility(
        preference=ENGINE_GSTREAMER,
        send_quality=SEND_QUALITY_SOURCE,
        contingency_on=True,
        mp4_ok=False,
        ffmpeg_cap=EngineCapability(ENGINE_FFMPEG, True, MODE_TRANSCODE),
        gst_cap=EngineCapability(ENGINE_GSTREAMER, True, MODE_COPY),
        probe=probe,
    )
    gst = next(r for r in rows if r.engine == ENGINE_GSTREAMER)
    assert gst.eligible is False
    assert "MP4" in gst.reason


def test_download_rejects_bad_hash(tmp_path, monkeypatch):
    sys.path.insert(0, str(INSTALLER))
    import download_deps

    manifest = {
        "components": {
            "ffmpeg": {
                "url": "https://example.com/ffmpeg.zip",
                "sha256": "0" * 64,
                "offline_cache_name": "ffmpeg.zip",
            }
        }
    }
    cache = tmp_path / "cache"
    cache.mkdir()
    bad = cache / "ffmpeg.zip"
    bad.write_bytes(b"not-the-right-bytes")

    with pytest.raises(download_deps.DownloadError, match="Cache inválida|Hash"):
        download_deps.ensure_component(manifest, "ffmpeg", cache_dir=cache)


def test_download_requires_pinned_sha(tmp_path):
    sys.path.insert(0, str(INSTALLER))
    import download_deps

    manifest = {
        "components": {
            "ffmpeg": {
                "url": "https://example.com/ffmpeg.zip",
                "sha256": "REPLACE_WITH_PINNED_SHA256_OF_FFMPEG_ZIP",
                "offline_cache_name": "ffmpeg.zip",
            }
        }
    }
    with pytest.raises(download_deps.DownloadError, match="SHA256|placeholder|placeholders"):
        download_deps.ensure_component(manifest, "ffmpeg", cache_dir=tmp_path)


def test_manifest_has_no_placeholders():
    sys.path.insert(0, str(INSTALLER))
    import validate_manifest

    errors = validate_manifest.validate(INSTALLER / "deps_manifest.json")
    assert errors == [], errors


def test_load_manifest_blocks_placeholders(tmp_path):
    sys.path.insert(0, str(INSTALLER))
    import download_deps

    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "components": {
                    "ffmpeg": {
                        "url": "https://example.com/x.zip",
                        "sha256": "REPLACE_WITH_PINNED_SHA256_OF_FFMPEG_ZIP",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(download_deps.DownloadError, match="placeholder"):
        download_deps.load_manifest(path)


def test_no_digitalocean_default_endpoint():
    mod = _load_stream_module()
    assert mod.DEFAULT_STATUS_ENDPOINT == ""


def test_mutex_name_unchanged():
    mod = _load_stream_module()
    assert mod._INSTANCE_MUTEX_NAME == "Global\\BWBStream2YTPrimary"


def test_build_full_url_validates_scheme():
    with pytest.raises(DestinationError):
        build_full_url("http://a.rtmps.youtube.com/live2", "KEY1234")
