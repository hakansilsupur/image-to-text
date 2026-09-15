"""The one place that ties loading, preprocessing and recognition together.

Both the window and the command line go through here, so they cannot drift.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .engines import OcrEngine, OcrResult, resolve_engine
from .imaging import PreprocessOptions, load_image, preprocess


def recognize_image(
    image: Image.Image,
    *,
    engine: OcrEngine | str | None = None,
    language: str | None = None,
    options: PreprocessOptions | None = None,
) -> OcrResult:
    """Run OCR over ``image`` after applying ``options``."""
    ocr_engine = engine if isinstance(engine, OcrEngine) else resolve_engine(engine)
    prepared = preprocess(image, options)
    return ocr_engine.recognize(prepared, language)


def recognize_file(
    path: str | Path,
    *,
    engine: OcrEngine | str | None = None,
    language: str | None = None,
    options: PreprocessOptions | None = None,
) -> OcrResult:
    """Load the image at ``path`` and recognize its text."""
    return recognize_image(
        load_image(path), engine=engine, language=language, options=options
    )
