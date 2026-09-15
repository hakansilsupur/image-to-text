"""Command line front end, for scripting and batch conversion.

    image-to-text scan.png
    image-to-text receipts\\*.jpg --out text\\ --format txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .engines import EngineUnavailableError, OcrError, all_engines, resolve_engine
from .export import clean_text, results_to_csv, results_to_json, save_text
from .imaging import SUPPORTED_EXTENSIONS, ImageLoadError, PreprocessOptions
from .ocr import recognize_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image-to-text",
        description="Extract text from images using an OCR engine.",
    )
    parser.add_argument(
        "images",
        nargs="*",
        help="Image files or folders to read. Folders are scanned one level deep.",
    )
    parser.add_argument("--version", action="version", version=f"image-to-text {__version__}")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the window instead of printing to the console.",
    )
    parser.add_argument(
        "-e",
        "--engine",
        help="OCR engine to use (see --list-engines).",
    )
    parser.add_argument("-l", "--language", help="Language tag, e.g. en-US or eng.")
    parser.add_argument(
        "-o",
        "--out",
        help="Write results here: a folder for many inputs, a file for one.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("txt", "json", "csv"),
        default="txt",
        help="Output format (default: txt).",
    )
    parser.add_argument(
        "--list-engines",
        action="store_true",
        help="Show the available engines and their languages, then exit.",
    )

    group = parser.add_argument_group("image preparation")
    group.add_argument("--no-grayscale", action="store_true", help="Keep colour.")
    group.add_argument("--no-autocontrast", action="store_true", help="Skip contrast stretch.")
    group.add_argument("--no-upscale", action="store_true", help="Skip upscaling small images.")
    group.add_argument("--sharpen", action="store_true", help="Sharpen before recognition.")
    group.add_argument("--invert", action="store_true", help="Invert (for light-on-dark text).")
    group.add_argument(
        "--threshold",
        type=int,
        metavar="0-255",
        help="Binarize at this cut-off.",
    )
    group.add_argument("--scale", type=float, default=1.0, help="Extra scale factor.")
    group.add_argument(
        "--rotate",
        type=int,
        default=0,
        metavar="DEGREES",
        help="Rotate clockwise before recognition.",
    )
    return parser


def options_from_args(args: argparse.Namespace) -> PreprocessOptions:
    options = PreprocessOptions(
        grayscale=not args.no_grayscale,
        autocontrast=not args.no_autocontrast,
        sharpen=args.sharpen,
        invert=args.invert,
        threshold=args.threshold,
        scale=args.scale,
        rotation=args.rotate,
        auto_upscale=not args.no_upscale,
    )
    options.normalize()
    return options


def collect_images(inputs: list[str]) -> list[Path]:
    """Expand the given files and folders into a sorted list of image paths."""
    found: list[Path] = []
    for entry in inputs:
        path = Path(entry)
        if path.is_dir():
            found.extend(
                sorted(
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            )
        else:
            found.append(path)
    # Preserve order while dropping duplicates.
    seen: set[Path] = set()
    unique = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def print_engines(stream=None) -> int:
    # Resolved on each call, so a redirected sys.stdout is honoured.
    stream = stream or sys.stdout
    for engine in all_engines():
        if engine.is_available():
            langs = ", ".join(engine.languages()) or "(none reported)"
            print(f"{engine.name:<10} {engine.display_name} - available", file=stream)
            print(f"{'':<10} languages: {langs}", file=stream)
        else:
            print(f"{engine.name:<10} {engine.display_name} - unavailable", file=stream)
            print(f"{'':<10} {engine.unavailable_reason()}", file=stream)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_engines:
        return print_engines()

    if args.gui or not args.images:
        from .app import run

        return run(args.images)

    try:
        engine = resolve_engine(args.engine)
    except EngineUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    paths = collect_images(args.images)
    if not paths:
        print("No image files matched.", file=sys.stderr)
        return 1

    options = options_from_args(args)
    language = args.language or engine.default_language()
    results = []
    failures = 0

    for path in paths:
        try:
            result = recognize_file(path, engine=engine, language=language, options=options)
        except (ImageLoadError, OcrError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue
        results.append((str(path), result))

    if not results:
        return 1

    _write_output(results, args)
    return 1 if failures else 0


def _write_output(results, args: argparse.Namespace) -> None:
    out = Path(args.out) if args.out else None
    multiple = len(results) > 1

    if args.format == "json":
        _emit(results_to_json(results), out, results, args, ".json")
        return
    if args.format == "csv":
        _emit(results_to_csv(results), out, results, args, ".csv")
        return

    if out is None:
        for index, (source, result) in enumerate(results):
            if multiple:
                header = f"=== {source} ===" if index == 0 else f"\n=== {source} ==="
                print(header)
            print(clean_text(result.text))
        return

    # A folder (explicit trailing separator, an existing directory, or several
    # inputs) gets one .txt per image; otherwise everything goes to one file.
    as_folder = out.is_dir() or multiple or args.out.endswith(("/", "\\"))
    if as_folder:
        out.mkdir(parents=True, exist_ok=True)
        for source, result in results:
            target = out / (Path(source).stem + ".txt")
            save_text(target, clean_text(result.text))
            print(f"{source} -> {target}")
    else:
        combined = "\n\n".join(clean_text(result.text) for _, result in results)
        save_text(out, combined)
        print(f"{results[0][0]} -> {out}")


def _emit(payload: str, out: Path | None, results, args: argparse.Namespace, suffix: str) -> None:
    if out is None:
        print(payload)
        return
    target = out
    if out.is_dir() or args.out.endswith(("/", "\\")):
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(results[0][0]).stem if len(results) == 1 else "extracted-text"
        target = out / (stem + suffix)
    save_text(target, payload)
    print(f"-> {target}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
