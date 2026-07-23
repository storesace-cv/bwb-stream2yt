from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "primary-windows" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ui_settings import (  # noqa: E402
    DictSettingsStore,
    default_ui_settings,
    format_source_status,
    load_ui_settings,
    save_ui_settings,
    validate_ui_settings,
)


def test_camera_failover_defaults_false_and_persists_without_env_write(
    monkeypatch,
) -> None:
    store = DictSettingsStore()
    monkeypatch.setenv("UNRELATED_TEST_VALUE", "keep")
    env_before = dict(os.environ)
    assert default_ui_settings().camera_failover_to_demo is False

    saved = save_ui_settings(
        store, replace(default_ui_settings(), camera_failover_to_demo=True)
    )
    loaded = load_ui_settings(store)
    assert saved.camera_failover_to_demo is True
    assert loaded.camera_failover_to_demo is True
    assert dict(os.environ) == env_before


def test_validation_keeps_failover_flag_and_format_helpers_work() -> None:
    settings = validate_ui_settings(
        replace(default_ui_settings(), camera_failover_to_demo=True)
    )
    assert settings.camera_failover_to_demo is True
    assert format_source_status(settings) == "Fonte: Câmara"
