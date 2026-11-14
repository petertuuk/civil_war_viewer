"""Impossibility checks on civil_war.db and one review queue for everything that needs a person.

Checks (no answer key needed):
  outside_service  a claim from the Official Records, Wikipedia or NPS puts a unit in an event more than
                   30 days before its first or after its last dated Dyer's entry (organized ... mustered out):
                   usually the wrong unit linked (a 3-month regiment for its 3-year namesake) or a misdated event
  two_places       one unit, whole, in two events on the same days more than 150 km apart (events with coordinates)
  two_brigades     placements within 90 days in brigades that share no unit (brigades only, no low-confidence
                   rows): two namesakes linked to one unit (Maney's and Turney's 1st Tennessee), a transfer or
                   reorganization, or a parsing error
  part_of_dates    a membership claim whose member falls outside its container's dates
  fast_jump        rows of data/scores/fast_jumps.csv (pipeline/fast_jumps.py) with a likely wrong end, by place

Review queue (data/scores/review_queue.csv), largest first by claims affected:
  the checks above, OCR flags left unresolved, Dyer's year segments fix_years.py would not move,
  AI-resolved event clusters marked for review (data/ai/review_queue.csv), and test-set misses.

Usage: python pipeline/consistency_checks.py civil_war.db . data/scores/consistency.txt data/scores/review_queue.csv
"""
import csv, json, math, re, sqlite3, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from common import km  # noqa: E402


def d(s):
    if not s:
        return None
    try:
        p = [int(x) for x in s[:10].split("-")]
        return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)
    except ValueError:
        return None


def main(dbp, root, out_txt, out_csv):
    root = Path(root)
    db = sqlite3.connect(dbp)
    unit_name = dict(db.execute("SELECT id, display_name FROM unit"))
    ev_name = dict(db.execute("SELECT id, display_name FROM event"))
    dyer_src = {r[0] for r in db.execute("SELECT id FROM source WHERE kind='compendium'")}
    q = []                          # review queue rows
    rep = []

    # ---- service windows from Dyer's
    win = {}
    for uid, lo, hi in db.execute(f"""
        SELECT x.unit_id, MIN(x.ds), MAX(COALESCE(x.de, x.ds)) FROM (
          SELECT p.unit_id, p.date_start ds, p.date_end de, c.source_id s FROM claim_participated p JOIN claim c ON c.id=p.claim_id
          UNION ALL
          SELECT u.unit_id, u.date_start, u.date_end, c.source_id FROM claim_unit_at u JOIN claim c ON c.id=u.claim_id) x
        WHERE x.unit_id IS NOT NULL AND x.ds IS NOT NULL AND x.s IN ({','.join(map(str, dyer_src))}) GROUP BY x.unit_id"""):
        win[uid] = (d(lo), d(hi))
    out = []
    for cid, uid, eid, ds, de, title, kind in db.execute("""
        SELECT c.id, p.unit_id, p.event_id, p.date_start, p.date_end, s.title, s.kind
        FROM claim_participated p JOIN claim c ON c.id=p.claim_id JOIN source s ON s.id=c.source_id
        WHERE p.unit_id IS NOT NULL AND p.date_start IS NOT NULL AND s.kind IN ('official_records','website','government_list')
          AND s.title NOT LIKE 'Wikidata%'"""):
        w = win.get(uid)
        a, b = d(ds), d(de) or d(ds)
        if not w or not a or not w[0]:
            continue
        if b < w[0] - timedelta(days=30) or a > w[1] + timedelta(days=30):
            out.append((uid, eid, ds, title, w))
    by_u = defaultdict(list)
    for r in out:
        by_u[r[0]].append(r)
    rep += [f"outside_service: {len(out)} claims for {len(by_u)} units"]
    for uid, rs in sorted(by_u.items(), key=lambda x: -len(x[1])):
        w = rs[0][4]
        q.append(("outside_service", unit_name.get(uid), len(rs),
                  f"Dyer's service {w[0]}..{w[1]}; e.g. {ev_name.get(rs[0][1]) or '?'} {rs[0][2]} ({rs[0][3][:40]})"
                  + (f" +{len(rs) - 1} more" if len(rs) > 1 else "")))

    # ---- two places at once
    coord = {}
    for eid, lat, lon in db.execute("""SELECT e.event_id, p.lat, p.lon FROM claim_event_at e JOIN place p ON p.id=e.place_id
                                       WHERE p.lat IS NOT NULL"""):
        coord.setdefault(eid, (lat, lon))
    evd = {i: (d(a), d(b) or d(a)) for i, a, b in db.execute(
        "SELECT event_id, MIN(date_start), MAX(COALESCE(date_end, date_start)) FROM claim_participated WHERE event_id IS NOT NULL GROUP BY event_id")}
    per = defaultdict(set)
    for uid, eid, portion in db.execute("SELECT unit_id, event_id, portion FROM claim_participated WHERE unit_id IS NOT NULL AND event_id IS NOT NULL"):
        if portion == "whole" and eid in coord:
            per[uid].add(eid)
    clash = []
    for uid, evs in per.items():
        evs = sorted((e for e in evs if evd.get(e, (None,))[0] and (evd[e][1] - evd[e][0]).days <= 3), key=lambda e: evd[e][0])
        for i, e1 in enumerate(evs):
            for e2 in evs[i + 1:]:
                if evd[e2][0] > evd[e1][1]:
                    break
                dist = km(coord[e1], coord[e2])
                if dist > 150:
                    clash.append((uid, e1, e2, dist))
    rep += [f"two_places: {len(clash)} pairs for {len({c[0] for c in clash})} units"]
    for uid, e1, e2, dist in sorted(clash, key=lambda c: -c[3])[:400]:
        q.append(("two_places", unit_name.get(uid), 2,
                  f"{ev_name.get(e1)} {evd[e1][0]} and {ev_name.get(e2)} {evd[e2][0]}, {dist:.0f} km apart"))

    # ---- two brigades at once: a namesake mix-up (Maney's 1st Tennessee in the West, Turney's 1st Tennessee in
    # Virginia, both linked to one unit). Two placements within 90 days whose brigade companions share no unit.
    import brigade_inference as BI
    snaps = defaultdict(set)
    sd = {}
    for sid, loc, uid, pm, pj, ds in db.execute("""
            SELECT c.source_id, c.locator, x.unit_id, x.parent_mention, x.parent_path_json, x.date_start
            FROM claim_subordinate_to x JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE s.kind IN ('official_records','website') AND x.unit_id IS NOT NULL AND x.date_start IS NOT NULL
            AND c.confidence > 0.5"""):
        b = BI.bkey(pj, pm)
        # brigades only (as brigade_inference.py): districts, posts and "Miscellaneous" are not brigades; low-confidence
        # rows (two-column scramble) left out
        if not b or not re.search(r"brigade|legion", b + " " + (pm or "").lower()):
            continue
        k = (sid, (loc or "").split(" (")[0], b, ds[:10])
        snaps[k].add(uid); sd[k] = (d(ds), (loc or "").split(" (")[0])
    per_u = defaultdict(list)
    for k, us in snaps.items():
        if len(us) >= 4:
            for u in us:
                per_u[u].append((sd[k][0], us - {u}, sd[k][1]))
    jumps = []
    for u, ps in per_u.items():
        ps.sort(key=lambda x: x[0])
        for i, (t1, c1, s1) in enumerate(ps):
            for t2, c2, s2 in ps[i + 1:]:
                if t2 - t1 > timedelta(days=90):
                    break
                if not (c1 & c2):
                    jumps.append((u, t1, s1, t2, s2)); break
    ju = defaultdict(list)
    for j in jumps:
        ju[j[0]].append(j)
    rep += [f"two_brigades: {len(ju)} units placed in brigades with no common unit within 90 days (namesakes mixed up?)"]
    for u, js in sorted(ju.items(), key=lambda x: -len(x[1])):
        _, t1, s1, t2, s2 = js[0]
        q.append(("two_brigades", unit_name.get(u), len(js), f"{t1} {s1[:60]} vs {t2} {s2[:60]}" + (f" +{len(js) - 1} more" if len(js) > 1 else "")))

    # ---- membership dates
    bad = db.execute("""SELECT p.event_id, p.parent_event_id FROM claim_part_of p WHERE p.dates_ok = 0""").fetchall()
    rep += [f"part_of_dates: {len(bad)} membership claims with the member outside its container's dates"]
    for e, pe in bad:
        n = db.execute("SELECT COUNT(*) FROM claim_participated WHERE event_id=?", (e,)).fetchone()[0]
        q.append(("part_of_dates", None, n, f"{ev_name.get(e)} {evd.get(e, ('?',))[0]} in {ev_name.get(pe)} {evd.get(pe, ('?',))[0]}"))

    # ---- OCR flags
    flags = Counter()
    fp = root / "data/dyers/units_clean.flags.jsonl"
    if fp.exists():
        for l in open(fp, encoding="utf-8"):
            flags[json.loads(l)["unit_id"]] += 1
    rep += [f"ocr_flags: {sum(flags.values())} unresolved number disagreements in {len(flags)} units"]
    for u, n in flags.most_common():
        q.append(("ocr_flag", u, n, "numbers where OCR, NPS and Civil War Archive disagree; check the page image"))

    # ---- Dyer's year segments not moved
    yp = root / "data/dyers/fix_years_report.txt"
    ny = 0
    if yp.exists():
        for l in open(yp, encoding="utf-8"):
            if "NOT shifted" in l:
                ny += 1
                u, rest = l.split(": ", 1)
                q.append(("dyers_year", u, 1, rest.strip()))
    rep += [f"dyers_year: {ny} Dyer's stretches whose year a Wikidata match disputes but fix_years.py left alone"]

    # ---- AI clusters marked for review
    ap = root / "data/ai/review_queue.csv"
    na = 0
    if ap.exists():
        for r in csv.DictReader(open(ap, encoding="utf-8")):
            na += 1
            q.append(("ai_cluster", None, int(r.get("regiments") or 0),
                      f"{r['cluster_id']} {r['dyer_name']} {r['dates']}: {r.get('note') or r.get('confidence')}"))
    rep += [f"ai_cluster: {na} AI-resolved clusters marked for review"]

    # ---- fast jumps (pipeline/fast_jumps.py, run just before): the end that is likely wrong, grouped by place, so one
    # misplaced name (Fort Rice in Dakota for the one at Petersburg) is one row
    fp = root / "data/scores/fast_jumps.csv"
    nf = 0
    if fp.exists():
        grp = defaultdict(list)
        for r in csv.DictReader(open(fp, encoding="utf-8")):
            nf += 1
            if r["likely_wrong"] in ("a", "b"):
                e = r["likely_wrong"]
                grp[(r[f"{e}_place"], (re.findall(r"\[([^\]]+)\]", r[f"{e}_source"]) or ["?"])[-1])].append(r)
        for (place, how), rs in grp.items():
            r = rs[0]; e = r["likely_wrong"]; o = "b" if e == "a" else "a"
            q.append(("fast_jump", r["unit"] + (f" +{len({x['unit'] for x in rs}) - 1} units" if len(rs) > 1 else ""), len(rs),
                      f"{place} ({how}) {r[e + '_date']}: {r['km']} km from {r[o + '_place']} {r[o + '_date']}; "
                      f"{r[e + '_text'][:80]}"))
    rep += [f"fast_jump: {nf} steps over 300 km faster than 250 km/day (data/scores/fast_jumps.csv)"]

    # ---- test-set misses
    gp = root / "data/scores/gold_scores.txt"
    ng = 0
    if gp.exists():
        unit = None
        for l in open(gp, encoding="utf-8"):
            if l.startswith("## "):
                unit = l[3:].split(" (db")[0]
            elif l.strip().startswith(("MISSING", "WRONG-EV")):
                ng += 1
                q.append(("test_set", unit, 1, re.sub(r"\s+", " ", l.strip())))
    rep += [f"test_set: {ng} test-set lines missing or resolved to the wrong event"]

    # outside_state: a place said to be in a state but located outside it (2026-11-14: Boston, Mass. in Virginia)
    from common import in_state
    outside = []
    for pid, nm, st, la, lo, nc in db.execute("""SELECT p.id, p.display_name, p.state, p.lat, p.lon, COUNT(a.claim_id)
            FROM place p JOIN claim_unit_at a ON a.place_id = p.id WHERE p.lat IS NOT NULL AND p.state IS NOT NULL
            GROUP BY p.id"""):
        if in_state(st, la, lo) is False:
            outside.append((nc, nm, st, la, lo))
    outside.sort(reverse=True)
    rep += [f"outside_state: {len(outside)} places, {sum(o[0] for o in outside)} unit_at claims"]
    for nc, nm, st, la, lo in outside:
        q.append(("outside_state", None, nc, f"{nm}, {st} at {la:.3f},{lo:.3f}"))
    q.sort(key=lambda r: (-r[2], r[0]))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["check", "unit", "claims_affected", "detail"])
        w.writerows(q)
    kinds = Counter(r[0] for r in q)
    rep += ["", f"review queue: {len(q)} rows " + str(dict(kinds)), "", "Top outside_service:"]
    rep += [f"  {r[2]:3d}  {r[1]}: {r[3]}" for r in q if r[0] == "outside_service"][:25]
    rep += ["", "Top two_brigades:"] + [f"  {r[2]:3d}  {r[1]}: {r[3]}" for r in q if r[0] == "two_brigades"][:25]
    rep += ["", "Top two_places:"] + [f"  {r[1]}: {r[3]}" for r in q if r[0] == "two_places"][:25]
    open(out_txt, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("\n".join(rep[:8]))


if __name__ == "__main__":
    main(*sys.argv[1:])
