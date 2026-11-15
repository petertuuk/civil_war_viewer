"""Tell namesake regiments apart in the Official Records organization tables by their brigade-mates.

Many states raised two or more regiments of one number (Maney's and Turney's 1st Tennessee; the 1st Arkansas of
1861 and of 1862). parse_or_all.py marks a row it cannot decide AMBIGUOUS:<codes> (dropped downstream), and links some
rows to a namesake by a default (the code without a suffix). A brigade stayed together for months, so the right
namesake is the one that appears, in OTHER tables within 400 days, beside the same brigade-mates as this row.

Evidence comes from the database of the previous build (other sources: Wikipedia orders of battle and infoboxes,
NPS battle lists and histories, state histories, Dyer's): a namesake is "in service" at a date when its own claims
(3 or more) span it, give or take 180 days. If exactly one candidate is in service, it is taken unless its own
positions within 60 days are over 400 km from the row's brigade-mates (the famous 3rd Arkansas fought in Virginia;
a "3d Arkansas" in a western table is another unit). If several are, the
one whose own positions within 60 days lie within 200 km of the row's brigade-mates (their positions within 30 days)
is taken when every other one is 400 km or more away. A linked row is relinked when Wikipedia places its code in another brigade
then and exactly one namesake beside the row's brigade-mates (OR rows only), or when its code has no evidence around that date and
the pick is clear. (Brigade-mates alone were tried first: an ambiguous code never appears
linked, so it has no brigade history to compare.) Wikipedia orders of battle decide first: a candidate listed in a brigade with one of the row's brigade-mates within
180 days is taken (if it is the only such candidate); one listed then only in brigades without any of them is ruled
out. Evidence excludes claims made from earlier picks (or_to_claims tags
them ':namesake') and the post-line and letter-heading claims, which follow the tables: a wrong pick must not vouch
for itself on the next build. Low-confidence rows (two-column scramble) are left alone.

Rewrites data/or/placements.jsonl in place: unit_code_parsed keeps parse_or_all.py's answer, unit_code the result,
namesake_note the reason; a later run starts again from unit_code_parsed. Report: data/scores/namesakes_report.txt.
Wikipedia mode (the same tests on data/wikipedia/oob_placements.jsonl, checked against the OR tables' brigades; dates
from the battle each order of battle belongs to): add data/wikipedia/oob_battles.json data/events/events.jsonl.
Usage: python pipeline/resolve_namesakes.py data/or/placements.jsonl data/external/acw_battle_data/nps_units.csv \
    ~/db/civil_war.db data/scores/namesakes_report.txt
       python pipeline/resolve_namesakes.py data/wikipedia/oob_placements.jsonl data/external/acw_battle_data/nps_units.csv \
    ~/db/civil_war.db data/scores/namesakes_wikipedia.txt data/wikipedia/oob_battles.json data/events/events.jsonl
"""
import csv, json, math, re, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cwv import params  # noqa: E402
from common import km  # noqa: E402



def dn(s):
    try:
        return date.fromisoformat((s or "")[:10]).toordinal()
    except ValueError:
        return None


def base(code):
    return re.sub(r"\d\d$", "", code) if re.search(r"R[A-Z]?\d\d$", code) else code


def main(pl_p, units_p, db_p, rep_p, battles_p=None, events_p=None):
    wikimode = battles_p is not None          # Wikipedia order-of-battle rows (data/wikipedia/oob_placements.jsonl)
    names = {r["unit_code"]: r["unit_name"] for r in csv.DictReader(open(units_p, encoding="utf-8"))}
    groups = defaultdict(set)
    for c in names:
        groups[base(c)].add(c)
    rows = [json.loads(l) for l in open(pl_p, encoding="utf-8")]
    if wikimode:                              # a Wikipedia row: its article is the "table", its battle gives the date
        B = json.load(open(battles_p, encoding="utf-8"))
        E = {json.loads(l)["event_id"]: json.loads(l) for l in open(events_p, encoding="utf-8")}
        for r in rows:
            r["_table"] = r.get("title")
            r["_date"] = E.get(B.get(r.get("battle"), {}).get("event_id"), {}).get("date_start")
    else:
        for r in rows:
            r["_table"], r["_date"] = r["table_id"], r["date_start"]
    for r in rows:
        if "unit_code_parsed" in r:
            r["unit_code"] = r["unit_code_parsed"]; r.pop("namesake_note", None)
        else:
            r["unit_code_parsed"] = r.get("unit_code")
    key = lambda r: (r["_table"], r["side"], r.get("corps") or "", r.get("division") or "", r.get("brigade") or "")
    stats = Counter()

    def linked(r):
        c = r.get("unit_code") or ""
        return c and not c.startswith("AMB") and r.get("confidence") != "low"

    # evidence per unit code from the database: dated claims (any type) and located positions, other sources only
    import sqlite3, statistics
    c = sqlite3.connect(db_p)
    code_of = dict(c.execute("select entity_id, value from external_id where entity_type='unit' and scheme='nps'"))
    dates, pos = defaultdict(list), defaultdict(list)
    for uid, ds, how in c.execute("""
            select unit_id, date_start, k.extracted_by from (
              select p.claim_id, p.unit_id, p.date_start from claim_participated p union all
              select u.claim_id, u.unit_id, u.date_start from claim_unit_at u union all
              select s.claim_id, s.unit_id, s.date_start from claim_subordinate_to s) x join claim k on k.id=x.claim_id
            where unit_id is not null and date_start is not null and k.extracted_by not like '%namesake%'
            and k.extracted_by not like '%or_stations%' and k.extracted_by not like '%datelines%'"""):
        d = dn(ds if len(ds) >= 10 else ds[:7] + "-15")
        if d and uid in code_of:
            dates[code_of[uid]].append(d)
    for uid, ds, la, lo in c.execute("""
            select u.unit_id, u.date_start, p.lat, p.lon from claim_unit_at u join place p on p.id=u.place_id
            join claim k on k.id=u.claim_id
            where u.date_precision='day' and p.lat is not null and p.precision_m <= 10000
            and k.extracted_by not like '%or_stations%' and k.extracted_by not like '%datelines%'
            union all
            select pa.unit_id, a.date_start, p.lat, p.lon from claim_participated pa join claim_event_at a on a.event_id=pa.event_id
            join place p on p.id=a.place_id join claim k on k.id=pa.claim_id
            where p.lat is not null and a.date_start is not null and k.extracted_by not like '%namesake%'"""):
        d = dn(ds)
        if d and uid in code_of:
            pos[code_of[uid]].append((d, la, lo))

    # the OTHER source's order-of-battle brigades (table or article, brigade, date) -> units: who served beside whom.
    # OR rows are checked against Wikipedia's brigades, Wikipedia rows against the OR tables' (never a row's own source)
    grp, mem = defaultdict(set), defaultdict(list)
    other = "regex:or_org%" if wikimode else "wikitext%"
    for uid, pm, ds, span, loc in c.execute("""select s.unit_id, s.parent_mention, s.date_start, k.source_span, k.locator
            from claim_subordinate_to s join claim k on k.id=s.claim_id
            where k.extracted_by like ? and k.extracted_by not like '%namesake%'
            and s.unit_id is not null and s.date_start is not null""", (other,)):
        if uid in code_of:
            g = (((loc or "") + (span or ""))[:100], pm, ds); grp[g].add(code_of[uid]); mem[code_of[uid]].append(g)

    def wiki(code, d, M):
        """'consistent' if a Wikipedia brigade of this code within 180 days holds one of M, 'inconsistent' if it has
        Wikipedia brigades then but none holds one of M, else None"""
        gs = [g for g in mem.get(code, ()) if dn(g[2]) and abs(dn(g[2]) - d) <= 180]
        if not gs or not M:
            return None
        return "consistent" if any(grp[g] & M for g in gs) else "inconsistent"

    def alive(code, d):
        ds = dates.get(code) or []
        return len(ds) >= 3 and min(ds) - 180 <= d <= max(ds) + 180

    def where(codes, d, win):
        ps = [(la, lo) for k in codes for t, la, lo in pos.get(k, ()) if abs(t - d) <= win]
        return (statistics.median(p[0] for p in ps), statistics.median(p[1] for p in ps)) if ps else None

    mates = defaultdict(set)
    for r in rows:
        c_ = r.get("unit_code") or ""
        if c_ and not c_.startswith("AMB") and r.get("confidence") != "low":
            mates[key(r)].add(c_)
    for r in rows:
        if r.get("confidence") == "low":
            continue
        c_ = r.get("unit_code") or ""
        if c_.startswith("AMB"):
            cands = c_.split(":", 1)[1].split("|")
        elif c_ and len(groups.get(base(c_), ())) > 1:
            cands = sorted(groups[base(c_)])
        else:
            continue
        d = dn(r["_date"]) if r.get("_date") else None
        if d is None:
            continue
        M = mates[key(r)] - set(cands)
        wk = {k: wiki(k, d, M) for k in cands}
        cons = [k for k in cands if wk[k] == "consistent"]
        live = [k for k in cands if alive(k, d) and wk[k] != "inconsistent"]
        pick, why = None, ""
        if len(cons) == 1:
            pick, why = cons[0], ("beside the same brigade-mates in an OR organization table within 180 days" if wikimode
                                  else "beside the same brigade-mates in a Wikipedia order of battle within 180 days")
            live = []
        elif len(cons) > 1:
            live = []
        here = where(mates[key(r)] - set(cands), d, params.NAMESAKE_MATES_DAYS) if live else None
        if len(live) == 1:
            w = where([live[0]], d, params.NAMESAKE_UNIT_DAYS)
            if here and w and km(here, w) > params.NAMESAKE_FAR_KM:
                stats["kept: the only namesake in service was over 400 km away"] += 1
            else:
                pick, why = live[0], "the only namesake with evidence around that date" + (
                    f" ({km(here, w):.0f} km from the brigade-mates)" if here and w else "")
        elif len(live) > 1:
            if here:
                dist = {}
                for k in live:
                    w = where([k], d, params.NAMESAKE_UNIT_DAYS)
                    dist[k] = km(here, w) if w else None
                near = [k for k in live if dist[k] is not None and dist[k] <= params.NAMESAKE_NEAR_KM]
                far = [k for k in live if dist[k] is not None and dist[k] >= params.NAMESAKE_FAR_KM]
                if len(near) == 1 and len(near) + len(far) == len(live):
                    pick, why = near[0], "near the row's brigade-mates (" + ", ".join(
                        f"{k} {dist[k]:.0f} km" for k in live) + ")"
        if c_.startswith("AMB"):
            stats[f"ambiguous rows ({r['side']})"] += 1
            if pick:
                r["unit_code"] = pick; r["namesake_note"] = "picked: " + why
                stats[f"ambiguous picked ({r['side']})"] += 1
        elif not wikimode and wk.get(c_) == "inconsistent" and len(cons) == 1 and cons[0] != c_:
            # (OR rows only: with both sources relinking by each other's brigades, a pair of relinks - 1st Tennessee,
            # 1862 - undid each other on alternate builds; the Wikipedia rows keep their default link)
            # a default link (parse_or_all.py takes the code without a suffix) that Wikipedia contradicts while it
            # places exactly one namesake beside this row's brigade-mates
            r["unit_code"] = cons[0]; r["namesake_note"] = f"relinked from {c_} (the other source places it in another brigade then): " + why
            stats[f"relinked by the other source's brigades ({r['side']})"] += 1
        elif pick and pick != c_ and not alive(c_, d):
            r["unit_code"] = pick; r["namesake_note"] = f"relinked from {c_} (no evidence around that date): " + why
            stats[f"relinked ({r['side']})"] += 1
    with open(pl_p, "w", encoding="utf-8") as fo:
        for r in rows:
            fo.write(json.dumps({k: v for k, v in r.items() if k not in ("_table", "_date")}, ensure_ascii=False) + "\n")
    rep = [f"{k}: {v}" for k, v in sorted(stats.items())]
    ex = [f"  {r['unit']} | {r['_table']} {r['_date']} | {r['namesake_note']}" for r in rows if r.get("namesake_note")][:60]
    open(rep_p, "w").write("\n".join(rep + ["", "Examples:"] + ex) + "\n")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*sys.argv[1:])
