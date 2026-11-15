"""Do the generated claim files still point at the events they were made for? (roadmap T2.3)

    python3 pipeline/refcheck.py [project folder]      exit 0 when every file passes, 1 otherwise

Event ids are list positions (ev00001 ...): when the events stage changes anything, every later id moves by one, and a file made
earlier (data/or, data/wikipedia, data/nps, data/places ...) then attaches its rows to the wrong events without any error (2026-11-14:
453 Bentonville participations landed on "White House"). Two checks per file:
  missing   rows whose event id is not in events.jsonl at all: always an error;
  disagree  for rows that carry their own event text (event_mention / event): the share whose words share nothing with the event
            they point at (its name or Dyer's name). On the current data 0.3-1.3% disagree (aliases such as Ox Hill / Chantilly);
            ids shifted by one give 86-100%. The limit is 5% (not 1%, which the current files already exceed).
build_db.py runs this first and stops when a file fails; CWV_ALLOW_STALE=1 lets it go on (needed once in the documented rebuild
chain, where the first db build is made from the old OR files on purpose, so that `or` can read it).
"""
import json
import os
import re
import sys
from pathlib import Path

LIMIT = 0.05            # share of rows with an event text that disagrees with their event
MIN_ROWS = 20           # fewer rows than this: only the missing-id check applies
STOP = {"battle", "siege", "the", "and", "campaign", "action", "skirmish", "near", "operations", "fort", "expedition", "of"}


def words(s):
    return set(re.findall(r"[a-z]{3,}", (s or "").lower())) - STOP


def agrees(text, ev):
    return bool(words(text) & (words(ev.get("name")) | words(ev.get("dyer_name"))))


def rows(path):
    p = Path(path)
    if not p.exists():
        return None
    return (json.loads(l) for l in open(p, encoding="utf-8") if l.strip())


def main_files():
    """(file, field with the event id, field with the event text or None, stage that makes it)."""
    return [
        ("data/or/claims_or.jsonl", "event_id", "event_mention", "or"),
        ("data/wikipedia/claims_wikipedia.jsonl", "event_id", "event_mention", "or"),
        ("data/wikipedia/claims_wp_regiments.jsonl", "event_id", "event_mention", "or"),
        ("data/nps/claims_nps_battles.jsonl", "event_id", "event_mention", "or"),
        ("data/places/event_resolution.jsonl", "event_id", "event", "links"),
        ("data/places/participation_off_route.jsonl", "event_id", "event", "links"),
        ("data/events/part_of.jsonl", "event_id", None, "events"),
        ("data/events/part_of.jsonl", "parent_event_id", None, "events"),
        ("data/events/cluster_to_event.jsonl", "event_id", None, "events"),
    ]


def check(P):
    """-> (results, events): results = list of dict(file, n, missing, with_text, disagree, stage)."""
    P = Path(P)
    ev = {e["event_id"]: e for e in rows(P / "data/events/events.jsonl")}
    out = []
    for f, idf, textf, stage in main_files():
        rs = rows(P / f)
        if rs is None:
            continue
        n = miss = wt = bad = 0
        for r in rs:
            eid = r.get(idf)
            if not eid:
                continue
            n += 1
            e = ev.get(eid)
            if e is None:
                miss += 1
            elif textf and r.get(textf):
                wt += 1
                bad += not agrees(r[textf], e)
        out.append(dict(file=f + (f" [{idf}]" if f.endswith("part_of.jsonl") else ""), n=n, missing=miss, with_text=wt, disagree=bad, stage=stage))
    # Dyer's own chain: mention -> cluster -> event
    c2e = {r["cluster_id"]: r["event_id"] for r in rows(P / "data/events/cluster_to_event.jsonl") or []}
    m2c = {}
    for m in rows(P / "data/dyers/mention_to_event.jsonl") or []:
        m2c[(m["unit_id"], m["mention"], m["date_start"])] = m["cluster_id"]
    n = miss = wt = bad = nocl = 0
    for c in rows(P / "data/dyers/claims_rules.jsonl") or []:
        if c["claim_type"] != "participated":
            continue
        cl = m2c.get((c["unit_id"], c.get("event_mention"), c.get("date_start")))
        if cl is not None and cl not in c2e:
            nocl += 1
        eid = c2e.get(cl)
        if not eid:
            continue
        n += 1
        e = ev.get(eid)
        if e is None:
            miss += 1
        elif c.get("event_mention"):
            wt += 1
            bad += not agrees(c["event_mention"], e)
    out.append(dict(file="data/dyers/claims_rules.jsonl (via mention_to_event, cluster_to_event)", n=n, missing=miss + nocl, with_text=wt,
                    disagree=bad, stage="events (then dyers/links)"))
    return out, ev


def failed(r):
    return r["missing"] > 0 or (r["with_text"] >= MIN_ROWS and r["disagree"] / r["with_text"] > LIMIT)


def run(P, allow=False, say=print):
    res, ev = check(P)
    say(f"reference check: {len(ev)} events")
    bad = []
    for r in res:
        rate = f"{100 * r['disagree'] / r['with_text']:.2f}% of {r['with_text']} disagree" if r["with_text"] else "ids only"
        flag = "FAIL" if failed(r) else "ok  "
        say(f"  {flag} {r['file']}: {r['n']} ids, {r['missing']} missing, {rate}")
        if failed(r):
            bad.append(r)
    if bad:
        say("STALE: these files point at event ids that no longer match events.jsonl; rerun the stage named, then build the database again:")
        for r in bad:
            say(f"  {r['file']}  -> stage {r['stage']}")
        if allow:
            say("CWV_ALLOW_STALE=1: going on anyway (the documented first database build of the rebuild chain; build again after `or`).")
    return not bad or allow


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else ".", allow=False) else 1)
