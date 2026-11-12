"""Shaded relief for a map window, from AWS Terrain Tiles (terrarium PNG elevation, public domain sources: SRTM, USGS NED).

Tiles are mosaicked on the Web Mercator tile grid, so the image's corners are tile corners and MapLibre can lay
it down as a canvas/image source with no reprojection. Output: a grey+alpha PNG where shadows are black and
sun-facing slopes white (alpha quantized to 22 levels), each with alpha by strength (flat land and water are transparent), so it works over the
light and dark themes; and a JSON sidecar with the four corner coordinates.

Usage: python pipeline/terrain.py W,S,E,N zoom out.png [exaggeration]
"""
import io, json, math, sys, time, urllib.request
import numpy as np
from PIL import Image

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def main(bbox, z, out, exag="1.0"):
    W, S, E, N = map(float, bbox.split(",")); z = int(z); exag = float(exag)
    x0, y0 = map(int, tile_xy(W, N, z)); x1, y1 = map(int, tile_xy(E, S, z))
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    elev = np.zeros((ny * 256, nx * 256), dtype=np.float32)
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            req = urllib.request.Request(URL.format(z=z, x=tx, y=ty), headers={"User-Agent": "civil-war-viewer/0.1 (personal research project)"})
            for attempt in range(3):
                try:
                    a = np.asarray(Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=30).read())).convert("RGB")).astype(np.float32)
                    break
                except Exception:
                    time.sleep(2)
            elev[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
    # metres per pixel at the window's middle latitude
    lat_mid = (S + N) / 2
    mpp = 156543.03392 * math.cos(math.radians(lat_mid)) / 2 ** z
    land = elev > 0.5
    e = np.where(land, elev, 0) * exag
    gy, gx = np.gradient(e, mpp)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(315), math.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)   # 1 lit .. 0 dark
    flat = math.sin(alt)
    rel = np.clip((shade - flat) / (1 - flat), -1, 1)       # >0 lit, <0 shadow, 0 flat
    h, w = rel.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    dark = rel < 0
    rgba[dark, :3] = (32, 38, 40)
    rgba[~dark, :3] = (255, 255, 250)
    a = np.where(dark, np.clip(-rel * 1.6, 0, 1) * 200, np.clip(rel * 1.2, 0, 1) * 120)
    # a little elevation tint: higher ground slightly darker, so ridges read at low zoom
    a = a + np.clip((elev - 150) / 1200, 0, 1) * 40 * land
    a = np.where(land, np.clip(a, 0, 255), 0)
    a = (np.round(a / 12) * 12).clip(0, 255).astype(np.uint8)          # 22 levels: far smaller PNG, same look
    # grey+alpha: 0 = shadow ink, 255 = highlight (the page tints them per theme)
    la = np.stack([np.where(dark, 0, 255).astype(np.uint8), a], axis=-1)
    Image.fromarray(la, "LA").save(out, optimize=True)
    nw = tile_lonlat(x0, y0, z); se = tile_lonlat(x1 + 1, y1 + 1, z)
    corners = [[nw[0], nw[1]], [se[0], nw[1]], [se[0], se[1]], [nw[0], se[1]]]
    json.dump({"corners": corners, "zoom": z, "m_per_px": round(mpp, 1), "size": [w, h]}, open(out.rsplit(".", 1)[0] + ".json", "w"))
    import os
    print(f"{nx}x{ny} tiles, {w}x{h} px, {mpp:.0f} m/px, {os.path.getsize(out)} bytes")


if __name__ == "__main__":
    main(*sys.argv[1:])
