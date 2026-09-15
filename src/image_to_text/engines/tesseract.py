"""OCR backed by Tesseract, for languages Windows does not ship a pack for.

Optional: the app runs fine without it, and simply hides the engine when no
``tesseract.exe`` can be found.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import TYPE_CHECKING

from .base import EngineUnavailableError, Line, OcrEngine, OcrError, OcrResult, result_from_lines

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

INSTALL_HINT = (
    "Tesseract was not found. Install it from "
    "https://github.com/UB-Mannheim/tesseract/wiki and run `pip install pytesseract`, "
    "or set the TESSERACT_CMD environment variable to tesseract.exe."
)

#: Where the UB-Mannheim installer puts the binary, in the order we try them.
WINDOWS_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe",
    r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe",
)


def find_tesseract() -> str:
    """Return the path to ``tesseract``/``tesseract.exe``, or an empty string."""
    override = os.environ.get("TESSERACT_CMD", "").strip().strip('"')
    if override:
        return override if os.path.isfile(override) else ""

    found = shutil.which("tesseract")
    if found:
        return found

    if sys.platform.startswith("win"):
        for candidate in WINDOWS_CANDIDATES:
            expanded = os.path.expandvars(candidate)
            if "%" not in expanded and os.path.isfile(expanded):
                return expanded
    return ""


class TesseractEngine(OcrEngine):
    name = "tesseract"
    display_name = "Tesseract"
    description = "Optional - install separately for more languages"

    #: Tesseract page segmentation mode: assume a single uniform block of text.
    page_segmentation_mode = 3

    def __init__(self) -> None:
        self._languages: list[str] | None = None
        self._binary: str | None = None
        self._reason = ""

    # -- availability -----------------------------------------------------
    def _pytesseract(self):
        try:
            import pytesseract
        except ImportError:
            self._reason = INSTALL_HINT
            return None
        binary = self.binary()
        if not binary:
            self._reason = INSTALL_HINT
            return None
        pytesseract.pytesseract.tesseract_cmd = binary
        return pytesseract

    def binary(self) -> str:
        if self._binary is None:
            self._binary = find_tesseract()
        return self._binary

    def is_available(self) -> bool:
        return self._pytesseract() is not None

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return self._reason or INSTALL_HINT

    # -- languages --------------------------------------------------------
    def languages(self) -> list[str]:
        if self._languages is not None:
            return self._languages
        pytesseract = self._pytesseract()
        if pytesseract is None:
            self._languages = []
            return self._languages
        try:
            langs = [lang for lang in pytesseract.get_languages(config="") if lang != "osd"]
        except Exception:  # pragma: no cover - depends on the local install
            langs = []
        # "eng" first when present, everything else alphabetically.
        langs.sort(key=lambda lang: (lang != "eng", lang))
        self._languages = langs
        return self._languages

    # -- recognition ------------------------------------------------------
    def recognize(self, image: Image, language: str | None = None) -> OcrResult:
        pytesseract = self._pytesseract()
        if pytesseract is None:
            raise EngineUnavailableError(self.unavailable_reason())

        lang = language or self.default_language() or "eng"
        config = f"--psm {self.page_segmentation_mode}"

        started = time.perf_counter()
        try:
            text = pytesseract.image_to_string(image, lang=lang, config=config)
        except Exception as exc:
            raise OcrError(f"Tesseract failed: {exc}") from exc
        duration = time.perf_counter() - started

        lines = tuple(Line(text=line) for line in text.replace("\r\n", "\n").split("\n"))
        # Tesseract likes to end on a blank line; drop trailing empties only.
        while lines and not lines[-1].text.strip():
            lines = lines[:-1]
        return result_from_lines(lines, engine=self.name, language=lang, duration=duration)
