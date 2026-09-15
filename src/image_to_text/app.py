"""The desktop window: pick a picture on the left, read its text on the right."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import __version__
from .capture import capture_region
from .engines import (
    EngineUnavailableError,
    OcrEngine,
    OcrError,
    OcrResult,
    all_engines,
    available_engines,
    get_engine,
    resolve_engine,
)
from .export import WINDOWS_NEWLINE, clean_text, default_output_path, save_text
from .imaging import (
    SUPPORTED_EXTENSIONS,
    ImageLoadError,
    PreprocessOptions,
    grab_clipboard_image,
    load_image,
)
from .ocr import recognize_image
from .resources import icon_path, icon_png_path
from .settings import Settings

APP_TITLE = "Image to Text"
FILE_TYPES = [
    ("Images", " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)),
    ("All files", "*.*"),
]
#: Padding used throughout, so the window keeps one rhythm.
PAD = 8


# eq=False keeps documents compared by identity, so looking one up in the
# list stays exact (and cheap) even when two pictures are pixel-identical.
@dataclass(eq=False)
class Document:
    """One loaded picture plus whatever we have read out of it."""

    image: Image.Image
    title: str
    path: Path | None = None
    result: OcrResult | None = None
    text: str = ""
    error: str = ""
    options: PreprocessOptions = field(default_factory=PreprocessOptions)

    @property
    def label(self) -> str:
        mark = "* " if self.result is None and not self.error else ""
        return f"{mark}{self.title}"


class ImageToTextApp(tk.Tk):
    def __init__(self, initial_files: list[str] | None = None) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.documents: list[Document] = []
        self.current_index: int | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_geometry: tuple[int, int, float, int, int] | None = None
        self._results_queue: queue.Queue[tuple] = queue.Queue()
        self._busy = False
        self._resize_job: str | None = None
        self._suspend_text_sync = False
        self._closing = False

        self.title(APP_TITLE)
        self.minsize(900, 560)
        self._apply_icon()
        if self.settings.window_geometry:
            try:
                self.geometry(self.settings.window_geometry)
            except tk.TclError:
                self.geometry("1100x700")
        else:
            self.geometry("1100x700")

        self._init_vars()
        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_keys()
        self._enable_drag_and_drop()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._populate_engines()
        self._report_engine_state()

        if initial_files:
            self.after(100, lambda: self.open_paths([Path(p) for p in initial_files]))

    # ------------------------------------------------------------------ setup
    def _apply_icon(self) -> None:
        """Put the app icon on the window, quietly giving up if it is missing."""
        ico = icon_path()
        if ico is not None:
            try:
                self.iconbitmap(default=str(ico))
                return
            except tk.TclError:
                pass  # .ico is Windows-only; fall through to the PNG
        png = icon_png_path()
        if png is None:
            return
        try:
            self._icon_image = ImageTk.PhotoImage(Image.open(png))
            self.iconphoto(True, self._icon_image)
        except Exception:
            # The icon is decoration; never let it stop the app from opening.
            pass

    def _init_vars(self) -> None:
        options = self.settings.preprocess
        self.engine_var = tk.StringVar()
        self.language_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready.")
        self.detail_var = tk.StringVar(value="")
        self.grayscale_var = tk.BooleanVar(value=options.grayscale)
        self.autocontrast_var = tk.BooleanVar(value=options.autocontrast)
        self.sharpen_var = tk.BooleanVar(value=options.sharpen)
        self.invert_var = tk.BooleanVar(value=options.invert)
        self.threshold_on_var = tk.BooleanVar(value=options.threshold is not None)
        self.threshold_var = tk.IntVar(value=options.threshold if options.threshold else 128)
        self.wrap_var = tk.BooleanVar(value=self.settings.wrap_text)
        self.auto_copy_var = tk.BooleanVar(value=self.settings.auto_copy)
        self.show_boxes_var = tk.BooleanVar(value=False)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        # "vista" is the native-looking theme on Windows; fall back elsewhere.
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("Toolbar.TFrame", padding=(PAD, 6))
        style.configure("Status.TLabel", padding=(PAD, 4))
        style.configure("Run.TButton", font=("Segoe UI", 9, "bold"))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Images...", accelerator="Ctrl+O", command=self.open_files)
        file_menu.add_command(
            label="Paste Image from Clipboard", accelerator="Ctrl+V", command=self.paste_image
        )
        file_menu.add_command(
            label="Capture Screen Region...",
            accelerator="Ctrl+Shift+S",
            command=self.capture_screen,
        )
        file_menu.add_separator()
        file_menu.add_command(label="Save Text As...", accelerator="Ctrl+S", command=self.save_text)
        file_menu.add_command(label="Save All Texts...", command=self.save_all_texts)
        file_menu.add_separator()
        file_menu.add_command(label="Close Image", command=self.close_current)
        file_menu.add_command(label="Close All", command=self.close_all)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Copy Text", accelerator="Ctrl+Shift+C", command=self.copy_text)
        edit_menu.add_command(label="Select All", accelerator="Ctrl+A", command=self.select_all)
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear Text", command=self.clear_text)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        ocr_menu = tk.Menu(menubar, tearoff=0)
        ocr_menu.add_command(label="Read This Image", accelerator="F5", command=self.run_current)
        ocr_menu.add_command(
            label="Read All Images", accelerator="Shift+F5", command=self.run_all
        )
        ocr_menu.add_separator()
        ocr_menu.add_command(label="Rotate Left", command=lambda: self.rotate(-90))
        ocr_menu.add_command(label="Rotate Right", command=lambda: self.rotate(90))
        menubar.add_cascade(label="OCR", menu=ocr_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Wrap Text", variable=self.wrap_var, command=self._apply_wrap
        )
        view_menu.add_checkbutton(
            label="Show Detected Text Boxes",
            variable=self.show_boxes_var,
            command=self._render_preview,
        )
        view_menu.add_checkbutton(label="Copy Text Automatically", variable=self.auto_copy_var)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Engine Status...", command=self.show_engine_status)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Toolbar.TFrame")
        bar.pack(side="top", fill="x")

        ttk.Button(bar, text="Open", width=9, command=self.open_files).pack(side="left")
        ttk.Button(bar, text="Paste", width=9, command=self.paste_image).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(bar, text="Capture", width=9, command=self.capture_screen).pack(
            side="left", padx=(4, 0)
        )

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=PAD)

        ttk.Label(bar, text="Engine:").pack(side="left")
        self.engine_combo = ttk.Combobox(
            bar, textvariable=self.engine_var, state="readonly", width=16
        )
        self.engine_combo.pack(side="left", padx=(4, PAD))
        self.engine_combo.bind("<<ComboboxSelected>>", self._on_engine_changed)

        ttk.Label(bar, text="Language:").pack(side="left")
        self.language_combo = ttk.Combobox(
            bar, textvariable=self.language_var, state="readonly", width=10
        )
        self.language_combo.pack(side="left", padx=(4, PAD))
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=(0, PAD))

        self.run_button = ttk.Button(
            bar, text="Read Text", style="Run.TButton", command=self.run_current
        )
        self.run_button.pack(side="left")
        ttk.Button(bar, text="Read All", command=self.run_all).pack(side="left", padx=(4, 0))

        ttk.Button(bar, text="Save...", command=self.save_text).pack(side="right")
        ttk.Button(bar, text="Copy", command=self.copy_text).pack(side="right", padx=(0, 4))

    def _build_body(self) -> None:
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(side="top", fill="both", expand=True, padx=PAD, pady=(0, PAD))

        left = ttk.Frame(panes)
        panes.add(left, weight=3)
        right = ttk.Frame(panes)
        panes.add(right, weight=2)

        self._build_left_pane(left)
        self._build_right_pane(right)

    def _build_left_pane(self, parent: ttk.Frame) -> None:
        files = ttk.LabelFrame(parent, text="Images")
        files.pack(side="top", fill="x")
        self.file_list = tk.Listbox(files, height=4, activestyle="dotbox", exportselection=False)
        self.file_list.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scroll = ttk.Scrollbar(files, orient="vertical", command=self.file_list.yview)
        scroll.pack(side="right", fill="y", pady=4)
        self.file_list.configure(yscrollcommand=scroll.set)
        self.file_list.bind("<<ListboxSelect>>", self._on_file_selected)
        self.file_list.bind("<Delete>", lambda _event: self.close_current())

        preview = ttk.LabelFrame(parent, text="Preview")
        preview.pack(side="top", fill="both", expand=True, pady=(PAD, 0))
        self.canvas = tk.Canvas(preview, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        self._build_options(parent)

    def _build_options(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Image preparation")
        box.pack(side="top", fill="x", pady=(PAD, 0))

        row = ttk.Frame(box)
        row.pack(fill="x", padx=4, pady=(4, 0))
        for text, var in (
            ("Grayscale", self.grayscale_var),
            ("Auto contrast", self.autocontrast_var),
            ("Sharpen", self.sharpen_var),
            ("Invert", self.invert_var),
        ):
            ttk.Checkbutton(row, text=text, variable=var, command=self._on_options_changed).pack(
                side="left", padx=(0, PAD)
            )

        row2 = ttk.Frame(box)
        row2.pack(fill="x", padx=4, pady=(2, 4))
        ttk.Checkbutton(
            row2,
            text="Black & white at",
            variable=self.threshold_on_var,
            command=self._on_options_changed,
        ).pack(side="left")
        # The label has to exist before the scale, because setting the scale's
        # value fires its command, which writes to the label.
        self.threshold_label = ttk.Label(row2, width=4, text=str(self.threshold_var.get()))
        self.threshold_scale = ttk.Scale(
            row2,
            from_=0,
            to=255,
            orient="horizontal",
            command=self._on_threshold_dragged,
        )
        self.threshold_scale.set(self.threshold_var.get())
        self.threshold_scale.pack(side="left", fill="x", expand=True, padx=4)
        self.threshold_label.pack(side="left")

        ttk.Button(row2, text="Rotate", width=7, command=lambda: self.rotate(90)).pack(
            side="left", padx=(PAD, 0)
        )

    def _build_right_pane(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Extracted text")
        box.pack(fill="both", expand=True)

        self.text = tk.Text(
            box,
            wrap="word" if self.settings.wrap_text else "none",
            undo=True,
            font=("Consolas", 10),
            padx=6,
            pady=6,
        )
        vbar = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        self.hbar = ttk.Scrollbar(box, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vbar.set, xscrollcommand=self.hbar.set)

        vbar.pack(side="right", fill="y")
        self.hbar.pack(side="bottom", fill="x")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<<Modified>>", self._on_text_modified)
        self._apply_wrap()

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(side="bottom", fill="x")
        ttk.Separator(bar, orient="horizontal").pack(side="top", fill="x")
        inner = ttk.Frame(bar)
        inner.pack(fill="x")
        ttk.Label(inner, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        ttk.Label(inner, textvariable=self.detail_var, style="Status.TLabel").pack(side="right")
        self.progress = ttk.Progressbar(inner, mode="indeterminate", length=120)

    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda _e: self.open_files())
        self.bind("<Control-v>", lambda _e: self.paste_image())
        self.bind("<Control-s>", lambda _e: self.save_text())
        self.bind("<Control-Shift-S>", lambda _e: self.capture_screen())
        self.bind("<Control-Shift-C>", lambda _e: self.copy_text())
        self.bind("<F5>", lambda _e: self.run_current())
        self.bind("<Shift-F5>", lambda _e: self.run_all())

    def _enable_drag_and_drop(self) -> None:
        """Accept files dropped on the window, when tkinterdnd2 is installed."""
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
        except ImportError:
            return
        try:
            self.TkdndVersion = TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:  # pragma: no cover - optional convenience only
            pass

    def _on_drop(self, event) -> None:  # pragma: no cover - needs a real drag
        paths = [Path(p) for p in self.tk.splitlist(event.data)]
        self.open_paths(paths)

    # ------------------------------------------------------- engine handling
    def _populate_engines(self) -> None:
        engines = available_engines()
        names = [engine.display_name for engine in engines]
        self.engine_combo.configure(values=names)
        if not engines:
            self.engine_combo.configure(state="disabled")
            self.language_combo.configure(state="disabled")
            return

        chosen = get_engine(self.settings.engine)
        if chosen is None or not chosen.is_available():
            chosen = engines[0]
        self.engine_var.set(chosen.display_name)
        self._populate_languages(chosen)

    def _populate_languages(self, engine: OcrEngine) -> None:
        languages = engine.languages()
        self.language_combo.configure(
            values=languages, state="readonly" if languages else "disabled"
        )
        remembered = self.settings.language_for(engine.name)
        if remembered in languages:
            self.language_var.set(remembered)
        else:
            self.language_var.set(engine.default_language())

    def current_engine(self) -> OcrEngine | None:
        wanted = self.engine_var.get()
        for engine in all_engines():
            if engine.display_name == wanted:
                return engine
        try:
            return resolve_engine(None)
        except EngineUnavailableError:
            return None

    def _on_engine_changed(self, _event=None) -> None:
        engine = self.current_engine()
        if engine is None:
            return
        self.settings.engine = engine.name
        self._populate_languages(engine)
        self.status_var.set(f"Engine set to {engine.display_name}.")

    def _on_language_changed(self, _event=None) -> None:
        engine = self.current_engine()
        if engine is not None:
            self.settings.set_language(engine.name, self.language_var.get())

    def _report_engine_state(self) -> None:
        if available_engines():
            return
        lines = [
            "No OCR engine is available yet.",
            "",
        ]
        for engine in all_engines():
            lines.append(f"{engine.display_name}: {engine.unavailable_reason()}")
        self._set_text("\n".join(lines))
        self.status_var.set("No OCR engine available - see Help > Engine Status.")

    def show_engine_status(self) -> None:
        lines = []
        for engine in all_engines():
            if engine.is_available():
                langs = ", ".join(engine.languages()) or "(none reported)"
                lines.append(f"{engine.display_name}: ready\n    Languages: {langs}")
            else:
                lines.append(
                    f"{engine.display_name}: not available\n    {engine.unavailable_reason()}"
                )
        messagebox.showinfo("Engine status", "\n\n".join(lines), parent=self)

    def show_about(self) -> None:
        messagebox.showinfo(
            "About " + APP_TITLE,
            f"{APP_TITLE} {__version__}\n\n"
            "Reads the text out of pictures, screenshots and scans.\n"
            "Open an image, paste one, or capture part of the screen, "
            "then press Read Text.",
            parent=self,
        )

    # -------------------------------------------------------- document state
    def open_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Open images",
            filetypes=FILE_TYPES,
            initialdir=self.settings.last_open_dir or None,
        )
        if paths:
            self.open_paths([Path(p) for p in paths])

    def open_paths(self, paths: list[Path]) -> None:
        opened = 0
        errors = []
        for path in paths:
            if path.is_dir():
                continue
            try:
                image = load_image(path)
            except ImageLoadError as exc:
                errors.append(str(exc))
                continue
            self.settings.last_open_dir = str(path.parent)
            self._add_document(Document(image=image, title=path.name, path=path), select=False)
            opened += 1

        if opened:
            self._select_index(len(self.documents) - 1)
            self.status_var.set(
                f"Opened {opened} image{'s' if opened != 1 else ''}. Press Read Text (F5)."
            )
        if errors:
            messagebox.showwarning("Could not open", "\n".join(errors), parent=self)

    def paste_image(self) -> None:
        try:
            image = grab_clipboard_image()
        except ImageLoadError as exc:
            messagebox.showwarning("Paste", str(exc), parent=self)
            return
        if image is None:
            self.status_var.set("There is no image on the clipboard.")
            return
        count = sum(1 for doc in self.documents if doc.path is None)
        self._add_document(Document(image=image, title=f"Clipboard {count + 1}"))
        self.status_var.set("Pasted image from clipboard.")
        self.run_current()

    def capture_screen(self) -> None:
        if self._busy:
            return
        self.withdraw()

        def done(image: Image.Image | None) -> None:
            self.deiconify()
            self.lift()
            if image is None:
                self.status_var.set("Capture cancelled.")
                return
            count = sum(1 for doc in self.documents if doc.path is None)
            self._add_document(Document(image=image, title=f"Capture {count + 1}"))
            self.status_var.set("Captured screen region.")
            self.run_current()

        # Give the window a moment to actually vanish before the overlay opens.
        self.after(180, lambda: capture_region(self, done))

    def _add_document(self, document: Document, select: bool = True) -> None:
        document.options = self._options_from_ui()
        self.documents.append(document)
        self.file_list.insert("end", document.label)
        if select:
            self._select_index(len(self.documents) - 1)

    def _select_index(self, index: int) -> None:
        if not (0 <= index < len(self.documents)):
            return
        self.current_index = index
        self.file_list.selection_clear(0, "end")
        self.file_list.selection_set(index)
        self.file_list.see(index)
        self._load_current_into_ui()

    def _on_file_selected(self, _event=None) -> None:
        selection = self.file_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if index != self.current_index:
            self.current_index = index
            self._load_current_into_ui()

    def current_document(self) -> Document | None:
        if self.current_index is None:
            return None
        if not (0 <= self.current_index < len(self.documents)):
            return None
        return self.documents[self.current_index]

    def _load_current_into_ui(self) -> None:
        document = self.current_document()
        if document is None:
            self._set_text("")
            self._render_preview()
            self.detail_var.set("")
            return
        self._apply_options_to_ui(document.options)
        self._set_text(document.error or document.text)
        self._render_preview()
        self._update_detail(document)
        self.title(f"{document.title} - {APP_TITLE}")

    def close_current(self) -> None:
        if self.current_index is None or not self.documents:
            return
        index = self.current_index
        self.documents.pop(index)
        self.file_list.delete(index)
        if not self.documents:
            self.current_index = None
            self.title(APP_TITLE)
            self._load_current_into_ui()
        else:
            self._select_index(min(index, len(self.documents) - 1))

    def close_all(self) -> None:
        self.documents.clear()
        self.file_list.delete(0, "end")
        self.current_index = None
        self.title(APP_TITLE)
        self._load_current_into_ui()
        self.status_var.set("Ready.")

    def _refresh_list_label(self, index: int) -> None:
        if 0 <= index < len(self.documents):
            selected = index in self.file_list.curselection()
            self.file_list.delete(index)
            self.file_list.insert(index, self.documents[index].label)
            if selected:
                self.file_list.selection_set(index)

    # --------------------------------------------------------------- options
    def _options_from_ui(self) -> PreprocessOptions:
        options = PreprocessOptions(
            grayscale=self.grayscale_var.get(),
            autocontrast=self.autocontrast_var.get(),
            sharpen=self.sharpen_var.get(),
            invert=self.invert_var.get(),
            threshold=self.threshold_var.get() if self.threshold_on_var.get() else None,
            scale=1.0,
            rotation=0,
            auto_upscale=True,
        )
        document = self.current_document()
        if document is not None:
            options.rotation = document.options.rotation
            options.scale = document.options.scale
        options.normalize()
        return options

    def _apply_options_to_ui(self, options: PreprocessOptions) -> None:
        self.grayscale_var.set(options.grayscale)
        self.autocontrast_var.set(options.autocontrast)
        self.sharpen_var.set(options.sharpen)
        self.invert_var.set(options.invert)
        self.threshold_on_var.set(options.threshold is not None)
        if options.threshold is not None:
            self.threshold_var.set(options.threshold)
            self.threshold_scale.set(options.threshold)
            self.threshold_label.configure(text=str(options.threshold))

    def _on_options_changed(self) -> None:
        document = self.current_document()
        if document is not None:
            document.options = self._options_from_ui()
        self.settings.preprocess = self._options_from_ui()

    def _on_threshold_dragged(self, value: str) -> None:
        threshold = int(float(value))
        self.threshold_var.set(threshold)
        self.threshold_label.configure(text=str(threshold))
        if self.threshold_on_var.get():
            self._on_options_changed()

    def rotate(self, degrees: int) -> None:
        document = self.current_document()
        if document is None:
            return
        document.options.rotation = (document.options.rotation + degrees) % 360
        self._render_preview()
        self.status_var.set(f"Rotated to {document.options.rotation} degrees.")

    # ------------------------------------------------------------- preview
    def _on_canvas_resize(self, _event=None) -> None:
        # Redrawing on every pixel of a drag is wasteful; settle first.
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, self._render_preview)

    def _render_preview(self) -> None:
        self._resize_job = None
        if self._closing or not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")
        document = self.current_document()
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if document is None or width < 10 or height < 10:
            if document is None and width > 40:
                self.canvas.create_text(
                    width // 2,
                    height // 2,
                    text="Open, paste or capture an image to begin",
                    fill="#9a9a9a",
                    font=("Segoe UI", 11),
                )
            return

        image = document.image
        if document.options.rotation:
            image = image.rotate(-document.options.rotation, expand=True, fillcolor=(255, 255, 255))

        ratio = min(width / image.width, height / image.height, 1.0)
        size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
        self._preview_photo = ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))
        offset_x = (width - size[0]) // 2
        offset_y = (height - size[1]) // 2
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self._preview_photo)
        self._preview_geometry = (offset_x, offset_y, ratio, image.width, image.height)

        if self.show_boxes_var.get():
            self._draw_boxes(document, offset_x, offset_y, ratio)

    def _draw_boxes(self, document: Document, offset_x: int, offset_y: int, ratio: float) -> None:
        """Outline what the engine found, in the preview's coordinates."""
        if document.result is None:
            return
        for line in document.result.lines:
            box = line.box
            if box is None:
                continue
            self.canvas.create_rectangle(
                offset_x + box.x * ratio,
                offset_y + box.y * ratio,
                offset_x + box.right * ratio,
                offset_y + box.bottom * ratio,
                outline="#4da3ff",
                width=1,
            )

    # ----------------------------------------------------------------- text
    def _set_text(self, value: str) -> None:
        self._suspend_text_sync = True
        self.text.delete("1.0", "end")
        if value:
            self.text.insert("1.0", value)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self._suspend_text_sync = False

    def get_text(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _on_text_modified(self, _event=None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._suspend_text_sync:
            return
        document = self.current_document()
        if document is not None:
            document.text = self.get_text()

    def _apply_wrap(self) -> None:
        wrap = self.wrap_var.get()
        self.text.configure(wrap="word" if wrap else "none")
        if wrap:
            self.hbar.pack_forget()
        else:
            self.hbar.pack(side="bottom", fill="x")
        self.settings.wrap_text = wrap

    def select_all(self) -> None:
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.focus_set()

    def clear_text(self) -> None:
        self._set_text("")
        document = self.current_document()
        if document is not None:
            document.text = ""

    def copy_text(self) -> None:
        text = self.get_text()
        if not text.strip():
            self.status_var.set("There is no text to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(text.replace("\n", WINDOWS_NEWLINE))
        self.update()  # keep the clipboard alive after the app closes
        self.status_var.set(f"Copied {len(text)} characters to the clipboard.")

    # ------------------------------------------------------------------ OCR
    def run_current(self) -> None:
        document = self.current_document()
        if document is None:
            self.status_var.set("Open an image first.")
            return
        self._start_ocr([(self.current_index, document)])

    def run_all(self) -> None:
        if not self.documents:
            self.status_var.set("Open an image first.")
            return
        self._start_ocr(list(enumerate(self.documents)))

    def _start_ocr(self, jobs: list[tuple[int, Document]]) -> None:
        if self._busy:
            self.status_var.set("Still reading the previous image...")
            return
        engine = self.current_engine()
        if engine is None or not engine.is_available():
            messagebox.showerror(
                "No OCR engine",
                "No OCR engine is available.\n\nSee Help > Engine Status for how to enable one.",
                parent=self,
            )
            return

        language = self.language_var.get() or engine.default_language()
        self.settings.set_language(engine.name, language)
        options = self._options_from_ui()
        for _index, document in jobs:
            # The toolbar toggles apply to every job; rotation stays per image.
            document.options = replace(
                options,
                rotation=document.options.rotation,
                scale=document.options.scale,
            )

        self._set_busy(True, f"Reading with {engine.display_name}...")
        worker = threading.Thread(
            target=self._ocr_worker,
            args=(engine, language, list(jobs)),
            daemon=True,
        )
        worker.start()
        self.after(60, self._poll_results)

    def _ocr_worker(
        self, engine: OcrEngine, language: str, jobs: list[tuple[int, Document]]
    ) -> None:
        """Runs off the UI thread; results go back through the queue."""
        for index, document in jobs:
            try:
                result = recognize_image(
                    document.image,
                    engine=engine,
                    language=language,
                    options=document.options,
                )
                self._results_queue.put(("ok", index, document, result))
            except (OcrError, EngineUnavailableError) as exc:
                self._results_queue.put(("error", index, document, str(exc)))
            except Exception as exc:  # pragma: no cover - last-resort guard
                traceback.print_exc()
                self._results_queue.put(("error", index, document, f"Unexpected failure: {exc}"))
        self._results_queue.put(("done", None, None, None))

    def _poll_results(self) -> None:
        # The window can be closed while the worker is still going; the thread
        # is a daemon and its queued results are simply dropped.
        if self._closing:
            return
        finished = False
        while True:
            try:
                kind, index, document, payload = self._results_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                finished = True
                continue
            # The list may have shifted while the worker ran, so find the row
            # this document sits on now - it may have been closed entirely.
            index = next(
                (i for i, doc in enumerate(self.documents) if doc is document), None
            )
            if index is None:
                continue
            if kind == "ok":
                document.result = payload
                document.text = clean_text(payload.text)
                document.error = ""
            else:
                document.result = None
                document.text = ""
                document.error = payload
            self._refresh_list_label(index)
            if index == self.current_index:
                self._set_text(document.error or document.text)
                self._update_detail(document)
                self._render_preview()
                if kind == "ok" and self.auto_copy_var.get() and document.text.strip():
                    self.copy_text()

        if finished:
            self._set_busy(False)
            self._summarize()
        else:
            self.after(60, self._poll_results)

    def _summarize(self) -> None:
        document = self.current_document()
        if document is None:
            self.status_var.set("Ready.")
        elif document.error:
            self.status_var.set("Could not read this image.")
        elif document.result is not None:
            result = document.result
            self.status_var.set(
                f"Read {result.word_count} words in {result.duration:.2f}s "
                f"using {result.engine} ({result.language})."
            )
        else:
            self.status_var.set("Ready.")

    def _update_detail(self, document: Document) -> None:
        image = document.image
        parts = [f"{image.width} x {image.height} px"]
        if document.result is not None:
            parts.append(f"{document.result.char_count} chars")
            parts.append(f"{len(document.result.lines)} lines")
        self.detail_var.set("   |   ".join(parts))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        if busy:
            self.status_var.set(message)
            self.progress.pack(side="right", padx=PAD)
            self.progress.start(12)
            self.configure(cursor="watch")
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.configure(cursor="")

    # --------------------------------------------------------------- saving
    def save_text(self) -> None:
        text = self.get_text()
        if not text.strip():
            self.status_var.set("There is no text to save yet.")
            return
        document = self.current_document()
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save text",
            defaultextension=".txt",
            initialfile=default_output_path(document.path if document else None),
            initialdir=self.settings.last_save_dir or self.settings.last_open_dir or None,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            saved = save_text(path, text)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.settings.last_save_dir = str(saved.parent)
        self.status_var.set(f"Saved to {saved}")

    def save_all_texts(self) -> None:
        ready = [doc for doc in self.documents if doc.text.strip()]
        if not ready:
            self.status_var.set("Nothing has been read yet.")
            return
        folder = filedialog.askdirectory(
            parent=self,
            title="Save all texts into folder",
            initialdir=self.settings.last_save_dir or self.settings.last_open_dir or None,
        )
        if not folder:
            return
        target = Path(folder)
        written = 0
        for document in ready:
            stem = Path(document.path).stem if document.path else Path(document.title).stem
            try:
                save_text(target / f"{stem}.txt", document.text)
            except OSError as exc:
                messagebox.showerror("Save failed", str(exc), parent=self)
                return
            written += 1
        self.settings.last_save_dir = str(target)
        self.status_var.set(f"Saved {written} text files to {target}")

    # ---------------------------------------------------------------- close
    def on_close(self) -> None:
        self._closing = True
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:  # pragma: no cover - already gone
                pass
            self._resize_job = None
        engine = self.current_engine()
        if engine is not None:
            self.settings.engine = engine.name
            self.settings.set_language(engine.name, self.language_var.get())
        self.settings.preprocess = self._options_from_ui()
        self.settings.wrap_text = self.wrap_var.get()
        self.settings.auto_copy = self.auto_copy_var.get()
        try:
            self.settings.window_geometry = self.winfo_geometry()
        except tk.TclError:  # pragma: no cover - window already gone
            pass
        self.settings.save()
        self.destroy()


def run(initial_files: list[str] | None = None) -> int:
    """Open the window. Returns a process exit code."""
    try:
        app = ImageToTextApp(initial_files)
    except tk.TclError as exc:
        print(f"Could not open a window: {exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
