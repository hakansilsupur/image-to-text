"""Persisted user preferences, stored next to the app's other roaming data."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .imaging import PreprocessOptions

APP_NAME = "ImageToText"


def config_dir() -> Path:
    """Per-user config directory (``%APPDATA%\\ImageToText`` on Windows)."""
    override = os.environ.get("IMAGE_TO_TEXT_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def settings_path() -> Path:
    return config_dir() / "settings.json"


@dataclass
class Settings:
    """Everything the app remembers between runs."""

    engine: str = ""
    #: Last language per engine, since the engines use different tag styles
    #: ("en-US" for Windows OCR, "eng" for Tesseract).
    languages: dict[str, str] = field(default_factory=dict)
    preprocess: PreprocessOptions = field(default_factory=PreprocessOptions)
    last_open_dir: str = ""
    last_save_dir: str = ""
    window_geometry: str = ""
    wrap_text: bool = True
    auto_copy: bool = False

    # -- language helpers -------------------------------------------------
    def language_for(self, engine: str) -> str:
        return self.languages.get(engine, "")

    def set_language(self, engine: str, language: str) -> None:
        if engine:
            self.languages[engine] = language

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "languages": dict(self.languages),
            "preprocess": self.preprocess.to_dict(),
            "last_open_dir": self.last_open_dir,
            "last_save_dir": self.last_save_dir,
            "window_geometry": self.window_geometry,
            "wrap_text": self.wrap_text,
            "auto_copy": self.auto_copy,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> Settings:
        data = data or {}
        languages = data.get("languages")
        return cls(
            engine=str(data.get("engine") or ""),
            languages={
                str(k): str(v) for k, v in languages.items() if isinstance(v, str)
            }
            if isinstance(languages, dict)
            else {},
            preprocess=PreprocessOptions.from_dict(data.get("preprocess")),
            last_open_dir=str(data.get("last_open_dir") or ""),
            last_save_dir=str(data.get("last_save_dir") or ""),
            window_geometry=str(data.get("window_geometry") or ""),
            wrap_text=bool(data.get("wrap_text", True)),
            auto_copy=bool(data.get("auto_copy", False)),
        )

    # -- disk -------------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Read saved settings, falling back to defaults on any problem.

        A broken settings file should never stop the app from starting.
        """
        path = path or settings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    def save(self, path: Path | None = None) -> bool:
        """Write settings to disk; returns whether it worked."""
        path = path or settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            return False
        return True
