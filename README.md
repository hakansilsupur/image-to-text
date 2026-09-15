# Image to Text

A Windows desktop app that reads the words out of a picture — screenshots,
scans, photos of documents, receipts — and hands you back editable text.

It uses the OCR engine that already ships with Windows 10 and 11, so there is
nothing extra to download and nothing is ever uploaded: images are read
entirely on your own machine.

---

## Quick start

**If you have the built `ImageToText.exe`:** double-click it. That's all — it is
self-contained and needs no installation.

**From source:** double-click `run.bat`. The first run creates a local virtual
environment and installs what it needs (about 15 seconds), then opens the app.
You need [Python 3.9 or newer](https://www.python.org/downloads/) with
"Add python.exe to PATH" ticked during setup.

## Using it

| To do this | Use this |
| --- | --- |
| Open image files | **Open** button, or `Ctrl+O`, or drop files on the window |
| Read an image already copied | **Paste** button, or `Ctrl+V` |
| Grab text off the screen | **Capture** button, or `Ctrl+Shift+S`, then drag a box |
| Extract the text | **Read Text** button, or `F5` |
| Do the whole list at once | **Read All**, or `Shift+F5` |
| Copy the result | **Copy** button, or `Ctrl+Shift+C` |
| Save the result | **Save...**, or `Ctrl+S` |

The extracted text lands in the right-hand pane, where you can edit it before
copying or saving. Each open image keeps its own text, so you can switch
between them without losing anything.

### When the text comes out wrong

Faint, small, or light-on-dark text often needs a nudge. The **Image
preparation** box under the preview has the usual fixes:

- **Grayscale** and **Auto contrast** — on by default, and right most of the time.
- **Sharpen** — helps with blurry photos of a screen or a page.
- **Invert** — for white text on a dark background.
- **Black & white at** — force every pixel to pure black or white at a cut-off
  you pick. Good for faded receipts and low-contrast scans.
- **Rotate** — for sideways photos.

Small images are automatically enlarged before recognition, since recognizers
struggle with tiny lettering.

`View > Show Detected Text Boxes` draws what the engine actually found over the
preview, which makes it obvious whether a problem is bad recognition or a
missed region.

## OCR engines

| Engine | Needs installing? | Notes |
| --- | --- | --- |
| **Windows OCR** | No | Built into Windows 10/11. Fast and accurate. Reads the languages your Windows has OCR packs for. |
| **Tesseract** | Yes, separately | Optional. Worth adding for a language Windows has no pack for. |

Pick one in the toolbar. `Help > Engine Status` lists what is available and, for
anything that is not, exactly what to do about it.

**Adding a Windows OCR language:** Settings → Time & language → Language &
region → pick the language → Language options → Optical character recognition.

**Adding Tesseract:** install it from
[UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki), then
`pip install pytesseract`. The app checks the usual install locations; if yours
is somewhere unusual, point the `TESSERACT_CMD` environment variable at
`tesseract.exe`.

## Building the .exe

Double-click `build.bat`. It installs the build tools, runs the tests, and
produces a single self-contained `dist\ImageToText.exe` that you can copy to
any Windows machine.

## Command line

The same engine is available for scripting and batch jobs:

```
image-to-text scan.png                      print the text
image-to-text receipts\ --out texts\        one .txt per image in a folder
image-to-text page.jpg --format json        text plus per-word positions
image-to-text photo.png --invert --threshold 140
image-to-text --list-engines                what is installed
```

Run `image-to-text --help` for the full list. From a source checkout without
installing, use `python -m image_to_text` instead.

## How it is put together

```
src/image_to_text/
  app.py           the window: file list, preview, text pane, background OCR
  capture.py       drag-a-rectangle screen capture
  cli.py           command line front end
  engines/         one module per OCR backend, behind a common interface
    base.py          OcrEngine, OcrResult, Line, Word, Box
    windows_ocr.py   Windows.Media.Ocr via Python/WinRT
    tesseract.py     Tesseract via pytesseract
  export.py        saving text, JSON and CSV
  imaging.py       loading images and the preparation steps
  ocr.py           load -> prepare -> recognize, shared by the GUI and the CLI
  settings.py      preferences, remembered between runs
```

Adding another engine means subclassing `OcrEngine` and listing it in
`engines/__init__.py`; the window and the CLI pick it up from there.

Settings live in `%APPDATA%\ImageToText\settings.json`.

## Development

```
pip install -r requirements-dev.txt
pytest
```

The suite covers image preparation, the engine registry, settings, export and
the CLI, and drives the real window through Tk for the GUI behaviour (opening
images, reading them, per-image text and rotation, saving, and error handling).
The GUI tests skip themselves automatically where no display is available.

## Requirements

- Windows 10 or 11 (the Windows OCR engine is Windows-only; the rest of the app
  runs anywhere Python and Tk do)
- Python 3.9+ when running from source — not needed for the built `.exe`

## Licence

MIT. See [LICENSE](LICENSE).
