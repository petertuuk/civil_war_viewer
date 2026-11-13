"""Geocode the places inventory (data/places/places_inventory.csv) against GNIS (data/external/gnis/gnis_index.tsv).

Tiers (hand overrides in data/places/place_overrides.csv first), each recorded in `method` with a precision radius (m) the map can draw as fuzziness:
  seed        a Wikidata-anchored event at the place (places_inventory seed_lat/lon)
  gnis        the name (or a cleaned form: "X Court House" <-> "X", "X's Ford" <-> "X Ford", "Fort X", feature words
              dropped) found in GNIS in the place's state. Dyer's "Va." also covers West Virginia (and the
              territories their successor states). Several candidates: the one that fits the feature word ("Run",
              "Gap", "Ford") and lies nearest the place's context (where the same regiments were within 30 days),
              preferring towns. A match farther than 150 km from that context (with 2+ context places) is
              rejected for the context estimate; for a town in the stated state the limit is 300 km, or 500 km when
              it is the only town of that name in the state (context drifts: Columbus, Ky. / Columbus, Ohio).
  context     not in GNIS: the median of the context places, if at least 2 (precision 25 km)
Streams and ridges get a coarse precision (GNIS gives a river's mouth); towns 2 km.
Usage: python pipeline/geocode.py data/places data/external/gnis/gnis_index.tsv data/events
Writes data/places/geocoded.csv and geocode_report.txt.
"""
import csv, json, math, re, statistics, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gnis_index import norm  # noqa: E402
from common import km, gnis_rows  # noqa: E402

SPELL = {"sumpter": "sumter", "colliersville": "collierville", "moorefleld": "moorefield", "spottsylvania": "spotsylvania",
         "kenesaw": "kennesaw", "chattahoochie": "chattahoochee", "opequan": "opequon", "fortress monroe": "fort monroe",
         "pittsburg landing": "pittsburg landing", "averysboro": "averasboro", "beverly ford": "beverly ford"}
SAME = {"VA": {"VA", "WV"}, "WV": {"WV", "VA"}, "DT": {"ND", "SD"}, "IT": {"OK"}, "NM": {"NM", "AZ"}, "AZ": {"AZ", "NM"},
        "WT": {"WA", "ID"}, "NE": {"NE"}, "CO": {"CO"}, "DC": {"DC", "VA", "MD"}}
FEATURE = [  # word in the place name -> GNIS classes that fit, precision (m)
    (r"\b(river|creek|run|branch|fork|bayou)\b", {"Stream"}, 15000),
    (r"\b(mountain|mountains|mt|hill|hills|knob|peak|top)\b", {"Summit", "Ridge", "Range", "Populated Place"}, 3000),
    (r"\b(ridge|heights)\b", {"Ridge", "Summit", "Populated Place"}, 5000),
    (r"\bgap\b", {"Gap", "Populated Place"}, 2000),
    (r"\b(ford|ferry|crossing|bridge)\b", {"Crossing", "Populated Place"}, 2000),
    (r"\b(island|isle)\b", {"Island"}, 3000),
    (r"\b(fort|ft|battery|camp|redoubt)\b", {"Military", "Populated Place", "Civil"}, 1500),
    (r"\b(swamp)\b", {"Swamp"}, 5000),
    (r"\b(valley)\b", {"Valley", "Populated Place"}, 15000),
    (r"\b(bluff|bluffs|point|cape)\b", {"Cliff", "Cape", "Populated Place"}, 3000),
    (r"\b(springs?)\b", {"Populated Place", "Spring"}, 2000),
]
PREC = {"Populated Place": 2000, "Civil": 10000, "Military": 1500, "Crossing": 1500, "Gap": 1500, "Summit": 2000,
        "Stream": 15000, "Ridge": 8000, "Valley": 15000, "Island": 3000, "Swamp": 5000, "Range": 15000}
TOWNISH = {"Populated Place", "Military", "Civil"}
RANK = {"Populated Place": 0, "Military": 1, "Crossing": 1, "Gap": 2, "Summit": 2, "Civil": 3, "Ridge": 3, "Stream": 4}


def forms(name):
    """Cleaned forms of a Dyer's place name to try against GNIS, best first."""
    n = norm(re.sub(r"\(.*?\)", " ", name))
    for a, b in SPELL.items():
        n = re.sub(rf"\b{a}\b", b, n)
    n = re.sub(r"^(near|about|at|on|to|from|the|and|in|of|front of|before|vicinity of)\s+", "", n)
    out = [n]
    out.append(re.sub(r"\bcourt house\b", "", n).strip())          # Spotsylvania Court House -> Spotsylvania
    if "court house" not in n:
        out.append(n + " court house")
    out.append(re.sub(r"\b(\w+)s\b(?= (ford|ferry|mill|mills|store|tavern|church|cross roads|station|landing|gap|farm|house|bluff|island|plantation|creek|run))", r"\1", n))
    out.append(re.sub(r"\b(station|landing|depot|cross roads|plantation|farm|house|tavern|store|church|mills?|road|pike|turnpike|heights|bridge)\b", "", n).strip())
    out.append(re.sub(r"^ft\b", "fort", n)); out.append(re.sub(r"^fort\b", "ft", n))
    out.append(re.sub(r"\bmt\b", "mountain", n))
    seen, res = set(), []
    for f in out:
        f = re.sub(r"\s+", " ", f).strip()
        if f and len(f) > 2 and f not in seen:
            seen.add(f); res.append(f)
    return res


def d(s):
    try:
        p = [int(x) for x in (s or "")[:10].split("-")]
        return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 15)
    except (ValueError, IndexError):
        return None


def main(places_dir, gnis_path, events_dir):
    places_dir = Path(places_dir)
    inv = list(csv.DictReader(open(places_dir / "places_inventory.csv", encoding="utf-8")))
    G = defaultdict(list)
    for nm, st, lat, lon, cl, co, fid, raw, kind in gnis_rows(gnis_path):
        G[nm].append((st, lat, lon, cl, co, fid, raw, kind))
    # context: places the same regiment was at within 30 days
    seq = defaultdict(list)
    for l in open(places_dir / "place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m.get("unit") and d(m.get("date")):
            seq[m["unit"]].append((d(m["date"]), m["place_key"]))
    neigh = defaultdict(Counter)
    for u, xs in seq.items():
        xs.sort()
        for i, (t, k) in enumerate(xs):
            for t2, k2 in xs[max(0, i - 6):i + 7]:
                if k2 != k and abs((t2 - t).days) <= 30:
                    neigh[k][k2] += 1
    loc, out = {}, {}
    # pass 0: hand overrides, then seeds
    ov = places_dir / "place_overrides.csv"
    if ov.exists():
        for r in csv.DictReader(open(ov, encoding="utf-8")):
            loc[r["place_key"]] = (float(r["lat"]), float(r["lon"]))
            out[r["place_key"]] = dict(lat=float(r["lat"]), lon=float(r["lon"]), method="override",
                                       precision_m=int(r["precision_m"]), detail=r["note"] or "place_overrides.csv")
    for p in inv:
        if p["seed_lat"] and p["place_key"] not in out:
            loc[p["place_key"]] = (float(p["seed_lat"]), float(p["seed_lon"]))
            out[p["place_key"]] = dict(lat=float(p["seed_lat"]), lon=float(p["seed_lon"]), method="seed",
                                       precision_m=2000, detail=p["seed_source"] + " " + p["seed_event"])

    def context(k):
        pts = [loc[x] for x, _ in neigh[k].most_common(12) if x in loc]
        if not pts:
            return None, 0
        return (statistics.median(a for a, _ in pts), statistics.median(b for _, b in pts)), len(pts)

    def candidates(p):
        st = p["state"]
        states = SAME.get(st, {st}) if st and st != "?" else None
        variants = [p["name"]] + [v for v in (p.get("variants") or "").split("|") if v]
        if states is not None:
            for v in variants:
                for f in forms(v):
                    allc = G.get(f, [])
                    cs = [c for c in allc if c[0] == st] or [c for c in allc if c[0] in states]
                    if cs:
                        return f, cs
        # no state in the source, or a place on a state line (Edwards Ferry, Md./Va.): any state, but only close to
        # where the same regiments were (a stateless "Davis' Farm" is not the one in California)
        ctx, n = context(p["place_key"])
        if ctx and n >= 2:
            for v in variants:
                for f in forms(v):
                    cs = [c for c in G.get(f, []) if km(ctx, (c[1], c[2])) < 60]
                    if cs:
                        return f, cs
        return None, []

    stats = Counter()
    for rnd in range(3):           # later rounds see more resolved neighbours
        for p in inv:
            k = p["place_key"]
            if k in out and out[k]["method"] not in ("context",):
                continue
            if p["kind"] == "state":
                continue
            f, cs = candidates(p)
            ctx, nctx = context(k)
            if cs:
                fit = next(((cls, prec) for rx, cls, prec in FEATURE if re.search(rx, norm(p["name"]))), None)
                def score(c):
                    s = 0.0
                    if fit:
                        s += 0 if c[3] in fit[0] else 3
                    s += RANK.get(c[3], 5) * 0.3
                    if ctx:
                        s += min(km(ctx, (c[1], c[2])), 600) / 50.0
                    if c[0] != p["state"]:
                        s += 0.5                       # WV for a "Va." place: fine, but the stated state first
                    return s
                cs = sorted(cs, key=score)
                best = cs[0]
                if len(cs) > 1 and not ctx and rnd < 2:
                    continue                           # wait for neighbours to choose among namesakes
                # how far from the context a match may be: context places drift (a regiment recruited in Ohio is in
                # West Virginia a month later), so a town that is the only one of its name in the stated state is
                # trusted up to 500 km, other towns 300 km, other features 150 km
                towns = [c for c in cs if c[3] in TOWNISH and c[0] == p["state"]]
                lim = 150
                if best[3] in TOWNISH and best[0] == p["state"]:
                    lim = 500 if len(towns) == 1 else 300
                far = ctx and km(ctx, (best[1], best[2])) > lim
                if far and nctx >= 2:
                    stats["gnis rejected: far from context"] += 1 if rnd == 2 else 0
                    if rnd < 2:
                        continue
                    best = None
                if best:
                    prec = (fit[1] if fit and best[3] in fit[0] else PREC.get(best[3], 5000))
                    out[k] = dict(lat=best[1], lon=best[2], method="gnis", precision_m=prec,
                                  detail=f"{best[6]} ({best[3]}, {best[4]} Co., {best[0]}; GNIS {best[5]}{'; variant' if best[7] == 'variant' else ''}; {len(cs)} candidates; matched '{f}')")
                    loc[k] = (best[1], best[2])
                    continue
            if rnd == 2 and ctx and nctx >= 2 and p["kind"] == "point":
                out[k] = dict(lat=round(ctx[0], 5), lon=round(ctx[1], 5), method="context", precision_m=25000,
                              detail=f"median of {nctx} places the same regiments were at within 30 days")
                loc[k] = ctx
    with open(places_dir / "geocoded.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["place_key", "name", "state", "kind", "mentions", "lat", "lon", "method", "precision_m", "detail"])
        for p in inv:
            o = out.get(p["place_key"])
            w.writerow([p["place_key"], p["name"], p["state"], p["kind"], p["mentions"]] +
                       ([o["lat"], o["lon"], o["method"], o["precision_m"], o["detail"]] if o else ["", "", "", "", ""]))
    tot = sum(int(p["mentions"]) for p in inv)
    by = Counter(); bym = Counter()
    for p in inv:
        m = out.get(p["place_key"], {}).get("method", "none")
        by[m] += 1; bym[m] += int(p["mentions"])
    rep = [f"places {len(inv)}; mentions {tot}"] + [f"  {m:8s} places {by[m]:6d}  mentions {bym[m]:7d} ({100*bym[m]/tot:.1f}%)" for m in ("override", "seed", "gnis", "context", "none")]
    rep += [f"  {k}: {v}" for k, v in stats.items()]
    rep += ["", "Most-mentioned places not located:"] + [f"  {p['mentions']:>5}  {p['name']}, {p['state']} ({p['kind']})" for p in sorted(inv, key=lambda p: -int(p["mentions"])) if p["place_key"] not in out][:40]
    open(places_dir / "geocode_report.txt", "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:6]))


if __name__ == "__main__":
    main(*sys.argv[1:])
