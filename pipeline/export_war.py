"""Whole-war export for the map: each unit's best located fix per day, run-length encoded, split into year files.

The browser derives the rest: a day covered by a segment is "known" (or "loose" for a long month-precision stay
such as "duty at Washington till March"), a gap of up to 21 days between segments is "moving" (linear), and up to
10 days after the last segment is "stale". Day numbers count from 1861-01-01.

Choice of fix for a day (same rule as the retired tracks.py, plus: a coarse fix, precision >= 10 km, such as a corps headquarters
or a district, only when nothing finer covers the day): day precision first, then short spans, then monument-grade
precision (<= 500 m), whole unit, source rank, confidence, shortest span. "En route"/"along" claims count on
arrival only; campaigns (> 20 days) are not positions, sieges are (drawn solid).

Writes viewer/war/data/units.json and viewer/war/data/y<year>.json:
  units.json   {"start": "1861-01-01", "units": {id: [name, side 0|1, branch, echelon]}}
  y1863.json   {"labels": [...], "fixes": [[lat*1e4, lon*1e4, precision_m, label, loose, source]], "srcs": [[text, url]], "seg": {id: [[d0, d1, fix], ...]},
                "brig": {id: [[day, label], ...]}, "events": [[id, name, d0, d1, lat*1e4, lon*1e4, units]]}
Usage: python pipeline/export_war.py civil_war.db viewer/war/data
"""
import json, sqlite3, sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_viewer import pretty  # noqa: E402
from common import parse_date as d, km  # noqa: E402

D0 = date(1861, 1, 1)
D1 = date(1865, 12, 31)
RANK = {"compendium": 3, "official_records": 4, "website": 2, "government_list": 2, "manual": 1}


def fixes_by_event_dates(db, evloc, ename):
    """event -> (start, end, lat, lon) for located events, from their participation claims"""
    out = {}
    for eid, a, b in db.execute("SELECT event_id, MIN(date_start), MAX(COALESCE(date_end, date_start)) FROM claim_participated WHERE event_id IS NOT NULL GROUP BY event_id"):
        if eid in evloc and d(a) and d(b, True):
            out[eid] = (d(a), d(b, True), evloc[eid][0], evloc[eid][1])
    return out


def derive(db, segs, evd, D0):
    """Positions for days a unit has no claim of its own and is not between two of its own fixes 21 days or less apart
    (map only, never stored as claims; the unit's own march comes first, but a brigade or campaign position beats
    its last known place):
      brigade   the median position of its brigade companions that day (companions from its nearest order-of-battle
                placement, 150 days before to 45 days after; at least 2 companions placed, a third of them, within 30 km)
      campaign  for a unit in a campaign's order of battle: the campaign's located battle nearest in time (7 days),
                or a straight line between two of them
    Returned as runs with a fix tuple flagged loose 2 (brigade) or 3 (campaign)."""
    import re as _re
    import statistics
    sys.path.insert(0, str(Path(__file__).parent))
    import brigade_inference as BI
    # known positions per day from the units' own fixes (not long stays)
    known = defaultdict(dict)
    covered = defaultdict(set)
    for uid, runs in segs.items():
        for a, b, f in runs:
            for k in range(a, b + 1):
                covered[uid].add(k)
            if f[2] or f[10] or (f[1] - f[0]).days <= 31:
                for k in range(a, b + 1):
                    known[k][uid] = (f[3], f[4])
    # order-of-battle brigade snapshots
    snaps = defaultdict(set); sdate = {}
    for sid, loc, uid, pm, pj, ds in db.execute("""SELECT c.source_id, c.locator, x.unit_id, x.parent_mention, x.parent_path_json, x.date_start
            FROM claim_subordinate_to x JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE s.kind IN ('official_records','website') AND x.unit_id IS NOT NULL AND x.date_start IS NOT NULL"""):
        bk = BI.bkey(pj, pm)
        if not bk or not _re.search(r"brigade|legion", bk):
            continue
        k = (sid, (loc or "").split(" (")[0], bk, ds[:10]); snaps[k].add(uid); sdate[k] = ((d(ds) - D0).days, bk)
    per = defaultdict(list)
    for k, us in snaps.items():
        if len(us) >= 3:
            for u in us:
                per[u].append((sdate[k][0], us - {u}, sdate[k][1]))
    for u in per:
        per[u].sort(key=lambda x: x[0])
    import bisect
    own = {u: sorted(v) for u, v in covered.items()}
    def far_from_own(uid, k, w=None):
        """True unless the unit's own fixes bracket day k within 21 days (the map draws its march between them)."""
        o = own.get(uid)
        if not o:
            return True
        i = bisect.bisect_left(o, k)
        if i < len(o) and o[i] == k:
            return False
        prev = o[i - 1] if i > 0 else None
        nxt = o[i] if i < len(o) else None
        return not (prev is not None and nxt is not None and nxt - prev <= 21)
    out = defaultdict(list)
    def put(uid, k, lat, lon, label, flag):
        out[uid].append((k, round(lat, 2), round(lon, 2), label, flag))
    nb = nc = 0
    for uid, ss in per.items():
        if not ss:
            continue
        lo, hi = ss[0][0] - 150, ss[-1][0] + 45
        for k in range(max(lo, 0), min(hi, (D1 - D0).days) + 1):
            if k in covered[uid] or not far_from_own(uid, k, 7):
                continue                  # the unit's own fixes (and the march between them) come first
            cand = [x for x in ss if k - 45 <= x[0] <= k + 150]
            if not cand:
                continue
            snap = min(cand, key=lambda x: abs(x[0] - k))
            pts = [known[k][c] for c in snap[1] if c in known[k]]
            if len(pts) < 2 or len(pts) * 3 < len(snap[1]):
                continue
            mlat, mlon = statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)
            close = [p for p in pts if abs(p[0] - mlat) < 0.27 and abs(p[1] - mlon) < 0.35]
            if len(close) < 2:
                continue
            put(uid, k, mlat, mlon, f"with its brigade ({snap[2][:50]}; {len(close)} placed)", 2); nb += 1
            covered[uid].add(k)
    # campaign tracks from located member battles (preferred part_of)
    kids = defaultdict(list)
    for e, p in db.execute("SELECT event_id, parent_event_id FROM claim_part_of WHERE preferred=1"):
        if e in evd:
            kids[p].append(evd[e])
    for p in list(kids):
        kids[p].sort()
    camp_name = dict(db.execute("SELECT id, display_name FROM event"))
    for uid, eid, ds, de in db.execute("""SELECT unit_id, event_id, date_start, date_end FROM claim_participated
                                         WHERE unit_id IS NOT NULL AND event_id IS NOT NULL"""):
        ks = kids.get(eid)
        a, b = d(ds), d(de or ds, True)
        if not ks or len(ks) < 2 or not a or not b or (b - a).days <= 20:
            continue
        for k in range(max((a - D0).days, 0), min((b - D0).days, (D1 - D0).days) + 1):
            if k in covered[uid] or not far_from_own(uid, k, 14):
                continue
            t = D0 + timedelta(days=k)
            near = min(ks, key=lambda x: min(abs((x[0] - t).days), abs((x[1] - t).days)) if not (x[0] <= t <= x[1]) else 0)
            gap = 0 if near[0] <= t <= near[1] else min(abs((near[0] - t).days), abs((near[1] - t).days))
            if gap <= 7:
                put(uid, k, near[2], near[3], f"with the {camp_name.get(eid, 'campaign')}", 3); nc += 1
                covered[uid].add(k)
    # days -> runs of the same rounded position
    res = {}
    for uid, rows in out.items():
        rows.sort()
        runs, cur = [], None
        for k, lat, lon, label, flag in rows:
            if cur and k == cur[1] + 1 and (lat, lon, label) == cur[2:5]:
                cur[1] = k
            else:
                if cur:
                    runs.append(cur)
                cur = [k, k, lat, lon, label, flag]
        if cur:
            runs.append(cur)
        res[uid] = [(a, b, (None, None, False, lat, lon, 5000 if flag == 2 else 15000, label, 0, 0, True, False, flag, None))
                    for a, b, lat, lon, label, flag in runs]
    print(f"derived unit-days: with brigade {nb}, with campaign {nc}")
    return res


ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
       "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth", "twenty-first", "twenty-second",
       "twenty-third", "twenty-fourth", "twenty-fifth"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
         "XXI", "XXII", "XXIII", "XXIV", "XXV"]


def canon(x, corps=False):
    """One spelling for an order-of-battle heading, so OR's "First Brigade / Third Army Corps" and Wikipedia's
    "1st Brigade / III Corps" group together on the map: ordinals as 1st, corps as roman numerals, no image sizes or tallies."""
    import re as _re
    if not x:
        return ""
    x = _re.sub(r"\s*\d+px\b", "", x)
    x = _re.sub(r"\s+[A-Z]-\d.*$", "", x)                 # "Third Brigade K-4, W-11, M-0 = 15"
    x = x.strip(" :.;,")
    sfx = lambda n: "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
    m = _re.match(r"(?i)^(%s)\b" % "|".join(ORD), x)
    n = ORD.index(m.group(1).lower()) + 1 if m else None
    if n is None:
        m = _re.match(r"^(\d+)(?:st|nd|rd|th)\b", x)
        n = int(m.group(1)) if m else None
    if n is None and corps:
        m = _re.match(r"^([IVX]+)\b", x)
        n = ROMAN.index(m.group(1)) + 1 if m and m.group(1) in ROMAN else None
    if n is None:
        return x
    rest = x[m.end():].strip()
    if corps and _re.match(r"(?i)^(army\s+)?corps\b", rest) and n <= len(ROMAN):
        return ROMAN[n - 1] + " Corps" + _re.sub(r"(?i)^(army\s+)?corps", "", rest)
    return sfx(n) + (" " + rest if rest else "")


def backdrop(out, evs):
    """viewer/war/data/backdrop.json for the timeline: the hand-checked political, social and command events of
    data/manual/backdrop.psv (level 1 shown at whole-war zoom, 2 at a year or so, 3 at a few months), and the CWSAC
    battles (class A with 7,000+ casualties -> 1; other A, and B with 1,500+ -> 2; other B and C -> 3; D left out).
    {"items": [[day0, day1, kind, level, title, note, url]]}"""
    import csv
    from urllib.parse import quote
    items = []
    src = Path(__file__).resolve().parent.parent / "data" / "manual" / "backdrop.psv"
    if src.exists():
        for r in csv.DictReader(open(src, encoding="utf-8"), delimiter="|"):
            a = date.fromisoformat(r["start"]); b = date.fromisoformat(r["end"]) if r["end"] else a
            url = "https://en.wikipedia.org/wiki/" + quote(r["wikipedia"].replace(" ", "_")) if r["wikipedia"] else ""
            items.append([(a - D0).days, (b - D0).days, r["kind"], int(r["level"]), r["title"], r["note"], url])
    # battles: the NPS Civil War Sites Advisory Commission classes (A decisive ... D limited) and casualties, a ranking
    # independent of how many units our sources happen to list
    cw = Path(__file__).resolve().parent.parent / "data" / "external" / "acw_battle_data" / "cwsac_battles.csv"
    ORDW = {"I": "First", "II": "Second", "III": "Third", "IV": "Fourth"}
    for r in (csv.DictReader(open(cw, encoding="utf-8")) if cw.exists() else []):
        sig = r["significance"]
        try:
            cas = int(float(r["casualties"] or 0))
        except ValueError:
            cas = 0
        if sig not in "ABC" or not r["start_date"]:
            continue
        lv = 1 if sig == "A" and cas >= 7000 else 2 if sig == "A" or (sig == "B" and cas >= 1500) else 3
        nm = r["battle_name"]
        m = __import__("re").match(r"^(.*?),? (First|Second|Third|Fourth|I|II|III|IV)$", nm)
        if m:
            nm = ORDW.get(m.group(2), m.group(2)) + " " + m.group(1)
        a = date.fromisoformat(r["start_date"][:10]); b = date.fromisoformat((r["end_date"] or r["start_date"])[:10])
        note = f"NPS class {sig} ({'decisive' if sig == 'A' else 'major' if sig == 'B' else 'formative'})" + (f"; about {cas:,} casualties" if cas else "")
        items.append([(a - D0).days, (b - D0).days, "battle", lv, nm, note, r["url"]])
    import collections
    dup = collections.Counter(x[4] for x in items if x[2] == "battle")
    for x in items:
        if x[2] == "battle" and dup[x[4]] > 1:           # two CWSAC entries named "Petersburg": add the month
            x[4] += " (" + (D0 + timedelta(days=x[0])).strftime("%b %Y") + ")"
    items.sort(key=lambda x: (x[0], x[3]))
    # campaigns (CWSAC): dates from their battles' first and last days; level 1 with a class A battle, 2 with a class B,
    # 3 otherwise; theater E(astern), W(estern), T(rans-Mississippi), S (Lower Seaboard), P(acific)
    camps = defaultdict(list)
    for r in (csv.DictReader(open(cw, encoding="utf-8")) if cw.exists() else []):
        if r["start_date"] and r["campaign"]:
            camps[r["campaign"]].append(r)
    cc = cw.parent / "cwsac_campaigns.csv"
    th = {r["campaign"]: r["theater"] for r in csv.DictReader(open(cc, encoding="utf-8"))} if cc.exists() else {}
    campaigns = []
    for name, rs in camps.items():
        sig = [r["significance"] for r in rs]
        if not any(x in "ABC" for x in sig):
            continue
        a = min(date.fromisoformat(r["start_date"][:10]) for r in rs)
        b = max(date.fromisoformat((r["end_date"] or r["start_date"])[:10]) for r in rs)
        lv = 1 if "A" in sig else 2 if "B" in sig else 3
        short = __import__("re").sub(r"\s*\[[^\]]*\]$", "", name)
        campaigns.append([(a - D0).days, (b - D0).days, lv, short, (th.get(name) or "?")[0], sig.count("A"), len(rs)])
    campaigns.sort()
    json.dump({"items": items, "campaigns": campaigns}, open(out / "backdrop.json", "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print("campaigns:", len(campaigns))
    print("backdrop items:", len(items), "battles:", sum(1 for x in items if x[2] == "battle"))


def locate(segs, day, Y):
    """The viewer's locate() (index.html): [lat, lon, state] on a day, or None. state 4 = with its brigade or campaign."""
    import bisect
    starts = Y["_starts"].get(id(segs))
    if starts is None:
        starts = Y["_starts"][id(segs)] = [s[0] for s in segs]
    i = bisect.bisect_right(starts, day) - 1
    if i >= 0 and segs[i][0] <= day <= segs[i][1]:
        f = Y["fixes"][segs[i][2]]
        return f[0] / 1e4, f[1] / 1e4, 4 if f[4] >= 2 else 3 if f[4] else 0
    prev = segs[i] if i >= 0 else None
    nxt = segs[i + 1] if i + 1 < len(segs) else None
    if prev and nxt and nxt[0] - prev[1] <= 21:
        a, b = Y["fixes"][prev[2]], Y["fixes"][nxt[2]]
        w = (day - prev[1]) / (nxt[0] - prev[1])
        return (a[0] + w * (b[0] - a[0])) / 1e4, (a[1] + w * (b[1] - a[1])) / 1e4, 1
    if prev and day - prev[1] <= 10:
        a = Y["fixes"][prev[2]]
        return a[0] / 1e4, a[1] / 1e4, 2
    return None


def activity(out, min_km=8):
    """viewer/war/data/activity.json for the timeline's activity strip: per day, how many Union and Confederate units
    were placed (all kinds) and how many moved min_km or more since the day before, as the map draws them (8 km: the trails' threshold).
    {"min_km": 8, "days": [[union_placed, conf_placed, union_moved, conf_moved], ...]} from 1861-01-01."""
    units = json.load(open(out / "units.json", encoding="utf-8"))["units"]
    side = {int(k): v[1] for k, v in units.items()}
    years = {}
    for y in range(1861, 1866):
        Y = json.load(open(out / f"y{y}.json", encoding="utf-8"))
        Y["_starts"] = {}
        years[y] = Y
    nd = (date(1865, 12, 31) - D0).days + 1
    days = [[0, 0, 0, 0] for _ in range(nd)]
    for d in range(nd):
        Y = years[(D0 + timedelta(days=d)).year]
        Yp = years[(D0 + timedelta(days=d - 1)).year] if d else None
        for uid, segs in Y["seg"].items():
            sd = side.get(int(uid))
            if sd is None:
                continue
            p = locate(segs, d, Y)
            if not p:
                continue
            days[d][sd] += 1
            sp = Yp["seg"].get(uid) if Yp else None
            q = locate(sp, d - 1, Yp) if sp else None
            if q and km(p[:2], q[:2]) >= min_km:
                days[d][2 + sd] += 1
    json.dump({"min_km": min_km, "days": days}, open(out / "activity.json", "w"), separators=(",", ":"))
    print("activity: peak moved", max(x[2] + x[3] for x in days))


def main(dbp, outdir):
    out = Path(outdir)
    db = sqlite3.connect(dbp)
    fixes = defaultdict(list)
    stitle = {i: (t, k, u) for i, t, k, u in db.execute("SELECT id, title, kind, url FROM source")}
    cites = {}
    def cite(sid, loc, by):
        """Short citation for the map's source panel: (text, url), shared by key."""
        t, k, u = stitle.get(sid, ("", "", None))
        loc, by = loc or "", by or ""
        how = ("order of battle" if "or_org" in by or "oob" in by else "letter heading" if "datelines" in by else
               "station list" if "stations" in by else "units engaged" if "nps_battle" in by else
               "battle list" if "infobox" in by else "monument" if ("osm:" in by or "battle_monuments" in by) else "brigade record" if "brigade" in by else "")
        if k == "compendium":
            txt = "Dyer's Compendium" + (", " + loc if loc.startswith("p.") else "")
        elif k == "official_records":
            txt = t.replace("Official Records, Ser. I, ", "Official Records, ") if t.startswith("Official Records") else "Official Records"
            m = __import__("re").search(r"\((warofrebellion\w+):", loc)
            if m:
                u = "https://archive.org/details/" + m.group(1)
        elif k == "website":
            txt = t.replace("Wikipedia: ", "Wikipedia, ")
        elif k == "government_list":
            txt = "NPS Soldiers and Sailors Database"
        else:
            txt = t
        if how and how not in txt:
            txt += " (" + how + ")"
        if how == "monument":                      # link to the monument's own record
            if loc.startswith("http"):
                u = loc
            elif __import__("re").match(r"(node|way|relation)/\d+$", loc):
                u = "https://www.openstreetmap.org/" + loc
        if by.endswith(":namesake"):
            txt += "; regiment number shared, resolved by brigade"
        key = (txt, u or "")
        return cites.setdefault(key, key)
    for uid, ds, de, prec, lat, lon, pm, name, sk, conf, pres, por, sid, loc, by in db.execute("""
            SELECT u.unit_id, u.date_start, u.date_end, u.date_precision, p.lat, p.lon, p.precision_m, p.display_name,
                   s.kind, c.confidence, u.presence, u.portion, c.source_id, c.locator, c.extracted_by
            FROM claim_unit_at u JOIN place p ON p.id=u.place_id JOIN claim c ON c.id=u.claim_id JOIN source s ON s.id=c.source_id
            WHERE u.unit_id IS NOT NULL AND p.lat IS NOT NULL AND u.date_start IS NOT NULL"""):
        a, b = d(ds), d(de or ds, True)
        if not a or not b or b < a:
            continue
        if pres in ("en_route", "along") and b > a:
            a = b
        fixes[uid].append((a, b, prec == "day", lat, lon, pm or 5000, name, RANK.get(sk, 1), conf, por in (None, "whole"), False, None, cite(sid, loc, by)))
    evloc = {}
    for eid, lat, lon, pm, name in db.execute("""SELECT e.event_id, p.lat, p.lon, p.precision_m, e.event_mention FROM claim_event_at e
                                                 JOIN place p ON p.id=e.place_id WHERE p.lat IS NOT NULL"""):
        evloc.setdefault(eid, (lat, lon, pm or 3000, name))
    ename = dict(db.execute("SELECT id, display_name FROM event"))
    ekind = dict(db.execute("SELECT id, kind FROM event"))
    siege = lambda eid: ekind.get(eid) == "siege" or "siege" in (ename.get(eid) or "").lower()
    for uid, eid, ds, de, prec, sk, conf, por, sid, loc, by in db.execute("""
            SELECT p.unit_id, p.event_id, p.date_start, p.date_end, p.date_precision, s.kind, c.confidence, p.portion,
                   c.source_id, c.locator, c.extracted_by
            FROM claim_participated p JOIN claim c ON c.id=p.claim_id JOIN source s ON s.id=c.source_id
            WHERE p.unit_id IS NOT NULL AND p.event_id IS NOT NULL AND p.date_start IS NOT NULL"""):
        if eid not in evloc:
            continue
        a, b = d(ds), d(de or ds, True)
        if not a or not b or b < a or ((b - a).days > 20 and not siege(eid)):
            continue                    # a campaign is not a position; a siege is (the lines stayed put)
        lat, lon, pm, _ = evloc[eid]
        fixes[uid].append((a, b, prec == "day" and (b - a).days <= 20, lat, lon, pm, ename.get(eid) or "", RANK.get(sk, 1) + 1, conf,
                           por in (None, "whole"), siege(eid), None, cite(sid, loc, by)))
    # sweep: best fix per day, then runs
    segs = {}
    for uid, fx in fixes.items():
        fx = [f for f in fx if f[1] >= D0 and f[0] <= D1]
        if not fx:
            continue
        key = lambda f: (f[5] >= 10000, not f[2], (f[1] - f[0]).days > 3, f[5] > 500, not f[9], -f[7], -f[8], (f[1] - f[0]).days, f[5])
        fx.sort(key=key)
        lo = max(min(f[0] for f in fx), D0); hi = min(max(f[1] for f in fx), D1)
        n = (hi - lo).days + 1
        best = [None] * n
        for i, f in enumerate(fx):                 # best first: fill only empty days
            a, b = max(f[0], lo), min(f[1], hi)
            for k in range((a - lo).days, (b - lo).days + 1):
                if best[k] is None:
                    best[k] = i
        runs, k = [], 0
        while k < n:
            if best[k] is None:
                k += 1; continue
            j = k
            while j + 1 < n and best[j + 1] == best[k]:
                j += 1
            f = fx[best[k]]
            runs.append(((lo - D0).days + k, (lo - D0).days + j, f))
            k = j + 1
        segs[uid] = runs
    derived = derive(db, segs, fixes_by_event_dates(db, evloc, ename), D0)
    for uid, runs in derived.items():
        segs.setdefault(uid, []).extend(runs)
        segs[uid].sort(key=lambda r: r[0])
    units = {}
    for uid, name, side, br, ech in db.execute("""SELECT u.id, u.display_name, s.name, u.branch, u.echelon FROM unit u
                                                 JOIN side s ON s.id=u.side_id"""):
        if uid in segs:
            units[uid] = [pretty(name), 0 if side == "Union" else 1, br or "", ech]
    json.dump({"start": D0.isoformat(), "units": units}, open(out / "units.json", "w", encoding="utf-8"), separators=(",", ":"))
    # brigade placements (order-of-battle) for brigade lines on battlefields
    brig = defaultdict(list)
    for uid, pm, pj, ds in db.execute("""SELECT x.unit_id, x.parent_mention, x.parent_path_json, x.date_start FROM claim_subordinate_to x
            JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE s.kind IN ('website','official_records') AND x.unit_id IS NOT NULL AND x.date_start IS NOT NULL ORDER BY x.date_start"""):
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            p = {}
        b = (p.get("brigade") or "").strip()
        if b and d(ds):
            brig[uid].append(((d(ds) - D0).days, " / ".join(x for x in (canon(b), canon(p.get("division")), canon(p.get("corps"), True)) if x)[:120]))
    # events with a location and a short span
    evs = []
    for eid, nm in ename.items():
        if eid not in evloc:
            continue
        r = db.execute("SELECT MIN(date_start), MAX(COALESCE(date_end, date_start)), COUNT(DISTINCT unit_id) FROM claim_participated WHERE event_id=?", (eid,)).fetchone()
        a, b = d(r[0]), d(r[1], True)
        if not a or not b or (b - a).days > 20 or r[2] < 2:
            continue
        lat, lon, _, _ = evloc[eid]
        evs.append((eid, nm, (a - D0).days, (b - D0).days, round(lat * 1e4), round(lon * 1e4), r[2]))
    sizes = {}
    for y in range(1861, 1866):
        y0, y1 = (date(y, 1, 1) - D0).days - 30, (date(y, 12, 31) - D0).days + 30   # margin for interpolation across the year edge
        labels, lab_i, fixtab, fix_i, seg, srcs, src_i = [], {}, [], {}, {}, [], {}
        for uid, runs in segs.items():
            rs = [r for r in runs if r[1] >= y0 and r[0] <= y1]
            if not rs:
                continue
            out_r = []
            for a, b, f in rs:
                if f[6] not in lab_i:
                    lab_i[f[6]] = len(labels); labels.append(f[6][:70])
                loose = f[11] if f[11] is not None else (0 if (f[2] or f[10] or (f[1] - f[0]).days <= 31) else 1)   # a siege's lines are a real position
                si = -1
                if f[12]:
                    if f[12] not in src_i:
                        src_i[f[12]] = len(srcs); srcs.append(list(f[12]))
                    si = src_i[f[12]]
                fk = (round(f[3] * 1e4), round(f[4] * 1e4), int(f[5]), lab_i[f[6]], loose, si)
                if fk not in fix_i:
                    fix_i[fk] = len(fixtab); fixtab.append(list(fk))
                out_r.append([a, b, fix_i[fk]])
            seg[uid] = out_r
        bri = {u: [[dd, lb] for dd, lb in v if y0 - 365 <= dd <= y1] for u, v in brig.items() if u in seg}
        bri = {u: v for u, v in bri.items() if v}
        ev = [list(e) for e in evs if e[3] >= y0 and e[2] <= y1]
        doc = {"year": y, "labels": labels, "fixes": fixtab, "srcs": srcs, "seg": seg, "brig": bri, "events": ev}
        p = out / f"y{y}.json"
        json.dump(doc, open(p, "w", encoding="utf-8"), separators=(",", ":"))
        sizes[y] = (len(seg), len(fixtab), len(ev), p.stat().st_size)
    backdrop(out, evs)
    activity(out)
    print("units with positions:", len(units))
    for y, (nu, nf, ne, sz) in sizes.items():
        print(f"  {y}: units {nu}, fixes {nf}, events {ne}, {sz/1e6:.1f} MB")


if __name__ == "__main__":
    main(*sys.argv[1:])
