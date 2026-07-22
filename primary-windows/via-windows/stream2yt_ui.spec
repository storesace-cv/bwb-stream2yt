# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the primary Windows UI (stream2yt-ui).

Produces dist/stream2yt-ui/stream2yt-ui.exe plus accompanying libraries.
FFmpeg is NOT bundled; the runtime uses the configured FFMPEG path.
"""

import inspect
from pathlib import Path

block_cipher = None

if "__file__" in globals():
    BASE_DIR = Path(__file__).resolve().parent
else:
    current_frame = inspect.currentframe()
    try:
        BASE_DIR = Path(inspect.getfile(current_frame)).resolve().parent
    finally:
        del current_frame

SRC_DIR = (BASE_DIR / ".." / "src").resolve()
SCRIPT = SRC_DIR / "ui_launcher.py"

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "ui_app",
    "observability",
    "preview_rtsp",
    "stream_to_youtube",
    "autotune",
]

analysis = Analysis(
    [str(SCRIPT)],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="stream2yt-ui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="stream2yt-ui",
)
