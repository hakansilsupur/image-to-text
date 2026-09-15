from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def text_image(tmp_path: Path):
    """A small black-on-white picture with a word on it."""

    def _make(word: str = "HELLO", size=(320, 120), name: str = "sample.png") -> Path:
        image = Image.new("RGB", size, "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 40), word, fill="black")
        path = tmp_path / name
        image.save(path)
        return path

    return _make


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep tests from touching the real %APPDATA% settings file."""
    monkeypatch.setenv("IMAGE_TO_TEXT_CONFIG_DIR", str(tmp_path / "config"))
