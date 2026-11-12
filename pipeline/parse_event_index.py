"""Parse Dyer's Part II alphabetical index (printed pp. 595-659) into an event catalog.

Each index row reads   <Place>, <State>. — <Type> [to|from|on] <Date>
e.g.                   Greenville, Miss. — Exp. to Feb. 14-26, 1863
                       Chattanooga-Ringgold — Camp'n Nov. 23-27, 1863     (no state)
                       (See De Green's.)                                  (cross-reference)

Usage:
    python pipeline/parse_event_index.py 08697590_3359_djvu.xml data/dyers/event_index.jsonl
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from segment_dyers import read_pages, split_header, reading_order, fix_page_numbers  # noqa: E402
from extract_dyers import parse_date, YearTracker, MON  # noqa: E402

FIRST, LAST = 595, 659

STATES = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "cal": "CA", "colo": "CO", "col": "CO", "conn": "CT", "dak": "DT",
    "d c": "DC", "del": "DE", "fla": "FL", "ga": "GA", "idaho": "ID", "ill": "IL", "ind t": "IT", "i t": "IT",
    "ind": "IN", "iowa": "IA", "kan": "KS", "kans": "KS", "ky": "KY", "la": "LA", "md": "MD", "me": "ME",
    "mass": "MA", "mich": "MI", "minn": "MN", "miss": "MS", "mo": "MO", "mont": "MT", "neb": "NE", "nev": "NV",
    "n c": "NC", "n j": "NJ", "n m": "NM", "n mex": "NM", "n y": "NY", "ohio": "OH", "ore": "OR", "pa": "PA",
    "s c": "SC", "tenn": "TN", "texas": "TX", "tex": "TX", "utah": "UT", "va": "VA", "vt": "VT", "w va": "WV",
    "wash": "WA", "wis": "WI", "penna": "PA", "penn": "PA", "dak t": "DT", "dak ter": "DT", "dakota": "DT",
    "n mex": "NM", "new mex": "NM", "cali": "CA", "ariz t": "AZ", "w v": "WV", "s c": "SC", "wyo": "WY", "n mexico": "NM", "indian ter": "IT", "ind ter": "IT",
}
STATE_RE = re.compile(r"(?:[,.]\s*|\s+)(" + "|".join(sorted((re.escape(k).replace(r"\ ", r"\.?\s*") for k in STATES),
                                                      key=len, reverse=True)) + r")\.?\s*$", re.I)

TYPES = [  # (pattern at start of the right-hand side, normalized type)
    (r"camp'?n|campaign", "campaign"), (r"siege", "siege"), (r"battles?", "battle"),
    (r"engm'?ts?|engagements?", "engagement"), (r"actions?", "action"), (r"combats?", "combat"),
    (r"assaults?", "assault"), (r"attacks?", "attack"), (r"skirs?|skirmish(?:es)?|skrs?", "skirmish"),
    (r"affairs?", "affair"), (r"exp'?d?\.?|exped(?:ition)?", "expedition"), (r"raids?", "raid"),
    (r"rec\.?|recon\.?|reconn?oiss?ance", "reconnaissance"), (r"scouts?", "scout"),
    (r"op'?ns|operations?", "operations"), (r"adv\.?|advance", "advance"), (r"retreat", "retreat"),
    (r"pursuit", "pursuit"), (r"capture|capt\.?", "capture"), (r"surrender", "surrender"),
    (r"evac\.?|evacuation", "evacuation"), (r"occupation|occ\.?", "occupation"),
    (r"demonst?\.?|demonstrations?", "demonstration"), (r"bombardment|bomb\.?", "bombardment"),
    (r"destruction|dest\.?", "destruction"), (r"defense|defence", "defense"), (r"march", "march"),
    (r"descent", "descent"), (r"burning", "burning"), (r"explosion", "explosion"), (r"mutiny", "mutiny"),
    (r"riot", "riot"), (r"massacre", "massacre"), (r"ambuscade|ambush", "ambush"),
]
OCR_MONTHS = {"mav": "May", "rnay": "May", "julv": "July", "juiv": "July", "jnly": "July", "juty": "July",
              "aue": "Aug", "aug,": "Aug", "dee": "Dec", "deo": "Dec", "men": "Mar", "mch": "Mar", "meh": "Mar",
              "noy": "Nov", "nov,": "Nov", "june": "June", "jane": "June", "apr": "Apr", "aprl": "Apr", "oet": "Oct",
              "oct,": "Oct", "sept": "Sept", "scpt": "Sept", "fob": "Feb", "feh": "Feb", "jau": "Jan", "jan": "Jan"}
TYPES += [(r"dmnstn|demon", "demonstration"), (r"bomb'?t", "bombardment"), (r"ab[a]?n'?d|aban'?d", "abandonment"),
          (r"opn'?s|on'ns|op", "operations"), (r"sur", "surrender"), (r"[kf]xp|exn", "expedition"),
          (r"re-?occ", "reoccupation"), (r"def", "defense"), (r"[be]ngm'?t", "engagement"),
          (r"d[e]?st'?n", "destruction"), (r"mov'?t", "movement"), (r"garr", "garrison"), (r"dscnt", "descent"),
          (r"rattle", "battle"), (r"okir|slkir|skirm", "skirmish"), (r"oce", "occupation"), (r"recto|ree|hec", "reconnaissance"),
          (r"arrival", "arrival"), (r"battys", "battery action"),
          (r"reconn?", "reconnaissance"), (r"ass", "assault"), (r"surr", "surrender"), (r"cap", "capture"),
          (r"att'?k", "attack"), (r"ret", "retreat"), (r"seized|seizure", "seizure"), (r"a'?bd|abandoned", "abandonment"),
          (r"[fe]ngm'?\s?t", "engagement"), (r"sk[il1]rs?", "skirmish"), (r"dam", "dam construction"),
          (r"occ", "occupation"), (r"op'?ns?", "operations"), (r"exps?", "expedition"), (r"scts?", "scout")]
TYPE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z'\u2019]*(?:\s?t\b)?)\.?(?:\s+(to|from|on|of|against|in|near|at|"
                     r"into|up|down|toward|towards))?(?=\s|$)", re.I)
DASH = re.compile(r"\s*[,.]?\s*(?:—|–|--|-\s*—|\.—|-(?=\s))\s*")


def norm_type(raw):
    r = raw.strip(".").lower().replace("\u2019", "'")
    for p, name in TYPES:
        if re.fullmatch(p, r):
            return name
    return "other:" + r


def parse_row(text, page):
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"^18[56]\d\s+(?=[A-Z])", "", t)                       # stray year from a neighbouring row
    see = re.match(r"^\(?\s*See\s+(.+?)\.?\s*\)?\.?$", t, re.I)
    if see:
        return {"kind": "see", "target": see.group(1).strip(" ."), "page": page, "raw": t}
    parts = DASH.split(t, maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = parts
    m = TYPE_RE.match(right)
    if not m:
        return None
    rest = right[m.end():].strip()
    rest = re.sub(r"\b[1lI][8SX]\s?[6G]\s?([0-9SGIlO])\b",
                  lambda m: "186" + m.group(1).translate(str.maketrans("SGIlO", "86110")), rest)
    rest = re.sub(r"[^A-Za-z0-9,\-\u2014 .]", " ", rest)                 # stray marks
    rest = re.sub(r"\b([A-Za-z]{3,4})\b\.?", lambda m: OCR_MONTHS.get(m.group(1).lower(), m.group(1)) +
                  ("." if m.group(1).lower() in OCR_MONTHS else ""), rest)
    rest = re.sub(r"\s+,", ",", rest)
    rest = re.sub(r",\s*,", ",", rest)
    rest = re.sub(r"(?<=[A-Za-z])'(?=\s*\d)", ".", rest)          # Sept' 7' -> Sept. 7
    dm = re.search(MON, rest)
    if not dm:
        return None
    date_text = rest[dm.start():]
    date_text = re.sub(r"(\d)\s*[—-]\s*,", r"\1,", date_text)          # 'May — , 1862' -> month only
    date_text = re.sub(rf"({MON})\s+[—-]+\s*,", r"\1,", date_text)
    date_text = re.sub(r"\bMch\b", "Mar", date_text)
    date_text = date_text.replace("1S6", "186").replace("18G", "186")
    parsed = parse_date(date_text, YearTracker())
    if parsed and parsed[1] < parsed[0]:                                # 'May 22-2«': garbled end day
        parsed = (parsed[0], parsed[0], parsed[2])
    sm = STATE_RE.search(left)
    state = None
    place = left
    if sm:
        key = re.sub(r"[.\s]+", " ", sm.group(1).lower()).strip()
        state = STATES.get(key)
        place = left[:sm.start()]
    return {"kind": "event", "place": re.sub(r"^[^A-Za-z]+", "", place).strip(" ,."), "state": state, "type": norm_type(m.group(1)),
            "type_raw": m.group(1), "prep": (m.group(2) or "").lower() or None,
            "date_start": parsed[0] if parsed else None, "date_end": parsed[1] if parsed else None,
            "date_precision": parsed[2] if parsed else None, "page": page, "raw": t}


YEARISH = re.compile(r"^\s*[1lI][8SX]\s?[6G]\s?[0-9SGIlO]\s*\.?\s*$")


def rows_of(W, lines):
    """Merge LINE boxes that share a printed row (same half of the page, overlapping height).
    Lines that hold only a year are attached to the nearest row in their half that lacks one."""
    mid = W / 2
    out = []
    for half in (0, 1):
        ls = sorted([l for l in lines if ((l[0] + l[2]) / 2 >= mid) == bool(half)], key=lambda x: x[1])
        years = [l for l in ls if YEARISH.match(l[4])]
        body = [l for l in ls if not YEARISH.match(l[4])]
        rows = []
        for l in body:
            h = max(l[3] - l[1], 10)
            for row in rows:
                if abs(row[0][1] - l[1]) < h * 0.6:
                    row.append(l)
                    break
            else:
                rows.append([l])
        def has_year(row):
            return bool(re.search(r"[1lI][8SX]\s?[6G]\s?[0-9SGIlO]\s*\.?\s*$", " ".join(x[4] for x in row)))
        for y in years:                                   # nearest row, by vertical centre, without a year
            yc = (y[1] + y[3]) / 2
            cands = [r for r in rows if not has_year(r) and r[0][2] <= y[0] + 40]
            if cands:
                best = min(cands, key=lambda r: abs((r[0][1] + r[0][3]) / 2 - yc))
                if abs((best[0][1] + best[0][3]) / 2 - yc) < max(best[0][3] - best[0][1], 10) * 1.5:
                    best.append(y)
        for row in rows:
            out.append(" ".join(x[4] for x in sorted(row, key=lambda x: x[0])))
    return out


def main(xml_path, out_path):
    pages, found = {}, {}
    for scan, W, H, lines in read_pages(xml_path):
        printed, body = split_header(W, H, lines)
        found[scan] = printed
        pages[scan] = rows_of(W, body)
        if scan > 700:
            break
    printed_of, _ = fix_page_numbers(found)
    rows, failed, last_event = [], [], None
    for s in sorted(pages):
        p = printed_of.get(s)
        if p is None or not (FIRST <= p <= LAST):
            continue
        carry = None
        for line in pages[s]:
            if carry and re.match(rf"^\s*{MON}", line):
                line, carry = carry + " " + line, None
            r = parse_row(line, p)
            if r is None and DASH.search(line) and not re.search(r"18[56]\d", line):
                carry = line
                continue
            if r is None:
                if len(line) > 12 and not re.match(r"^[A-Z]$", line.strip()):
                    failed.append((p, line))
                continue
            if r["kind"] == "see":
                r["from_place"] = last_event["place"] if last_event else None
                r["from_state"] = last_event["state"] if last_event else None
            else:
                last_event = r
            rows.append(r)
    with open(out_path, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            r["id"] = f"idx{i:05d}"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    ev = [r for r in rows if r["kind"] == "event"]
    print(f"rows: {len(rows)}  events: {len(ev)}  cross-references: {len(rows) - len(ev)}  unparsed lines: {len(failed)}")
    print(f"  no state: {sum(1 for r in ev if not r['state'])}   no date: {sum(1 for r in ev if not r['date_start'])}")
    print("  types:", dict(Counter(r["type"] for r in ev).most_common(14)))
    print("  states:", dict(Counter(r["state"] for r in ev).most_common(12)))
    Path(out_path).with_suffix(".unparsed.txt").write_text("\n".join(f"p.{p}  {l}" for p, l in failed), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
