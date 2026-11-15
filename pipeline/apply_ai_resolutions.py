"""Apply AI (historical-knowledge) resolutions to canonical event clusters.

Usage:
  python3 pipeline/apply_ai_resolutions.py data/dyers/canonical_events.jsonl \
      data/wikidata/wikidata_civil_war_events.json data/ai data/ai

Reads every data/ai/event_resolutions_*.psv (pipe-separated, '#' comments):
  cluster_id|kind|canonical|wd|wd_try|parent|lat|lon|date_fix|conf|note
  wd      = label in the local Wikidata file for the SAME event (gets its QID)
  wd_try  = label expected in Wikidata but missing locally (retry after a broader pull)
  parent  = containing campaign/battle (label, local Wikidata if possible)
  lat/lon = approximate AI coordinates, used only when no Wikidata coords
Writes resolved_events.jsonl, review_queue.csv, ai_report.txt.
"""
from cwv import paths
import csv, glob, json, sys
from datetime import date
from pathlib import Path

FIELDS = "cluster_id kind canonical wd wd_try parent lat lon date_fix conf note".split()
NON_EVENT = {"admin"}


def load_wd(path):
    by_label = {}
    for r in json.load(open(path, encoding="utf-8")):
        q = r["b"].rsplit("/", 1)[1]
        lab = r.get("label")
        if not lab:
            continue
        rec = by_label.setdefault(lab.lower(), {})
        if q not in rec:
            lat = lon = None
            if r.get("coord", "").startswith("Point("):
                lon, lat = map(float, r["coord"][6:-1].split())
            rec[q] = {"qid": q, "label": lab, "lat": lat, "lon": lon,
                      "date": ((r.get("start") if int(r.get("start_prec") or 0) >= int(r.get("pit_prec") or 0)
                                else r.get("pit")) or r.get("pit") or "")[:10],
                      "prec": max(int(r.get("pit_prec") or 0), int(r.get("start_prec") or 0))}
    return by_label


def d(s):
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def rekey(keys_path, clusters):
    """The .psv files name clusters by the ids they had when written (snapshot in cluster_keys_v1.jsonl).
    Cluster ids are reassigned on every re-run, so map each old cluster to today's by name/variants + dates."""
    from datetime import date as _d
    def day(s):
        try: return _d.fromisoformat((s or "")[:10]) if len(s or "") >= 10 else None
        except ValueError: return None
    by_name = {}
    for c in clusters.values():
        for v in {c["name"]} | set(c.get("variants") or []):
            by_name.setdefault(v.lower(), []).append(c)
    m, how = {}, {}
    for l in open(keys_path, encoding="utf-8"):
        o = json.loads(l); od = day(o.get("date_start"))
        best = None
        for v in [o["name"]] + list(o.get("variants") or []):
            for c in by_name.get(v.lower(), []):
                cd = day(c.get("date_start"))
                gap = abs((cd - od).days) if cd and od else (0 if c.get("date_start") == o.get("date_start") else 999)
                primary = v == o["name"] and c["name"] == o["name"]
                om, cm = o.get("mentions", 1) or 1, c.get("mentions", 1) or 1
                similar = max(om, cm) <= 2 * min(om, cm)
                if not (gap <= 31 or primary and similar and gap <= 90): continue
                score = (not primary, not similar, gap)
                if best is None or score < best[0]: best = (score, c["cluster_id"])
        if not best:   # names repaired by the OCR clean-up ('TJtoy Creek' -> 'Utoy Creek')
            import difflib
            for c in clusters.values():
                cd = day(c.get("date_start"))
                if cd and od and abs((cd - od).days) <= 7 and \
                        difflib.SequenceMatcher(None, o["name"].lower(), c["name"].lower()).ratio() >= 0.8:
                    score = ((abs((cd - od).days)), True, -c.get("mentions", 0))
                    if best is None or score < best[0]: best = (score, c["cluster_id"])
        if best:
            m[o["cluster_id"]] = best[1]; how["matched"] = how.get("matched", 0) + 1
        else:
            how["unmatched"] = how.get("unmatched", 0) + 1
    return m, how


def main(events_path, wd_path, res_dir, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    clusters = {}
    for l in open(events_path, encoding="utf-8"):
        c = json.loads(l); clusters[c["cluster_id"]] = c
    wd = load_wd(wd_path)
    res = []
    for p in sorted(glob.glob(str(Path(res_dir) / "event_resolutions_*.psv"))):
        for line in open(p, encoding="utf-8"):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("|")
            assert len(parts) == len(FIELDS), (p, line)
            res.append(dict(zip(FIELDS, parts)))
    keys = Path(res_dir) / "cluster_keys_v1.jsonl"
    if keys.exists():
        idmap, how = rekey(keys, clusters)
        moved = 0
        import re as _re
        def _sub(m):
            return idmap.get(m.group(0), "unmatched-" + m.group(0))
        for r in res:                        # notes cite clusters too ('Same as cl02343')
            for f in ("note", "parent"):
                r[f] = _re.sub(r"\bcl\d{5}\b", _sub, r[f])
        # since campaign/siege clusters split from same-named battles (anchor_events.container_tag), a row whose
        # kind disagrees with its mapped cluster's tag moves to the sibling cluster with the same words and the right tag
        sib = {}
        for c in clusters.values():
            sib.setdefault(tuple(c.get("words") or ()), []).append(c)
        want = lambda kind: "campaign" if kind == "campaign" else "siege" if kind == "siege" else ""
        for r in res:
            new = idmap.get(r["cluster_id"])
            if new and new in clusters and (clusters[new].get("tag") or "") != want(r["kind"]):
                c0 = clusters[new]
                alt = [c for c in sib.get(tuple(c0.get("words") or ()), []) if (c.get("tag") or "") == want(r["kind"])
                       and abs(int(c["date_start"][:4]) - int(c0["date_start"][:4])) <= 1]
                if alt:
                    idmap = dict(idmap); idmap[r["cluster_id"] + "#" + r["kind"]] = max(alt, key=lambda c: c["regiments"])["cluster_id"]
                    r["_alt"] = r["cluster_id"] + "#" + r["kind"]
        for r in res:
            new = idmap.get(r.pop("_alt", None) or r["cluster_id"])
            r["cluster_id_v1"] = r["cluster_id"]
            if new:
                moved += new != r["cluster_id"]; r["cluster_id"] = new
            else:
                r["cluster_id"] = "unmatched:" + r["cluster_id"]
        print(f"re-keyed AI resolutions via {keys.name}: {how}; ids changed for {moved} of {len(res)} rows")

    problems, rows, overrides = [], [], []
    for r in res:
        c = clusters.get(r["cluster_id"])
        if not c:
            problems.append(f"{r['cluster_id']}: cluster not found"); continue
        if r["wd"] == "-":
            r["wd"] = ""
            detach = True                       # the rules anchor is wrong for this cluster
        else:
            detach = False
            if c.get("wikidata") and not r["wd"]:
                problems.append(f"{r['cluster_id']}: already anchored by rules ({c['wikidata_label']}); "
                                f"put its label in wd, or '-' to detach")
            elif c.get("wikidata") and r["wd"].lower() != (c.get("wikidata_label") or "").lower():
                detach = True                   # explicit AI label overrides the rules anchor
                overrides.append(f"{r['cluster_id']}: rules {c['wikidata_label']} -> AI {r['wd']}")
        start = r["date_fix"].split("..")[0] if r["date_fix"] else c["date_start"]
        o = {"cluster_id": r["cluster_id"], "dyer_name": c["name"], "regiments": c["regiments"],
             "mentions": c["mentions"], "date_start": start,
             "date_end": r["date_fix"].split("..")[-1] if r["date_fix"] else c["date_end"],
             "kind": r["kind"], "canonical": r["canonical"], "confidence": r["conf"],
             "note": r["note"], "source": "ai_knowledge"}
        if detach:
            o["detach_rules_anchor"] = True
        if r["wd"]:
            hits = wd.get(r["wd"].lower(), {})
            if not hits:
                problems.append(f"{r['cluster_id']}: wd label not in local file: {r['wd']}")
            else:
                if len(hits) > 1:
                    # pick the one whose date is closest to the cluster's
                    hits = sorted(hits.values(), key=lambda h: abs((d(h["date"]) or date(1863,1,1)) - (d(start) or date(1863,1,1))))
                else:
                    hits = list(hits.values())
                h = hits[0]
                gap = abs(((d(h["date"]) or d(start)) - d(start)).days) if d(start) else 0
                if gap > 45 and h["prec"] >= 11:  # only day-precision dates are comparable
                    problems.append(f"{r['cluster_id']}: {r['wd']} dated {h['date']} vs cluster {start} ({gap} days)")
                o.update(wikidata=h["qid"], wikidata_label=h["label"], wd_date=h["date"])
                if h["lat"] is not None:
                    o.update(lat=h["lat"], lon=h["lon"], coord_source="wikidata")
        if r["wd_try"]:
            o["wikidata_try"] = r["wd_try"]
        if r["parent"]:
            o["parent"] = r["parent"]
            ph = wd.get(r["parent"].lower())
            if ph:
                o["parent_wikidata"] = sorted(ph)[0]
        if "lat" not in o and r["lat"]:
            o.update(lat=float(r["lat"]), lon=float(r["lon"]), coord_source="ai_approx")
        rows.append(o)

    with open(out / "resolved_events.jsonl", "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    with open(out / "review_queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cluster_id", "regiments", "dates", "dyer_name", "kind", "canonical",
                    "wikidata", "parent", "coords", "confidence", "note"])
        order = {"low": 0, "med": 1, "high": 2}
        for o in sorted(rows, key=lambda o: (order.get(o["confidence"], 0), -o["regiments"])):
            w.writerow([o["cluster_id"], o["regiments"], f"{o['date_start']}..{o['date_end']}",
                        o["dyer_name"], o["kind"], o["canonical"],
                        o.get("wikidata_label", ""), o.get("parent", ""),
                        o.get("coord_source", ""), o["confidence"], o["note"]])

    allc = list(clusters.values())
    tot = sum(c["mentions"] for c in allc)
    resolved = {o["cluster_id"]: o for o in rows}
    def pct(n): return f"{100*n/tot:.0f}%"
    wd_before = sum(c["mentions"] for c in allc if c.get("wikidata"))
    wd_after = wd_before + sum(o["mentions"] for o in rows if o.get("wikidata"))
    xy_before = sum(c["mentions"] for c in allc if c.get("lat") is not None)
    xy_after = xy_before + sum(o["mentions"] for o in rows if o.get("lat") is not None
                               and clusters[o["cluster_id"]].get("lat") is None)
    named = sum(c["mentions"] for c in allc if c.get("wikidata") or c.get("dyer_index_event")
                or c["cluster_id"] in resolved)
    big = [c for c in allc if c["regiments"] >= 20]
    big_xy = sum(1 for c in big if c.get("lat") is not None
                 or resolved.get(c["cluster_id"], {}).get("lat") is not None)
    big_ok = sum(1 for c in big if c.get("wikidata") or c["cluster_id"] in resolved)
    kinds = {}
    for o in rows:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    rep = [
        f"AI resolutions applied: {len(rows)} clusters, {sum(o['mentions'] for o in rows)} mentions",
        f"Confidence: " + ", ".join(f"{k} {sum(1 for o in rows if o['confidence']==k)}" for k in ("high", "med", "low")),
        f"Kinds: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])),
        "",
        f"Mentions anchored to Wikidata (same event): {pct(wd_before)} -> {pct(wd_after)}",
        f"Mentions with coordinates: {pct(xy_before)} -> {pct(xy_after)} (AI approx coords flagged coord_source=ai_approx)",
        f"Mentions with any identification (Wikidata, Dyer index or AI): {pct(named)}",
        f"Clusters with 20+ regiments identified: {big_ok} of {len(big)}; with coordinates: {big_xy} of {len(big)}",
        f"Linked to a parent campaign/battle: {sum(1 for o in rows if o.get('parent'))}; parent found in local Wikidata: {sum(1 for o in rows if o.get('parent_wikidata'))}",
        f"Labels to retry after a broader Wikidata pull (wd_try): {sum(1 for o in rows if o.get('wikidata_try'))}",
        "",
        f"Overrides of rules anchors ({len(overrides)}):",
    ] + ["  " + p for p in overrides] + ["", f"Problems ({len(problems)}):"] + ["  " + p for p in problems]
    (out / "ai_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*(sys.argv[1:5] or paths.defaults("apply_ai_resolutions")))
