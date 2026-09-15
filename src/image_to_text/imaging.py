"""Loading and clean-up of the pictures we hand to an OCR engine.

Recognizers do much better on a large, high-contrast, upright greyscale image
than on a small dim photo, so the app exposes a handful of cheap corrections
the user can toggle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

#: Extensions the file pickers offer and the CLI accepts.
SUPPORTED_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
)

#: Below this, text is usually too small for the recognizer to latch onto.
_UPSCALE_TARGET = 1000


class ImageLoadError(RuntimeError):
    """Raised when a file cannot be opened as an image."""


@dataclass
class PreprocessOptions:
    """Corrections applied before recognition, all individually optional."""

    grayscale: bool = True
    autocontrast: bool = True
    sharpen: bool = False
    invert: bool = False
    #: Binarize at this 0-255 cut-off; ``None`` leaves greys alone.
    threshold: int | None = None
    #: Extra scaling on top of the automatic upscale of small images.
    scale: float = 1.0
    #: Clockwise rotation in degrees; only right angles are offered in the UI.
    rotation: int = 0
    auto_upscale: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> PreprocessOptions:
        options = cls()
        if not data:
            return options
        for key, value in data.items():
            if not hasattr(options, key):
                continue
            setattr(options, key, value)
        options.normalize()
        return options

    def normalize(self) -> None:
        """Clamp values that a hand-edited settings file could put out of range."""
        self.scale = max(0.25, min(float(self.scale or 1.0), 8.0))
        self.rotation = int(self.rotation or 0) % 360
        if self.threshold is not None:
            self.threshold = max(0, min(int(self.threshold), 255))


def load_image(path: str | Path) -> Image.Image:
    """Open ``path`` as an RGB image, applying any EXIF orientation."""
    path = Path(path)
    try:
        with Image.open(path) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except FileNotFoundError as exc:
        raise ImageLoadError(f"No such file: {path}") from exc
    except OSError as exc:
        raise ImageLoadError(f"Could not read '{path.name}' as an image: {exc}") from exc
    return _to_rgb(image)


def _to_rgb(image: Image.Image) -> Image.Image:
    """Flatten transparency onto white and drop exotic colour modes."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def fit_within(image: Image.Image, max_dimension: int) -> Image.Image:
    """Shrink ``image`` so neither side exceeds ``max_dimension``."""
    if max_dimension <= 0:
        return image
    longest = max(image.width, image.height)
    if longest <= max_dimension:
        return image
    ratio = max_dimension / longest
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(size, Image.LANCZOS)


def auto_scale_factor(image: Image.Image, target: int = _UPSCALE_TARGET) -> float:
    """How much to enlarge a small image so its text is legible to the engine."""
    longest = max(image.width, image.height)
    if longest <= 0 or longest >= target:
        return 1.0
    return min(4.0, target / longest)


def preprocess(image: Image.Image, options: PreprocessOptions | None = None) -> Image.Image:
    """Apply ``options`` to ``image`` and return a new image ready for OCR."""
    options = options or PreprocessOptions()
    options.normalize()
    result = image

    if options.rotation:
        # PIL rotates counter-clockwise; the UI speaks in clockwise turns.
        result = result.rotate(-options.rotation, expand=True, fillcolor=(255, 255, 255))

    scale = options.scale
    if options.auto_upscale:
        scale *= auto_scale_factor(result)
    if abs(scale - 1.0) > 1e-3:
        size = (max(1, round(result.width * scale)), max(1, round(result.height * scale)))
        result = result.resize(size, Image.LANCZOS)

    if options.grayscale or options.threshold is not None:
        result = result.convert("L")

    if options.autocontrast:
        result = ImageOps.autocontrast(result, cutoff=1)

    if options.sharpen:
        result = ImageEnhance.Sharpness(result).enhance(2.0)
        result = result.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))

    if options.invert:
        result = ImageOps.invert(result.convert("L") if result.mode != "L" else result)

    if options.threshold is not None:
        cutoff = options.threshold
        result = result.point(lambda pixel: 255 if pixel > cutoff else 0, mode="L")

    return result


def grab_clipboard_image() -> Image.Image | None:
    """Return the picture on the clipboard, or ``None`` if there is not one.

    A copied file in Explorer arrives as a list of paths, which we happily
    treat as "open that image".
    """
    try:
        from PIL import ImageGrab
    except ImportError:  # pragma: no cover - Pillow always ships ImageGrab
        return None
    try:
        grabbed = ImageGrab.grabclipboard()
    except (OSError, NotImplementedError):
        return None

    if isinstance(grabbed, list):
        for entry in grabbed:
            candidate = Path(str(entry))
            if candidate.suffix.lower() in SUPPORTED_EXTENSIONS and candidate.is_file():
                return load_image(candidate)
        return None
    if isinstance(grabbed, Image.Image):
        return _to_rgb(grabbed)
    return None


def is_supported_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS
