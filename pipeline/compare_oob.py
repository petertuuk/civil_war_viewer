"""Link Wikipedia order-of-battle placements to events, and compare them with the Official Records.

Usage:
  python3 pipeline/compare_oob.py data/wikipedia/oob_placements.jsonl data/or/claims_or.jsonl data/events data/wikipedia data/scores/oob_vs_or.txt

1. Each article's battle name ("Battle of Gettysburg") -> Wikipedia page -> Wikidata QID (pageprops) -> our event.
   Writes data/wikipedia/oob_battles.json (battle -> qid, event_id).
2. For events with both an OR table and a Wikipedia list (same side): units in each, overlap,
   and brigade agreement: for units in both, do OR and Wikipedia group them the same way?
"""
from cwv import paths
import collections, json, re, sys, urllib.parse, urllib.request, time
from pathlib import Path

UA = "CivilWarViewer/0.2 (personal history research; python urllib)"


def qids_for(titles):
    out = {}
    for i in range(0, len(titles), 40):
        u = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
            "redirects": 1, "titles": "|".join(titles[i:i + 40]), "format": "json", "formatversion": 2})
        r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60))
        norm = {n["from"]: n["to"] for n in r["query"].get("normalized", [])}
        redir = {n["from"]: n["to"] for n in r["query"].get("redirects", [])}
        got = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in r["query"]["pages"]}
        for t in titles[i:i + 40]:
            t2 = redir.get(norm.get(t, t), norm.get(t, t))
            out[t] = got.get(t2)
        time.sleep(0.5)
    return out


def main(wp, orc, events_dir, wdir, out):
    W = [json.loads(l) for l in open(wp, encoding="utf-8")]
    battles = sorted({r["battle"] for r in W})
    cache = Path(wdir) / "oob_battles.json"
    known = json.load(open(cache)) if cache.exists() else {}
    need = [b for b in battles if b not in known]
    if need:
        for b, q in qids_for(need).items():
            known[b] = {"qid": q}
    ev = [json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")]
    by_q = {}
    for e in sorted(ev, key=lambda e: -e["regiments"]):
        if e.get("wikidata"):
            by_q.setdefault(e["wikidata"], e)
    for b, v in known.items():
        e = by_q.get(v.get("qid"))
        v["event_id"] = e["event_id"] if e else None
        v["event_name"] = e["name"] if e else None
    json.dump(known, open(cache, "w"), indent=1)
    linked = sum(1 for v in known.values() if v.get("event_id"))
    # 2. compare where both exist
    wp_units = collections.defaultdict(dict)       # (side, event) -> unit_code -> brigade
    for r in W:
        e = known.get(r["battle"], {}).get("event_id"); c = r.get("unit_code") or ""
        if e and c and c[0] in "UC" and not c.startswith("AMB"):
            wp_units[(r["side"], e)][c] = (r["corps"] or "") + " / " + (r["division"] or "") + " / " + (r["brigade"] or "")
    or_units = collections.defaultdict(dict)
    or_pl = {}
    for l in open(orc, encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] == "subordinate_to":
            or_pl[(c["source_ref"], c["unit_mention"])] = c.get("parent_path", {}) | {"conf": c["confidence"]}
    for l in open(orc, encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] == "participated" and c.get("event_id") and c["unit_id"]:
            code = c["unit_id"][4:] if c["unit_id"].startswith("nps:") else None
            if code is None:
                continue                                 # Dyer's ids: compare via code below
            p = or_pl.get((c["source_ref"], c["unit_mention"]), {})
            or_units[(c["side"], c["event_id"])][code] = ((p.get("corps") or "") + " / " + (p.get("division") or "") + " / " + (p.get("brigade") or ""), p.get("conf"))
    # Union OR units carry Dyer's ids: map back to codes
    import csv
    import sys as _sys, os as _os; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import nps_links
    d2n, _, _ = nps_links.load("data/scores/dyer_to_nps.csv")       # cleaned, content-checked links
    for l in open(orc, encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] == "participated" and c.get("event_id") and c["unit_id"] in d2n:
            p = or_pl.get((c["source_ref"], c["unit_mention"]), {})
            or_units[(c["side"], c["event_id"])][d2n[c["unit_id"]]] = ((p.get("corps") or "") + " / " + (p.get("division") or "") + " / " + (p.get("brigade") or ""), p.get("conf"))
    names = {e["event_id"]: e["name"] for e in ev}
    rep = [f"Wikipedia battles: {len(battles)}; with a Wikidata id: {sum(1 for v in known.values() if v.get('qid'))}; linked to our events: {linked}",
           f"Wikipedia placements linked to events: {sum(1 for r in W if known.get(r['battle'], {}).get('event_id'))} of {len(W)}", "",
           f"{'side':4} {'event':40} {'OR':>4} {'WP':>4} {'both':>5} {'OR-only':>7} {'WP-only':>7} {'brigade agree':>13} {'low-conf disagree':>17}"]
    tot = collections.Counter()
    for key in sorted(set(or_units) & set(wp_units), key=lambda k: names[k[1]]):
        o, w = or_units[key], wp_units[key]
        both = set(o) & set(w)
        # brigade agreement by co-membership: unit pairs grouped together in one source and not the other
        agree = dis_low = 0
        for u in both:
            mates_o = {v for v in both if v != u and o[v][0] == o[u][0]}
            mates_w = {v for v in both if v != u and w[v] == w[u]}
            if mates_o == mates_w or (mates_o & mates_w and len(mates_o ^ mates_w) <= 1):
                agree += 1
            elif o[u][1] == 0.5:
                dis_low += 1
        tot.update(both=len(both), agree=agree, o_only=len(set(o) - set(w)), w_only=len(set(w) - set(o)))
        rep.append(f"{key[0][:4]:4} {names[key[1]][:40]:40} {len(o):4} {len(w):4} {len(both):5} {len(set(o)-set(w)):7} {len(set(w)-set(o)):7} "
                   f"{agree:6}/{len(both):<6} {dis_low:17}")
    rep += ["", f"Totals: units in both {tot['both']}; brigade grouping agrees for {tot['agree']} ({100*tot['agree']/max(1,tot['both']):.0f}%); "
                f"OR only {tot['o_only']}; Wikipedia only {tot['w_only']}"]
    Path(out).write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*(sys.argv[1:6] or paths.defaults("compare_oob")))
