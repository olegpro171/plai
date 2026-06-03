#!/usr/bin/env python3
"""
Decode the Plai launcher app icons back into PNGs (for reference / restyling).

For every app whose packer calls getAppIcon(), this reads the referenced
image_data_* array, UN-byte-swaps it (assets are stored big-endian RGB565),
treats 0x8631 as transparent, and writes:
  - <APPNAME>.png   one per icon, native 56x56, transparent background
  - _all_icons.png  a labelled side-by-side sheet on the launcher background

Run from the repo root. Requires Pillow:  pip install pillow

Usage:
    python scripts/icons_to_png.py [--out <dir>]     # default: icon_export/
"""
import argparse
import glob
import math
import os
import re
from PIL import Image, ImageDraw, ImageFont

TRANSPARENT = 0x8631
BG = (0x33, 0x33, 0x33)   # THEME_COLOR_BG (launcher background)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.join(REPO, "main", "apps")


def collect():
    """Return [(display_name, var)] and {var: [u16,...]}."""
    apps = []
    for h in glob.glob(os.path.join(APPS, "**", "*.h"), recursive=True):
        txt = open(h, encoding="utf-8", errors="ignore").read()
        m_icon = re.search(r"AppIcon_t\(\s*(image_data_\w+)", txt)
        if not m_icon:
            continue
        m_name = re.search(r'getAppName\(\)\s*(?:override\s*)?\{\s*return\s*"([^"]*)"', txt)
        apps.append((m_name.group(1) if m_name else m_icon.group(1), m_icon.group(1)))

    arrays = {}
    for h in glob.glob(os.path.join(APPS, "**", "assets", "*.h"), recursive=True):
        txt = open(h, encoding="utf-8", errors="ignore").read()
        for m in re.finditer(r"(image_data_\w+)\s*\[\s*\d*\s*\]\s*=\s*\{(.*?)\};", txt, re.S):
            arrays[m.group(1)] = [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]{1,4}", m.group(2))]
    return apps, arrays


def decode(vals):
    side = int(round(math.sqrt(len(vals))))
    if side * side != len(vals):
        return None
    img = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    px = img.load()
    for i, v in enumerate(vals):
        if v == TRANSPARENT:
            continue
        s = ((v & 0xFF) << 8) | (v >> 8)   # un-byte-swap to true RGB565
        r, g, b = (s >> 11) & 0x1F, (s >> 5) & 0x3F, s & 0x1F
        px[i % side, i // side] = (round(r * 255 / 31), round(g * 255 / 63), round(b * 255 / 31), 255)
    return img


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    apps, arrays = collect()
    icons = []
    for name, var in apps:
        vals = arrays.get(var)
        if not vals:
            print("!! no array for", var); continue
        img = decode(vals)
        if img is None:
            print("!! non-square", var, len(vals)); continue
        img.save(os.path.join(out_dir, f"{name}.png"))
        icons.append((name, img))
        print(f"{name:10s} {img.size[0]}x{img.size[1]}")

    if icons:
        SCALE, pad, cols, labelh = 4, 14, 4, 26
        tile = 56 * SCALE
        cellw, cellh = tile + pad, tile + labelh + pad
        rows = math.ceil(len(icons) / cols)
        sheet = Image.new("RGBA", (cols * cellw + pad, rows * cellh + pad), (0x22, 0x22, 0x22, 255))
        d = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        for idx, (name, img) in enumerate(icons):
            r, c = divmod(idx, cols)
            x, y = pad + c * cellw, pad + r * cellh
            tilebg = Image.new("RGBA", (tile, tile), BG + (255,))
            tilebg.alpha_composite(img.resize((tile, tile), Image.NEAREST))
            sheet.alpha_composite(tilebg, (x, y))
            tw = d.textlength(name, font=font)
            d.text((x + (tile - tw) / 2, y + tile + 4), name, fill=(0xDD, 0xDD, 0xDD, 255), font=font)
        sheet.convert("RGB").save(os.path.join(out_dir, "_all_icons.png"))
    print("done ->", out_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Decode Plai app icons to PNG")
    ap.add_argument("--out", default=os.path.join(REPO, "icon_export"), help="output directory")
    main(ap.parse_args().out)
