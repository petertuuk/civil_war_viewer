"""Fast jumps: a unit placed at two places too far apart for the days between them, as a review queue.

Every dated position of a unit in civil_war.db, from all sources: unit_at claims located to 25 km or better (Dyer's,
Official Records letter headings and stations, NPS and state histories, monuments) and the located short events it
fought in (event_at, events up to 7 days, campaigns left out). In date order, a step from one position to the next is a
fast jump when it is over 300 km and faster than 250 km a day (rail and steamer moves are allowed; the same day counts
as one day, month-precision dates get 15 days of slack). A unit's first 45 days are left out (the trip to the front).
A move ("March to Louisville, Aug. 31-Sept. 26", presence en_route) puts the unit at its destination on arrival, as
export_war does; a stay ending in a month only ("duty there till July") ends on the 1st of that month.

For each jump the likely wrong end is named when the positions on either side say so: the end whose removal makes
its neighbours a possible move while the other end's removal does not ('a' or 'b'); 'unclear' otherwise. Support is
the number of the unit's other positions within 10 days and 50 km of each end (from any source).
The trails on the map draw these as dotted lines; this lists them with both sources.

Usage: python pipeline/fast_jumps.py civil_war.db data/scores/fast_jumps.csv data/scores/fast_jumps.txt
"""
import csv, math, sqlite3, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import params  # noqa: E402
from common import km, day_num as day, D0, too_fast, MIN_KM, MAX_KMDAY  # noqa: E402

START_DAYS, PREC_MAX = params.FRONT_TRIP_DAYS, params.FAST_JUMP_PREC_MAX_M


def fast(a, b):
    d = km(a["ll"], b["ll"])
    t = max(1, b["t0"] - a["t1"] + a["sl"] + b["sl"])
    return too_fast(d, t), d, t


def main(dbp, out_csv, out_txt):
    db = sqlite3.connect(dbp)
    uname = dict(db.execute("SELECT id, display_name FROM unit"))
    src = dict(db.execute("SELECT id, title FROM source"))
    obs = defaultdict(list)
    for uid, ds, de, la, lo, pm, pl, span, sid, xb, pid, pres in db.execute("""
        SELECT u.unit_id, u.date_start, u.date_end, p.lat, p.lon, p.precision_m, u.place_mention, c.source_span,
               c.source_id, c.extracted_by, p.display_name, u.presence
        FROM claim_unit_at u JOIN claim c ON c.id=u.claim_id JOIN place p ON p.id=u.place_id
        WHERE u.unit_id IS NOT NULL AND p.lat IS NOT NULL AND u.portion='whole' AND c.status!='rejected'"""):
        if (pm or 99999) > PREC_MAX:
            continue
        t0, sl = day(ds); t1, sl1 = day(de or ds)
        if t1 is not None and sl1:
            t1 -= sl1                   # "duty there till July": left in July, as early as the 1st
        if t0 is None:
            continue
        if pres in ("en_route", "along") and t1 and t1 > t0:
            t0 = t1                     # at the destination on arrival, as export_war places it
        obs[uid].append({"t0": t0, "t1": max(t0, t1 or t0) if not sl else t0, "sl": sl, "ll": (la, lo), "date": ds,
                         "place": pid or pl, "src": f"{src.get(sid, '')} [{xb}]", "span": (span or "")[:140]})
    # located events (short ones) the unit fought in
    evloc = {}
    for eid, la, lo, pm in db.execute("""SELECT e.event_id, p.lat, p.lon, p.precision_m FROM claim_event_at e
            JOIN claim c ON c.id=e.claim_id JOIN place p ON p.id=e.place_id WHERE p.lat IS NOT NULL ORDER BY c.confidence"""):
        if (pm or 99999) <= PREC_MAX:
            evloc[eid] = (la, lo)
    evinfo = {r[0]: r[1:] for r in db.execute("SELECT id, display_name, kind FROM event")}
    for uid, eid, ds, de, sid, xb in db.execute("""
        SELECT p.unit_id, p.event_id, p.date_start, p.date_end, c.source_id, c.extracted_by
        FROM claim_participated p JOIN claim c ON c.id=p.claim_id
        WHERE p.unit_id IS NOT NULL AND p.event_id IS NOT NULL AND p.portion='whole' AND c.status!='rejected'"""):
        if eid not in evloc or evinfo[eid][1] in ("campaign", "operation", "expedition", "march", "siege"):
            continue
        t0, sl = day(ds); t1, _ = day(de or ds)
        if t0 is None or sl or (t1 or t0) - t0 > 7:
            continue
        obs[uid].append({"t0": t0, "t1": t1 or t0, "sl": 0, "ll": evloc[eid], "date": ds, "place": evinfo[eid][0],
                         "src": f"{src.get(sid, '')} [{xb}] (event)", "span": ""})
    rows, stats = [], Counter()
    for uid, xs in obs.items():
        xs.sort(key=lambda o: (o["t0"], o["t1"]))
        if not xs:
            continue
        start = xs[0]["t0"]
        xs = [o for o in xs if o["t0"] - start > START_DAYS]
        # one position per (day, ~5 km cell): same place from several sources is one observation
        ded, seen = [], {}
        for o in xs:
            k = (o["t0"], round(o["ll"][0] / 0.05), round(o["ll"][1] / 0.05))
            if k in seen:
                seen[k]["n"] += 1
                continue
            o["n"] = 1; seen[k] = o; ded.append(o)
        xs = ded
        stats["positions"] += len(xs)
        for i in range(len(xs) - 1):
            a, b = xs[i], xs[i + 1]
            f, d, t = fast(a, b)
            stats["steps"] += 1
            if not f:
                continue
            p = xs[i - 1] if i > 0 else None
            n = xs[i + 2] if i + 2 < len(xs) else None
            # a is the odd one when its predecessor reaches b but not a; b when a reaches b's successor but b does not
            a_bad = p is not None and fast(p, a)[0] and not fast(p, b)[0]
            b_bad = n is not None and fast(b, n)[0] and not fast(a, n)[0]
            sup = lambda o: sum(x["n"] for x in xs if x is not o and abs(x["t0"] - o["t0"]) <= params.SUPPORT_DAYS and km(x["ll"], o["ll"]) <= params.SUPPORT_KM) + o["n"] - 1
            sa, sb = sup(a), sup(b)
            culprit = "a" if a_bad and not b_bad else "b" if b_bad and not a_bad else (
                "a" if sa == 0 and sb >= 2 else "b" if sb == 0 and sa >= 2 else "unclear")
            stats["fast jumps"] += 1; stats[f"likely wrong end: {culprit}"] += 1
            bad = a if culprit == "a" else b if culprit == "b" else None
            if bad:
                stats[f"likely wrong source: {bad['src'].split(' [')[1].split(']')[0]}"] += 1
            rows.append([uname.get(uid), uid, round(d), round(d / t), culprit,
                         a["date"], a["place"], a["src"], sa, a["span"],
                         b["date"], b["place"], b["src"], sb, b["span"]])
    rows.sort(key=lambda r: (r[4] == "unclear", -r[2]))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["unit", "unit_id", "km", "km_per_day", "likely_wrong", "a_date", "a_place", "a_source", "a_support",
                    "a_text", "b_date", "b_place", "b_source", "b_support", "b_text"])
        w.writerows(rows)
    from metrics import record
    record("fast_jumps", rows=len(rows), stats=dict(stats))
    rep = [f"{k}: {v}" for k, v in sorted(stats.items())]
    rep += ["", "Largest with a likely wrong end:"]
    rep += [f"  {r[0]}: {r[2]} km in {max(1, round(r[2] / max(r[3], 1)))} d; {r[5]} {r[6]} ({r[7]}) -> {r[10]} {r[11]} ({r[12]}); "
            f"wrong: {r[4]}" for r in rows if r[4] != "unclear"][:30]
    open(out_txt, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:12]))


if __name__ == "__main__":
    main(*(sys.argv[1:4] or paths.defaults("fast_jumps")))
