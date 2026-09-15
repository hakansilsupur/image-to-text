"""OCR backed by the recognizer that ships with Windows 10/11.

Uses ``Windows.Media.Ocr`` through the Python/WinRT projection, so there is
nothing for the user to install beyond the app itself: the language packs
already present on the machine are what the engine can read.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
from typing import TYPE_CHECKING, Any

from .base import (
    Box,
    EngineUnavailableError,
    Line,
    OcrEngine,
    OcrError,
    OcrResult,
    Word,
    result_from_lines,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

# Both the monolithic ``winsdk`` package and the newer split ``winrt-*``
# packages expose the same namespaces; accept whichever is installed.
_WINRT_ROOTS = ("winsdk", "winrt")

# Fallback used when the recognizer does not report its own limit.
_FALLBACK_MAX_DIMENSION = 2600


class _WinRt:
    """Lazily imported handles to the WinRT types this engine needs."""

    def __init__(self, root: str) -> None:
        from importlib import import_module

        self.root = root
        ocr = import_module(f"{root}.windows.media.ocr")
        imaging = import_module(f"{root}.windows.graphics.imaging")
        streams = import_module(f"{root}.windows.storage.streams")
        globalization = import_module(f"{root}.windows.globalization")

        self.OcrEngine = ocr.OcrEngine
        self.BitmapDecoder = imaging.BitmapDecoder
        self.InMemoryRandomAccessStream = streams.InMemoryRandomAccessStream
        self.DataWriter = streams.DataWriter
        self.Language = globalization.Language


_winrt: _WinRt | None = None
_import_error: str = ""


def _load_winrt() -> _WinRt | None:
    """Import the WinRT projection once, remembering any failure."""
    global _winrt, _import_error
    if _winrt is not None or _import_error:
        return _winrt
    if not sys.platform.startswith("win"):
        _import_error = "The Windows OCR engine only runs on Windows."
        return None
    errors = []
    for root in _WINRT_ROOTS:
        try:
            _winrt = _WinRt(root)
            return _winrt
        except Exception as exc:  # pragma: no cover - depends on installed wheels
            errors.append(f"{root}: {exc}")
    _import_error = (
        "Python/WinRT is not installed. Run `pip install winsdk` to enable the "
        "built-in Windows recognizer. (" + "; ".join(errors) + ")"
    )
    return None


def _static(owner: Any, name: str, default: Any = None) -> Any:
    """Read a WinRT static property, tolerating getter-style projections."""
    for attr in (name, f"get_{name}"):
        value = getattr(owner, attr, None)
        if value is None:
            continue
        return value() if callable(value) else value
    return default


class WindowsOcrEngine(OcrEngine):
    name = "windows"
    display_name = "Windows OCR"
    description = "Built into Windows 10/11 - no extra download"

    def __init__(self) -> None:
        self._languages: list[str] | None = None

    # -- availability -----------------------------------------------------
    def is_available(self) -> bool:
        return bool(_load_winrt()) and bool(self.languages())

    def unavailable_reason(self) -> str:
        if not sys.platform.startswith("win"):
            return "The Windows OCR engine only runs on Windows."
        if _load_winrt() is None:
            return _import_error
        if not self.languages():
            return (
                "Windows has no OCR language packs installed. Add one under "
                "Settings > Time & language > Language & region > (language) > "
                "Language options > Optical character recognition."
            )
        return ""

    # -- languages --------------------------------------------------------
    def languages(self) -> list[str]:
        if self._languages is not None:
            return self._languages
        winrt = _load_winrt()
        if winrt is None:
            self._languages = []
            return self._languages
        try:
            available = _static(winrt.OcrEngine, "available_recognizer_languages", []) or []
            self._languages = [lang.language_tag for lang in available]
        except Exception:  # pragma: no cover - defensive
            self._languages = []
        return self._languages

    def default_language(self) -> str:
        langs = self.languages()
        if not langs:
            return ""
        # Prefer whatever matches the user's own display language.
        winrt = _load_winrt()
        if winrt is not None:
            try:
                engine = winrt.OcrEngine.try_create_from_user_profile_languages()
                if engine is not None:
                    tag = engine.recognizer_language.language_tag
                    if tag in langs:
                        return tag
            except Exception:  # pragma: no cover - defensive
                pass
        return langs[0]

    def max_image_dimension(self) -> int:
        winrt = _load_winrt()
        if winrt is None:
            return _FALLBACK_MAX_DIMENSION
        try:
            value = int(_static(winrt.OcrEngine, "max_image_dimension", 0) or 0)
        except Exception:  # pragma: no cover - defensive
            value = 0
        return value or _FALLBACK_MAX_DIMENSION

    # -- recognition ------------------------------------------------------
    def recognize(self, image: Image, language: str | None = None) -> OcrResult:
        winrt = _load_winrt()
        if winrt is None:
            raise EngineUnavailableError(self.unavailable_reason())

        from ..imaging import fit_within  # local import keeps engines import-light

        tag = language or self.default_language()
        if not tag:
            raise EngineUnavailableError(self.unavailable_reason())

        prepared = fit_within(image, self.max_image_dimension())
        png = _to_png_bytes(prepared)

        started = time.perf_counter()
        try:
            raw = asyncio.run(_recognize_async(winrt, png, tag))
        except EngineUnavailableError:
            raise
        except Exception as exc:
            raise OcrError(f"Windows OCR failed: {exc}") from exc
        duration = time.perf_counter() - started

        scale_x = image.width / prepared.width if prepared.width else 1.0
        scale_y = image.height / prepared.height if prepared.height else 1.0
        lines = tuple(_convert_line(line, scale_x, scale_y) for line in raw.lines)
        return result_from_lines(lines, engine=self.name, language=tag, duration=duration)


async def _recognize_async(winrt: _WinRt, png: bytes, tag: str) -> Any:
    stream = winrt.InMemoryRandomAccessStream()
    writer = winrt.DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(png)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await winrt.BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    language = winrt.Language(tag)
    engine = winrt.OcrEngine.try_create_from_language(language)
    if engine is None:
        raise EngineUnavailableError(
            f"Windows has no OCR language pack for '{tag}'. Install it under "
            "Settings > Time & language > Language & region."
        )
    return await engine.recognize_async(bitmap)


def _convert_line(raw_line: Any, scale_x: float, scale_y: float) -> Line:
    words = []
    for raw_word in raw_line.words:
        rect = raw_word.bounding_rect
        words.append(
            Word(
                text=raw_word.text,
                box=Box(
                    rect.x * scale_x,
                    rect.y * scale_y,
                    rect.width * scale_x,
                    rect.height * scale_y,
                ),
            )
        )
    return Line(text=raw_line.text, words=tuple(words))


def _to_png_bytes(image: Image) -> bytes:
    buffer = io.BytesIO()
    # The decoder wants a plain RGB/RGBA surface; palette and CMYK modes are not
    # something Windows' bitmap decoder accepts for OCR.
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGB")
    image.save(buffer, format="PNG")
    return buffer.getvalue()
