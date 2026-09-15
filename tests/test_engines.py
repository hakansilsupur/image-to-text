from __future__ import annotations

import pytest
from PIL import Image

from image_to_text import engines
from image_to_text.engines import (
    Box,
    EngineUnavailableError,
    Line,
    OcrEngine,
    Word,
    result_from_lines,
)
from image_to_text.engines.tesseract import TesseractEngine, find_tesseract
from image_to_text.engines.windows_ocr import WindowsOcrEngine


class FakeEngine(OcrEngine):
    name = "fake"
    display_name = "Fake"

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls: list[tuple] = []

    def is_available(self) -> bool:
        return self.available

    def languages(self) -> list[str]:
        return ["xx-XX", "yy-YY"] if self.available else []

    def recognize(self, image, language=None):
        self.calls.append((image.size, language))
        return result_from_lines(
            [Line(text="hello"), Line(text="world")],
            engine=self.name,
            language=language or "xx-XX",
        )


@pytest.fixture
def registry(monkeypatch):
    """Swap the real engine registry for controllable fakes."""
    ready = FakeEngine(available=True)
    missing = FakeEngine(available=False)
    missing.name = "missing"
    missing.display_name = "Missing"
    monkeypatch.setattr(engines, "all_engines", lambda: [missing, ready])
    monkeypatch.setattr(
        engines, "available_engines", lambda: [e for e in (missing, ready) if e.is_available()]
    )
    return ready, missing


def test_line_box_spans_its_words():
    line = Line(
        text="two words",
        words=(
            Word("two", Box(10, 20, 30, 10)),
            Word("words", Box(50, 18, 40, 14)),
        ),
    )

    box = line.box
    assert (box.x, box.y) == (10, 18)
    assert box.right == 90
    assert box.bottom == 32


def test_line_box_is_none_without_word_boxes():
    assert Line(text="plain", words=(Word("plain"),)).box is None


def test_result_counts():
    result = result_from_lines(
        [Line(text="one two"), Line(text="three")], engine="fake", language="xx"
    )
    assert result.text == "one two\nthree"
    assert result.word_count == 3
    assert result.char_count == len("one two\nthree")


def test_resolve_engine_prefers_the_named_one(registry):
    ready, _missing = registry
    assert engines.resolve_engine("fake") is ready


def test_resolve_engine_falls_back_when_unavailable(registry):
    ready, _missing = registry
    assert engines.resolve_engine("missing") is ready
    assert engines.resolve_engine(None) is ready


def test_resolve_engine_explains_when_nothing_is_available(monkeypatch):
    missing = FakeEngine(available=False)
    monkeypatch.setattr(engines, "all_engines", lambda: [missing])
    monkeypatch.setattr(engines, "available_engines", lambda: [])

    with pytest.raises(EngineUnavailableError) as excinfo:
        engines.resolve_engine("fake")

    assert "No OCR engine is available" in str(excinfo.value)
    assert missing.display_name in str(excinfo.value)


def test_get_engine_knows_the_real_engines():
    assert isinstance(engines.get_engine("windows"), WindowsOcrEngine)
    assert isinstance(engines.get_engine("tesseract"), TesseractEngine)
    assert engines.get_engine("nope") is None


def test_engines_are_reused_across_lookups():
    assert engines.get_engine("windows") is engines.get_engine("windows")


def test_default_language_is_the_first_language():
    assert FakeEngine().default_language() == "xx-XX"
    assert FakeEngine(available=False).default_language() == ""


def test_windows_engine_is_unavailable_off_windows(monkeypatch):
    monkeypatch.setattr("image_to_text.engines.windows_ocr.sys.platform", "linux")
    monkeypatch.setattr("image_to_text.engines.windows_ocr._winrt", None)
    monkeypatch.setattr("image_to_text.engines.windows_ocr._import_error", "")

    engine = WindowsOcrEngine()

    assert engine.is_available() is False
    assert "only runs on Windows" in engine.unavailable_reason()
    with pytest.raises(EngineUnavailableError):
        engine.recognize(Image.new("RGB", (10, 10)))


def test_tesseract_uses_the_env_override(monkeypatch, tmp_path):
    binary = tmp_path / "tesseract.exe"
    binary.write_text("")
    monkeypatch.setenv("TESSERACT_CMD", str(binary))

    assert find_tesseract() == str(binary)


def test_tesseract_env_override_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "missing.exe"))
    assert find_tesseract() == ""


def test_tesseract_reports_install_hint_when_missing(monkeypatch):
    monkeypatch.setattr("image_to_text.engines.tesseract.find_tesseract", lambda: "")

    engine = TesseractEngine()

    assert engine.is_available() is False
    assert "Install it from" in engine.unavailable_reason()
    assert engine.languages() == []
