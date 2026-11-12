"""Parse an Official Records "Organization of ..." table into unit placements.

Usage:
  python3 pipeline/parse_or_organization.py data/or/OR_s1_v27_p2.txt \
      --start "Organization of the Army of Northern Virginia at th" --end "^No\\. 425\\." \
      --army "Army of Northern Virginia" --side Confederate --event "Battle of Gettysburg" \
      --date 1863-07-01..1863-07-03 --source "OR Ser. I, Vol. 27, Pt. 2, pp. 283-291" \
      --units data/external/acw_battle_data/nps_units.csv --out data/or/anv_gettysburg.jsonl

Text must have single spaces (sed -E 's/ +/ /g'). Output, one row per unit:
  unit (as printed), unit_code (NPS, when matched), army, corps, division, brigade,
  commanders (as printed, in order), event, date range, source.
These become subordinate_to (unit -> brigade -> division -> corps) and commanded
claims dated to the event, and participated claims for the event.
"""
import argparse, csv, json, re

RANK = re.compile(r"^(Lieut\.|Lieat\.|Brig\.|Maj\.|Col\.|Capt\.|Cpl\.|Gen\.|Lient\.|Sergt\.|Surg\.|Brevet)", re.I)
ORD = re.compile(r"^(\d+)(?:st|d|nd|rd|th)\b\.?\s+(.*)$")
STATES = {"Alabama": "AL", "Arkansas": "AR", "Florida": "FL", "Georgia": "GA", "Kentucky": "KY", "Louisiana": "LA",
          "Maryland": "MD", "Mississippi": "MS", "Missouri": "MO", "North Carolina": "NC", "South Carolina": "SC",
          "Tennessee": "TN", "Texas": "TX", "Virginia": "VA"}


def lines_between(path, start, end):
    out, on = [], False
    for l in open(path, encoding="utf-8", errors="replace"):
        l = l.strip()
        if not on and re.search(start, l):
            on = True
        elif on and re.search(end, l):
            break
        if on:
            out.append(l)
    return out


def join_wrapped(lines):
    """Drop page furniture and footnotes; join hyphenated and wrapped name lines."""
    keep = []
    for l in lines:
        if not l:
            continue
        if keep and keep[-1].endswith("-") and (l[:1].islower() or not RANK.match(l)):
            keep[-1] = keep[-1][:-1] + l                      # "Leven-" + "thorpe."
            continue
        if re.search(r"division\.?\s*$", l, re.I) and not ORD.match(l):
            keep.append(re.sub(r"[’']", "'", l).upper()); continue       # "m' laws' division."
        if re.fullmatch(r"\d{1,4}", l) or l.startswith(("[Chap", "No. ")) or re.match(r"^[*+†‡§%]|^[a-z]", l) \
                or re.search(r"\b(VA|PA|MD|N\. C)\.,? .*ETC\.?$", l, re.I) or l.lower().startswith("organization of") \
                or re.fullmatch(r"THE [A-Z ]+CAMPAIGN\.?", l):
            continue
        prev = keep[-1] if keep else ""
        if prev and re.search(r",\s*(Lieut\.|Brig\.|Maj\.|Col\.|Capt\.)", prev) and not prev.endswith((".", ":")) \
                or prev and re.search(r"(Capt|Col|Lieut|Maj)\.(\s+[A-Z]\.)*$", prev) and not RANK.match(l) \
                and not ORD.match(l) and "(" not in l and len(l.split()) <= 4:
            keep[-1] = prev + " " + l                         # "Letcher Artillery, Capt. T." + "A. Brander."
            continue
        keep.append(l)
    return keep


def classify(l):
    if re.fullmatch(r"[A-Z0-9’'. ,()&-]+", l) and len(l) > 4:
        if "CORPS" in l: return "corps"
        if "DIVISION" in l or "COMMAND" in l: return "division"
        if "RESERVE" in l or "CAVALRY" in l or "ARTILLERY" in l: return "corps"
        return "division"
    if re.search(r"(Brigade|Battalion)\s*\.?\s*[*+†‡]?\s*$", l) and not ORD.match(l):
        return "brigade"
    if re.fullmatch(r"Artillery\s*\.?", l):
        return "brigade"
    if RANK.match(l):
        return "commander"
    return "unit"


def nps_index(path):
    idx = {}
    for u in csv.DictReader(open(path, encoding="utf-8")):
        if u["belligerent"] != "Confederate" or u["duplicate"] == "1":
            continue
        try:
            o = int(u["ordinal"] or 0)
        except ValueError:
            continue
        idx.setdefault((u["state"], o, u["type"]), []).append(u)
    return idx


def match(unit, section, idx):
    m = ORD.match(unit)
    if not m:
        return None
    n, rest = int(m.group(1)), m.group(2)
    st = next((c for s, c in STATES.items() if rest.startswith(s)), None)
    if not st:
        return None
    typ = "B" if "Battalion" in rest else ("C" if section == "cavalry" or "Cavalry" in rest else
                                          ("Y" if "Artillery" in rest or section == "artillery" else "R"))
    cands = idx.get((st, n, typ), [])
    if typ == "R":
        cands = [u for u in cands if "Infantry" in u["unit_name"]] or cands
    base = [u for u in cands if re.fullmatch(r"C[A-Z]{2}\d{4}[A-Z]{2}", u["unit_code"])]
    if len(cands) > 1 and len(base) == 1:
        return base[0]["unit_code"]                    # 2d South Carolina -> CSC0002RI, not RI02/RIR
    return cands[0]["unit_code"] if len(cands) == 1 else (None if not cands else "AMBIGUOUS:" + "|".join(c["unit_code"] for c in cands))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text"); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--army", required=True); ap.add_argument("--side", default="Confederate")
    ap.add_argument("--event", required=True); ap.add_argument("--date", required=True)
    ap.add_argument("--source", required=True); ap.add_argument("--units"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    idx = nps_index(a.units) if a.units else {}
    lines = join_wrapped(lines_between(a.text, a.start, a.end))
    corps = div = brig = None; section = "infantry"; rows = []; last = None; pending_cmd = None
    prev_kind, scrambled = None, set()
    for l in lines:
        k = classify(l)
        if k not in ("unit", "brigade", "commander"):
            prev_kind = k
        if k == "corps":
            corps, div, brig, last = re.sub(r"[’']S\b", "'s", l.title()).rstrip(" ."), None, None, None
            section = "cavalry" if "CAVALRY" in l else ("artillery" if "ARTILLERY" in l else "infantry")
            pending_cmd = "corps"
        elif k == "division":
            div, brig, last = re.sub(r"[’']S\b", "'s", l.title()).rstrip(" ."), None, None
            if "CAVALRY" in (corps or "").upper():
                section = "cavalry"
            pending_cmd = "division"
        elif k == "brigade":
            if prev_kind == "brigade":
                scrambled.add((corps, div))            # two headers in a row: two-column text read across
            brig, last = l.rstrip(" .*+†‡"), None
            prev_kind = "brigade"
            if brig.startswith("Artillery") or "Battalion" in brig and section != "infantry":
                pass
            pending_cmd = "brigade"
        elif k == "commander":
            if last is not None and last.get("_open"):
                last["commanders"].append(l.rstrip("."))
            # commanders of corps/division/brigade are kept on the unit rows' context only
        else:
            name, cmd = l, None
            m = re.match(r"^(.*?),\s*((?:Lieut\.|Brig\.|Maj\.|Col\.|Capt\.|Gen\.).*)$", l)
            if m:
                name, cmd = m.group(1), m.group(2)
            name = re.sub(r"\s*:\s*[*+†‡§%f]?\s*$", ":", name.strip())
            open_ = name.endswith(":")
            name = name.rstrip(" :.*+†‡§%")
            sec = "artillery" if (brig or "").startswith("Artillery") or section == "artillery" else section
            row = {"unit": name, "army": a.army, "corps": corps, "division": div, "brigade": brig,
                   "commanders": [cmd.rstrip(".")] if cmd else [], "event": a.event,
                   "date_start": a.date.split("..")[0], "date_end": a.date.split("..")[-1],
                   "side": a.side, "source": a.source, "_open": open_, "_section": sec}
            code = match(name, sec, idx) if idx else None
            if code: row["unit_code"] = code
            rows.append(row); last = row
        prev_kind = k
    flagged = 0
    for r in rows:
        if (r["corps"], r["division"]) in scrambled:
            r["confidence"] = "low"; r["note"] = "two-column text read across columns; brigade may be wrong"; flagged += 1
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            r.pop("_open", None)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    matched = sum(1 for r in rows if r.get("unit_code") and not r["unit_code"].startswith("AMB"))
    amb = sum(1 for r in rows if (r.get("unit_code") or "").startswith("AMB"))
    print(f"units: {len(rows)}; matched to NPS codes: {matched}; ambiguous: {amb}; unmatched: {len(rows)-matched-amb}")
    print(f"rows flagged low confidence (two-column scramble): {flagged}")
    print(f"corps: {len({r['corps'] for r in rows})}; divisions: {len({(r['corps'], r['division']) for r in rows})}; "
          f"brigades: {len({(r['division'], r['brigade']) for r in rows})}")


if __name__ == "__main__":
    main()
