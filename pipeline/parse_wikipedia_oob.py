"""Parse Wikipedia "order of battle" articles into unit placements.

Usage:
  python3 pipeline/parse_wikipedia_oob.py data/wikipedia/oob.jsonl data/external/acw_battle_data/nps_units.csv data/wikipedia/oob_placements.jsonl

Works line by line on the wikitext (tables or nested lists):
  == headings ==         army / corps / wing context
  non-bullet lines       division / brigade headers ("Heth's Division", "Pettigrew's Brigade") and their commanders
  bullet lines           units: "26th North Carolina: Col Henry K. Burgwyn, Jr (k), Ltc John R. Lane (w)"
Commanders keep casualty marks: k killed, mw mortally wounded, w wounded, c captured.
Unit codes come from the same matcher as the Official Records parser.
"""
import csv, json, re, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parse_or_all import nps_index, match, split_units
from unit_match import Index, match_named

RANKS = r"(?:Gen|GEN|LTG|Lt\. ?Gen|MG|Maj\. ?Gen|BG|Brig\. ?Gen|Col|COL|Ltc|LTC|Lt\. ?Col|Maj|MAJ|Cpt|Capt|CPT|1Lt|2Lt|Lt|Lieut|Sgt|Surg)\.?"
RANK_LINE = re.compile(r"^\s*" + RANKS + r"\s")
STRUCT = re.compile(r"\b(Corps|Division|Brigade|Battalion|Wing|Army|Reserve|Artillery|Cavalry|Escort|Headquarters|Guard|District|Department|Command|Column|Detachment)\b")


def clean(s):
    s = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"<br\s*/?>|&nbsp;|''+|<[^>]+>", " ", s)
    s = re.sub(r"(?:^|\|\s*)(?:rowspan|colspan|style|align|width|bgcolor)\s*=\s*\"?[^|]*\"?\s*\|", "", s)
    return re.sub(r"\s+", " ", s).strip(" |")


def commanders(text):
    """'Col A (k), Ltc B (w&c), Cpt C' -> [{'name':'Col A','status':'k'}, ...]"""
    out = []
    for part in re.split(r",\s*(?=" + RANKS + r"\s)", text):
        part = part.strip(" ,;.")
        if not part:
            continue
        m = re.search(r"\(\s*([kmwc&/ ]+)\s*\)\s*$", part)
        status = re.sub(r"\s", "", m.group(1)) if m else None
        name = part[:m.start()].strip() if m else part
        if RANK_LINE.match(name + " "):
            out.append({"name": name, "status": status})
    return out


def side_and_battle(title):
    side = "Confederate" if "Confederate" in title else ("Union" if "Union" in title or "Federal" in title else "?")
    battle = re.split(r"\s+order of battle|\s+Union order|\s+Confederate order", title)[0]
    phase = re.search(r"order of battle:?\s*(.*?)(?:,?\s*(?:Union|Confederate))?$", title)
    return side, battle.strip(), (phase.group(1).strip(" ,") if phase else "")


def parse(page, idx):
    side, battle, phase = side_and_battle(page["title"])
    rows, ctx = [], {"h2": None, "h3": None, "h4": None}
    groups = []                      # stack of (kind, name, commanders) for current division / brigade
    div = brig = None; div_cmd = []; brig_cmd = []; last_hdr = None; skipping = False
    for raw in page["wikitext"].splitlines():
        line = raw.strip()
        if not line or line.startswith(("{|", "|}", "!", "[[File", "[[Image", "{{")):
            continue
        h = re.match(r"^(=+)\s*(.*?)\s*=+$", line)
        if h:
            lvl = len(h.group(1)); name = clean(h.group(2))
            if re.search(r"^(References|Notes|Sources|See also|External links|Bibliography|Further reading|Citations|Footnotes)", name, re.I):
                break
            if lvl == 2:
                skipping = bool(re.search(r"^(Abbreviations|Key|Legend|Background|Overview|Casualties)", name, re.I))
            if skipping:
                continue
            ctx[{2: "h2", 3: "h3"}.get(lvl, "h4")] = name
            if lvl == 2: ctx["h3"] = ctx["h4"] = None
            if lvl == 3: ctx["h4"] = None
            div = brig = None; div_cmd = []; brig_cmd = []
            continue
        if line.startswith("|-") or skipping:
            continue
        bullet = re.match(r"^(\*+)\s*(.*)$", line)
        text = clean(bullet.group(2) if bullet else line.lstrip("|").strip())
        if not text:
            continue
        if bullet and not STRUCT.search(text.split(":")[0]):
            unit, _, cmd = text.partition(":")
            unit = unit.strip(" :")
            if not unit or RANK_LINE.match(unit + " "):
                continue
            for nm in split_units(unit):
                r = {"source": "wikipedia", "title": page["title"], "revid": page["revid"], "side": side, "battle": battle,
                     "phase": phase, "army": ctx["h2"], "corps": ctx["h3"] or ctx["h2"], "section": ctx["h4"],
                     "division": div, "division_commanders": div_cmd, "brigade": brig, "brigade_commanders": brig_cmd,
                     "unit": nm, "commanders": commanders(cmd)}
                if side in ("Union", "Confederate"):
                    code = match(nm, "cavalry" if re.search(r"Cavalry", f"{brig} {div} {ctx['h3']}") else "infantry", side, None, idx)
                    if not code:
                        code, note = match_named(nm, side, "cavalry" if "Cavalry" in f"{brig} {div}" else
                                                 ("artillery" if re.search(r"Artillery|Batter", f"{brig} {nm}") else "infantry"),
                                                 r["commanders"], IX)
                        if code:
                            r["matched_by"] = "named"
                            if note: r["portion"] = note
                    if code:
                        r["unit_code"] = code
                rows.append(r)
            continue
        if RANK_LINE.match(text + " "):                 # a commander line under the last header
            c = commanders(text)
            if last_hdr == "brigade": brig_cmd = brig_cmd + c
            elif last_hdr == "division": div_cmd = div_cmd + c
            continue
        head = text.split("|")[-1].strip()
        if re.search(r"\bDivision\b", head) and not re.search(r"\bBrigade\b", head):
            div, div_cmd, brig, brig_cmd, last_hdr = head, commanders(head.split(head.split()[-1])[-1]) if False else [], None, [], "division"
        elif STRUCT.search(head):
            brig, brig_cmd, last_hdr = head, [], "brigade"
    return rows


IX = None


def main(oob, units_csv, out):
    global IX
    idx = nps_index(units_csv)
    IX = Index(units_csv)
    pages = [json.loads(l) for l in open(oob, encoding="utf-8")]
    allr = []
    for p in pages:
        if p["title"].startswith("List of"):
            continue
        allr += parse(p, idx)
    with open(out, "w", encoding="utf-8") as f:
        for r in allr:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    st = Counter((r["side"], "matched" if (r.get("unit_code") or "AMB").startswith(("U", "C")) and not r.get("unit_code", "").startswith("AMB") else "other") for r in allr)
    print(f"articles: {len(pages)}; placements: {len(allr)}; by side/match: {dict(st)}")
    print("with a division:", sum(1 for r in allr if r["division"]), "with a brigade:", sum(1 for r in allr if r["brigade"]),
          "with unit commanders:", sum(1 for r in allr if r["commanders"]))
    print("commanders with casualty marks:", sum(1 for r in allr for c in r["commanders"] if c["status"]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
