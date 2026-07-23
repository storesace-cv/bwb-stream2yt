"""Cobertura leve da configuração do worker em failover."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if "autotune" not in sys.modules:
    autotune = types.ModuleType("autotune")
    autotune.estimate_upload_bitrate = lambda *_a, **_kw: None  # type: ignore[attr-defined]
    autotune.AUTOTUNE_AVAILABLE = False  # type: ignore[attr-defined]
    autotune.AUTOTUNE_UNAVAILABLE_REASON = ""  # type: ignore[attr-defined]
    sys.modules["autotune"] = autotune

spec = importlib.util.spec_from_file_location(
    "_stream_worker_failover_test", SRC / "stream_to_youtube.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _config():
    return module.StreamingConfig(
        yt_url="rtmps://example/live2/key",
        input_args=["-i", "rtsp://camera/stream"],
        output_args=["-c:v", "libx264"],
        resolution="720p",
        ffmpeg="ffmpeg",
        day_start_hour=0,
        day_end_hour=24,
        tz_offset_hours=0,
        autotune_enabled=False,
        bitrate_min_kbps=1000,
        bitrate_max_kbps=2000,
        autotune_interval=8,
        autotune_safety_margin=0.2,
        heartbeat=module.HeartbeatConfig(
            False, None, 20, 5, "TEST", None, Path("hb"), 3600
        ),
        camera_probe=module.CameraProbeConfig("ffprobe", 5, 2, False),
    )


def test_failover_worker_prepares_two_configs_and_single_process_slot() -> None:
    worker = module.StreamingWorker(
        _config(), failover_enabled=True, contingency_demo_path="/tmp/demo.mp4"
    )
    assert worker._camera_config is not None  # noqa: SLF001
    assert worker._contingency_demo_config is not None  # noqa: SLF001
    assert worker._process is None  # noqa: SLF001

    snapshot = worker.status_snapshot()
    assert snapshot["failover_enabled"] is True
    assert snapshot["configured_source"] == "camera"
    assert snapshot["effective_source"] == "camera"
    assert snapshot["failover_transition_active"] is False
