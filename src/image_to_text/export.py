"""Turning recognized text into something the user can keep."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from pathlib import Path

from .engines import OcrResult

#: Windows tools (Notepad included) are happiest with CRLF in .txt files.
WINDOWS_NEWLINE = "\r\n"


def normalize_newlines(text: str, newline: str = "\n") -> str:
    """Collapse mixed CRLF/CR/LF line endings to ``newline``."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    return unified if newline == "\n" else unified.replace("\n", newline)


def clean_text(text: str) -> str:
    """Trim trailing whitespace per line and blank lines at the ends."""
    lines = [line.rstrip() for line in normalize_newlines(text).split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def default_output_path(image_path: str | Path | None, suffix: str = ".txt") -> str:
    """Suggest a file name for the text extracted from ``image_path``."""
    if not image_path:
        return f"extracted-text{suffix}"
    path = Path(image_path)
    return str(path.with_suffix(suffix).name)


def save_text(path: str | Path, text: str, *, newline: str = WINDOWS_NEWLINE) -> Path:
    """Write ``text`` to ``path`` as UTF-8 with a BOM.

    The BOM is what makes Notepad and Excel read non-ASCII output correctly on
    Windows, which is where this app runs.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" turns off Python's own line-ending translation, which would
    # otherwise expand our CRLF into CRCRLF on Windows.
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(normalize_newlines(text, newline))
    return path


def results_to_json(results: Iterable[tuple[str, OcrResult]]) -> str:
    """Serialize ``(source, result)`` pairs, boxes included, as JSON."""
    payload = []
    for source, result in results:
        payload.append(
            {
                "source": source,
                "engine": result.engine,
                "language": result.language,
                "duration": round(result.duration, 3),
                "text": result.text,
                "lines": [
                    {
                        "text": line.text,
                        "box": _box_to_dict(line.box),
                        "words": [
                            {"text": word.text, "box": _box_to_dict(word.box)}
                            for word in line.words
                        ],
                    }
                    for line in result.lines
                ],
            }
        )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def results_to_csv(results: Sequence[tuple[str, OcrResult]]) -> str:
    """One row per recognized line, for pasting into a spreadsheet."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["source", "line_number", "text"])
    for source, result in results:
        for index, line in enumerate(result.lines, start=1):
            writer.writerow([source, index, line.text])
    return buffer.getvalue()


def _box_to_dict(box) -> dict | None:
    if box is None:
        return None
    return {
        "x": round(box.x, 2),
        "y": round(box.y, 2),
        "width": round(box.width, 2),
        "height": round(box.height, 2),
    }
