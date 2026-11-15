"""Second-pass unit matcher for names the regiment matcher misses.

Handles: U.S. Colored Troops, U.S. regulars (incl. "5th United States, Battery H" -> the artillery regiment),
Union batteries ("4th Indiana Battery" = independent battery; "1st Rhode Island Light, Battery E" -> the regiment,
battery noted), "10th Confederate", ranges "10th-19th South Carolina" (split by caller), and Confederate named units
by surname or nickname + state + class: "Carrington's Virginia Battery", "Letcher (Virginia) Artillery, Capt. Brander"
(nickname, or captain surname), "Phillips's (Georgia) Legion", "Byrd's (South Carolina) battalion".
match_named(name, side, section, commanders, idx) -> (unit_code or None, note or None)
"""
from cwv import states as cwv_states
import csv, re
from collections import defaultdict

STATES = cwv_states.table("Name", "CODE", "AL", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "IL", "IN", "IA", "KS",
                                          "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "NE", "NH", "NJ",
                                          "NY", "NC", "OH", "PA", "RI", "SC", "TN", "TX", "VT", "VA", "WV", "WI",
                                          "DC", "AZ")
ST_RE = "|".join(sorted(map(re.escape, STATES), key=len, reverse=True))
ORDN = r"(\d+)(?:st|d|nd|rd|th)"


def klass(text):
    t = text.lower()
    if "legion" in t: return "legion"
    if re.search(r"artillery|battery|howitzer|light\b", t): return "artillery"
    if re.search(r"cavalry|rangers|mounted", t): return "cavalry"
    if "battalion" in t: return "battalion"
    return "infantry"


def surname(s):
    m = re.search(r"([A-Z][A-Za-z\-]+)(?:['’]s|['’])(?=\W|$)", s)
    return m.group(1).lower() if m else None


class Index:
    def __init__(self, path):
        self.by = defaultdict(list)
        self.named = defaultdict(list)          # (side, state, key, class) -> units
        for u in csv.DictReader(open(path, encoding="utf-8")):
            side = "Union" if u["belligerent"] == "US" else "Confederate"
            try:
                o = int(u["ordinal"] or 0)
            except ValueError:
                o = 0
            self.by[(side, u["state"], o, u["type"], u["func"])].append(u)
            name = u["unit_name"]
            k = klass(name)
            sn = surname(name.split(",")[0])
            if sn:
                self.named[(side, u["state"], sn, k)].append(u)
            for nick in re.findall(r"\(([^)]*)\)", name):
                w = re.sub(r"\b(Artillery|Battery|Light|Rifles|Guards|Company|Legion|Rangers)\b", "", nick).strip().lower()
                w = re.sub(r"['’]s?$", "", w).strip()
                if w and not re.search(r"\d|months|regiment|battalion", w):
                    self.named[(side, u["state"], w, k)].append(u)
            m = re.match(r"^([A-Z][A-Za-z ]+?) (?:Artillery|Legion|Battery)\b", name)   # "Jeff Davis Artillery, Alabama"
            if m:
                self.named[(side, u["state"], m.group(1).lower(), k)].append(u)

    def one(self, cands, prefer=None):
        if prefer:
            p = [u for u in cands if prefer(u)]
            if len(p) == 1:
                return p[0]["unit_code"]
        cands = [u for u in cands if not u.get("special")] or cands
        return cands[0]["unit_code"] if len(cands) == 1 else None


def match_named(name, side, section, commanders, ix):
    n = re.sub(r"\s+", " ", name.replace("U. S.", "U.S.").replace("United States", "U.S.")).strip(" .,;*")
    n = re.sub(r"\s+-\s+(Cpt|Capt|Lt|Col|Maj)\b.*$", "", n)
    n = re.sub(r"\bRegiment\s+", "", n)
    # U.S. Colored Troops
    m = re.match(ORDN + r"\s+U\.?S\.? Colored(?: Troops)?(?: (Infantry|Cavalry|Heavy Artillery|Light Artillery))?", n)
    if m:
        func = {"Cavalry": "C", "Heavy Artillery": "A", "Light Artillery": "A"}.get(m.group(2) or "", "I")
        return ix.one(ix.by.get(("Union", "US", int(m.group(1)), "R", func), [])), None
    # U.S. regulars
    m = re.match(ORDN + r"\s+U\.?S\.?(?: Regulars?)?(?: (Infantry|Cavalry|Artillery))?(?:,? (?:Batter(?:y|ies)) ([A-M](?: and [A-M])?))?$", n)
    if m and side == "Union":
        func = "A" if (m.group(3) or m.group(2) == "Artillery") else ("C" if (m.group(2) == "Cavalry" or section == "cavalry") else "I")
        code = ix.one(ix.by.get(("Union", "UR", int(m.group(1)), "R", func), []), prefer=lambda u: "Mounted" not in u["unit_name"])
        return code, (f"battery {m.group(3)}" if m.group(3) else None)
    # "Confederate" units
    m = re.match(ORDN + r"\s+Confederate(?: (Infantry|Cavalry))?", n)
    if m and side == "Confederate":
        func = "C" if (m.group(2) == "Cavalry" or section == "cavalry") else "I"
        return ix.one(ix.by.get(("Confederate", "CS", int(m.group(1)), "R", func), [])), None
    # Union batteries
    m = re.match(ORDN + r"\s+(" + ST_RE + r")(?: (Light|Heavy))?(?: Artillery)?,? Batter(?:y|ies) ([A-M])", n) or \
        re.match(r"Batter(?:y|ies) ([A-M]),? " + ORDN + r"\s+(" + ST_RE + r")(?: (Light|Heavy))?", n)
    if m and side == "Union":
        g = m.groups()
        if g[0].isdigit():
            num, st, kind, letter = int(g[0]), g[1], g[2], g[3]
        else:
            letter, num, st, kind = g[0], int(g[1]), g[2], g[3]
        cands = ix.by.get(("Union", STATES[st], num, "R", "A"), [])
        code = ix.one(cands, prefer=lambda u: ("Heavy" in u["unit_name"]) == (kind == "Heavy"))
        return code, f"battery {letter}"
    m = re.match(ORDN + r"\s+(?:Independent\s+)?(" + ST_RE + r")\s+(?:Independent\s+)?(?:Light\s+)?Battery", n) or \
        re.match(r"(" + ST_RE + r") Light Artillery,? " + ORDN + r" Battery", n)
    if m and side == "Union":
        g = m.groups()
        num, st = (int(g[0]), g[1]) if g[0].isdigit() else (int(g[1]), g[0])
        return ix.one(ix.by.get(("Union", STATES[st], num, "Y", "A"), []) or ix.by.get(("Union", STATES[st], num, "Y", ""), [])), None
    # Named units by surname / nickname + state + class
    sm = re.search(r"\(?(" + ST_RE + r")\)?", n)
    if not sm:
        return None, None
    st = STATES[sm.group(1)]
    k = klass(n + " " + (section or ""))
    keys = []
    sn = surname(n)
    if sn:
        keys.append(sn)
    pre = re.match(r"^([A-Z][A-Za-z .]+?)\s+\(?(?:" + ST_RE + r")", n)          # "Letcher (Virginia) Artillery"
    if pre:
        keys.append(re.sub(r"['’]s?$", "", pre.group(1)).strip().lower())
    for c in commanders or []:                                                 # captain's surname for batteries
        c = c["name"] if isinstance(c, dict) else c
        m = re.search(r"([A-Z][a-z]+)(?:,? jr)?\.?\s*$", c.strip())
        if m and k == "artillery":
            keys.append(m.group(1).lower())
    for key in keys:
        code = ix.one(ix.named.get((side, st, key, k), []))
        if code:
            return code, None
    return None, None
