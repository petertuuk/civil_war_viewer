"""Period-neutral basemap for a map window, from Natural Earth (public domain): state outlines, coastline,
major rivers and lakes, clipped to a box and simplified; plus town labels from the geocoded places most
mentioned in the window. Modern roads and cities are left out on purpose.

Usage: python pipeline/basemap.py data/external/naturalearth W,S,E,N data/places/geocoded.csv out.json [tolerance_deg]
"""
import csv, json, sys
from pathlib import Path
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union


# Dyer's period spellings -> the name used today, for the map's town labels
DISPLAY_NAMES = {"Mission Ridge": "Missionary Ridge"}

def main(ne, bbox, geocoded, out, tol="0.004"):
    ne = Path(ne)
    W, S, E, N = map(float, bbox.split(","))
    B = box(W, S, E, N)
    tol = float(tol)
    layers = {}

    def clip(fname, keep=lambda p: True, props=lambda p: {}):
        feats = []
        for f in json.load(open(ne / fname, encoding="utf-8"))["features"]:
            p = f["properties"]
            if not keep(p) or not f.get("geometry"):
                continue
            g = shape(f["geometry"])
            if not g.intersects(B):
                continue
            g = g.intersection(B).simplify(tol, preserve_topology=True)
            if g.is_empty:
                continue
            feats.append({"type": "Feature", "properties": props(p), "geometry": json.loads(json.dumps(mapping(g)), parse_float=lambda x: round(float(x), 4))})
        return feats

    layers["states"] = clip("ne_10m_admin_1_states_provinces_lakes.geojson", lambda p: p.get("adm0_a3") in ("USA", "CAN"),
                            lambda p: {"name": p.get("name"), "abbr": (p.get("postal") or "")})
    layers["lakes"] = clip("ne_10m_lakes.geojson", lambda p: (p.get("scalerank") or 9) <= 6, lambda p: {"name": p.get("name")})
    rivers = clip("ne_10m_rivers_lake_centerlines.geojson", lambda p: True, lambda p: {"name": p.get("name"), "rank": p.get("scalerank")})
    rivers += clip("ne_10m_rivers_north_america.geojson", lambda p: True, lambda p: {"name": p.get("name"), "rank": p.get("scalerank")})
    layers["rivers"] = rivers
    towns = []
    for r in csv.DictReader(open(geocoded, encoding="utf-8")):
        if not r["lat"] or r["method"] not in ("gnis", "override", "seed") or r["kind"] != "point":
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        if W <= lon <= E and S <= lat <= N and int(float(r["precision_m"] or 9e9)) <= 3000:
            towns.append((int(r["mentions"]), DISPLAY_NAMES.get(r["name"], r["name"]), lat, lon))
    towns.sort(reverse=True)
    layers["towns"] = [{"type": "Feature", "properties": {"name": n, "mentions": m},
                        "geometry": {"type": "Point", "coordinates": [round(lo, 4), round(la, 4)]}} for m, n, la, lo in towns[:int(__import__("os").environ.get("TOWNS", "400"))]]
    json.dump({k: {"type": "FeatureCollection", "features": v} for k, v in layers.items()}, open(out, "w", encoding="utf-8"),
              separators=(",", ":"))
    print({k: len(v) for k, v in layers.items()}, Path(out).stat().st_size, "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:])
