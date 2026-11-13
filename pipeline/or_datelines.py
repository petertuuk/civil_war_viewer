"""Positions from the headings of Official Records letters and reports: "HEADQUARTERS THIRD BRIGADE, THIRD DIVISION,
TWENTIETH CORPS, Atlanta, Ga., September 23, 1864." puts that command's headquarters at Atlanta on that day.

1. Extract (all OR text files): each "Headquarters ..." / "Hdqrs. ..." line with a date within its next three lines.
   The text before the date splits at commas into command parts (regiment, brigade, division, corps, army, department)
   and the place (what follows the last command part; "Camp near", "In the field" stripped). Side: the nearest
   running head or report title above (CONFEDERATE / UNION, "C. S. Army" / "U. S. Army").
2. Resolve the command against the OR organization tables (data/or/placements.jsonl) of the same side, nearest table first, within
   45 days of the date (TABLE_DAYS; up to 120 only for the units a table on the other side of the date also holds:
   2026-11-12 check, far tables agreed with other positions 63% of the time vs 81% for near ones): every command part given must agree with the table row (ordinal number, or a
   commander's name: "Ross' Brigade", "Jackson's Cavalry Division"; cavalry vs infantry). The matching rows must form
   one brigade / division / corps; if two do, the heading is ambiguous and dropped. A regiment heading
   ("124th Ohio Volunteer Infantry") is matched to the unit itself. Army, department and district headquarters are
   not used (too wide).
3. (place) A place no step below can settle is voted on by the commanded units' routes (see vote() in the code).
   Locate the place like the post lines (data/places/geocoded.csv, then GNIS) in the written state, or a well-known
   place name (Dyer's 40+ mentions). Each unit of the command gets a unit_at claim on that day, with a precision by
   level: regiment 2 km, brigade 4 km, division 10 km, corps 25 km (+3 km for "near").

   A later part of the place names a place next to the first ("White House, Lookout Mountain"). A stateless famous
   place far (> 300 km) from the book's other headings gives way to a namesake near them that Dyer's regiments were at.
4. (members) Brigade / division / corps headings do not place: company / detachment rows of the table; a unit whose
   own clear positions within 10 days (ROUTE_DAYS: Dyer's route from unit_tracks.jsonl, post lines, NPS histories)
   are all too fast to reach from the place (common.too_fast, the test of fast_jumps.py); a unit whose last position before and first after (each within 30
   days) are within 100 km of each other and over 300 km from the place (it stayed put), or the place is over 300 km from both and a 600 km
   detour from the way between them (it moved elsewhere); for a "Detachment ..." heading, a unit with no position within
   150 km then ("Detachment Nineteenth Army Corps, Near Leesburg": the divisions left in Louisiana); a Union unit that
   Dyer's attachments put only in other numbered corps that month (the Oct. 31, 1863 Gulf table files Nineteenth
   Corps regiments under the Thirteenth).

Writes data/or/datelines.jsonl (every heading, resolved or not, with the reason) and data/derived/or_datelines.json
(manual claims format). Usage: python pipeline/or_datelines.py <dir of OR text files> data/or/volumes.json \
    data/or/placements.jsonl data/or/tables.jsonl data/places/geocoded.csv data/external/gnis/gnis_index.tsv \
    data/external/acw_battle_data/nps_units.csv data/or/datelines.jsonl data/derived/or_datelines.json
"""
import csv, difflib, json, re, sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gnis_index import norm  # noqa: E402
from common import gnis_by_name_state, km, too_fast  # noqa: E402
from or_stations import split_place, SAME, ABBR  # noqa: E402

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MON = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan\.|Feb\.|Mar\.|Apr\.|Aug\.|Sept?\.|Oct\.|Nov\.|Dec\."
DATE = re.compile(rf"({MON})\s*(\d{{1,2}})\s*,?\s*(18[56]\d)")
HEAD = re.compile(r"^(HEADQUARTERS|HDQRS\.?|Headquarters|Hdqrs\.?|HEADQRS\.?|Headqrs\.?)\b")
_U = ["", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth"]
_TEENS = ["tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth",
          "nineteenth"]
_TENS = {2: ("twentieth", "twenty"), 3: ("thirtieth", "thirty"), 4: ("fortieth", "forty"), 5: ("fiftieth", "fifty"),
         6: ("sixtieth", "sixty"), 7: ("seventieth", "seventy"), 8: ("eightieth", "eighty"), 9: ("ninetieth", "ninety")}


def _ordword(n):
    if n >= 100:
        r = n - 100
        return "one hundredth" if r == 0 else "one hundred and " + _ordword(r)
    if n < 10:
        return _U[n]
    if n < 20:
        return _TEENS[n - 10]
    t, u = divmod(n, 10)
    return _TENS[t][0] if u == 0 else f"{_TENS[t][1]}-{_U[u]}"


ORDW = {_ordword(n): n for n in range(1, 200)}
ROMAN = {r: i + 1 for i, r in enumerate("i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx xxi xxii xxiii xxiv xxv".split())}
LEVELS = [("brigade", r"\bbrig(?:ade)?s?\b|\bbrig\.|\bbrigd?e?\b"), ("division", r"\bdiv(?:ision)?s?\b|\bdiv\.|\bdivn\b"),
          ("corps", r"\bcorps\b|\bc\b\.?$"), ("army", r"\barmy\b|\barmies\b|\bwing\b"),
          ("dept", r"department|\bdept\b|district|\bdist\b|military|\bpost\b|forces|defenses|\bline\b|\bcommand\b|expedition|"
                   r"provost|office|bureau|engineer|ordnance|signal|commissary|quartermaster|subsistence|medical|hospital|"
                   r"camp of instruction|garrison|station|depot|headquarters")]
REGT = re.compile(r"\b(regt|regiment|infantry|infty|inf|cavalry|cav|volunteers|vols?|artillery|arty|battalion|batt|battery|legion|"
                  r"rangers|zouaves|sharpshooters|rifles)\b", re.I)
STATES = {"ala": "Alabama", "ark": "Arkansas", "cal": "California", "conn": "Connecticut", "del": "Delaware", "fla": "Florida",
          "ga": "Georgia", "ill": "Illinois", "ind": "Indiana", "iowa": "Iowa", "kans": "Kansas", "ky": "Kentucky",
          "la": "Louisiana", "me": "Maine", "md": "Maryland", "mass": "Massachusetts", "mich": "Michigan", "minn": "Minnesota",
          "miss": "Mississippi", "mo": "Missouri", "n. h": "New Hampshire", "n. j": "New Jersey", "n. y": "New York",
          "n. c": "North Carolina", "ohio": "Ohio", "pa": "Pennsylvania", "penn": "Pennsylvania", "r. i": "Rhode Island",
          "s. c": "South Carolina", "tenn": "Tennessee", "tex": "Texas", "vt": "Vermont", "va": "Virginia",
          "w. va": "West Virginia", "wis": "Wisconsin", "u. s": "United States"}
USE_SIGNER = False     # signer route (see signer()): tried 2026-11-12, ~1 in 6 wrong in a sample (a general's letter put his
                       # old command where he was); off until signatures are told apart from quoted documents
PLACEISH = re.compile(r"(?i)^(camp|bivouac)\b|^post [A-Z]|\bpost$|\b(station|landing|depot|court[- ]house|ferry|ford|gap|"
                      r"bridge|mills?|springs?|cross[- ]roads|junction)$")
# OCR and spelling repairs of heading places, then names GNIS does not have under the OR's spelling
OCR = [(r"[\^\\]", ","), (r"\bNeiv\b", "New"), (r"\bBock\b", "Rock"), (r"\bIII\b\.?$", "Ill"), (r"(?<=[a-z])horough\b", "borough"),
       (r"\bShelby ville\b", "Shelbyville"), (r"^lanta\b", "Atlanta"), (r"’", "'"), (r"\s+,", ","), (r"\bArlcansas\b", "Arkansas"),
       (r"\bPost Arkansas\b", "Arkansas Post"),
       (r"^[a-z]{1,2}\s+(near|at)\s+", ""), (r"^(near|at|camp near|camp at)\s+", ""), (r"\bNei[oc]\b", "New"),
       (r"\bBla[lh]c?ely\b", "Blakely"), (r"\bBalcer\b", "Baker"), (r"ougli\b", "ough"), (r"shurg\b", "sburg"),
       (r",\s*Fa\.?$", ", Va"), (r"\bLa Fayette\b", "LaFayette")]
ALIAS = {  # normalized OR spelling -> (lat, lon, precision m, state); checked by hand against maps, 2026-11-12
    "devalvs bluff": (34.7898, -91.4593, 2000, "AR"), "devalls bluff": (34.7898, -91.4593, 2000, "AR"),
    "duvalls bluff": (34.7898, -91.4593, 2000, "AR"), "blakely": (30.7416, -87.9225, 2000, "AL"),
    "fort buffalo": (38.8783, -77.1620, 1500, "VA"), "pass cavallo": (28.3700, -96.4000, 3000, "TX"),
    "mouth of white river": (33.9840, -91.0710, 3000, "AR"), "missionary ridge": (35.0250, -85.2630, 3000, "TN"),
    "kenesaw mountain": (33.9830, -84.5780, 3000, "GA"), "kennesaw mountain": (33.9830, -84.5780, 3000, "GA"),
    "gordons mills": (34.8900, -85.2720, 2000, "GA"), "lee and gordons mills": (34.8900, -85.2720, 2000, "GA"),
    "pond spring": (34.7360, -85.3290, 3000, "GA"), "stevens gap": (34.7780, -85.4280, 2000, "GA"),
    "chattanooga valley": (34.9400, -85.3200, 6000, "GA"), "nottoway court house": (37.1290, -78.0710, 2000, "VA"),
    "fort monroe": (37.0035, -76.3075, 1500, "VA"), "fortress monroe": (37.0035, -76.3075, 1500, "VA"),
    "arkansas post": (33.9865, -91.3480, 1500, "AR"), "saint louis": (38.6270, -90.1994, 3000, "MO"),
    "st louis": (38.6270, -90.1994, 3000, "MO"), "new orleans": (29.9511, -90.0715, 3000, "LA"),
    "little rock": (34.7465, -92.2896, 3000, "AR"), "harrisons landing": (35.1140, -85.1380, 3000, "TN"),
    "chattahoochee river": (33.8600, -84.4700, 8000, "GA"), "cumberland ford": (36.7600, -83.6900, 2000, "KY"),
    "mouth of red river": (31.0080, -91.6530, 3000, "LA"), "lafayette": (34.7048, -85.2819, 2000, "GA"),
    "rankins ferry": (35.0400, -85.5400, 3000, "TN"), "whitesides": (34.9990, -85.4760, 3000, "TN"),
    "big black": (32.3500, -90.7100, 5000, "MS"), "north chickamauga": (35.2000, -85.2100, 4000, "TN"),
    "coopers gap": (34.7300, -85.5000, 3000, "GA"), "meadow bluff": (37.9530, -80.6600, 2000, "WV"), "bolivar springs": (40.6500, -79.1500, 0, "?"),
}
ALIAS.pop("bolivar springs")


def clean_place(pl):
    for a, b in OCR:
        pl = re.sub(a, b, pl)
    return pl.strip(" ,.")


TABLE_DAYS, TABLE_FAR = 45, 120   # a command's table within TABLE_DAYS of the heading; up to TABLE_FAR only for units
                                  # the command also holds in a table on the other side of the heading's date
ROUTE_DAYS = 10             # a unit's own positions this near in time test a command heading
BRACKET_DAYS = 30           # ... and its last position before / first after, if both in the same place
PREC = {"regiment": 2000, "brigade": 4000, "division": 10000, "corps": 25000}
CONF = {"regiment": 0.65, "brigade": 0.6, "division": 0.5, "corps": 0.4}


def ordnum(t):
    """Ordinal in a command part: '3d', 'Third', 'Thied' (OCR), 'XII' -> int."""
    t = t.lower().replace("’", "'")
    m = re.search(r"\b(\d{1,3})\s*(?:st|d|nd|rd|th|tli|tb)\b", t)
    if m:
        return int(m.group(1))
    t2 = re.sub(r"\s+", " ", re.sub(r"\b(one hundred) (and )?", r"one hundred and ", t))
    for w in sorted(ORDW, key=len, reverse=True):              # longest first: "one hundred and twenty-fourth"
        if re.search(rf"(?<![a-z-]){re.escape(w)}(?![a-z-])", t2):
            return ORDW[w]
    for w in re.findall(r"[a-z][a-z-]{4,}", t2):             # OCR: "Thied", "Secoyid", "Twentyt-sixth"
        c = difflib.get_close_matches(w, [x for x in ORDW if " " not in x], 1, 0.8)
        if c and (("-" in w) == ("-" in c[0])):
            return ORDW[c[0]]
    m = re.search(r"\b([xvi]{1,6})\b", t)
    if m and m.group(1) in ROMAN and re.search(r"corps", t):
        return ROMAN[m.group(1)]
    return None


def cname(t):
    """Commander name in a command part: "Ross' Brigade" -> 'ross'; "Walthall's (late M'Laws') Division" -> 'walthall'."""
    t = t.replace("’", "'").replace("‘", "'")
    m = re.search(r"([A-Z][A-Za-z\-]+(?:\s+[A-Z][A-Za-z\-]+)?)\s*'s?\s*(?:\(|cavalry|cav|infantry|light|old|\b(?:brig|div|corps|command))",
                  t, re.I)
    if not m:
        return None
    n = m.group(1).split()[-1].lower()
    n = re.sub(r"^m'", "mc", n)
    n = re.sub(r"[^a-z]", "", n)
    if n in ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "army", "cavalry", "reserve",
             "light", "artillery", "provisional", "independent", "consolidated", "colored", "hdqrs", "headquarters") or len(n) < 3:
        return None
    return n


def part_key(t):
    return (ordnum(t), cname(t), bool(re.search(r"\bcav", t, re.I)))


def row_keys(r):
    out = {}
    for lev in ("brigade", "division", "corps"):
        v = r.get(lev) or ""
        if lev == "corps" and re.search(r"Division", v):          # "First Division, Ninth Army Corps" in the corps field
            v = v.split(",")[-1]
        out[lev] = part_key(v) if v else (None, None, False)
    return out


def comp_ok(spec, have):
    num, name, cav = spec
    hnum, hname, hcav = have
    if num is None and name is None:
        return True
    if name is not None and hname != name:
        return False
    if num is not None and hnum != num:
        return False
    if cav and not hcav:
        return False                     # "Cavalry Division, Sixteenth Corps" is not its infantry divisions
    return True


def side_above(L, i):
    for k in range(i - 1, max(0, i - 160), -1):
        x = L[k]
        if re.search(r"[—–-]\s*CONFEDERATE\b|\bC\.\s*S\.\s*Army\b|Confederate\s+(forces|army)", x):
            return "Confederate"
        if re.search(r"[—–-]\s*UNION\b|\bU\.\s*S\.\s*Army\b|Union\s+(forces|army)", x):
            return "Union"
    return None


SIG = re.compile(r"^([A-Z][A-Z.’'\- ]{2,}[A-Z])\.?,?\s*$")
STAFF = re.compile(r"adjutant|aide|chief of|assistant|inspector|quartermaster|surgeon|commissary|engineer|ordnance|secretary|"
                   r"clerk|operator|telegraph|provost|acting|signal|judge|paymaster|agent|president", re.I)
ROLE = re.compile(r"general|colonel|lieutenant|major|captain|commanding", re.I)


def surname_of(name):
    """'JOS. R. DAVIS' / 'Brig. Gen. Joseph R. Davis' / "M'LAWS" -> ('davis', 'j')."""
    t = re.sub(r"^(?:(?:Lieut|Brig|Maj|Col|Capt|Gen|Bvt|Brevet)\.?\s*)+", "", name.strip(), flags=re.I)
    t = re.sub(r",?\s*(jr|sr)\.?$", "", t, flags=re.I).replace("’", "'")
    toks = [x for x in re.split(r"\s+", t) if x]
    if not toks:
        return None, None
    sn = re.sub(r"^m'", "mc", toks[-1].lower())
    sn = re.sub(r"[^a-z]", "", sn)
    ini = toks[0][0].lower() if len(toks) > 1 and toks[0][0].isalpha() else None
    return (sn if len(sn) >= 3 else None), ini


def signer(L, j):
    """The commander who signed the document whose heading ends at line j: the first capitalised name line followed by a
    rank (not a staff officer), or the general named in 'By command of Major-General Ewell:'."""
    for k in range(j + 1, min(len(L), j + 300)):
        x = L[k].strip()
        if HEAD.match(x) or re.match(r"^No\. \d+\.", x):
            return None
        m = re.match(r"^By (?:command|order) of (?:Maj(?:or)?\.?-?\s*Gen(?:eral)?\.?|Brig(?:adier)?\.?-?\s*Gen(?:eral)?\.?|"
                     r"Lieut(?:enant)?\.?-?\s*Gen(?:eral)?\.?|General|Colonel|Col\.)\s+([A-Z][\w.' ’]+?)\s*:?\s*$", x)
        if m:
            return surname_of(m.group(1))
        s_ = SIG.match(x)
        if s_ and not re.search(r"CAMPAIGN|CHAP|CORRESPONDENCE|OPERATIONS|REPORTS|ARMY|CORPS|DIVISION|BRIGADE|TOTAL|OFFICIAL|"
                                r"INCLOSURE|HEADQUARTERS|CONFEDERATE|UNION|DEPARTMENT|DISTRICT|REGIMENT|COMPANY|BATTERY|"
                                r"ADDENDA|ENDORSEMENT|RETURN|ABSTRACT|STATEMENT|CIRCULAR|ORDERS|MEMORANDA", s_.group(1)):
            role = " ".join(L[k + 1:k + 3])
            if STAFF.search(role.split(".")[0] if role else "") or not ROLE.search(role[:80]):
                return None
            return surname_of(s_.group(1).title())
    return None


def parse_heading(blk, m):
    pre = blk[:m.start()]
    pre = HEAD.sub("", pre).strip(" ,.;:")
    parts = [p.strip(" .;:") for p in re.split(r",|;", pre) if p.strip(" .;:")]
    cmd, place = [], []
    for p in parts:
        lp = p.lower()
        lev = None
        if REGT.search(p) and (ordnum(p) or re.search(r"\b\d", p)) and (
                not re.search(r"\bbrig|\bdiv|\bcorps", lp) or re.search(r"\b(?:regt|regiment)\b.*\bcorps\b", lp)):
            # "Fourth Regt. Pennsylvania Reserve Corps" is a regiment of the Reserve Corps, not the Fourth Corps
            lev = "regiment"
        else:
            for name, rx in LEVELS:
                if re.search(rx, lp):
                    lev = name; break
        if cmd and not place and lp.startswith("of "):
            cmd[-1] = (cmd[-1][0], cmd[-1][1] + " " + p); continue          # "Department" / "of West Virginia" (wrapped)
        if lev and cmd and lev == "dept" and PLACEISH.search(p) and not ordnum(p):
            lev = None                                                      # "Arkansas Post", "Camp near Cowan Station"
        if lev and not place:
            cmd.append((lev, p))
        elif lev and place and lev in ("brigade", "division", "corps", "army", "regiment"):
            cmd.append((lev, p)); place = []                      # "Hdqrs., In the field, 1st Div." (rare)
        else:
            place.append(p)
    pl = ", ".join(place)
    pl = re.sub(r"(?i)^(in (the )?field|in camp|on the march|line of battle|in line|in the trenches)[\s,]*(near|at|before)?\s*", "", pl)
    near = bool(re.search(r"(?i)\b(near|before|camp|vicinity|in front of|opposite)\b", pl))
    pl = re.sub(r"(?i)^(camp\s+)?(near|at|before|in front of|opposite|vicinity of|on)\s+", "", pl).strip(" ,.")
    pl = re.sub(r"(?i)^camp\s+(?=[A-Z])", "Camp ", pl)
    return cmd, pl, near


def regt_name(p):
    """'Twenty-third Regt. Wis. Vol. Infty.' -> '23d Wisconsin Infantry' (for the OR regiment matcher)."""
    n = ordnum(p)
    t = " " + p.replace("’", "'") + " "
    if re.search(r"militia|enrolled|home guard|state guard|battery|\bbatt\.|battalion|detachment|squadron|company", t, re.I):
        return None, None                 # not a whole numbered regiment of the line
    st = None
    for k, v in sorted(STATES.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(k)}\.?(?=\W)", t, re.I) or re.search(rf"\b{v}\b", t):
            st = v; break
    if not n or not st or st == "United States":
        return None, None
    typ = "Cavalry" if re.search(r"\bcav", t, re.I) else ("Artillery" if re.search(r"artil|arty|battery", t, re.I) else
          ("Battalion" if re.search(r"\bbatt?(alion)?\b", t, re.I) else "Infantry"))
    suf = "st" if n % 10 == 1 and n != 11 else ("d" if n % 10 in (2, 3) and n not in (12, 13) else "th")
    return f"{n}{suf} {st}" + ("" if typ == "Infantry" else f" {typ}"), typ.lower()


def main(txt_dir, vol_p, pl_p, tables_p, geocoded_p, gnis_p, units_p, out_lines, out_claims):
    import parse_or_all as P
    vols = json.load(open(vol_p))
    idx = P.nps_index(units_p)

    # ---- organization tables: rows by side, sorted by table date
    tabs = defaultdict(list)                  # side -> [(date, table_id, rows)]
    cur = {}
    # tables of troops "not employed in the Atlanta Campaign" list a field corps' detached pieces left behind: a heading
    # "Headquarters Fifteenth Army Corps, Before Atlanta" must not place them at Atlanta
    behind = {f"{t['book']}:{t['start']}" for t in map(json.loads, open(tables_p, encoding="utf-8"))
              if re.search(r"(?i)not\s*em[¬\s-]*ployed|not\s+engaged", t["heading"])}
    for l in open(pl_p, encoding="utf-8"):
        r = json.loads(l)
        c = r.get("unit_code") or ""
        if not c or c.startswith("AMB") or not r.get("date_start") or r["side"] not in ("Union", "Confederate") \
                or r.get("confidence") == "low":
            continue
        if r["table_id"] in behind:
            continue
        cur.setdefault((r["side"], r["table_id"], r["date_start"]), []).append(dict(r, k=row_keys(r)))
    for (s, tid, ds), rows in cur.items():
        tabs[s].append((date.fromisoformat(ds), tid, rows))
    for s in tabs:
        tabs[s].sort(key=lambda x: x[0])
    tdates = {s: [t[0] for t in tabs[s]] for s in tabs}
    # commander surname -> per side, table: the rows he commands at each level
    cmd_ix = defaultdict(lambda: defaultdict(list))   # (side, surname) -> list of (date, tid, level, initial, rows)
    for s in tabs:
        for td, tid, rows in tabs[s]:
            per = defaultdict(list)
            for r in rows:
                for lv, nm in (r.get("cmdrs") or {}).items():
                    sn, ini = surname_of(nm)
                    if sn:
                        per[(sn, lv, ini, r.get(lv) or "")].append(r)
            for (sn, lv, ini, grp), rs in per.items():
                cmd_ix[(s, sn)][tid].append((td, lv, ini, grp, rs))
    # generals named in table headings ("Army of the Potomac, Maj. Gen. George G. Meade"): army / department commanders
    head_cmd = defaultdict(list)
    returns = set()                                       # department returns ("Troops in the ..."): commands spread out
    for t in map(json.loads, open(tables_p, encoding="utf-8")):
        if re.match(r"(?i)troops in\b", t["heading"]):
            returns.add(f"{t['book']}:{t['start']}")
    for t in map(json.loads, open(tables_p, encoding="utf-8")):
        dm = DATE.search(t.get("date_text") or "") or DATE.search(t["heading"])
        if not dm:
            continue
        try:
            td = date(int(dm.group(3)), next(k for k, x in enumerate(MONTHS) if x.startswith(dm.group(1).lower()[:3])) + 1,
                      int(dm.group(2)))
        except (StopIteration, ValueError):
            continue
        for g in re.findall(r"(?:Gen\.|General)\s+((?:[A-Z][a-z]*\.?\s*){1,3}[A-Z][A-Za-z']+)", t["heading"]):
            sn, _ = surname_of(g)
            if sn:
                head_cmd[sn].append(td)

    # ---- places
    geo, famous, geo_mn = {}, {}, {}
    for g in csv.DictReader(open(geocoded_p, encoding="utf-8")):
        if g["lat"] and g["method"] in ("override", "seed", "gnis"):
            geo[(norm(g["name"]), g["state"])] = (float(g["lat"]), float(g["lon"]), int(float(g["precision_m"])))
            mn = int(g["mentions"] or 0)
            geo_mn[(norm(g["name"]), g["state"])] = mn
            if mn >= 40 and mn > famous.get(norm(g["name"]), ("", 0))[1]:
                famous[norm(g["name"])] = (g["state"], mn)
    G = gnis_by_name_state(gnis_p, ("Populated Place", "Military", "Civil", "Island", "Locale", "Crossing", "Gap"))

    stats = Counter()
    G2 = defaultdict(list)                       # name -> every (state, lat, lon, class): for namesakes by context
    for (nm, st), cs in G.items():
        for c in cs:
            if c[2] in ("Populated Place", "Military", "Locale", "Crossing", "Gap"):
                G2[nm].append((st, c[0], c[1], c[2]))
    for (nm, st), v in geo.items():
        G2[nm].append((st, v[0], v[1], "geocoded"))

    def locate(name, st, ctx=None):
        a = ALIAS.get(norm(name))
        if a and (not st or st in SAME.get(a[3], [a[3]])):
            if not ctx or km(a[:2], ctx) < 250:
                return (a[0], a[1], a[2]), a[3]
        r = locate0(name, st)
        # a stateless famous place far from the book's context: a namesake near the context that Dyer's regiments
        # were at (>= 10 mentions: "Winchester" in a Tennessee volume is Winchester, Tenn.) replaces it; otherwise it is
        # kept (GNIS hamlets lost to it: "Vicksburg", Ga.), and the per-unit route test below drops the units that
        # were not there ("Auburn" in a Vicksburg volume stays Auburn, Va.: no Fifteenth Corps unit is placed)
        if r and ctx and not st and km(r[0][:2], ctx) > 300:
            ns = [(k[1], v) for k, v in geo.items() if k[0] == norm(name) and geo_mn.get(k, 0) >= 10
                  and km(v[:2], ctx) <= 150]
            if len(ns) == 1:
                stats["famous place far from the book's context: used namesake Dyer's regiments were at"] += 1
                return (ns[0][1], ns[0][0])
        if r or not ctx:
            return r
        # namesakes: the one nearest the other headings of this book within a few weeks (<= 120 km of their median)
        sts = SAME.get(st, [st]) if st else None
        cs = [c for c in G2.get(norm(name), []) if sts is None or c[0] in sts]
        if not cs:
            return None
        best = min(cs, key=lambda c: km((c[1], c[2]), ctx))
        d1 = km((best[1], best[2]), ctx)
        if d1 > 120:
            return None
        others = [km((c[1], c[2]), ctx) for c in cs if km((c[1], c[2]), (best[1], best[2])) > 30]
        if others and min(others) < 2 * d1 + 40:
            return None                          # another namesake nearly as near: leave it
        stats["place by context among namesakes"] += 1
        return (best[1], best[2], 5000), best[0]

    def locate0(name, st):
        if not st:
            f = famous.get(norm(name))
            if not f:
                return None
            st = f[0]
        for s in SAME.get(st, [st]):
            k = (norm(name), s)
            if k in geo:
                return geo[k], s
            for a in (norm(name), norm(re.sub(r"^Fort\b", "Ft", name)), norm(re.sub(r"^Saint\b", "St", name)),
                      norm(re.sub(r"\s+Court[- ]House$", "", name)), norm(re.sub(r"borough$", "boro", name))):
                cs = G.get((a, s)) or []
                pp = [c for c in cs if c[2] in ("Populated Place", "Military")] or cs
                if pp and len({(round(c[0], 1), round(c[1], 1)) for c in pp}) == 1:
                    return (pp[0][0], pp[0][1], 3000), s
        return None

    # ---- units' routes (data/places/unit_tracks.jsonl from resolve_mentions.py, by NPS code via dyer_to_nps.csv, plus
    # the day-precision positions of the post lines and NPS histories): for a place the steps above cannot settle
    # (no namesake or several), the commanded units vote: the namesake that is the smallest detour on their routes
    # (anchor before -> candidate -> anchor after, within 45 days), if it leads by 1.0 (2.0 with one unit) and its mean
    # detour is under 0.4 (about 100 km)
    from resolve_mentions import step as rstep
    D0_ = date(1861, 1, 1)
    tracks = defaultdict(list)
    d2n = {r["unit_id"]: r["unit_code"] for r in csv.DictReader(open(Path(pl_p).parents[1] / "scores/dyer_to_nps.csv", encoding="utf-8"))
           if r["status"] == "linked" and r["unit_code"]}
    tp = Path(geocoded_p).parent / "unit_tracks.jsonl"
    if tp.exists():
        for l in open(tp, encoding="utf-8"):
            r = json.loads(l)
            if r["unit"] in d2n:
                tracks[d2n[r["unit"]]] += [tuple(x) for x in r["points"]]
    for f_ in ("or_stations.json", "nps_confederate_histories.json"):
        fp = Path(out_claims).parent / f_
        if fp.exists():
            for c in json.load(open(fp, encoding="utf-8"))["claims"]:
                if c.get("date_precision") == "day" and c["place"]["precision_m"] <= 10000:
                    t = (date.fromisoformat(c["date_start"][:10]) - D0_).days
                    tracks[c["unit"]["nps_code"]].append((t, t, 0, c["place"]["lat"], c["place"]["lon"]))
    for k in tracks:
        tracks[k].sort()
    # Dyer's attachments ("1st Brigade, 3rd Division, 19th Army Corps ... 1864-06 to 1864-08"): the numbered corps a
    # Union unit was in, by NPS code: a corps heading does not place a unit Dyer's puts in other corps only that month
    dyer_corps = defaultdict(list)
    dcp = Path(pl_p).parents[1] / "dyers/claims_rules.jsonl"
    if dcp.exists():
        def mday(s, end=False):
            p_ = (s or "").split("-")
            if len(p_) < 2 or not p_[0].isdigit():
                return None
            y, mo = int(p_[0]), int(p_[1])
            if len(p_) == 3:
                return (date(y, mo, int(p_[2])) - D0_).days
            return ((date(y + (mo == 12), mo % 12 + 1, 1) if end else date(y, mo, 1)) - D0_).days - (1 if end else 0)
        for l in open(dcp, encoding="utf-8"):
            r = json.loads(l)
            if r["claim_type"] != "subordinate_to" or r["unit_id"] not in d2n:
                continue
            ns = {int(x) for x in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th|d)\s+(?:Army\s+)?Corps\b", r.get("parent_mention") or "")}
            a0, a1 = mday(r.get("date_start")), mday(r.get("date_end") or r.get("date_start"), True)
            if ns and a0 is not None and a1 is not None:
                dyer_corps[d2n[r["unit_id"]]].append((a0, a1, ns))

    def vote(name, st, codes, d):
        sts = SAME.get(st, [st]) if st else None
        cs = {}
        for c in G2.get(norm(name), []):
            if sts is None or c[0] in sts:
                cs.setdefault((round(c[1], 1), round(c[2], 1)), c)
        cs = list(cs.values())
        if not cs:
            return None
        t = (d - D0_).days
        tot = [0.0] * len(cs); used = 0
        for code in set(codes):
            tr = tracks.get(code) or []
            prv = [a for a in tr if a[1] < t and t - a[1] <= 45]; nxt = [a for a in tr if a[0] > t and a[0] - t <= 45]
            if not prv or not nxt:
                continue
            a, b = prv[-1], nxt[0]; used += 1
            base = rstep(a[3:5], b[3:5], a[1], b[0], a[2] + b[2])
            for j, c in enumerate(cs):
                tot[j] += min(10.0, rstep(a[3:5], c[1:3], a[1], t, a[2]) + rstep(c[1:3], b[3:5], t, b[0], b[2]) - base)
        if not used:
            return None
        order = sorted(range(len(cs)), key=lambda j: tot[j])
        margin = tot[order[1]] - tot[order[0]] if len(cs) > 1 else 99.0
        if margin < (1.0 if used >= 2 else 2.0) or tot[order[0]] / used > 0.4:
            return None
        c = cs[order[0]]
        return (c[1], c[2], 4000), c[0]

    claims, lines_out = [], []
    # pre-pass: where each book's headings are (any command, places found without context) -> context for namesakes
    ctxp = defaultdict(list)
    heads = []
    for f in sorted(Path(txt_dir).glob("warofrebellion*unit.txt")):
        L = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, l in enumerate(L):
            if not HEAD.match(l):
                continue
            blk = " ".join(x.strip() for x in L[i:i + 4] if x.strip())
            m = DATE.search(blk)
            if not m:
                continue
            mon = m.group(1).lower().rstrip(".")
            mi = next((k for k, x in enumerate(MONTHS) if x.startswith(mon[:3])), None)
            try:
                d0 = date(int(m.group(3)), mi + 1, int(m.group(2)))
            except (TypeError, ValueError):
                continue
            _, pl0, _ = parse_heading(blk, m)
            pl0 = clean_place(pl0)
            if len(pl0) < 3:
                continue
            r0 = locate(*split_place(pl0))
            if r0:
                ctxp[f.stem].append((d0.toordinal(), r0[0][0], r0[0][1]))
    for b in ctxp:
        ctxp[b].sort()
    import statistics

    def context(book, d):
        xs = ctxp.get(book) or []
        for w in (21, 60):
            lo, hi = bisect_left(xs, (d.toordinal() - w,)), bisect_left(xs, (d.toordinal() + w + 1,))
            pts = xs[lo:hi]
            if len(pts) >= 3:
                return statistics.median(p[1] for p in pts), statistics.median(p[2] for p in pts)
        return None
    for f in sorted(Path(txt_dir).glob("warofrebellion*unit.txt")):
        book = f.stem
        L = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, l in enumerate(L):
            if not HEAD.match(l):
                continue
            stats["headings"] += 1
            blk, j = l, i
            while not DATE.search(blk) and j < i + 3 and j + 1 < len(L):
                j += 1
                if L[j].strip():
                    blk += " " + L[j].strip()
            m = DATE.search(blk)
            rec = {"book": book, "volume": vols.get(book), "line": i + 1, "text": blk[:m.end() if m else 200][:220]}
            if not m:
                stats["no date"] += 1; continue
            mon = m.group(1).lower().rstrip(".")
            mi = next((k for k, x in enumerate(MONTHS) if x.startswith(mon[:3])), None)
            try:
                d = date(int(m.group(3)), mi + 1, int(m.group(2)))
            except (TypeError, ValueError):
                stats["bad date"] += 1; continue
            if not date(1861, 1, 1) <= d <= date(1865, 12, 31):
                stats["date outside the war"] += 1; continue
            cmd, pl, near = parse_heading(blk, m)
            side = side_above(L, i)
            rec.update(date=d.isoformat(), side=side, command=[c[1] for c in cmd], place=pl)
            def done(reason):
                rec["result"] = reason; stats[reason] += 1; lines_out.append(rec)
            low = cmd[0][0] if cmd else None
            use_signer = USE_SIGNER and not cmd or USE_SIGNER and (low in ("brigade", "division", "corps") and not any(
                (part_key(p)[0] or part_key(p)[1]) for lv, p in cmd if lv in ("brigade", "division", "corps")))
            if not cmd and not use_signer:
                done("no command named"); continue
            if low in ("army", "dept"):
                done(f"{low} headquarters: not used"); continue
            if not pl or len(pl) < 3:
                done("no place"); continue
            pl = clean_place(pl); rec["place"] = pl
            name, st = split_place(pl)
            ctx_b = context(book, d)
            loc = locate(name, st, ctx_b)
            # later parts of the place ("White House, Lookout Mountain"): a place they name is next to the first one
            for part in [x.strip() for x in pl.split(",")[1:]]:
                n2, s2 = split_place(part)
                if len(n2) < 4 or n2.lower().strip(" .") in ABBR or re.search(r"(?i)\b(field|camp|headquarters|hdqrs)\b", n2):
                    continue
                l2 = locate(n2, s2 or st, ctx_b)
                if not l2:
                    continue
                if not loc or km(loc[0][:2], l2[0][:2]) > 50:
                    alt = locate(name, st or l2[1], (l2[0][0], l2[0][1]))
                    if alt and km(alt[0][:2], l2[0][:2]) <= 50:
                        loc = alt
                    else:
                        loc = ((l2[0][0], l2[0][1], max(l2[0][2], 5000)), l2[1])
                    stats["place set by a later part of the heading's place"] += 1
                break
            pending = not loc                   # try the commanded units' routes once the command is known
            (lat, lon, gp), pst = loc if loc else ((None, None, None), None)
            sides = [side] if side else ["Union", "Confederate"]
            units, how, head_corps = None, None, None
            if use_signer:
                sg = signer(L, j)
                if not sg or not sg[0]:
                    done("no command named, no signer" if not cmd else "command has no number or name"); continue
                sn, ini = sg
                best = None
                for s in sides:
                    for tid, ents in cmd_ix.get((s, sn), {}).items():
                        for td, lv, cini, grp, rs in ents:
                            if abs((td - d).days) > TABLE_DAYS or (ini and cini and ini != cini) or len(rs) < 2:
                                continue
                            if re.search(r"District|Post\b|Defenses|Garrison|Forces|Department|Sub-|Troops", grp) or \
                                    tid in returns:
                                continue                  # a district commander: his "division" is spread over a region
                            if low and lv != low:
                                continue                  # "Headquarters Cavalry Corps" signed by a man who led a brigade
                            rank = {"corps": 3, "division": 2, "brigade": 1}[lv]
                            key = (abs((td - d).days), -rank)
                            if best is None or key < best[0]:
                                best = (key, s, tid, td, lv, grp, rs, set())
                            if best and best[2] == tid and best[4] == lv and best[5] != grp:
                                best[7].add(grp)
                if not best:
                    done(f"signer commands nothing in a table within {TABLE_DAYS} days"); continue
                if any(abs((hd - d).days) <= 60 for hd in head_cmd.get(sn, [])):
                    done("signer heads an army or department then"); continue
                _, s_, tid, td, lv, grp, rs, other = best
                if other:
                    done("signer ambiguous"); continue
                low, side = lv, s_
                units = [(r["unit_code"], r["unit"]) for r in rs]
                how = f"{lv} of signer {sn} in table {tid} ({td.isoformat()})"
                rec["signer"] = sn
            elif low == "regiment":
                nm, sec = regt_name(cmd[0][1])
                if not nm:
                    done("regiment not parsed"); continue
                hits = set()
                for s in sides:
                    c = P.match(nm, sec if sec in ("cavalry", "artillery") else "infantry", s, d.isoformat(), idx)
                    if c and not c.startswith("AMB"):
                        hits.add((s, c))
                if len(hits) != 1:
                    done("regiment not matched" if not hits else "regiment on both sides"); continue
                (s_, c_), = hits
                units, how, side = [(c_, nm)], "regiment", s_
            elif True:
                spec = {}
                for lev, p in cmd:
                    if lev in ("brigade", "division", "corps") and lev not in spec:
                        spec[lev] = part_key(p)
                if not any(v[0] or v[1] for v in spec.values()):
                    done("command has no number or name"); continue
                named = any(v[1] for v in spec.values())
                if not named and ("corps" not in spec or spec["corps"][0] is None):
                    done("numbered command without its corps"); continue     # "Third Brigade, First Division" alone: which army?
                found = None
                for s in sides:
                    if s not in tabs:
                        continue
                    k0 = bisect_left(tdates[s], d)
                    cand = sorted(range(max(0, k0 - 40), min(len(tabs[s]), k0 + 40)), key=lambda k: abs((tabs[s][k][0] - d).days))
                    for k in cand:
                        td, tid, rows = tabs[s][k]
                        if abs((td - d).days) > TABLE_FAR:
                            break
                        hit = [r for r in rows if all(comp_ok(spec[lv], r["k"][lv]) for lv in spec)]
                        if not hit:
                            continue
                        groups = {tuple((r.get(lv) or "") for lv in ("brigade", "division", "corps")
                                        if ["brigade", "division", "corps"].index(lv) >= ["brigade", "division", "corps"].index(low))
                                  for r in hit}
                        if len(groups) > 1:
                            found = found or ("ambiguous", s, tid, td)
                            break
                        if found and found[0] != "ambiguous":
                            found = ("two sides", s, tid, td); break
                        found = ("ok", s, tid, td, hit); break
                if not found:
                    done(f"command not in a table within {TABLE_FAR} days"); continue
                if found[0] != "ok":
                    done(f"command {found[0]}"); continue
                _, side, tid, td, hit = found
                head_corps = spec.get("corps", (None,))[0]
                units = [(r["unit_code"], r["unit"]) for r in hit]
                how = f"{low} in table {tid} ({td.isoformat()})"
                if abs((td - d).days) > TABLE_DAYS:
                    # a far table: only members the command also holds in a table on the other side of the date
                    # (the command did not change around the heading for them)
                    other = set()
                    for td2, tid2, rows2 in tabs[side]:
                        if tid2 != tid and abs((td2 - d).days) <= TABLE_FAR and (td2 - d).days * (td - d).days <= 0:
                            other |= {r["unit_code"] for r in rows2 if all(comp_ok(spec[lv], r["k"][lv]) for lv in spec)}
                    n0 = len(units)
                    units = [u for u in units if u[0] in other]
                    stats["members dropped: far table, not held on the other side of the date"] += n0 - len(units)
                    if not units:
                        done(f"command only in a table over {TABLE_DAYS} days away, not confirmed"); continue
                    how += f", confirmed by a table on the other side of the date"
            if pending:
                v = vote(name, st, [cd for cd, _ in units], d)
                if v:
                    stats["place by the commanded units' routes"] += 1
                if not v:
                    done("place not located"); continue
                (lat, lon, gp), pst = v
            prec = max(PREC[low], gp) + (3000 if near else 0)
            # who the heading places. A brigade / division / corps heading is where its headquarters were; its units
            # were usually near, but corps were split ("Detachment Nineteenth Army Corps" in Virginia while other
            # divisions stayed in Louisiana), tables list companies and garrisons with a field corps, and a commander's
            # name can match another command. Per unit:
            #  - companies / detachments named in the table row are not the regiment (Company C, 1st Indiana Cavalry
            #    was the Thirteenth Corps' escort at Vicksburg; the regiment was in Arkansas): not placed
            #  - the unit's own clear positions (Dyer's route, post lines, NPS histories) within ROUTE_DAYS: if every one
            #    is beyond rail / boat reach of the heading's place (150 + 250 km a day, as resolve_mentions.step), the
            #    unit was not with its headquarters: not placed
            #  - a heading that names a detachment of its command places only units whose own route is near it then
            detached = bool(re.search(r"(?i)\bdetach", " ".join(c[1] for c in cmd)))
            keep = []
            for code, nm in units:
                if low != "regiment" and re.search(r"(?i)\bcompan|\bcos?\.|\bsection\b|\bdetach|\bsquadron\b|\bbattalion\b", nm or "") \
                        and not re.search(r"(?i)battalion\b.*\b(infantry|cavalry|artillery|sharpshooters)\b$|^\S+ battalion", nm or ""):
                    stats["member skipped: companies or detachment of the unit"] += 1; continue
                if low != "regiment":
                    t = (d - D0_).days
                    pts = [(max(0, a[0] - t, t - a[1]), a) for a in tracks.get(code) or ()]
                    pts = [(dt, a) for dt, a in pts if dt <= ROUTE_DAYS]
                    far = [dt for dt, a in pts if too_fast(km(a[3:5], (lat, lon)), dt + a[2], prec / 1000)]
                    if pts and len(far) == len(pts):
                        stats["member skipped: its own route is elsewhere"] += 1; continue
                    if head_corps and side == "Union":
                        att = [ns for a0, a1, ns in dyer_corps.get(code, ()) if a0 <= t <= a1]
                        if att and not any(head_corps in ns for ns in att):
                            stats["member skipped: Dyer's puts it in another corps then"] += 1; continue
                    # stayed put: the unit's last position before and first after (each within BRACKET_DAYS) are
                    # within 100 km of each other and the heading's place is over 300 km from them ("Thirteenth Army
                    # Corps, Steamship McClellan": headquarters sailed for Texas, the divisions stayed in Louisiana); likewise
                    # when the two positions differ but the heading is a 600 km detour from the way between them
                    tr = tracks.get(code) or ()
                    bef = [a for a in tr if a[1] < t and t - a[1] <= BRACKET_DAYS]
                    aft = [a for a in tr if a[0] > t and a[0] - t <= BRACKET_DAYS]
                    if bef and aft:
                        pa_, na_ = bef[-1], aft[0]
                        d_ba, d_bp, d_pa = km(pa_[3:5], na_[3:5]), km(pa_[3:5], (lat, lon)), km((lat, lon), na_[3:5])
                        if min(d_bp, d_pa) > 300 + prec / 1000:
                            if d_ba <= 100:
                                stats["member skipped: stayed elsewhere (positions before and after)"] += 1; continue
                            # or moved between them without going near the heading: the 5th Iowa at Cherokee, Ala.,
                            # Oct. 29, 1863 and Chattanooga Nov. 20 was not with the Seventeenth Corps at Vicksburg
                            if d_bp + d_pa - d_ba > 600:
                                stats["member skipped: moved elsewhere (positions before and after)"] += 1; continue
                    if detached and not any(
                            km(a[3:5], (lat, lon)) <= 150 for dt, a in pts):
                        stats["member skipped: detachment heading, unit's route not near"] += 1; continue
                keep.append((code, nm))
            if not keep:
                done("placed no member (all elsewhere by their routes)"); continue
            units = keep
            rec.update(result="placed", level=low, units=len(units), side=side, lat=lat, lon=lon, precision_m=prec)
            stats["placed"] += 1; stats[f"placed: {low}"] += 1; lines_out.append(rec)
            for code, nm in units:
                claims.append({"type": "unit_at", "source": "or", "confidence": CONF[low],
                               "span": rec["text"][:200], "extracted_by": "rules:or_datelines_v2",
                               "note": f"{rec['volume']} line {i + 1}: headquarters of the {how}",
                               "unit": {"nps_code": code, "display_name": nm, "side": side},
                               "unit_mention": nm, "place_mention": pl[:120],
                               "place": {"display_name": name, "state": pst, "lat": lat, "lon": lon, "precision_m": prec,
                                         "kind": "town"},
                               "presence": "present", "portion": "whole",
                               "date_start": d.isoformat(), "date_end": d.isoformat(), "date_precision": "day"})
    # one claim per unit and day: the finest level (smallest precision) wins
    best = {}
    for c in claims:
        k = (c["unit"]["nps_code"], c["date_start"])
        if k not in best or c["place"]["precision_m"] < best[k]["place"]["precision_m"]:
            best[k] = c
    claims = list(best.values())
    with open(out_lines, "w", encoding="utf-8") as fo:
        for r in lines_out:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    doc = {"about": "Unit positions from the headings of Official Records letters and reports (HEADQUARTERS <command>, <place>, <date>), "
                    "by pipeline/or_datelines.py.",
           "sources": {"or": {"title": "The War of the Rebellion: Official Records, Series I (letter and report headings)",
                              "kind": "official_records", "url": "https://archive.org/details/warofrebellion", "public_domain": 1,
                              "notes": "commands matched to OR organization tables within 45 days (120 when a table on the other side of the "
                                       "date also holds the unit); members whose own route is elsewhere are dropped; places located with "
                                       "data/places/geocoded.csv and USGS GNIS"}},
           "claims": claims}
    json.dump(doc, open(out_claims, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    by = Counter(c["unit"]["side"] for c in claims)
    print("claims", len(claims), dict(by), "units", len({c['unit']['nps_code'] for c in claims}))


if __name__ == "__main__":
    main(*sys.argv[1:])
