"""Parse every located Official Records organization table into unit placements.

Usage:
  python3 pipeline/parse_or_all.py data/or/tables.jsonl <dir of OR text files> \
      data/external/acw_battle_data/nps_units.csv data/or/placements.jsonl

For each table (from locate_or_tables.py): walk corps / division / brigade headers,
read unit lines and their commanders, match units to NPS unit codes (both sides),
parse the heading date. Output one row per unit placement:
  table_id, side, army (heading), as_of start/end, corps, division, brigade, unit,
  unit_code (or AMBIGUOUS:...), commanders, confidence (+ note for two-column scramble).
"""
import csv, json, re, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parse_or_organization import join_wrapped, classify, ORD, RANK
from unit_match import Index, match_named

STATES = {"Alabama": "AL", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
          "Florida": "FL", "Georgia": "GA", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY",
          "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
          "Mississippi": "MS", "Missouri": "MO", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
          "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "Ohio": "OH", "Oregon": "OR", "Pennsylvania": "PA",
          "Rhode Island": "RI", "South Carolina": "SC", "Tennessee": "TN", "Texas": "TX", "Vermont": "VT", "Virginia": "VA",
          "West Virginia": "WV", "Wisconsin": "WI", "District of Columbia": "DC"}
ST_RE = re.compile(r"^(" + "|".join(sorted(map(re.escape, STATES), key=len, reverse=True)) + r")\b")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s):
    """'July 1-3, 1863' -> ('1863-07-01','1863-07-03'); 'December 26, 1862-January 5, 1863'; 'May 31, 1864'."""
    s = (s or "").replace("lS", "18").replace("l8", "18")
    parts = re.findall(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?,?\s*(18\d\d)?", s, re.I)
    years = re.findall(r"18[6][0-5]", s)
    if not parts or not years:
        return None, None
    y_end = int(years[-1])
    m0, d0, d0b, y0 = parts[0]
    y0 = int(y0) if y0 else (int(years[0]) if len(years) > 1 else y_end)
    start = f"{y0}-{MONTHS[m0[:3].lower()]:02d}-{int(d0):02d}"
    if len(parts) > 1:
        m1, d1, _, y1 = parts[-1]
        end = f"{int(y1) if y1 else y_end}-{MONTHS[m1[:3].lower()]:02d}-{int(d1):02d}"
    else:
        end = f"{y0}-{MONTHS[m0[:3].lower()]:02d}-{int(d0b or d0):02d}"
    from datetime import date as _d
    try:
        _d.fromisoformat(start); _d.fromisoformat(end)
    except ValueError:
        return None, None                                  # day 0, February 30 ... from scan errors
    if end < start:
        end = start
    return start, end


def nps_index(path):
    idx = {}
    for u in csv.DictReader(open(path, encoding="utf-8")):
        side = "Union" if u["belligerent"] == "US" else "Confederate"
        try:
            o = int(u["ordinal"] or 0)
        except ValueError:
            continue
        idx.setdefault((side, u["state"], o, u["type"], u["func"]), []).append(u)
    return idx


def fix_ocr(u):
    u = re.sub(r"^(\d+)(tli|tb|lh|tk|tli\.|ih)\b", r"\1th", u)
    u = re.sub(r"^(1)(si|sl|8t)\b", r"\1st", u)
    u = re.sub(r"^l(st|th|\d)", r"1\1", u)
    return u.replace("Netv ", "New ").replace("Carolma", "Carolina")


def split_units(u):
    """'6th and 9th Tennessee' / '2d, 10th, 20th, and 37th Tennessee' -> one name per regiment."""
    u = re.sub(r"^(\d+(?:st|d|nd|rd|th))\s*[-–]\s*(\d+(?:st|d|nd|rd|th))\b", r"\1 and \2", u)   # "10th-19th South Carolina"
    m = re.match(r"^((?:\d+(?:st|d|nd|rd|th)\s*,?\s*(?:and\s+)?)+)(\D.*)$", u)
    if not m:
        return [u]
    nums = re.findall(r"\d+(?:st|d|nd|rd|th)", m.group(1))
    return [f"{n} {m.group(2).strip()}" for n in nums] if len(nums) > 1 else [u]


def match(unit, section, side, date, idx):
    m = ORD.match(unit)
    if not m:
        return None
    n, rest = int(m.group(1)), m.group(2)
    sm = ST_RE.match(rest)
    if not sm:
        return None
    st = STATES[sm.group(1)]
    if "Battery" in rest or "Light" in rest:
        return None                                        # batteries need their own matching
    typ = "B" if "Battalion" in rest else "R"
    func = "A" if "Heavy Artillery" in rest or "Artillery" in rest else (
        "C" if "Cavalry" in rest or "Mounted" in rest or section == "cavalry" else "I")
    cands = idx.get((side, st, n, typ, func), []) or (idx.get((side, st, n, typ, ""), []) if func in ("I", "C") else [])
    if len(cands) > 1:
        reg = [u for u in cands if not u.get("special")] or cands          # not militia / reserves / state guards
        if len(reg) == 1:
            return reg[0]["unit_code"]
        plain = [u for u in reg if not re.search(r"\d\d$", u["unit_code"])]  # code without a numeric suffix
        if len(plain) == 1:
            return plain[0]["unit_code"]
        cands = reg
        early = date and date < "1861-09"
        pick = [u for u in cands if ("months" in u["unit_name"]) == bool(early) and "Militia" not in u["unit_name"]]
        if len(pick) == 1:
            return pick[0]["unit_code"]
        return "AMBIGUOUS:" + "|".join(u["unit_code"] for u in cands[:5])
    return cands[0]["unit_code"] if cands else None


UNITWORD = re.compile(r"\d+\s?(?:st|d|nd|rd|th|tli|tb|tk|st\.)\b|\b(Infantry|Cavalry|Artillery|Battery|Batteries|Battalion|Regiment|Legion|Brigade|"
                      r"Compan(y|ies)|Troop|Guards?|Rangers|Scouts|Volunteers|Militia|Reserves|Squadron|Sharpshooters|Rifles|"
                      r"Zouaves|Engineers?|Sappers|Pioneers|Detachment|Siege Train|Train|Signal|Provost|Convalescents|"
                      r"Invalid|Veteran|Colored|Heavy|Light|Mounted|Partisan|Home|Corps|men|commanding|Navy|Marines)\b", re.I)
STATION = re.compile(r"^(?:Post of|Garrison of|Defenses of|Forces at|Troops at|Troops in|At|Camp near|Posts? at|Fort|Camp|"
                     r"Batter(?:y|ies) at)\b")
ST_ABBR_RE = re.compile(r",\s*(?:Va|W\.\s*Va|N\.\s*C|S\.\s*C|Ga|Fla|Ala|Miss|La|Tex|Ark|Tenn|Ky|Mo|Md|Kans|Ind\.\s*T|"
                        r"Ill|Ohio|Pa|D\.\s*C|N\.\s*Y|Ariz|N\.\s*Mex|Cal|Oreg|Wash)\.?\s*[*+†‡§!|]?\s*[.:]?\s*$")


NOTST = r"^(Unattached|Official|Total|Aggregate|Detached|Reserve|Staff|Escort|Miscellaneous|Unassigned|Not brigaded|Headquarters|" \
        r"Independent|Unbrigaded|General|Recapitulation|Grand total|Effective|Present|Absent|Note|In the field|Not brigaded|" \
        r"Major|Brigadier|Assistant|Secretary|President|Chief|Aide|Officers?|Wounded|Killed|Missing|Remarks|Command|Attached|" \
        r"Transferred|Ordered|Relieved|Assigned|Organized|Consolidated|Chap\.)\b"


_KNOWN = None


def known_places():
    """Place names Dyer's mentions 3+ times (data/places/geocoded.csv), lower case; state names excluded."""
    global _KNOWN
    if _KNOWN is None:
        p = Path(__file__).parent.parent / "data/places/geocoded.csv"
        _KNOWN = {r["name"].lower() for r in csv.DictReader(open(p, encoding="utf-8")) if int(r["mentions"] or 0) >= 3} \
            - {s.lower() for s in STATES}
    return _KNOWN


def is_station(l):
    """A line naming where the units below it were (no unit words, no commander): "Fort Pillow.", "Trenton, Tenn.",
    "Post of Natchez:", "At Columbus." -- or a short title-case place name the locator decides on later."""
    l = " ".join(l.split())
    x = re.sub(r"[\s.:,;*+†‡§!|]+$", "", l)
    if re.match(NOTST, x) or UNITWORD.search(x) or re.search(r"[’']s?\b\s*$|[’']s\s|\b(Lieut|Capt|Col|Maj|Gen|Brig)\.|\d{3,}|\(", x) or len(x) < 4:
        return False
    if re.match(r"^(?:Post of|Garrison of|Defenses of|Forces at|Troops at|At|Posts? at|Camp near)\s+[A-Z]", x):
        return True
    words = x.split()
    if not (ST_ABBR_RE.search(l) or re.match(r"^(Fort|Camp|Forts)\s", x)) and x.lower() not in known_places():
        return False                              # a bare name must be a place Dyer's knows ("Jones" is a wrapped surname)
    return (len(words) <= 5 and all(w[:1].isupper() or w in ("of", "de", "la", "and", "No.", "the") or w[:1].isdigit()
                                     for w in words)
            and bool(ST_ABBR_RE.search(l) or re.match(r"^(Fort|Camp|Forts)\s", x) or len(words) <= 3))


def parse_table(lines, t, idx):
    corps = div = brig = None; section = "infantry"; rows = []; last = None; prev = None; scrambled = set(); station = None; prevl = None; cmdr = {}; hdr_pending = None
    start, end = parse_date(t.get("date_text") or t["heading"])
    for l in join_wrapped(lines):
        k = classify(l)
        ln = " ".join(l.split())
        if k != "unit" or STATION.match(ln) or re.match(NOTST, ln):
            station = None                                 # a new header ends the station block
        bare = not (ST_ABBR_RE.search(ln) or re.match(r"^(Fort|Camp|Forts|Post|Posts|Garrison|Defenses|Forces|Troops|At)\s", ln))
        wrapped = prevl is not None and (re.search(r"(\b[A-Z][a-z]{0,2}\.|,|[^.:;])\s*$", prevl) is not None)
        if k == "unit" and is_station(ln) and not (bare and wrapped):    # "Col. John L." + "Jones." is a surname
            station = re.sub(r"[\s.:,;*+†‡§!|]+$", "", ln)          # "Fort Pillow." / "Trenton, Tenn." / "Post of Natchez:"
        prevl = ln
        if k in ("corps", "division", "brigade"):
            lv = k
            for x in {"corps": ("corps", "division", "brigade"), "division": ("division", "brigade"), "brigade": ("brigade",)}[lv]:
                cmdr.pop(x, None)
            hdr_pending = lv
        elif k == "unit":
            hdr_pending = None
        if k == "corps":
            corps, div, brig, last = re.sub(r"[’']S\b", "'s", l.title()).rstrip(" ."), None, None, None
            section = "cavalry" if "CAVALRY" in l else ("artillery" if "ARTILLERY" in l else "infantry")
        elif k == "division":
            div, brig, last = re.sub(r"[’']S\b", "'s", l.title()).rstrip(" ."), None, None
            if "CAVALRY" in l:
                section = "cavalry"
        elif k == "brigade":
            if prev == "brigade":
                scrambled.add((corps, div))
            brig, last = l.rstrip(" .*+†‡"), None
        elif k == "commander":
            if hdr_pending and hdr_pending not in cmdr:
                cmdr[hdr_pending] = " ".join(l.split()).rstrip(" .,")      # "Brig. Gen. Roswell S. Ripley" heads the brigade
            hdr_pending = None
            if last is not None and last.get("_open"):
                last["commanders"].append(l.rstrip("."))
        else:
            name, cmd = l, None
            m = re.match(r"^(.*?),\s*((?:Lieut\.|Brig\.|Maj\.|Col\.|Capt\.|Gen\.).*)$", l)
            if m:
                name, cmd = m.group(1), m.group(2)
            name = re.sub(r"\s*:\s*[*+†‡§%f]?\s*$", ":", name.strip())
            open_ = name.endswith(":")
            name = name.rstrip(" :.*+†‡§%")
            name = fix_ocr(name)
            if len(name) < 4 or not name[0].isalnum() or re.search(r"\bSee\b.{0,40}Troops", name):
                prev = k; continue
            sec = "artillery" if (brig or "").startswith("Artillery") or section == "artillery" else section
            for nm in split_units(name):
              row = {"table_id": f"{t['book']}:{t['start']}", "side": t["side"], "heading": t["heading"][:160],
                   "date_start": start, "date_end": end, "corps": corps, "division": div, "brigade": brig,
                   "unit": nm, "commanders": [cmd.rstrip(".")] if cmd else [], "_open": open_}
              if station and station != name.rstrip(" .:"):
                  row["station"] = station
              if cmdr:
                  row["cmdrs"] = dict(cmdr)
              if nm != name:
                  row["consolidated_from"] = name
              if t["side"] in ("Union", "Confederate"):
                  code = match(nm, sec, t["side"], start, idx)
                  if code:
                      row["unit_code"] = code
              rows.append(row); last = row
        prev = k
    for r in rows:
        if not r.get("unit_code") and t["side"] in ("Union", "Confederate") and IX is not None:
            sec = "cavalry" if "Cavalry" in f"{r['brigade']} {r['division']} {r['corps']}" else (
                  "artillery" if "Artillery" in f"{r['brigade']} {r['division']}" else "infantry")
            code, note = match_named(r["unit"], t["side"], sec, r["commanders"], IX)
            if code:
                r["unit_code"] = code; r["matched_by"] = "named"
                if note: r["portion"] = note
    for r in rows:
        r.pop("_open", None)
        if (r["corps"], r["division"]) in scrambled:
            r["confidence"] = "low"; r["note"] = "two-column text read across columns; brigade may be wrong"
    return rows


IX = None


def main(tables_path, txt_dir, units_csv, out_path):
    global IX
    idx = nps_index(units_csv)
    IX = Index(units_csv)
    tables = [json.loads(l) for l in open(tables_path, encoding="utf-8")]
    by_book = {}
    for t in tables:
        by_book.setdefault(t["book"], []).append(t)
    allrows = []
    for book, ts in by_book.items():
        L = [l.strip() for l in (Path(txt_dir) / f"{book}.txt").read_text(encoding="utf-8", errors="replace").splitlines()]
        for t in ts:
            allrows += parse_table(L[t["start"] - 1:t["end"]], t, idx)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in allrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    st = Counter()
    for r in allrows:
        c = r.get("unit_code") or ""
        st[(r["side"], "matched" if c and not c.startswith("AMB") else ("ambiguous" if c else "unmatched"))] += 1
    print(f"tables: {len(tables)}; unit placements: {len(allrows)}; with a parsed date: {sum(1 for r in allrows if r['date_start'])}")
    for k in sorted(st):
        print(f"  {k[0]:12} {k[1]:10} {st[k]}")
    codes = Counter((r["side"], r["unit_code"]) for r in allrows if r.get("unit_code") and not r["unit_code"].startswith("AMB"))
    print("distinct matched units:", Counter(s for s, _ in codes))
    print("low confidence (two-column scramble):", sum(1 for r in allrows if r.get("confidence") == "low"))


if __name__ == "__main__":
    main(*sys.argv[1:5])
