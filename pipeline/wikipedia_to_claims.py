"""Turn Wikipedia order-of-battle placements into claims (a second source beside the Official Records).

Usage:
  python3 pipeline/wikipedia_to_claims.py data/wikipedia/oob_placements.jsonl data/wikipedia/oob_battles.json \
      data/scores/dyer_to_nps.csv data/events data/wikipedia/claims_wikipedia.jsonl
Claims: subordinate_to (unit -> brigade, division, corps), commanded (with order and casualty status:
k killed, mw mortally wounded, w wounded, c captured), participated (event from the article's battle).
Dated to the event. Source: English Wikipedia (CC BY-SA 4.0), article title and revision id kept.
Confidence 0.8: compiled secondary source, usually from the Official Records.
"""
from cwv import paths
import csv, json, sys
import nps_links
from collections import Counter
from pathlib import Path


def main(pl, battles, d2n_path, events_dir, out_path):
    _, code2dyer, _ = nps_links.load(d2n_path)
    B = json.load(open(battles))
    E = {json.loads(l)["event_id"]: json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")}
    n = Counter()
    with open(out_path, "w", encoding="utf-8") as out:
        for r in map(json.loads, open(pl, encoding="utf-8")):
            eid = B.get(r["battle"], {}).get("event_id")
            e = E.get(eid, {})
            code = nps_links.resolve_ambiguous(r.get("unit_code")) or ""
            picked = (r.get("unit_code") or "").startswith("AMBIGUOUS:") and bool(code)     # tagged like a namesake pick
            if not code:
                code = nps_links.alias_code(r["unit"], r["side"]) or ""      # data/manual/unit_aliases.psv
            uid = (code2dyer.get(code) or f"nps:{code}") if code and code[0] in "UC" and not code.startswith("AMB") else None
            bat = nps_links.battery_from_code(code, r.get("portion"), code2dyer) if code else None
            if bat:
                uid, r = bat, dict(r, portion=None)         # the lettered battery's own Dyer's record
            base = {"unit_id": uid, "unit_mention": r["unit"], "side": r["side"], "source": "Wikipedia",
                    "source_ref": f"{r['title']} (rev {r['revid']})", "source_span": r["title"],
                    "date_start": e.get("date_start"), "date_end": e.get("date_end"), "date_precision": "day" if e else None,
                    "confidence": 0.8, "extracted_by": "wikitext:oob_v1" + (":namesake" if r.get("namesake_note") or picked else ""),
                    "license": "CC BY-SA 4.0"}
            if r.get("portion"):
                base["portion"] = r["portion"]
            parent = ", ".join(x for x in (r["brigade"], r["division"], r["corps"]) if x)
            if parent:
                out.write(json.dumps(dict(base, claim_type="subordinate_to", parent_mention=parent,
                    parent_path={"brigade": r["brigade"], "division": r["division"], "corps": r["corps"], "army": r["army"],
                                 "brigade_commanders": r["brigade_commanders"], "division_commanders": r["division_commanders"]}),
                    ensure_ascii=False) + "\n"); n["subordinate_to"] += 1
            for i, c in enumerate(r["commanders"]):
                out.write(json.dumps(dict(base, claim_type="commanded", person_mention=c["name"], order=i,
                                          casualty=c["status"]), ensure_ascii=False) + "\n"); n["commanded"] += 1
            out.write(json.dumps(dict(base, claim_type="participated", event_mention=r["battle"] + (f" ({r['phase']})" if r["phase"] else ""),
                                      event_id=eid), ensure_ascii=False) + "\n")
            n["participated"] += 1; n["linked" if eid else "unlinked"] += 1; n["with unit id" if uid else "no unit id"] += 1
    print(dict(n))


if __name__ == "__main__":
    main(*(sys.argv[1:6] or paths.defaults("wikipedia_to_claims")))
