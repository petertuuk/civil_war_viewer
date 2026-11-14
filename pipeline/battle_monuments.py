"""Positions of units inside battles from battlefield monuments and tablets, beyond Gettysburg (battle_positions.py).

Sources (raw copies in data/external/battles/):
  npgallery_monuments.jsonl  NPS NPGallery "Civil War Monuments and Markers Digital Collection" (photographs made for the
                             Civil War Soldiers and Sailors System, public domain): one record per monument (Legacy NPS Focus
                             record), with the NPS unit name ("113th Regiment, Ohio Infantry"), battle keywords, a comment that
                             often names the day, and the photo's coordinates (longitudes stored without their minus sign).
                             Used for Chickamauga, Chattanooga (Wauhatchie, Lookout Mountain, Missionary Ridge) and Vicksburg.
  shiloh_tablets_0/1.json    "ShilohWeb" ArcGIS layer of Shiloh NMP tablets (casey.counce, public): unit, brigade, army,
                             branch, first day (layer 0, with camp sites) and second day (layer 1).
  osm_antietam_monuments.json OpenStreetMap monuments at Antietam (ODbL), fetched with the OSM API in tiles.
Each located monument becomes a unit_at claim (day precision) at its coordinates, written to
data/battles/<battle>_positions.jsonl in battle_positions.py's format plus "source" and "ref" (a URL for the map's
source panel). Day: a day named in the monument's text if it is one of the battle's days, else the battle's span;
Vicksburg: the unit's own siege dates from its participation claims (the siege span when it has none).
Checks: coordinates inside the battle's box; units resolved by NPS name, or side + state + number + branch (batteries
by letter). Report: data/scores/battle_monuments.txt.

Usage: python pipeline/battle_monuments.py ~/db/civil_war.db data/external/battles data/battles data/scores/battle_monuments.txt
"""
import csv, json, re, sqlite3, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import km, too_fast  # noqa: E402

ST = {"ME": "Maine", "NH": "New Hampshire", "VT": "Vermont", "MA": "Massachusetts", "RI": "Rhode Island", "CT": "Connecticut",
      "NY": "New York", "NJ": "New Jersey", "PA": "Pennsylvania", "DE": "Delaware", "MD": "Maryland", "WV": "West Virginia",
      "OH": "Ohio", "IN": "Indiana", "IL": "Illinois", "MI": "Michigan", "WI": "Wisconsin", "MN": "Minnesota", "IA": "Iowa",
      "MO": "Missouri", "KY": "Kentucky", "KS": "Kansas", "NE": "Nebraska", "US": "U.S.",
      "VA": "Virginia", "NC": "North Carolina", "SC": "South Carolina", "GA": "Georgia", "AL": "Alabama", "MS": "Mississippi",
      "LA": "Louisiana", "TX": "Texas", "AR": "Arkansas", "TN": "Tennessee", "FL": "Florida"}
NAME2ST = {v.lower(): k for k, v in ST.items()}
NAME2ST.update({"ind": "IN", "ohio": "OH", "n.y.": "NY", "brooklyn": "NY", "conn": "CT", "mass": "MA", "penn": "PA"})
MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# battle: (event display name, first day, last day, (south, west, north, east))
BATTLES = {
    "chickamauga": ("Battle of Chickamauga", "1863-09-18", "1863-09-20", (34.83, -85.33, 34.975, -85.19)),
    "wauhatchie": ("Battle of Wauhatchie", "1863-10-28", "1863-10-29", (34.975, -85.42, 35.06, -85.355)),
    "lookout_mountain": ("Battle of Lookout Mountain", "1863-11-24", "1863-11-24", (34.975, -85.355, 35.03, -85.325)),
    "missionary_ridge": ("Battle of Missionary Ridge", "1863-11-23", "1863-11-25", (34.975, -85.325, 35.09, -85.20)),
    "vicksburg": ("Siege of Vicksburg", "1863-05-18", "1863-07-04", (32.30, -90.91, 32.42, -90.81)),
    "shiloh": ("Battle of Shiloh", "1862-04-06", "1862-04-07", (35.07, -88.40, 35.19, -88.28)),
    "antietam": ("Battle of Antietam", "1862-09-17", "1862-09-17", (39.43, -77.78, 39.50, -77.71)),
}
SRC = {"npgallery": ("NPS NPGallery: Civil War Monuments and Markers Digital Collection (Civil War Soldiers and Sailors System photographs)",
                     "https://npgallery.nps.gov/", 1, "public domain (NPS contract photographs); coordinates of each monument photograph"),
       "shiloh_arcgis": ("Shiloh National Military Park tablets (ArcGIS layer ShilohWeb, casey.counce)",
                         "https://services2.arcgis.com/MPzXAppZq4kTyKOS/arcgis/rest/services/ShilohWeb/FeatureServer", 0,
                         "public ArcGIS Online layer; tablet positions with unit, brigade and day"),
       "ga_markers": ("Georgia historical markers (Georgia Historical Commission, texts mostly by Wilbur G. Kurtz; Georgia Historical Society layer), formations read by Claude",
                      "https://historicalmarkers.georgiahistory.com/", 0,
                      "marker coordinates and texts from the Georgia Historical Society's public ArcGIS layer GA_Historical_Markers; "
                      "which formations a marker places at its spot read by Claude (data/external/battles/ga_markers_read.psv)"),
       "osm": ("OpenStreetMap contributors: battlefield monuments and markers", "https://www.openstreetmap.org/copyright", 0,
               "ODbL 1.0: attribute OpenStreetMap contributors")}


def inbox(lat, lon, b):
    return b[0] <= lat <= b[2] and b[1] <= lon <= b[3]


class Units:
    def __init__(self, db, nps_csv):
        self.db = db
        self.units = db.execute("SELECT u.id, s.name, u.state, u.number, u.branch, u.echelon, u.display_name FROM unit u JOIN side s ON s.id=u.side_id").fetchall()
        self.dyer = dict(db.execute("SELECT entity_id, value FROM external_id WHERE entity_type='unit' AND scheme='dyer'"))
        self.nps = dict(db.execute("SELECT entity_id, value FROM external_id WHERE entity_type='unit' AND scheme='nps'"))
        self.by_nps = defaultdict(list)
        for uid, v in self.nps.items():
            self.by_nps[v].append(uid)
        self.nps_name = defaultdict(list)
        for r in csv.DictReader(open(nps_csv, encoding="utf-8")):
            self.nps_name[r["unit_name"].strip().lower()].append((r["unit_code"], r["duplicate"]))
        self.battery = {}
        for uid, v in self.dyer.items():
            m = re.search(r"^([a-z_]+)/\d+_battery_([a-m])_(\d+)(?:st|nd|rd|th|d)_", v)
            if m:
                self.battery[(m.group(1), int(m.group(3)), m.group(2).upper())] = uid
        self.bykey = defaultdict(list)
        for uid, side, st, num, br, ech, nm in self.units:
            self.bykey[(side, st, num)].append((uid, br, ech, nm))
        self.name = {u[0]: u[6] for u in self.units}

    def key(self, u):
        return self.dyer.get(u) or (f"nps:{self.nps[u]}" if u in self.nps else None)

    def by_nps_name(self, name, side=None):
        codes = sorted(self.nps_name.get(name.strip().lower(), []), key=lambda c: c[1])
        if side:                                  # NPS codes start with C (Confederate) or U (Union)
            codes = [c for c in codes if c[0][:1] == side[0]]
        for code, _ in codes:
            us = self.by_nps.get(code, [])
            if len(us) == 1:
                return us[0]
            if us:
                d = [u for u in us if u in self.dyer]
                return (d or us)[0]
        return None

    def battery_of(self, state, num, letter):
        pref = "u_s_regular_army" if state == "US" else ST[state].lower().replace(" ", "_")
        return self.battery.get((pref, num, letter))

    def resolve(self, side, state, num, branch, letter=None, indep=False, name_hint=None, pref=None):
        """side 'Union'/'Confederate', state code, number, branch infantry|cavalry|artillery -> unit id or None (with reason)"""
        if branch == "artillery" and letter and side == "Union":
            b = self.battery_of(state, num, letter)
            return (b, None) if b else (None, "battery letter not found")
        if state == "US" and side == "Union":
            cands = self.bykey.get(("Union", "UR", num), [])
        else:
            cands = self.bykey.get((side, state, num), [])
        if branch == "artillery":
            cands = [c for c in cands if c[1] == "artillery" and (c[2] == "battery" if indep else True)]
            if indep:
                cands = [c for c in cands if not re.search(r"Heavy|Regiment", c[3])] or cands
        else:
            cands = [c for c in cands if c[1] == branch and c[2] == "regiment" and not re.search(r"Months|Militia|Emergency|Veteran|Reserve|National Guard|Home Guard|State Troops|Battalion|Consolidated", c[3])]
        if len(cands) > 1 and sum(c[0] in self.dyer for c in cands) == 1:
            cands = [c for c in cands if c[0] in self.dyer]
        if len(cands) > 1 and name_hint:
            h = [c for c in cands if name_hint.lower() in c[3].lower()]
            cands = h or cands
        if len(cands) > 1 and pref:                  # namesakes: the one the database already links to this battle
            h = [c for c in cands if c[0] in pref]
            cands = h if len(h) == 1 else cands
        if len(cands) == 1:
            return cands[0][0], None
        return None, f"{len(cands)} candidates"

    def named_battery(self, side, state, surname):
        """Confederate batteries known by their captain: 'Swett's MS Battery' -> the unit whose name has Swett and the state"""
        s = surname.lower().rstrip("'’s")
        c = [u for u in self.units if u[1] == side and u[4] == "artillery" and (state is None or u[2] == state) and re.search(r"\b" + re.escape(s), u[6].lower())]
        if len(c) > 1 and sum(u[0] in self.dyer for u in c) == 1:
            c = [u for u in c if u[0] in self.dyer]
        return (c[0][0], None) if len(c) == 1 else (None, f"{len(c)} named-battery candidates")


def days_in(text, d0, d1):
    """Days of the battle named in a text ('September 20, 1863', 'Sept. 19', 'Nov. 25th') -> sorted list"""
    y = d0[:4]
    out = set()
    for m in re.finditer(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th|d)?\b", text):
        ds = f"{y}-{MON[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
        if d0 <= ds <= d1:
            out.add(ds)
    return sorted(out)


def npgallery(path, U, events, part_dates, rows, stats, linked):
    recs = [json.loads(l) for l in open(path, encoding="utf-8")]
    shared = Counter((round(r["lat"], 4), round(abs(r["lon"]), 4)) for r in recs if r["lat"] is not None and len(r["titles"]) > 1)
    for r in recs:
        if r["lat"] is not None and shared[(round(r["lat"], 4), round(abs(r["lon"]), 4))] >= 3:
            stats["npgallery: coordinate shared by 3+ monuments (a default, not the monument)"] += 1; continue
        if r["park"] not in ("CHCH", "VICK") or len(r["titles"]) < 2 or r["lat"] is None:
            continue
        lat, lon = r["lat"], -abs(r["lon"])
        t0, t1 = r["titles"][0], r["titles"][1].strip()
        if re.search(r"\b(batch|Memorial Plaques)\b", t0, re.I):
            continue
        cands = [k for k in BATTLES if (k == "vicksburg") == (r["park"] == "VICK") and inbox(lat, lon, BATTLES[k][3])]
        if not cands:
            stats["npgallery: outside every battle box"] += 1; continue
        text = r["comment"] + " " + t0
        bk = cands[0]
        if r["park"] == "CHCH":                     # a day named in the text picks among the Chattanooga battles
            for k in ("chickamauga", "wauhatchie", "lookout_mountain", "missionary_ridge"):
                if days_in(text, BATTLES[k][1], BATTLES[k][2]) and inbox(lat, lon, (34.80, -85.45, 35.10, -85.18)):
                    if k != bk and not (k in ("lookout_mountain", "missionary_ridge") and bk in ("lookout_mountain", "missionary_ridge")):
                        stats[f"npgallery: date text says {k}, place says {bk}: place kept"] += 1
                    elif k != bk:
                        bk = k
                    break
        ename, d0, d1, _ = BATTLES[bk]
        side = "Confederate" if (U.nps_name.get(t1.lower()) and U.nps_name[t1.lower()][0][0].startswith("C")) or re.search(r"C\.\s?S\.\s?A|\bCSA\b|Confederate", t0) else "Union"
        # the monument's title (its inscription) over NPGallery's unit tag when they disagree on number or state
        a0 = re.match(r"^(?:C\.?\s?S\.?\s?A\.?\s+)?(\d+)(?:st|nd|rd|th|d)\s+(?:C\.?S\.?A\.?\s+)?([A-Z][A-Za-z.]*(?:\s[A-Z][a-z]+)?)\b", t0)
        a1 = re.match(r"^(\d+)\w*\s+[^,]*, (.+?) (?:Infantry|Cavalry|Light Artillery|Artillery|Sharpshooters|Mounted)", t1)
        if a0 and a1:
            w = a0.group(2).replace(".", "").split()
            s0 = next((NAME2ST.get(x.lower()) or (x if x in ST else None) for x in (" ".join(w[:2]), w[0]) if NAME2ST.get(x.lower()) or x in ST), None)
            s1 = NAME2ST.get(a1.group(2).lower())
            if s0 and s1 and (int(a0.group(1)) != int(a1.group(1)) or s0 != s1):
                br = "cavalry" if re.search(r"Cav", t0) else "artillery" if re.search(r"Batt|Artillery", t0) else "infantry"
                u0, _ = U.resolve(side, s0, int(a0.group(1)), br, pref=linked.get(bk))
                stats["npgallery: title and unit tag disagree" + (": title used" if u0 else ": skipped")] += 1
                if not u0:
                    continue
                t1 = None
                forced = u0
            else:
                forced = None
        else:
            forced = None
        targets = []
        m = re.search(r"Battery[- ]+([A-M])\b", t0)
        if m and not forced and re.search(r"Artillery", t1):
            mm = re.match(r"(\d+)\w*\s+Regiment, (.+?) (?:Light )?Artillery", t1)
            stc = NAME2ST.get(mm.group(2).lower()) if mm else None
            u = U.battery_of(stc, int(mm.group(1)), m.group(1)) if stc else None
            targets = [u] if u else []
        elif forced:
            targets = [forced]
        else:
            u = U.by_nps_name(t1, side)
            mm = re.match(r"^(\d+)\w*\s+(Regiment|Independent Battery|Battery), (.+?) (Infantry|Cavalry|Light Artillery|Artillery)\b", t1)
            if mm and u is not None and u not in U.dyer and NAME2ST.get(mm.group(3).lower()):
                br = {"Infantry": "infantry", "Cavalry": "cavalry"}.get(mm.group(4), "artillery")
                d, _ = U.resolve(side, NAME2ST[mm.group(3).lower()], int(mm.group(1)), br, indep="Battery" in mm.group(2), pref=linked.get(bk))
                if d and d in U.dyer:                  # the Dyer's record over an NPS-only duplicate
                    u = d; stats["npgallery: NPS-only unit replaced by its Dyer's record"] += 1
            targets = [u] if u else []
            m2 = re.match(r"^(\d+)(?:st|nd|rd|th|d)\s*&\s*(\d+)(?:st|nd|rd|th|d)\s+(\w[\w ]*?)\s+Infantry", t0)   # "12th & 47th Tennessee"
            if m2 and targets:
                n2 = int(m2.group(2)); ordn = lambda n: f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
                u2 = U.by_nps_name(f"{ordn(n2)} Regiment, {m2.group(3)} Infantry", side)
                if u2:
                    targets.append(u2)
        if not targets:
            stats["npgallery: unit not resolved"] += 1; stats["unresolved: " + t1] += 1; continue
        ds = days_in(text, d0, d1)
        for t in targets:
            a, b = (ds[0], ds[-1]) if len(ds) == 1 else (d0, d1)
            if len(ds) != 1 and t in part_dates.get(bk, {}):    # no day on the monument: the unit's own dates in the battle
                a2, b2 = max(d0, part_dates[bk][t][0]), min(d1, part_dates[bk][t][1])
                if a2 <= b2:
                    a, b = a2, b2; stats["npgallery: dated by the unit's participation"] += 1
            rows[bk].append(dict(unit_id=t, lat=lat, lon=lon, precision_m=100, role="main", kind="regiment",
                                 date_start=a, date_end=b, source_span=t0, source="npgallery",
                                 ref="https://npgallery.nps.gov/AssetDetail/" + r["asset"], osm=f"npgallery/{r['legacy']}",
                                 battle=ename, event_id=events.get(ename)))
            stats[f"npgallery {bk}"] += 1


ITEM = re.compile(r"^(?:[A-Z][\w'’]+'?s?\s*\()?(\d+)\s*(?:st|nd|rd|th|d)?\s+([A-Z]{2})\b\)?\s*(Cav\w*|Inf\w*|Sharpshooters)?", re.I)


def shiloh(dirp, U, events, rows, stats, linked):
    ename, d0, d1, box = BATTLES["shiloh"]
    pref = linked.get("shiloh", set())
    for layer, day in ((0, "1862-04-06"), (1, "1862-04-07")):
        for f in json.load(open(dirp / f"shiloh_tablets_{layer}.json", encoding="utf-8"))["features"]:
            a, g = f["attributes"], f.get("geometry") or {}
            unit, br, army = (a.get("Unit") or "").strip(), a.get("Branch"), a.get("Army")
            if not g or br in ("Burial", "HQ", "Mortuary") or not unit or not inbox(g["y"], g["x"], box):
                stats["shiloh: not a unit tablet"] += 1; continue
            side = "Confederate" if army == "AM" else "Union"
            items = [unit] if br == "Art" else [x.strip() for x in re.split(r"[,.]\s+(?=\d|[A-Z][a-z]+'s|Crews|Orleans)", unit) if x.strip()]
            targets = []
            for it in items:
                u, why = None, "no pattern"
                if br == "Art" or re.search(r"Batt(ery|\.)?\b|Btry|Lt\.? Art", it):
                    m = re.search(r"[\"“]([A-M])(?: & [A-M])?[\"”],?\s*(\d+)\w*\s+([A-Z]{2})", it)
                    m2 = re.search(r"(\d+)\w*\s+([A-Z]{2})\s+(Lt|Art)", it)
                    m3 = re.match(r"([A-Z][\w]+)['’]s?\s+(?:([A-Z]{2})\s+)?Batter", it)
                    if m:
                        u, why = U.resolve(side, m.group(3), int(m.group(2)), "artillery", letter=m.group(1), pref=pref)
                    elif m2:
                        u, why = U.resolve(side, m2.group(2), int(m2.group(1)), "artillery", indep=True, pref=pref)
                    elif m3:
                        u, why = U.named_battery(side, m3.group(2), m3.group(1))
                else:
                    m = ITEM.match(it)
                    if m and m.group(2).upper() in ST:
                        b = "cavalry" if (m.group(3) or "").lower().startswith("cav") or br == "Cav" else "infantry"
                        hint = re.match(r"([A-Z][a-z]+)['’]s?\b", it)
                        u, why = U.resolve(side, m.group(2).upper(), int(m.group(1)), b, name_hint=hint.group(1) if hint else None, pref=pref)
                if u:
                    targets.append(u)
                else:
                    stats[f"shiloh: unresolved ({why})"] += 1; stats["unresolved: " + it] += 1
            multi = len(items) > 1
            for t in targets:
                rows["shiloh"].append(dict(unit_id=t, lat=g["y"], lon=g["x"], precision_m=300 if multi else 60,
                                           role="camp" if br == "Camp" else "main", kind="brigade" if multi else "regiment",
                                           date_start="1862-04-05" if br == "Camp" else day, date_end="1862-04-05" if br == "Camp" else day,
                                           source_span=("camp site: " if br == "Camp" else "") + unit + (f" ({a['Comments']})" if a.get("Comments") else ""),
                                           source="shiloh_arcgis", ref=a.get("Link") or SRC["shiloh_arcgis"][1],
                                           osm=f"shiloh/{layer}/{a['OBJECTID']}", battle=ename, event_id=events.get(ename)))
                stats[f"shiloh day {layer + 1}{' camp' if br == 'Camp' else ''}"] += 1


OSMRX = re.compile(r"^(?:.*?-\s*)?(\d+)(?:st|nd|rd|th|d)?\s+(?:Regiment\s+)?([A-Za-z.]+)\b\s*(.*)$")


CSA = {"VA", "NC", "SC", "GA", "AL", "MS", "LA", "TX", "AR", "TN", "FL"}


def antietam(dirp, U, events, rows, stats, linked):
    ename, d0, d1, box = BATTLES["antietam"]
    pref = linked.get("antietam", set())
    for e in json.load(open(dirp / "osm_antietam_monuments.json", encoding="utf-8"))["elements"]:
        nm = e["tags"].get("name", "")
        if not nm or not inbox(e["lat"], e["lon"], box) or re.search(r"Killed|Wounded|State|Memorial|Brigade|Division|Army|Monument to|Slave|Coffee|Private Soldier|Mansfield|Purnell", nm):
            stats["antietam: not a regiment monument"] += 1; continue
        nm2 = nm.replace("14th Brooklyn", "84th NY").replace("’", "'")
        targets = []
        m = re.match(r"^(\d+)\w*\s+MD Light Artillery Battery ([A-M])", nm2)
        if m:
            u, _ = U.resolve("Union", "MD", int(m.group(1)), "artillery", letter=m.group(2)); targets = [u] if u else []
        elif "," in nm2 or " and " in nm2:                      # "5th, 7th and 66th OH"
            st = NAME2ST.get(nm2.split()[-1].lower()) or (nm2.split()[-1] if nm2.split()[-1] in ST else None)
            for n in re.findall(r"(\d+)(?:st|nd|rd|th|d)", nm2):
                u, _ = U.resolve("Union", st, int(n), "infantry", pref=pref) if st else (None, None)
                if u:
                    targets.append(u)
        else:
            m = OSMRX.match(re.sub(r"^Hawkins Zouaves Monument - ", "", nm2))
            if m:
                w = m.group(2).rstrip(".").lower()
                st = w.upper() if w.upper() in ST else NAME2ST.get(w) or NAME2ST.get(m.group(2).lower())
                if st == "NY" or w in ("n.y", "new"):
                    st = "NY"
                br = "cavalry" if "Cavalry" in m.group(3) else "infantry"
                if st:
                    u, why = U.resolve("Confederate" if st in CSA else "Union", st, int(m.group(1)), br, pref=pref)
                    targets = [u] if u else []
        if not targets:
            stats["antietam: unresolved"] += 1; stats["unresolved: " + nm] += 1; continue
        for t in targets:
            rows["antietam"].append(dict(unit_id=t, lat=e["lat"], lon=e["lon"], precision_m=60, role="main", kind="regiment",
                                         date_start=d0, date_end=d1, source_span=nm, source="osm",
                                         ref=f"https://www.openstreetmap.org/{e['type']}/{e['id']}", osm=f"{e['type']}/{e['id']}",
                                         battle=ename, event_id=events.get(ename)))
            stats["antietam"] += 1


def route_trim(db, rows, stats):
    """A monument dated by the battle's span (or the unit's siege dates) may cover days the unit's own Dyer's record puts
    it far away (a regiment reaching Vicksburg in June). Trim the span to days a unit could be there: Dyer's day-precision
    positions (spans of 3 days or less) within the span or 3 days of it, too far to reach (common.too_fast), cut it;
    a span left empty drops the claim."""
    want = {r["unit_id"] for rr in rows.values() for r in rr}
    pos = defaultdict(list)
    for uid, a, b, lat, lon in db.execute("""SELECT u.unit_id, u.date_start, COALESCE(u.date_end, u.date_start), p.lat, p.lon FROM claim_unit_at u
            JOIN claim c ON c.id=u.claim_id JOIN source s ON s.id=c.source_id JOIN place p ON p.id=u.place_id
            WHERE s.kind='compendium' AND u.date_precision='day' AND p.lat IS NOT NULL AND length(u.date_start)=10
              AND COALESCE(u.presence, 'present')='present'"""):
        if uid in want and len(b) == 10:
            da, db_ = date.fromisoformat(a), date.fromisoformat(b)
            if (db_ - da).days <= 3:
                pos[uid].append((da, db_, lat, lon))
    for bk, rr in rows.items():
        keep = []
        for r in rr:
            a, b = date.fromisoformat(r["date_start"]), date.fromisoformat(r["date_end"])
            for pa, pb, lat, lon in pos.get(r["unit_id"], ()):
                d = km((r["lat"], r["lon"]), (lat, lon))
                if d <= 150:
                    continue
                need = timedelta(days=max(1, int(d // 250) + 1))       # days needed to cover the distance
                if pb < a - timedelta(days=3) or pa > b + timedelta(days=3):
                    continue
                if pb < a + (b - a) / 2 and too_fast(d, max(1, (a - pb).days)):
                    a = max(a, pb + need)
                elif pa > a + (b - a) / 2 and too_fast(d, max(1, (pa - b).days)):
                    b = min(b, pa - need)
                elif a <= pa <= b or a <= pb <= b:
                    a, b = b + timedelta(days=1), b                      # a position inside a short span: drop it
            if a > b:
                stats[f"route: dropped ({bk})"] += 1; continue
            if (a.isoformat(), b.isoformat()) != (r["date_start"], r["date_end"]):
                stats[f"route: trimmed ({bk})"] += 1
                r["date_start"], r["date_end"] = a.isoformat(), b.isoformat()
            keep.append(r)
        rows[bk] = keep


GA_BATTLES = [("kennesaw", "Battle of Kennesaw Mountain", "1864-06-15", "1864-07-04"),
              ("peachtree_creek", "Battle of Peachtree Creek", "1864-07-17", "1864-07-21"),
              ("ezra_church", "Battle of Ezra Church", "1864-07-28", "1864-07-28"),
              ("atlanta", "Battle of Atlanta", "1864-07-22", "1864-08-29"),
              ("jonesboro", "Battle of Jonesboro", "1864-08-30", "1864-09-02")]
PREC = {("regiment", "here"): 300, ("regiment", "near"): 600, ("battery", "here"): 300, ("battery", "near"): 600,
        ("brigade", "here"): 500, ("brigade", "near"): 1000, ("division", "here"): 1000, ("division", "near"): 2000}


def toks(x):
    return [re.sub(r"[^a-z]", "", w.lower()) for w in x.split() if re.sub(r"[^a-z]", "", w.lower())]


def has(tokens, names):
    words = set(w for n in names for w in toks(re.sub(r"['’]s\b", "", n or "")))
    return all(t in words for t in tokens)


def ga_markers(src, db, U, rows, stats):
    """Georgia markers: formations a marker places at its spot (ga_markers_read.psv), expanded to their regiments by the
    Wikipedia orders of battle of the Atlanta campaign and its battles (the battle's own order of battle when it covers
    the day, else the campaign's): brigade by its commander's name (and its division's), division by its commander's."""
    mk = {f["attributes"]["OBJECTID"]: f["attributes"] for f in json.load(open(src / "ga_markers.json", encoding="utf-8"))}
    oob = []
    for uid, pj, a, b, title in db.execute("""SELECT x.unit_id, x.parent_path_json, x.date_start, COALESCE(x.date_end, x.date_start), s.title
            FROM claim_subordinate_to x JOIN claim c ON c.id=x.claim_id JOIN source s ON s.id=c.source_id
            WHERE x.unit_id IS NOT NULL AND s.title LIKE 'Wikipedia:%order of battle%' AND (s.title LIKE '%Atlanta%' OR s.title LIKE '%Peachtree%'
              OR s.title LIKE '%Ezra%' OR s.title LIKE '%Jonesbor%' OR s.title LIKE '%Kennesaw%' OR s.title LIKE '%Kolb%')"""):
        try:
            p = json.loads(pj or "{}")
        except ValueError:
            continue
        side = "CS" if "Confederate" in title else "US"
        if "First phase" in title:                       # the campaign's two orders of battle: before and after Hood (July 18)
            b = min(b, "1864-07-17")
        elif "Second phase" in title:
            a = max(a, "1864-07-18")
        oob.append(dict(unit=uid, side=side, a=a, b=b, title=title, brig=[p.get("brigade")] + [c["name"] for c in p.get("brigade_commanders") or []],
                        div=[p.get("division")] + [c["name"] for c in p.get("division_commanders") or []], key=(title, p.get("division"), p.get("brigade"))))
    lines = [l.rstrip("\n").split("|") for l in open(src / "ga_markers_read.psv", encoding="utf-8") if l.strip() and not l.startswith("#")][1:]
    for m, d0, d1, side, level, who, ctx, where in lines:
        a = mk.get(int(m))
        if not a or not a.get("Latitude"):
            stats["ga: marker not found"] += 1; continue
        bk = next((k for k, _n, x0, x1 in GA_BATTLES if x0 <= d0 <= x1), None)
        if not bk:
            stats["ga: date outside the battles"] += 1; continue
        targets = []
        if level in ("regiment", "battery"):
            w = who.split()
            sd = "Confederate" if side == "CS" else "Union"
            if level == "battery":
                u, why = U.resolve(sd, w[1], int(w[0]), "artillery", letter=w[2] if len(w) > 2 else None, indep=len(w) == 2)
            else:
                u, why = U.resolve(sd, w[1], int(w[0]), "infantry")
            targets = [u] if u else []
            if not u:
                stats[f"ga: {level} unresolved ({why})"] += 1; stats["unresolved: " + who] += 1
        else:
            cand = [o for o in oob if o["side"] == side and o["a"] <= d0 and d1 <= o["b"]]
            tw, tc = toks(who), toks(ctx)
            if level == "brigade":
                hit = [o for o in cand if has(tw, o["brig"]) and (not tc or has(tc, o["div"]))]
            else:
                hit = [o for o in cand if has(tw, o["div"])]
            if hit:                                         # the narrowest order of battle that has the formation
                span = min((date.fromisoformat(o["b"]) - date.fromisoformat(o["a"])).days for o in hit)
                hit = [o for o in hit if (date.fromisoformat(o["b"]) - date.fromisoformat(o["a"])).days == span]
                per = defaultdict(set)
                for o in hit:
                    per[o["title"]].add(o["key"][1:] if level == "brigade" else o["key"][1])
                if any(len(g) > 1 for g in per.values()):   # the same name in two places of one order of battle
                    groups = set().union(*per.values())
                    stats[f"ga: {level} ambiguous"] += 1; stats[f"ambiguous: {level} {who} / {ctx} {sorted(map(str, groups))[:3]}"] += 1; continue
                targets = sorted({o["unit"] for o in hit})
            if not targets:
                stats[f"ga: {level} not in an order of battle"] += 1; stats[f"unresolved: {level} {who} / {ctx} {d0}"] += 1; continue
        kind = {"battery": "regiment"}.get(level, level)
        for t in targets:
            rows["ga_" + bk].append(dict(unit_id=t, lat=a["Latitude"], lon=a["Longitude"], precision_m=PREC[(level, where)], role="main",
                                         kind=kind, date_start=d0, date_end=d1, source_span=f"{a['Name']} ({a.get('Number') or ''}): {level} {who}",
                                         source="ga_markers", ref=a.get("Learn_More") or SRC["ga_markers"][1], osm=f"ga_marker/{m}",
                                         battle=dict((k, n) for k, n, *_ in GA_BATTLES)[bk], event_id=None))
            stats[f"ga {bk} {level}"] += 1


def main(dbp, srcdir, outdir, report):
    db = sqlite3.connect(dbp)
    src, out = Path(srcdir), Path(outdir)
    U = Units(db, src.parent / "acw_battle_data/nps_units.csv")
    events = {}
    for k, (ename, *_r) in BATTLES.items():
        r = db.execute("SELECT id FROM event WHERE display_name=? ORDER BY CASE kind WHEN 'battle' THEN 0 WHEN 'siege' THEN 1 ELSE 2 END, id", (ename,)).fetchone()
        events[ename] = r[0] if r else None
    vk = [i for (i,) in db.execute("SELECT id FROM event WHERE display_name IN ('Siege of Vicksburg','Assaults on Vicksburg')")]
    part = {}                                    # battle -> unit -> (first, last day) of its participation claims
    for bk, (ename, *_r) in BATTLES.items():
        eids = [e for e in ({events.get(ename)} | (set(vk) if bk == "vicksburg" else set())) if e]
        part[bk] = {}
        # Dyer's dates first (a unit's own record: "Siege of Vicksburg June 14-July 4"); the NPS battle lists give
        # every unit the whole battle
        for uid, kind, a, b in db.execute(f"""SELECT p.unit_id, s.kind, MIN(p.date_start), MAX(COALESCE(p.date_end, p.date_start)) FROM claim_participated p
                JOIN claim c ON c.id=p.claim_id JOIN source s ON s.id=c.source_id
                WHERE p.event_id IN ({','.join(map(str, eids)) or 0}) AND p.unit_id IS NOT NULL AND length(p.date_start)=10 GROUP BY p.unit_id, s.kind"""):
            if a and b and len(b) == 10 and (uid not in part[bk] or kind == "compendium"):
                part[bk][uid] = (a, b)
    linked = {}
    for bk, (ename, *_r) in BATTLES.items():
        eids = [e for e in ({events.get(ename)} | (set(vk) if bk == "vicksburg" else set())) if e]
        linked[bk] = {u for (u,) in db.execute(f"SELECT DISTINCT unit_id FROM claim_participated WHERE event_id IN ({','.join(map(str, eids))})")} if eids else set()
    rows, stats = defaultdict(list), Counter()
    npgallery(src / "npgallery_monuments.jsonl", U, events, part, rows, stats, linked)
    shiloh(src, U, events, rows, stats, linked)
    antietam(src, U, events, rows, stats, linked)
    ga_markers(src, db, U, rows, stats)
    route_trim(db, rows, stats)
    # participation check: units the database already links to the battle (or its siege)
    lines = []
    for bk, rr in sorted(rows.items()):
        ename = BATTLES[bk][0] if bk in BATTLES else rr[0]["battle"]
        us = {r["unit_id"] for r in rr}
        lk = linked.get(bk, set())
        with open(out / f"{bk}_positions.jsonl", "w", encoding="utf-8") as f:
            for r in rr:
                r["unit_key"] = U.key(r["unit_id"])
                if not r["unit_key"]:
                    stats["no stable unit key"] += 1; continue
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        lines.append(f"{bk}: {len(rr)} claims, {len(us)} units; already linked to {ename}: {len(us & lk)} ({100 * len(us & lk) // max(1, len(us))}%)")
        for u in sorted(us - lk, key=lambda u: U.name.get(u, ""))[:40]:
            lines.append(f"   not linked: {U.name.get(u)}")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")
        for k, v in sorted(stats.items()):
            f.write(f"{v:6d}  {k}\n")
    print("\n".join(l for l in lines if not l.startswith("   ")))
    print({k: v for k, v in stats.items() if not k.startswith("unresolved: ")})


if __name__ == "__main__":
    main(*sys.argv[1:])
