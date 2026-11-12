"""Daily positions of units for the map, from the claims database.

For each unit, every dated claim with a location is a fix: unit_at claims (the place's coordinates) and
participated claims (the event's location). For each day in the window:
  known   a fix covers the day (an "en route"/"along" claim only on its last day: arrival) (day-precision fixes first, then the shortest span, then source rank and
          confidence; a month-precision fix only when nothing finer covers the day)
  moving  between two fixes at most 21 days apart: linear between the end of one and the start of the next
  stale   no fix for longer: the last position, for up to 10 days, drawn faded
Days with no fix within reach are left out (the unit is not drawn).

Usage: python pipeline/tracks.py civil_war.db START END out.json [W,S,E,N]
  e.g. python pipeline/tracks.py ~/db/civil_war.db 1863-06-01 1863-07-31 viewer/data/gettysburg.json -80,37,-75.5,41
Each unit also carries its brigade in the window (latest order-of-battle placement).
Units are kept when they have a known fix inside the box during the window.
"""
import json, math, sqlite3, sys
from collections import defaultdict
from datetime import date, timedelta

RANK = {"compendium": 3, "official_records": 4, "website": 2, "government_list": 2, "manual": 1}


def d(s, end=False):
    if not s:
        return None
    p = [int(x) for x in s[:10].split("-")]
    try:
        if len(p) == 3:
            return date(*p)
        if len(p) == 2:
            if end:
                return date(p[0] + (p[1] == 12), p[1] % 12 + 1, 1) - timedelta(days=1)
            return date(p[0], p[1], 1)
        return date(p[0], 12, 31) if end else date(p[0], 1, 1)
    except ValueError:
        return date(p[0], p[1], 28)


def main(dbp, start, end, out, bbox=None):
    D0, D1 = d(start), d(end, True)
    box = [float(x) for x in bbox.split(",")] if bbox else None
    db = sqlite3.connect(dbp)
    fixes = defaultdict(list)
    lo, hi = (D0 - timedelta(days=60)).isoformat(), (D1 + timedelta(days=60)).isoformat()
    q1 = """SELECT u.unit_id, u.date_start, u.date_end, u.date_precision, p.lat, p.lon, p.precision_m, p.display_name,
                   s.kind, c.confidence, u.presence, u.portion
            FROM claim_unit_at u JOIN place p ON p.id=u.place_id JOIN claim c ON c.id=u.claim_id JOIN source s ON s.id=c.source_id
            WHERE u.unit_id IS NOT NULL AND p.lat IS NOT NULL AND u.date_start <= ? AND COALESCE(u.date_end, u.date_start) >= ?"""
    for uid, ds, de, prec, lat, lon, pm, name, sk, conf, pres, por in db.execute(q1, (hi, lo)):
        a, b = d(ds), d(de or ds, True)
        if pres in ("en_route", "along") and b and a and b > a:
            a = b                       # "Pursuit of Lee to Manassas Gap, July 5-24": there on arrival, not all along
        fixes[uid].append(dict(a=a, b=b, day=prec == "day", lat=lat, lon=lon, pm=pm or 5000,
                               label=name, rank=RANK.get(sk, 1), conf=conf, kind="at", whole=por in (None, "whole")))
    evloc = {}
    for eid, lat, lon, pm, name in db.execute("""SELECT e.event_id, p.lat, p.lon, p.precision_m, e.event_mention FROM claim_event_at e
                                                 JOIN place p ON p.id=e.place_id WHERE p.lat IS NOT NULL"""):
        evloc.setdefault(eid, (lat, lon, pm or 3000, name))
    q2 = """SELECT p.unit_id, p.event_id, p.date_start, p.date_end, p.date_precision, s.kind, c.confidence, p.portion, ev.display_name
            FROM claim_participated p JOIN claim c ON c.id=p.claim_id JOIN source s ON s.id=c.source_id JOIN event ev ON ev.id=p.event_id
            WHERE p.unit_id IS NOT NULL AND p.event_id IS NOT NULL AND p.date_start <= ? AND COALESCE(p.date_end, p.date_start) >= ?"""
    for uid, eid, ds, de, prec, sk, conf, por, ename in db.execute(q2, (hi, lo)):
        if eid not in evloc:
            continue
        a, b = d(ds), d(de or ds, True)
        if (b - a).days > 20:
            continue                    # a campaign or siege is not a position
        lat, lon, pm, _ = evloc[eid]
        fixes[uid].append(dict(a=a, b=b, day=prec == "day", lat=lat, lon=lon, pm=pm, label=ename,
                               rank=RANK.get(sk, 1) + 1, conf=conf, kind="event", whole=por in (None, "whole")))
    units = {r[0]: r[1:] for r in db.execute("""SELECT u.id, u.display_name, s.name, u.branch, u.echelon, u.state
                                                FROM unit u JOIN side s ON s.id=u.side_id""")}
    # brigade in this window (latest order-of-battle placement), so the map can draw a brigade's regiments as a line
    brig = {}
    for uid, pm, pj, ds in db.execute("""SELECT x.unit_id, x.parent_mention, x.parent_path_json, x.date_start FROM claim_subordinate_to x
            JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE s.kind IN ('website','official_records') AND x.unit_id IS NOT NULL AND x.date_start BETWEEN ? AND ?
            ORDER BY x.date_start""", (D0.isoformat(), D1.isoformat())):
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            p = {}
        b = (p.get("brigade") or "").strip()
        if b:
            brig[uid] = (b + " / " + (p.get("division") or "")).strip(" /")[:90]
    ndays = (D1 - D0).days + 1
    res, nk = [], 0
    for uid, fx in fixes.items():
        fx = [f for f in fx if f["a"] and f["b"] and f["b"] >= f["a"]]
        if box and not any(box[0] <= f["lon"] <= box[2] and box[1] <= f["lat"] <= box[3] and f["b"] >= D0 and f["a"] <= D1 for f in fx):
            continue
        def best(t):
            cov = [f for f in fx if f["a"] <= t <= f["b"]]
            if not cov:
                return None
            cov.sort(key=lambda f: (not f["day"], (f["b"] - f["a"]).days > 3, f["pm"] > 500, not f["whole"], -f["rank"], -f["conf"], (f["b"] - f["a"]).days, f["pm"]))
            return cov[0]
        days = [best(D0 + timedelta(days=i)) for i in range(ndays)]
        known = [i for i, f in enumerate(days) if f and (f["day"] or (f["b"] - f["a"]).days <= 31)]
        if not known:
            continue
        track = []
        # fixes just outside the window help interpolate its first and last days
        before = max((f for f in fx if f["b"] < D0 and (f["day"] or (f["b"] - f["a"]).days <= 31)), key=lambda f: f["b"], default=None)
        after = min((f for f in fx if f["a"] > D1 and (f["day"] or (f["b"] - f["a"]).days <= 31)), key=lambda f: f["a"], default=None)
        pts = [(i, days[i]) for i in known]
        if before:
            pts.insert(0, ((before["b"] - D0).days, before))
        if after:
            pts.append(((after["a"] - D0).days, after))
        j = 0
        for i in range(ndays):
            f = days[i] if i in set(known) else None
            if f:
                track.append([i, round(f["lat"], 4), round(f["lon"], 4), 0, f["pm"], f["label"][:60]]); nk += 1
                continue
            while j + 1 < len(pts) and pts[j + 1][0] < i:
                j += 1
            prev = pts[j] if pts[j][0] < i else None
            nxt = pts[j + 1] if j + 1 < len(pts) and pts[j + 1][0] > i else (pts[j] if pts[j][0] > i else None)
            if prev and nxt and nxt[0] - prev[0] <= 21:
                w = (i - prev[0]) / (nxt[0] - prev[0])
                lat = prev[1]["lat"] + w * (nxt[1]["lat"] - prev[1]["lat"])
                lon = prev[1]["lon"] + w * (nxt[1]["lon"] - prev[1]["lon"])
                track.append([i, round(lat, 4), round(lon, 4), 1, max(prev[1]["pm"], nxt[1]["pm"]),
                              f"{prev[1]['label'][:28]} -> {nxt[1]['label'][:28]}"])
            elif prev and i - prev[0] <= 10:
                track.append([i, round(prev[1]["lat"], 4), round(prev[1]["lon"], 4), 2, prev[1]["pm"], prev[1]["label"][:60]])
        name, side, br, ech, st = units[uid]
        res.append(dict(id=uid, name=name, side=side, branch=br, echelon=ech, state=st, track=track, brig=brig.get(uid)))
    events = []
    for eid, ename, kind in db.execute("SELECT id, display_name, kind FROM event"):
        if eid not in evloc:
            continue
        r = db.execute("SELECT MIN(date_start), MAX(COALESCE(date_end, date_start)), COUNT(DISTINCT unit_id) FROM claim_participated WHERE event_id=?", (eid,)).fetchone()
        a, b = d(r[0]), d(r[1], True)
        if not a or b < D0 or a > D1 or (b - a).days > 20:
            continue
        lat, lon, pm, _ = evloc[eid]
        if box and not (box[0] <= lon <= box[2] and box[1] <= lat <= box[3]):
            continue
        events.append(dict(id=eid, name=ename, kind=kind, start=(a - D0).days, end=(b - D0).days, lat=lat, lon=lon, units=r[2]))
    json.dump(dict(start=D0.isoformat(), days=ndays, units=res, events=events,
                   fields=["day", "lat", "lon", "state (0 known, 1 moving, 2 stale)", "precision_m", "label"]),
              open(out, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"units {len(res)} (Union {sum(u['side']=='Union' for u in res)}, Confederate {sum(u['side']=='Confederate' for u in res)}); "
          f"known unit-days {nk}; all unit-days {sum(len(u['track']) for u in res)}; events {len(events)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
