"""Rule-based claim extraction from Dyer's Compendium unit entries (no AI).

Each entry has a fixed shape:
    Organized at <place> ... <date>.  [Moved to / Left State for ...]
    Attached to <parent>, to <Month>, <Year>. <parent>, to <Month>, <Year>. ...
    SERVICE.— <item> <date>. <item> <date>. ...
    Regiment lost during service ... Total N.

The extractor turns those parts into claims shaped like the database schema
(unit_at, participated, subordinate_to, unit_numbers, known_as, succeeded_by).
It resolves nothing: places, events and parents stay as text mentions.
Anything it cannot read confidently gets low confidence and a note, so the
AI step and the review queue know where to look.

Usage:
    python pipeline/extract_dyers.py data/dyers/units.jsonl data/dyers/claims_rules.jsonl
"""
import json
from datetime import date
import re
import sys
from collections import Counter

MONTHS = {"jan": 1, "jany": 1, "january": 1, "feb": 2, "feby": 2, "february": 2, "mar": 3, "march": 3,
          "apr": 4, "april": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "aug": 8, "august": 8,
          "sept": 9, "sep": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
          "dec": 12, "december": 12}
MON = r"(?:Jany|January|Jan|Feby|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|August|Aug|" \
      r"September|Sept|Sep|October|Oct|November|Nov|December|Dec)\b\.?"
YEAR = r"18[56]\d"
POINT = rf"{MON}\s+\d{{1,2}}(?:[,.]?\s+{YEAR})?"
DATE_RE = re.compile(
    rf"(?P<date>(?<=till ){MON}(?:,?\s+{YEAR})?(?!\s*\d)"                      # till April / till April, 1863
    rf"|{POINT}(?:,?\s*(?:-|to)\s*(?:{MON}\s+)?\d{{1,2}}(?:[,.]?\s+{YEAR})?)?"   # May 5-7 / Oct 20-Nov 6 / ... to ...
    rf"|{MON}\s+(?:to|-)\s+{MON},?\s+{YEAR}"                                  # January to April, 1865
    rf"|{MON},?\s+{YEAR})")                                                     # December, 1862
ABBREV_END = re.compile(r"\b(?:[A-Z][a-z]?|Co|Cos|Ft|Mt|St|Gen|Col|Capt|Lieut|Maj|Dept|Dist|Div|Regt|Infy|"
                        r"Cav|Arty|Batty|Indpt|Vols|Va|Md|Ky|Mo|Ga|Ala|Tenn|Miss|Ark|Tex|La|Pa|Mich|Ill|"
                        r"Ind|Wis|Minn|Kan|Neb|Fla|Cal|Ohio|N|S|C|D|T|I)\.$")
UNIT_LOST = re.compile(r"(?:Regiment|Battery|Company|Battalion|Squadron|Detachment|Corps|Legion)\s+lost\s+during\s+service",
                       re.I)

MOVE_WORDS = ("moved to", "move to", "ordered to", "march to", "marched to", "movement to", "return to", "returned to",
              "sent to", "proceeded to", "embarked for", "to ", "thence to", "and to", "advance to", "retreat to")
DEPART_WORDS = ("left state for", "left for", "started for", "left ")   # 'Left Boston on Steamer "De Molay" for Hilton Head'

DUTY_WORDS = ("assigned to", "duty at", "duty in", "duty on", "duty near", "duty along", "at ", "garrison", "provost", "guard ",
              "camp at", "camp near", "in camp", "post duty", "on line of", "picket", "railroad guard",
              "garrison duty", "occupation of", "winter quarters", "stationed")
PORTION_RE = [(re.compile(r"\bnon-?veterans?\b", re.I), "non_veterans"),
              (re.compile(r"\bveterans on furlough\b", re.I), "veterans"),
              (re.compile(r"\bdetachments?\b", re.I), "detachment"),
              (re.compile(r"\bCos?\.\s*\"?[A-M]\"?", re.I), "companies"),
              # 'Companies "B" and "G" moved to Fort Ridgly' / 'Company "A" moved to Fort Ripley' (1st Minnesota's
              # frontier forts were filed as the whole regiment)
              (re.compile(r"\bCompan(?:y|ies)\s+\"?[A-M]\b", re.I), "companies"),
              (re.compile(r"^(?:one|two|three|four|five|six|seven|eight|nine|\d)\s+compan(?:y|ies)\b", re.I), "companies")]


# ------------------------------------------------------------------ dates
import os
USE_TILL = os.environ.get('DY_TILL', '0') == '1'
TILL_YEAR = os.environ.get('DY_TILL_YEAR', '0') == '1'   # tested 2026-11-14: 18 units worse, 5 better
USE_PAREN = os.environ.get('DY_PAREN', '1') == '1'   # 'till' context (off) made 66 more wrong years than it fixed


class YearTracker:
    """Dyer's lists service in order and often omits the year; carry it forward."""
    def __init__(self, year=None):
        self.year, self.month, self.rolled = year, None, False
        self.mark_till, self.till_ctx = False, None
        self.is_till = False     # the date being read ends a 'till' stay: it lies after the running date
        self.floor = None        # (year, month) of muster-in: nothing in the service list is before it
        self.last_item = None    # (year, month) where the previous item of the list ended
        self.misprints = 0

    def resolve(self, month, year, is_start=True):
        if is_start:
            self.rolled = False
        # After 'duty guarding Upper Potomac till February, 1862.' the next undated item ('Operations about
        # Ball's Bluff October 11-23') is often inside the duty period, not after its end. Take the reading
        # inside the period when it fits there, else the one after the 'till' date.
        if is_start and self.till_ctx and not year and not self.mark_till:
            py, pm, ty, tm = self.till_ctx
            self.till_ctx = None
            inside = py if month >= pm else py + 1
            if (py, pm) <= (inside, month) <= (ty, tm):
                self.year = inside
            else:
                self.year = ty if month >= tm else ty + 1
            self.month = month
            return self.year
        if is_start and not self.mark_till:
            self.till_ctx = None
        pre = (self.year, self.month)
        if year and year < 1861:
            self.misprints += 1          # 'Mustered out July 1, 1860' (188th New York)
            year = None
        if year:
            self.year = year
        elif self.year and self.month and month < self.month:
            if not is_start:
                self.year += 1                   # a range that wraps the year: December 26 to January 5
            elif self.is_till and self.month - month >= 5:
                # 'Battle of Fredericksburg, Va., December 12-15. At Falmouth till April 27.': a stay ends after it
                # began, so an earlier month is next year (only Dec -> Jan-Mar rolled before; the 72nd New York's
                # 1863 stayed in 1862 and its review card offered no right answer). Only a long way back: a till date a
                # few months back is a stay inside the item before ('Red River Campaign March 23-May 22. At Alexandria
                # till April 12'); tested 2026-11-14 with 5 months
                self.year += 1
            else:
                if self.month >= 10 and month <= 3:
                    self.year += 1               # Dec ... Jan with no year written
                self.rolled = True               # either a year-end or an out-of-order date: flag it
        self.month = month                       # range ends count too ('December 14, 1862, to January 19, 1863')
        if self.mark_till and is_start:
            self.mark_till = False
            if pre[0] and pre[1] and (pre[0], pre[1]) <= (self.year, self.month):
                self.till_ctx = (pre[0], pre[1], self.year, self.month)
        return self.year


def parse_point(s):
    m = re.match(rf"({MON})\s*(\d{{1,2}})?(?:[,.]?\s+({YEAR}))?", s.strip())
    if not m:
        return None
    return MONTHS[m.group(1).rstrip(".").lower()], (int(m.group(2)) if m.group(2) else None), \
        (int(m.group(3)) if m.group(3) else None)


def parse_date(expr, years):
    """Return (start, end, precision) as ISO strings from a Dyer's date expression."""
    parts = re.split(r",?\s*(?:-|\bto\b)\s*", expr.strip(), maxsplit=1)
    pt = parse_point(parts[0])
    if not pt:
        return None
    m1, d1, y1 = pt
    m2 = d2 = y2 = None
    if len(parts) == 2:
        p2 = parts[1].strip()
        if re.match(r"\d", p2):                                   # May 5-7(, 1864)
            dm = re.match(rf"(\d{{1,2}})(?:[,.]?\s+({YEAR}))?", p2)
            m2, d2, y2 = m1, int(dm.group(1)), (int(dm.group(2)) if dm.group(2) else None)
        else:
            pt = parse_point(p2)
            if pt:
                m2, d2, y2 = pt
    # A year written only at the end of a range applies to the start too, unless months wrap.
    y_first = y1 or (y2 if (y2 and (m2 is None or m1 <= m2)) else None)
    y1r = years.resolve(m1, y_first)
    if y1r is None:
        return None
    start = f"{y1r}-{m1:02d}-{d1:02d}" if d1 else f"{y1r}-{m1:02d}"
    prec = "day" if d1 else "month"
    if m2:
        rolled = years.rolled
        y2r = years.resolve(m2, y2, is_start=False)
        years.rolled = rolled
        end = f"{y2r}-{m2:02d}-{d2:02d}" if d2 else f"{y2r}-{m2:02d}"
    else:
        end = start
    return start, end, prec


# ------------------------------------------------------------------ text helpers
# 'Moved to Folly Island, S. C. Expedition to James Island': a period closing a state name is also a sentence end when
# an item of the service list starts next ('Kingston, Ga. March to the sea' was read as one place)
STATE_END = re.compile(r"(?:\b(?:Va|Md|Ky|Mo|Ga|Ala|Tenn|Miss|Ark|Tex|La|Pa|Mich|Ill|Ind|Wis|Minn|Kan|Neb|Fla|Cal|Mass|"
                       r"Conn|Del|Colo|Ariz|Ter)|\b[DSN]\. ?C)\.$")
ITEM_START = re.compile(r"(?:Duty|March|Moved?|Movement|Ordered|Expeditions?|Battles?|Siege|Skirmish(?:es)?|Actions?|"
                        r"Engagements?|Occupation|Pursuit|Advance|Operations?|Garrison|Guard(?:ing)?|Scout(?:ing)?|Raid|"
                        r"Reconn?oissances?|Attack|Assault|Capture|Surrender|Mustered|Provost|Camp|Stationed|Refitting|"
                        r"Defen[cs]es?|Assigned|Attached|Relieved|Detached|Returned?|Retreat|Sent|Proceeded|Embarked|"
                        r"Regiment|Headquarters|Picket|Rejoined|Joined|Operating|Left|Veterans|Non-veterans)\b")


def split_sentences(s):
    """Split on '. ' followed by a capital, unless the period closes an abbreviation."""
    out, buf = [], ""
    for piece in re.split(r"(?<=\.)\s+(?=[A-Z(\"])", s):
        if buf and STATE_END.search(buf) and ITEM_START.match(piece):
            out.append(buf)
            buf = ""
        buf = f"{buf} {piece}".strip() if buf else piece
        if not ABBREV_END.search(buf):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def clean_desc(s):
    s = re.sub(r"^[\s.,;:)]+|[\s.,;:]+$", "", s)          # ')' left over from a closed aside
    s = re.sub(r"^(?:and|then|thence|also)\s+", "", s, flags=re.I)
    return s.strip()


def portion_of(text):
    for rx, name in PORTION_RE:
        if rx.search(text):
            return name
    return "whole"


PORTION_LEAD = re.compile(r'^(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:companies|cos\.?)|'
                          r'cos?\.\s*(?:"[a-z]"[,\s]*(?:and\s*)?)+|detachments?|battalion|non-veterans|veterans|'
                          r'regiment|recruits|old members|left wing|right wing)\s+', re.I)
ADMIN = re.compile(r'^(?:(?:discharged|connect(?:ed)? with|join(?:ed)?|rejoined|re-?enlisted|regiment|companies|'
                   r'on furlough|furlough)\b|\d[\d ,and]*$)', re.I)


ACTION_WORDS = re.compile(r"\b(?:actions?|battles?|skirmish(?:es)?|engagements?|siege|assaults?|affairs?|"
                          r"expeditions?|raids?|campaign|scouts?|attack|repulse|capture|defence|defense)\b", re.I)


def classify(desc):
    d = desc.lower()
    d = re.sub(r"^(?:and|then|thence)\s+", "", d)
    d = PORTION_LEAD.sub("", d)                  # 'Eight Companies moved to Hilton Head' -> 'moved to Hilton Head'
    if ADMIN.match(d.strip()):
        return "unit_at", "present"
    if re.match(r"(?:duty|guarding|guarded|garrisoning|picketing|patrolling)\b", d):
        return "unit_at", "present"
    if re.match(r"(?:on\s+)?(?:the\s+)?line\s+of\s+the\s+(?!.*railroad)", d):   # 'On line of the Pamunkey May 26-28'
        return "participated", None
    if re.match(r"march to the sea|campaign|siege|battle", d):
        return "participated", None
    if d.startswith(DEPART_WORDS):
        return "unit_at", "departed"
    if d.startswith(("organized at", "org. at", "mustered in", "mustered out", "reorganized")):
        return "unit_at", "present"
    if d.startswith(DUTY_WORDS):
        return "unit_at", "present"
    if d.startswith(MOVE_WORDS) or re.match(r"(?:moved|ordered|marched) (?:by|via|through)", d):
        return "unit_at", "en_route"
    return "participated", None


def move_legs(place):
    """'Memphis, thence march to Chattanooga, Tenn' -> ['Memphis', 'Chattanooga, Tenn'];
    'Washington, D. C., via Richmond, Va' -> ['Richmond, Va', 'Washington, D. C.'] (places passed through come first);
    'Jefferson City, Mo., and to Warsaw, Mo' -> ['Jefferson City, Mo.', 'Warsaw, Mo']."""
    main, via = (re.split(r",?\s+via\.?\s*", place, maxsplit=1) + [""])[:2]
    legs = [x.strip(" ,.") for x in re.split(r",?\s*(?:and\s+)?thence\s+(?:(?:by\s+\w+|march|marched|moved|move|"
                                             r"movement|returned|ordered|proceeded|embarked)\s+)?(?:to|for)?\s*|"
                                             r",?\s+and\s+to\s+", main)]
    legs = [x for x in legs if len(x) > 1]
    vias = [x.strip(" ,.") for x in re.split(r",?\s+and\s+", via)] if via else []
    vias = [v for v in vias if len(v) > 1 and not re.match(
        r"(?i)(the\s+)?(\w+\s+)?(river|bayou|railroad|r\.\s*r)\b|(rail(road)?|steamer|transports?|water|sea|land|canal)\b", v)]
    if not legs:
        return [place]
    return legs[:-1] + vias + legs[-1:]


# 'Lookout Mountain building hospitals, running mills, etc.' / 'Memphis, Tenn., arriving there' / 'Fort Delaware during
# entire service': what the unit did there is not part of the place
PLACE_TAIL = re.compile(r",?\s+(?:engaged|employed|under orders|for (?:special |provost |garrison )?duty|for muster|"
                        r"[a-z]{3,}ing)\b.*$")


def place_from(desc):
    d = clean_desc(desc)
    mj = re.search(r"\b(?:re)?join(?:ed)?\b[^.;]*?\bat\s+([A-Z].+)$", d)    # '..., and joined Brigade at Cold Harbor, Va'
    m = re.search(r"\b(?:to|for|at|in|near|on line of|along|of)\s+(.+)$", d)
    p = mj.group(1) if mj else (m.group(1) if m else d)
    mj = re.match(r"(?:join(?:ed)?|report(?:ed)?)\b.*?\bat\s+(.+)$", p, re.I)    # 'to join 14th Army Corps at Kingston, Ga'
    if mj:
        p = mj.group(1)
    p = re.sub(r"\s+(?:till|until)$", "", p)
    p = PLACE_TAIL.sub("", p)
    p = re.sub(r"[,\s]+(?:and|or)$", "", p)
    return p.strip(" ,.")


# ------------------------------------------------------------------ sections
def split_sections(text):
    lost = UNIT_LOST.search(text)
    losses = text[lost.start():] if lost else ""
    body = text[:lost.start()] if lost else text
    svc = re.search(r"SERVICE\.?\s*[—–-]+\s*", body)
    head, service = (body[:svc.start()], body[svc.end():]) if svc else (body, "")
    att = re.search(r"\bAt-?\s*tached\s+to\b|\bAttached\s+to\b|\bServed\s+(?:Unattached|unattached)", head)
    pre, attach = (head[:att.start()], head[att.start():]) if att else (head, "")
    return pre, attach, service, losses


def _shift(a, n):
    from datetime import timedelta
    return (date.fromisoformat(a) + timedelta(days=n)).isoformat()


def _gap_days(a, b):
    """Days from the end a to the start b (ISO day or month strings); 0 when unknown."""
    try:
        da = date.fromisoformat(a if len(a) == 10 else a + "-28")
        db = date.fromisoformat(b if len(b) == 10 else b + "-01")
        return (db - da).days
    except (TypeError, ValueError):
        return 0


def items_from(text, years, base_conf=0.8):
    """Cut dated items out of running text. Undated sentences become low-confidence items."""
    items, pos, saved = [], 0, None
    for m in DATE_RE.finditer(text):
        desc_all = text[pos:m.start()]
        expr = m.group("date")
        pos = m.end()
        till = bool(re.search(r"\btill\s*$", desc_all))
        sentences = split_sentences(desc_all.strip())
        for s in sentences[:-1]:                    # undated sentences before this item
            s = clean_desc(s)
            if s and not s.startswith("("):
                items.append({"desc": s, "date": None, "conf": 0.3})
        last = clean_desc(sentences[-1]) if sentences else ""
        last = re.sub(r"\s+till$", "", last)
        # a leading parenthesis belongs to the previous item: '(Detachment). Near Pulaski'
        paren = re.match(r"^(\([^)]*\))[\s.,;]*(.*)$", last)
        if paren and items:
            items[-1]["note"] = ((items[-1].get("note") or "") + " " + paren.group(1)).strip()
            last = paren.group(2)
        # trailing portion markers that belong to the previous item: 'Detachment.) Near Pulaski'
        pm = re.match(r"^\(?((?:Detachment|Co\.|Cos\.|non-veterans|Non-veterans)[^)]*)\)\.?\)?\s*(.*)$", last)
        if pm and items:
            items[-1]["note"] = ((items[-1].get("note") or "") + " (" + pm.group(1) + ")").strip()
            last = clean_desc(pm.group(2))
        # a dated aside in parentheses ('(Cos. "B" and "F" at Morris Island till February, 1865.)') must not
        # move the running year for the text after it: save the tracker on entering, restore on leaving
        depth = text[:m.start()].count("(") - text[:m.start()].count(")")
        if not USE_PAREN:
            pass
        elif depth > 0 and saved is None:
            saved = (years.year, years.month)
        elif depth <= 0 and saved is not None:
            years.year, years.month = saved
            saved = None
        # 'duty guarding Upper Potomac till February, 1862. Operations about Ball's Bluff October 11-23': a till date
        # with its year printed spans months, and the next item inside that span belongs to its first year (1st
        # Minnesota's Ball's Bluff was dated 1862, and a year error ran on to Fredericksburg). Unprinted till years
        # stay off (DY_TILL: that version made more wrong years than it fixed).
        years.is_till = till
        years.mark_till = till and (USE_TILL or (TILL_YEAR and bool(re.search(YEAR, expr))))
        parsed = parse_date(expr, years)
        years.mark_till = False
        years.is_till = False
        if parsed and len(parsed[1]) >= 7:
            years.last_item = (int(parsed[1][:4]), int(parsed[1][5:7]))
        if last.lower() in ("and", "") and items and parsed and items[-1].get("date") and \
                _gap_days(items[-1]["date"][1], parsed[0]) > 3:
            # 'Malvern Hill July 1 and August 5': two actions at one place, not a five-week battle
            items.append({**items[-1], "date": parsed, "date_text": expr})
            continue
        if last.lower() in ("and", "") and items and parsed and items[-1].get("date"):
            d0, _, prec = items[-1]["date"]           # 'December 30-31, 1862, and January 1-3, 1863'
            items[-1]["date"] = (d0, parsed[1], prec)
            items[-1]["date_text"] += " and " + expr
            continue
        if not last:
            continue
        if last.startswith("("):                       # unclosed parenthesis: '(Pittinger's Raid ...'
            last = last.lstrip("(").strip()
        if re.match(r"^(?:on|to|at|of|against)\s", last) and items:
            vm = re.match(r"^(.*?)\s(?:on|to|at|of|against)\s", items[-1]["desc"])
            if vm:
                last = vm.group(1) + " " + last     # 'Advance on Bowling Green ...; on Nashville'
        conf = base_conf - (0.3 if years.rolled else 0)
        items.append({"desc": last, "date": parsed, "till": till, "conf": conf, "date_text": expr,
                      "note": "Date out of order or year inferred; check" if years.rolled else None})
    tail = text[pos:]
    for s in split_sentences(tail.strip()):
        s = clean_desc(s)
        paren = re.match(r"^(\([^)]*\))[\s.,;]*(.*)$", s)
        if paren and items:
            items[-1]["note"] = ((items[-1].get("note") or "") + " " + paren.group(1)).strip()
            s = paren.group(2)
        if s:
            items.append({"desc": s, "date": None, "conf": 0.3})
    return items


def parse_attachments(attach, years, start_iso):
    """'Attached to A, to October, 1862. B, to November, 1862.' -> chain with start = previous end."""
    text = re.sub(r"^(?:At-?\s*tached\s+to|Attached\s+to)\s+", "", attach.strip())
    out, prev_end = [], start_iso
    rx = re.compile(rf"(?P<parent>.+?),?\s+to\s+(?P<m>{MON}),?\s*(?P<y>{YEAR})?\s*(?:\.|$)", re.S)
    pos = 0
    for m in rx.finditer(text):
        parent = clean_desc(m.group("parent"))
        mon = MONTHS[m.group("m").rstrip(".").lower()]
        yr = years.resolve(mon, int(m.group("y")) if m.group("y") else None)
        end = f"{yr}-{mon:02d}" if yr else None
        if parent:
            out.append({"parent": parent, "date_start": prev_end, "date_end": end,
                        "span": m.group(0).strip()})
        prev_end, pos = end, m.end()
    leftover = clean_desc(text[pos:])
    return out, leftover


def parse_losses(losses):
    if not losses:
        return None
    s = re.sub(r"\s+", " ", losses)
    def count(part):
        return sum(int(n) for n in re.findall(r"(\d+)\s+(?:Officers?|Enlisted\s+m[ae]n)", part or ""))
    k = re.search(r"lost during service(.*?)killed and mortally wounded", s, re.I)
    rest = s[k.end():] if k else s[re.search(r"lost during service", s, re.I).end():]
    d = re.search(r"^(.*?)by disease", rest, re.I)
    t = re.search(r"Total,?\s*(\d+)", s)
    rec = {"killed": count(k.group(1)) if k else None,
           "died_disease": count(d.group(1)) if d else None,
           "casualties_total": int(t.group(1)) if t else None}
    if not any(v is not None for v in rec.values()):
        return None
    return rec


def fix_order(claims):
    """An end before the start: the stated end is the reliable part. Items listed out of order ('Company "F" at
    Fort Bunker Hill November 17, 1862' after 1864 items) or a brigade chain step out of order inherit a start
    from the previous item; drop that start. A truncated same-month range ('May 25-3') ends at its start."""
    for c in claims:
        a, b = c.get("date_start"), c.get("date_end")
        if not (a and b) or b >= a:
            continue
        if a[:7] == b[:7] and len(b) == 10:
            c["date_end"] = a
            c["note"] = ((c.get("note") or "") + " end day truncated in source; set to start").strip()
        elif c["claim_type"] == "participated":       # keep it dated (clustering needs a start): the stated end
            c["date_start"] = b
            c["confidence"] = round(max(0.1, c["confidence"] - 0.1), 2)
            c["note"] = ((c.get("note") or "") + " start set to stated end: listed out of order in source").strip()
        else:
            c["date_start"] = None
            c["confidence"] = round(max(0.1, c["confidence"] - 0.1), 2)
            c["note"] = ((c.get("note") or "") + " start unknown: listed out of order in source").strip()
    return claims


# ------------------------------------------------------------------ main extraction
MONTH_DOT_YEAR = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\. (18[56]\d)\b")


def extract(unit):
    # 'Ordered to Dept. of the Gulf March. 1864': a comma OCR read as a period (131 times in Part III). Read as
    # 'March. 18' it gave the day 18 and lost the year, so a whole year of service stayed a year early (11th NY Cavalry).
    text = MONTH_DOT_YEAR.sub(r"\1, \2", unit["text"])
    pre, attach, service, losses = split_sections(text)
    years = YearTracker()
    claims = []

    def add(ctype, span, conf, **detail):
        claims.append({"unit_id": unit["id"], "claim_type": ctype, "source_span": span,
                       "page": unit["page_start"], "confidence": round(conf, 2), **detail})

    home = None        # the organization place (in the State a 'Left State for ...' leaves)
    last = None        # the last place named, for 'duty there' and 'Mustered out'
    last_d = None

    def add_unit_at(span, conf, place, presence, portion, d0, d1, prec, note, **extra):
        """'Left State for Louisville, Ky., September 12' says where the regiment was going, not where it was on
        that day: the destination is kept undated (it was not reached that day), and the day is placed at the
        regiment's last place before leaving (its organization place, for a first departure)."""
        nonlocal home, last, last_d
        # 'duty there', 'arriving there', 'Mustered out': no place of their own; they are at the last place named
        # (2,058 'there' and 2,160 'Mustered out' claims had no place). Lowercase-only text before the first place
        # ('The first Regiment tendered to the government') is not a place at all.
        if place and re.fullmatch(r"[\d\s,]*(?:and[\d\s,]*)*", place):
            return                  # '9 and 10': the tail of 'Actions on James Island July 2, 9 and 10'
        if not place or re.search(r"\bthere\b", place) or (not re.search(r"[A-Z]", place) or
                      re.fullmatch(r"(?i)(?:mustered (?:out|in)|discharged|reorganized|re-?enlisted)\b.*", place)):
            if not last or (d0 and last_d and _gap_days(last_d, d0) > 60):
                return              # nothing named lately ('Mustered out' a year after the last place named)
            note = ((note + "; ") if note else "") + f"no place named: at the last place, {last}"
            place = last
            conf *= 0.8
        if presence == "departed":
            n = (note + "; ") if note else ""
            bare = DATE_RE.sub("", span).strip(" ,.")
            mf = re.match(r"Left\s+(?!State\b|for\b)(.+?)(?:\s+(?:on|by|via|for)\b.*)?$", bare)
            src = mf.group(1).strip(" ,.") if mf else (home if re.search(r"\bstate for\b", span, re.I) else None)
            if src:
                add("unit_at", span, conf * 0.8, place_mention=src, presence="departed", portion=portion,
                    date_start=d0, date_end=d1, date_precision=prec,
                    note=n + (f"left {src}" if mf else f"left the State for {place}: placed at the last place before it ({home})"),
                    **extra)
            if re.search(r"\bfor\b", bare) and place and not (mf and place == bare):
                add("unit_at", span, conf * 0.8, place_mention=place, presence="en_route", portion=portion,
                    date_start=None, date_end=None, date_precision=None,
                    note=n + "destination of a departure; arrival date not stated", **extra)
                last = place
            elif src:
                last = src
            return
        add("unit_at", span, conf, place_mention=place, presence=presence, portion=portion,
            date_start=d0, date_end=d1, date_precision=prec, note=note, **extra)
        if place:
            last = place
            last_d = d1 or d0 or last_d
        if place and re.match(r"(?:Organized|Org\.)", span):
            home = place            # in the State it later left; later camps are not tracked

    # Cross-reference stubs: 'See 1st Regiment Heavy Artillery.'
    see = re.match(r"^\(?\s*See\s+(.+?)[.)]*\s*(?:for service)?\.?\)?$", text.strip(), re.I)
    if see:
        add("known_as", text.strip(), 0.6, name=unit["heading"], target_mention=see.group(1),
            note="Cross-reference: same unit under another designation, or a successor")
        return claims

    # Organization and moves before the attachment list
    org_date = None
    pre_end = None
    pre_home = False
    in_action = False
    for it in items_from(pre, years):
        kind, presence = classify(it["desc"])
        # entries with no SERVICE section put their actions here: 'Actions at Apache Canon March 26.
        # La Glorietta Pass, or Pigeon Ranch, March 28.'  An action word starts a run of actions; bare
        # place-and-date items after it stay actions until a movement, duty or organization line.
        if kind == "participated" and it["date"] and not re.match(r"(?:Organized|Org\.)", it["desc"], re.I) and (
                in_action or ACTION_WORDS.search(it["desc"])):
            in_action = True
            d0, d1, prec = it["date"]
            org_date = org_date or d0
            add("participated", f"{it['desc']} {it['date_text']}", it["conf"] - 0.1, event_mention=it["desc"],
                portion=portion_of(it["desc"] + " " + (it.get("note") or "")), date_start=d0, date_end=d1,
                date_precision=prec, note="Action in the text before the attachment list (no SERVICE section)")
            continue
        if kind == "unit_at":
            in_action = False
        if re.match(r"(?:Organized|Org\.)", it["desc"], re.I):
            kind, presence = "unit_at", "present"
            m = re.search(r"(?:Organized|Org\.)\s+(?:at|in)\s+(.+?)(?:,?\s+and\s+mustered|$)", it["desc"], re.I)
            place = m.group(1).strip(" ,.") if m else None
        else:
            place = place_from(it["desc"])
        if not it["date"]:
            if place and kind == "unit_at":
                add_unit_at(it["desc"], it["conf"], place, presence, portion_of(it["desc"]), None, None, None, None)
            continue
        d0, d1, prec = it["date"]
        org_date = org_date or d0
        pre_end = max(pre_end or d1, d1)
        pre_home = bool(re.match(r"(?i)(?:organized|org\.|mustered|left\b|\w+ companies left|reorganized)", it["desc"]))
        if presence == "en_route" and d0 == d1:
            presence = "arrived"
        add_unit_at(f"{it['desc']} {it['date_text']}", it["conf"], place, presence, portion_of(it["desc"]), d0, d1, prec, None)

    # Attachment chain
    if org_date and re.search(r"(?i)\bmustered in\b|\borganized\b", pre):
        years.floor = (int(org_date[:4]), int(org_date[5:7]))
    chain, leftover = parse_attachments(attach, years, org_date[:7] if org_date else None)
    years.last_item = (int(pre_end[:4]), int(pre_end[5:7])) if pre_end and len(pre_end) >= 7 else None
    for a in chain:
        add("subordinate_to", a["span"], 0.85, parent_mention=a["parent"], date_start=a["date_start"],
            date_end=a["date_end"], date_precision="month")
    if attach and not chain:
        add("subordinate_to", attach.strip(), 0.3, parent_mention=attach.strip(), date_start=None, date_end=None,
            note="Attachment text present but not parsed")

    # Service items
    last_event = None
    last_place = None
    # 'Moved to Washington, D. C., August 29' in the text before the attachments: the first 'Duty ... till October 1'
    # starts there, not at muster-in (the 24th Michigan was in Washington while still in Detroit)
    prev_end = pre_end or org_date
    for it in items_from(leftover + " " + service if leftover else service, years):
        desc = it["desc"]
        note = it.get("note")
        if re.match(r"Regiment selected|Designation changed|Consolidated with|Transferred to", desc, re.I) and not it["date"]:
            add("participated", desc, 0.3, event_mention=desc, portion="whole", date_start=None, date_end=None,
                note="Undated statement; may be a succession or a notable event")
            continue
        kind, presence = classify(desc)
        d0, d1, prec = it["date"] if it["date"] else (None, None, None)
        if it.get("till") and d0:          # 'Duty at X till October 1' -> from previous end to that date
            d0, d1 = prev_end or d0, d0
            if pre_home and d0 and len(d0) == 10:
                # the first stay after muster-in or 'Left State for ...': the journey took days ('Left State for
                # Washington March 22. Duty in the Defences of Washington till ...' was in Washington on March 22)
                d0 = min(_shift(d0, 5), d1) if len(d1 or "") == 10 else _shift(d0, 5)
                note = ((note + "; ") if note else "") + "start set 5 days after leaving home (arrival not stated)"
        if it["date"]:
            pre_home = False
        portion = portion_of(desc + " " + (note or ""))
        span = f"{desc} {it.get('date_text') or ''}".strip()
        if kind == "unit_at":
            place = re.split(r",?\s+and\s+(?:duty|thence|camp)\b", place_from(desc))[0]
            if place.lower().startswith("there") and last_place:
                place = last_place
            if presence == "en_route" and d0 and d0 == d1:
                presence = "arrived"
            legs = move_legs(place) if presence in ("en_route", "arrived") else [place]
            last_place = legs[-1]
            if len(legs) == 1:
                add_unit_at(span, it["conf"], place, presence, portion, d0, d1, prec, note)
            else:
                # a move in stages ("Movement to Memphis, thence march to Chattanooga, Tenn September 27-November 20";
                # "March to Washington via Richmond"): the last stage carries the move's dates (arrival at the end, as
                # before for a one-place move); the earlier stages are kept, undated, as the places passed through
                n = len(legs)
                last = legs[-1]
                for k, leg in enumerate(legs, 1):
                    if k == n:
                        add("unit_at", span, it["conf"], place_mention=leg, presence=presence, portion=portion,
                            date_start=d0, date_end=d1, date_precision=prec, note=note, leg=f"{k}/{n}")
                        continue
                    # earlier stages have no date of their own: the move's first date is when it left the place
                    # before ("At Clifton, Tenn., January 16. Movement to Washington, thence to Fort Fisher, January
                    # 16-February 9" reached Washington ten days later), and spreading the stages evenly over the dates
                    # put them weeks off ("to Memphis, thence march to Chattanooga" took days, then a month)
                    ds = None
                    add("unit_at", span, it["conf"] * 0.8, place_mention=leg, presence="arrived" if ds else "en_route",
                        portion=portion, date_start=ds, date_end=ds, date_precision=prec if ds else None,
                        note=((note + "; ") if note else "") + f"stage {k} of {n} of a move, no date of its own",
                        leg=f"{k}/{n}")
        else:
            parts = [p.strip() for p in re.split(r";\s*", desc) if p.strip()]
            add("participated", span, it["conf"], event_mention=parts[-1] if parts else desc, portion=portion,
                date_start=d0, date_end=d1, date_precision=prec, note=note)
            last_event = parts[-1] if parts else desc
        if d1:
            prev_end = d1
        # Losses stated inside a parenthesis after an event
        if note and re.search(r"\blost\b", note):
            n = {}
            for k, rx in [("casualties_total", r"(\d+)\s+killed,\s*wounded\s+and\s+missing"),
                          ("strength", r"out\s+of\s+(\d+)"), ("killed", r"(\d+)\s+killed(?!,)"),
                          ("wounded", r"(\d+)\s+wounded(?!\s+and\s+missing)"),
                          ("missing_captured", r"(\d+)\s+(?:missing|captured)")]:
                mm = re.search(rx, note)
                if mm:
                    n[k] = int(mm.group(1))
            if n:
                add("unit_numbers", note, 0.75, scope="event", event_mention=last_event, **n)

    # Whole-service losses
    rec = parse_losses(losses)
    if rec:
        add("unit_numbers", losses.strip(), 0.95, scope="whole_service", event_mention=None, **rec)
    return fix_order(claims)


def main(src, dst):
    stats, n_units = Counter(), 0
    low = Counter()
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as out:
        for line in f:
            u = json.loads(line)
            n_units += 1
            cl = extract(u)
            for c in cl:
                stats[c["claim_type"]] += 1
                if c["confidence"] < 0.5:
                    low[c["claim_type"]] += 1
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"units: {n_units}  claims: {sum(stats.values())}")
    for k, v in stats.most_common():
        print(f"  {k:<15} {v:>7}   low-confidence {low[k]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
