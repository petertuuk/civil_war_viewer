"""Merge duplicate event clusters into events, and link events to parents.

Usage:
  python3 pipeline/merge_events.py data/dyers data/ai data/events data/wikidata/wikidata_civil_war_events.json

Inputs:  data/dyers/canonical_events.jsonl, data/dyers/mention_to_event.jsonl,
         data/ai/resolved_events.jsonl, data/ai/event_resolutions_*.psv (notes)
Outputs: data/events/events.jsonl            one row per merged event
         data/events/cluster_to_event.jsonl  cluster_id -> event_id
         data/events/merge_report.txt

Clusters are merged (union-find) when:
  1. an AI note says "Same as clXXXXX";
  2. they share a Wikidata QID (rules or AI) and their date ranges, after any
     date_fix, overlap or are within GAP_DAYS (Cherokee Station Oct 21 and
     Oct 29, 1863 share a QID but are different skirmishes, so they stay apart);
  3. neither has a QID but they share the same AI canonical name and their
     dates overlap or are within GAP_DAYS.
Event fields come from the largest member (by regiments); dates span all
members; regiments = distinct units across members.
"""
import collections, glob, json, re, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import first_day as d  # noqa: E402

GAP_DAYS = 2


def theater(ll, log):
    """Coordinates outside the theater of the war (lat 24-50, lon -125..-66) are a data error: Wikidata's Brown's Ferry
    had lon +85.354. A flipped longitude sign that lands inside is corrected; anything else is dropped."""
    if not ll or ll[0] is None:
        return ll
    lat, lon = float(ll[0]), float(ll[1])
    ok = lambda a, b: 24 < a < 50 and -125 < b < -66
    if ok(lat, lon):
        return ll
    if ok(lat, -lon):
        log["coordinates: longitude sign corrected"] += 1
        return (lat, -lon) + tuple(ll[2:])
    log["coordinates outside the theater dropped"] += 1
    return None


class UF:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b, why, log):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra; log[why] += 1


def close(a, b):
    a0, a1, b0, b1 = d(a[0]), d(a[1]), d(b[0]), d(b[1])
    if not (a0 and b0):
        return False
    a1, b1 = a1 or a0, b1 or b0
    return (b0 - a1).days <= GAP_DAYS and (a0 - b1).days <= GAP_DAYS


def main(dyers_dir, ai_dir, out_dir, wd_path=None):
    dyers, ai_dir, out = Path(dyers_dir), Path(ai_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cs = {}
    for l in open(dyers / "canonical_events.jsonl", encoding="utf-8"):
        c = json.loads(l); cs[c["cluster_id"]] = c
    ai = {}
    for l in open(ai_dir / "resolved_events.jsonl", encoding="utf-8"):
        o = json.loads(l); ai[o["cluster_id"]] = o
    units = collections.defaultdict(set)
    for l in open(dyers / "mention_to_event.jsonl", encoding="utf-8"):
        m = json.loads(l); units[m["cluster_id"]].add(m["unit_id"])

    def span(cid):
        o = ai.get(cid)
        return (o["date_start"], o["date_end"]) if o else (cs[cid]["date_start"], cs[cid]["date_end"])
    for cid, o in ai.items():
        if o.get("detach_rules_anchor") and cid in cs:      # AI overrides a wrong rules anchor
            for k in ("wikidata", "wikidata_label", "wikidata_aliases", "lat", "lon"):
                cs[cid].pop(k, None)
    # Wikidata date ranges: a cluster keeps its QID only if its dates overlap the Wikidata event's (+-3 days).
    # Otherwise it is a separate action at the same place (Front Royal May 23 vs May 30, 1862) or a bad anchor.
    wd_range = {}
    if wd_path:
        for r in json.load(open(wd_path, encoding="utf-8")):
            q = r["b"].rsplit("/", 1)[1]
            lo = d(r.get("start")) or (d(r.get("pit")) if r.get("pit") and not r["pit"][4:10] == "-01-01" else None)
            hi = d(r.get("end")) or lo
            if r.get("end") and r["end"][:4] > "1866":
                wd_range[q] = "postwar"                # e.g. Reconstruction Era: never a Dyer's event
            elif lo:
                wd_range[q] = (lo, hi)
    detached = collections.Counter()
    # Wikidata matches that the units' routes ruled out (resolve_mentions.py writes route_detached.jsonl: the units that
    # fought there were all far from the Wikidata place, e.g. Dyer's "Gainesville" of Oct. 1862 matched to the Great
    # Hanging at Gainesville, Texas): a different action, so Dyer's own name and no Wikidata coordinates
    route_det = set()
    rdp = Path(out_dir) / "route_detached.jsonl"
    if rdp.exists():
        for l in open(rdp, encoding="utf-8"):
            r = json.loads(l)
            route_det |= {(c, r["wikidata"]) for c in r["clusters"]}
    route_cl = set()
    def qid(cid):
        q = cs[cid].get("wikidata") or ai.get(cid, {}).get("wikidata")
        if q and (cid, q) in route_det:
            detached[cid] = q; route_cl.add(cid)
            return None
        if not q or q not in wd_range:
            return q
        rg = wd_range[q]
        a0, a1 = d(span(cid)[0]), d(span(cid)[1]) or d(span(cid)[0])
        if rg == "postwar" or (a0 and ((a0 - rg[1]).days > 3 or (rg[0] - a1).days > 3)):
            detached[cid] = q
            return None
        return q

    uf, log = UF(), collections.Counter()
    conflicts = {}
    for cid in cs:
        uf.find(cid)
    # 1. explicit notes
    for o in ai.values():
        for m in re.findall(r"[Ss]ame as (cl\d{5})", o.get("note", "")):
            if m in cs:
                uf.union(m, o["cluster_id"], "note 'Same as'", log)
    # 2. same QID, close dates   3. same AI canonical name, no QID, close dates
    groups = collections.defaultdict(list)
    for cid in cs:
        q = qid(cid)
        if q:
            groups[("q", q)].append(cid)
        elif cid in ai:
            groups[("n", ai[cid]["canonical"].lower())].append(cid)
    for key, mem in groups.items():
        mem.sort(key=lambda c: span(c)[0])
        for i, a in enumerate(mem):
            for b in mem[i + 1:]:
                if key[0] == "q" and (cs[a].get("tag") or "") != (cs[b].get("tag") or ""):
                    conflicts[(a, b, key[1])] = None       # campaign/siege vs plain cluster: membership, not merge
                    continue
                if close(span(a), span(b)) or (key[0] == "q" and isinstance(wd_range.get(key[1]), tuple)):
                    uf.union(a, b, "same Wikidata ID, dates within 2 days" if key[0] == "q"
                             else "same AI name, dates within 2 days", log)

    members = collections.defaultdict(list)
    for cid in cs:
        members[uf.find(cid)].append(cid)

    events, c2e = [], {}
    for n, mem in enumerate(sorted(members.values(), key=lambda m: min(span(c)[0] for c in m))):
        mem.sort(key=lambda c: -cs[c]["regiments"])
        top = mem[0]; c, o = cs[top], ai.get(top, {})
        eid = f"ev{n:05d}"
        q = next((qid(m) for m in mem if qid(m)), None)
        lab = next((cs[m].get("wikidata_label") or ai.get(m, {}).get("wikidata_label")
                    for m in mem if qid(m)), None)

        lat = next(((cs[m].get("lat"), cs[m].get("lon"), "wikidata") for m in mem if cs[m].get("lat") is not None
                    and m not in route_cl), None) \
            or next(((ai[m]["lat"], ai[m]["lon"], ai[m]["coord_source"]) for m in mem
                     if m in ai and ai[m].get("lat") is not None and m not in route_cl), None)
        lat = theater(lat, log)
        starts = [span(m)[0] for m in mem]; ends = [span(m)[1] or span(m)[0] for m in mem]
        ev = {"event_id": eid,
              "name": lab or o.get("canonical") or c["name"],
              "dyer_name": c["name"],
              "kind": o.get("kind") or c.get("dyer_type") or "",
              "date_start": min(starts), "date_end": max(ends),
              "regiments": len(set().union(*(units[m] for m in mem))),
              "mentions": sum(cs[m]["mentions"] for m in mem),
              "clusters": mem}
        if q: ev.update(wikidata=q)
        elif any(m in detached for m in mem):          # a different action at the same place: Dyer's own name
            ev.update(name=c["name"], wikidata_detached=next(detached[m] for m in mem if m in detached))
            if any(m in route_cl for m in mem):
                ev["detach_reason"] = "route"
        if lat: ev.update(lat=lat[0], lon=lat[1], coord_source=lat[2])
        for k in ("parent", "parent_wikidata", "confidence", "wikidata_try"):
            v = next((ai[m][k] for m in mem if m in ai and ai[m].get(k)), None)
            if v: ev[k] = v
        if c.get("state"): ev["state"] = c["state"]
        if any(m in ai for m in mem): ev["source"] = "rules+ai" if any(cs[m].get("wikidata") or cs[m].get("dyer_index_event") for m in mem) else "ai"
        events.append(ev)
        for m in mem:
            c2e[m] = eid

    # parents that exist only in Wikidata (e.g. Atlanta campaign): add them as events
    if wd_path:
        wd = {}
        for r in json.load(open(wd_path, encoding="utf-8")):
            wd.setdefault(r["b"].rsplit("/", 1)[1], r)
        have = {ev.get("wikidata") for ev in events}
        for pq in sorted({ev["parent_wikidata"] for ev in events if ev.get("parent_wikidata")} - have):
            r = wd.get(pq)
            if not r:
                continue
            st = (r.get("start") or r.get("pit") or "")[:10]
            en = (r.get("end") or st)[:10]
            kids = [e for e in events if e.get("parent_wikidata") == pq]
            ev = {"event_id": f"ev{len(events):05d}", "name": r.get("label") or pq, "kind": "campaign",
                  "date_start": min([st] + [k["date_start"] for k in kids if not st]) if st else min(k["date_start"] for k in kids),
                  "date_end": en or max(k["date_end"] for k in kids), "regiments": 0, "mentions": 0,
                  "clusters": [], "wikidata": pq, "source": "wikidata_parent"}
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r.get("coord") or "")
            ll = theater((float(m.group(2)), float(m.group(1)), "wikidata"), log) if m else None
            if ll:
                ev.update(lat=ll[0], lon=ll[1], coord_source="wikidata")
            events.append(ev); log["parent added from Wikidata"] += 1

    # parent links: parent label -> event with that Wikidata ID, Wikidata label or AI name
    by_q, by_name = {}, {}
    for ev in events:
        if ev.get("wikidata"):
            by_q.setdefault(ev["wikidata"], ev)
        by_name.setdefault(ev["name"].lower(), ev)
    linked = 0
    for ev in events:
        p = (by_q.get(ev.get("parent_wikidata")) if ev.get("parent_wikidata") else None) \
            or by_name.get((ev.get("parent") or "").lower())
        if p and p is not ev:
            ev["parent_event"] = p["event_id"]; linked += 1

    # membership: part_of claims from NPS campaigns, Wikidata, Dyer's sequences, anchors and AI; preferred parent
    import event_membership
    for k in list(conflicts):
        conflicts[k] = (c2e.get(k[0]), c2e.get(k[1]))
    part_of, mem_report = (event_membership.build(events, cs, conflicts, wd_path, Path(dyers_dir).resolve().parents[1], log)
                           if wd_path else ([], []))
    linked = sum(1 for e in events if e.get("parent_event"))
    with open(out / "part_of.jsonl", "w", encoding="utf-8") as f:
        for o in part_of:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    with open(out / "events.jsonl", "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    with open(out / "cluster_to_event.jsonl", "w", encoding="utf-8") as f:
        for cid, eid in sorted(c2e.items()):
            f.write(json.dumps({"cluster_id": cid, "event_id": eid}) + "\n")

    merged = [ev for ev in events if len(ev["clusters"]) > 1]
    big = sorted(merged, key=lambda e: -e["regiments"])[:15]
    n_cl = sum(1 for e in events if e["clusters"])
    rep = [f"Clusters: {len(cs)} -> events from clusters: {n_cl} ({len(cs)-n_cl} clusters folded in); "
           f"plus {len(events)-n_cl} parent campaigns from Wikidata",
           f"Events built from 2+ clusters: {len(merged)}",
           "Merges by reason: " + ", ".join(f"{k} {v}" for k, v in log.items()),
           f"Clusters whose Wikidata ID was detached (dates outside the Wikidata event, or ruled out by the units' routes: "
           f"{len(route_cl)}): {len(detached)}",
           f"Coordinates: longitude sign corrected {log['coordinates: longitude sign corrected']}, "
           f"outside the theater dropped {log['coordinates outside the theater dropped']}",
           f"Events with a parent named: {sum(1 for e in events if e.get('parent'))}; with a preferred parent (part_of): {linked}",
           *mem_report,
           f"Events with 20+ regiments: {sum(1 for e in events if e['regiments'] >= 20)}",
           "", "Largest merged events (regiments, clusters, dates, name):"]
    rep += [f"  {e['regiments']:4d}  {len(e['clusters']):2d}  {e['date_start']}..{e['date_end']}  {e['name']}" for e in big]
    long = [e for e in merged if d(e["date_start"]) and d(e["date_end"]) and (d(e["date_end"]) - d(e["date_start"])).days > 120 and e.get("kind") not in ("siege", "campaign", "operations")]
    rep += ["", f"Check: merged non-campaign events spanning 120+ days ({len(long)}):"]
    rep += [f"  {e['event_id']} {e['date_start']}..{e['date_end']} {e['name']} {e['clusters'][:6]}" for e in long[:20]]
    (out / "merge_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*sys.argv[1:5])
