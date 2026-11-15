"""Compare Confederate units at single battles across three sources.

Usage: python3 pipeline/check_confederate.py data/or/claims_or.jsonl data/events data/external/acw_battle_data data/nps/units.jsonl data/scores/confederate_check.txt

Sources per battle: OR organization table (participated claims, units with NPS codes),
CWSS units-engaged rows (Crute, via Arnold), and NPS unit histories that link the battle.
"""
from cwv import paths
import collections, csv, json, sys
from pathlib import Path

BATTLES = {"Battle of Shiloh": "TN003", "Battle of Perryville": "KY009", "Battle of Stones River": "TN010",
           "Battle of Gettysburg": "PA002", "Battle of Chickamauga": "GA004", "Battle of Mine Run": "VA041",
           "Siege of Vicksburg": "MS011", "Second Battle of Corinth": "MS016"}


def main(claims, events_dir, arnold, nps_units, out):
    names = {b["cwsac_id"].upper(): b["battle_name"] for b in csv.DictReader(open(Path(arnold) / "nps_battles.csv", encoding="utf-8"))}
    ev = {json.loads(l)["event_id"]: json.loads(l)["name"] for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")}
    orc = collections.defaultdict(set)
    for l in open(claims, encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] == "participated" and c["side"] == "Confederate" and c.get("event_id") and (c["unit_id"] or "").startswith("nps:"):
            orc[ev.get(c["event_id"])].add(c["unit_id"][4:])
    crute = collections.defaultdict(set)
    for r in csv.DictReader(open(Path(arnold) / "nps_battle_units.csv", encoding="utf-8")):
        if r["belligerent"] == "Confederate":
            crute[r["cwsac_id"].upper()].add(r["unit_code"])
    nps = collections.defaultdict(set)
    for l in open(nps_units, encoding="utf-8"):
        u = json.loads(l)
        for b in u["battle_links"]:
            nps[b.upper()].add(u["unit_code"])
    rep = ["Confederate units per battle: OR table vs CWSS (Crute) vs NPS histories linking the battle", "",
           f"{'battle':28} {'cwsac':6} {'OR':>4} {'CWSS':>5} {'NPS':>4} {'OR&CWSS':>8} {'OR&NPS':>7} {'CWSS-only':>9} {'NPS-only':>8}"]
    for ename, bid in BATTLES.items():
        if bid not in names:
            continue
        o, c, n = orc.get(ename, set()), crute.get(bid, set()), nps.get(bid, set())
        rep.append(f"{ename[:28]:28} {bid:6} {len(o):4} {len(c):5} {len(n):4} {len(o & c):8} {len(o & n):7} {len(c - o):9} {len(n - o):8}")
    tot_o = set().union(*orc.values()) if orc else set()
    rep += ["", f"Distinct Confederate units with OR participation in any linked event: {len(tot_o)}",
            f"CWSS Confederate unit-battle rows (Crute): {sum(len(v) for v in crute.values())} over {len(crute)} battles"]
    Path(out).write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*(sys.argv[1:6] or paths.defaults("check_confederate")))
