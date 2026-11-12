"""Check letter-heading claims (data/manual/or_datelines.json) against the same unit's other one-day positions in the
database (unit_at with a single date, not from letter headings; events of <= 3 days with a location). A claim agrees
when it is within max(50 km, 2 x its precision) of the other position on that day.
Usage: python pipeline/validate_datelines.py ~/db/civil_war.db data/manual/or_datelines.json [old or_datelines.json]
With an old file: also scores only the claims that are new (unit, day not in the old file)."""
import json, math, sqlite3, sys
from collections import Counter, defaultdict


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, h)))


def main(db, new_p, old_p=None):
    c = sqlite3.connect(db)
    code = dict(c.execute("select value, entity_id from external_id where entity_type='unit' and scheme='nps'"))
    ref = defaultdict(list)
    for uid, ds, lat, lon in c.execute("""select u.unit_id, u.date_start, p.lat, p.lon from claim_unit_at u join claim k on k.id=u.claim_id
            join place p on p.id=u.place_id where u.date_start=u.date_end and u.date_precision='day' and p.lat is not null
            and k.extracted_by not like '%datelines%'"""):
        ref[(uid, ds)].append((lat, lon))
    for uid, ds, de, lat, lon in c.execute("""select pa.unit_id, e.date_start, e.date_end, p.lat, p.lon from claim_participated pa
            join (select event_id, min(date_start) date_start, max(date_end) date_end, min(place_id) place_id from claim_event_at
                  group by event_id) e on e.event_id=pa.event_id join place p on p.id=e.place_id
            where p.lat is not null and e.date_start is not null and e.date_end is not null
            and julianday(e.date_end)-julianday(e.date_start) <= 2"""):
        from datetime import date, timedelta
        d0, d1 = date.fromisoformat(ds[:10]), date.fromisoformat(de[:10])
        while d0 <= d1:
            ref[(uid, d0.isoformat())].append((lat, lon)); d0 += timedelta(days=1)
    old = set()
    if old_p:
        old = {(x["unit"]["nps_code"], x["date_start"]) for x in json.load(open(old_p, encoding="utf-8"))["claims"]}
    for label, keep in (("all", lambda k: True), ("new", lambda k: k not in old)) if old_p else (("all", lambda k: True),):
        st = Counter()
        for x in json.load(open(new_p, encoding="utf-8"))["claims"]:
            k = (x["unit"]["nps_code"], x["date_start"])
            if not keep(k):
                continue
            uid = code.get(k[0])
            rs = ref.get((uid, k[1])) if uid else None
            lev = x["note"].split("headquarters of the ")[-1].split()[0]
            st[(lev, "n")] += 1
            if not rs:
                continue
            p = (x["place"]["lat"], x["place"]["lon"])
            ok = min(km(p, r) for r in rs) <= max(50, 2 * x["place"]["precision_m"] / 1000)
            st[(lev, "checked")] += 1; st[(lev, "agree")] += ok
        print(label, "claims", sum(v for (l, t), v in st.items() if t == "n"))
        for lev in ("regiment", "brigade", "division", "corps"):
            n = st[(lev, "checked")]
            print(f"  {lev:9s} claims {st[(lev, 'n')]:6d}  checked {n:5d}  agree {100 * st[(lev, 'agree')] / max(n, 1):.0f}%")


if __name__ == "__main__":
    main(*sys.argv[1:])
