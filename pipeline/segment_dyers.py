"""Segment Part III (Regimental Histories) of Dyer's Compendium into one entry per unit.

Reads the Internet Archive word-position file (08697590_3359_djvu.xml), which keeps
every scanned page separate and records where each line sits. For each page it:
  * reads the printed page number from the running heading and drops the heading;
  * puts lines in reading order (full-width lines split the page into bands; within
    a band, the left column, then the right);
then it walks Part III, tracks the current state, finds unit headings, and writes
each unit's cleaned text with its printed page range.

Usage (from the project folder):
    python pipeline/segment_dyers.py 08697590_3359_djvu.xml data/dyers

Outputs in data/dyers/:
    units.jsonl          one JSON record per unit (id, state, heading, branch, number,
                         term, page_start, page_end, text, raw_text)
    units/<STATE>/...    the same entries as readable .txt files
    part3_clean.txt      the whole of Part III in reading order, with [p. N] markers
    segment_report.txt   counts, page-number repairs and entries worth a look
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

PART3_FIRST, PART3_LAST = 997, 1747          # printed pages
HEADER_BAND = 0.075                           # top 7.5% of the page holds the running heading

# Table of contents of Part III (state, first printed page), sorted by page.
STATES = [
    ("ALABAMA", 997), ("ARKANSAS", 997), ("CALIFORNIA", 1000), ("COLORADO", 1004),
    ("CONNECTICUT", 1006), ("DAKOTA TERRITORY", 1016), ("DELAWARE", 1016),
    ("DISTRICT OF COLUMBIA", 1018), ("FLORIDA", 1020), ("GEORGIA", 1020), ("ILLINOIS", 1021),
    ("INDIANA", 1103), ("IOWA", 1158), ("KANSAS", 1181), ("KENTUCKY", 1189), ("LOUISIANA", 1212),
    ("MAINE", 1215), ("MARYLAND", 1228), ("MASSACHUSETTS", 1237), ("MICHIGAN", 1269),
    ("MINNESOTA", 1293), ("MISSISSIPPI", None), ("MISSOURI", None), ("NEBRASKA", None),
    ("NEVADA", None), ("NEW HAMPSHIRE", None), ("NEW JERSEY", None), ("NEW MEXICO", None),
    ("NEW YORK", None), ("NORTH CAROLINA", None), ("OHIO", None), ("OREGON", None),
    ("PENNSYLVANIA", None), ("RHODE ISLAND", 1627), ("SOUTH CAROLINA", 1636),
    ("TENNESSEE", 1636), ("TEXAS", 1647), ("VERMONT", 1647), ("VIRGINIA", 1654),
    ("WASHINGTON TERRITORY", 1655), ("WEST VIRGINIA", 1655), ("WISCONSIN", 1666),
    ("U.S. REGULAR ARMY", 1689), ("U.S. VOLUNTEERS", 1716), ("U.S. VETERAN VOLUNTEERS", 1717),
    ("U.S. CORPS DE AFRIQUE", 1718), ("U.S. COLORED TROOPS", 1720), ("U.S. INDIANS", 1740),
    ("U.S. VETERAN RESERVE CORPS", 1741),
]
# State title lines as printed in Part III (letters only, upper case) -> state name
STATE_KEYS = {re.sub(r"[^A-Z]", "", s.replace("U.S.", "UNITED STATES")): s for s, _ in STATES}
STATE_KEYS.update({"DISTCOLUMBIA": "DISTRICT OF COLUMBIA", "WASHINGTON": "WASHINGTON TERRITORY",
                   "DAKOTA": "DAKOTA TERRITORY"})

UNIT_WORDS = re.compile(r"REGIMENT|REGT|BATTALION|BATTERY|BATTY|COMPANY|COMPANIES|SQUADRON|LEGION|"
                        r"CORPS|GUARD|MILITIA|ARTILLERY|CAVALRY|INFANTRY|ENGINEERS|SHARPSHOOT|"
                        r"RANGERS|SCOUTS|MOUNTED|DETACHMENT|BRIGADE|INDEPENDENT|ZOUAVES|HOME")
INLINE_HEADING = re.compile(r"^(\d+\w*\s+[A-Z][A-Za-z0-9 ,\"'()&.]+?)\s*[.,]?\s*[\u2014\u2013-]+\s*"
                            r"((?:Organized|Org\.|Formerly|Originally|Consolidated|Mustered|Designation).*)$")
RUNNING_HEAD = re.compile(r"REGIMENTAL\s+HISTORIES|COMP\w*\s+O\w\s+THE|REBELLION", re.I)


# ---------------------------------------------------------------- page reading
def read_pages(xml_path):
    """Yield (scan_index, width, height, [ (l, t, r, b, text) ... ]) for every scanned page."""
    i = -1
    for _, el in ET.iterparse(xml_path, events=("end",)):
        if el.tag != "OBJECT":
            continue
        i += 1
        W, H = int(el.get("width")), int(el.get("height"))
        lines = []
        for line in el.iter("LINE"):
            words = line.findall("WORD")
            if not words:
                continue
            boxes = [list(map(int, w.get("coords").split(",")[:4])) for w in words]  # l,b,r,t
            l = min(b[0] for b in boxes); r = max(b[2] for b in boxes)
            t = min(b[3] for b in boxes); b_ = max(b[1] for b in boxes)
            text = " ".join((w.text or "").strip() for w in words).strip()
            if text:
                lines.append((l, t, r, b_, text))
        yield i, W, H, lines
        el.clear()


def split_header(W, H, lines):
    """Separate running-heading lines from body lines; return (printed_page or None, body)."""
    page, body = None, []
    for ln in lines:
        l, t, r, b, text = ln
        if t < H * HEADER_BAND:
            m = re.fullmatch(r"\s*(\d{3,4})\s*", text.replace(" ", ""))
            if m:
                page = int(m.group(1))
            elif re.search(r"\b(\d{3,4})\b", text) and RUNNING_HEAD.search(text):
                page = int(re.search(r"\b(\d{3,4})\b", text).group(1))
            continue
        body.append(ln)
    return page, body


def reading_order(W, lines):
    """Full-width lines split the page into bands; read each band left column, then right."""
    mid = W / 2
    spanning = sorted([ln for ln in lines if ln[0] < mid - 60 and ln[2] > mid + 60], key=lambda x: x[1])
    cols = [ln for ln in lines if not (ln[0] < mid - 60 and ln[2] > mid + 60)]
    cuts = [s[1] for s in spanning] + [10 ** 9]
    out, prev = [], -1
    for k, cut in enumerate(cuts):
        band = [ln for ln in cols if prev <= ln[1] < cut]
        left = sorted([ln for ln in band if (ln[0] + ln[2]) / 2 < mid], key=lambda x: x[1])
        right = sorted([ln for ln in band if (ln[0] + ln[2]) / 2 >= mid], key=lambda x: x[1])
        out += [ln[4] for ln in left] + [ln[4] for ln in right]
        if k < len(spanning):
            out.append(spanning[k][4])
        prev = cut
    return out


def fix_page_numbers(found):
    """found: {scan: printed or None}. Keep numbers consistent with their neighbours' offset;
    fill the rest from the nearest trusted offset. Returns ({scan: printed}, repairs)."""
    scans = sorted(found)
    offsets = {s: s - p for s, p in found.items() if p}
    trusted = {}
    for s in scans:
        if s not in offsets:
            continue
        near = [offsets[x] for x in range(s - 6, s + 7) if x != s and x in offsets]
        if near and Counter(near).most_common(1)[0][0] == offsets[s]:
            trusted[s] = offsets[s]
    result, repairs, last = {}, 0, None
    for s in scans:
        if s in trusted:
            last = trusted[s]
        if last is None:
            nxt = next((trusted[x] for x in scans if x > s and x in trusted), None)
            last_used = nxt
        else:
            last_used = last
        if last_used is None:
            continue
        result[s] = s - last_used
        if found.get(s) != result[s]:
            repairs += 1
    return result, repairs


# ---------------------------------------------------------------- text cleaning
def fix_ocr(text):
    def year(m):
        return m.group(0).translate(str.maketrans("SGOIlo", "860110"))
    text = re.sub(r"\b1[8S][6G][0-9SGOIlo]\b", year, text)                    # 1S64, 18G5
    text = re.sub(r"\b[il](\d)\b", r"1\1", text)                              # i5 -> 15
    text = re.sub(r"(?<=\d-)S\b", "8", text)                                  # 7-S -> 7-8
    text = re.sub(r"(?<=[A-Za-z], )111\.", "Ill.", text)                      # Springfield, 111.
    text = re.sub(r"\bD\. [CO],", "D. C.,", text)                             # D. C, -> D. C.,
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def join_lines(lines):
    """Join OCR lines into running text, rejoining words split at line ends."""
    out = ""
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln:
            continue
        if out.endswith("-") and re.search(r"[a-z]-$", out) and re.match(r"[a-z]", ln):
            out = out[:-1] + ln                    # Rich- mond -> Richmond
        elif out:
            out += " " + ln
        else:
            out = ln
    return out


# ---------------------------------------------------------------- headings
def caps_ratio(text):
    t = re.sub(r"(\d+)\s*(st|nd|rd|th|d)\b", r"\1", text)      # 24th -> 24
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 4:
        return 0.0
    return sum(c.isupper() for c in letters) / len(letters)


def is_heading_start(text):
    if caps_ratio(text) < 0.85 or len(text) > 90:
        return False
    if re.match(r"\s*SERVICE", text):
        return False
    return bool(UNIT_WORDS.search(text.upper()))


def is_heading_continuation(prev, text):
    if caps_ratio(text) < 0.85 or len(text) > 90 or re.match(r"\s*(Organized|Org\.|SERVICE)", text):
        return False
    unbalanced = prev.count("(") > prev.count(")") or prev.count('"') % 2 == 1
    return prev.rstrip().endswith("-") or unbalanced or not prev.rstrip().endswith(".")


def state_title(text):
    key = re.sub(r"[^A-Z]", "", text.upper())
    key = re.sub(r"(VOLUNTEERS|TROOPS)$", "", key) if key not in STATE_KEYS else key
    if caps_ratio(text) < 0.9 or len(text) > 50:
        return None
    return STATE_KEYS.get(key)


def parse_heading(h):
    H = h.upper()
    num = re.match(r"\s*(\d+)", h)
    branch = next((b for k, b in [("HEAVY ARTILLERY", "heavy artillery"), ("LIGHT ARTILLERY", "light artillery"),
                                  ("ARTILLERY", "artillery"), ("BATTERY", "light artillery"),
                                  ("CAVALRY", "cavalry"), ("MOUNTED", "cavalry"), ("ENGINEER", "engineers"),
                                  ("SHARPSHOOT", "sharpshooters"), ("INFANTRY", "infantry"), ("ZOUAVE", "infantry")]
                   if k in H), None)
    kind = next((k.lower() for k in ["REGIMENT", "BATTALION", "BATTERY", "COMPANY", "SQUADRON", "LEGION"] if k in H), None)
    term = None
    m = re.search(r"\(\s*(\d+|ONE|THREE|SIX|NINE)\s+(MONTHS|YEARS|DAYS)\s*\.?\)", H)
    if m:
        term = f"{m.group(1).lower()} {m.group(2).lower()}"
    elif "REORGANIZED" in H:
        term = "reorganized"
    return {"number": int(num.group(1)) if num else None, "branch": branch, "kind": kind, "term": term}


def ocr_quality(text):
    """Share of tokens that look like clean words or numbers (1.0 = clean)."""
    toks = text.split()
    if not toks:
        return 1.0
    ok = sum(bool(re.fullmatch(r"[\"(]?([A-Z]?[a-z]+('s)?|[A-Z]{1,4}|[A-Z][a-z]*\.|\d+(st|nd|rd|th|d)?|\d+-\d+|[A-Z]\.)[)\",.;:]*", t))
             for t in toks)
    return round(ok / len(toks), 3)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60]


# ---------------------------------------------------------------- main
def main(xml_path, out_dir):
    out = Path(out_dir)
    (out / "units").mkdir(parents=True, exist_ok=True)

    pages, found = {}, {}
    for scan, W, H, lines in read_pages(xml_path):
        printed, body = split_header(W, H, lines)
        found[scan] = printed
        pages[scan] = reading_order(W, body)
    printed_of, repairs = fix_page_numbers(found)

    part3 = [(printed_of[s], pages[s]) for s in sorted(pages)
             if s in printed_of and PART3_FIRST <= printed_of[s] <= PART3_LAST]

    # Walk Part III line by line.
    toc = sorted([(p, s) for s, p in STATES if p], key=lambda x: x[0])
    units, cur, state = [], None, "ALABAMA"
    state_switches, clean_dump = [], []
    pending_heading = None
    for page, lines in part3:
        clean_dump.append(f"\n[p. {page}]\n")
        for raw in lines:
            text = raw.strip()
            clean_dump.append(text)
            if RUNNING_HEAD.fullmatch(text.strip(". ")):
                continue
            st = state_title(text)
            if st and st != state:
                state = st
                state_switches.append((page, st))
                continue
            if pending_heading is not None and is_heading_continuation(pending_heading["heading"], text):
                h = pending_heading["heading"].rstrip()
                pending_heading["heading"] = (h[:-1] + text) if h.endswith("-") else (h + " " + text)
                continue
            pending_heading = None
            m = INLINE_HEADING.match(text)
            if m and is_heading_start(m.group(1)):
                cur = {"state": state, "heading": m.group(1), "page_start": page, "page_end": page,
                       "lines": [m.group(2)]}
                units.append(cur)
                continue
            if is_heading_start(text):
                cur = {"state": state, "heading": text, "page_start": page, "page_end": page, "lines": []}
                units.append(cur)
                pending_heading = cur
                continue
            if cur is not None:
                cur["lines"].append(text)
                cur["page_end"] = page

    # Finish records.
    seq = Counter()
    with open(out / "units.jsonl", "w", encoding="utf-8") as f:
        for u in units:
            raw_text = join_lines(u.pop("lines"))
            u["heading"] = fix_ocr(re.sub(r"\s+", " ", u["heading"]))
            u["raw_text"] = raw_text
            u["text"] = fix_ocr(raw_text)
            u.update(parse_heading(u["heading"]))
            u["ocr_quality"] = ocr_quality(u["text"])
            seq[u["state"]] += 1
            u["id"] = f"{slug(u['state'])}/{seq[u['state']]:03d}_{slug(u['heading'])}"
            f.write(json.dumps(u, ensure_ascii=False) + "\n")
            p = out / "units" / f"{u['id']}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"{u['heading']}\n{u['state']}, Dyer's Compendium pp. {u['page_start']}"
                         f"{'-' + str(u['page_end']) if u['page_end'] != u['page_start'] else ''}\n\n{u['text']}\n",
                         encoding="utf-8")
    (out / "part3_clean.txt").write_text("\n".join(clean_dump), encoding="utf-8")

    # Report.
    by_state = Counter(u["state"] for u in units)
    short = [u for u in units if len(u["text"]) < 60]
    long_ = [u for u in units if len(u["text"]) > 12000]
    no_branch = [u for u in units if not u["branch"]]
    rep = [f"Pages read: {len(pages)} scans; Part III pages {PART3_FIRST}-{PART3_LAST}: {len(part3)} found",
           f"Page numbers repaired or filled from neighbours: {repairs}",
           f"Units found: {len(units)}", "", "Units by state:"]
    rep += [f"  {s:<28} {by_state.get(s, 0)}" for s, _ in STATES]
    rep += ["", "State switches (page, state):"] + [f"  {p}  {s}" for p, s in state_switches]
    rep += ["", f"Very short entries ({len(short)}), possibly split headings:"]
    rep += [f"  {u['id']}  ->  {u['text'][:80]!r}" for u in short[:80]]
    rep += ["", f"Very long entries ({len(long_)}), possibly missed headings:"]
    rep += [f"  {u['id']}  {len(u['text'])} chars" for u in long_]
    poor = sorted([u for u in units if u["ocr_quality"] < 0.85 and len(u["text"]) > 200], key=lambda u: u["ocr_quality"])
    rep += ["", f"Poor OCR ({len(poor)}): check against the PDF"]
    rep += [f"  {u['ocr_quality']:.2f}  {u['id']}  pp. {u['page_start']}-{u['page_end']}" for u in poor]
    rep += ["", f"Headings with no recognized branch ({len(no_branch)}):"]
    rep += [f"  {u['id']}" for u in no_branch[:80]]
    (out / "segment_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:3]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
