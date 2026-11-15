"""Count 'teleports' in units' Dyer's position records: consecutive located mentions (by date) more than 300 km apart
at an implied speed over 250 km/day (month-precision dates get 15 days of slack), with the pooled place locations
(geocode.py) and with the per-mention resolutions (resolve_mentions.py). A unit's first 45 days are left out: the
rail trip from its home state to the front is a real long move.
Usage: python pipeline/teleports.py data/places"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import params  # noqa: E402
from geocode import km  # noqa: E402
from resolve_mentions import day  # noqa: E402


def main(places_dir):
    P = Path(places_dir)
    geo = {g["place_key"]: g for g in csv.DictReader(open(P / "geocoded.csv", encoding="utf-8"))}
    res = {}
    for l in open(P / "mention_resolution.jsonl", encoding="utf-8"):
        r = json.loads(l); res[(r["unit"], r["date"], r["raw"])] = (r["lat"], r["lon"]) if r["lat"] is not None else None
    seq = defaultdict(list); seen = set()
    for l in open(P / "place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] != "unit_at" or not m.get("unit"):
            continue
        k = (m["unit"], m.get("date"), m["raw"])
        if k in seen:
            continue
        seen.add(k)
        t, sl = day(m.get("date"))
        g = geo.get(m["place_key"])
        pooled = (float(g["lat"]), float(g["lon"])) if g and g["lat"] else None
        seq[m["unit"]].append((t, sl, pooled, res.get(k, pooled)))
    for label, ix in (("pooled places", 2), ("resolved by route", 3)):
        n = tel = 0; units = set()
        for u, xs in seq.items():
            xs = sorted((x for x in xs if x[0] is not None and x[ix]), key=lambda x: x[0])
            if xs:
                start = xs[0][0]
                xs = [x for x in xs if x[0] - start > params.FRONT_TRIP_DAYS]       # not the trip from the home state to the front
            for a, b in zip(xs, xs[1:]):
                n += 1
                d = km(a[ix], b[ix]); t = max(1, b[0] - a[0] + a[1] + b[1])
                if d > 300 and d / t > 250:
                    tel += 1; units.add(u)
        print(f"{label:18s} steps {n:6d}  teleports {tel:5d} in {len(units)} units")


if __name__ == "__main__":
    main(*sys.argv[1:])
