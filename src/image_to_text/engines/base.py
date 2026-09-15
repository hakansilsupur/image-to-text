"""Engine-agnostic OCR types and the base class every engine implements."""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image


class OcrError(RuntimeError):
    """Raised when an engine cannot produce a result."""


class EngineUnavailableError(OcrError):
    """Raised when an engine is not usable on this machine."""


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in pixel coordinates of the recognized image."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True)
class Word:
    text: str
    box: Box | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class Line:
    text: str
    words: tuple[Word, ...] = ()

    @property
    def box(self) -> Box | None:
        """Bounding box covering every word on the line, when boxes are known."""
        boxes = [w.box for w in self.words if w.box is not None]
        if not boxes:
            return None
        left = min(b.x for b in boxes)
        top = min(b.y for b in boxes)
        right = max(b.right for b in boxes)
        bottom = max(b.bottom for b in boxes)
        return Box(left, top, right - left, bottom - top)


@dataclass(frozen=True)
class OcrResult:
    text: str
    lines: tuple[Line, ...] = ()
    engine: str = ""
    language: str = ""
    duration: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def char_count(self) -> int:
        return len(self.text)


def result_from_lines(
    lines: Sequence[Line],
    *,
    engine: str,
    language: str,
    duration: float = 0.0,
) -> OcrResult:
    """Build a result whose ``text`` is the lines joined with newlines."""
    text = "\n".join(line.text for line in lines)
    return OcrResult(
        text=text,
        lines=tuple(lines),
        engine=engine,
        language=language,
        duration=duration,
    )


class OcrEngine(abc.ABC):
    """Common interface for the OCR backends the app can drive."""

    #: Stable identifier persisted in settings.
    name: str = ""
    #: Human readable name shown in the UI.
    display_name: str = ""
    #: Short note rendered next to the engine in menus.
    description: str = ""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Whether this engine can run right now."""

    def unavailable_reason(self) -> str:
        """Human readable explanation for why :meth:`is_available` is false."""
        return "" if self.is_available() else "Engine is not available on this system."

    @abc.abstractmethod
    def languages(self) -> list[str]:
        """Language tags this engine can recognize, best first."""

    def default_language(self) -> str:
        langs = self.languages()
        return langs[0] if langs else ""

    @abc.abstractmethod
    def recognize(self, image: Image, language: str | None = None) -> OcrResult:
        """Recognize text in ``image``."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.display_name or self.name
