#!/usr/bin/env python3
"""
Download OpenStreetMap tiles for offline map display on the device.

Downloads pre-rendered JPEG tiles in the standard slippy map format:
  {zoom}/{x}/{y}.jpg

Styles:
  osm       - Standard OpenStreetMap (light, detailed)
  dark      - CartoDB Dark Matter (dark bg, bright features) [RECOMMENDED]
  voyager   - CartoDB Voyager (clean, modern)
  topo      - OpenTopoMap (topographic with elevation)

Usage:
  # Dark theme, high contrast (recommended for small TFT display):
  python download_osm_tiles.py --lat 52.52 --lon 13.405 --radius 50 --style dark

  # Extra contrast boost on any style:
  python download_osm_tiles.py --lat 52.52 --lon 13.405 --radius 50 --style dark --contrast 1.3

The output directory should be copied to /sdcard/map/tiles/ on the device.
"""

import argparse
import math
import os
import sys
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

TILE_SERVERS = {
    "osm":     "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "dark":    "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "voyager": "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    "topo":    "https://tile.opentopomap.org/{z}/{x}/{y}.png",
}

USER_AGENT = "Plai-Meshtastic-Offline-Map/1.0"

# Rate limiting
REQUEST_DELAY = 0.1  # seconds between requests


def latlon_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def tile_to_latlon(x, y, zoom):
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def tiles_in_radius(center_lat, center_lon, radius_km, zoom):
    """Get all tile coordinates within radius_km of center at given zoom."""
    deg_per_km_lat = 1.0 / 111.0
    deg_per_km_lon = 1.0 / (111.0 * math.cos(math.radians(center_lat)))

    lat_min = center_lat - radius_km * deg_per_km_lat
    lat_max = center_lat + radius_km * deg_per_km_lat
    lon_min = center_lon - radius_km * deg_per_km_lon
    lon_max = center_lon + radius_km * deg_per_km_lon

    lat_min = max(-85.051, lat_min)
    lat_max = min(85.051, lat_max)

    x_min, y_max_tile = latlon_to_tile(lat_min, lon_min, zoom)
    x_max, y_min_tile = latlon_to_tile(lat_max, lon_max, zoom)

    tiles = []
    for x in range(x_min, x_max + 1):
        for y in range(y_min_tile, y_max_tile + 1):
            n = 2 ** zoom
            if 0 <= x < n and 0 <= y < n:
                tiles.append((x, y))
    return tiles


def download_tile(z, x, y, output_dir, tile_url, convert_jpg=True,
                  contrast=1.0, brightness=1.0, saturation=1.0):
    """Download a single tile. Returns True if successful or already exists."""
    ext = "jpg" if convert_jpg else "png"
    out_path = os.path.join(output_dir, str(z), str(x), f"{y}.{ext}")

    if os.path.exists(out_path):
        return True

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    url = tile_url.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  FAILED {z}/{x}/{y}: {e}")
        return False

    if convert_jpg:
        try:
            from PIL import Image, ImageEnhance
            import io
            img = Image.open(io.BytesIO(raw_data)).convert("RGB")
            if contrast != 1.0:
                img = ImageEnhance.Contrast(img).enhance(contrast)
            if brightness != 1.0:
                img = ImageEnhance.Brightness(img).enhance(brightness)
            if saturation != 1.0:
                img = ImageEnhance.Color(img).enhance(saturation)
            img.save(out_path, "JPEG", quality=75)
        except ImportError:
            out_path = os.path.join(output_dir, str(z), str(x), f"{y}.png")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(raw_data)
            print("  WARNING: Pillow not installed, saving as PNG (pip install Pillow)")
            return True
    else:
        with open(out_path, "wb") as f:
            f.write(raw_data)

    return True


def main():
    styles_list = ", ".join(TILE_SERVERS.keys())
    parser = argparse.ArgumentParser(description="Download OSM tiles for offline map")
    parser.add_argument("--lat", type=float, required=True, help="Center latitude")
    parser.add_argument("--lon", type=float, required=True, help="Center longitude")
    parser.add_argument("--radius", type=float, default=50, help="Radius in km (default: 50)")
    parser.add_argument("--min-zoom", type=int, default=2, help="Minimum zoom level (default: 2)")
    parser.add_argument("--max-zoom", type=int, default=12, help="Maximum zoom level (default: 12)")
    parser.add_argument("--global-zoom", type=int, default=5,
                        help="Download ALL tiles globally up to this zoom (default: 5)")
    parser.add_argument("--style", default="dark", choices=TILE_SERVERS.keys(),
                        help=f"Map style: {styles_list} (default: dark)")
    parser.add_argument("--contrast", type=float, default=1.0,
                        help="Contrast multiplier, e.g. 1.3 for +30%% (default: 1.0)")
    parser.add_argument("--brightness", type=float, default=1.0,
                        help="Brightness multiplier (default: 1.0)")
    parser.add_argument("--saturation", type=float, default=1.0,
                        help="Color saturation multiplier (default: 1.0)")
    parser.add_argument("--output", default=None, help="Output directory (default: map/<style>)")
    parser.add_argument("--png", action="store_true", help="Save as PNG instead of JPEG")
    args = parser.parse_args()

    convert_jpg = not args.png
    ext = "jpg" if convert_jpg else "png"
    tile_url = TILE_SERVERS[args.style]

    output_dir = args.output if args.output else os.path.join(SCRIPT_DIR, args.style)

    print(f"=== OSM Tile Downloader ===")
    print(f"Center: {args.lat:.4f}, {args.lon:.4f}")
    print(f"Radius: {args.radius} km")
    print(f"Zoom range: {args.min_zoom}-{args.max_zoom}")
    print(f"Global zoom: 0-{args.global_zoom}")
    print(f"Style: {args.style} ({tile_url})")
    if args.contrast != 1.0 or args.brightness != 1.0 or args.saturation != 1.0:
        print(f"Adjust: contrast={args.contrast}, brightness={args.brightness}, saturation={args.saturation}")
    print(f"Format: {ext.upper()}")
    print(f"Output: {output_dir}\n")

    os.makedirs(output_dir, exist_ok=True)

    total_tiles = 0
    total_downloaded = 0
    total_skipped = 0

    # Phase 1: Global tiles at low zoom
    for z in range(args.min_zoom, args.global_zoom + 1):
        n = 2 ** z
        tile_count = n * n
        print(f"Zoom {z}: downloading all {tile_count} global tiles...")
        downloaded = 0
        skipped = 0
        for x in range(n):
            for y in range(n):
                out_path = os.path.join(output_dir, str(z), str(x), f"{y}.{ext}")
                if os.path.exists(out_path):
                    skipped += 1
                    continue
                if download_tile(z, x, y, output_dir, tile_url, convert_jpg,
                                args.contrast, args.brightness, args.saturation):
                    downloaded += 1
                time.sleep(REQUEST_DELAY)
        total_tiles += tile_count
        total_downloaded += downloaded
        total_skipped += skipped
        print(f"  -> {downloaded} new, {skipped} cached")

    # Phase 2: Regional tiles at higher zoom
    for z in range(args.global_zoom + 1, args.max_zoom + 1):
        tiles = tiles_in_radius(args.lat, args.lon, args.radius, z)
        print(f"Zoom {z}: {len(tiles)} tiles in {args.radius}km radius...")
        downloaded = 0
        skipped = 0
        for x, y in tiles:
            out_path = os.path.join(output_dir, str(z), str(x), f"{y}.{ext}")
            if os.path.exists(out_path):
                skipped += 1
                continue
            if download_tile(z, x, y, output_dir, tile_url, convert_jpg,
                            args.contrast, args.brightness, args.saturation):
                downloaded += 1
            time.sleep(REQUEST_DELAY)
        total_tiles += len(tiles)
        total_downloaded += downloaded
        total_skipped += skipped
        print(f"  -> {downloaded} new, {skipped} cached")

    # Summary
    total_size = 0
    total_files = 0
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
            total_files += 1

    print(f"\n{'='*50}")
    print(f"SUMMARY")
    print(f"{'='*50}")
    print(f"  Tiles planned:    {total_tiles}")
    print(f"  Downloaded:       {total_downloaded}")
    print(f"  Already cached:   {total_skipped}")
    print(f"  Total on disk:    {total_files} files, {total_size/1024/1024:.1f} MB")
    print(f"\nCopy the '{os.path.basename(output_dir)}' folder to /sdcard/map/ on the device.")
    print("Done!")


if __name__ == "__main__":
    main()
