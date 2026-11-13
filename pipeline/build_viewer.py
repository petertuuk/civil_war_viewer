"""Assemble a self-contained map page: viewer/template.html + tracks JSON + basemap JSON + MapLibre's stylesheet.

Usage: python pipeline/build_viewer.py viewer/data/gettysburg.json viewer/data/basemap_gettysburg.json viewer/gettysburg.html \
          "Gettysburg Campaign" "June 1 to July 31, 1863" -79.3,37.6,-76.2,40.4
"""
import json, re, sys
from pathlib import Path

ORD = r"(\d+)(St|Nd|Rd|Th|D)"


# Dyer's headings with OCR damage that the ordinal rule cannot repair (checked by hand against the unit's nickname)
OCR_FIX = {"New York 5 Nd Regiment Infantry": "New York 52nd Regiment Infantry",        # 52nd NY, "German Rangers"
           "New York Ls2Nd Regiment Infantry": "New York 182nd Regiment Infantry",      # 182nd NY, the 69th N.Y.N.G.
           "U.S. Colored Troops I25Th Regiment Infantry": "U.S. Colored Troops 125th Regiment Infantry"}


def pretty(name):
    for bad, good in OCR_FIX.items():
        if name.startswith(bad):
            name = good + name[len(bad):]
    n = re.sub(r"\s*\.?\s*[—–-]+\s*", " ", name).strip(" .,")
    n = re.sub(r"\b(\d+) (Th|St|Nd|Rd)\b", r"\1\2", n)          # "5 Th" -> "5Th" (lowercased below)
    n = re.sub(r"\s{2,}", " ", n)
    n = re.sub(r"(['’])S\b", r"\1s", n).replace('."', '"')
    n = re.sub(r"\b(\d+)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(), n)
    m = re.match(r"^U\.S\. Regular Army Battery \"?([A-M])\"?,? (\d+\w+) Artillery", n)
    if m:
        return f"Battery {m.group(1)}, {m.group(2)} U.S. Artillery"
    m = re.match(r"^(.+?) (\d+(?:st|nd|rd|th|d)) (Regiment|Battalion|Independent Battery|Battery) (.+?)(?: \((.*)\))?$", n)
    if m and not m.group(1)[0].isdigit():
        st, num, kind, rest, nick = m.groups()
        rest = rest.replace("Light Artillery", "Light Artillery").strip()
        label = f"{num} {st} {rest if kind.startswith('Regiment') or kind == 'Battalion' else kind + ' ' + rest}".replace("  ", " ")
        if kind == "Battalion":
            label = f"{num} {st} {rest} Battalion"
        return label + (f" ({nick})" if nick and len(nick) < 30 else "")
    m = re.match(r"^(\d+(?:st|nd|rd|th|d)) (Regiment|Battalion), ([A-Za-z ]+?) (Infantry|Cavalry|Artillery|Light Artillery|Heavy Artillery|Sharpshooters|Mounted Infantry)(.*)$", n)
    if m:
        num, kind, st, br, rest = m.groups()
        return f"{num} {st} {br}{' Battalion' if kind == 'Battalion' else ''}{rest}"
    return n


def main(tracks, base, out, heading="Unit positions", sub="", view=None, terrain="", focus=""):
    """terrain: comma list of viewer/data/terrain_<name>.png (name:minzoom); focus: name=W,S,E,N;name=..."""
    root = Path(__file__).resolve().parents[1]
    J = json.load(open(tracks, encoding="utf-8"))
    for u in J["units"]:
        u["name"] = pretty(u["name"])
    J["view"] = [float(x) for x in view.split(",")] if view else [-80, 37, -76, 41]   # initial map view W,S,E,N
    import base64
    terr = []
    for t in [x for x in terrain.split(",") if x]:
        nm, _, mz = t.partition(":")
        png = root / f"viewer/data/terrain_{nm}.png"
        meta = json.load(open(png.with_suffix(".json")))
        terr.append({"name": nm, "corners": meta["corners"], "minzoom": float(mz or 0),
                     "png": "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()})
    foc = []
    for f in [x for x in focus.split(";") if x]:
        nm, _, bb = f.partition("=")
        foc.append({"name": nm, "bounds": [float(v) for v in bb.split(",")]})
    tpl = open(root / "viewer/template.html", encoding="utf-8").read()
    css = open(root / "viewer/maplibre-gl.css", encoding="utf-8").read()
    page = (tpl.replace("/*MAPLIBRE_CSS*/", css)
               .replace("/*DATA*/", json.dumps(J, separators=(",", ":")))
               .replace("/*BASEMAP*/", open(base, encoding="utf-8").read())
               .replace("/*TERRAIN*/", json.dumps(terr)).replace("/*FOCUS*/", json.dumps(foc))
               .replace("__TITLE__", heading).replace("__HEADING__", heading).replace("__SUB__", sub))
    open(out, "w", encoding="utf-8").write(page)
    print(out, len(page), "bytes;", len(J["units"]), "units")


if __name__ == "__main__":
    main(*sys.argv[1:])
