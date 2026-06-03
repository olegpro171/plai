# Icon tooling

Launcher app icons are **56×56 RGB565**, stored **byte-swapped** (big-endian, to
match the ST7789 / LovyanGFX panel) with **`0x8631`** as the transparent color
key. These two scripts hide those details so the colors come out right on device.

Requires Pillow (`pip install pillow`). Default paths resolve relative to the
repo, so you can run these from any directory.

## Make / replace an app icon

1. Draw a **56×56 PNG** with a **transparent background** (Aseprite, Piskel, …).
2. Convert it to the C header:
   ```
   python scripts/png_to_icon.py my_icon.png
   ```
   Defaults overwrite the charge app's icon
   (`main/apps/app_charge/assets/app_charge.h`, array `image_data_app_charge`).
   For another app, pass `--out` / `--var`:
   ```
   python scripts/png_to_icon.py my_icon.png --out main/apps/app_xxx/assets/app_xxx.h --var image_data_app_xxx
   ```
   The app's packer must reference that array:
   ```cpp
   void* getAppIcon() override { return (void*)(new AppIcon_t(image_data_app_xxx, nullptr)); }
   ```
3. Build & flash. Editing an existing icon header only needs an app flash:
   ```
   .\flash.ps1 -AppOnly
   ```

## Export existing icons (reference / restyling)

```
python scripts/icons_to_png.py            # -> icon_export/ (gitignored)
```
Writes one `<APP>.png` per icon (native 56×56, transparent) plus `_all_icons.png`,
a labelled side-by-side sheet on the launcher background.

## Gotchas

- **Byte order:** colors are stored byte-swapped. `png_to_icon.py` does this for
  you; a generic RGB565 converter (or lcd-image-converter *without* its byte-swap
  option) produces wrong colors — blue↔green, yellow↔purple, noisy edges.
- **Transparency:** PNG alpha below 128 becomes the `0x8631` key. Use a
  transparent background, not a solid fill.
- **Size:** 56×56. Other sizes are resized NEAREST; author at 56×56 for crisp pixels.
