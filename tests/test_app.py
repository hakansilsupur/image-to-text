"""Smoke tests that drive the real window.

Skipped wherever Tk cannot open a display; on Windows they just run.
"""

from __future__ import annotations

import time

import pytest

tk = pytest.importorskip("tkinter", reason="Tk is required for the GUI tests")

from PIL import Image  # noqa: E402

from image_to_text.engines import Line, OcrEngine, OcrError, result_from_lines  # noqa: E402


class StubEngine(OcrEngine):
    name = "stub"
    display_name = "Stub Engine"

    def __init__(self, text: str = "line one\nline two", fail: str = "") -> None:
        self.text = text
        self.fail = fail
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def languages(self) -> list[str]:
        return ["en-US", "de-DE"]

    def recognize(self, image, language=None):
        self.calls += 1
        if self.fail:
            raise OcrError(self.fail)
        return result_from_lines(
            [Line(text=line) for line in self.text.split("\n")],
            engine=self.name,
            language=language or "en-US",
            duration=0.02,
        )


@pytest.fixture
def app(monkeypatch, tmp_path):
    """A real ImageToTextApp wired to a stub engine, torn down afterwards."""
    from image_to_text import app as app_module

    engine = StubEngine()
    monkeypatch.setattr(app_module, "all_engines", lambda: [engine])
    monkeypatch.setattr(app_module, "available_engines", lambda: [engine])
    monkeypatch.setattr(app_module, "get_engine", lambda name: engine if name == "stub" else None)
    monkeypatch.setattr(app_module, "resolve_engine", lambda name: engine)

    try:
        window = app_module.ImageToTextApp()
    except tk.TclError as exc:  # pragma: no cover - no display available
        pytest.skip(f"no display: {exc}")
    window.engine = engine
    try:
        yield window
    finally:
        try:
            window.destroy()
        except tk.TclError:
            pass


def pump(window, timeout: float = 30.0) -> None:
    """Let Tk run until the OCR worker has reported back."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.update()
        window.update_idletasks()
        if not window._busy:
            break
        time.sleep(0.01)
    else:  # pragma: no cover - only on a hung worker
        raise AssertionError(f"OCR did not finish within {timeout}s")
    window.update()


def add_image(window, name: str = "sample.png", size=(300, 120)):
    from image_to_text.app import Document

    window._add_document(Document(image=Image.new("RGB", size, "white"), title=name))
    window.update()


def test_window_opens_with_the_stub_engine(app):
    assert app.engine_var.get() == "Stub Engine"
    assert app.language_var.get() == "en-US"
    assert app.current_document() is None


def test_run_current_without_an_image_is_harmless(app):
    app.run_current()
    assert "Open an image first" in app.status_var.get()


def test_read_text_fills_the_text_pane(app):
    add_image(app)

    app.run_current()
    pump(app)

    assert app.get_text() == "line one\nline two"
    assert app.engine.calls == 1
    assert "Read 4 words" in app.status_var.get()


def test_read_all_reads_every_image(app):
    add_image(app, "a.png")
    add_image(app, "b.png")

    app.run_all()
    pump(app)

    assert app.engine.calls == 2
    assert all(doc.text for doc in app.documents)


def test_engine_errors_are_shown_not_raised(app, monkeypatch):
    add_image(app)
    app.engine.fail = "the engine fell over"

    app.run_current()
    pump(app)

    assert "the engine fell over" in app.get_text()
    assert app.current_document().result is None
    assert "Could not read" in app.status_var.get()


def test_switching_images_keeps_each_text(app):
    add_image(app, "a.png")
    app.run_current()
    pump(app)
    app.engine.text = "different words"
    add_image(app, "b.png")
    app.run_current()
    pump(app)

    app._select_index(0)
    assert app.get_text() == "line one\nline two"
    app._select_index(1)
    assert app.get_text() == "different words"


def test_edits_to_the_text_are_kept_per_image(app):
    add_image(app, "a.png")
    app.run_current()
    pump(app)
    add_image(app, "b.png")

    app._select_index(0)
    app.text.insert("end", "\nmy own note")
    app.update()
    app._select_index(1)
    app._select_index(0)

    assert app.get_text().endswith("my own note")


def test_rotation_is_remembered_per_image(app):
    add_image(app, "a.png")
    add_image(app, "b.png")

    app._select_index(0)
    app.rotate(90)
    app._select_index(1)

    assert app.documents[0].options.rotation == 90
    assert app.documents[1].options.rotation == 0


def test_toolbar_options_reach_the_engine(app, monkeypatch):
    add_image(app)
    app.invert_var.set(True)
    app.threshold_on_var.set(True)
    app.threshold_var.set(200)
    app._on_options_changed()

    seen = {}
    original = app.engine.recognize

    def spy(image, language=None):
        seen["mode"] = image.mode
        return original(image, language)

    monkeypatch.setattr(app.engine, "recognize", spy)
    app.run_current()
    pump(app)

    assert seen["mode"] == "L"  # thresholding produced a 1-bit-ish greyscale
    assert app.current_document().options.threshold == 200


def test_close_current_and_close_all(app):
    add_image(app, "a.png")
    add_image(app, "b.png")

    app.close_current()
    assert len(app.documents) == 1
    assert app.current_index == 0

    app.close_all()
    assert app.documents == []
    assert app.current_index is None
    assert app.get_text() == ""


def test_copy_text_puts_crlf_on_the_clipboard(app):
    add_image(app)
    app.run_current()
    pump(app)

    app.copy_text()

    assert app.clipboard_get() == "line one\r\nline two"
    assert "Copied" in app.status_var.get()


def test_save_text_writes_the_pane_contents(app, tmp_path, monkeypatch):
    from image_to_text import app as app_module

    add_image(app)
    app.run_current()
    pump(app)

    target = tmp_path / "out.txt"
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **_: str(target))
    app.save_text()

    assert target.read_text(encoding="utf-8-sig").splitlines() == ["line one", "line two"]


def test_save_all_texts(app, tmp_path, monkeypatch):
    from image_to_text import app as app_module

    add_image(app, "a.png")
    add_image(app, "b.png")
    app.run_all()
    pump(app)

    monkeypatch.setattr(app_module.filedialog, "askdirectory", lambda **_: str(tmp_path))
    app.save_all_texts()

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").exists()


def test_paste_with_an_empty_clipboard_says_so(app, monkeypatch):
    from image_to_text import app as app_module

    monkeypatch.setattr(app_module, "grab_clipboard_image", lambda: None)
    app.paste_image()

    assert "no image on the clipboard" in app.status_var.get()


def test_open_paths_reports_broken_files(app, tmp_path, monkeypatch):
    from image_to_text import app as app_module

    warned = {}
    monkeypatch.setattr(
        app_module.messagebox,
        "showwarning",
        lambda *args, **kwargs: warned.setdefault("msg", args[1]),
    )
    broken = tmp_path / "broken.png"
    broken.write_text("not an image")

    app.open_paths([broken])

    assert app.documents == []
    assert "Could not read" in warned["msg"]


def test_show_boxes_does_not_break_the_preview(app):
    add_image(app)
    app.run_current()
    pump(app)

    app.show_boxes_var.set(True)
    app._render_preview()  # stub results carry no boxes; must not raise
    app.update()


def test_settings_are_saved_on_close(app, monkeypatch):
    add_image(app)
    app.wrap_var.set(False)
    app.auto_copy_var.set(True)

    app.on_close()

    from image_to_text.settings import Settings

    saved = Settings.load()
    assert saved.engine == "stub"
    assert saved.wrap_text is False
    assert saved.auto_copy is True


def test_closing_an_image_while_it_is_being_read(app):
    """The result for a closed image is dropped, not written to its neighbour."""
    import threading

    add_image(app, "a.png")
    add_image(app, "b.png")

    release = threading.Event()
    original = app.engine.recognize

    def slow(image, language=None):
        release.wait(5)
        return original(image, language)

    app.engine.recognize = slow
    app.run_all()

    app._select_index(0)
    app.close_current()  # drop "a.png" while the worker is still going
    release.set()
    pump(app)

    assert [doc.title for doc in app.documents] == ["b.png"]
    assert app.documents[0].text == "line one\nline two"
