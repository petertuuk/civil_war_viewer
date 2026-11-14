"""Turn answers from the review page (artifact "Dyer's Review Queue", db collection 'decisions') into the
pipeline's decision files.

usage: python pipeline/review_import.py data/review/decisions.jsonl
  (decisions.jsonl: one answer per line, as the page stores it; Claude dumps it from the artifact's db)

  ocr  answer reading/other -> data/dyers/flag_decisions.jsonl {unit_id, ocr, before, printed, source}
       (vote_witnesses.py: keyed by unit, OCR reading and the words before it)
  year answer keep/shift    -> data/dyers/year_decisions.jsonl {unit_id, mention, date, shift, decision}
       (fix_years.py)
  can't tell: no decision; kept in decisions.jsonl and counted, the case stays in the queue with its note.
Entries are replaced by key, so answering again (or changing an answer) overwrites the earlier one.
Then rebuild from the 'units' stage (OCR) or the 'dyers' stage (years) on.
"""
import json, sys
from pathlib import Path

SRC = "human review (Dyer's Review Queue)"


def load(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if Path(p).exists() else []


def save(p, rows):
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(dec_p, root="."):
    root = Path(root)
    D = load(dec_p)
    fp, yp = root / "data/dyers/flag_decisions.jsonl", root / "data/dyers/year_decisions.jsonl"
    flags, years = load(fp), load(yp)
    fk = lambda r: (r["unit_id"], r["ocr"], " ".join((r.get("before") or "").split()[-4:])) if "before" in r else None
    yk = lambda r: (r["unit_id"], r["mention"], r["date"], r["shift"])
    fidx = {fk(r): i for i, r in enumerate(flags) if fk(r)}
    yidx = {yk(r): i for i, r in enumerate(years)}
    n = {"ocr": 0, "year": 0, "cant_tell": 0, "removed": 0}
    for d in D:
        if d.get("answer") == "cant_tell":
            n["cant_tell"] += 1
            continue
        if d["kind"] == "ocr":
            r = {"unit_id": d["unit_id"], "ocr": d["ocr"], "before": d["before"], "printed": d["printed"] or "",
                 "source": SRC, "case_id": d["case_id"], "at": d.get("at")}
            if d.get("note"):
                r["note"] = d["note"]
            k = fk(r)
            if k in fidx: flags[fidx[k]] = r
            else: fidx[k] = len(flags); flags.append(r)
            n["ocr"] += 1
        elif d["kind"] == "year" and d["answer"] in ("keep", "shift"):
            r = {"unit_id": d["unit_id"], "mention": d["mention"], "date": d["date"], "shift": d["shift"],
                 "decision": d["answer"], "source": SRC, "case_id": d["case_id"], "at": d.get("at")}
            if d.get("note"):
                r["note"] = d["note"]
            k = yk(r)
            if k in yidx: years[yidx[k]] = r
            else: yidx[k] = len(years); years.append(r)
            n["year"] += 1
    # an answer cleared on the page: drop the decision this script wrote for it earlier
    live = {d["case_id"] for d in D if d.get("answer") != "cant_tell"}
    keep = lambda r: r.get("source") != SRC or r.get("case_id") in live
    n["removed"] = sum(not keep(r) for r in flags + years)
    save(fp, [r for r in flags if keep(r)]); save(yp, [r for r in years if keep(r)])
    print(f"review answers: {len(D)}; OCR decisions {n['ocr']}, year decisions {n['year']}, "
          f"can't tell {n['cant_tell']}, withdrawn {n['removed']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
