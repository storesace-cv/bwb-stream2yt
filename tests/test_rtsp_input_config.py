"""Testes da configuração de entrada RTSP sem credenciais embutidas."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "primary-windows"
    / "src"
    / "stream_to_youtube.py"
)
SRC_DIR = MODULE_PATH.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

SPEC = importlib.util.spec_from_file_location(
    "_stream_to_youtube_rtsp_cfg", MODULE_PATH
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules["_stream_to_youtube_rtsp_cfg"] = module

if "autotune" not in sys.modules:
    autotune_stub = types.ModuleType("autotune")

    def _estimate_upload_bitrate(*_args, **_kwargs):
        raise NotImplementedError

    autotune_stub.estimate_upload_bitrate = _estimate_upload_bitrate  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune_stub.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune_stub

SPEC.loader.exec_module(module)


@pytest.fixture(autouse=True)
def _clear_input_env(monkeypatch):
    for key in (
        "YT_INPUT_ARGS",
        "RTSP_HOST",
        "RTSP_PORT",
        "RTSP_PATH",
        "RTSP_USERNAME",
        "RTSP_PASSWORD",
        "YT_URL",
        "YT_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(module, "_ensure_env_file", lambda: None)
    monkeypatch.setattr(module, "_load_env_files", lambda: None)


def test_default_input_args_have_no_rtsp_url():
    args = module._default_input_args()
    joined = " ".join(args)
    assert "-i" not in args
    assert "rtsp://" not in joined.lower()
    assert "@" not in joined


def test_load_config_uses_yt_input_args(monkeypatch):
    monkeypatch.setenv(
        "YT_INPUT_ARGS",
        "-rtsp_transport tcp -i rtsp://UTILIZADOR_RTSP:PALAVRA_PASSE@192.0.2.10:554/stream",
    )
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    config = module.load_config()
    assert config.input_args[-2:] == [
        "-i",
        "rtsp://UTILIZADOR_RTSP:PALAVRA_PASSE@192.0.2.10:554/stream",
    ]


def test_load_config_builds_rtsp_from_env_vars(monkeypatch):
    monkeypatch.setenv("RTSP_HOST", "192.0.2.10")
    monkeypatch.setenv("RTSP_PORT", "554")
    monkeypatch.setenv("RTSP_PATH", "Streaming/Channels/101")
    monkeypatch.setenv("RTSP_USERNAME", "UTILIZADOR_RTSP")
    monkeypatch.setenv("RTSP_PASSWORD", "PALAVRA_PASSE")
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    config = module.load_config()
    assert config.input_args[-2] == "-i"
    assert (
        config.input_args[-1]
        == "rtsp://UTILIZADOR_RTSP:PALAVRA_PASSE@192.0.2.10:554/Streaming/Channels/101"
    )
    assert config.input_args[0] == "-rtsp_transport"


def test_load_config_missing_source_raises_clear_error():
    with pytest.raises(ValueError, match="Configuração de entrada ausente"):
        module.load_config()


def test_load_config_allows_missing_source_for_demo(monkeypatch):
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    config = module.load_config(require_input_source=False)
    assert "-i" not in config.input_args
    demo = module.apply_demo_video_source(config, "/tmp/demo-exemplo.mp4")
    assert demo.demo_mode is True
    assert any(arg.endswith(".mp4") or "demo" in arg.lower() for arg in demo.input_args)
    assert "-i" in demo.input_args


def test_mask_sensitive_arg_hides_rtsp_password():
    raw = "rtsp://UTILIZADOR_RTSP:PALAVRA_PASSE@192.0.2.10:554/stream"
    masked = module._mask_sensitive_arg(raw)
    assert "PALAVRA_PASSE" not in masked
    assert "***" in masked
    assert "UTILIZADOR_RTSP" in masked


def test_diagnostics_text_does_not_expose_password(monkeypatch):
    monkeypatch.setenv(
        "YT_INPUT_ARGS",
        "-i rtsp://UTILIZADOR_RTSP:segredo-teste-xyz@192.0.2.10:554/stream",
    )
    monkeypatch.setenv("YT_URL", "rtmps://a.rtmps.youtube.com/live2/EXEMPLO")
    config = module.load_config()
    text = module._collect_full_diagnostics(config)
    assert "segredo-teste-xyz" not in text
    assert "rtsp://UTILIZADOR_RTSP:***@" in text or "***" in text
