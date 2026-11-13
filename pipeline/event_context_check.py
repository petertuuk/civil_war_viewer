"""Move events that were geocoded to the wrong namesake town, using where their own units were.

For each event located by geocoding a name (claim_event_at from pipeline:geocode or pipeline:merge_events, with fewer
than 20 participating units), the context is where its participating units were within 3 days of the event from
OTHER evidence: one-day unit_at claims located to 10 km or better (not letter headings, which place whole commands;
not 'context' place estimates) and their other
located events of <= 3 days that are themselves trustworthy (anchored, or 20+ units). Tier 2, when no unit has such
context: their other small geocoded events, for a move only, with 3+ units agreeing (2 moved Salem, Va. to Indiana). Each unit contributes the median of its positions. If at least 2 units (or 1 unit with
2+ positions) have a context and all of them (80% when 5 or more) are over 250 km from the event, the event is misplaced:
  - the same name (the event's place name, else the event name's place words) in GNIS, any state, within 80 km of
    the units' median -> the event is moved there (new place row, precision 3 km);
  - otherwise it is only flagged in the csv: removing locations was tried and took out correct ones (units moved
    fast by rail: the 171st Ohio was at Johnson's Island two days before Cynthiana).
Every change is written to the override table (target_table 'claim_event_at') and to data/scores/event_relocations.csv.
Runs on the built database (rebuild.sh db stage, after build_db).
Usage: python pipeline/event_context_check.py ~/db/civil_war.db data/external/gnis/gnis_index.tsv data/scores/event_relocations.csv
"""
import csv, math, re, sqlite3, statistics, sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gnis_index import norm  # noqa: E402
from common import km, gnis_by_name  # noqa: E402

FAR_KM, NEAR_KM, SHARE, WIN, MIN_T2 = 250, 80, 0.8, 3, 3   # WIN: days either side (units moved fast by rail)
CLASSES = {"Populated Place", "Locale", "Crossing", "Military", "Gap", "Summit", "Ridge", "Stream", "Island", "Civil"}


def d(s):
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def name_forms(place_name, event_name):
    out = []
    for n in (place_name, event_name):
        if not n:
            continue
        n = re.sub(r"\(.*?\)|,.*$", "", n)
        n = re.sub(r"(?i)^(battle|siege|skirmish|action|affair|engagement|scout|expedition|reconnaissance|reconnoissance|"
                   r"operations?|combat|attack|capture|near|at|on|of|to|from|the|and|in)\b\s*", "", n)
        n = re.sub(r"(?i)^(battle|siege|skirmish|action|affair|engagement|scout|expedition|reconnaissance|near|at|on|of|to|"
                   r"from|the)\b\s*", "", n)
        for part in re.split(r"(?i)\s+and\s+|\s*;\s*", n):
            f = norm(part.strip())
            short = re.sub(r"\s+(bridge|ford|ferry|church|station|road|creek|river|landing|mills?|cross roads)$", "", f)
            if short != f and len(short) >= 4:
                out.append(short)
            if len(f) >= 4 and f not in out:
                out.append(f)
                out.append(re.sub(r"sburg$", "sville", f)) if f.endswith("sburg") else None
                out.append(re.sub(r"sville$", "sburg", f)) if f.endswith("sville") else None
    return [f for f in out if f]


STATE_ABBR = {"ala": "AL", "ark": "AR", "fla": "FL", "ga": "GA", "ky": "KY", "la": "LA", "md": "MD", "miss": "MS", "mo": "MO",
              "n. c": "NC", "s. c": "SC", "tenn": "TN", "tex": "TX", "va": "VA", "w. va": "WV", "pa": "PA", "ohio": "OH",
              "ind": "IN", "kans": "KS", "ind. ter": "OK", "n. mex": "NM", "ariz": "AZ"}
SAME = {"VA": {"VA", "WV"}, "WV": {"WV", "VA"}}


def written_state(name):
    m = re.search(r",\s*((?:w\. )?[a-z]{2,5}(?:\. [a-z])?(?:\. ter)?)\.?\s*$", (name or "").lower())
    return STATE_ABBR.get(m.group(1).strip()) if m else None


def main(db, gnis_p, out_p):
    c = sqlite3.connect(db)
    G = gnis_by_name(gnis_p, CLASSES)
    ev = {}            # event id -> (claim id, place id, name, place name, lat, lon, d0, d1, source)
    for cid, eid, en, pid, pn, la, lo, ds, de, how in c.execute("""
            select a.claim_id, e.id, e.display_name, p.id, p.display_name, p.lat, p.lon, a.date_start, a.date_end, k.extracted_by
            from claim_event_at a join event e on e.id=a.event_id join claim k on k.id=a.claim_id join place p on p.id=a.place_id
            where p.lat is not null"""):
        if d(ds):
            ev.setdefault(eid, (cid, pid, en, pn, la, lo, d(ds), d(de) or d(ds), how))
    # the database's own located places by name (Savage Station, Va. is there from the Seven Days even if GNIS lacks it)
    for pn_, st_, la_, lo_ in c.execute("select display_name, state, lat, lon from place where lat is not null and "
                                        "(precision_m is null or precision_m <= 5000)"):
        f_ = norm(re.sub(r"\(.*?\)|,.*$", "", pn_ or ""))
        if len(f_) >= 4:
            G[f_].append((st_ or "", la_, lo_, "database place"))
    units = defaultdict(set)
    for uid, eid in c.execute("select unit_id, event_id from claim_participated where unit_id is not null and event_id is not null"):
        units[eid].add(uid)
    # other evidence per unit: (day, lat, lon, event id or None)
    pos = defaultdict(list)
    pos2 = defaultdict(list)      # small geocoded events: second-tier context, only for moves agreed by 2+ units
    for uid, ds, de, la, lo, prec, how in c.execute("""
            select u.unit_id, u.date_start, u.date_end, p.lat, p.lon, p.precision_m, k.extracted_by from claim_unit_at u
            join claim k on k.id=u.claim_id join place p on p.id=u.place_id
            where u.unit_id is not null and p.lat is not null and u.date_precision='day'"""):
        a, b = d(ds), d(de) or d(ds)
        if a and b and (b - a).days <= 2 and "datelines" not in how and (prec or 0) <= 10000:
            pos[uid].append((a, la, lo, None))
    for eid, uids in units.items():
        e = ev.get(eid)
        # only trustworthy events as context: anchored (Wikidata, manual) or with 20+ units; a geocoded small event
        # may itself be a wrong namesake (Newport Bridge in the Keys made Natural Bridge look misplaced)
        if e and (e[7] - e[6]).days <= 3:
            trusted = e[8] not in ("pipeline:geocode", "pipeline:merge_events") or len(uids) >= 20
            for uid in uids:
                (pos if trusted else pos2)[uid].append((e[6], e[4], e[5], eid))
    rows, stats = [], defaultdict(int)
    now = datetime.utcnow().isoformat(timespec="seconds")
    for eid, (cid, pid, en, pn, la, lo, d0, d1, how) in ev.items():
        if how not in ("pipeline:geocode", "pipeline:merge_events") or len(units[eid]) >= 20:
            continue
        ctxs = []
        for uid in units[eid]:
            ps = [(p[1], p[2]) for p in pos[uid] if p[3] != eid and d0 - timedelta(WIN) <= p[0] <= d1 + timedelta(WIN)]
            if ps:
                ctxs.append(((statistics.median(p[0] for p in ps), statistics.median(p[1] for p in ps)), len(ps)))
        tier = 1
        if not ctxs:
            tier = 2
            for uid in units[eid]:
                ps = [(p[1], p[2]) for p in pos2[uid] if p[3] != eid and d0 - timedelta(WIN) <= p[0] <= d1 + timedelta(WIN)]
                if ps:
                    ctxs.append(((statistics.median(p[0] for p in ps), statistics.median(p[1] for p in ps)), len(ps)))
            if len(ctxs) < MIN_T2:
                continue
        if not ctxs or (len(ctxs) == 1 and ctxs[0][1] < 2):
            continue
        stats["events with unit context"] += 1
        far = [x for x in ctxs if km(x[0], (la, lo)) > FAR_KM]
        if len(far) < len(ctxs) if len(ctxs) <= 4 else len(far) / len(ctxs) < SHARE:
            continue                                 # units disagree (namesake units mixed in): leave the event
        mid = (statistics.median(x[0][0] for x in ctxs), statistics.median(x[0][1] for x in ctxs))
        named = written_state(en)
        best = None
        for f in name_forms(pn, en):
            for st, a, b, cl in G.get(f, []):
                if named and st and st not in SAME.get(named, {named}):
                    continue                         # "Expedition to Charleston, W. Va." stays in West Virginia
                dk = km(mid, (a, b))
                if dk <= NEAR_KM and (best is None or dk < best[0]):
                    best = (dk, st, a, b, cl, f)
        if best:
            stats["moved to a namesake near its units"] += 1
            c.execute("INSERT INTO place(display_name, kind, state, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?,?)",
                      (pn, "town", best[1], best[2], best[3], 3000,
                       f"event_context_check: GNIS '{best[5]}' ({best[4]}, {best[1]}) {best[0]:.0f} km from the event's units"))
            new = c.execute("select last_insert_rowid()").fetchone()[0]
            c.execute("UPDATE claim_event_at SET place_id=? WHERE claim_id=?", (new, cid))
            act = f"moved to {best[1]} ({best[2]:.4f},{best[3]:.4f})" + (" [tier 2]" if tier == 2 else "")
        elif True:                                  # removal tried 2026-11-12: removed right ones (Cynthiana, Blain's X Roads)
            stats["left alone: one unit only, or the event names its state (see csv)"] += 1
            rows.append([eid, en, d0.isoformat(), pn, round(la, 4), round(lo, 4), "flagged only",
                         f"{len(far)}/{len(ctxs)} units over {FAR_KM} km away"])
            continue
        else:
            stats["location removed (no namesake near its units)"] += 1
            c.execute("UPDATE claim_event_at SET place_id=NULL WHERE claim_id=?", (cid,))
            act = "location removed"
        dist = statistics.median(km(x[0], (la, lo)) for x in ctxs)
        reason = f"{len(far)}/{len(ctxs)} units over {FAR_KM} km away within {WIN} day (median {dist:.0f} km)"
        c.execute("INSERT INTO override(target_table, target_id, field, value, reason, created_at) VALUES (?,?,?,?,?,?)",
                  ("claim_event_at", cid, "place_id", act, "event_context_check: " + reason, now))
        rows.append([eid, en, d0.isoformat(), pn, round(la, 4), round(lo, 4), act, reason])
    c.commit()
    with open(out_p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "event", "date", "place", "lat", "lon", "action", "reason"])
        w.writerows(sorted(rows, key=lambda r: r[2]))
    print(dict(stats))


if __name__ == "__main__":
    main(*sys.argv[1:])
