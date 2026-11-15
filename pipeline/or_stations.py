"""Positions from Official Records organization tables: where each listed unit was on the table's date.

Department and district returns ("Troops in the Defenses of Wilmington, N. C., ... December 31, 1863") list units under
posts ("Fort Pillow.", "Trenton, Tenn.", "Post of Selma, Ala.") or under districts ("FIRST MILITARY DISTRICT").
parse_or_all.py records the post line a unit sits under as `station`; the district or department is in the row's
division / corps / heading. For each placement with a matched unit and a date, the innermost of these that can be
located wins:
  station   a post line: located like Dyer's places (data/places/geocoded.csv, then GNIS Populated Place / Military /
            Island in the named state; with no state written, the states named in the table heading, then the unit's
            own state). Precision 3 km (GNIS) or the geocoded place's own.
  region    a district or department in data/manual/or_regions.psv (Confederate tables only; hand-made: headquarters town
            and a spread radius). Precision = that radius.
Field-army tables (Army of Northern Virginia, Army of Tennessee) name no posts or regions and yield nothing here.

Writes data/derived/or_stations.json (manual claims format, loaded by build_db through manual_claims.py) and prints counts.
Usage: python pipeline/or_stations.py data/or/placements.jsonl data/or/tables.jsonl data/manual/or_regions.psv \
           data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/external/acw_battle_data/nps_units.csv \
           data/derived/or_stations.json
"""
import csv, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
from gnis_index import norm  # noqa: E402
from common import gnis_by_name_state  # noqa: E402

ABBR = {"va": "VA", "w. va": "WV", "w.va": "WV", "n. c": "NC", "n.c": "NC", "s. c": "SC", "s.c": "SC", "ga": "GA", "fla": "FL",
        "ala": "AL", "miss": "MS", "la": "LA", "tex": "TX", "ark": "AR", "tenn": "TN", "ky": "KY", "mo": "MO", "md": "MD",
        "kans": "KS", "ill": "IL", "ohio": "OH", "pa": "PA", "d. c": "DC", "d.c": "DC", "n. y": "NY", "ind": "IN",
        "ariz": "AZ", "n. mex": "NM", "cal": "CA", "oreg": "OR", "wash": "WA", "colo. ter": "CO", "idaho ter": "ID",
        "dak. ter": "SD", "n. h": "NH", "mass": "MA", "conn": "CT", "del": "DE", "minn": "MN", "wis": "WI", "iowa": "IA",
        "mich": "MI", "nebr": "NE", "nev": "NV", "me": "ME", "vt": "VT", "r. i": "RI", "n. j": "NJ", "ind. t": "OK"}
STATE_WORDS = cwv_states.table("Name", "CODE", "VA", "NC", "SC", "GA", "FL", "AL", "MS", "LA", "TX", "AR", "TN",
                                               "KY", "MO", "MD", ("Richmond", "VA"), ("Wilmington", "NC"),
                                               ("Charleston", "SC"), ("Savannah", "GA"), ("Mobile", "AL"),
                                               ("Vicksburg", "MS"), "KS", "OH", "PA", ("Washington", "DC"),
                                               ("Baltimore", "MD"), ("New Orleans", "LA"), "AZ", "NM")
SAME = {"VA": ["VA", "WV"], "WV": ["WV", "VA"]}
MON_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"


def split_place(s):
    """'Post of Selma, Ala' -> ('Selma', 'AL');  'Troops at X, Y and Z' -> ('X', None);  'Fort Pillow' -> ('Fort Pillow', None)"""
    s = re.sub(r"^(X|\*|\W)+\s*", "", s.strip())
    s = re.sub(r"^(Post of|Posts? at|Garrison of|Defenses of|Forces at|Troops at|At|Near|Camp near)\s+", "", s, flags=re.I)
    st = None
    m = re.search(r",\s*([A-Za-z. ]{2,10}?)\.?\s*$", s)
    if m and m.group(1).strip(" .").lower() in ABBR:
        st, s = ABBR[m.group(1).strip(" .").lower()], s[:m.start()]
    s = re.split(r",| and | or |;", s)[0].strip(" .")
    s = re.sub(r"^Forts\b", "Fort", s)
    return s, st


def portion(r):
    t = f"{r['unit']} {r.get('portion') or ''}".lower()
    return "detachment" if "detach" in t else ("companies" if re.search(r"compan|battery [a-z]\b|section", t) else "whole")


def main(pl_p, tables_p, regions_p, geocoded_p, gnis_p, units_p, out_p):
    geo, famous = {}, set()
    for g in csv.DictReader(open(geocoded_p, encoding="utf-8")):
        if g["lat"] and g["method"] in ("override", "seed", "gnis"):
            geo[(norm(g["name"]), g["state"])] = (float(g["lat"]), float(g["lon"]), int(float(g["precision_m"])))
            if int(g["mentions"] or 0) >= 40:
                famous.add(norm(g["name"]))
    G = gnis_by_name_state(gnis_p, ("Populated Place", "Military", "Civil", "Island", "Locale"))
    ustate = {u["unit_code"]: u["state"] for u in csv.DictReader(open(units_p, encoding="utf-8"))}
    STABBR = cwv_states.table("Name", "CODE", "AL", "AR", "FL", "GA", "KY", "LA", "MS", "MO", "NC", "SC", "TN", "TX",
                                              "VA", "MD")

    def locate(name, states):
        for s in [x for st in states for x in SAME.get(st, [st])]:
            k = (norm(name), s)
            if k in geo:
                return geo[k], s, "dyers"
            alt = [norm(name), norm(re.sub(r"^Fort\b", "Ft", name)), norm(re.sub(r"^Saint\b", "St", name))]
            for a in alt:
                cs = G.get((a, s)) or []
                pp = [c for c in cs if c[2] in ("Populated Place", "Military")] or cs
                if pp and len({(round(c[0], 1), round(c[1], 1)) for c in pp}) == 1:
                    return (pp[0][0], pp[0][1], 3000), s, "gnis"
        return None

    regions = []
    for line in open(regions_p, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f_ = line.rstrip("\n").split("|")
        pat, scope, place, st, rad, note = f_[:6]
        dates = f_[6].split("..") if len(f_) > 6 and f_[6].strip() else None      # army snapshot: only tables in this window
        cav = len(f_) > 7 and f_[7].strip() == "cavalry"                          # this camp line is for the army's cavalry
        if "@" in place:                       # "Georgetown@33.3768,-79.2945": GNIS has several, coordinates given
            place, ll = place.split("@"); la, lo = map(float, ll.split(","))
            loc = ((la, lo, 3000), st, "given")
        else:
            loc = locate(place, [st])
        if not loc:
            print("region place not located:", place, st); continue
        rx = re.compile("|".join(f"(?:{p})" for p in pat.split(";")), re.I)
        regions.append((rx, re.compile(scope, re.I) if scope else None, place, st, loc[0][0], loc[0][1], int(rad) * 1000, note,
                        dates, cav))

    tables = {f"{t['book']}:{t['start']}": t for t in map(json.loads, open(tables_p, encoding="utf-8"))}
    tov = {}                                      # hand-checked table dates (data/or/table_overrides.psv), as or_to_claims
    ovp = Path(tables_p).parent / "table_overrides.psv"
    if ovp.exists():
        for line in open(ovp, encoding="utf-8"):
            if line.strip() and not line.startswith("#"):
                tid_, s_, e_ = line.split("|")[:3]
                tov[tid_] = (s_, e_)
    claims, stats, units = [], Counter(), set()
    for l in open(pl_p, encoding="utf-8"):
        r = json.loads(l)
        code = r.get("unit_code") or ""
        if not code or code.startswith("AMB") or not r.get("date_start") or r["side"] not in ("Union", "Confederate"):
            continue
        t = tables[r["table_id"]]
        if r["table_id"] in tov:
            r["date_start"], r["date_end"] = tov[r["table_id"]]
        head = " ".join(t["heading"].split())
        if r.get("detached"):
            continue                              # listed with the army but away from it (table footnote)
        if re.search(r"\bbattle\b|engaged|\bcampaign\b|during the|operations", head, re.I):
            continue                              # a battle's order of battle: the battle itself places the units
        hstates = list(dict.fromkeys(v for k, v in STATE_WORDS.items() if re.search(rf"\b{k}\b", head)))
        hit, win = None, None
        if r.get("station"):
            name, st = split_place(r["station"])
            lone = " " not in name and not st and not re.match(r"(Fort|Camp|Post|Garrison|Defenses|Forces|Troops|At)\b", r["station"])
            if lone and norm(name) not in famous:
                stats["lone word, not a well-known place: skipped"] += 1      # "Jones." is usually a wrapped surname
            elif len(name) >= 3 and not re.fullmatch(r"[A-Z .']+", name):
                bare = not st and not re.match(r"(Fort|Camp|Post|Garrison|Defenses|Forces|Troops|At)\b", r["station"])
                states = [st] if st else hstates + ([ustate.get(code)] if ustate.get(code) and not (bare and " " not in name) else [])
                # a one-word bare name ("Jones") only in a state the heading names: lone words are often wrapped surnames
                loc = locate(name, [s for s in states if s])
                if loc:
                    (lat, lon, prec), s, how = loc
                    hit = ("station", r["station"], name, s, lat, lon, prec, how)
                else:
                    stats["station not located"] += 1
        if not hit and r["side"] == "Confederate":
            for txt in (r.get("division"), r.get("corps"), head):
                if not txt:
                    continue
                for rx, scope, place, st, lat, lon, rad, note, dates, cav in regions:
                    if dates and not (dates[0] <= r["date_start"][:10] <= dates[1]):
                        continue
                    is_cav = bool(re.search(r"cavalry|horse artillery", f"{r.get('corps')} {r.get('division')} {r.get('brigade')}", re.I))
                    if dates and is_cav != cav:
                        continue                  # an army's cavalry camps apart and wider: its own lines (8th field "cavalry")
                    if rx.search(txt) and (scope is None or scope.search(head)):
                        hit = ("region", txt, place, st, lat, lon, rad, "or_regions.psv")
                        win = "..".join(dates) if dates else None
                        break
                if hit:
                    break
        if not hit:
            stats["no position"] += 1
            continue
        kind, text, pname, pst, lat, lon, prec, how = hit
        stats[f"{r['side']} {kind}"] += 1
        units.add(code)
        claims.append({"type": "unit_at", "source": "or", "confidence": 0.75 if kind == "station" else 0.6,
                       "span": f"{t.get('volume')}: {head[:150]} | {text[:80]} | {r['unit'][:80]}",
                       "extracted_by": "rules:or_stations_v1",
                       "note": f"OR table {r['table_id']} ({kind}; located via {how})",
                       "unit": {"nps_code": code, "display_name": r["unit"], "side": r["side"]},
                       "unit_mention": r["unit"], "place_mention": text[:120],
                       "place": {"display_name": pname, "state": pst, "lat": lat, "lon": lon, "precision_m": prec,
                                 "kind": "town" if kind == "station" else "region"},
                       "presence": "present", "portion": portion(r),
                       "date_start": r["date_start"], "date_end": r["date_end"], "date_precision": "day", "_win": win})
    # Consecutive returns that put a unit at the same post or district (<= 92 days apart, no other return between) are
    # read as one stay from the first to the last: a garrison between monthly returns. Month precision, so the map
    # draws it as a loose stay; anything dated more finely (a battle) wins on its own days.
    by_unit = defaultdict(list)
    for c in claims:
        by_unit[c["unit"]["nps_code"]].append(c)
    stays = []
    for code, cs in by_unit.items():
        cs.sort(key=lambda c: c["date_start"])
        run = [cs[0]]
        for c in cs[1:] + [None]:
            if c is not None and c["date_start"] == run[-1]["date_start"]:
                continue                                  # two tables of the same date
            same = c is not None and (c["place"]["display_name"], c["place"]["state"]) == \
                (run[-1]["place"]["display_name"], run[-1]["place"]["state"])
            from datetime import date as _d, timedelta
            # an army's snapshots within one camp window (or_regions.psv dates) merge whatever the gap: the army stayed
            if same and ((_d.fromisoformat(c["date_start"]) - _d.fromisoformat(run[-1]["date_end"])).days <= 92 or
                         c["_win"] and c["_win"] == run[-1]["_win"]):
                run.append(c); continue
            if run and (len(run) >= 2 or run[0]["_win"]):
                a, b = run[0], run[-1]
                d0, d1 = a["date_start"], b["date_end"]
                if a["_win"] and a["_win"] == b["_win"]:
                    # an army snapshot in its camp window: the stay reaches up to 45 days beyond the first and last
                    # snapshot, within the window (units came and went: Longstreet's return, Hoke to North Carolina)
                    w0, w1 = a["_win"].split("..")
                    d0 = max(w0, (_d.fromisoformat(d0) - timedelta(45)).isoformat())
                    d1 = min(w1, (_d.fromisoformat(d1) + timedelta(45)).isoformat())
                st = dict(a, confidence=0.5, extracted_by="rules:or_stations_v1:stay", date_start=d0,
                          date_end=d1, date_precision="month",
                          note=f"{len(run)} consecutive returns at {a['place']['display_name']}: {a['note']} ... {b['note']}",
                          span=f"{a['span'][:140]} ... {b['span'][:140]}")
                stays.append(st)
            run = [c] if c is not None else []
    stats["stays (consecutive returns merged)"] = len(stays)
    claims += stays
    for c in claims:
        c.pop("_win", None)
    doc = {"about": "Unit positions from Official Records organization tables (posts and districts), by pipeline/or_stations.py.",
           "sources": {"or": {"title": "The War of the Rebellion: Official Records, Series I (organization tables and department returns)",
                              "kind": "official_records", "url": "https://archive.org/details/warofrebellion", "public_domain": 1,
                              "notes": "post lines located with data/places/geocoded.csv and USGS GNIS; districts with data/manual/or_regions.psv"}},
           "claims": claims}
    json.dump(doc, open(out_p, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print(dict(stats))
    by = Counter((c["unit"]["side"]) for c in claims)
    print("claims", len(claims), dict(by), "units", len(units))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("or_stations")))
