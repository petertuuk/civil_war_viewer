"""Forts missing from GNIS, as extra GNIS-index rows (data/external/gnis/gnis_extra.tsv), read by every GNIS loader
through gnis_index.index_lines().

GNIS lists few Civil War works: its only Fort Rice is the Dakota post, so Dyer's "At Fort Rice" (the Petersburg line,
Oct. 1864) had no Virginia candidate for the route resolver. Two sources:
1. Wikidata: items whose class is fort, fortification, bastion fort, redoubt, coastal fort or star fort, in the US,
   with coordinates and a state (data/external/forts/wikidata_forts.rq -> wikidata_forts.csv, fetched 2026-11-12);
   inception after 1865 dropped; "Fort Pulaski National Monument" also as "Fort Pulaski".
2. OpenStreetMap, Petersburg-Richmond lines and the Defenses of Washington (osm_forts.ql ->
   osm_forts_petersburg_washington.json, fetched 2026-11-12): named "Fort / Battery X" features tagged as historic
   (memorial, ruins, monument, fort, archaeological site) or parks ("Fort Stanton Park"). Inside Petersburg only, a
   street named for a siege fort ("Fort Rice Street") stands in for a fort no other source places (class Locale,
   3 km): the streets of the city's south and east sides carry the names of the forts of the line they cross.
A fort GNIS already has within 30 km in the same state is not repeated. Modern posts (Fort Lee, Gregg-Adams, Belvoir, McNair, Myer, Hunt) are left out.
Rows: norm name, state, lat, lon, class (Military; Locale for street stand-ins), county '', id (wd:Q.. / osm:..),
name, 'extra:wikidata' / 'extra:osm' / 'extra:osm-street'.
Usage: python pipeline/forts_gazetteer.py data/external/forts data/external/gnis/gnis_index.tsv data/external/gnis/gnis_extra.tsv
"""
import csv, json, math, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gnis_index import norm, STATES  # noqa: E402

MODERN = {"fort lee", "fort gregg adams", "fort belvoir", "fort lesley j mcnair", "fort mcnair", "fort myer", "fort hunt",
          "fort detrick", "fort meyer heights", "fort america pentagon", "fort drum", "fort knox", "fort carroll",
          "fort worth", "fort place", "fort drive", "fort street", "fort hill", "fort hills", "fort alamo",
          "fort saratoga", "fort sumter", "fort sumner", "fort circle", "fort myer", "fort belvoir", "fort washington light"}
HIST = {"memorial", "ruins", "monument", "fort", "archaeological_site", "castle", "bunker", "heritage", "park",
        "nature_reserve", "yes"}
SUFFIX = r"\s+(National Monument|National Historic(al)? Site|State Historic(al)? Site|Historic(al)? Site|State Park|" \
         r"National Park|Park|Museum|Historic District|Archeological Site|Archaeological Site)$"
PETERSBURG = (37.12, 37.27, -77.48, -77.30)


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))


def main(src, gnis_p, out_p):
    src = Path(src)
    towns = []                                             # for the state of an OSM point: nearest town in VA / DC / MD
    known = {}                                             # (name, state) -> GNIS points: a fort GNIS has is not repeated
    for line in open(gnis_p, encoding="utf-8"):
        nm, st, lat, lon, cl, *_ = line.rstrip("\n").split("\t")
        if cl == "Populated Place" and st in ("VA", "DC", "MD"):
            towns.append((float(lat), float(lon), st))
        if nm.startswith(("fort ", "battery ", "redoubt ", "camp ")):
            known.setdefault((nm, st), []).append((float(lat), float(lon)))
    rows, seen = [], set()

    def add(name, st, lat, lon, cl, fid, kind):
        k = (norm(name), st, round(lat, 2), round(lon, 2))
        if k in seen or not norm(name).strip():
            return False
        if any(km((lat, lon), p) <= 30 for p in known.get((norm(name), st), ())):
            return False                 # GNIS has it (a second copy would make one fort two candidates)
        seen.add(k)
        rows.append([norm(name), st, f"{lat:.5f}", f"{lon:.5f}", cl, "", fid, name, kind])
        return True

    n_wd = 0
    for r in csv.DictReader(open(src / "wikidata_forts.csv", encoding="utf-8")):
        st = STATES.get(r["stateLabel"])
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r["coord"])
        if not st or not m or (r["inception"][:4].isdigit() and int(r["inception"][:4]) > 1865):
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        name = re.sub(r"\s*\(.*?\)\s*$", "", r["itemLabel"]).strip()
        if not re.match(r"(?i)(fort|battery|redoubt|camp)\b", name) or norm(name) in MODERN:
            continue
        qid = "wd:" + r["item"].rsplit("/", 1)[-1]
        n_wd += add(name, st, lat, lon, "Military", qid, "extra:wikidata")
        short = re.sub(SUFFIX, "", name, flags=re.I)
        if short != name:
            add(short, st, lat, lon, "Military", qid, "extra:wikidata")
    n_osm = n_st = 0
    osm = json.load(open(src / "osm_forts_petersburg_washington.json", encoding="utf-8"))["elements"]
    have = {r[0] for r in rows}
    streets = []
    for e in osm:
        t = e.get("tags", {}); name = t.get("name", "")
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        if c["lat"] is None:
            continue
        lat, lon = c["lat"], c["lon"]
        st = min(towns, key=lambda x: km((lat, lon), x[:2]))[2]
        base = re.sub(r",\s*Petersburg National Battlefield$", "", name)
        base = re.sub(r"\s+-\s+.*$|\s+earthworks$|\s+Plaque$", "", base)
        kind = t.get("historic") or t.get("military") or t.get("leisure") or t.get("building") or ""
        if t.get("highway") in ("residential", "unclassified", "tertiary", "secondary", "service"):
            m = re.match(r"((?:Fort|Battery) [A-Z][a-z]+)\s+(Street|Road|Drive|Court|Place|Lane|Way|Avenue)$", base)
            if m and PETERSBURG[0] <= lat <= PETERSBURG[1] and PETERSBURG[2] <= lon <= PETERSBURG[3]:
                streets.append((m.group(1), st, lat, lon, e["type"][0] + str(e["id"])))
            continue
        npb = name.endswith("Petersburg National Battlefield")
        if kind not in HIST or (kind in ("yes", "park", "nature_reserve") and not npb and not re.search(SUFFIX, base, re.I)):
            continue                     # buildings and parks only when named for the work ("Fort Stanton Park")
        base = re.sub(SUFFIX, "", base, flags=re.I)
        one = r"(?:Fort|Battery|Redoubt) (?:[A-Z][\w.]*|[IVXL]+|\d+)"
        two = r"(?:Fort|Battery|Redoubt) (?:[A-Z][\w.]*|de) [A-Z][\w.]*"
        if not (re.fullmatch(one, base) or (kind in HIST - {"yes", "park", "nature_reserve"} and re.fullmatch(two, base))) \
                or norm(base) in MODERN:
            continue
        n_osm += add(base, st, lat, lon, "Military", "osm:" + e["type"][0] + str(e["id"]), "extra:osm")
    have = {(r[0], r[1]) for r in rows}
    gnis_va = set()
    for line in open(gnis_p, encoding="utf-8"):
        nm, st, *_ = line.split("\t", 2)
        if st == "VA" and nm.startswith(("fort ", "battery ")):
            gnis_va.add(nm)
    for name, st, lat, lon, fid in streets:
        if (norm(name), st) in have or norm(name) in gnis_va or norm(name) in MODERN:
            continue
        n_st += add(name, st, lat, lon, "Locale", "osm:" + fid, "extra:osm-street"); have.add((norm(name), st))
    with open(out_p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"extra rows {len(rows)}: wikidata {n_wd}, osm {n_osm}, Petersburg street stand-ins {n_st}")


if __name__ == "__main__":
    main(*sys.argv[1:])
