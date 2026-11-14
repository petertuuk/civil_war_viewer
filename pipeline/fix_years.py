"""Correct years Dyer's text leaves out and the year tracker got wrong.

Dyer's rarely repeats the year, so extract_dyers carries it forward; one missed or extra year
change shifts every following item ('Battle of Gettysburg July 2-4' read as 1862). Well-dated
Wikidata events anchor the fix: an item whose name matches a Wikidata event and whose month and day
fall in that event's dates only after shifting by whole years votes for that shift.

A segment is a run of claims whose year was inferred (no year printed in the claim's text) and did
not change along the run. A segment is shifted when its votes agree: two or more votes for the same
shift, or one vote from a short event (7 days or less), a claim
that matches its event unshifted splits the run, so only the stretch where the year went wrong moves,
and the shifted stretch must stay in date order with the claims around it (45 days' slack) where
those claims' years are solid (printed, or confirmed by a match). Names after 'near' do not vote.
Only action claims vote (not 'duty at', 'stationed', 'moved to'), and a match needs every word of the Wikidata name (and at most two more), the same campaign/siege
wording, and a one-word
name shared by events in different years (Richmond, Columbia, Lexington) does not vote.
Claims with a printed year are never shifted, except a printed year out of date order that Wikidata contradicts
(misprints(), below).

Human review (data/dyers/year_decisions.jsonl, written by review_import.py): a run whose shift was refused for
date order is shifted anyway when the reviewer said 'shift', and left alone (logged) when they said 'keep'. Runs left
for review are written to <report>.review.jsonl with their claims and neighbours (review_cases.py makes cards of them).

Usage: python pipeline/fix_years.py claims_rules.jsonl wikidata.json out.jsonl [report.txt]
"""
import json, re, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from anchor_events import container_tag, load_wikidata, words_of  # noqa: E402
from resolve_events import iso  # noqa: E402

YEAR = re.compile(r"\b18[56]\d\b")
DATED = ("participated", "unit_at")
FEATURE = {"station", "creek", "river", "mill", "mills", "ford", "ferry", "bridge", "gap", "landing", "road",
           "church", "hill", "run", "roads", "springs", "bayou", "bluff", "bluffs", "island", "point", "mountain"}


def shift(s, k):
    if not s:
        return s
    return str(int(s[:4]) + k) + s[4:]


NOT_ACTION = re.compile(r"^\W*(?:duty|stationed|station|garrison|at|moved|march|marched|ordered|camp|post|"
                        r"provost|guard|guarding|engaged in|on|joined|left|mustered|reached|arrived|expedition to|near|"
                        r"in (?:the )?(?:district|dept|department|defences|defenses))\b", re.I)   # 'in the District of Baton Rouge': duty, not the battle


def votes_for(c, wd, index, ambiguous):
    if c.get("claim_type") != "participated":
        return []
    m = c.get("event_mention") or ""
    if NOT_ACTION.match(m) or re.search(r"\bfrom\b", m, re.I):
        return []                             # 'Scout from Pine Bluff': the origin, not the action
    w = words_of(m)
    if not w:
        return []
    out = []
    cand = set().union(*(index.get(x, set()) for x in w))
    for i in cand:
        e = wd[i]
        if not e["lo"] or not e["words"]:
            continue
        common = w & e["words"]
        if not e["words"] <= w or len(w - e["words"]) > 2:
            continue
        if container_tag(m) != container_tag(e["label"]) and not (container_tag(m) == "" and "Q831663" not in e["classes"]):
            continue
        if len(e["words"]) == 1:
            fl = FEATURE & set(re.findall(r"[a-z]+", (e["label"] or "").lower()))
            fm = FEATURE & set(re.findall(r"[a-z]+", m.lower()))
            if fl and fm and not fl & fm:
                continue                      # 'Thompson's Creek' is not 'Thompson's Station'
        if len(common) == 1 and next(iter(common)) in ambiguous:
            continue                          # Richmond, Columbia, Lexington: several events, several states
        hi = e["hi"] or e["lo"]
        span = (hi - e["lo"]).days
        if span > 120:
            continue
        for k in (0, 1, -1, 2, -2, 3, -3):
            d0 = iso(shift(c["date_start"], k))
            d1 = iso(shift(c.get("date_end") or c["date_start"], k), end=True) or d0
            if not d0 or not (1861 <= d0.year <= 1865):
                continue
            if d0 <= hi + timedelta(days=3) and d1 >= e["lo"] - timedelta(days=3):
                out.append((k, span, e["label"]))
                break
    return out


def misprints(u, idx, claims, wd, index, ambiguous, segs, log):
    """A printed year Dyer's got wrong ('"Mud March," January 20-24, 1865' for 1863, a misprint the NPS and Civil War
    Archive copies repeat): the narrative runs in date order, so a printed date later than the NEXT printed date
    (beyond 45 days' slack) is suspect. It is taken as a misprint, and moved with the stretch that carried its year,
    when one shift k puts the stretch back in order (after the printed date before it, before the next) and the
    stretch's Wikidata votes are all for k (at least one). Runs in place, before the segment pass."""
    slack = timedelta(days=45)
    order = [n for n in idx if claims[n].get("claim_type") in DATED and claims[n].get("date_start")]
    pr = [i for i, n in enumerate(order) if YEAR.search(claims[n].get("source_span") or "")]
    for a_, (pi, qi) in enumerate(zip(pr, pr[1:])):
        p, q = order[pi], order[qi]
        dp, dq = iso(claims[p]["date_start"]), iso(claims[q]["date_start"])
        if not dp or not dq or dp <= dq + slack:
            continue
        run = [p] + order[pi + 1:qi]
        prev = iso(claims[order[pr[a_ - 1]]]["date_start"]) if a_ > 0 else None
        votes = Counter(k for n in run for k, _, _ in votes_for(claims[n], wd, index, ambiguous)[:1])
        if len(votes) != 1 or 0 in votes:
            continue
        k = next(iter(votes))
        first, last = iso(shift(claims[p]["date_start"], k)), iso(shift(claims[run[-1]]["date_start"], k))
        if not first or not last or (prev and first + slack < prev) or last > dq + slack:
            continue
        note = f"Year corrected by {k:+d}: printed {claims[p]['date_start'][:4]} taken as a misprint (out of order with the next printed date; Wikidata agrees)"
        for n in run:
            c = claims[n]
            c["date_start"] = shift(c["date_start"], k)
            if c.get("date_end"):
                c["date_end"] = shift(c["date_end"], k)
            c["confidence"] = round(max(0.1, c.get("confidence", 0.5) - 0.05), 3)
            c["note"] = ((c.get("note") or "") + " " + note).strip()
        segs["misprinted year corrected"] += 1
        log.append(f"{u}: {len(run)} claims {note} ('{claims[p].get('event_mention')}')")


def main(src, wdp, dst, rep=None):
    wd = [e for e in load_wikidata(wdp)]
    index = defaultdict(set)
    for i, e in enumerate(wd):
        for x in e["words"]:
            index[x].add(i)
    # a one-word name shared by events in different years is ambiguous (Richmond 1862 Ky., 1864-65 Va.)
    ambiguous = {x for x, ii in index.items()
                 if len({wd[i]["lo"].year for i in ii if wd[i]["lo"]}) > 1}
    dates = {e["label"]: (str(e["lo"]), str(e["hi"] or e["lo"])) for e in wd if e["lo"]}
    decisions = {}
    dp = Path(dst).parent / "year_decisions.jsonl"
    if dp.exists():
        for l in open(dp, encoding="utf-8"):
            if l.strip():
                o = json.loads(l)
                decisions[(o["unit_id"], o["mention"], o["date"], o["shift"])] = o["decision"]
    review = []
    claims = [json.loads(l) for l in open(src, encoding="utf-8")]
    by_unit = defaultdict(list)
    for n, c in enumerate(claims):
        if c.get("claim_type") == "subordinate_to":
            continue                          # attachments come from their own list, not the service text
        if (c.get("claim_type") in DATED and c.get("date_start") and len(c["date_start"]) >= 7) or \
                YEAR.search(c.get("source_span") or ""):
            by_unit[c["unit_id"]].append(n)
    shifted, segs, log = 0, Counter(), []
    for u, idx in by_unit.items():
        misprints(u, idx, claims, wd, index, ambiguous, segs, log)
        seg, segments, prev_y = [], [], None
        solid = {n for n in idx if YEAR.search(claims[n].get("source_span") or "")}
        for n in idx:
            c = claims[n]
            y = (c.get("date_start") or "")[:4]
            printed = bool(YEAR.search(c.get("source_span") or ""))
            if printed or y != prev_y:
                if seg:
                    segments.append(seg)
                seg = []
            if not printed and c.get("claim_type") in DATED and c.get("date_start"):
                seg.append(n)
            prev_y = y
        if seg:
            segments.append(seg)
        for seg in segments:
            # votes per claim; a claim matching its event unshifted (vote 0) splits the run, so the fix
            # covers only the stretch where the year went wrong ('Battle of Fredericksburg December 12-15'
            # stays 1862 while '"Mud March" January 20-24' after a misprinted 'till April 27, 1862' moves)
            order = [n for n in idx if claims[n].get("claim_type") in DATED and claims[n].get("date_start")]
            runs, cur = [], []
            for n in seg:
                vs = votes_for(claims[n], wd, index, ambiguous)
                if any(k == 0 for k, _, _ in vs):
                    solid.add(n)
                    if cur:
                        runs.append(cur)
                    cur = []
                    segs["claims matching unshifted"] += 1
                    continue
                cur.append((n, vs[:1]))
            if cur:
                runs.append(cur)
            for run in runs:
                v, short, why = Counter(), Counter(), {}
                for n, vs in run:
                    for k, span, lab in vs:
                        v[k] += 1
                        short[k] += span <= 7
                        why.setdefault(k, (claims[n].get("event_mention"), lab))
                if not v:
                    continue
                k, cnt = v.most_common(1)[0]
                if len(v) > 1 or not (cnt >= 2 or short[k] >= 1):
                    segs["unsure"] += 1
                    continue
                # the shifted run must still sit in order between its neighbours ('Near Chancellorsville May 4'
                # after 'Demonstration on the Rapidan February 6-7, 1864' is the 1864 fight, not the 1863 battle)
                first, last = run[0][0], run[-1][0]
                pos0, pos1 = order.index(first), order.index(last)
                # only neighbours whose year is solid count: printed in the text, or confirmed by a match
                before = [claims[x]["date_start"] for x in order[:pos0] if x in solid][-1:]
                after = [claims[x]["date_start"] for x in order[pos1 + 1:] if x in solid][:1]
                a0 = iso(shift(claims[first]["date_start"], k))
                a1 = iso(shift(claims[last]["date_start"], k))
                slack = timedelta(days=45)
                key = (u, claims[first].get("event_mention"), claims[first]["date_start"], k)
                dec = decisions.get(key)
                if dec == "keep":
                    segs["kept by review"] += 1
                    log.append(f"{u}: KEPT by review {k:+d} ({key[1]} {key[2]})")
                    continue
                if dec != "shift" and ((before and iso(before[0]) and a0 + slack < iso(before[0])) or
                                       (after and iso(after[0]) and a1 > iso(after[0]) + slack)):
                    segs["out of order after shift"] += 1
                    review.append({"unit_id": u, "shift": k, "mention": key[1], "date": key[2],
                                   "why": {"mention": why[k][0], "event": why[k][1], "dates": dates.get(why[k][1])},
                                   "votes": dict(v), "before": before, "after": after,
                                   "claims": [{"mention": claims[n].get("event_mention"), "start": claims[n]["date_start"],
                                               "end": claims[n].get("date_end"), "span": claims[n].get("source_span")}
                                              for n, _ in run]})
                    log.append(f"{u}: NOT shifted {k:+d} ({claims[first].get('event_mention')} {claims[first]['date_start']}; before {before} after {after})")
                    continue
                segs["shifted"] += 1
                note = f"Year corrected by {k:+d}: '{why[k][0]}' matches {why[k][1]}" + (" (human review)" if dec == "shift" else "")
                runset = {n for n, _ in run}
                old_ends = {claims[n].get("date_end") or claims[n]["date_start"]: shift(claims[n].get("date_end") or claims[n]["date_start"], k)
                            for n in runset}
                for n, _ in run:
                    c = claims[n]
                    c["date_start"] = shift(c["date_start"], k)
                    if c.get("date_end"):
                        c["date_end"] = shift(c["date_end"], k)
                    c["confidence"] = round(max(0.1, c.get("confidence", 0.5) - 0.05), 3)
                    c["note"] = ((c.get("note") or "") + " " + note).strip()
                    shifted += 1
                # a stay right after the run took its start from the run's (wrong) last date and its end from a printed
                # year ('... Fort Wagner ... September 7. Operations against Charleston and duty at Folly Island till
                # April, 1864' began 1862-09-07 when the run moved to 1863): move that start with the run
                for n2, c2 in enumerate(claims):
                    if n2 in runset or c2.get("unit_id") != u or not c2.get("date_start") or not c2.get("date_end"):
                        continue
                    ns = old_ends.get(c2["date_start"])
                    if ns and ns <= c2["date_end"] and c2["date_start"] < ns:
                        c2["date_start"] = ns
                        c2["note"] = ((c2.get("note") or "") + f" start moved with the corrected run ({k:+d})").strip()
                log.append(f"{u}: {len(run)} claims {note}")
    with open(dst, "w", encoding="utf-8") as f:
        for c in claims:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    rpt = [f"segments: {dict(segs)}", f"claims shifted: {shifted}", ""] + log
    if rep:
        open(rep, "w", encoding="utf-8").write("\n".join(rpt) + "\n")
        with open(Path(rep).with_suffix(".review.jsonl"), "w", encoding="utf-8") as f:
            for r in review:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\n".join(rpt[:3]))


if __name__ == "__main__":
    main(*sys.argv[1:])
