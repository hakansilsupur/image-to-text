from __future__ import annotations

from pathlib import Path

from image_to_text.engines import Box, Line, Word, result_from_lines
from image_to_text.export import (
    clean_text,
    default_output_path,
    normalize_newlines,
    results_to_csv,
    results_to_json,
    save_text,
)
from image_to_text.imaging import PreprocessOptions
from image_to_text.settings import Settings, config_dir, settings_path


# ------------------------------------------------------------------ settings
def test_settings_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(
        engine="windows",
        languages={"windows": "en-GB", "tesseract": "deu"},
        preprocess=PreprocessOptions(sharpen=True, threshold=90),
        last_open_dir=r"C:\Scans",
        wrap_text=False,
        auto_copy=True,
    )

    assert settings.save(path) is True
    restored = Settings.load(path)

    assert restored.engine == "windows"
    assert restored.language_for("tesseract") == "deu"
    assert restored.preprocess.threshold == 90
    assert restored.preprocess.sharpen is True
    assert restored.wrap_text is False
    assert restored.auto_copy is True


def test_settings_load_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ this is not json")

    settings = Settings.load(path)

    assert settings.engine == ""
    assert settings.preprocess == PreprocessOptions()


def test_settings_load_survives_wrong_shape(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('["not", "an", "object"]')

    assert Settings.load(path).engine == ""


def test_settings_load_missing_file_returns_defaults(tmp_path):
    assert Settings.load(tmp_path / "never-written.json").wrap_text is True


def test_settings_language_helpers():
    settings = Settings()
    settings.set_language("windows", "fr-FR")
    settings.set_language("", "ignored")

    assert settings.language_for("windows") == "fr-FR"
    assert settings.language_for("tesseract") == ""
    assert "" not in settings.languages


def test_config_dir_honours_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_TO_TEXT_CONFIG_DIR", str(tmp_path / "cfg"))
    assert config_dir() == tmp_path / "cfg"
    assert settings_path() == tmp_path / "cfg" / "settings.json"


# -------------------------------------------------------------------- export
def test_normalize_newlines():
    assert normalize_newlines("a\r\nb\rc\nd") == "a\nb\nc\nd"
    assert normalize_newlines("a\nb", newline="\r\n") == "a\r\nb"


def test_clean_text_trims_edges_but_keeps_inner_blanks():
    assert clean_text("\n\n  hello  \n\nworld \n\n") == "  hello\n\nworld"


def test_clean_text_of_empty_input():
    assert clean_text("\n\n  \n") == ""


def test_default_output_path():
    assert default_output_path(Path("scans") / "receipt.jpg") == "receipt.txt"
    assert default_output_path(None) == "extracted-text.txt"
    assert default_output_path("") == "extracted-text.txt"
    assert default_output_path("photo.png", ".json") == "photo.json"


def test_save_text_writes_utf8_bom_and_crlf(tmp_path):
    target = tmp_path / "out" / "text.txt"

    saved = save_text(target, "Grüße\nWorld")

    assert saved == target
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    # Exactly one CR per line break - no CRCRLF from double translation.
    assert raw.count(b"\r") == 1
    assert raw.decode("utf-8-sig") == "Grüße\r\nWorld"


def test_results_to_json_includes_boxes():
    result = result_from_lines(
        [Line(text="hi", words=(Word("hi", Box(1.234, 2.0, 30.0, 10.0)),))],
        engine="fake",
        language="en-US",
    )

    payload = results_to_json([("a.png", result)])

    assert '"source": "a.png"' in payload
    assert '"x": 1.23' in payload
    assert '"language": "en-US"' in payload


def test_results_to_csv_has_one_row_per_line():
    result = result_from_lines(
        [Line(text="first"), Line(text="second")], engine="fake", language="en"
    )

    rows = results_to_csv([("a.png", result)]).strip().split("\n")

    assert rows[0] == "source,line_number,text"
    assert rows[1] == "a.png,1,first"
    assert rows[2] == "a.png,2,second"


def test_results_to_csv_quotes_commas():
    result = result_from_lines([Line(text="a, b")], engine="fake", language="en")
    assert '"a, b"' in results_to_csv([("x.png", result)])
