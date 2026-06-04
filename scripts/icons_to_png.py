#!/usr/bin/env python3
"""
Decode Plai icon headers back into PNGs (for reference / restyling).

Scans a directory tree for every `image_data_*` C array — launcher app icons,
the 12x12 status/list glyphs, the non-square battery icon, the "big" detail
icons, all of them — un-byte-swaps each one (assets are stored big-endian
RGB565 for the ST7789 / LovyanGFX panel), drops the transparent color key, and
writes one PNG per icon plus a labelled contact sheet.

Dimensions come from the `tImage` comment that accompanies each array, e.g.
    // const tImage bat = { image_data_bat, 32, 16, 16 };
so non-square icons decode correctly. If no such comment is present the array is
assumed square (side = sqrt(length)); a non-square array with no comment is
skipped with a warning (pass its size with --dims var=WxH).

Transparency: the color key lives at the pushImage() call site, not in the
asset, so it cannot be read from the header. By default both keys actually used
in this codebase are treated as transparent:
    0x8631  (dark theme background, used by launcher / big icons)
    0xFFFF  (TFT_WHITE, used by the small glyphs)
Override with --keys (e.g. --keys 0x8631  or  --keys none for fully opaque).

Requires Pillow:  pip install pillow

Usage:
    python scripts/icons_to_png.py                       # all icons under main/ -> icon_export/
    python scripts/icons_to_png.py --dir main/apps/app_nodes   # just one app
    python scripts/icons_to_png.py --keys 0x8631 --out /tmp/icons
"""
import argparse
import glob
import math
import os
import re
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont

DEFAULT_KEYS = (0x8631, 0xFFFF)   # color keys treated as transparent by default
BG = (0x33, 0x33, 0x33)           # THEME_COLOR_BG, the contact-sheet tile background
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARRAY_RE = re.compile(r"(image_data_\w+)\s*\[\s*(\d*)\s*\]\s*=\s*\{(.*?)\};", re.S)
DIMS_RE = re.compile(r"tImage\s+\w+\s*=\s*\{\s*(image_data_\w+)\s*,\s*(\d+)\s*,\s*(\d+)")
DEFINE_RE = re.compile(r"#define\s+(\w+)\s+(0[xX][0-9A-Fa-f]+)")
# A pixel token is a hex literal or a #define'd color name (e.g. stat_tasks.h's BG/FG/DT).
TOKEN_RE = re.compile(r"0[xX][0-9A-Fa-f]{1,4}|[A-Za-z_]\w*")


def strip_comments(s):
    """Drop // and /* */ comments so ASCII-art labels don't pollute the value scan."""
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"//[^\n]*", " ", s)


def group_of(path):
    """A short label for where an icon lives: its app folder, else parent dir."""
    parts = os.path.normpath(path).split(os.sep)
    if "apps" in parts:
        i = parts.index("apps")
        if i + 1 < len(parts):
            return parts[i + 1]
    return parts[-2] if len(parts) >= 2 else "misc"


def collect(root, extra_dims):
    """Scan *.h under root. Return (icons, dims).

    icons: list of {file, var, vals, group}
    dims:  {var: (w, h)} parsed from tImage comments, merged with extra_dims.
    """
    icons, dims = [], dict(extra_dims)
    for h in sorted(glob.glob(os.path.join(root, "**", "*.h"), recursive=True)):
        txt = open(h, encoding="utf-8", errors="ignore").read()
        if "image_data_" not in txt:
            continue
        defines = {n: int(v, 16) for n, v in DEFINE_RE.findall(txt)}
        for m in DIMS_RE.finditer(txt):
            dims.setdefault(m.group(1), (int(m.group(2)), int(m.group(3))))
        for m in ARRAY_RE.finditer(txt):
            var, declared = m.group(1), m.group(2)
            vals, unknown = [], set()
            for tok in TOKEN_RE.findall(strip_comments(m.group(3))):
                if tok[:2] in ("0x", "0X"):
                    vals.append(int(tok, 16))
                elif tok in defines:
                    vals.append(defines[tok])
                else:
                    unknown.add(tok)
            if unknown:
                print(f"!! {var}: ignored unknown token(s): {', '.join(sorted(unknown))}")
            if not vals:
                print(f"!! {var}: no pixel values parsed, skipping")
                continue
            n = int(declared) if declared else len(vals)
            if len(vals) < n:                      # C zero-initializes the unspecified tail
                print(f"note: {var}: parsed {len(vals)} of {n} values, zero-padding")
                vals += [0] * (n - len(vals))
            elif len(vals) > n:
                print(f"!! {var}: parsed {len(vals)} > declared [{n}], truncating")
                vals = vals[:n]
            icons.append({"file": h, "var": var, "vals": vals, "group": group_of(h)})
    return icons, dims


def dimensions(var, n, dims):
    """Resolve (w, h) for an array of length n: tImage comment, else square."""
    if var in dims:
        return dims[var]
    side = int(round(math.sqrt(n)))
    return (side, side) if side * side == n else None


def decode(vals, w, h, keys):
    """Un-byte-swap to true RGB565; keyed pixels become transparent."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for i, v in enumerate(vals):
        if v in keys:
            continue
        s = ((v & 0xFF) << 8) | (v >> 8)   # un-byte-swap
        r, g, b = (s >> 11) & 0x1F, (s >> 5) & 0x3F, s & 0x1F
        px[i % w, i // w] = (round(r * 255 / 31), round(g * 255 / 63), round(b * 255 / 31), 255)
    return img


def out_name(icon, per_file):
    """PNG basename: the header stem, disambiguated by var if a file has several."""
    stem = os.path.splitext(os.path.basename(icon["file"]))[0]
    if len(per_file[icon["file"]]) > 1:
        return f"{stem}.{icon['var'][len('image_data_'):]}"
    return stem


def contact_sheet(rendered):
    """rendered: list of (group, name, RGBA image). Returns an RGB sheet."""
    SCALE, pad, cols, labelh = 4, 14, 6, 22
    tile = 56 * SCALE
    cellw, cellh = tile + pad, tile + labelh + pad
    rows = math.ceil(len(rendered) / cols)
    sheet = Image.new("RGBA", (cols * cellw + pad, rows * cellh + pad), (0x22, 0x22, 0x22, 255))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    for idx, (group, name, img) in enumerate(rendered):
        r, c = divmod(idx, cols)
        x, y = pad + c * cellw, pad + r * cellh
        cell = Image.new("RGBA", (tile, tile), BG + (255,))
        f = tile / max(img.width, img.height)          # fit, preserve aspect (handles non-square)
        scaled = img.resize((max(1, round(img.width * f)), max(1, round(img.height * f))), Image.NEAREST)
        cell.alpha_composite(scaled, ((tile - scaled.width) // 2, (tile - scaled.height) // 2))
        sheet.alpha_composite(cell, (x, y))
        label = f"{group}/{name}"
        tw = d.textlength(label, font=font)
        d.text((x + max(0, (tile - tw) / 2), y + tile + 3), label, fill=(0xDD, 0xDD, 0xDD, 255), font=font)
    return sheet.convert("RGB")


def main(root, out_dir, keys, extra_dims):
    os.makedirs(out_dir, exist_ok=True)
    icons, dims = collect(root, extra_dims)
    per_file = defaultdict(list)
    for ic in icons:
        per_file[ic["file"]].append(ic)

    rendered = []
    for ic in sorted(icons, key=lambda i: (i["group"], out_name(i, per_file))):
        wh = dimensions(ic["var"], len(ic["vals"]), dims)
        if wh is None:
            print(f"!! skip {ic['var']}: non-square ({len(ic['vals'])} values) and no tImage/--dims")
            continue
        w, h = wh
        img = decode(ic["vals"], w, h, keys)
        name = out_name(ic, per_file)
        sub = os.path.join(out_dir, ic["group"])
        os.makedirs(sub, exist_ok=True)
        img.save(os.path.join(sub, f"{name}.png"))
        rendered.append((ic["group"], name, img))
        print(f"{ic['group']+'/'+name:32s} {w}x{h}")

    if rendered:
        contact_sheet(rendered).save(os.path.join(out_dir, "_all_icons.png"))
    print(f"done -> {out_dir}  ({len(rendered)} icons)")


def parse_keys(s):
    s = s.strip().lower()
    if s in ("none", "opaque", ""):
        return frozenset()
    return frozenset(int(x, 16) for x in s.split(","))


def parse_dims(items):
    out = {}
    for it in items or []:
        var, _, size = it.partition("=")
        w, _, h = size.lower().partition("x")
        key = var if var.startswith("image_data_") else "image_data_" + var
        out[key] = (int(w), int(h))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Decode Plai icon headers to PNG",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(REPO, "main"),
                    help="directory tree to scan (default: main/; point at one app to export just it)")
    ap.add_argument("--out", default=os.path.join(REPO, "icon_export"),
                    help="output directory (default: icon_export/)")
    ap.add_argument("--keys", type=parse_keys, default=frozenset(DEFAULT_KEYS),
                    help="comma-separated transparent color keys in hex, or 'none' "
                         "(default: 0x8631,0xFFFF)")
    ap.add_argument("--dims", action="append", metavar="var=WxH",
                    help="override size for an array with no tImage comment (repeatable)")
    args = ap.parse_args()
    main(args.dir, args.out, args.keys, parse_dims(args.dims))
