"""Infer participation from brigade companions.

Orders of battle (Official Records, Wikipedia) place a unit in a brigade at a date. When two placements of the
same unit share most of their companions (Jaccard >= 0.4 over the other units), the unit is taken to have stayed
in that brigade between them. If, inside that stretch, an event has participation claims from enough of the
stable companions (at least 2, and at least half of them) and the unit has no claim for the event, for any
event inside it, or for anything else on those days (within 2 days), a participated claim is inferred: source "Pipeline inference: brigade companions", confidence
0.5, with the companions in the note. Also inferred within 45 days of a single placement when the companions
come from that same placement.

Only units with no Dyer's record (in practice Confederate units) get inferred claims.

Runs on a built database (in place; replaces its own earlier claims).
Usage: python pipeline/brigade_inference.py civil_war.db [report.txt]
"""
import json, re, sqlite3, sys, time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import parse_date as d  # noqa: E402

TITLE = "Pipeline inference: brigade companions (brigade_inference.py)"
GAP = timedelta(days=270)        # longest stretch between two placements bridged
NEAR = timedelta(days=45)        # around a single placement


def bkey(path_json, mention):
    try:
        p = json.loads(path_json or "{}")
    except ValueError:
        p = {}
    b = p.get("brigade") or mention or ""
    return re.sub(r"\s+", " ", b).strip().lower()


def main(dbp, rep=None):
    db = sqlite3.connect(dbp)
    cur = db.cursor()
    old = [r[0] for r in cur.execute("SELECT id FROM source WHERE title=?", (TITLE,))]
    if old:
        cur.execute(f"DELETE FROM claim_participated WHERE claim_id IN (SELECT id FROM claim WHERE source_id IN ({','.join(map(str, old))}))")
        cur.execute(f"DELETE FROM claim WHERE source_id IN ({','.join(map(str, old))})")
        cur.execute(f"DELETE FROM source WHERE id IN ({','.join(map(str, old))})")
    # placements -> brigade snapshots: (source, table/article, brigade) at a date
    snaps = defaultdict(lambda: {"units": set(), "date": None, "picked": set()})
    for sid, loc, uid, pm, pj, ds, xb in cur.execute("""
            SELECT c.source_id, c.locator, x.unit_id, x.parent_mention, x.parent_path_json, x.date_start, c.extracted_by
            FROM claim_subordinate_to x JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE s.kind IN ('official_records','website') AND x.unit_id IS NOT NULL AND x.date_start IS NOT NULL"""):
        b = bkey(pj, pm)
        if not b or not re.search(r"brigade|legion", b + " " + (pm or "").lower()):
            continue
        k = (sid, loc.split(" (")[0] if loc else "", b, ds[:10])
        snaps[k]["units"].add(uid)
        snaps[k]["date"] = d(ds)
        if "namesake" in (xb or ""):
            snaps[k]["picked"].add(uid)     # in this brigade by a namesake pick, not by the source's own text
    by_unit = defaultdict(list)
    for k, s in snaps.items():
        if len(s["units"]) >= 3:
            for u in s["units"]:
                by_unit[u].append((s["date"], s["units"], u in s["picked"]))
    # participation (not inferred), events with dates
    part = defaultdict(set)
    busy_days = defaultdict(set)    # unit -> days (+-2) of its dated claims: a unit already somewhere is not inferred
    ev_dates = defaultdict(list)
    for uid, eid, ds, de in cur.execute("""SELECT p.unit_id, p.event_id, p.date_start, p.date_end FROM claim_participated p
                                       WHERE p.unit_id IS NOT NULL AND p.event_id IS NOT NULL"""):
        part[uid].add(eid)
        if ds:
            a, b = d(ds), d(de) or d(ds)
            if b - a <= timedelta(days=14):
                busy_days[uid].update(range(a.toordinal() - 2, b.toordinal() + 3))
        if ds:
            ev_dates[eid].append(ds[:10])
    evd = {}
    for e, ds in ev_dates.items():
        c = Counter(ds).most_common(1)[0][0]
        evd[e] = d(c)
    kind = dict(cur.execute("SELECT id, kind FROM event"))
    children = defaultdict(set)
    for e, p in cur.execute("SELECT id, parent_event_id FROM event WHERE parent_event_id IS NOT NULL"):
        children[p].add(e)
    def below(e, depth=0):
        out = set(children.get(e, ()))
        if depth < 4:
            for c in list(out):
                out |= below(c, depth + 1)
        return out
    who = defaultdict(set)          # event -> units with a claim
    for u, es in part.items():
        for e in es:
            who[e].add(u)
    ev_by_month = defaultdict(set)
    for e, x in evd.items():
        if x and kind.get(e) in ("battle", "engagement", "siege", "campaign", "operation", "expedition", "other"):
            ev_by_month[(x.year, x.month)].add(e)
    def events_between(a, b):
        out, m = set(), date(a.year, a.month, 1)
        while m <= b:
            out |= {e for e in ev_by_month.get((m.year, m.month), ()) if a <= evd[e] <= b}
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        return out

    # units with a Dyer's record are left alone: on the test set's complete Union keys only about a third of
    # brigade inferences were right (Dyer's omissions are mostly real: detached, on furlough, mustered out)
    has_dyer = {r[0] for r in cur.execute("""SELECT DISTINCT p.unit_id FROM claim_participated p JOIN claim c ON c.id=p.claim_id
                                             JOIN source s ON s.id=c.source_id WHERE s.kind='compendium'""")}
    inferred = {}
    for u, ss in by_unit.items():
        if u in has_dyer:
            continue
        ss.sort(key=lambda x: x[0])
        stretches = []
        for i, (t1, m1, p1) in enumerate(ss):
            stretches.append((t1 - NEAR, t1 + NEAR, m1 - {u}, p1))
            if i + 1 < len(ss):
                t2, m2, p2 = ss[i + 1]
                a, b = m1 - {u}, m2 - {u}
                if a and b and len(a & b) / len(a | b) >= 0.4 and t2 - t1 <= GAP:
                    stretches.append((t1, t2, a & b, p1 or p2))
        mine = set(part.get(u, ()))
        covered = set(mine)
        for e in mine:
            covered |= below(e)
        for a, b, comp, picked in stretches:
            if len(comp) < 2:
                continue
            for e in events_between(a, b):
                if e in covered or e in inferred.get(u, {}):
                    continue
                with_e = comp & who[e]
                if not (len(with_e) >= 2 and len(with_e) * 2 >= len(comp)):
                    continue
                if evd[e].toordinal() in busy_days.get(u, ()):
                    continue                      # already placed at something on those days (often the same battle under another name)
                if below(e) & mine:
                    continue                      # the unit has a battle inside this campaign already
                inferred.setdefault(u, {})[e] = (len(with_e), len(comp), picked)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cur.execute("INSERT INTO source(title, kind, citation, fetched_at, public_domain, notes) VALUES (?,?,?,?,?,?)",
                (TITLE, "manual", "Brigade placements in the Official Records and Wikipedia orders of battle", now, 1,
                 "A unit is inferred at an event most of its stable brigade companions were at"))
    sid = cur.lastrowid
    names = dict(cur.execute("SELECT id, display_name FROM event"))
    n = 0
    for u, es in inferred.items():
        for e, (k, m, picked) in es.items():
            ds = evd[e].isoformat()
            # ':namesake' when the unit's place in the brigade came from a namesake pick: resolve_namesakes.py does not
            # count it as evidence on the next build (counted, it made picks flip between builds)
            cur.execute("""INSERT INTO claim(claim_type, source_id, source_span, confidence, extracted_by, extracted_at, status, review_note, locator)
                           VALUES ('participated', ?, ?, 0.5, ?, ?, 'pending', ?, ?)""",
                        (sid, f"{k} of {m} brigade companions at {names.get(e)}",
                         "inference:brigade_v1" + (":namesake" if picked else ""), now,
                         "inferred from brigade companions; check", f"event {e}"))
            cur.execute("""INSERT INTO claim_participated(claim_id, unit_mention, unit_id, event_mention, event_id, portion, date_start, date_end, date_precision)
                           VALUES (?, ?, ?, ?, ?, 'whole', ?, ?, 'day')""", (cur.lastrowid, str(u), u, names.get(e) or "", e, ds, ds))
            n += 1
    db.commit()
    msg = [f"brigade snapshots: {sum(1 for s in snaps.values() if len(s['units']) >= 3)}; units placed: {len(by_unit)}",
           f"inferred participated claims: {n} for {len(inferred)} units"]
    side = dict(cur.execute("SELECT u.id, s.name FROM unit u JOIN side s ON s.id=u.side_id"))
    c = Counter(side.get(u) for u, es in inferred.items() for _ in es)
    msg.append(f"by side: {dict(c)}")
    print("\n".join(msg))
    if rep:
        open(rep, "w", encoding="utf-8").write("\n".join(msg) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
