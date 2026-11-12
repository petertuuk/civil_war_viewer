"""Dyer's unit <-> NPS unit code links, cleaned.

data/scores/dyer_to_nps.csv links some qualified Dyer's units to a plain NPS code (1st Michigan Colored Infantry ->
the 1st Michigan Infantry's code; Missouri State Militia Cavalry -> Missouri Cavalry). Those links are dropped
here, and where one code is still linked to several Dyer's units it goes to the one with the shortest heading
(the plain unit). Every consumer (or_to_claims, wikipedia_to_claims, build_db, compare_oob, score_dyers_vs_cwss)
loads links through this module.

Content check (2026-11-11): where data/witness/matches.json exists (pipeline/match_witnesses.py), a link whose NPS
page has text must also match the unit's Dyer's text (or its Civil War Archive copy). That replaces the name rules:
  - verified matches are used, including ambiguous candidates resolved by content;
  - a code whose NPS text does not match is dropped (militia / emergency / enrolled militia units and "See ..."
    cross-references had taken the 3-year regiment's code);
  - links that cannot be checked (NPS page empty or not fetched) fall back to the name rules.
"""
import csv, json, re
from pathlib import Path

QUAL = ["colored|african", "militia", "national guard", "home guard", "wing", "enrolled", "state guard",
        "potomac home", "emergency"]


def load(d2n_path, nps_units_path=None):
    """Return (dyer_to_code, code_to_dyer, dropped_unit_ids)."""
    if nps_units_path is None:
        nps_units_path = Path(d2n_path).parents[1] / "external/acw_battle_data/nps_units.csv"
    name = {r["unit_code"]: r["unit_name"].lower() for r in csv.DictReader(open(nps_units_path, encoding="utf-8"))}
    root = Path(d2n_path).parents[1]
    mp, npp = root / "witness/matches.json", root / "nps_us/units.jsonl"
    verified, has_text = {}, set()
    if mp.exists() and npp.exists():
        verified = {k: v["nps"]["code"] for k, v in json.load(open(mp, encoding="utf-8")).items() if "nps" in v}
        has_text = {r["unit_code"] for r in map(json.loads, open(npp, encoding="utf-8")) if not r["empty"]}
    d2c, dropped = {}, []
    for r in csv.DictReader(open(d2n_path, encoding="utf-8")):
        uid = r["unit_id"]
        if uid in verified:
            d2c[uid] = verified[uid]; continue
        if not r["unit_code"]:
            continue
        if r["unit_code"] in has_text:              # checkable, and the content did not match
            dropped.append(uid); continue
        d = uid.split("/")[1].replace("_", " ").lower()
        n = name.get(r["unit_code"], "")
        if any(re.search(q, d) and not re.search(q, n) for q in QUAL):
            dropped.append(uid); continue
        d2c[uid] = r["unit_code"]
    c2d = {}
    for d, c in sorted(d2c.items(), key=lambda kv: (len(kv[0].split("/")[1]), kv[0])):
        c2d.setdefault(c, d)
    d2c = {d: c for d, c in d2c.items() if c2d[c] == d}       # one Dyer's unit per code
    return d2c, c2d, dropped


# ------------------------------------------------------------------ ambiguous NPS codes
_NAMES = None
NOT_FIELD = __import__("re").compile(r"Consolidated|/|Local Defense|\bmonths\b|Army of 10,000|Militia|Reserves|State Guard", 0)


def resolve_ambiguous(code, units_csv=None):
    """'AMBIGUOUS:CMO0001RI01|CMO0001RI02' -> the one field regiment once consolidated, local-defense, short-term
    and militia namesakes are set aside ('1st Missouri' -> 1st Regiment, not 1st/4th Consolidated). None when
    several field regiments share the number (South Carolina's five 1st Infantry regiments)."""
    global _NAMES
    if not code or not code.startswith("AMBIGUOUS:"):
        return code
    if _NAMES is None:
        import csv
        from pathlib import Path
        p = units_csv or Path(__file__).resolve().parents[1] / "data/external/acw_battle_data/nps_units.csv"
        _NAMES = {u["unit_code"]: u["unit_name"] for u in csv.DictReader(open(p, encoding="utf-8"))}
    cands = code.split(":", 1)[1].split("|")
    field = [c for c in cands if not NOT_FIELD.search(_NAMES.get(c, ""))]
    return field[0] if len(field) == 1 else None


_ALIASES = None


def alias_code(name, side, aliases_psv=None):
    """Unit code for a named unit the order-of-battle matcher could not place (data/manual/unit_aliases.psv)."""
    global _ALIASES
    import re
    from pathlib import Path
    if _ALIASES is None:
        p = aliases_psv or Path(__file__).resolve().parents[1] / "data/manual/unit_aliases.psv"
        _ALIASES = []
        if Path(p).exists():
            for line in open(p, encoding="utf-8"):
                if line.startswith("#") or not line.strip():
                    continue
                pat, notw, sd, code, _note = (line.rstrip("\n").split("|") + [""] * 5)[:5]
                _ALIASES.append((re.compile(pat), notw, sd, code))
    for rx, notw, sd, code in _ALIASES:
        if sd and side in ("Union", "Confederate") and sd != side:
            continue
        if rx.search(name or "") and not any(w and w in name for w in notw.split(";")):
            return code
    return None


_BATT = None


def battery_unit(reg_id, portion, units_clean=None):
    """Dyer's battery unit for a placement linked to its artillery regiment: ('illinois/0xx_1st_regiment_light_artillery',
    'battery H') -> 'illinois/0xx_battery_h_1st_regiment_light_artillery'. Dyer's gives each lettered battery its own
    record, so the claim belongs there, not on the regiment."""
    global _BATT
    import json, re
    from pathlib import Path
    m = re.match(r"batter(?:y|ies) ([A-M])\b", portion or "", re.I)
    if not reg_id or not m or "/" not in reg_id:
        return None
    if _BATT is None:
        _BATT = {}
        p = units_clean or Path(__file__).resolve().parents[1] / "data/dyers/units_clean.jsonl"
        for l in open(p, encoding="utf-8"):
            i = json.loads(l)["id"]
            b = re.search(r"/\d+_battery_([a-m])_(\d+)(?:st|nd|rd|th|d)_", i)
            if b:
                _BATT[(i.split("/")[0], int(b.group(2)), b.group(1), "heavy" in i)] = i
    r = re.search(r"/\d+_(\d+)(?:st|nd|rd|th|d)_(?:regiment_)?(?:light_|heavy_)?artillery", reg_id)
    if not r:
        return None
    return _BATT.get((reg_id.split("/")[0], int(r.group(1)), m.group(1).lower(), "heavy" in reg_id))


def battery_from_code(code, portion, code2dyer):
    """Same, from the NPS regiment code ('UIL0001RAL' + 'battery H'): the NPS list has no lettered batteries."""
    import re
    m = re.match(r"U([A-Z]{2})(\d{4})RA([LH]?)$", code or "")
    if not m or not re.match(r"batter(?:y|ies) [A-M]\b", portion or "", re.I):
        return None
    st, num, lh = m.group(1), int(m.group(2)), m.group(3)
    pref = {"UR": "u_s_regular_army", "US": "u_s_colored_troops"}.get(st)
    if not pref:
        pref = next((v.split("/")[0] for k, v in code2dyer.items() if k[1:3] == st and "/" in v), None)
    if not pref:
        return None
    battery_unit(f"{pref}/000_x", portion)         # loads the table
    letter = re.match(r"batter(?:y|ies) ([A-M])", portion, re.I).group(1).lower()
    for heavy in ((lh == "H",) if lh else (False, True)):
        i = _BATT.get((pref, num, letter, heavy))
        if i:
            return i
    return None
