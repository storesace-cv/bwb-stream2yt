# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build configuration for the Windows primary executable.

This mirrors the CLI invocation:
pyinstaller --onefile --noconsole --hidden-import win32timezone --collect-binaries pywin32 \
    primary-windows/src/stream_to_youtube.py
"""

import inspect
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

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
SCRIPT = SRC_DIR / "stream_to_youtube.py"

pywin32_datas, pywin32_binaries, pywin32_hiddenimports = collect_all("pywin32")

analysis = Analysis(
    [str(SCRIPT)],
    pathex=[str(SRC_DIR)],
    binaries=pywin32_binaries,
    datas=pywin32_datas,
    hiddenimports=["win32timezone", *pywin32_hiddenimports],
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
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    [],
    name="stream_to_youtube",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
