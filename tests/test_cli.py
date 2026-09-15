from __future__ import annotations

import json

import pytest

from image_to_text import cli, ocr
from image_to_text.engines import Line, OcrEngine, result_from_lines


class StubEngine(OcrEngine):
    name = "stub"
    display_name = "Stub"

    def __init__(self, text: str = "hello world") -> None:
        self.text = text
        self.seen: list[tuple] = []

    def is_available(self) -> bool:
        return True

    def languages(self) -> list[str]:
        return ["en-US"]

    def recognize(self, image, language=None):
        self.seen.append((image.size, image.mode, language))
        return result_from_lines(
            [Line(text=line) for line in self.text.split("\n")],
            engine=self.name,
            language=language or "en-US",
            duration=0.01,
        )


@pytest.fixture
def stub(monkeypatch):
    engine = StubEngine()
    monkeypatch.setattr(cli, "resolve_engine", lambda _name: engine)
    monkeypatch.setattr(ocr, "resolve_engine", lambda _name: engine)
    return engine


def test_recognize_file_applies_preprocessing(stub, text_image):
    from image_to_text.imaging import PreprocessOptions

    result = ocr.recognize_file(
        text_image(),
        engine=stub,
        language="en-US",
        options=PreprocessOptions(grayscale=True, auto_upscale=False),
    )

    assert result.text == "hello world"
    size, mode, language = stub.seen[0]
    assert mode == "L"  # the engine got the greyscale version
    assert language == "en-US"


def test_cli_prints_text(stub, text_image, capsys):
    exit_code = cli.main([str(text_image())])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "hello world"


def test_cli_writes_a_single_file(stub, text_image, tmp_path):
    out = tmp_path / "result.txt"

    assert cli.main([str(text_image()), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8-sig").strip() == "hello world"


def test_cli_writes_one_file_per_image_into_a_folder(stub, text_image, tmp_path):
    first = text_image(name="a.png")
    second = text_image(name="b.png")
    out = tmp_path / "texts"

    assert cli.main([str(first), str(second), "--out", str(out)]) == 0
    assert (out / "a.txt").exists()
    assert (out / "b.txt").exists()


def test_cli_scans_a_folder(stub, text_image, capsys):
    path = text_image(name="one.png")
    text_image(name="two.png")

    assert cli.main([str(path.parent)]) == 0
    out = capsys.readouterr().out
    assert "one.png" in out and "two.png" in out


def test_cli_json_output(stub, text_image, capsys):
    assert cli.main([str(text_image()), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["text"] == "hello world"
    assert payload[0]["engine"] == "stub"


def test_cli_csv_output(stub, text_image, capsys):
    assert cli.main([str(text_image()), "--format", "csv"]) == 0
    assert "source,line_number,text" in capsys.readouterr().out


def test_cli_reports_unreadable_files(stub, tmp_path, capsys):
    broken = tmp_path / "broken.png"
    broken.write_text("nope")

    assert cli.main([str(broken)]) == 1
    assert "Could not read" in capsys.readouterr().err


def test_cli_keeps_going_after_a_bad_file(stub, text_image, tmp_path, capsys):
    good = text_image(name="good.png")
    broken = tmp_path / "broken.png"
    broken.write_text("nope")

    # One failure among several still prints what worked, and exits non-zero.
    assert cli.main([str(good), str(broken)]) == 1
    assert "hello world" in capsys.readouterr().out


def test_cli_no_matching_images(stub, tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert cli.main([str(empty)]) == 1
    assert "No image files matched" in capsys.readouterr().err


def test_cli_list_engines(capsys):
    assert cli.main(["--list-engines"]) == 0
    out = capsys.readouterr().out
    assert "Windows OCR" in out and "Tesseract" in out


def test_cli_opens_the_window_without_arguments(monkeypatch):
    pytest.importorskip("tkinter", reason="the GUI needs Tk, which ships with Windows Python")
    import image_to_text.app as app_module

    opened: dict = {}

    def fake_run(files=None):
        opened["files"] = files
        return 0

    monkeypatch.setattr(app_module, "run", fake_run)

    assert cli.main([]) == 0
    assert opened["files"] == []


def test_collect_images_deduplicates(text_image):
    path = text_image(name="dup.png")
    assert cli.collect_images([str(path), str(path)]) == [path]


def test_collect_images_skips_non_images_in_folders(text_image, tmp_path):
    image = text_image(name="keep.png")
    (image.parent / "notes.txt").write_text("skip me")

    found = cli.collect_images([str(image.parent)])

    assert [p.name for p in found] == ["keep.png"]


def test_options_from_args_maps_the_flags():
    args = cli.build_parser().parse_args(
        ["x.png", "--no-grayscale", "--sharpen", "--threshold", "140", "--rotate", "450"]
    )
    options = cli.options_from_args(args)

    assert options.grayscale is False
    assert options.sharpen is True
    assert options.threshold == 140
    assert options.rotation == 90  # normalized into 0-359
