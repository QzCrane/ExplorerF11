#!/usr/bin/env python3
"""Generate the two application icons from geometry, so they stay reproducible.

    python tools/make-icons.py

Writes src/ExplorerF11.ico and src/ExplorerF11-paused.ico. Both carry every
size Windows asks for (16 through 256), which is what keeps the tray icon sharp
at 100 %, 150 % and 200 % scaling instead of being a stretched 16 px bitmap.

The mark is a flat single-colour lightning bolt on a transparent background - no
tile, no plate. That is the shape of the icons already sitting in the Windows 11
notification area (thin glyphs on the taskbar, not app-store squares), so it
lines up with them instead of looking pasted in. Blue reads on both the light
and the dark taskbar; the paused variant is the same bolt in neutral grey.
"""

import pathlib
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    sys.exit("Pillow is required: python -m pip install pillow")

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 8                     # supersampling factor for the anti-aliased master
GRID = 256                 # logical design grid

# Bolt in the 256 grid, filling the height so it still reads at 16 px: the waist
# is 17 px, which lands on a full pixel once downsampled.
BOLT = [(161, 10), (52, 132), (111, 132), (97, 246), (205, 118), (145, 118)]

RUNNING = (24, 104, 200, 255)   # #1868C8 - the accent blue Windows uses
PAUSED  = (126, 133, 142, 255)  # neutral grey, still legible on dark and light


def build(colour):
    """One 256 px RGBA master, drawn at SS x and box-filtered down."""
    big = GRID * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon([(x * SS, y * SS) for x, y in BOLT], fill=colour)
    return img.resize((GRID, GRID), Image.LANCZOS)


def write(path, m):
    frames = [m.resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(path, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"{path}  {path.stat().st_size:,} bytes  sizes {SIZES}")


if __name__ == "__main__":
    root = pathlib.Path(__file__).resolve().parent.parent
    write(root / "src" / "ExplorerF11.ico", build(RUNNING))
    write(root / "src" / "ExplorerF11-paused.ico", build(PAUSED))
