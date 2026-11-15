"""Dated positions (unit_at claims) from the public-domain state unit histories read by extract_state_histories.py
(Clark's North Carolina, Rowland's Mississippi pts. 2-3, Lindsley's Tennessee, Brewer's Alabama).

extract_state_histories.py takes battle participation from these chapters; this script takes where the regiment was
between battles. Chapters and their NPS unit codes are found the same way (its BOOKS, HEAD(S), unit_code).
Sentence by sentence (years 1861-1865 only; the chapter's year and month carried along from earlier dates):
  date   a day date ("May 14", "14th of May", year from the sentence or the chapter so far), "on the 27th" with the
         month of the chapter's last date when the day is later in that month, or a month ("In March, 1862,": month
         precision). No date, no claim.
  verb   a station word -- camped, encamped, bivouacked, (went into) winter quarters, stationed, garrisoned, posted,
         on duty, remained, arrived, reached, occupied (confidence 0.6) -- or a movement word -- moved, marched,
         ordered, sent, transferred, proceeded, went, took the cars, embarked (0.45: the destination on the date the
         move began) -- with a capitalized place within 40 characters after it.
  place  located like the NPS histories (extract_nps_histories.py): data/places/geocoded.csv, then a unique GNIS
         town or post; state written after the place, else states named in the sentence, else the state of the
         chapter's previous claim, else the unit's state. Counties, rivers, roads and generals are skipped.
Skipped: sentences naming another regiment's number, the enemy as subject ("the enemy moved"), companies or
detachments ("Company B was sent"), hearsay, and a claim more than 400 km from the chapter's previous claim within
3 days (a wrong place or date).
Writes data/derived/state_stations.json (manual claims format; build_db loads it through manual_claims.py) and
data/scores/state_stations_report.txt (counts and a sample).
Usage: python pipeline/extract_state_stations.py data/external/state_histories data/external/acw_battle_data/nps_units.csv \
    data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/derived/state_stations.json data/scores/state_stations_report.txt \
    data/events/events.jsonl
"""
import csv, json, os, re, sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import params  # noqa: E402
from gnis_index import norm  # noqa: E402
from common import gnis_by_name_state, km  # noqa: E402
from extract_state_histories import BOOKS, HEADS, HEAD, unit_code, own_number, other_regiment, key_of, ALIAS, GOOD_KINDS  # noqa: E402
from extract_nps_histories import STATES, NOTPLACE  # noqa: E402

MON = "January|February|March|April|May|June|July|August|September|October|November|December"
MN = {m.lower(): i + 1 for i, m in enumerate(MON.split("|"))}
MABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "aug": 8, "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
DAY1 = re.compile(rf"\b({MON}|Jan|Feb|Mar|Apr|Aug|Sept?|Oct|Nov|Dec)\.?\s+(\d{{1,2}})(?:st|d|nd|rd|th)?\b(?!\s*(?:,\s*)?\d{{3}}[^0-9])(?:,?\s*(186[1-5]))?")
DAY2 = re.compile(rf"\b(\d{{1,2}})(?:st|d|nd|rd|th)\s+(?:day\s+)?(?:of\s+)?({MON}),?\s*(186[1-5])?")
ONTHE = re.compile(rf"\b(?:on|by|until|till|about) the (\d{{1,2}})(?:st|d|nd|rd|th)\b(?!\s+(?:day\s+)?(?:of\s+)?(?:{MON}))")
MONTH = re.compile(rf"\b(?:[Ii]n|[Dd]uring|[Ee]arly in|[Ll]ate in|[Bb]y)\s+(?:the\s+)?(?:(?:early|latter|last|first) part of\s+)?({MON}),?\s*(186[1-5])?")
YEAR = re.compile(r"\b(186[1-5])\b")
ABBREV = {"gen", "col", "maj", "mr", "dr", "st", "mt", "ft", "co", "no", "jr", "sr", "vs", "capt", "lieut", "sept", "brig",
          "cav", "inf", "regt", "lt", "adjt", "gov", "hon", "rev", "messrs", "jan", "feb", "aug", "oct", "nov", "dec", "va",
          "tenn", "miss", "ala", "ga", "ky", "la", "ark", "tex", "md", "pa", "fla", "mo"}


class _Split:
    rx = re.compile(r"[.!?]\s+(?=[A-Z\"“])")

    def split(self, text):
        out, a = [], 0
        for m in self.rx.finditer(text):
            w = re.search(r"(\S+)$", text[a:m.start()])
            w = w.group(1).lower().strip("(\"“") if w else ""
            if len(w) == 1 or w in ABBREV or re.fullmatch(r"[a-z]\.[a-z]", w):
                continue                                   # "W. C. F. Brooks", "Gen. Lee", "N.C. troops"
            out.append(text[a:m.start() + 1]); a = m.end()
        out.append(text[a:])
        return out


SPLIT = _Split()
ROSTER = re.compile(r"Total enrolled|on roll|\b(?:Captains?|Lieutenants?|Colonels?|Majors?|Adjutants?|Surgeons?|Chaplains?)\s*[—–-]|"
                    r"\b(?:promoted|resigned|dropped|retired)\s*[;,.]", re.I)
ATPL = re.compile(r"(?:^|[,;]\s+|\b(?:at|near)\s+)(?:(?:[Aa]t|[Nn]ear)\s+)?((?:[A-Z][A-Za-z'’\.]+)(?:\s+(?!(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Aug|Sept?|Oct|Nov|Dec)\b)(?:[A-Z][A-Za-z'’\.]+|of))*),?\s+"
                  rf"(?=(?:{MON}|Jan|Feb|Mar|Apr|Aug|Sept?|Oct|Nov|Dec)\.?\s+\d{{1,2}}\b)")
YEARCTX = re.compile(rf"(?:\b(?:in|of|year|spring|summer|fall|autumn|winter|during|{MON})\s+|,\s*)(186[1-5])\b")
STAY = r"(?:was|were) organized|organized|mustered (?:in|into (?:the )?(?:Confederate |State )?service)|rendezvoused|(?:en)?camped|bivouack?ed|went into (?:winter )?(?:quarters|camp)|(?:in|built|building) winter quarters|stationed|garrisoned|was posted|were posted|on duty|remained|arrived|reached|occupied|halted"
DEPART = r"left|leaving|started from|marched from|moved from|set out from|evacuated|abandoned"
MOVE = r"moved|marched|ordered|sent|transferred|proceeded|went|took the (?:cars|train)|embarked|returned|fell back|retreated"
VERB = re.compile(rf"\b({DEPART}|{STAY}|{MOVE})\b")
PLACE = re.compile(r"(?:\s+(?:at|in|to|near|for|on|upon|into|toward|towards|around|by rail to|by way of))?(?:\s+the(?:\s+(?:field|vicinity|neighborhood|town|city) of)?)?\s+"
                   r"((?:[A-Z][A-Za-z'’\.]+)(?:\s+(?!(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Aug|Sept?|Oct|Nov|Dec)\b)(?:[A-Z][A-Za-z'’\.]+|of))*)(?:,\s*(" + "|".join(STATES) +
                   r"|Va|Tenn|Miss|Ala|Ga|Ky|N\. ?C|S\. ?C|La|Ark|Tex|Md|Pa|Fla|Mo)\.?)?")
SABBR = {"Va": "VA", "Tenn": "TN", "Miss": "MS", "Ala": "AL", "Ga": "GA", "Ky": "KY", "N. C": "NC", "N.C": "NC", "S. C": "SC",
         "S.C": "SC", "La": "LA", "Ark": "AR", "Tex": "TX", "Md": "MD", "Pa": "PA", "Fla": "FL", "Mo": "MO"}
NOTP2 = re.compile(r"^(?:Gen|Col|Capt|Lieut|Maj|Major|Colonel|General|Captain|Lieutenant|Sergeant|Mr|Dr|Rev|Gov|Governor|President|"
                   r"Company|Companies|Co|Regiment|Brigade|Division|Corps|Army|Mississippians|Tennesseans|Federals|Yankees|"
                   r"Confederates|Rebels|Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Christmas|God|They|The|It|"
                   r"He|We|This|That|Here|There|On|In|At|A|An|I|Our|Their|His|Its|After|When|Then|Thence|From|For|By)\b"
                   r"|^(?:Potomac|Rapidan|Rappahannock|Mississippi|Tennessee|Cumberland|Chattahoochee|Shenandoah|James|York|"
                   r"Ohio|Missouri|Kentucky|Virginia|Georgia|Alabama|Carolina|Texas|Arkansas|Louisiana|Maryland|Pennsylvania|"
                   r"Valley|Peninsula|Gulf|Coast|Trans|Old|New|Big|Little|Upper|Lower)$")
NOTP3 = re.compile(r"\b(?:County|Counties|Parish|River|Creek|Road|Pike|Turnpike|Railroad|R\. ?R|Mountain|Mountains|Ridge|Valley|Hill|"
                   r"Brigade|Division|Corps|Army|Regiment|Battalion|Department|District|Line|Lines|Front|Mills?)$")
SKIP = re.compile(r"\b(?:companies? [A-K]\b|company [a-z]+ (?:was|were)|detachment|detail|detached|section|squad|heard|news|"
                  # 'the Confederacy of Southern States, organized at Montgomery' (Clark, 26th N.C.): a government, a
                  # convention or a school class is the subject, not the regiment
                  r"Confedera(?:cy|te (?:States|government|Congress))|government|convention|legislature|Congress|"
                  r"Military Institute|graduated|"
                  r"rumou?r|reported that|prisoners?|captured|exchanged|paroled|hospital|furlough|sick)\b", re.I)
ENEMY_SUBJ = re.compile(r"\b(?:enemy|federals?|yankees?|union (?:army|forces|troops)|[A-Z][a-z]+'s (?:army|corps|cavalry)|"
                        r"Grant|Sherman|Thomas|Rosecrans|Buell|McClellan|Burnside|Hooker|Meade|Sheridan|Schofield|McPherson|"
                        r"he|General [A-Z][a-z]+)\b[^,;]{0,25}$")


def ymd(y, m, d):
    try:
        x = date(y, m, d)
    except ValueError:
        return None
    return x if date(1861, 4, 1) <= x <= date(1865, 6, 30) else None


def mnum(s):
    s = s.lower().rstrip(".")
    return MN.get(s) or MABBR.get(s)


def main(src_dir, units_p, geocoded_p, gnis_p, out_p, rep_p, events_p=None):
    codes = {r["unit_code"]: r["unit_name"] for r in csv.DictReader(open(units_p, encoding="utf-8"))}
    geo, famous = {}, {}
    for g in csv.DictReader(open(geocoded_p, encoding="utf-8")):
        if g["lat"] and g["method"] in ("override", "seed", "gnis"):
            geo[(norm(g["name"]), g["state"])] = (float(g["lat"]), float(g["lon"]), int(float(g["precision_m"])))
            mn = int(g["mentions"] or 0)
            if mn >= 40 and mn > famous.get(norm(g["name"]), ("", 0))[1]:
                famous[norm(g["name"])] = (g["state"], mn)
    ev = {}                                       # battle place word -> {(start, end)}: anchors a chapter's year
    if events_p:
        for l in open(events_p, encoding="utf-8"):
            e = json.loads(l)
            if not e.get("date_start") or not e.get("date_end") or (e.get("kind") or "") not in GOOD_KINDS:
                continue
            if not (e.get("wikidata") or (e.get("regiments") or 0) >= 40):
                continue
            for nm in {e["name"], e.get("dyer_name") or e["name"]}:
                k = key_of(nm)
                if len(k) >= 5:
                    ev.setdefault(k, set()).add((date.fromisoformat(e["date_start"][:10]), date.fromisoformat(e["date_end"][:10])))
    EVRX = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(set(ev) | {a for a in ALIAS if ALIAS[a] in ev}, key=len, reverse=True)) + r")\b") if ev else None

    def anchor(sent, ds):
        """A battle named in the sentence whose dates fit a date here up to the year: that year."""
        if not EVRX or not ds:
            return None
        low = re.sub(r"'s\b", "s", sent.lower().replace("’", "'")).replace("'", "")
        ys_ = set()
        for k0 in set(EVRX.findall(low)):
            for a, b in ev.get(ALIAS.get(k0, k0), ()):
                for d in ds:
                    for yy in (a.year, b.year):
                        x = ymd(yy, d[1].month, d[1].day if d[2] == "day" else 1)
                        if x and a - timedelta(3) <= x <= b + timedelta(3 if d[2] == "day" else 31):
                            ys_.add(yy)
        return ys_.pop() if len(ys_) == 1 else None

    G = gnis_by_name_state(gnis_p, ("Populated Place", "Military", "Civil", "Crossing", "Gap", "Island"))

    CSA = ["VA", "NC", "SC", "GA", "FL", "AL", "MS", "LA", "TX", "AR", "TN", "KY", "MO", "MD", "WV", "PA"]

    def cands(name, s):
        n = norm(name)
        out = []
        for s2 in ([s, "WV"] if s == "VA" else [s]):
            if (n, s2) in geo:
                return [geo[(n, s2)] + (s2,)]
            cs = G.get((n, s2)) or G.get((norm(re.sub(r"^Fort\b", "Ft", name)), s2)) or []
            pp = [c for c in cs if c[2] == "Populated Place"] or cs
            if len(pp) == 1 or (pp and len({(round(c[0], 1), round(c[1], 1)) for c in pp}) == 1):
                out.append((pp[0][0], pp[0][1], 3000, s2))
        return out

    def locate(name, explicit, sent_states, prev, unit_st, stale=None):
        """explicit state > nearest to the previous claim (within 400 km; the Dyer's-famous place first) > famous >
        states named in the sentence > the unit's state."""
        n = norm(name)
        if explicit:
            cs = cands(name, explicit)
            return cs[0] if cs else None
        fam = None
        if n in famous and (n, famous[n][0]) in geo:
            fam = geo[(n, famous[n][0])] + (famous[n][0],)
        if prev and fam and len(prev) > 4:                # the reference is only a place named in the sentence
            return fam
        if prev:
            if fam and km((prev[1], prev[2]), fam[:2]) <= params.STATION_PREV_KM:
                return fam
            allc = [c for s in CSA for c in cands(name, s)]
            near = sorted((km((prev[1], prev[2]), c[:2]), c) for c in allc)
            if near and near[0][0] <= params.STATION_PREV_KM:
                return near[0][1]
            return fam
        if fam:
            return fam
        for s in sent_states:
            cs = cands(name, s)
            if cs:
                return cs[0]
        if stale:
            allc = [c for s in CSA for c in cands(name, s)]
            near = sorted((km((stale[1], stale[2]), c[:2]), c) for c in allc)
            if near and near[0][0] <= params.STATION_STALE_KM:
                return near[0][1]
        for s in [unit_st]:
            cs = cands(name, s)
            if cs:
                return cs[0]
        return None

    stats, claims, keys, sample = Counter(), [], set(), []
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
                        continue
                    cur = [c, s, i, []]; chapters.append(cur)
                    continue
            if cur is not None:
                cur[3].append(l)
        for code, head, start, lines in chapters:
            if not code:
                continue
            stats["chapters"] += 1
            text = re.sub(r"(\w)- (\w)", r"\1\2", " ".join(lines))
            text = re.sub(r"\s+", " ", text)
            text = re.sub(r"\b1\s?[8S]\s?6\s?([1-5])\b", r"186\1", text)
            text = re.sub(r"([A-Z][a-z]+) (ville|burg|boro|borough|town)\b", r"\1\2", text)    # OCR: "Shelby ville"      # OCR: "186 1", "1 86 1", "1S61"
            n_own = own_number(head)
            year, last, prev = None, None, None          # chapter year, last date seen, previous claim (date, lat, lon, state)
            for sent in SPLIT.split(text):
                if ROSTER.search(sent):
                    stats["roster sentences skipped"] += 1
                    continue
                ys = [int(y) for y in YEARCTX.findall(sent)]
                if not year and not ys:
                    continue
                ds = []                                   # (pos, date, precision, year written)

                def add(pos, mo, d_, ytxt):
                    y = ytxt or (ys[0] if ys else year)
                    if not y or not mo:
                        return
                    x = ymd(y, mo, d_) or (None if ytxt else ymd(y + 1, mo, d_))
                    if x:
                        ds.append((pos, x, "day" if d_ != 0 else "month", bool(ytxt)))
                for m in DAY1.finditer(sent):
                    add(m.start(), mnum(m.group(1)), int(m.group(2)), int(m.group(3)) if m.group(3) else None)
                for m in DAY2.finditer(sent):
                    add(m.start(), MN[m.group(2).lower()], int(m.group(1)), int(m.group(3)) if m.group(3) else None)
                for m in ONTHE.finditer(sent):           # "on the 17th": the month of the date before it
                    ref = [d for d in ds if d[0] < m.start() and d[2] == "day"]
                    base = ref[-1][1] if ref else last
                    if base and int(m.group(1)) >= base.day:
                        x = ymd(base.year, base.month, int(m.group(1)))
                        if x:
                            ds.append((m.start(), x, "day", False))
                if not ds:
                    for m in MONTH.finditer(sent):
                        y = int(m.group(2)) if m.group(2) else None
                        yy = y or (ys[0] if ys else year)
                        x = yy and (ymd(yy, MN[m.group(1).lower()], 1) or (None if y else ymd(yy + 1, MN[m.group(1).lower()], 1)))
                        if x:
                            ds.append((m.start(), x, "month", bool(y)))
                ds.sort(key=lambda d: d[0])
                ay = anchor(sent, ds)
                if ay and any(d[1].year != ay for d in ds):
                    stats["year corrected by a battle date"] += 1
                    ds = [(d[0], ymd(ay, d[1].month, d[1].day) or d[1], d[2], True) for d in ds]
                if ay and prev and prev[0] > max(d[1] for d in ds) + timedelta(15):
                    drop = [x for x in claims if x["unit"]["nps_code"] == code and x["date_start"] > max(d[1] for d in ds).isoformat()
                            and x["note"].startswith(f"{f.stem} line {start + 1}:")]
                    for x in drop:
                        claims.remove(x)
                        if os.environ.get("DBG") == code:
                            print("  DROP", x["date_start"], x["place"]["display_name"], "anchor", ay, sent[:80])
                    stats["claims dropped: after a battle-anchored date"] += len(drop)
                    prev = None
                vm = list(VERB.finditer(sent))
                if os.environ.get("DBG") == code:
                    print("  Y", year, "| ds", [(d[1].isoformat(), d[2]) for d in ds], "| v", [v.group(1) for v in vm], "|", sent[:150])
                if ds and vm:
                    found = []                            # (place pos, verb, name, loc)
                    if SKIP.search(sent):
                        stats["skipped: company, detachment or hearsay"] += 1
                    elif other_regiment(sent.lower(), n_own):
                        stats["skipped: names another regiment"] += 1
                    else:
                        sst = [STATES[x] for x in re.findall("|".join(STATES), sent)]
                        ref = prev if prev and abs((ds[0][1] - prev[0]).days) <= 120 else None
                        if not ref:                       # a well-known place named in the sentence ("Sharpsburg")
                            for w in re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)?", sent):
                                if norm(w) in famous and (norm(w), famous[norm(w)][0]) in geo:
                                    g = geo[(norm(w), famous[norm(w)][0])]
                                    ref = (ds[0][1], g[0], g[1], famous[norm(w)][0], "named"); break
                        for v in vm:
                            if ENEMY_SUBJ.search(sent[max(0, v.start() - 60):v.start()]):
                                stats["verb: someone else is the subject"] += 1
                                continue
                            pm = PLACE.match(sent, v.end())
                            if not pm or pm.start(1) - v.end() > 40:
                                continue
                            name = re.sub(r"\s+(of|Of)$", "", pm.group(1).strip(" .,'’"))
                            if (NOTPLACE.match(name) or NOTP2.search(name) or NOTP3.search(name) or name in STATES
                                    or len(name) < 3 or mnum(name.split()[0]) or name.endswith("'s")):
                                stats["verb with no place after it"] += 1
                                continue
                            pst = pm.group(2)
                            pst = (STATES.get(pst) or SABBR.get(pst)) if pst else None
                            loc = locate(name, pst, sst, ref, st, prev)
                            if not loc:
                                stats["place not located"] += 1
                                continue
                            if not any(f_[0] == pm.start(1) for f_ in found):
                                found.append((pm.start(1), v.group(1), name, loc))
                        for am in ATPL.finditer(sent):
                            name = am.group(1).strip(" .,'’")
                            if not re.search(r"(?:\b[Aa]t|\b[Nn]ear)\s+" + re.escape(name), sent[max(0, am.start() - 2):am.end()]):
                                continue
                            if (NOTPLACE.match(name) or NOTP2.search(name) or NOTP3.search(name) or name in STATES or len(name) < 3
                                    or mnum(name.split()[0])):
                                continue
                            pos_ = am.start(1)
                            if any(abs(f_[0] - pos_) < 3 for f_ in found):
                                continue
                            loc = locate(name, None, sst, ref, st, prev)
                            if loc:
                                found.append((pos_, "at", name, loc))
                    # dates to places: each place takes the nearest unused date (ties: the later); with several places,
                    # only dates within 90 characters
                    used, out = set(), []
                    for ppos, verb, name, loc in sorted(found):
                        if verb == "at":
                            opts = [d for d in ds if ppos < d[0] <= ppos + len(name) + 4]
                        else:
                            opts = [d for d in ds if d not in used and (len(found) == 1 or abs(d[0] - ppos) <= 90)]
                        if not opts:
                            continue
                        dsel = min(opts, key=lambda d: (abs(d[0] - ppos), -d[0]))
                        used.add(dsel)
                        out.append((verb, name, loc, dsel[1], dsel[2], dsel[3]))
                    for verb, name, loc, d0, prec, ywritten in out:
                        if prev and d0 < prev[0] - timedelta(15):
                            if ywritten:
                                stats["skipped: looks back (written year before the previous claim)"] += 1
                                continue
                            d1 = None
                            for yy in range(prev[0].year, 1866):
                                d1 = ymd(yy, d0.month, d0.day if prec == "day" else 1)
                                if d1 and d1 >= prev[0] - timedelta(15):
                                    break
                                d1 = None
                            if not d1:
                                stats["skipped: date before the previous claim"] += 1
                                continue
                            d0 = d1; stats["year moved forward (chronological narrative)"] += 1
                        if prev and abs((d0 - prev[0]).days) <= 3 and km((prev[1], prev[2]), (loc[0], loc[1])) > params.STATION_JUMP_KM:
                            stats["skipped: >400 km from the previous claim within 3 days"] += 1
                            continue
                        stay = verb == "at" or bool(re.fullmatch(STAY, verb) or re.fullmatch(DEPART, verb))
                        ds_ = d0.isoformat()[:7] if prec == "month" else d0.isoformat()
                        k = (code, ds_, norm(name))
                        if k in keys:
                            continue
                        keys.add(k)
                        prev = (d0, loc[0], loc[1], loc[3])
                        year = d0.year
                        if prec == "day":
                            last = d0
                        kind_ = "at place, date" if verb == "at" else "station" if stay else "movement"
                        stats[f"claims ({kind_}, {prec})"] += 1
                        claims.append({"type": "unit_at", "source": "shs", "span": sent.strip()[:300],
                                       "confidence": (params.STATION_AT_CONF if verb == "at" else params.STATION_STAY_CONF if stay else params.STATION_MOVE_CONF) - (params.STATION_MONTH_PENALTY if prec == "month" else 0),
                                       "extracted_by": "regex:state_stations_v1",
                                       "note": f"{f.stem} line {start + 1}: chapter '{head}'; verb '{verb}'",
                                       "unit": {"nps_code": code, "display_name": codes.get(code, code), "side": "Confederate"},
                                       "unit_mention": head.title(), "place_mention": name,
                                       "place": {"display_name": name, "state": loc[3], "lat": loc[0], "lon": loc[1],
                                                 "precision_m": loc[2], "kind": "town"},
                                       "presence": "present", "portion": "whole",
                                       "date_start": ds_, "date_end": ds_, "date_precision": prec})
                        if os.environ.get("DBG") == code:
                            print("  CLAIM", ds_, name, loc[3], verb)
                        sample.append(f"{code} {ds_} {name}, {loc[3]} [{verb}] | {sent.strip()[:160]}")
                    if out:
                        continue
                if ds:
                    cand = [d for d in ds if not prev or d[1] >= prev[0] - timedelta(15) or d[3]]
                    if cand:
                        dl = cand[-1]
                        if not prev or dl[1] >= prev[0] - timedelta(15):
                            year = dl[1].year
                            if dl[2] == "day":
                                last = dl[1]
                elif ys and (not prev or ys[-1] >= prev[0].year):
                    year = ys[-1]
    doc = {"about": "Dated positions from public-domain state unit histories (Clark NC 1901, Rowland MS 1908, Lindsley TN 1886, "
                    "Brewer AL 1872) by pipeline/extract_state_stations.py.",
           "sources": {"shs": {"title": "State unit histories (stations): Clark, Histories of the Several Regiments and Battalions from "
                                        "North Carolina (1901); Rowland, Official and Statistical Register of Mississippi (1908) pts. 2-3; "
                                        "Lindsley, Military Annals of Tennessee (1886); Brewer, Alabama (1872)",
                               "kind": "regimental_history", "url": "https://archive.org/details/officialstatisti02miss",
                               "public_domain": 1, "notes": "regex extraction: dated station and movement sentences; places located with "
                                                           "data/places/geocoded.csv and USGS GNIS"}},
           "claims": claims}
    json.dump(doc, open(out_p, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    per_unit = Counter(c["unit"]["nps_code"] for c in claims)
    rep = [f"{k}: {v}" for k, v in stats.most_common()] + [f"units with claims: {len(per_unit)}; claims {len(claims)}", "", "sample:"] + sample
    open(rep_p, "w").write("\n".join(rep) + "\n")
    print("\n".join(rep[:min(14, len(stats))] + [rep[len(stats)]]))   # the totals line always (rebuild.sh greps it)


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("extract_state_stations")))
