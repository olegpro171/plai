# Icon tooling

Plai icons are C arrays of **RGB565** stored **byte-swapped** (big-endian, to
match the ST7789 / LovyanGFX panel). These two scripts convert between those
arrays and PNGs and handle the byte-swap (and transparency) so colors come out
right on device. They work for **every icon in the firmware**, not just one app:

| Kind | Size | Example arrays | Transparent key at the call site |
|------|------|----------------|----------------------------------|
| Launcher app icons | 56×56 | `image_data_app_nodes` | `0x8631` (dark theme bg, swapped) |
| "Big" detail icons | 48–56² | `image_data_nodes_big` | usually opaque / `0x8631` |
| Small status glyphs | 12×12 | `chat`, `pos_*`, `trace_*`, `key_*`, `stat_*` | `0xFFFF` (`TFT_WHITE`) or opaque |
| Battery | 32×16 | `image_data_bat` | opaque (no key) |

The **transparent color key is chosen at the `pushImage()` call site**, not in
the asset, so it must match between the icon, the converter, and the C code that
draws it.

Requires Pillow (`pip install pillow`). Default paths resolve relative to the
repo, so you can run these from any directory.

## Make / replace an icon — `png_to_icon.py`

1. Draw a PNG (Aseprite, Piskel, …). Author at the icon's native size with a
   **transparent background** for keyed icons. Size and key are configurable, so
   one tool covers app icons, status glyphs, the battery, etc.
2. Convert it to a C header:
   ```bash
   # Launcher app icon (56×56, default key 0x8631):
   python scripts/png_to_icon.py nodes.png \
       --out main/apps/app_nodes/assets/app_nodes.h --var image_data_app_nodes

   # 12×12 white-keyed status glyph:
   python scripts/png_to_icon.py chat.png \
       --out main/apps/app_nodes/assets/chat.h --key 0xFFFF

   # Opaque icon, forced to 32×16 (alpha flattened over --bg, default black):
   python scripts/png_to_icon.py bat.png --width 32 --height 16 --key none
   ```
   Defaults: `--out` is `<png>.h` next to the source, `--var` is
   `image_data_<out-stem>`, size is taken from the PNG, key is `0x8631`. Size
   mismatches are resized **NEAREST** (author at native size for crisp pixels).
3. Point the app at the array. The key passed to `pushImage` **must match**
   `--key`:
   ```cpp
   // launcher icon:
   void* getAppIcon() override { return (void*)(new AppIcon_t(image_data_app_xxx, nullptr)); }
   // glyph drawn directly:
   canvas->pushImage(x, y, w, h, image_data_xxx, 0xFFFF);   // 0xFFFF == --key
   ```
4. Build & flash. Editing an existing icon header only needs an app flash:
   ```
   .\flash.ps1 -AppOnly
   ```

The generated header also carries a `// const tImage … = { var, W, H, 16 };`
comment recording the dimensions, so non-square icons round-trip correctly.

## Export existing icons (reference / restyling) — `icons_to_png.py`

```bash
python scripts/icons_to_png.py                       # every icon under main/ -> icon_export/
python scripts/icons_to_png.py --dir main/apps/app_nodes   # just one app
python scripts/icons_to_png.py --keys 0x8631 --out /tmp/icons
```
Writes one PNG per icon under `icon_export/<app>/<name>.png` (gitignored) plus
`_all_icons.png`, a labelled contact sheet on the launcher background.

It finds every `image_data_*` array in the tree, reads dimensions from the
`tImage` comment (falling back to square; use `--dims var=WxH` for a non-square
array that lacks the comment), resolves `#define`d color names (e.g.
`stat_tasks.h`), and zero-pads under-filled arrays the way C does.

By default both keys used in this codebase (`0x8631`, `0xFFFF`) render as
transparent so glyph shapes are visible. Override with `--keys` — e.g.
`--keys none` to see opaque icons exactly as drawn.

## Gotchas

- **Byte order:** colors are stored byte-swapped. The scripts do this for you; a
  generic RGB565 converter (or lcd-image-converter *without* its byte-swap
  option) produces wrong colors — blue↔green, yellow↔purple, noisy edges.
- **The key must match the call site.** `--key` (encode) and the value passed to
  `pushImage` must be the same, or transparency breaks on device.
- **Round-trip fidelity:** decode→encode is byte-exact *only if the keys match*.
  Export an opaque icon with `--keys none` (then `--key none`) to preserve every
  pixel; the default key set treats `0x8631`/`0xFFFF` as transparent for viewing.
- **Transparency:** PNG alpha below 128 becomes the color key. Use a transparent
  background, not a solid fill (unless the icon is opaque — then use `--key none`).
- **Size:** pass `--width`/`--height` or let the PNG define it. Other sizes are
  resized NEAREST; author at native size for crisp pixels.
