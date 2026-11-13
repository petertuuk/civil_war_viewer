"""Check resolved Dyer's mentions (data/places/mention_resolution.jsonl) against independent positions of the same unit
within 10 days: Official Records letter headings (to 25 km: up to corps level) and posts, and the NPS histories
(data/derived/or_datelines.json, or_stations.json, nps_confederate_histories.json). For mentions that moved, the old and
new locations are both scored: share within 150 km of the nearest independent position.
Usage: python pipeline/validate_mention_resolution.py data/places/mention_resolution.jsonl data/places/geocoded.csv \
    data/scores/dyer_to_nps.csv data/derived"""
import csv, json, math, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import km  # noqa: E402


def dn(s):
    p = (s or "")[:10].split("-")
    try:
        return date(int(p[0]), int(p[1]), int(p[2]) if len(p) > 2 else 15).toordinal()
    except (ValueError, IndexError):
        return None


LIMIT_M, OK_KM = 25000, 150


def main(res_p, geo_p, map_p, manual_dir):
    geo = {g["place_key"]: g for g in csv.DictReader(open(geo_p, encoding="utf-8"))}
    d2n = {}
    for r in csv.DictReader(open(map_p, encoding="utf-8")):
        k = r.get("dyer_unit") or r.get("unit_id") or list(r.values())[0]
        v = r.get("nps_code") or r.get("unit_code") or list(r.values())[1]
        d2n[k] = v
    ind = defaultdict(list)
    for f in ("or_datelines.json", "or_stations.json", "nps_confederate_histories.json"):
        for c in json.load(open(f"{manual_dir}/{f}", encoding="utf-8"))["claims"]:
            if c["type"] != "unit_at" or c["place"]["precision_m"] > LIMIT_M or c.get("date_precision") != "day":
                continue
            t = dn(c["date_start"])
            if t:
                ind[c["unit"]["nps_code"]].append((t, c["place"]["lat"], c["place"]["lon"]))
    st = Counter()
    for l in open(res_p, encoding="utf-8"):
        r = json.loads(l)
        code = d2n.get(r["unit"]); t = dn(r["date"])
        if not code or not t or r["lat"] is None:
            continue
        ps = [p for p in ind.get(code, []) if abs(p[0] - t) <= 10]
        if not ps:
            continue
        kind = "newly located" if r["was"] == "none" else ("same" if (r["moved_km"] or 0) < 20 else "moved")
        new = min(km((r["lat"], r["lon"]), p[1:]) for p in ps)
        st[(kind, "n")] += 1; st[(kind, "new ok")] += new <= OK_KM
        g = geo.get(r["place_key"])
        if kind == "moved" and g and g["lat"]:
            old = min(km((float(g["lat"]), float(g["lon"])), p[1:]) for p in ps)
            st[(kind, "old ok")] += old <= OK_KM
    for kind in ("moved", "newly located", "same"):
        n = st[(kind, "n")]
        if n:
            line = f"{kind:14s} checked {n:4d}: new location within {OK_KM} km {100 * st[(kind, 'new ok')] / n:3.0f}%"
            if kind == "moved":
                line += f"; old location {100 * st[(kind, 'old ok')] / n:3.0f}%"
            print(line)


if __name__ == "__main__":
    main(*sys.argv[1:])
