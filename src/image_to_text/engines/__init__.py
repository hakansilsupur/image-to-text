"""Registry of the OCR engines the app can drive."""

from __future__ import annotations

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
from .tesseract import TesseractEngine
from .windows_ocr import WindowsOcrEngine

#: Engines in preference order: the Windows recognizer needs no install, so it
#: goes first, with Tesseract as the opt-in alternative.
_ENGINE_TYPES: tuple[type[OcrEngine], ...] = (WindowsOcrEngine, TesseractEngine)

_instances: dict[str, OcrEngine] = {}


def all_engines() -> list[OcrEngine]:
    """Every known engine, available or not, in preference order."""
    for engine_type in _ENGINE_TYPES:
        if engine_type.name not in _instances:
            _instances[engine_type.name] = engine_type()
    return [_instances[engine_type.name] for engine_type in _ENGINE_TYPES]


def available_engines() -> list[OcrEngine]:
    """Engines that can actually run on this machine."""
    return [engine for engine in all_engines() if engine.is_available()]


def get_engine(name: str) -> OcrEngine | None:
    """Look up an engine by its stable ``name``."""
    for engine in all_engines():
        if engine.name == name:
            return engine
    return None


def default_engine() -> OcrEngine | None:
    """The engine to use when the user has not chosen one."""
    available = available_engines()
    return available[0] if available else None


def resolve_engine(name: str | None) -> OcrEngine:
    """Return the named engine, falling back to the best available one.

    Raises :class:`EngineUnavailableError` when nothing can run, with a message
    that explains what to install.
    """
    if name:
        engine = get_engine(name)
        if engine is not None and engine.is_available():
            return engine
    fallback = default_engine()
    if fallback is not None:
        return fallback
    reasons = [
        f"- {engine.display_name}: {engine.unavailable_reason()}" for engine in all_engines()
    ]
    raise EngineUnavailableError("No OCR engine is available.\n" + "\n".join(reasons))


__all__ = [
    "Box",
    "EngineUnavailableError",
    "Line",
    "OcrEngine",
    "OcrError",
    "OcrResult",
    "TesseractEngine",
    "WindowsOcrEngine",
    "Word",
    "all_engines",
    "available_engines",
    "default_engine",
    "get_engine",
    "resolve_engine",
    "result_from_lines",
]
