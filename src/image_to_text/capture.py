"""Grab a rectangle of the screen, so text can be read straight off the desktop.

Draws a dimmed overlay the user drags a box on, then screenshots that box.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from PIL import Image

#: Anything smaller than this is treated as a stray click, not a selection.
MIN_SELECTION_PX = 8


def capture_region(root: tk.Misc, on_done: Callable[[Image.Image | None], None]) -> None:
    """Let the user drag a rectangle, then hand the screenshot to ``on_done``.

    ``on_done`` receives ``None`` if the user pressed Escape, right-clicked, or
    drew nothing worth grabbing. Returns immediately: the screenshot is taken
    after Tk has torn the overlay down, so the overlay never lands in the shot.
    """
    overlay = tk.Toplevel(root)
    overlay.withdraw()
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True)
    try:
        overlay.attributes("-alpha", 0.3)
    except tk.TclError:  # pragma: no cover - window manager dependent
        pass

    # Cover the whole virtual desktop, not just the primary monitor.
    width = root.winfo_vrootwidth() or root.winfo_screenwidth()
    height = root.winfo_vrootheight() or root.winfo_screenheight()
    left = root.winfo_vrootx()
    top = root.winfo_vrooty()
    overlay.geometry(f"{width}x{height}+{left}+{top}")

    canvas = tk.Canvas(
        overlay, cursor="crosshair", bg="black", highlightthickness=0, takefocus=True
    )
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        width // 2,
        40,
        text="Drag to select the text you want to read  -  Esc to cancel",
        fill="white",
        font=("Segoe UI", 16),
    )

    state = {"x": 0, "y": 0, "rect": None, "finished": False}

    def finish(bbox: tuple[int, int, int, int] | None) -> None:
        if state["finished"]:
            return
        state["finished"] = True
        overlay.destroy()
        # Let the compositor actually remove the overlay before screenshotting.
        root.update_idletasks()
        root.after(120, lambda: on_done(_grab(bbox) if bbox else None))

    def on_press(event: tk.Event) -> None:
        state["x"], state["y"] = event.x_root, event.y_root
        state["rect"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#4da3ff", width=2, fill="white"
        )

    def on_drag(event: tk.Event) -> None:
        if state["rect"] is None:
            return
        canvas.coords(
            state["rect"],
            state["x"] - left,
            state["y"] - top,
            event.x_root - left,
            event.y_root - top,
        )

    def on_release(event: tk.Event) -> None:
        x1, y1 = state["x"], state["y"]
        x2, y2 = event.x_root, event.y_root
        box = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        too_small = (box[2] - box[0]) < MIN_SELECTION_PX or (box[3] - box[1]) < MIN_SELECTION_PX
        finish(None if too_small else box)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<ButtonPress-3>", lambda _event: finish(None))
    overlay.bind("<Escape>", lambda _event: finish(None))

    overlay.deiconify()
    overlay.lift()
    canvas.focus_force()


def _grab(bbox: tuple[int, int, int, int]) -> Image.Image | None:
    try:
        from PIL import ImageGrab

        shot = ImageGrab.grab(bbox=bbox, all_screens=True)
    except TypeError:  # pragma: no cover - all_screens is Windows-only
        from PIL import ImageGrab

        shot = ImageGrab.grab(bbox=bbox)
    except (OSError, ImportError):  # pragma: no cover - defensive
        return None
    return shot.convert("RGB") if shot is not None else None
