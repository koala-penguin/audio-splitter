# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AudioSplitter.

Builds a single-file binary on the host platform:
    - Windows -> dist/AudioSplitter.exe
    - macOS   -> dist/AudioSplitter (and a .app bundle alongside)

Notes:
- imageio_ffmpeg ships its ffmpeg binary as a data file; we use
  collect_all to pull the package + binaries automatically.
- pydub has no compiled deps but imports lazily; collect_submodules
  guards against missing-module errors at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

datas: list = []
binaries: list = []
hiddenimports: list = []

for pkg in ("imageio_ffmpeg", "pydub"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("audio_splitter")

a = Analysis(
    [str(SRC_DIR / "audio_splitter" / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy Qt modules we don't use; trims ~50-100 MB on the bundle.
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQml",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "tkinter",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AudioSplitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # GUI app: no console window on Windows
    disable_windowed_traceback=False,
    argv_emulation=True,       # macOS: lets file-open events come through argv
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS .app bundle (only emitted when building on darwin)
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="AudioSplitter.app",
        icon=None,
        bundle_identifier="com.lanclaude.audiosplitter",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "LSMinimumSystemVersion": "11.0",
        },
    )
