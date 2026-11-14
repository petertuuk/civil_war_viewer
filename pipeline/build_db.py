"""Build the claims database (SQLite) from every pipeline output.

Usage: python3 pipeline/build_db.py <project dir> <output .db path>
Applies pipeline/schema.sql (v0.2) + pipeline/schema_v03.sql, then loads:
  entities  sides; units (Dyer's units, linked to NPS codes; NPS units not in Dyer's); events (merged events,
            parents, Wikidata ids); places (places inventory + event locations); persons (commander mentions)
  claims    Dyer's (claims_rules.jsonl), Official Records (claims_or.jsonl), Wikipedia (claims_wikipedia.jsonl), NPS battle unit lists (claims_nps_battles.jsonl),
            event locations (event_at, from Wikidata / Wikipedia / AI), event names (known_as)
Resolution done here: unit ids through external_id; participated -> event through the pipeline's
mention_to_event / cluster_to_event (Dyer's) or event_id (OR, Wikipedia); unit_at -> place through place_mentions;
commanders -> person by normalized name and side (no fuzzy merging yet).
"""
import csv, json, re, sqlite3, sys, time
from datetime import date, timedelta
import nps_links
from collections import Counter, defaultdict
collections_Counter = Counter
from pathlib import Path

NOW = time.strftime("%Y-%m-%dT%H:%M:%S")
ST = {"ALABAMA": "AL", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DAKOTA": "DT",
      "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "ILLINOIS": "IL", "INDIANA": "IN",
      "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
      "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "NEBRASKA": "NE",
      "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
      "OHIO": "OH", "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "TENNESSEE": "TN",
      "TEXAS": "TX", "VERMONT": "VT", "VIRGINIA": "VA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WASHINGTON TERRITORY": "WA",
      "U.S. COLORED TROOPS": "US", "U.S. REGULAR ARMY": "UR", "U.S. VETERAN RESERVE CORPS": "VR", "U.S. VOLUNTEERS": "UV",
      "U.S. VETERAN VOLUNTEERS": "UV", "CORPS D'AFRIQUE": "US", "DAKOTA TERRITORY": "DT"}
EVENT_KIND = {"campaign": "campaign", "battle": "battle", "siege": "siege", "operations": "operation", "march": "march",
              "expedition": "expedition", "raid": "expedition", "pursuit": "operation", "demonstration": "operation",
              "reconnaissance": "operation", "combat": "engagement", "engagement": "engagement", "action": "engagement",
              "skirmish": "engagement", "assault": "engagement", "affair": "engagement", "capture": "engagement",
              "occupation": "operation", "surrender": "political", "review": "political", "admin": "other",
              "engineering": "operation", "attack": "engagement"}
RANK = re.compile(r"^(?:Lieut\.?|Lt\.?|Lieutenant|Capt\.?|Cpt\.?|Captain|Col\.?|Colonel|Ltc\.?|LTC|Lt\.? ?Col\.?|Maj\.?|Major|"
                  r"Brig\.?|BG|MG|LTG|Gen\.?|General|Sergt\.?|Sgt\.?|Surg\.?|1Lt|2Lt|First|Second|Brevet)\s+", re.I)


def norm_person(s):
    s = re.sub(r"\(.*?\)", "", s or "")
    for _ in range(4):
        s = RANK.sub("", s.strip())
    s = re.sub(r",?\s*(jr|Jr|sr|Sr)\.?$", "", s.strip(" .,"))
    return re.sub(r"\s+", " ", s).strip(" .,")


def main(proj, db_path):
    P = Path(proj)
    Path(db_path).unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript((P / "pipeline/schema.sql").read_text(encoding="utf-8"))
    con.executescript((P / "pipeline/schema_v03.sql").read_text(encoding="utf-8"))
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")              # bulk load; checked at the end
    side = {}
    for n in ("Union", "Confederate"):
        cur.execute("INSERT INTO side(name) VALUES (?)", (n,)); side[n] = cur.lastrowid
    xref = defaultdict(dict)                               # (entity_type, scheme) -> value -> id

    def add_x(et, eid, scheme, value):
        if value and value not in xref[(et, scheme)]:
            xref[(et, scheme)][value] = eid
            cur.execute("INSERT OR IGNORE INTO external_id VALUES (?,?,?,?)", (et, eid, scheme, value))

    # ---------- units: Dyer's (Union) ----------
    # Dyer's -> NPS code links, cleaned (see nps_links.py)
    d2n, _, dropped = nps_links.load(P / "data/scores/dyer_to_nps.csv")
    print("Dyer's-NPS links kept", len(d2n), "dropped (qualifier mismatch)", len(dropped))
    ech = {"regiment": "regiment", "battalion": "battalion", "battery": "battery", "company": "company", "legion": "regiment", "squadron": "company"}
    br = {"infantry": "infantry", "cavalry": "cavalry", "light artillery": "artillery", "heavy artillery": "artillery",
          "artillery": "artillery", "sharpshooters": "sharpshooters", "engineers": "engineers"}
    units_file = P / "data/dyers/units_clean.jsonl"          # cleaned text + hand-checked units (vote_witnesses.py)
    if not units_file.exists():
        units_file = P / "data/dyers/units.jsonl"
    for l in open(units_file, encoding="utf-8"):
        u = json.loads(l)
        st = ST.get(u["state"])
        name = f"{u['state'].title()} {u['heading'].rstrip('.').title()}"
        cur.execute("INSERT INTO unit(side_id, echelon, branch, state, number, display_name, notes) VALUES (?,?,?,?,?,?,?)",
                    (side["Union"], ech.get(u.get("kind"), "other"), br.get(u.get("branch")), st, u.get("number"), name,
                     f"Dyer's pp. {u.get('page_start')}-{u.get('page_end')}"))
        uid_ = cur.lastrowid
        add_x("unit", uid_, "dyer", u["id"])
        if u["id"] in d2n:
            add_x("unit", uid_, "nps", d2n[u["id"]])
    # ---------- units: NPS codes not linked to Dyer's (Confederate, and unlinked Union) ----------
    tmap = {"R": "regiment", "B": "battalion", "Y": "battery", "C": "company", "L": "regiment", "S": "company", "D": "other", "X": "other"}
    fmap = {"I": "infantry", "C": "cavalry", "A": "artillery"}
    for u in csv.DictReader(open(P / "data/external/acw_battle_data/nps_units.csv", encoding="utf-8")):
        if u["unit_code"] in xref[("unit", "nps")]:
            continue
        try:
            num = int(u["ordinal"]) if u["ordinal"] else None
        except ValueError:
            num = None
        cur.execute("INSERT INTO unit(side_id, echelon, branch, state, number, display_name, notes) VALUES (?,?,?,?,?,?,?)",
                    (side["Union" if u["belligerent"] == "US" else "Confederate"], tmap.get(u["type"], "other"),
                     fmap.get(u["func"]), u["state"], num, u["unit_name"], "NPS Soldiers and Sailors unit list (via Arnold)"))
        add_x("unit", cur.lastrowid, "nps", u["unit_code"])

    def unit_of(uid):
        if not uid:
            return None
        if uid.startswith("nps:"):
            return xref[("unit", "nps")].get(uid[4:])
        return xref[("unit", "dyer")].get(uid)

    # ---------- sources ----------
    def source(title, kind, citation=None, url=None, pd=1, notes=None):
        cur.execute("INSERT INTO source(title, kind, citation, url, fetched_at, public_domain, notes) VALUES (?,?,?,?,?,?,?)",
                    (title, kind, citation, url, NOW, pd, notes)); return cur.lastrowid
    S_DYER = source("Dyer, A Compendium of the War of the Rebellion (1908)", "compendium",
                    "Frederick H. Dyer, Des Moines, 1908", "https://archive.org/details/08697590.3359.emory.edu")
    S_WD = source("Wikidata", "website", None, "https://www.wikidata.org", 1, "CC0")
    S_AI = source("AI event resolution (Claude), batches 1-3", "manual", "data/ai/event_resolutions_*.psv", None, 1,
                  "Historical-knowledge resolutions of event clusters; approximate coordinates flagged")
    or_src, wp_src = {}, {}

    # ---------- events ----------
    ev_id = {}
    events = [json.loads(l) for l in open(P / "data/events/events.jsonl", encoding="utf-8")]
    for e in events:
        cur.execute("INSERT INTO event(kind, display_name, notes) VALUES (?,?,?)",
                    (EVENT_KIND.get((e.get("kind") or "").lower(), "other"), e["name"],
                     f"{len(e['clusters'])} Dyer's clusters; {e['regiments']} regiments; {e['mentions']} mentions"))
        ev_id[e["event_id"]] = eid_ = cur.lastrowid
        add_x("event", eid_, "pipeline_event", e["event_id"])
        if e.get("wikidata"):
            add_x("event", eid_, "wikidata", e["wikidata"])
    for e in events:
        if e.get("parent_event") in ev_id:
            cur.execute("UPDATE event SET parent_event_id=? WHERE id=?", (ev_id[e["parent_event"]], ev_id[e["event_id"]]))
    c2e = {json.loads(l)["cluster_id"]: json.loads(l)["event_id"] for l in open(P / "data/events/cluster_to_event.jsonl", encoding="utf-8")}

    # ---------- places ----------
    pl_id = {}
    geo = {}                                   # data/places/geocoded.csv (pipeline/geocode.py): override, seed, gnis, context
    gp = P / "data/places/geocoded.csv"
    if gp.exists():
        for g in csv.DictReader(open(gp, encoding="utf-8")):
            if g["lat"]:
                geo[g["place_key"]] = g
    for r in csv.DictReader(open(P / "data/places/places_inventory.csv", encoding="utf-8")):
        kind = {"region": "region", "state": "region"}.get(r["kind"], "other")
        g = geo.get(r["place_key"])
        if g:
            lat, lon, prec = float(g["lat"]), float(g["lon"]), int(float(g["precision_m"]))
            note = f"{r['mentions']} weighted mentions; located by {g['method']}: {g['detail']}"
        else:
            lat = float(r["seed_lat"]) if r["seed_lat"] else None
            lon = float(r["seed_lon"]) if r["seed_lon"] else None
            prec = (2000 if r["seed_source"] == "wikidata" else 20000) if lat is not None else None
            note = f"{r['mentions']} weighted mentions; seed from {r['seed_source'] or 'none'}"
        cur.execute("INSERT INTO place(display_name, kind, state, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?,?)",
                    (r["name"], kind, r["state"] or None, lat, lon, prec, note))
        pl_id[r["place_key"]] = cur.lastrowid
        add_x("place", pl_id[r["place_key"]], "place_key", r["place_key"])
    pm = {}
    for l in open(P / "data/places/place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] == "unit_at":
            pm.setdefault((m["unit"], m.get("date"), m["raw"]), m["place_key"])
    # per-mention resolutions from the unit's own route (pipeline/resolve_mentions.py): a Dyer's "Alexandria" of a unit
    # on the Red River is Alexandria, La., whatever the pooled place says
    res, res_place = {}, {}
    rp = P / "data/places/mention_resolution.jsonl"
    if rp.exists():
        for l in open(rp, encoding="utf-8"):
            r = json.loads(l)
            if (r["was"] in ("none", "off_route") or (r.get("moved_km") or 0) >= 5) and pm.get((r["unit"], r["date"], r["raw"])) == r["place_key"]:
                res[(r["unit"], r["date"], r["raw"])] = r

    def resolved_place(r):
        k = (r["name"], r["state"], r["lat"], r["lon"])
        if k not in res_place:
            cur.execute("INSERT INTO place(display_name, kind, state, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?,?)",
                        (r["name"], "town", r["state"], r["lat"], r["lon"], r["precision_m"],
                         f"resolve_mentions.py: from the unit's route ({r['class']}, margin {r['margin']}, "
                         f"{r['candidates']} candidates; pooled place was {r['place_key']} by {r['was']})"))
            res_place[k] = cur.lastrowid
        return res_place[k]

    # ---------- persons ----------
    person = {}

    def person_of(mention, side_name):
        n = norm_person(mention)
        if len(n) < 3:
            return None
        k = (side_name, n.lower())
        if k not in person:
            cur.execute("INSERT INTO person(display_name, side_id) VALUES (?,?)", (n, side.get(side_name)))
            person[k] = cur.lastrowid
        return person[k]

    # ---------- claim helper ----------
    def claim(ctype, src, span, conf, by, locator, table, **cols):
        cur.execute("INSERT INTO claim(claim_type, source_id, source_span, confidence, extracted_by, extracted_at, locator) VALUES (?,?,?,?,?,?,?)",
                    (ctype, src, (span or "")[:500], conf, by, NOW, locator))
        cid = cur.lastrowid
        cols["claim_id"] = cid
        cur.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(cols.values()))
        return cid
    PORT = {"whole", "detachment", "companies", "veterans", "non_veterans"}
    # Dyer's participations its unit cannot have been at (resolve_mentions.py: clear positions before and after agree,
    # both out of reach of the event): left unlinked to the event
    off_part = set()
    opp = P / "data/places/participation_off_route.jsonl"
    if opp.exists():
        off_part = {(r["unit"], r["event_id"]) for r in map(json.loads, open(opp, encoding="utf-8"))}

    # ---------- Dyer's claims ----------
    m2c = {}
    for l in open(P / "data/dyers/mention_to_event.jsonl", encoding="utf-8"):
        m = json.loads(l); m2c[(m["unit_id"], m["mention"], m["date_start"])] = m["cluster_id"]
    n = defaultdict(int)
    for l in open(P / "data/dyers/claims_rules.jsonl", encoding="utf-8"):
        c = json.loads(l); t = c["claim_type"]; uid = unit_of(c["unit_id"]); um = c["unit_id"]
        loc = f"p. {c.get('page')}" if c.get("page") else None
        common = dict(date_start=c.get("date_start"), date_end=c.get("date_end"), date_precision=c.get("date_precision"))
        if t == "participated":
            eid_ = c2e.get(m2c.get((c["unit_id"], c.get("event_mention"), c.get("date_start"))))
            e = ev_id.get(eid_)
            if e and (c["unit_id"], eid_) in off_part:
                e = None; n["dyer participated unlinked: off the unit's route"] += 1
            claim(t, S_DYER, c["source_span"], c["confidence"], "regex:dyers_v1", loc, "claim_participated", unit_mention=um, unit_id=uid,
                  event_mention=c.get("event_mention") or "", event_id=e, portion=c.get("portion") if c.get("portion") in PORT else "whole", **common)
            n["dyer participated linked" if e else "dyer participated unlinked"] += 1
        elif t == "unit_at":
            mk = (c["unit_id"], c.get("date_start"), (c.get("place_mention") or "")[:80])
            pk = pm.get(mk)
            plid = pl_id.get(pk)
            if mk in res:
                if res[mk]["lat"] is None:      # the pooled place is impossible on the unit's route: no position
                    plid = None; pk = None; n["dyer unit_at place detached by route"] += 1
                else:
                    plid = resolved_place(res[mk]); n["dyer unit_at place resolved by route"] += 1
            claim(t, S_DYER, c["source_span"], c["confidence"], "regex:dyers_v1", loc, "claim_unit_at", unit_mention=um, unit_id=uid,
                  place_mention=c.get("place_mention") or "", place_id=plid, presence=c.get("presence") or "present",
                  portion=c.get("portion") if c.get("portion") in PORT else "whole", **common)
            n["dyer unit_at with place" if pk else "dyer unit_at no place"] += 1
        elif t == "subordinate_to":
            claim(t, S_DYER, c["source_span"], c["confidence"], "regex:dyers_v1", loc, "claim_subordinate_to", unit_mention=um, unit_id=uid,
                  parent_mention=c.get("parent_mention") or "", **common); n["dyer subordinate_to"] += 1
        elif t == "unit_numbers":
            claim(t, S_DYER, c["source_span"], c["confidence"], "regex:dyers_v1", loc, "claim_unit_numbers", unit_mention=um, unit_id=uid,
                  event_mention=c.get("event_mention"), scope=c.get("scope") or "whole_service", killed=c.get("killed"),
                  died_disease=c.get("died_disease"), casualties_total=c.get("casualties_total"), wounded=c.get("wounded"),
                  missing_captured=c.get("missing_captured"), strength=c.get("strength")); n["dyer unit_numbers"] += 1
        elif t == "known_as":
            claim(t, S_DYER, c["source_span"], c["confidence"], "regex:dyers_v1", loc, "claim_known_as", entity_type="unit", entity_id=uid,
                  name=c.get("target_mention") or c.get("name") or "", name_type="alias"); n["dyer known_as"] += 1

    # ---------- Official Records and Wikipedia claims ----------
    def load_secondary(path, kind):
        for l in open(path, encoding="utf-8"):
            c = json.loads(l); t = c["claim_type"]
            if kind == "nps":
                src, by, loc = S_NPSBU, "csv:nps_battle_units_v1", c["source_ref"]
            elif kind == "or":
                vol = c["source_ref"].split(" (")[0]
                if vol not in or_src:
                    or_src[vol] = source(f"Official Records, Ser. I, {vol}", "official_records",
                                         f"The War of the Rebellion: Official Records, Series I, {vol}", "https://archive.org/details/warofrebellion")
                src, by = or_src[vol], "regex:or_org_v1"
                loc = c["source_ref"]
            else:
                art = c["source_span"]
                if art not in wp_src:
                    wp_src[art] = source(f"Wikipedia: {art}", "website", None, "https://en.wikipedia.org/wiki/" + art.replace(" ", "_"), 0,
                                         "CC BY-SA 4.0")
                src, by = wp_src[art], "wikitext:oob_v1"
                loc = c["source_ref"]
            by = c.get("extracted_by") or by
            uid = unit_of(c["unit_id"]); um = c["unit_mention"]
            common = dict(date_start=c.get("date_start"), date_end=c.get("date_end"), date_precision=c.get("date_precision"))
            portion = "companies" if c.get("portion") else "whole"
            if t == "participated":
                claim(t, src, c["source_span"], c["confidence"], by, loc, "claim_participated", unit_mention=um, unit_id=uid,
                      event_mention=c.get("event_mention") or "", event_id=ev_id.get(c.get("event_id")), portion=portion,
                      portion_detail=c.get("portion"), **common)
            elif t == "subordinate_to":
                claim(t, src, c["source_span"], c["confidence"], by, loc, "claim_subordinate_to", unit_mention=um, unit_id=uid,
                      parent_mention=c.get("parent_mention") or "", parent_path_json=json.dumps(c.get("parent_path"), ensure_ascii=False), **common)
            elif t == "commanded":
                claim(t, src, c["source_span"], c["confidence"], by, loc, "claim_commanded", person_mention=c["person_mention"],
                      person_id=person_of(c["person_mention"], c["side"]), unit_mention=um, unit_id=uid, seq=c.get("order"),
                      casualty=c.get("casualty"), **common)
            n[f"{kind} {t}"] += 1
            n[f"{kind} with unit id" if uid else f"{kind} without unit id"] += 1
    S_NPSBU = source("NPS Soldiers and Sailors Database: units engaged in each CWSAC battle (Confederate units, from Crute)",
                     "government_list", "Crute, Units of the Confederate States Army (1987), via NPS Soldiers and Sailors Database",
                     "https://www.nps.gov/civilwar/search-battle-units.htm", 1)
    load_secondary(P / "data/or/claims_or.jsonl", "or")
    if (P / "data/nps/claims_nps_battles.jsonl").exists():
        load_secondary(P / "data/nps/claims_nps_battles.jsonl", "nps")
    load_secondary(P / "data/wikipedia/claims_wikipedia.jsonl", "wikipedia")
    if (P / "data/wikipedia/claims_wp_regiments.jsonl").exists():      # infobox battle lists of Confederate unit articles
        load_secondary(P / "data/wikipedia/claims_wp_regiments.jsonl", "wikipedia")

    # ---------- event locations and names ----------
    ev_place = defaultdict(collections_Counter)          # event -> places named in its mentions (geocoded)
    for l in open(P / "data/places/place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] == "event" and m.get("event_id"):
            ev_place[m["event_id"]][m["place_key"]] += m.get("weight", 1)
    S_GEO = source("Geocoded place names (GNIS) of an event's mentions", "manual", "data/places/geocoded.csv (pipeline/geocode.py)",
                   "https://www.usgs.gov/us-board-on-geographic-names", 1)
    # events located by their units' routes (pipeline/resolve_mentions.py, phase 2): the namesake their units could reach
    ev_res = {}
    erp = P / "data/places/event_resolution.jsonl"
    if erp.exists():
        for l in open(erp, encoding="utf-8"):
            r = json.loads(l); ev_res[r["event_id"]] = r
    for e in events:
        eid = ev_id[e["event_id"]]
        r = ev_res.get(e["event_id"])          # for an event with coordinates: only when they were suspect (replaces_coords)
        if r and r["lat"] is None:             # its place is out of its units' reach: not placed (resolve_mentions.py)
            n["event not placed: out of its units' reach"] += 1
        elif r:
            cur.execute("INSERT INTO place(display_name, kind, state, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?,?)",
                        (r["name"], "town", r["state"], r["lat"], r["lon"], r["precision_m"],
                         f"resolve_mentions.py: chosen by the routes of {r['units']} units ({r['class']}, margin {r['margin']}, "
                         f"{r['candidates']} candidates; pooled place {r['place_key']} by {r['was']})"))
            claim("event_at", S_GEO, e["name"], 0.6, "pipeline:route", e["event_id"], "claim_event_at",
                  event_mention=e["name"], event_id=eid, place_mention=r["name"], place_id=cur.lastrowid,
                  date_start=e["date_start"], date_end=e["date_end"], date_precision="day" if len(e["date_start"] or "") == 10 else "month")
            n["event_at from units' routes"] += 1
        elif e.get("lat") is None and ev_place.get(e["event_id"]):
            for pk, _ in ev_place[e["event_id"]].most_common(3):
                g = geo.get(pk)
                est = e.get("state")
                if g and est and g["state"] and g["state"] != est and {g["state"], est} != {"VA", "WV"}:
                    n["event_at from geocoded place: state disagrees"] += 1
                    continue
                if g and g["method"] in ("gnis", "override", "seed") and pk in pl_id:
                    claim("event_at", S_GEO, e["name"], 0.6, "pipeline:geocode", e["event_id"], "claim_event_at",
                          event_mention=e["name"], event_id=eid, place_mention=g["name"], place_id=pl_id[pk],
                          date_start=e["date_start"], date_end=e["date_end"], date_precision="day" if len(e["date_start"] or "") == 10 else "month")
                    n["event_at from geocoded place"] += 1
                    break
        if e.get("lat") is not None and not r:
            src = {"wikidata": S_WD, "ai_approx": S_AI}.get(e.get("coord_source"), S_WD)
            cur.execute("INSERT INTO place(display_name, kind, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?)",
                        (e["name"], "battlefield", e["lat"], e["lon"], 2000 if src == S_WD else 20000, f"location of {e['event_id']}"))
            claim("event_at", src, e["name"], 0.9 if src == S_WD else 0.5, "pipeline:merge_events", e["event_id"], "claim_event_at",
                  event_mention=e["name"], event_id=eid, place_mention=e["name"], place_id=cur.lastrowid,
                  date_start=e["date_start"], date_end=e["date_end"], date_precision="day" if len(e["date_start"] or "") == 10 else "month")
            n["event_at"] += 1
        if e.get("dyer_name") and e["dyer_name"] != e["name"]:
            claim("known_as", S_DYER, e["dyer_name"], 0.8, "pipeline:merge_events", e["event_id"], "claim_known_as",
                  entity_type="event", entity_id=eid, name=e["dyer_name"], name_type="alias"); n["event known_as"] += 1
    # ---------- event membership: part_of claims (data/events/part_of.jsonl, see event_membership.py) ----------
    pf = P / "data/events/part_of.jsonl"
    if pf.exists():
        S_NPS = source("NPS Civil War Sites Advisory Commission: battle-to-campaign assignments", "website",
                       "via Arnold, acw_battle_data (ODC-BY)", "https://www.nps.gov/abpp/battles/", 1)
        S_PIPE = source("Pipeline inference (event_membership.py)", "manual", None, None, 1,
                        "anchor: campaign and battle anchored to the same Wikidata item; inferred: chained from a member's candidates")
        src_of = {"nps": S_NPS, "wikidata": S_WD, "ai": S_AI, "dyers": S_DYER, "anchor": S_PIPE, "inferred": S_PIPE}
        ename = {e["event_id"]: e["name"] for e in events}
        for l in open(pf, encoding="utf-8"):
            o = json.loads(l)
            if o["event_id"] not in ev_id or o["parent_event_id"] not in ev_id: continue
            cid = claim("part_of", src_of[o["source"]], o.get("note") or "", o["confidence"], f"membership:{o['source']}",
                        o["event_id"], "claim_part_of", event_mention=ename[o["event_id"]], event_id=ev_id[o["event_id"]],
                        parent_mention=ename[o["parent_event_id"]], parent_event_id=ev_id[o["parent_event_id"]],
                        preferred=int(o["preferred"]), dates_ok=int(o["dates_ok"]))
            if not o["dates_ok"]:
                cur.execute("UPDATE claim SET review_note='child dates outside the container' WHERE id=?", (cid,))
            n["part_of " + o["source"]] += 1
            n["part_of preferred"] += int(o["preferred"])

    # ---------- positions inside battles: monuments and markers (data/battles/*_positions.jsonl: battle_positions.py,
    #            battle_monuments.py; each row names its source: osm (default), npgallery, shiloh_arcgis) ----------
    S_BP = {}
    BY = {"osm": "osm:battle_positions_v1", "npgallery": "npgallery:battle_monuments_v1", "shiloh_arcgis": "arcgis:battle_monuments_v1",
          "ga_markers": "claude:battle_monuments_ga_markers_v1"}
    for bp in sorted((P / "data/battles").glob("*_positions.jsonl")) if (P / "data/battles").exists() else []:
        for l in open(bp, encoding="utf-8"):
            r = json.loads(l)
            sk = r.get("source", "osm")
            if sk not in S_BP:
                if sk == "osm":
                    S_BP[sk] = source("OpenStreetMap contributors: battlefield monuments and markers", "website",
                                      "Overpass / OSM API extract of historic=memorial|monument features (pipeline/battle_positions.py, battle_monuments.py)",
                                      "https://www.openstreetmap.org/copyright", 0, "ODbL 1.0: attribute OpenStreetMap contributors")
                else:
                    import battle_monuments
                    t, u, pd, note = battle_monuments.SRC[sk]
                    S_BP[sk] = source(t, "website", "pipeline/battle_monuments.py", u, pd, note)
            cur.execute("INSERT INTO place(display_name, kind, lat, lon, precision_m, notes) VALUES (?,?,?,?,?,?)",
                        (r["source_span"][:200], "other", r["lat"], r["lon"], r["precision_m"], f"monument/marker {r['osm']} ({r['battle']})"))
            pid = cur.lastrowid
            by = BY[sk] if "source" in r or sk != "osm" else BY["osm"]
            if "source" in r and sk == "osm":
                by = "osm:battle_monuments_v1"
            conf = 0.5 if r["kind"] == "division" else 0.6 if r["kind"] == "brigade" else 0.8 if r.get("role") == "camp" else 0.85
            claim("unit_at", S_BP[sk], r["source_span"], conf, by,
                  r.get("ref") or r["osm"], "claim_unit_at", unit_mention=r["source_span"], unit_id=unit_of(r["unit_key"]), place_mention=r["source_span"],
                  place_id=pid, presence="present", portion="whole", date_start=r["date_start"], date_end=r["date_end"],
                  date_precision="day")
            n["battle positions (monuments): " + sk] += 1

    # ---------- manual / uploaded claims (data/manual/*.json, generated data/derived/*.json; see manual_claims.py) ----------
    import manual_claims
    manual_claims.load(P, cur, side, xref, events, ev_id, person_of, source, claim, n)

    # ---------- namesake decisions (data/manual/namesake_decisions.psv) ----------
    # Placements linked to one unit that belong to a namesake (Turney's 1st Tennessee in Virginia under the
    # Western 1st Tennessee): a placement's participated, subordinate_to and commanded claims share source,
    # locator, unit and date; its theater (pipeline/theater.py) and brigade come from the subordinate_to claim.
    import theater
    dp = P / "data/manual/namesake_decisions.psv"
    rules = []
    if dp.exists():
        for line in open(dp, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            f = (line.rstrip("\n").split("|") + [""] * 8)[:8]
            rules.append(dict(zip(("frm", "th", "d0", "d1", "brig", "to", "cite", "note"), f)))
    code_unit = {v: k for k, v in cur.execute("SELECT entity_id, value FROM external_id WHERE entity_type='unit' AND scheme='nps'").fetchall()}
    unit_code = {v: k for k, v in code_unit.items()}
    moved_ns = Counter()
    if rules:
        frm_units = {code_unit[r["frm"]] for r in rules if r["frm"] in code_unit}
        groups = defaultdict(list)
        q = ",".join(map(str, frm_units)) or "0"
        for tbl in ("claim_participated", "claim_subordinate_to", "claim_commanded"):
            for cid, uid, ds, sid, loc, title in cur.execute(f"""SELECT x.claim_id, x.unit_id, x.date_start, c.source_id, c.locator, s.title
                    FROM {tbl} x JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
                    WHERE x.unit_id IN ({q}) AND s.kind IN ('official_records','website')""").fetchall():
                groups[(sid, loc, uid, (ds or "")[:10])].append((tbl, cid, title))
        for (sid, loc, uid, ds), items in groups.items():
            sub = [cid for tbl, cid, _ in items if tbl == "claim_subordinate_to"]
            pm, pj = cur.execute("SELECT parent_mention, parent_path_json FROM claim_subordinate_to WHERE claim_id=?", (sub[0],)).fetchone() if sub else ("", "{}")
            try:
                path = json.loads(pj or "{}")
            except ValueError:
                path = {}
            brig = path.get("brigade") or pm or ""
            th = theater.classify(items[0][2], path.get("army"), path.get("army_heading"), path.get("corps"), pm)
            for r in rules:
                if code_unit.get(r["frm"]) != uid or (r["th"] != "*" and r["th"] != th):
                    continue
                if (r["d0"] and ds < r["d0"]) or (r["d1"] and ds > r["d1"]) or (r["brig"] and not re.search(r["brig"], brig)):
                    continue
                to = None if r["to"] == "UNLINK" else code_unit.get(r["to"])
                if r["to"] != "UNLINK" and not to:
                    n[f"namesake decision: unknown code {r['to']}"] += 1
                    break
                for tbl, cid, _ in items:
                    cur.execute(f"UPDATE {tbl} SET unit_id=? WHERE claim_id=?", (to, cid))
                    cur.execute("UPDATE claim SET review_note=COALESCE(review_note||'; ','')||? WHERE id=?",
                                (f"namesake decision: {r['frm']} -> {r['to']} ({r['cite'][:120]})", cid))
                moved_ns[r["to"]] += len(items)
                break
    n["namesake decisions: claims moved or unlinked"] = sum(moved_ns.values())

    # ---------- relink by service dates ----------
    # An order-of-battle line "6th Pennsylvania" in 1862 is not the 3-month 6th Pennsylvania of 1861. Where a claim
    # from the Official Records, Wikipedia or NPS falls more than 30 days outside its unit's Dyer's service (first
    # to last dated entry) and exactly one namesake (same side, state, number, branch; any branch if none) was in service then, the
    # claim moves to it; otherwise it keeps its unit and gets a review note (pipeline/consistency_checks.py lists them).
    win = {}
    for tbl in ("claim_participated", "claim_unit_at"):
        for uid, lo, hi in cur.execute(f"""SELECT x.unit_id, MIN(x.date_start), MAX(COALESCE(x.date_end, x.date_start))
                FROM {tbl} x JOIN claim c ON c.id=x.claim_id WHERE c.source_id=? AND x.unit_id IS NOT NULL
                AND x.date_start IS NOT NULL GROUP BY x.unit_id""", (S_DYER,)).fetchall():
            a, b = win.get(uid, (lo, hi))
            win[uid] = (min(a, lo), max(b, hi))
    names, any_branch = defaultdict(list), defaultdict(list)
    for uid, sd, st, num, br in cur.execute("SELECT id, side_id, state, number, branch FROM unit WHERE number IS NOT NULL").fetchall():
        names[(sd, st, num, br)].append(uid)
        any_branch[(sd, st, num)].append(uid)
    key_of = {u: k for k, us in names.items() for u in us}
    def pd(x, end=False):
        p = [int(v) for v in x[:10].split("-")]
        if len(p) == 3:
            try:
                return date(*p)
            except ValueError:
                return date(p[0], p[1], 28)
        if len(p) == 2:
            return date(p[0], p[1], 28 if end else 1)
        return date(p[0], 12 if end else 1, 28 if end else 1)
    def in_win(u, ds, slack=30):
        w = win.get(u)
        if not w:
            return None
        try:
            return pd(w[0]) - timedelta(days=slack) <= pd(ds) <= pd(w[1], True) + timedelta(days=slack)
        except ValueError:
            return None
    moved = kept = 0
    for tbl in ("claim_participated", "claim_subordinate_to", "claim_commanded"):
        rows = cur.execute(f"""SELECT x.claim_id, x.unit_id, x.date_start FROM {tbl} x JOIN claim c ON c.id=x.claim_id
                JOIN source s ON s.id=c.source_id WHERE x.unit_id IS NOT NULL AND x.date_start IS NOT NULL
                AND s.kind IN ('official_records','website','government_list') AND s.title NOT LIKE 'Wikidata%'""").fetchall()
        for cid, uid, ds in rows:
            if in_win(uid, ds) is not False:
                continue
            alt = [u for u in names.get(key_of.get(uid), []) if u != uid and in_win(u, ds)]
            if not alt and key_of.get(uid):             # a regiment that changed branch: 15th New York Infantry -> Engineers
                alt = [u for u in any_branch[key_of[uid][:3]] if u != uid and in_win(u, ds)]
            if len(alt) == 1:
                cur.execute(f"UPDATE {tbl} SET unit_id=? WHERE claim_id=?", (alt[0], cid))
                cur.execute("UPDATE claim SET review_note=COALESCE(review_note||'; ','')||? WHERE id=?",
                            (f"unit relinked from {uid}: outside its Dyer's service dates", cid)); moved += 1
            else:
                cur.execute("UPDATE claim SET review_note=COALESCE(review_note||'; ','')||? WHERE id=?",
                            ("outside the unit's Dyer's service dates", cid)); kept += 1
    n["relinked to a namesake in service"] = moved
    n["outside service, left for review"] = kept

    # ---------- person merge: initials onto the one full name with the same side, surname and first initial ----------
    groups = defaultdict(list)
    for (sd, key), pid in person.items():
        toks = key.replace(".", ". ").split()
        if len(toks) >= 2 and len(toks[-1]) > 2:
            groups[(sd, toks[-1], toks[0][0])].append((pid, toks))
    merged = 0
    for g in groups.values():
        inits = lambda t: "".join(x[0] for x in t[:-1])
        full = [(pid, t) for pid, t in g if len(t[0].rstrip(".")) > 1]
        for pid, t in g:
            if len(t[0].rstrip(".")) != 1:
                continue
            cand = [f for f, ft in full if inits(ft) == inits(t)] or ([full[0][0]] if len(full) == 1 and len(t) == 2 else [])
            if len(cand) != 1:
                continue                                        # no full name, or several that fit: leave alone
            cur.execute("UPDATE claim_commanded SET person_id=? WHERE person_id=?", (cand[0], pid))
            cur.execute("DELETE FROM person WHERE id=?", (pid,)); merged += 1
    n["persons merged (initials -> full name)"] = merged
    con.commit()
    cur.execute("PRAGMA foreign_keys = ON")
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    stats = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
             ("unit", "event", "place", "person", "source", "claim", "external_id")}
    print("rows:", stats)
    print("loads:", dict(n))
    print("foreign key problems:", len(bad))
    con.execute("ANALYZE"); con.commit(); con.close()


if __name__ == "__main__":
    main(*sys.argv[1:3])
