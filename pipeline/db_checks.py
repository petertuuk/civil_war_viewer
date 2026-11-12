"""Sanity checks and agreement report on the claims database.
Usage: python3 pipeline/db_checks.py <db> > data/scores/db_checks.txt"""
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); q = lambda s, *a: c.execute(s, a).fetchall()
ev = lambda qid: q("select entity_id from external_id where entity_type='event' and scheme='wikidata' and value=?", qid)[0][0]
dy = lambda d: q("select entity_id from external_id where entity_type='unit' and scheme='dyer' and value=?", d)[0][0]
print("== Row counts"); [print(f"  {t}: {q(f'select count(*) from {t}')[0][0]:,}") for t in ("unit", "event", "place", "person", "source", "claim")]
print("  claims by type and source kind:")
for r in q("select c.claim_type, s.kind, count(*), sum(c.confidence)/count(*) from claim c join source s on s.id=c.source_id group by 1,2 order by 1,2"):
    print(f"    {r[0]:15} {r[1]:17} {r[2]:7,}  mean conf {r[3]:.2f}")
print("  participated with unit and event resolved:", q("select count(*) from claim_participated where unit_id is not null and event_id is not null")[0][0])
print("\n== Unit-event participation pairs by number of independent source kinds")
for r in q("select source_kinds, count(*) from v_participation_support group by 1"): print(f"  {r[0]} kind(s): {r[1]:,}")
print("  pairs where Dyer's has the unit's record but a battle reported by both OR and Wikipedia is missing from it:",
      q("""select count(*) from v_participation_support v where v.kinds='official_records,website'
           and exists(select 1 from external_id x where x.entity_type='unit' and x.entity_id=v.unit_id and x.scheme='dyer')""")[0][0])
for qid, name in [("Q33132", "Gettysburg"), ("Q651713", "Antietam"), ("Q209478", "Shiloh"), ("Q1260018", "Stones River")]:
    try: e = ev(qid)
    except IndexError: continue
    print(f"\n== {name}: units by source combination")
    for r in q("""select s.name, v.kinds, count(*) from v_participation_support v join unit u on u.id=v.unit_id join side s on s.id=u.side_id
                 where v.event_id=? group by 1,2 order by 1,3 desc""", e): print(f"  {r[0]:12} {r[1]:40} {r[2]}")
for label, uid in [("24th Michigan", dy("michigan/068_24th_regiment_infantry"))] + \
        [("26th North Carolina", r[0]) for r in q("select id from unit where display_name='26th Regiment, North Carolina Infantry'")]:
    print(f"\n== {label}")
    for r in q("""select e.display_name, v.kinds, (select min(date_start) from claim_participated where unit_id=v.unit_id and event_id=v.event_id) d
                 from v_participation_support v join event e on e.id=v.event_id where v.unit_id=? order by d""", uid):
        print(f"  {r[2] or '':10} {r[0][:48]:48} {r[1]}")
    print("  commanders:", "; ".join(f"{r[0]}{' ('+r[1]+')' if r[1] else ''} [{r[2]}]" for r in q(
        """select person, max(casualty), count(distinct source) from v_unit_commanders where unit_id=? group by person_id order by min(date_start)""", uid)))

# ---------------------------------------------------------------- event membership (part_of), added 2026-11-11
print("\n== Event membership (part_of)")
for r in q("""select s.kind, c.extracted_by, count(*), sum(p.preferred), sum(1 - p.dates_ok) from claim_part_of p join claim c on c.id=p.claim_id
              join source s on s.id=c.source_id group by 1,2 order by 3 desc"""):
    print(f"  {r[1]:22} claims {r[2]:5,}  preferred {r[3]:5,}  dates outside container {r[4]:4,}")
par = dict(q("select id, parent_event_id from event where parent_event_id is not null"))
def depth(e, seen=None):
    k = 0
    while e in par and k < 10: e = par[e]; k += 1
    return k
from collections import Counter
dd = Counter(depth(e) for (e,) in q("select id from event"))
print("  events by depth below a top-level event:", dict(sorted(dd.items())))
kids = Counter(par.values())
print("  containers with members:", len(kids), "; largest:", ", ".join(
    f"{q('select display_name from event where id=?', e)[0][0]} ({n})" for e, n in kids.most_common(6)))

print("\n== Participation agreement rolled up through membership (a battle claim also supports its containers)")
q("""create temp table roll as
     with recursive up(unit_id, event_id, kind, d) as (
       select cp.unit_id, cp.event_id, s.kind, 0 from claim_participated cp join claim c on c.id=cp.claim_id
       join source s on s.id=c.source_id where cp.unit_id is not null and cp.event_id is not null
       union
       select up.unit_id, e.parent_event_id, up.kind, up.d + 1 from up join event e on e.id=up.event_id
       where e.parent_event_id is not null and up.d < 8)
     select unit_id, event_id, count(distinct kind) kinds, group_concat(distinct kind) kindlist from up group by 1, 2""")
for r in q("select kinds, count(*) from roll group by 1"): print(f"  {r[0]} kind(s): {r[1]:,}")
anc_dy = {(u, e) for u, e in q("""select cp.unit_id, cp.event_id from claim_participated cp join claim c on c.id=cp.claim_id
                                   join source s on s.id=c.source_id where s.kind='compendium' and cp.unit_id is not null and cp.event_id is not null""")}
miss = q("""select v.unit_id, v.event_id from v_participation_support v where v.kinds='official_records,website'
            and exists(select 1 from external_id x where x.entity_type='unit' and x.entity_id=v.unit_id and x.scheme='dyer')""")
def has_container(u, e):
    k = 0
    while e in par and k < 10:
        e = par[e]; k += 1
        if (u, e) in anc_dy: return True
    return False
cont = sum(1 for u, e in miss if has_container(u, e))
print(f"  battles in both OR and Wikipedia missing from a unit's Dyer's record: {len(miss)}; of these Dyer's lists the containing campaign/siege: {cont}; missing entirely: {len(miss) - cont}")
for qid, name in [("Q33132", "Gettysburg")]:
    try: e = ev(qid)
    except IndexError: continue
    p = par.get(e)
    if p:
        print(f"  {name} rolled up into {q('select display_name from event where id=?', p)[0][0]}: units by number of source kinds",
              dict(q("select kinds, count(*) from roll where event_id=? group by 1", p)))
