"""Score state-history battle claims (data/scores/state_histories_report.jsonl, written by extract_state_histories.py)
against the other sources' participation claims in the database: per book and route (date / unique name), the share
confirmed among units that have other battle claims at all.
Usage: python pipeline/validate_state_histories.py ~/db/civil_war.db data/scores/state_histories_report.jsonl data/events/events.jsonl"""
import json, sqlite3, sys
from collections import Counter


def main(db, rep, events_p):
    c = sqlite3.connect(db)
    code = dict(c.execute("select value, entity_id from external_id where entity_type='unit' and scheme='nps'"))
    evid = dict(c.execute("select value, entity_id from external_id where entity_type='event' and scheme='pipeline_event'"))
    name2ev = {}
    for l in open(events_p, encoding="utf-8"):
        e = json.loads(l)
        name2ev.setdefault((e["name"], e["date_start"][:10] if e.get("date_start") else None), e["event_id"])
    other = set(c.execute("""select p.unit_id, p.event_id from claim_participated p join claim k on k.id=p.claim_id
                             where k.extracted_by not like 'regex:state_histories%'"""))
    covered = {u for u, _ in other}
    st = Counter()
    for l in open(rep):
        r = json.loads(l)
        u = code.get(r["unit"]); e = evid.get(name2ev.get((r["event"], r["date"])))
        k = (r["book"], r["how"])
        st[k + ("n",)] += 1
        if u in covered and e:
            st[k + ("checked",)] += 1
            st[k + ("confirmed",)] += (u, e) in other
    for k in sorted({k[:2] for k in st}):
        n, ch, cf = st[k + ("n",)], st[k + ("checked",)], st[k + ("confirmed",)]
        print(f"{k[0]:26s} {k[1]:12s} claims {n:4d} checked {ch:4d} confirmed {100 * cf / max(ch, 1):3.0f}%")


if __name__ == "__main__":
    main(*sys.argv[1:])
