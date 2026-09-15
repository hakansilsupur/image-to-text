from __future__ import annotations

import pytest
from PIL import Image

from image_to_text.imaging import (
    ImageLoadError,
    PreprocessOptions,
    auto_scale_factor,
    fit_within,
    is_supported_file,
    load_image,
    preprocess,
)


def test_load_image_returns_rgb(text_image):
    image = load_image(text_image())
    assert image.mode == "RGB"
    assert image.size == (320, 120)


def test_load_image_flattens_transparency(tmp_path):
    source = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    path = tmp_path / "clear.png"
    source.save(path)

    loaded = load_image(path)

    assert loaded.mode == "RGB"
    # Fully transparent pixels land on the white backdrop, not on black.
    assert loaded.getpixel((5, 5)) == (255, 255, 255)


def test_load_image_rejects_non_images(tmp_path):
    path = tmp_path / "notes.png"
    path.write_text("this is not a picture")

    with pytest.raises(ImageLoadError):
        load_image(path)


def test_load_image_reports_missing_file(tmp_path):
    with pytest.raises(ImageLoadError):
        load_image(tmp_path / "nope.png")


def test_fit_within_shrinks_only_when_needed():
    big = Image.new("RGB", (4000, 2000))
    small = Image.new("RGB", (100, 50))

    assert fit_within(big, 1000).size == (1000, 500)
    assert fit_within(small, 1000) is small
    assert fit_within(big, 0) is big


def test_auto_scale_factor_enlarges_small_images():
    assert auto_scale_factor(Image.new("RGB", (250, 100)), target=1000) == 4.0
    assert auto_scale_factor(Image.new("RGB", (2000, 100)), target=1000) == 1.0
    # Never blow an image up more than 4x, however tiny it is.
    assert auto_scale_factor(Image.new("RGB", (10, 10)), target=1000) == 4.0


def test_preprocess_grayscale_and_threshold():
    image = Image.new("RGB", (40, 40), (120, 120, 120))
    options = PreprocessOptions(
        grayscale=True, autocontrast=False, threshold=100, auto_upscale=False
    )

    result = preprocess(image, options)

    assert result.mode == "L"
    assert result.getpixel((5, 5)) == 255  # 120 > 100 -> white


def test_preprocess_threshold_below_cutoff_goes_black():
    image = Image.new("RGB", (40, 40), (60, 60, 60))
    options = PreprocessOptions(autocontrast=False, threshold=100, auto_upscale=False)

    assert preprocess(image, options).getpixel((5, 5)) == 0


def test_preprocess_invert():
    image = Image.new("RGB", (20, 20), (0, 0, 0))
    options = PreprocessOptions(invert=True, autocontrast=False, auto_upscale=False)

    assert preprocess(image, options).getpixel((1, 1)) == 255


def test_preprocess_rotation_is_clockwise():
    image = Image.new("RGB", (40, 10), "white")
    # Mark the top-left corner so we can tell which way it turned.
    image.putpixel((0, 0), (0, 0, 0))

    rotated = preprocess(
        image,
        PreprocessOptions(
            rotation=90, grayscale=False, autocontrast=False, auto_upscale=False
        ),
    )

    assert rotated.size == (10, 40)
    # A clockwise quarter turn sends the top-left corner to the top-right.
    assert rotated.getpixel((9, 0)) == (0, 0, 0)


def test_preprocess_scale_and_auto_upscale():
    image = Image.new("RGB", (100, 50), "white")

    doubled = preprocess(image, PreprocessOptions(scale=2.0, auto_upscale=False))
    assert doubled.size == (200, 100)

    upscaled = preprocess(image, PreprocessOptions(auto_upscale=True))
    assert upscaled.size == (400, 200)  # capped at 4x


def test_preprocess_defaults_do_not_mutate_input():
    image = Image.new("RGB", (100, 50), "white")
    preprocess(image, PreprocessOptions())
    assert image.mode == "RGB"
    assert image.size == (100, 50)


def test_options_normalize_clamps_wild_values():
    options = PreprocessOptions(scale=99.0, rotation=450, threshold=900)
    options.normalize()

    assert options.scale == 8.0
    assert options.rotation == 90
    assert options.threshold == 255


def test_options_round_trip_through_dict():
    options = PreprocessOptions(sharpen=True, threshold=77, rotation=270)
    restored = PreprocessOptions.from_dict(options.to_dict())
    assert restored == options


def test_options_from_dict_ignores_unknown_keys():
    restored = PreprocessOptions.from_dict({"sharpen": True, "bogus": 1})
    assert restored.sharpen is True


def test_is_supported_file():
    assert is_supported_file("scan.PNG")
    assert is_supported_file("photo.jpeg")
    assert not is_supported_file("notes.docx")
