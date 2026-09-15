"""Finding bundled files, whether running from source or from the built .exe."""

from __future__ import annotations

import sys
from pathlib import Path


def resource_dir() -> Path:
    """Directory holding the bundled assets."""
    # PyInstaller unpacks a one-file build into a temporary folder it points
    # sys._MEIPASS at; from a source checkout the assets sit beside the package.
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def resource_path(name: str) -> Path | None:
    """Full path to a bundled asset, or ``None`` when it is missing."""
    candidate = resource_dir() / name
    return candidate if candidate.is_file() else None


def icon_path() -> Path | None:
    return resource_path("app.ico")


def icon_png_path() -> Path | None:
    return resource_path("app.png")
