"""Find "Organization of ..." tables in Official Records Series I text files.

Usage:
  python3 pipeline/locate_or_tables.py <dir of warofrebellion*unit.txt> <volumes.json> data/or/tables.jsonl

A heading counts as a table when the next 40 lines hold command structure
(CORPS / DIVISION / Brigade headers and rank lines). The table ends at the next
document number ("No. 425."), the next "Organization of", or a return/report heading.
Output rows: book, volume, part, start/end line, heading, date text, side guess, line count.
"""
import json, re, sys
from pathlib import Path

ROW = re.compile(r"^\d+(st|d|nd|rd|th)\b|Battery|Artillery|Cavalry|Infantry|Volunteers|Legion|Battalion|^(Lieut|Capt|Col|Maj|Brig)\.")
USA_SUFFIX = re.compile(r"\b(U|TJ|JJ|IT)\.?\s*[S8]\.?\s*(Army|Volunteers|Navy|Forces)", re.I)
NORTH = re.compile(r"^\d+(?:st|d|nd|rd|th)\s+(Pennsylvania|New York|Ohio|Indiana|Illinois|Michigan|Wisconsin|Minnesota|Iowa|"
                   r"Massachusetts|Maine|New Hampshire|Vermont|Connecticut|Rhode Island|New Jersey|Kansas|U\.? ?S\.? Colored)")
SOUTH = re.compile(r"^\d+(?:st|d|nd|rd|th)\s+(Georgia|Alabama|Mississippi|South Carolina|Louisiana|Texas|Florida|Arkansas|"
                   r"North Carolina|Virginia|Tennessee)")
CSA_SUFFIX = re.compile(r"\b[CG]\.?\s*[S8]\.?\s*Army|C\.\s*S\.\s*A\b", re.I)
FULLDATE = re.compile(r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
                      r"\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?,\s*18[6][0-5])")
HEAD = re.compile(r"^(?:No\.\s*\d+\.\s*[—–-]+\s*)?(?:(Organization|Organisation)\s+(of|and)\b|Troops\s+in\s+(?:the|district)\b)", re.I)
STRUCT = re.compile(r"(CORPS|DIVISION|BRIGADE|Brigade\.?$|Battalion\.?$|^Brig\. Gen\.|^Maj\. Gen\.|^Col\. )")
END = re.compile(r"^(No\. \d+\.(?!\s*[—–-]+\s*Organi)|Organization of|Organisation of|Troops\s+in\s+(?:the|district)\b|Return of|Abstract from|RETURN|REPORTS?\b|Report of|"
                 r"INDEX\b|CORRESPONDENCE|Summary of|Recapitulation)", re.I)
CSA_HINT = re.compile(r"Confederate|Northern Virginia|Army of Tennessee\b|Army of the Valley|Department of South Carolina, "
                      r"Georgia|Army of Mississippi|Trans-Mississippi Department|Army of the Kanawha|forces under .*(Lee|Bragg|Johnston|"
                      r"Hood|Beauregard|Pemberton|Kirby Smith|Price|Van Dorn|Forrest|Longstreet|Early|Jackson|Taylor|Magruder|Hardee)", re.I)
USA_HINT = re.compile(r"Union|Federal|Army of the Potomac|Army of the Cumberland|Army of the Tennessee\b|Army of the Ohio|"
                      r"Army of the James|Army of the Gulf|Department of the Gulf|Army of Virginia|Army of the Shenandoah|"
                      r"Military Division|Army of the Mississippi|Department of the (Cumberland|Ohio|Tennessee|Missouri|South|"
                      r"Gulf|Susquehanna|Pennsylvania|Washington|West Virginia)|(Grant|Sherman|Meade|McClellan|Rosecrans|Thomas|"
                      r"Banks|Burnside|Hooker|Pope|Buell|Halleck|Sheridan|Butler|Canby|Schofield|Curtis|Steele)", re.I)


def main(txt_dir, vol_json, out):
    vols = json.load(open(vol_json))
    rows = []
    for p in sorted(Path(txt_dir).glob("warofrebellion*unit.txt")):
        book = p.stem
        L = [l.strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()]
        n = len(L)
        for i, l in enumerate(L):
            if not HEAD.match(l):
                continue
            # heading = this line plus continuation lines until a line ends with '.' or holds a date
            j, head = i, l
            while j + 1 < n and j - i < 4 and not re.search(r"18\d\d\.?\s*[*†]?\s*$|18\d\d[;:]", head) \
                    and not (re.search(r"[.*]\s*$", head) and not re.search(r"\b[A-Z]\.\s*$|Gen\s*\.\s*$|Maj\.\s*$|Col\.\s*$|,\s*$", head)) \
                    and not re.fullmatch(r"[A-Z0-9 .,'’-]{6,}", L[j + 1] or "x"):
                j += 1
                if L[j]:
                    head += " " + L[j]
            win = [x for x in L[j + 1:j + 61] if x]
            hits = sum(1 for x in win if STRUCT.search(x) or ROW.search(x))
            if hits < 6 or re.search(r"\.\s*\d{1,4}\s*$|\.\.\.\.", head):    # index / contents lines end in page numbers
                continue
            k, last_good = j + 1, j + 1
            while k < n and k - j < 4000 and not END.match(L[k]):
                x = L[k]
                if re.search(r"\bSee\b.{0,40}\bTroops\b|^I am,|^Very respectfully|^Respectfully|your obedient servant|"
                             r"^(General|Special|Field) Orders,? No|^(Sir|General|Colonel): ?$|^Hdqrs\.", x):
                    break                                   # back-of-book index or correspondence
                if x and (STRUCT.search(x) or ROW.search(x) or (len(x) < 60 and not re.search(r"[a-z]{3,} [a-z]{3,} [a-z]{3,} [a-z]{3,}", x))):
                    last_good = k
                elif x and k - last_good > 30:
                    break                                   # 30 lines of prose: the table is over
                k += 1
            k = min(k, last_good + 1)
            look = head + " " + " ".join(x for x in L[j + 1:j + 4] if x)     # date or 'U. S. Army' can sit on the next lines
            date = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|December|"
                             r"Jan\.|Feb\.|Mar\.|Apr\.|Aug\.|Sept\.|Oct\.|Nov\.|Dec\.)[^.;]*?\d{1,2}(?:[-–, ]+(?:\w+\.? )?\d{1,2})*,?\s*18\d\d)", look)
            body = L[j + 1:k]
            nn, ss = sum(1 for x in body if NORTH.match(x)), sum(1 for x in body if SOUTH.match(x))
            if nn + ss >= 3 and max(nn, ss) >= 0.8 * (nn + ss):
                side = "Union" if nn > ss else "Confederate"          # the units decide (VA/TN/NC count as South)
            elif USA_SUFFIX.search(look) and not CSA_SUFFIX.search(look):
                side = "Union"
            elif CSA_SUFFIX.search(look) and not USA_SUFFIX.search(look):
                side = "Confederate"
            else:
                side = "Confederate" if CSA_HINT.search(look) and not USA_HINT.search(look) else \
                       ("Union" if USA_HINT.search(look) and not CSA_HINT.search(look) else "?")
            date_source = "heading" if date else None
            if not date:                                    # nearest full date before the table (document date)
                for b in range(i - 1, max(0, i - 800), -1):
                    dm = FULLDATE.search(L[b])
                    if dm:
                        date, date_source = dm, f"context:{i - b}"
                        break
            if k - i < 12 or re.match(r"^(organi[sz]ation\s+(of|and)|troops\s+in)\b", l, re.I) and not l[0].isupper() \
                    or re.search(r"\b\d{2,4},\d{2,4}\b|\s\d{3,4}\s+[A-Z][a-z]+, [A-Z]", head):
                continue                                   # contents entry (no body) or index line
            if rows and rows[-1]["book"] == book and re.search(r"Continued", head, re.I) and i - rows[-1]["end"] < 400:
                rows[-1]["end"] = k; rows[-1]["lines"] = k - rows[-1]["start"] + 1   # "— Continued." page heading
                rows[-1]["continued"] = rows[-1].get("continued", 0) + 1
                continue
            rows.append({"book": book, "volume": vols.get(book), "start": i + 1, "end": k, "lines": k - i,
                         "heading": head[:240], "date_text": date.group(1) if date else "", "date_source": date_source, "side": side,
                         "north_units": nn, "south_units": ss})
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    import collections
    print(f"tables: {len(rows)} in {len({r['book'] for r in rows})} books; lines total {sum(r['lines'] for r in rows)}")
    print("side guess:", collections.Counter(r["side"] for r in rows))
    print("with a date in the heading:", sum(1 for r in rows if r["date_text"]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
