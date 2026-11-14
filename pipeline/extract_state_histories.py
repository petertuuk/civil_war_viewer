"""Battle participation from public-domain state unit histories (data/external/state_histories; see its README):
Clark's North Carolina regiments (1901, 5 vols), Rowland's Mississippi register (1908 v.3, cavalry and state troops),
Lindsley's Military Annals of Tennessee (1886: "FIRST TENNESSEE INFANTRY." chapters by veterans, memorial rolls) and
Brewer's Alabama (1872: "TWENTIETH ALABAMA- (Infantry)." sketches with officer lists "killed at Shiloh").
Headings' OCR-garbled ordinals ("FOBTY-FIEST") are repaired by closest ordinal word; a state number with several NPS
units (Tennessee's 1st, 2nd...) is skipped.

1. Chapters: an upper-case heading line "TWENTY-SIXTH REGIMENT." (Clark; "ADDITIONAL SKETCH ..." too) or
   "SECOND REGIMENT— CAVALRY." (Rowland) starts a unit's chapter, which runs to the next such heading. The heading
   becomes an NPS unit code (data/external/acw_battle_data/nps_units.csv): Clark numbers all North Carolina State Troops
   regiments in one series, so his 9th, 19th, 41st, 59th, 63rd, 65th are the 1st-6th Cavalry and his 10th, 36th, 40th
   the 1st-3rd Artillery; the 17th's first organization (captured at Roanoke Island) is used before 1862-03.
   Battalions, companies, rosters and state troops without an NPS code are skipped.
2. Sentences: each sentence naming a battle is checked against well-attested events (data/events/events.jsonl with a
   Wikidata item, or 20+ regiments, kind battle/siege/engagement/combat/assault): the battle's place word ("Gettysburg",
   "Sharpsburg" -> Antietam, "Manassas" -> Bull Run, "Murfreesboro" -> Stones River, "Fair Oaks" -> Seven Pines) and a
   date in the sentence within 3 days of the event (a year-only route, USE_YEAR, is off: about half wrong). Sentences that
   are hearsay ("heard of", "news", about the enemy) or name another regiment's number are skipped; names that are also
   generals' surnames (Jackson, Franklin) need battle wording ("battle of Franklin").
   Second route (USE_UNIQUE), no day date: strict wording ("fought at", "engaged at", "killed at", "k. in action at";
   not "captured", "promoted") and a battle name that only one well-attested event has, within a year of the
   chapter's current year. Checked against other sources (validate_state_histories.py): ~65-75% confirmed for
   Lindsley and Brewer; most unconfirmed ones read right in a hand sample (other sources are incomplete).
3. One participated claim per unit and event (the first sentence that names it is the span), confidence 0.5
   (narratives also mention battles their unit only heard of).
Writes data/derived/state_histories.json (manual claims format) and data/scores/state_histories_report.txt.
Usage: python pipeline/extract_state_histories.py data/external/state_histories data/events/events.jsonl \
    data/external/acw_battle_data/nps_units.csv data/derived/state_histories.json data/scores/state_histories_report.txt
"""
import csv, json, re, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from or_datelines import ordnum  # noqa: E402

BOOKS = {  # file stem -> (state, author style)
    "cu31924092908536": ("NC", "clark"), "cu31924092908544": ("NC", "clark"), "historiesofsever03clar": ("NC", "clark"),
    "cu31924092908569": ("NC", "clark"), "historiesofsever05clar": ("NC", "clark"), "officialstatisti03miss": ("MS", "rowland"), "officialstatisti02miss": ("MS", "rowland"),
    "cu31924032778700": ("TN", "lindsley"), "cu31924028794042": ("AL", "brewer"),
}
STATE_NAME = {"NC": "North Carolina", "MS": "Mississippi", "TN": "Tennessee", "AL": "Alabama"}
HEADS = {  # style -> chapter heading (other styles: HEAD below, upper case)
    "lindsley": re.compile(r"^[A-Z][A-Z\-' ()]+ (TENNESSEE|TENN\.|KENTUCKY|CONFEDERATE)?\s*(INFANTRY|CAVALRY|BATTALION|ARTILLERY|"
                           r"REGIMENT|BATTERY)\b[A-Z.,* ()]*$|^[A-Z][A-Z'\- ]+ (ARTILLERY|BATTERY)[.,*]?$"),
    "brewer": re.compile(r"^(?:[IV]+\.[—–-]\s*)?[A-Z][A-Z'\-, ]+?\s*A\s?L\s?A\s?B\s?A\s?M\s?A\*?(?:\s*[—–-]+\s*[({].{4,14}?[)}]|\s+BATTALION.*|\s+REGIMENT.*)?\s*[.,]?\s*$"),
}
NC_CAV = {9: 1, 19: 2, 41: 3, 59: 4, 63: 5, 65: 6}
NC_ART = {10: 1, 36: 2, 40: 3}
OCR_ORD = {"thied": "third", "foubth": "fourth", "fikst": "first", "thihd": "third", "seventli": "seventh", "eiglith": "eighth",
           "fouetii": "fourth", "nintli": "ninth"}
MON = "January|February|March|April|May|June|July|August|September|October|November|December"
MN = {m.lower(): i + 1 for i, m in enumerate(MON.split("|"))}
DATE = re.compile(rf"\b({MON})\s+(\d{{1,2}})(?:st|d|nd|rd|th)?(?:\s*[-–,]\s*\d{{1,2}})?(?:,?\s*(18[6][0-5]))?")
DATE2 = re.compile(rf"\b(\d{{1,2}})(?:st|d|nd|rd|th)?\s+(?:of\s+)?({MON}),?\s*(18[6][0-5])?")
YEAR = re.compile(r"\b(186[0-5])\b")
ALIAS = {"sharpsburg": "antietam", "manassas": "bull run", "murfreesboro": "stones river", "murfreesborough": "stones river",
         "fair oaks": "seven pines", "spottsylvania": "spotsylvania", "gaines mill": "gaines mill", "gaines' mill": "gaines mill",
         "cold harbor": "cold harbor", "mechanicsville": "beaver dam creek", "kenesaw": "kennesaw", "boonsboro": "south mountain"}
USE_UNIQUE = True  # no day date, but battle wording ("fought at", "killed at") and a name only one well-attested event has
USE_YEAR = False   # year-only matches (no day date in the sentence): ~half wrong in a sample (recollections of earlier
                   # battles, 2026-11-12); off
GOOD_KINDS = {"battle", "siege", "engagement", "combat", "assault", ""}


def key_of(name):
    n = name.lower().replace("’", "'")
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"^(the )?((first|second|third) )?(battle|siege|battles|engagement|combat|action|assault) (of|at|on|for) ", "", n)
    n = re.sub(r",.*$", "", n)
    n = re.sub(r"\b(court house|courthouse)\b", "court house", n)
    n = re.sub(r"'s\b", "s", n).replace("'", "")
    n = re.sub(r"\s+", " ", n).strip()
    return ALIAS.get(n, n)


ORD_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh",
             "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth",
             "twentieth", "twenty", "thirtieth", "thirty", "fortieth", "forty", "fiftieth", "fifty", "sixtieth", "sixty",
             "seventieth", "seventy", "eightieth", "eighty"]


def fix_ordinal_ocr(t):
    """'fobty-fiest' -> 'forty-first' (OCR of upper-case headings: B/E for R, Y for V, T for Y)."""
    import difflib
    def one(w):
        if w in ORD_WORDS or not re.fullmatch(r"[a-z]{4,12}", w):
            return w
        m = difflib.get_close_matches(w, ORD_WORDS, n=1, cutoff=0.7)
        return m[0] if m else w
    t = re.sub(r"\b(t ?w ?e ?n ?t ?y|t wenty)\b", "twenty", t)
    head = re.split(r"\s+(?=alabama|tennessee|north carolina|regiment|a l a b)", t, maxsplit=1)
    head[0] = re.sub(r"[a-z]+", lambda m: one(m.group(0)), head[0])
    return " ".join(head)


def unit_code(heading, st, style, codes, d=None):
    h = heading.upper()
    if style == "brewer" and re.search(r"'S\b|\bI+\.", h):
        return None                                                # Roddy's / Russell's 4th, I.- / II.- 9th: two of a number
    if re.search(r"COMPANY|ROSTER|OFFICERS|BATTALION|BATTERY|MINUTE|STATE TROOPS|RESERVE|HOME GUARD|MILITIA|MOUNTED|CONFEDERATE", h):
        return None
    t = h.lower()
    for a, b in OCR_ORD.items():
        t = t.replace(a, b)
    t = fix_ordinal_ocr(t)
    n = ordnum(re.sub(r"additional sketch", "", t))
    if not n:
        return None
    if style == "clark":
        if n in NC_CAV:
            return f"CNC{NC_CAV[n]:04d}RC"
        if n in NC_ART:
            return f"CNC{NC_ART[n]:04d}RA"
        for c in (f"CNC{n:04d}RI", f"CNC{n:04d}RI02", f"CNC{n:04d}R0S"):
            if c in codes:
                return c
        return None
    if style in ("lindsley", "brewer"):
        arm = "RC" if "CAV" in h else "RI"                         # Brewer's "(Infantry)" is often OCR-garbled
        base = f"C{st}{n:04d}{arm}"
        if base in codes:
            return base
        alts = [c for c in codes if c.startswith(base) and re.fullmatch(r"\d\d", c[len(base):] or "x")
                and "onsolidated" not in codes[c]]
        return alts[0] if len(alts) == 1 else None                  # several regiments of that number: leave it
    if "CAVALRY" in h:
        c = f"C{st}{n:04d}RC"
        return c if c in codes else None
    if "INFANTRY" in h or re.match(r"^[A-Z\-]+ REGIMENT\.?$", h.strip()):
        c = f"C{st}{n:04d}RI"
        return c if c in codes else None
    return None


NEG = re.compile(r"\b(had just fought|until the battle|until after|winter succeeding|great battles of|captured at|"
                 r"promoted|heard|hear of|news|rumou?r|reported that|telegraph|while we were|had been fought|since the battle|"
                 r"before the battle|after the battle|enemy|federals?|yankees?|union army|general [a-z]+ (was|had|having))\b")
CUE = (r"(battles?|engagements?|fights?|actions?|charges?|siege|assaults?|struggle|conflict|fighting)\s+(of|at|near|around|"
       r"before|on)\s+(the\s+)?((first|second|third)\s+)?{k}\b|"
       r"\b(engaged|fought|participated|took part|took a part|bore|lost|charged|wounded|killed|captured|repulsed|attacked)\b[^.;]{{0,60}}"
       r"\b(at|of|near|in|around)\s+(the\s+)?((first|second|third)\s+)?{k}\b")
CUE_STRICT = (r"\b(engaged|fought|participated|took part|took a part|bore a part|lost (heavily|severely|\d+)|charged|"
              r"killed|k\.|wounded|mortally wounded|fell)\b(?!.{{0,20}}\b(captured|promoted|resigned)\b)[^.;]{{0,50}}"
              r"\b(at|of|in)\s+(the\s+)?(battles? of\s+)?((first|second|third)\s+)?{k}\b")
PERSONISH = {"jackson", "franklin", "hampton", "stuart", "lee", "pope", "johnston", "grant", "sherman", "early", "hood",
             "morgan", "forrest", "price", "wheeler", "hill", "kelly", "brandy"}
ORDW_RX = re.compile(r"\b((?:one hundred and )?(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)?-?\s?"
                     r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|"
                     r"fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|thirtieth|fortieth|fiftieth|"
                     r"sixtieth|seventieth))\s+(?:north carolina|mississippi|tennessee|alabama|regiment)")


def own_number(head):
    t = head.lower()
    for a, b in OCR_ORD.items():
        t = t.replace(a, b)
    return ordnum(re.sub(r"additional sketch", "", t))


def other_regiment(low, n_own):
    ns = {ordnum(m.group(1)) for m in ORDW_RX.finditer(low)} - {None}
    return bool(ns) and n_own not in ns


HEAD = re.compile(r"^(ADDITIONAL SKETCH,? )?[A-Z][A-Z\-' ]{2,40}(REGIMENT|BATTALION)\b[^a-z]{0,30}$")


def main(src_dir, events_p, units_p, out_p, rep_p):
    codes = {r["unit_code"]: r["unit_name"] for r in csv.DictReader(open(units_p, encoding="utf-8"))}
    # well-attested events by place word
    ev = defaultdict(list)
    for l in open(events_p, encoding="utf-8"):
        e = json.loads(l)
        if not e.get("date_start") or not e.get("date_end"):
            continue
        good = e.get("wikidata") or (e.get("regiments") or 0) >= 20
        if not good or (e.get("kind") or "") not in GOOD_KINDS:
            continue
        for nm in {e["name"], e.get("dyer_name") or e["name"]}:
            k = key_of(nm)
            if len(k) >= 4:
                ev[k].append((date.fromisoformat(e["date_start"][:10]), date.fromisoformat(e["date_end"][:10]),
                              e["event_id"], e["name"]))
    for k in ev:
        ev[k] = sorted(set(ev[k]))
    keys = sorted(ev, key=len, reverse=True)
    KRX = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys + sorted(ALIAS, key=len, reverse=True)) + r")\b")
    stats, claims, seen, per_unit = Counter(), [], set(), Counter()
    for f in sorted(Path(src_dir).glob("*.txt")):
        if f.stem not in BOOKS:
            continue
        st, style = BOOKS[f.stem]
        L = f.read_text(encoding="utf-8", errors="replace").splitlines()
        chapters, cur = [], None
        for i, l in enumerate(L):
            s = l.strip()
            hm = HEADS[style].match(s) if style in HEADS else (HEAD.match(s) and s.upper() == s and len(s) < 70)
            if hm:
                c = unit_code(s, st, style, codes)
                if c or style in HEADS or re.search(r"REGIMENT|BATTALION", s):
                    if cur and cur[0] == c and c:
                        continue                                   # repeated heading (title page, page head)
                    cur = [c, s, i, []]; chapters.append(cur)
                    continue
            if cur is not None:
                cur[3].append(l)
        for code, head, start, lines in chapters:
            if not code:
                stats["chapters without a unit code"] += 1
                continue
            stats["chapters"] += 1
            text = " ".join(lines)
            text = re.sub(r"(\w)- (\w)", r"\1\2", text)                    # re-join hyphenated line breaks
            year = None
            n_own = own_number(head)
            for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", text):
                low = sent.lower().replace("’", "'")
                low = re.sub(r"'s\b", "s", low).replace("'", "")
                days = []
                for m in DATE.finditer(sent):
                    y = int(m.group(3)) if m.group(3) else year
                    if y:
                        try:
                            days.append(date(y, MN[m.group(1).lower()], int(m.group(2))))
                        except ValueError:
                            pass
                for m in DATE2.finditer(sent):
                    y = int(m.group(3)) if m.group(3) else year
                    if y:
                        try:
                            days.append(date(y, MN[m.group(2).lower()], int(m.group(1))))
                        except ValueError:
                            pass
                hits = set(KRX.findall(low))
                if hits and NEG.search(low):
                    stats["sentence is hearsay or about others"] += 1; hits = set()
                if hits and other_regiment(low, n_own):
                    stats["sentence about another regiment"] += 1; hits = set()
                for k0 in hits:
                    k = ALIAS.get(k0, k0)
                    cands = ev.get(k) or []
                    if not cands:
                        continue
                    cue = re.search(CUE.format(k=re.escape(k0)), low)
                    if k in PERSONISH and not cue:
                        continue                                     # "Jackson", "Franklin": the man, not the battle
                    pick = None
                    if days:
                        ok = [c for c in cands if any(c[0] - timedelta(3) <= d <= c[1] + timedelta(3) for d in days)]
                        if len({c[2] for c in ok}) == 1:
                            pick, how = ok[0], "date"
                    elif USE_UNIQUE and re.search(CUE_STRICT.format(k=re.escape(k0)), low) and len({c[2] for c in cands}) == 1 \
                            and (not year or abs(cands[0][0].year - year) <= 1):
                        pick, how = cands[0], "unique name"
                    elif USE_YEAR and year and cue:
                        ok = [c for c in cands if c[0].year == year or c[1].year == year]
                        if len({c[2] for c in ok}) == 1:
                            pick, how = ok[0], "year"
                    if not pick:
                        stats["battle named, no date fit"] += 1
                        continue
                    c_ = code
                    if code.startswith("CNC0017"):
                        c_ = "CNC0017RI01" if pick[0] < date(1862, 3, 1) else "CNC0017RI02"
                    if (c_, pick[2]) in seen:
                        continue
                    seen.add((c_, pick[2]))
                    stats[f"claims by {how}"] += 1; per_unit[c_] += 1
                    claims.append({"type": "participated", "source": "sh", "span": sent.strip()[:240],
                                   "confidence": 0.55 if how == "date" else 0.45, "_how": how, "_book": f.stem,
                                   "extracted_by": "regex:state_histories_v3",
                                   "note": f"{f.stem} line {start + 1}: chapter '{head}'",
                                   "unit": {"nps_code": c_, "display_name": codes.get(c_, c_), "side": "Confederate"},
                                   "unit_mention": head.title(), "event_mention": pick[3],
                                   "event": {"name": pick[3]}, "portion": "whole",
                                   "date_start": pick[0].isoformat(), "date_end": pick[1].isoformat(), "date_precision": "day"})
                ys = YEAR.findall(sent)
                if ys:
                    year = int(ys[-1])
    doc = {"about": "Battle participation from Clark's North Carolina regiments (1901) and Rowland's Mississippi register (1908), "
                    "by pipeline/extract_state_histories.py.",
           "sources": {"sh": {"title": "State unit histories: Clark, Histories of the Several Regiments and Battalions from North "
                                       "Carolina (1901); Rowland, Official and Statistical Register of Mississippi (1908) v.3",
                              "kind": "regimental_history", "url": "https://archive.org/details/cu31924092908536",
                              "public_domain": 1, "notes": "regex extraction: battle names with a fitting date or year"}},
           "claims": claims}
    open(Path(rep_p).with_suffix(".jsonl"), "w").write("".join(json.dumps({"unit": c["unit"]["nps_code"], "event": c["event_mention"],
        "date": c["date_start"], "how": c.pop("_how"), "book": c.pop("_book")}) + "\n" for c in claims))
    json.dump(doc, open(out_p, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    rep = [f"{k}: {v}" for k, v in stats.most_common()] + [f"units with claims: {len(per_unit)}; claims {len(claims)}"]
    open(rep_p, "w").write("\n".join(rep) + "\n")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*sys.argv[1:])
