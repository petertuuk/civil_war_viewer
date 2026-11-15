"""Confederate battle participation from the NPS Soldiers and Sailors battle unit lists.

The NPS lists of units engaged in each CWSAC battle (nps_battle_units.csv) were compiled from Dyer's
for the Union (not independent of Dyer's, so not loaded) and from Crute, Units of the Confederate States
Army, for the Confederacy. The Confederate rows become participated claims.

Battle -> event: Wikipedia title -> Wikidata label -> an event anchored to that item with dates near the
battle's; else the battle's name words (main or other names) and overlapping dates, largest event first.

Usage: python pipeline/nps_battles_to_claims.py data/external/acw_battle_data data/wikidata/<file>.json \
           data/scores/dyer_to_nps.csv data/events data/nps/claims_nps_battles.jsonl
"""
import csv, json, re, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from common import first_day as d  # noqa: E402
import nps_links  # noqa: E402
from anchor_events import words_of  # noqa: E402


def main(ar, wdp, d2n, events_dir, out_path):
    ar = Path(ar)
    _, code2dyer, _ = nps_links.load(d2n)
    W = json.load(open(wdp, encoding="utf-8"))
    lab = defaultdict(set)
    for r in W:
        q = r["b"].rsplit("/", 1)[-1]
        for nm in [r.get("label") or ""] + (r.get("aliases") or "").split("|"):
            if nm:
                lab[nm.lower()].add(q)
    events = [json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")]
    by_q = defaultdict(list)
    for e in events:
        if e.get("wikidata"):
            by_q[e["wikidata"]].append(e)
    by_word = defaultdict(list)
    for e in events:
        for w in words_of(e["name"]) | words_of(e.get("dyer_name") or ""):
            by_word[w].append(e)
    wiki = {r["cwsac_id"].upper(): r["wikipedia_title"].replace("_", " ")
            for r in csv.DictReader(open(ar / "nps_battles_to_wiki.csv", encoding="utf-8"))}
    battles = {r["battle"].upper(): r for r in csv.DictReader(open(ar / "cwsac_battles.csv", encoding="utf-8"))}

    def near(e, bs, be):
        a0, a1 = d(e["date_start"]), d(e["date_end"]) or d(e["date_start"])
        return a0 and a0 - timedelta(days=3) <= be and bs <= (a1 or a0) + timedelta(days=3)

    ev_of, how = {}, Counter()
    for bid, r in battles.items():
        bs, be = d(r["start_date"]), d(r["end_date"]) or d(r["start_date"])
        if not bs:
            continue
        t = (wiki.get(bid) or "").lower()
        qs = lab.get(t) or lab.get(re.sub(r"\s*\([^)]*\)\s*$", "", t)) or set()
        cand = [e for q in qs for e in by_q.get(q, []) if near(e, bs, be)]
        if cand:
            ev_of[bid] = max(cand, key=lambda e: e["regiments"]); how["by wikidata"] += 1
            continue
        best = None
        for nm in [r["battle_name"]] + [x.strip() for x in (r.get("other_names") or "").split(",")]:
            w = words_of(nm)
            if not w:
                continue
            for e in {id(e): e for x in w for e in by_word.get(x, [])}.values():
                ew = words_of(e["name"]) | words_of(e.get("dyer_name") or "")
                if w <= ew and near(e, bs, be) and "campaign" not in e["name"].lower():
                    if best is None or e["regiments"] > best["regiments"]:
                        best = e
        if best:
            ev_of[bid] = best; how["by name and dates"] += 1
        else:
            how["no event"] += 1

    n = Counter()
    with open(out_path, "w", encoding="utf-8") as out:
        for r in csv.DictReader(open(ar / "nps_battle_units.csv", encoding="utf-8")):
            if r["belligerent"] != "Confederate" or r["src"] == "DYER":
                continue
            b = battles.get(r["cwsac_id"].upper())
            if not b:
                n["battle not in cwsac list"] += 1
                continue
            e = ev_of.get(r["cwsac_id"].upper())
            code = r["unit_code"]
            portion = ", ".join(x for x in (r.get("companies") and f"Cos. {r['companies']}",
                                             r.get("batteries") and f"batteries {r['batteries']}",
                                             r.get("detachment") and "detachment", r.get("section") and "section") if x)
            out.write(json.dumps({
                "claim_type": "participated", "unit_id": code2dyer.get(code) or f"nps:{code}", "unit_mention": code,
                "side": "Confederate", "event_mention": b["battle_name"], "event_id": e["event_id"] if e else None,
                "cwsac_id": r["cwsac_id"].upper(), "date_start": b["start_date"], "date_end": b["end_date"] or b["start_date"],
                "date_precision": "day", "confidence": 0.8, "portion": portion or None,
                "source_span": f"{b['battle_name']} ({r['cwsac_id'].upper()}): {code}",
                "source_ref": f"nps_battle_units.csv {r['cwsac_id'].upper()}"}, ensure_ascii=False) + "\n")
            n["claims"] += 1
            n["linked to an event" if e else "no event"] += 1
    print("battles:", dict(how))
    print("claims:", dict(n))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("nps_battles_to_claims")))
