"""Inventory distinct places (name + state) mentioned in Dyer's, ready for geocoding.

Usage:
  python3 pipeline/places_inventory.py data/dyers data/events data/places

Sources:
  index   Dyer's Part II alphabetical index (place + state per event)
  unit_at "Organized at / Moved to / Duty at" claims (place_mention)
  event   event names for events with no Dyer's index link ("Action at X, Ala")
Steps: clean OCR and abbreviations; split "A and B" / "via"; drop non-places
("Mustered out", "join Pope"); classify point / region / state; fill missing
states from the unit's previous mention (unit_context) or from the name's only
state elsewhere (global, when one state has 80%+ of stated uses).
Outputs: places_inventory.csv (one row per place), place_mentions.jsonl
(each mention -> place_key), places_report.txt.
"""
import collections, csv, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parse_event_index import STATES  # abbreviation -> postal code

FULL = {"alabama": "AL", "arkansas": "AR", "california": "CA", "colorado": "CO", "connecticut": "CT",
        "delaware": "DE", "florida": "FL", "georgia": "GA", "illinois": "IL", "indiana": "IN", "iowa": "IA",
        "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
        "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
        "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
        "new york": "NY", "north carolina": "NC", "ohio": "OH", "oregon": "OR", "pennsylvania": "PA",
        "rhode island": "RI", "south carolina": "SC", "tennessee": "TN", "texas": "TX", "vermont": "VT",
        "virginia": "VA", "west virginia": "WV", "wisconsin": "WI", "dakota": "DT", "indian territory": "IT",
        "arizona": "AZ", "district of columbia": "DC", "utah": "UT", "idaho": "ID", "montana": "MT",
        "washington territory": "WA"}
STATES = dict(STATES, **{"n h": "NH", "r i": "RI", "d c": "DC"})
ST_RE = re.compile(r"(?:,\s*|\s+)(" + "|".join(sorted((re.escape(k).replace(r"\ ", r"\.?\s*") for k in STATES),
                   key=len, reverse=True)) + r")\.?\s*$", re.I)
NOT_PLACE = re.compile(r"^(disbanded|called|discharg|bombardment|hood |jackson up|price |forrest |morgan |wheeler |operations|"
                       r"mustered|muster|join|duty|garrison|guard|provost|consolidated|discharged|transferred|"
                       r"attached|reorganized|organized|veteranized|on |in |at |the field|field|front|home|"
                       r"various|points|line of|camp near|headquarters|post|picket|scout|patrol|outpost)", re.I)
REGION = re.compile(r"\b(valley|department|district|region|county|counties|parish|mountains|river|bayou|"
                    r"island|coast|sound|peninsula|territory|swamp|line|lines|defences|defenses)\b", re.I)
EVENT_LEAD = re.compile(r"^(?:(?:and|line of|on line of|flank movement|investment and|advance on and|battles?|actions?|skirmish(?:es)?|engagements?|combats?|affairs?|assaults?|"
                        r"attacks?|siege|capture|surrender|defen[cs]e|occupation|demonstrations?|expedition|"
                        r"reconnoi?ssance|scouts?|raids?|pursuit|advance|operations?|movement|march|near|about|"
                        r"before|investment|evacuation|fall|repulse)\s+(?:of|at|on|to|from|near|about|against|"
                        r"upon|toward|towards|in)?\s*)+", re.I)


def clean(s):
    s = (s or "").replace("„", ",").replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s).strip(" .;:-'\"()")
    s = re.sub(r"^(the|a)\s+", "", s, flags=re.I)
    s = re.sub(r"^(defen[cs]es|vicinity|neighborhood|works|trenches|fortifications) of\s+", "", s, flags=re.I)
    s = re.sub(r"\bFt\.?\s+", "Fort ", s)
    s = re.sub(r"\bMt\.?\s+", "Mount ", s)
    s = re.sub(r"\bC\.\s*H\b\.?", "Court House", s)
    s = re.sub(r"\bSta\.?(?=\s|$|,)", "Station", s)
    s = re.sub(r"\bX\s*Roads\b", "Cross Roads", s)
    return s.strip(" .,;")


def split_state(s):
    m = ST_RE.search(s)
    if m:
        key = re.sub(r"[^a-z]+", " ", m.group(1).lower()).strip()
        return s[:m.start()].strip(" ,."), STATES.get(key)
    return s, None


def parts_of(mention):
    s = clean(mention)
    s = re.split(r",?\s+(?:for|to join|to report|to guard|to protect|to reinforce|on duty|and duty)\s+", s)[0]
    s = re.split(r"\.\s+[A-Z][a-z]+ing\b", s)[0]           # "City Point, Va. Occupying ..." -> cut
    out = []
    for p in re.split(r",?\s+via\s+|;\s*|\s+and\s+thence\s+|,?\s+thence\s+|,?\s+and\s+(?=[A-Z])", s):
        p = clean(p)
        m = re.search(r"(?:^|,\s*|\s)near\s+(.+)$", p)
        if m and m.group(1)[:1].isupper():
            p = clean(m.group(1))                          # "Livingston Road, near Clinton" -> "Clinton"
        if p:
            out.append(p)
    return out


MILITARY = re.compile(r"\b(?:army|corps|brigade|division|dept|regiment|battalion|battery|company|companies|detachments?|"
                      r"mustered|attached|duty|guard|between)\b|^(?:january|february|march|april|may|june|july|august|september|october|"
                      r"november|december)\b", re.I)


def _state_token(t):
    k = re.sub(r"[^a-z]+", " ", t.lower()).strip()
    return STATES.get(k) or FULL.get(k)


def places_of(mention):
    """Places of a unit_at mention with the state each was written with: [(name, state, state_source)].
    Splits like parts_of, and also comma lists ("Carrollton, Brashear City and Berwick"); a list item without a state
    takes the state written later in the same list ("Norfolk and Portsmouth, Va": state_source 'list', a preference
    for the route resolution, not a limit). Lists are not crossed by via / thence (separate legs of a move)."""
    s = clean(mention)
    s = re.split(r",?\s+(?:for|to join|to report|to guard|to protect|to reinforce|on duty|and duty)\s+", s)[0]
    s = re.split(r"\.\s+[A-Z][a-z]+ing\b", s)[0]
    out = []
    for leg in re.split(r",?\s+via\s+|;\s*|\s+and\s+thence\s+|,?\s+thence\s+", s):
        leg = re.sub(r"^(?:and\s+)?(?:(?:march(?:ed)?|moved?|proceed(?:ed)?|return(?:ed)?|went)\s+)?(?:to|by)\s+", "", leg.strip(), flags=re.I)
        items = []
        for piece in re.split(r",?\s+and\s+(?=[A-Z])", leg):
            for j, t in enumerate(re.split(r",\s*", piece)):
                t = clean(re.sub(r"^(?:at|in)\s+(?=[A-Z])", "", t.strip(), flags=re.I))
                if not t or MILITARY.search(t):
                    continue
                st = _state_token(t)
                if st and j > 0 and items and items[-1][1] is None:   # "Covington, Ky" (not "Tennessee and Alabama")
                    items[-1] = (items[-1][0], st, "explicit")
                    continue
                m = re.search(r"(?:^|\s)near\s+(.+)$", t)
                if m and m.group(1)[:1].isupper():
                    t = clean(m.group(1))                  # "Livingston Road, near Clinton" -> "Clinton"
                    if items and m.start() == 0:
                        items.pop()
                name, st2 = split_state(t)
                items.append((name, st2, "explicit" if st2 else None))
        # a state written once, at the end of the list, applies to the items before it ("Covington, Lexington and
        # Danville, Ky"); not when other items carry states ("Cape Girardeau, Fort Holt, Ky., and Elliott's Mills")
        if len(items) > 1 and items[-1][1] and not any(it[1] for it in items[:-1]):
            items = [(n, items[-1][1], "list") if n.lower() not in FULL else (n, st, src) for n, st, src in items[:-1]] + items[-1:]
        out += [it for it in items if it[0]]
    return out


def classify(name, state):
    low = name.lower()
    if low in FULL:
        return "state", FULL[low]
    if REGION.search(name):
        return "region", state
    return "point", state


def key_of(name, state):
    k = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("'s", "s"))
    k = re.sub(r"\b(saint|st)\b", "st", k)
    return re.sub(r"\s+", " ", k).strip() + "|" + (state or "?")


def main(dyers_dir, events_dir, out_dir):
    dy, out = Path(dyers_dir), Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    mentions = []                        # dicts: name, state, state_source, source, unit, date, raw
    for l in open(dy / "event_index.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r.get("place"):
            name = clean(r["place"])
            mentions.append({"name": name, "state": r.get("state"), "state_source": "explicit" if r.get("state") else None,
                             "source": "index", "unit": None, "date": r.get("date_start"), "raw": r["raw"][:80]})
    last_state, seeds = {}, []
    for l in open(dy / "claims_rules.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["claim_type"] != "unit_at" or not r.get("place_mention"):
            continue
        for name, st, src in places_of(r["place_mention"]):
            if NOT_PLACE.search(name) or len(name) < 3 or not name[0].isupper():
                continue
            ctx = last_state.get(r["unit_id"]) if not st and name.lower() not in FULL else None
            if src == "explicit":
                last_state[r["unit_id"]] = st
            mentions.append({"name": name, "state": st, "state_source": src, "source": "unit_at", "ctx_state": ctx,
                             "unit": r["unit_id"], "date": r.get("date_start"), "raw": r["place_mention"][:80],
                             **({"arrival": r["date_end"]} if r.get("presence") == "en_route" and r.get("date_end")
                                and r.get("date_end") != r.get("date_start") else {})})
    # state context for events: where were the event's regiments (unit_at, within 30 days)?
    from datetime import date as _date
    def _d(s):
        s = (s or "")[:10]
        s = s + "-01" if len(s) == 7 else s
        try:
            return _date.fromisoformat(s)
        except ValueError:
            return None
    unit_states = collections.defaultdict(list)
    for m in mentions:
        if m["source"] == "unit_at" and m["state"] and m["state_source"] == "explicit" and _d(m["date"]):
            unit_states[m["unit"]].append((_d(m["date"]), m["state"]))
    c2e = {}
    for l in open(Path(events_dir) / "cluster_to_event.jsonl", encoding="utf-8"):
        r = json.loads(l); c2e[r["cluster_id"]] = r["event_id"]
    ev_units = collections.defaultdict(set)
    for l in open(dy / "mention_to_event.jsonl", encoding="utf-8"):
        r = json.loads(l); ev_units[c2e.get(r["cluster_id"])].add(r["unit_id"])
    def context_state(eid, day):
        day = _d(day); c = collections.Counter()
        if not day:
            return None
        for u in ev_units.get(eid, ()):
            for dd, st in unit_states.get(u, ()):
                if abs((dd - day).days) <= 30:
                    c[st] += 1
        if c:
            st, n = c.most_common(1)[0]
            if n >= 5 and n / sum(c.values()) >= 0.7:
                return st
        return None

    # reference points: located events whose state is known (from Dyer's index or the name itself)
    import math
    ev_all = [json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")]
    refs = []
    for e in ev_all:
        if e.get("lat") is not None and e.get("coord_source") == "wikidata":
            st = e.get("state") or split_state(clean(e.get("dyer_name") or ""))[1]
            if st:
                refs.append((e["lat"], e["lon"], st))
    def nearest_state(lat, lon, max_km=60):
        best = None
        for la, lo, st in refs:
            dkm = 111 * math.hypot(la - lat, (lo - lon) * math.cos(math.radians(lat)))
            if dkm <= max_km and (best is None or dkm < best[0]):
                best = (dkm, st)
        return best[1] if best else None

    for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if not e["clusters"] or e.get("kind") in ("campaign", "march", "admin", "review", "pursuit", "raid"):
            continue
        nm = clean(EVENT_LEAD.sub("", clean(e.get("dyer_name") or e["name"])))
        if not nm or re.search(r"'s\b|campaign|expedition|march|mustered|regiment", nm, re.I):
            continue
        nm = re.split(r"\s+and\s+(?:against|battles?|siege|capture|fall)\b|,\s*(?:and\s+)?battles?\s+about\b", nm)[0]
        for p in parts_of(nm)[:1]:
            name, st = split_state(p)
            if not st and not e.get("state"):
                cs_ = nearest_state(e["lat"], e["lon"]) if e.get("lat") is not None else None
                if cs_:
                    e["state"], e["_ctx"] = cs_, "event_nearby"
                else:
                    cs_ = context_state(e["event_id"], e["date_start"])
                    if cs_:
                        e["state"], e["_ctx"] = cs_, "event_units"
            if e.get("lat") is not None:
                seeds.append((name, st or e.get("state"), e["lat"], e["lon"], e.get("coord_source"), e["event_id"], e["name"]))
            mentions.append({"name": name, "state": st or e.get("state"), "state_source": "explicit" if st else (e["_ctx"] if e.get("_ctx") else ("event" if e.get("state") else None)),
                             "source": "event", "unit": None, "date": e["date_start"], "raw": e.get("dyer_name", "")[:80],
                             "event_id": e["event_id"], "weight": e["mentions"]})

    mentions = [m for m in mentions if m["name"][:1].isupper() and not NOT_PLACE.search(m["name"]) and len(m["name"]) >= 3]
    # global state fill: a name whose stated uses are 80%+ one state
    by_name = collections.defaultdict(collections.Counter)
    for m in mentions:
        if m["state"]:
            by_name[key_of(m["name"], None)][m["state"]] += 1
    for m in mentions:
        if not m["state"]:
            c = by_name.get(key_of(m["name"], None))
            if c:
                st, n = c.most_common(1)[0]
                if n / sum(c.values()) >= 0.8:
                    m["state"], m["state_source"] = st, "global"
                    continue
            if m.get("ctx_state") and not c:
                m["state"], m["state_source"] = m["ctx_state"], "unit_context"
            elif m.get("ctx_state") and c and m["ctx_state"] in c:
                m["state"], m["state_source"] = m["ctx_state"], "unit_context_ambiguous"   # Alexandria + unit in VA -> VA

    places = {}
    for m in mentions:
        kind, st = classify(m["name"], m["state"])
        m["state"] = st
        k = key_of(m["name"], st)
        m["place_key"] = k
        p = places.setdefault(k, {"place_key": k, "name": collections.Counter(), "state": st or "", "kind": kind,
                                  "mentions": 0, "index": 0, "unit_at": 0, "event": 0, "units": set(),
                                  "first": None, "last": None, "state_sources": collections.Counter()})
        w = m.get("weight", 1)
        p["name"][m["name"]] += 1; p["mentions"] += w; p[m["source"]] += w
        p["state_sources"][m["state_source"] or "none"] += 1
        if m["unit"]: p["units"].add(m["unit"])
        if m["date"]:
            p["first"] = min(p["first"] or m["date"], m["date"]); p["last"] = max(p["last"] or m["date"], m["date"])

    for name, st, lat, lon, src, eid, ename in seeds:
        k = key_of(name, st)
        if k not in places:
            # event name gave no state: attach to the single stated place with that name, if unique
            cands = [q for q in places if q.startswith(key_of(name, None)[:-1]) and q.split("|")[0] == key_of(name, None).split("|")[0]]
            if len(cands) == 1:
                k = cands[0]
            else:
                continue
        p = places[k]
        rank = {"wikidata": 2, "ai_approx": 1}.get(src, 0)
        if rank > p.get("seed_rank", 0):
            p.update(seed_lat=lat, seed_lon=lon, seed_source=src, seed_event=f"{eid} {ename}", seed_rank=rank)
    rows = sorted(places.values(), key=lambda p: -p["mentions"])
    with open(out / "places_inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["place_key", "name", "state", "kind", "mentions", "from_index", "from_unit_at", "from_events",
                    "units", "first", "last", "state_source", "variants", "seed_lat", "seed_lon", "seed_source", "seed_event"])
        for p in rows:
            w.writerow([p["place_key"], p["name"].most_common(1)[0][0], p["state"], p["kind"], p["mentions"],
                        p["index"], p["unit_at"], p["event"], len(p["units"]), p["first"] or "", p["last"] or "",
                        p["state_sources"].most_common(1)[0][0], "; ".join(n for n, _ in p["name"].most_common(4)),
                        p.get("seed_lat", ""), p.get("seed_lon", ""), p.get("seed_source", ""), p.get("seed_event", "")])
    with open(out / "place_mentions.jsonl", "w", encoding="utf-8") as f:
        for m in mentions:
            f.write(json.dumps({k: v for k, v in m.items() if v is not None}, ensure_ascii=False) + "\n")

    tot = sum(p["mentions"] for p in rows)
    cum, curve = 0, []
    for i, p in enumerate(rows, 1):
        cum += p["mentions"]
        if i in (100, 500, 1000, 2000, 5000):
            curve.append(f"top {i}: {100*cum/tot:.0f}%")
    kinds = collections.Counter(p["kind"] for p in rows)
    ss = collections.Counter(m["state_source"] or "none" for m in mentions)
    rep = [f"Place mentions: {len(mentions)} (index {sum(1 for m in mentions if m['source']=='index')}, "
           f"unit_at {sum(1 for m in mentions if m['source']=='unit_at')}, events {sum(1 for m in mentions if m['source']=='event')})",
           f"Distinct places (name + state): {len(rows)}; kinds: " + ", ".join(f"{k} {v}" for k, v in kinds.items()),
           "Coverage of weighted mentions: " + ", ".join(curve),
           "State source per mention: " + ", ".join(f"{k} {v}" for k, v in ss.most_common()),
           f"Places with no state: {sum(1 for p in rows if not p['state'])} "
           f"({sum(p['mentions'] for p in rows if not p['state'])} weighted mentions)",
           f"Places with seed coordinates from located events: {sum(1 for p in rows if p.get('seed_source')=='wikidata')} from Wikidata, "
           f"{sum(1 for p in rows if p.get('seed_source')=='ai_approx')} AI approx; covering "
           f"{100*sum(p['mentions'] for p in rows if p.get('seed_source'))/tot:.0f}% of weighted mentions",
           "", "Top 40 places:"]
    rep += [f"  {p['mentions']:6d}  {p['name'].most_common(1)[0][0]}, {p['state'] or '?'}  [{p['kind']}]{'  @'+p['seed_source'] if p.get('seed_source') else ''}" for p in rows[:40]]
    (out / "places_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*sys.argv[1:4])
