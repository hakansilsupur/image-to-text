"""Entry point for the packaged ImageToText.exe.

The .exe is built windowed (no console), so it always opens the window. Any
file names passed along - from a double-click on an associated image, or from
dropping files onto the .exe - are opened in it.
"""

from __future__ import annotations

import sys

from image_to_text.app import run

if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
