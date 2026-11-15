"""Positions of units inside a battle from battlefield monuments and markers mapped in OpenStreetMap.

At Gettysburg nearly every Union regiment and battery has a monument, often with position markers ("July 1st
1863 pos marker") and flank markers; Confederate positions are mostly marked by brigade tablets. OSM names follow
a compact convention: "147th NY Miller(w) / Harney", "1st NY Light Artillery Battery L ...", "CS Kershaw SC Brigade",
"US HQ 2-2nd Division Gibbon(w)". Each parsed marker becomes a unit_at claim at its coordinates:
  regiment or battery monument/marker  -> that unit (precision 60 m); dated markers get their day, others the battle days
  Confederate brigade tablet           -> each regiment the battle's order of battle puts in that brigade (precision 400 m)
Data: OpenStreetMap contributors (ODbL 1.0), fetched with Overpass (historic=memorial|monument in the battlefield box).

Usage: python pipeline/battle_positions.py data/battles/osm_gettysburg_monuments.json civil_war.db "Battle of Gettysburg" \
          1863-07-01 1863-07-03 data/battles/gettysburg_positions.jsonl
"""
from cwv import states as cwv_states
import json, re, sqlite3, sys
from collections import Counter, defaultdict

ST = cwv_states.table("CODE", "Name", "ME", "NH", "VT", "MA", "RI", "CT", "NY", "NJ", "PA", "DE", "MD", "WV", "OH",
                                      "IN", "IL", "MI", "WI", "MN", ("US", "U.S."), "VA", "NC", "SC", "GA", "AL",
                                      "MS", "LA", "TX", "AR", "TN", "FL")
DAY = {"1st": "01", "2nd": "02", "3rd": "03"}


def bk(name):
    """Brigade key: commander surname, lower case, without a final s ("Doles'" and "Dole's" both -> "dole")."""
    return re.sub(r"s$", "", re.sub(r"[^a-z]", "", name.lower()))


def parse(name):
    if name.startswith("CS ") and "Stonewall Brigade" in name:
        return dict(side="Confederate", kind="brigade", commander="Stonewall", state="VA", cavalry=False,
                    day=None, role="main")
    n = re.sub(r"[“”\"].*?[“”\"]", " ", name).strip()
    side = "Confederate" if n.startswith("CS ") else "Union"
    n = re.sub(r"^(US|CS)\s+", "", n)
    n = re.sub(r"\((?:w|c|k|mw)\)|\+", "", n)                 # (w)ounded, (c)aptured, + killed
    n = re.sub(r"^[A-Z][a-z]+\s*/\s*", "", n) if side == "Confederate" else n   # "Hood / Law Texas Brigade" -> Law
    day = re.search(r"July (1st|2nd|3rd)", name)
    role = "flank" if re.search(r"\b(left|right)\b", name, re.I) else "marker" if re.search(r"\bmarker\b", name, re.I) else "main"
    if side == "Confederate" and re.match(r"HQ\s+\S.*Brigade", n):
        n = re.sub(r"^HQ\s+", "", n)                 # a Confederate brigade's HQ tablet marks the brigade's line
    if n.startswith("HQ") or re.search(r"\bGeneral\b|KIA|House|Farm|State\b|Monument to|Regiments markers", n):
        return None
    m = re.match(r"^(\d+)(?:st|nd|rd|th|d)\s+([A-Z]{2})\b\s*(.*)$", n)
    if m:
        num, st, rest = int(m.group(1)), m.group(2), m.group(3)
        if st not in ST:
            return None
        if re.match(r"(Light\s+)?Artillery\b", rest) or re.match(r"Artillery", rest):
            b = re.search(r"Battery\s+([A-M])\b", rest)
            kind = "battery" if b else "battery_ind"
            return dict(side=side, state=st, number=num, branch="artillery", letter=b.group(1) if b else None,
                        heavy="Heavy" in rest, kind=kind, day=day and DAY[day.group(1)], role=role)
        if rest.startswith("Battery"):
            return dict(side=side, state=st, number=num, branch="artillery", kind="battery_ind", letter=None, day=day and DAY[day.group(1)], role=role)
        br = "cavalry" if rest.startswith("Cavalry") else "infantry"
        if re.match(r"(PA )?Res\b|Reserves", rest):
            br = "reserves"
        return dict(side=side, state=st, number=num, branch=br, kind="regiment", day=day and DAY[day.group(1)], role=role)
    m = re.match(r"^(?:[A-Z]\.\s*)*([A-Z][A-Za-z'’\.]+?)\+?(?:['’]s)?\s+(?:([A-Z]{2})\s+)?(Cavalry\s+)?Brigade\b", n)
    if m and side == "Confederate":
        return dict(side=side, kind="brigade", commander=re.sub(r"['’]s?$", "", m.group(1)).replace("'", "").replace("’", "").rstrip("."),
                    state=m.group(2), cavalry=bool(m.group(3)), day=day and DAY[day.group(1)], role=role)
    return None


def main(osm, dbp, battle, d0, d1, out):
    E = json.load(open(osm, encoding="utf-8"))["elements"]
    db = sqlite3.connect(dbp)
    units = db.execute("""SELECT u.id, s.name, u.state, u.number, u.branch, u.echelon, u.display_name FROM unit u
                          JOIN side s ON s.id=u.side_id""").fetchall()
    dyer = dict(db.execute("SELECT entity_id, value FROM external_id WHERE entity_type='unit' AND scheme='dyer'"))
    nps = dict(db.execute("SELECT entity_id, value FROM external_id WHERE entity_type='unit' AND scheme='nps'"))
    key_of = lambda u: dyer.get(u) or (f"nps:{nps[u]}" if u in nps else None)   # stable across rebuilds, unlike row ids
    battery = {}                               # (dyer state prefix, regiment number, letter) -> unit
    for uid, v in dyer.items():
        m = re.search(r"^([a-z_]+)/\d+_battery_([a-m])_(\d+)(?:st|nd|rd|th|d)_", v)
        if m:
            battery[(m.group(1), int(m.group(3)), m.group(2).upper())] = uid
    bykey = defaultdict(list)
    for uid, side, st, num, br, ech, nm in units:
        bykey[(side, st, num)].append((uid, br, ech, nm))
    # Confederate brigades in the battle's order of battle: brigade commander surname -> regiments
    ev = db.execute("SELECT id FROM event WHERE display_name=?", (battle,)).fetchone()
    brig = defaultdict(set)
    for uid, pm, pj in db.execute("""SELECT x.unit_id, x.parent_mention, x.parent_path_json FROM claim_subordinate_to x
            JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE x.unit_id IS NOT NULL AND x.date_start BETWEEN ? AND ? AND s.title LIKE ?""",
                                  (d0, d1, f"%{battle}%Confederate%")):
        try:
            b = json.loads(pj or "{}").get("brigade") or pm or ""
        except ValueError:
            b = pm or ""
        for w in re.findall(r"([A-Z][a-z]+)(?:['’]s|['’])?\s+(?:\(old\)\s+)?Brigade|\(([A-Z][a-z]+)['’]s?\)", b):
            brig[bk(w[0] or w[1])].add(uid)
    stats, rows = Counter(), []
    for e in E:
        nm = e.get("tags", {}).get("name", "")
        lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
        p = parse(nm) if nm else None
        if not p:
            stats["not a unit marker"] += 1; continue
        targets = []
        if p["kind"] == "brigade":
            targets = sorted(brig.get(bk(p["commander"]), ()))
            prec = 400
        else:
            st = ST[p["state"]]
            prec = 60
            cands = bykey.get((p["side"], p["state"], p["number"]), [])
            if p["state"] == "US":
                cands = [c for c in bykey.get(("Union", "UR", p["number"]), [])]
            if p["kind"] == "battery":
                pref = "u_s_regular_army" if p["state"] == "US" else st.lower().replace(" ", "_")
                b = battery.get((pref, p["number"], p["letter"]))
                cands = [(b, "artillery", "battery", "")] if b else []
            elif p["kind"] == "battery_ind":
                cands = [c for c in cands if c[1] == "artillery" and c[2] == "battery"]
            elif p["branch"] == "reserves":
                cands = [c for c in cands if "Reserve" in c[3]]
            else:
                cands = [c for c in cands if c[1] == p["branch"] and c[2] == "regiment" and not re.search(r"Months|Militia|Emergency|Veteran|Reserve|National Guard", c[3])]
            if len(cands) > 1 and sum(c[0] in dyer for c in cands) == 1:
                cands = [c for c in cands if c[0] in dyer]          # the Dyer's record over an NPS-only duplicate
            if len(cands) == 1:
                targets = [cands[0][0]]
            else:
                stats[f"{p['kind']}: {len(cands)} candidates"] += 1
        if not targets:
            stats["unresolved"] += 1; continue
        stats[f"{p['side']} {p['kind']} resolved"] += 1
        for t in targets:
            if not key_of(t):
                stats["no stable unit key"] += 1; continue
            rows.append(dict(unit_key=key_of(t), unit_id=t, lat=lat, lon=lon, precision_m=prec, role=p["role"], kind=p["kind"],
                             date_start=f"{d0[:8]}{p['day']}" if p["day"] else d0, date_end=f"{d0[:8]}{p['day']}" if p["day"] else d1,
                             source_span=nm, osm=f"{e['type']}/{e['id']}", battle=battle, event_id=ev[0] if ev else None))
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(dict(stats)); print("claims", len(rows), "units", len({r['unit_id'] for r in rows}))


if __name__ == "__main__":
    main(*sys.argv[1:])
