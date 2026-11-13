"""Turn Official Records organization placements into claims.

Usage:
  python3 pipeline/or_to_claims.py data/or/placements.jsonl data/or/tables.jsonl data/scores/dyer_to_nps.csv \
      data/events data/or/claims_or.jsonl

Unit identity: Dyer's unit_id where the NPS code links to one (Union), else "nps:<code>",
else "or:<side>:<printed name>" (unit_mention kept for later resolution).
Claims (same field style as Dyer's claims_rules.jsonl):
  subordinate_to  unit -> "Brigade, Division, Corps, <army from heading>", dated to the table
  commanded       one per commander listed for the unit, with order (several = change of command)
  participated    only for tables about a battle or campaign; linked to an event_id when one matches
Confidence: 0.9 heading-dated; 0.75 context-dated; 0.5 two-column scramble or undated.
"""
import nps_links, collections, csv, json, re, sys
from datetime import date, timedelta
from pathlib import Path

EVENT_PHRASE = re.compile(r"(?:at the battles? of|at the|during the|in the|engaged in the|engaged at|operations (?:before|against|around|about)|"
                          r"engagements? (?:around|at|near)|siege of|before)\s+(.+?)(?:[,;]\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d|"
                          r"\d{1,2}[-–]|18\d\d)|\.\s*$|$)", re.I)
STOP = set("battle battles of the at and near on in to engagement campaign operations army forces union confederate "
           "troops commanded general corps division department district pa va md tenn ga miss ala ky la mo ark".split())


def d(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def words(s):
    s = (s or "").lower().replace("'", "").replace("’", "")
    s = s.replace("spottsylvania", "spotsylvania").replace("shiloli", "shiloh").replace("jshiloh", "shiloh")
    return {w for w in re.findall(r"[a-z]{4,}", s) if w not in STOP}


def main(pl_path, tables_path, d2n_path, events_dir, out_path):
    _, code2dyer, _ = nps_links.load(d2n_path)
    tables = {f"{t['book']}:{t['start']}": t for t in map(json.loads, open(tables_path, encoding="utf-8"))}
    events = [json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")]
    ev_by_year = collections.defaultdict(list)
    for e in events:
        s, x = d(e["date_start"]), d(e["date_end"]) or d(e["date_start"])
        if s and e["regiments"] >= 3 or e.get("source") == "wikidata_parent":
            if s:
                for y in range(s.year, (x or s).year + 1):
                    ev_by_year[y].append((s, x or s, words(e["name"]) | words(e.get("dyer_name")), e))

    first = {}
    for r in map(json.loads, open(pl_path, encoding="utf-8")):
        first.setdefault(r["table_id"], r)
    # which tables describe a battle or campaign, and which event they are
    table_event, stats = {}, collections.Counter()
    # hand-checked overrides for the main battle and campaign tables (dates garbled or missing in the scan)
    overrides = {}
    ov_path = Path(tables_path).parent / "table_overrides.psv"
    if ov_path.exists():
        by_name = {}
        for e in events:
            by_name.setdefault(e["name"].lower(), e)
        for line in open(ov_path, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            tid_, s_, e_, ev_, note_ = line.rstrip("\n").split("|")
            e = by_name.get(ev_.lower())
            overrides[tid_] = (s_, e_, ev_, e["event_id"] if e else None)
            stats["overrides" if e else "overrides with no matching event"] += 1
            if not e:
                print("override event not found:", ev_)
    for tid, t in tables.items():
        if tid in overrides:
            s_, e_, ev_, eid_ = overrides[tid]
            table_event[tid] = (ev_, eid_)
            continue
        h = t["heading"]
        if re.search(r"not\s+em[-¬\s]*ployed|Proceedings|\.\s*\d{3}\b", h, re.I):
            continue                                       # "not employed in the Atlanta Campaign"
        m = EVENT_PHRASE.search(h)
        keyword = bool(m) and bool(re.search(r"battle|engag|campaign|siege|operations|during|expedition", h, re.I))
        ranged = bool(re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*[-–]\s*\d{1,2}\b"
                               r"|\d{1,2}\s*[-–]\s*\d{1,2},?\s*18\d\d|[1l][8S][\dS(]{2,3}\s*[-–]\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                               r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\s*(?:to|[-–])\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", h))
        if not (keyword or ranged):
            continue                                       # a single-date return: organization snapshot, not a battle
        phrase = m.group(1).strip() if keyword else h      # no "at the battle of": match on dates only
        stats["event tables"] += 1
        f0 = first.get(tid)
        s, x = (d(f0["date_start"]), d(f0["date_end"]) or d(f0["date_start"])) if f0 else (None, None)
        if not s:
            table_event[tid] = (phrase, None); stats["event tables without a usable date"] += 1; continue
        pw = words(phrase) if keyword else set()
        best = None
        span = max(1, (x - s).days + 1)
        for y in {s.year, x.year}:
            for es, ee, ew, e in ev_by_year.get(y, []):
                if not (es <= x + timedelta(days=10) and ee >= s - timedelta(days=10)):
                    continue
                ov = max(0, (min(ee, x) - max(es, s)).days + 1) / span
                named = len(pw & ew)
                if not named and not (ov >= 0.5 and e.get("kind") in ("battle", "campaign", "siege", "operations")
                                      and e["regiments"] >= 50 and ee - es <= (x - s) + timedelta(days=10)):
                    continue
                score = (named, round(ov, 1), bool(e.get("wikidata")), e["regiments"])
                if best is None or score > best[0]:
                    best = (score, e)
        table_event[tid] = (phrase, best[1]["event_id"] if best else None)
        stats["event tables linked to an event" if best else "event tables not linked"] += 1

    out = open(out_path, "w", encoding="utf-8")
    n = collections.Counter()
    for r in map(json.loads, open(pl_path, encoding="utf-8")):
        t = tables.get(r["table_id"], {})
        if r["table_id"] in overrides:
            r["date_start"], r["date_end"] = overrides[r["table_id"]][:2]
            t = dict(t, date_source="heading")              # hand-checked
        code = nps_links.resolve_ambiguous(r.get("unit_code")) or ""
        # a namesake chosen here (the one field regiment) is a pick too: tagged ':namesake' like resolve_namesakes.py's,
        # so the next build's namesake evidence does not count it (untagged, it made picks flip between builds)
        picked = (r.get("unit_code") or "").startswith("AMBIGUOUS:") and bool(code)
        if not code:
            code = nps_links.alias_code(r["unit"], r["side"]) or ""      # data/manual/unit_aliases.psv
        bat = nps_links.battery_from_code(code, r.get("portion"), code2dyer) if code else None
        if bat:
            uid = bat                                       # the lettered battery's own Dyer's record
            r = dict(r, portion=None)
        elif code and not code.startswith("AMB"):
            uid = code2dyer.get(code) or f"nps:{code}"
        else:
            uid = None
        conf = 0.9 if (t.get("date_source") or "") == "heading" else 0.75
        if r.get("confidence") == "low" or not r["date_start"]:
            conf = 0.5
        base = {"unit_id": uid, "unit_mention": r["unit"], "side": r["side"], "source": "OR Ser. I",
                "source_ref": f"{t.get('volume')} ({r['table_id']})", "source_span": r["heading"],
                "date_start": r["date_start"], "date_end": r["date_end"], "date_precision": "day" if r["date_start"] else None,
                "confidence": conf, "extracted_by": "regex:or_org_v1" + (":namesake" if r.get("namesake_note") or picked else "")}
        if r.get("portion"):
            base["portion"] = r["portion"]                    # e.g. "battery E" of an artillery regiment
        if r.get("consolidated_from"):
            base["note"] = f"consolidated: {r['consolidated_from']}"
        parent = ", ".join(x for x in (r["brigade"], r["division"], r["corps"]) if x)
        if parent:
            out.write(json.dumps(dict(base, claim_type="subordinate_to", parent_mention=parent,
                                      parent_path={"brigade": r["brigade"], "division": r["division"], "corps": r["corps"],
                                                   "army_heading": r["heading"][:120]}), ensure_ascii=False) + "\n")
            n["subordinate_to"] += 1
        for i, cmd in enumerate(r["commanders"]):
            out.write(json.dumps(dict(base, claim_type="commanded", person_mention=cmd, order=i,
                                      note=(base.get("note", "") + " several commanders listed: change of command during the period").strip()
                                      if len(r["commanders"]) > 1 else base.get("note")), ensure_ascii=False) + "\n")
            n["commanded"] += 1
        if r["table_id"] in table_event:
            phrase, eid = table_event[r["table_id"]]
            out.write(json.dumps(dict(base, claim_type="participated", event_mention=phrase, event_id=eid), ensure_ascii=False) + "\n")
            n["participated"] += 1
            n["participated linked" if eid else "participated unlinked"] += 1
        n["placements with a unit id" if uid else "placements without a unit id"] += 1
    out.close()
    print("tables:", dict(stats))
    print("claims:", dict(n))


if __name__ == "__main__":
    main(*sys.argv[1:6])
