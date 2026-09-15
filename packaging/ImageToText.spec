# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a single-file ImageToText.exe (PyInstaller 6.x).

    pyinstaller packaging\\ImageToText.spec

Run it from the repository root; build.bat does that for you.
"""

from pathlib import Path

# SPECPATH is the folder holding this spec file; the project root is its parent.
ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "packaging" / "windows_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[
        (str(ROOT / "assets" / "app.ico"), "assets"),
        (str(ROOT / "assets" / "app.png"), "assets"),
    ],
    # winsdk resolves its WinRT namespaces at runtime, so PyInstaller cannot
    # see these imports by itself.
    hiddenimports=[
        # Pillow loads this indirectly from ImageTk; without it the frozen app
        # dies the moment it shows a picture.
        "PIL._tkinter_finder",
        "winsdk",
        "winsdk.windows.media.ocr",
        "winsdk.windows.graphics.imaging",
        "winsdk.windows.storage.streams",
        "winsdk.windows.globalization",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here uses these; excluding them keeps the .exe a sensible size.
    excludes=["matplotlib", "numpy", "scipy", "pandas", "PyQt5", "PySide2", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ImageToText",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # A GUI app, so no console window flashes up behind it.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico"),
)
