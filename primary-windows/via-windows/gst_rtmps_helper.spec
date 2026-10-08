# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile for gst_rtmps_helper (sem gi; usa gst-launch do runtime)."""

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
SCRIPT = SRC_DIR / "gst_rtmps_helper.py"

analysis = Analysis(
    [str(SCRIPT)],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["gi", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="gst_rtmps_helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
