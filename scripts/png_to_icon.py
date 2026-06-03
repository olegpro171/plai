#!/usr/bin/env python3
"""
Convert a PNG into a Plai launcher app-icon header.

Launcher icons are 56x56, RGB565, stored BYTE-SWAPPED (big-endian) to match the
ST7789 / LovyanGFX panel, with 0x8631 as the transparent color key. This script
handles all of that for you:
  - PNG alpha (below the threshold) -> 0x8631 transparent key
  - opaque pixels  -> byte-swapped RGB565

Author a 56x56 PNG with a transparent background (non-56x56 input is resized
NEAREST so pixel art stays crisp). Requires Pillow:  pip install pillow

Usage:
    python scripts/png_to_icon.py <icon.png> [--out <header.h>] [--var <name>]

Defaults target the charge app:
    --out  main/apps/app_charge/assets/app_charge.h
    --var  image_data_app_charge

To use the icon, the app packer's getAppIcon() must reference <var>, e.g.:
    void* getAppIcon() override { return (void*)(new AppIcon_t(image_data_app_xxx, nullptr)); }
"""
import argparse
import os
from PIL import Image

SIZE = 56
TRANSPARENT = 0x8631      # color key (matched on the raw stored value, never swapped)
ALPHA_THRESHOLD = 128

# This file lives in scripts/. Resolve default paths relative to the repo root so
# the tool writes to the right place no matter which directory it is run from.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def store(v):
    """Byte-swap so the panel renders the intended color."""
    return ((v & 0xFF) << 8) | (v >> 8)


def convert(png_path, out_path, var):
    img = Image.open(png_path).convert("RGBA")
    if img.size != (SIZE, SIZE):
        print(f"note: resizing {img.size} -> {SIZE}x{SIZE} (NEAREST)")
        img = img.resize((SIZE, SIZE), Image.NEAREST)
    px = img.load()
    vals = []
    for y in range(SIZE):
        for x in range(SIZE):
            r, g, b, a = px[x, y]
            if a < ALPHA_THRESHOLD:
                vals.append(TRANSPARENT)
            else:
                s = store(rgb565(r, g, b))
                vals.append(s ^ 1 if s == TRANSPARENT else s)  # never collide with the key
    lines = [
        "",
        f"/* Auto-generated app icon ({SIZE}x{SIZE}, byte-swapped RGB565, key 0x8631). */",
        "#include <stdint.h>",
        "",
        f"static const uint16_t {var}[{SIZE * SIZE}] = {{",
    ]
    for y in range(SIZE):
        lines.append("    " + ",".join(f"0x{v:04X}" for v in vals[y * SIZE:(y + 1) * SIZE]) + ",")
    lines += ["};", ""]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"wrote {out_path}  ({var})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="PNG -> Plai app-icon header (byte-swapped RGB565)")
    ap.add_argument("png", help="source PNG (ideally 56x56 with a transparent background)")
    ap.add_argument("--out", default=os.path.join(REPO, "main", "apps", "app_charge", "assets", "app_charge.h"),
                    help="output header path")
    ap.add_argument("--var", default="image_data_app_charge", help="C array name")
    args = ap.parse_args()
    convert(args.png, args.out, args.var)
