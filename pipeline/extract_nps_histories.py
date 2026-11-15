"""Dated positions from the NPS unit histories of Confederate units (Crute, Units of the Confederate States Army,
via the NPS Soldiers and Sailors Database; data/nps/units.jsonl "overview").

The histories are short prose: "organized at Griffin, Georgia, in May, 1862", "served at Mobile until April, 1864",
"moved to Virginia", "surrendered on April 26, 1865". Sentence by sentence, an action word (organized, served
or stationed until, surrendered; moved, captured and disbanded are skipped: their dates too often belong to another
clause) with a place within 60 characters after it and a month or day date
becomes a unit_at claim. Places are located like Dyer's places (data/places/geocoded.csv first, then GNIS in the
named state, else the unit's state); a state or region alone is not a position. "Surrendered on <date>" with no
place takes the army's surrender place for that date (Appomattox, Greensboro, Citronelle, Gainesville).

Writes data/derived/nps_confederate_histories.json (manual claims format; loaded by build_db via manual_claims.py)
and a report. Usage: python pipeline/extract_nps_histories.py data/nps/units.jsonl data/places/geocoded.csv \
    data/external/gnis/gnis_index.tsv data/derived/nps_confederate_histories.json
"""
import csv, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
from gnis_index import norm  # noqa: E402
from common import gnis_by_name_state  # noqa: E402

MON = "January|February|March|April|May|June|July|August|September|October|November|December"
MN = {m: i + 1 for i, m in enumerate(MON.split("|"))}
SEASON = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 2)}
STATES = cwv_states.table("Name", "CODE", "AL", "AR", "FL", "GA", "KY", "LA", "MD", "MS", "MO", "NC", "SC", "TN",
                                          "TX", "VA", "WV", ("Indian Territory", "OK"), "AZ", "NM", "PA", "OH", "IN",
                                          "KS")
SURRENDER = {  # date -> (place, state, lat, lon): the main surrenders
    "1865-04-09": ("Appomattox Court House", "VA", 37.3771, -78.7964),
    "1865-04-26": ("Greensboro", "NC", 36.0726, -79.7920),
    "1865-05-04": ("Citronelle", "AL", 31.0907, -88.2281),
    "1865-05-09": ("Gainesville", "AL", 32.8204, -88.1606)}
ACT = [("organized", r"\b(?:was|were) (?:organized|assembled|formed|raised|recruited|mustered into (?:Confederate|state) service)|\borganized\b"),
       ("served", r"\b(?:served|stationed|garrisoned|on duty|remained|was posted|was on duty|performed (?:garrison|picket|provost) duty)\b"),
       ("moved", r"\b(?:moved|ordered|transferred|sent|marched|went)\b"),
       ("captured", r"\bcaptured\b"),
       ("disbanded", r"\b(?:disbanded|broken up)\b"),
       ("surrendered", r"\b(?:surrendered|paroled)\b")]
NOTPLACE = re.compile(r"^(?:Army|Department|District|Division|Brigade|Corps|Battalion|Regiment|Company|Legion|Confederate|"
                      r"General|Colonel|Captain|Major|Lieutenant|the|The|State|Trans|Seven|Battle|Battles|Campaign|Expedition|"
                      r"Reserve|Provisional|Home|Local|Partisan|Field|Light|Heavy|Artillery|Infantry|Cavalry|Mounted|Union|Federal|"
                      r"North|South|East|West|Northern|Southern|Eastern|Western|Gulf|Coast|Valley|Peninsula|Military|C\.S\.A|CSA|"
                      r"Indian|Missouri State Guard|" + MON + r")\b")


def dates(s):
    out = []
    for m in re.finditer(rf"\b({MON}) (\d{{1,2}}), (186\d)", s):
        out.append((m.start(), f"{m.group(3)}-{MN[m.group(1)]:02d}-{int(m.group(2)):02d}", "day"))
    for m in re.finditer(rf"\b({MON}),? (186\d)", s):
        if not any(a <= m.start() <= a + 3 for a, _, _ in out):
            out.append((m.start(), f"{m.group(2)}-{MN[m.group(1)]:02d}", "month"))
    for m in re.finditer(r"\b(spring|summer|fall|autumn|winter) of (186\d)", s, re.I):
        a, b = SEASON[m.group(1).lower()]
        out.append((m.start(), f"{m.group(2)}-{a:02d}", "season"))
    return sorted(out)


def places(s):
    out = []
    for m in re.finditer(r"\b(?:at|near|in|to|around|from|on)\s+((?:[A-Z][A-Za-z'’\.]+)(?:\s+(?:[A-Z][A-Za-z'’\.]+|of|de|la))*)(?:,\s*(" + "|".join(STATES) + r"))?", s):
        name, st = m.group(1).strip(" .,"), m.group(2)
        if NOTPLACE.match(name) or name in STATES or len(name) < 3:
            continue
        if re.search(r"\b(?:County|Counties|Parish)\b", name) or re.search(r"^\s*(?:County|Counties|Parish)\b", s[m.end():m.end() + 10]):
            continue                      # "men from Jackson County": where men came from, not a position
        out.append((m.start(), name, STATES.get(st) if st else None))
    return out


def main(units_p, geocoded_p, gnis_p, out_p):
    geo, famous = {}, {}
    for g in csv.DictReader(open(geocoded_p, encoding="utf-8")):
        if g["lat"] and g["method"] in ("override", "seed", "gnis"):
            geo[(norm(g["name"]), g["state"])] = (float(g["lat"]), float(g["lon"]), int(float(g["precision_m"])))
            mn = int(g["mentions"] or 0)
            if mn >= 40 and mn > famous.get(norm(g["name"]), ("", 0))[1]:
                famous[norm(g["name"])] = (g["state"], mn)     # "Vicksburg" alone is Vicksburg, Miss.
    G = gnis_by_name_state(gnis_p, ("Populated Place", "Military", "Civil", "Crossing", "Gap", "Island"))

    def locate(name, st, explicit, text_states):
        if not explicit and norm(name) in famous:
            st = famous[norm(name)][0]
            return geo[(norm(name), st)] + ("dyers",)
        order = [st] if explicit else []
        order += [x for x in text_states if x not in order] + ([st] if st and st not in order else [])
        order += ["WV"] if "VA" in order and "WV" not in order else []
        for s in order:
            k = (norm(name), s)
            if k in geo:
                return geo[k] + ("dyers",)
            cs = G.get(k) or G.get((norm(re.sub(r"^Fort\b", "Ft", name)), s)) or []
            pp = [c for c in cs if c[2] == "Populated Place"] or cs
            if len(pp) == 1 or (pp and len({(round(c[0]), round(c[1])) for c in pp}) == 1):
                return (pp[0][0], pp[0][1], 3000, "gnis")
        return None

    claims, stats = [], Counter()
    for l in open(units_p, encoding="utf-8"):
        u = json.loads(l)
        if u["side"] != "Confederate" or u.get("empty") or not u.get("overview"):
            continue
        stats["histories"] += 1
        text = re.sub(r"\s+", " ", u["overview"])
        text_states = [STATES[m] for m in re.findall("|".join(STATES), text)]
        text_states = list(dict.fromkeys(text_states))
        last_date = None
        for sent in re.split(r"(?<=[a-z0-9\)])\.\s+(?=[A-Z])", text):
            acts = [a for a, rx in ACT if re.search(rx, sent)]
            ds, ps = dates(sent), places(sent)
            if not acts:
                if ds:
                    last_date = ds[-1]
                continue
            if re.search(r"\bbattles\b|\bfrom [A-Z][\w' ]+ to [A-Z]", sent) and "surrender" not in sent:
                stats["battle list, not a position"] += 1
                if ds:
                    last_date = ds[-1]
                continue
            act = acts[0]
            for a in acts:
                if a == "surrendered":
                    act = a
            when = None
            if act == "served":
                m = re.search(rf"\buntil (?:the )?(?:(spring|summer|fall|autumn|winter) of (186\d)|({MON}),? (186\d)|(186\d))", sent)
                if m:
                    if m.group(3):
                        end = f"{m.group(4)}-{MN[m.group(3)]:02d}"
                    elif m.group(1):
                        end = f"{m.group(2)}-{SEASON[m.group(1).lower()][0]:02d}"
                    else:
                        end = None
                    start = (ds[0][1] if ds and ds[0][1] < (end or "9") else (last_date[1] if last_date else None))
                    if end:
                        when = (start or end, end, "month")
            if not when and ds:
                when = (ds[0][1], ds[0][1], "day" if ds[0][2] == "day" else "month")
            if ds:
                last_date = ds[-1]
            if act == "surrendered" and when and when[0] in SURRENDER and not ps:
                nm, st, lat, lon = SURRENDER[when[0]]
                ps = [(0, nm, st)]
                fixed = (lat, lon, 3000, "surrender")
            else:
                fixed = None
            if not when or not ps:
                stats[f"{act}: no {'date' if not when else 'place'}"] += 1
                continue
            if act in ("moved", "captured", "disbanded"):
                stats[f"{act}: skipped (dates too often belong to another clause)"] += 1
                continue
            kw = re.search(dict(ACT)[act], sent)
            after = [p for p in ps if kw and kw.start() < p[0] <= kw.end() + 60]
            if not after and not fixed:
                stats[f"{act}: no place right after the verb"] += 1
                continue
            _, pname, pst = (after or ps)[0]
            loc = fixed or locate(pname, pst or u["state"], bool(pst), text_states)
            if not loc:
                stats[f"{act}: place not located"] += 1
                continue
            stats[f"{act}: claim"] += 1
            a, b, prec = when
            claims.append({"type": "unit_at", "source": "nps", "span": sent[:300], "confidence": 0.5 if act == "moved" else 0.7,
                           "extracted_by": "regex:nps_histories_v1",
                           "unit": {"nps_code": u["unit_code"], "display_name": u["name"], "side": "Confederate"},
                           "unit_mention": u["name"], "place_mention": pname,
                           "place": {"display_name": pname, "state": pst or (famous[norm(pname)][0] if norm(pname) in famous and not pst else u["state"]), "lat": loc[0], "lon": loc[1],
                                     "precision_m": loc[2], "kind": "town"},
                           "presence": "present", "portion": "whole",
                           "date_start": a, "date_end": b, "date_precision": "day" if prec == "day" else "month"})
    doc = {"about": "Dated positions extracted from the NPS Soldiers and Sailors Database unit histories of Confederate units "
                    "(from Crute, Units of the Confederate States Army) by pipeline/extract_nps_histories.py.",
           "sources": {"nps": {"title": "NPS Soldiers and Sailors Database: Confederate unit histories (from Crute)",
                               "kind": "government_list", "url": "https://www.nps.gov/civilwar/search-battle-units.htm",
                               "public_domain": 1, "notes": "regex extraction; places located with data/places/geocoded.csv and USGS GNIS"}},
           "claims": claims}
    json.dump(doc, open(out_p, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print(dict(stats)); print("claims", len(claims), "units", len({c['unit']['nps_code'] for c in claims}))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("extract_nps_histories")))
