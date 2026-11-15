"""Link Dyer's units to NPS unit codes, and score Dyer's battle extraction against
the NPS/CWSS units-engaged table (which the NPS compiled from Dyer's).

Usage:
  python3 pipeline/score_dyers_vs_cwss.py data/dyers data/external/acw_battle_data data/scores

Outputs:
  dyer_to_nps.csv            unit_id -> unit_code (or ambiguous / none)
  cwss_pairs_compare.csv     per (unit, battle): in CWSS? found in our claims?
  cwss_score.txt             recall / precision summary and the worst units
Matching a Dyer's battle mention to a CWSAC battle: date ranges overlap (+/- 2 days)
and the mention shares a distinctive word with the battle name or its Wikipedia title.
"""
import collections, csv, json, re, sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
from common import first_day as d  # noqa: E402

ST = cwv_states.table("NAME", "CODE", "AL", "AR", "CA", "CO", "CT", "DT", "DE", "DC", "FL", "GA", "IL", "IN", "IA",
                                      "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "NE", "NV", "NH",
                                      "NJ", "NM", "NY", "NC", "OH", "OR", "PA", "RI", "SC", "TN", "TX", "VT", "VA",
                                      "WV", "WI", ("WASHINGTON TERRITORY", "WA"),
                                      # Dyer's U.S. sections -> NPS pseudo-states (added 2026-11-11; these had never been linked)
                                      ("U.S. COLORED TROOPS", "US"), ("U.S. REGULAR ARMY", "UR"),
                                      ("U.S. VETERAN VOLUNTEERS", "UV"), ("U.S. VOLUNTEERS", "UV"),
                                      ("U.S. VETERAN RESERVE CORPS", "VR"))
SPELL = {"spottsylvania": "spotsylvania", "jonesboro": "jonesborough", "opequan": "opequon", "kenesaw": "kennesaw",
         "chickamauga": "chickamauga", "peach": "peachtree", "averysboro": "averasborough", "averasboro": "averasborough",
         "drury": "drewry", "drurys": "drewrys", "savage": "savages", "champions": "champion", "shiloh": "shiloh"}
STOP = set("church old new battle battles of the at and near on in to engagement action actions skirmish siege assault assaults "
           "combat operations campaign creek river run station court house ford mills hill farm road cross roads "
           "pa va md tenn ga miss ala ky la mo ark n c s".split())


def words(s):
    s = (s or "").lower().replace("'", "").replace("peach tree", "peachtree")
    return {SPELL.get(w, w) for w in re.findall(r"[a-z]{4,}", s) if SPELL.get(w, w) not in STOP}


def main(dyers_dir, arnold_dir, out_dir):
    dy, ar, out = Path(dyers_dir), Path(arnold_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nps = list(csv.DictReader(open(ar / "nps_units.csv", encoding="utf-8")))
    idx = collections.defaultdict(list)
    for u in nps:
        if u["belligerent"] == "US":
            try:
                idx[(u["state"], int(u["ordinal"] or 0), u["type"], u["func"])].append(u)
            except ValueError:
                pass
    # 1. Dyer's unit -> NPS code
    links, stat = {}, collections.Counter()
    with open(out / "dyer_to_nps.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["unit_id", "unit_code", "status", "candidates"])
        for l in open(dy / "units_fixed.jsonl" if (dy / "units_fixed.jsonl").exists() else dy / "units.jsonl", encoding="utf-8"):
            u = json.loads(l)
            st, n = ST.get(u["state"]), u.get("number")
            typ = {"regiment": "R", "battalion": "B"}.get(u.get("kind"))
            func = {"infantry": "I", "cavalry": "C", "heavy artillery": "A", "artillery": "A", "light artillery": "A",
                    "sharpshooters": "I", "engineers": "E"}.get(u.get("branch"))
            if func is None and st == "VR":
                func = ""                     # Veteran Reserve Corps regiments carry no arm in either source
            if not (st and n and typ and func is not None):
                stat["not a state regiment/battalion"] += 1; continue
            c = idx.get((st, int(n), typ, func), [])
            if len(c) > 1:
                term = (u.get("term") or "")
                t2 = [x for x in c if (term and term.split()[0] in x["unit_name"] and "month" in x["unit_name"]) or
                      (not term.startswith("3 m") and "month" not in x["unit_name"] and "Militia" not in x["unit_name"])]
                c = t2 if len(t2) == 1 else ([x for x in c if not re.search(r"\d\d$", x["unit_code"])] if not term else t2) or c
            status = "linked" if len(c) == 1 else ("ambiguous" if c else "no code")
            stat[status] += 1
            if len(c) == 1:
                links[u["id"]] = c[0]["unit_code"]
            w.writerow([u["id"], c[0]["unit_code"] if len(c) == 1 else "", status, "|".join(x["unit_code"] for x in c[:4])])
    # 2. CWSAC battles and the CWSS (unit, battle) pairs
    battles = {}
    wiki = {r["cwsac_id"].upper(): r["wikipedia_title"] for r in csv.DictReader(open(ar / "nps_battles_to_wiki.csv", encoding="utf-8"))}
    for b in csv.DictReader(open(ar / "nps_battles.csv", encoding="utf-8")):
        s, e = d(b["start_date"]), d(b["end_date"]) or d(b["start_date"])
        if s:
            battles[b["cwsac_id"].upper()] = (s - timedelta(days=2), e + timedelta(days=2),
                                              words(b["battle_name"]) | words((wiki.get(b["cwsac_id"].upper()) or "").replace("_", " ")),
                                              b["battle_name"])
    # score with the cleaned, content-checked links (nps_links.py), not the raw name-based ones written above
    import sys as _sys; _sys.path.insert(0, str(Path(__file__).parent)); import nps_links
    links, _, _ = nps_links.load(out / "dyer_to_nps.csv", ar / "nps_units.csv")
    code2unit = {c: u for u, c in links.items()}
    truth = collections.defaultdict(set)
    for r in csv.DictReader(open(ar / "nps_battle_units.csv", encoding="utf-8")):
        if r["belligerent"] == "US" and r["unit_code"] in code2unit and r["cwsac_id"].upper() in battles:
            truth[code2unit[r["unit_code"]]].add(r["cwsac_id"].upper())
    # 2b. CWSAC battle -> Wikidata QID (Wikipedia title = Wikidata label or alias); our mentions -> event QID
    wdl = collections.defaultdict(list)
    for r in json.load(open(Path(dyers_dir).parent / "wikidata" / "wikidata_civil_war_events_v2.json", encoding="utf-8")):
        q = r["b"].rsplit("/", 1)[1]
        dt = d(r.get("start") if (r.get("start_prec") or 0) >= 11 else (r.get("pit") or r.get("start")))
        for nm in [r.get("label", "")] + (r.get("aliases") or "").split("|"):
            if nm:
                wdl[nm.lower()].append((q, dt))
    def lookup(title, bstart):
        t = (title or "").replace("_", " ")
        cands = wdl.get(t.lower()) or wdl.get(re.sub(r"\s*\([^)]*\)\s*$", "", t).lower()) or []   # "Battle of Franklin (1864)"
        if len({q for q, _ in cands}) > 1:
            cands = sorted(cands, key=lambda x: abs((x[1] - bstart).days) if x[1] else 9999)
        return cands[0][0] if cands else None
    b2q = {bid: lookup(wiki.get(bid), battles[bid][0] + timedelta(days=2)) for bid in battles}
    q2b = collections.defaultdict(set)
    for bid, q in b2q.items():
        if q:
            q2b[q].add(bid)
    c2e = {json.loads(l)["cluster_id"]: json.loads(l)["event_id"] for l in open(Path(dyers_dir).parent / "events" / "cluster_to_event.jsonl")}
    e2q = {}
    for l in open(Path(dyers_dir).parent / "events" / "events.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if e.get("wikidata"):
            e2q[e["event_id"]] = e["wikidata"]
    ours = collections.defaultdict(set)
    via_q, has_q = 0, set()
    for l in open(dy / "mention_to_event.jsonl", encoding="utf-8"):
        m = json.loads(l)
        q = e2q.get(c2e.get(m["cluster_id"]))
        if q:
            has_q.add((m["unit_id"], m["mention"], m["date_start"]))     # event identified: no name fallback
        if m["unit_id"] in links and q in q2b:
            ours[m["unit_id"]] |= q2b[q]; via_q += 1
    # 3. our pairs from Dyer's participated claims (name + date fallback)
    by_year = collections.defaultdict(list)
    for bid, (s, e, ws, nm) in battles.items():
        for y in range(s.year, e.year + 1):
            by_year[y].append(bid)
    for l in open(dy / "claims_rules.jsonl", encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] != "participated" or c["unit_id"] not in links:
            continue
        s, e = d(c.get("date_start")), d(c.get("date_end")) or d(c.get("date_start"))
        if not s or (c["unit_id"], c.get("event_mention"), c.get("date_start")) in has_q:
            continue
        mw = words(c.get("event_mention"))
        for bid in by_year.get(s.year, []):
            bs, be, bw, _ = battles[bid]
            if s <= be and e >= bs and bw and len(mw & bw) >= max(1, (len(bw) + 1) // 2):
                ours[c["unit_id"]].add(bid)
    # 4. score on units present in both
    units = [u for u in truth]
    tp = sum(len(truth[u] & ours[u]) for u in units)
    fn = sum(len(truth[u] - ours[u]) for u in units)
    fp = sum(len(ours[u] - truth[u]) for u in units)
    with open(out / "cwss_pairs_compare.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["unit_id", "unit_code", "cwsac_id", "battle", "in_cwss", "in_ours"])
        for u in units:
            for bid in sorted(truth[u] | ours[u]):
                w.writerow([u, links[u], bid, battles[bid][3], int(bid in truth[u]), int(bid in ours[u])])
    miss = collections.Counter(battles[b][3] for u in units for b in truth[u] - ours[u])
    extra = collections.Counter(battles[b][3] for u in units for b in ours[u] - truth[u])
    rep = ["Dyer's units -> NPS codes: " + ", ".join(f"{k} {v}" for k, v in stat.most_common()),
           f"Units scored (linked, with CWSS battles): {len(units)}; CWSAC battles with a Wikidata ID: {sum(1 for q in b2q.values() if q)} of {len(b2q)}; mentions matched via Wikidata: {via_q}",
           f"(unit, major battle) pairs in CWSS: {tp + fn}; found by our extraction: {tp} (recall {100*tp/max(1,tp+fn):.1f}%)",
           f"pairs we found that CWSS lacks: {fp} (agreement/precision {100*tp/max(1,tp+fp):.1f}%)",
           "", "Battles most often missed (unit-battle pairs):"] + [f"  {n:4d}  {b}" for b, n in miss.most_common(15)] + \
          ["", "Battles we add most often:"] + [f"  {n:4d}  {b}" for b, n in extra.most_common(15)]
    (out / "cwss_score.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*(sys.argv[1:4] or paths.defaults("score_dyers_vs_cwss")))
