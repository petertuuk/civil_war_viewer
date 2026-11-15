"""Build canonical events from regimental mention clusters and anchor them to Wikidata and Dyer's index.

1. Cluster: every dated 'participated' claim is keyed by the distinctive words of its name and its
   dates; clusters with the same words and overlapping dates are merged. Each cluster's dates come
   from the most common dating across regiments.
2. Anchor to Wikidata: a cluster matches a Wikidata event when they share a distinctive name word
   (label or alias) and their dates agree within two days (Wikidata often has only a start date).
   The match brings coordinates, a standard name and aliases.
3. Anchor to Dyer's index: the same matching against canonical index events brings state, type
   and the index's alternate names.

Usage:
    python pipeline/anchor_events.py data/dyers/claims_rules.jsonl wikidata_civil_war_events.json \
        data/dyers/events.jsonl data/dyers
Writes canonical_events.jsonl, mention_to_event.jsonl and anchor_report.txt.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
from resolve_events import LEAD, norm, core_words, iso  # noqa: E402

EXTRA_STOP = {"first", "second", "third", "battle", "siege", "engagement", "skirmish", "action", "combat",
              "campaign", "assault", "raid", "expedition"}
QID = re.compile(r"Q\d+$")
ST_ABBR = cwv_states.table("Name", "CODE", "AL", "AZ", "AR", "CA", "CO", "DE", "FL", "GA", "ID", "IL", "IN", "IA",
                                           "KS", "KY", "LA", "MD", "MN", "MS", "MO", "NE", "NV", "NM", "NY", "NC",
                                           "ND", "OH", "OK", "OR", "PA", "SC", "SD", "TN", "TX", "UT", "VA", "WV",
                                           ("Washington, D.C.", "DC"), "DC", "VT", "WY", "MT",
                                           ("Idaho Territory", "ID"))
MENTION_ST = {"va": "VA", "w. va": "WV", "md": "MD", "pa": "PA", "tenn": "TN", "ky": "KY", "ga": "GA", "ala": "AL", "miss": "MS",
              "la": "LA", "ark": "AR", "mo": "MO", "tex": "TX", "n. c": "NC", "s. c": "SC", "fla": "FL", "ind": "IN", "ohio": "OH",
              "kan": "KS", "n. m": "NM", "i. t": "OK", "d. c": "DC"}
# place-type words: a match on these alone is no match
GENERIC = {"cross", "roads", "crossroads", "ford", "ferry", "bridge", "mill", "mills", "farm", "church", "gap", "hill",
           "hills", "run", "springs", "spring", "court", "house", "point", "mountain", "island", "bluff", "bluffs",
           "junction", "fort", "camp", "valley", "county", "city", "plains", "plantation", "heights", "tavern",
           "store", "bend", "pass", "lake", "bay", "harbor", "gulf", "north", "south", "east", "west", "upper", "lower",
           "new", "old", "big", "little", "great", "mount", "port", "bayou", "swamp", "cove", "shoals", "landing"}


def words_of(name):
    core = LEAD.sub("", norm(name))
    while LEAD.match(core):
        core = LEAD.sub("", core)
    return core_words(core) - EXTRA_STOP


# ------------------------------------------------------------------ clusters
def container_tag(mention):
    """'campaign' / 'siege' for container events, '' otherwise. Part of the cluster key, so 'Chancellorsville
    Campaign' and 'Battle of Chancellorsville' (same words, overlapping dates) stay separate events; their
    relation is a part_of claim (event_membership.py), not a merge."""
    m = (mention or "").lower()
    return "campaign" if re.search(r"\bcampaign\b", m) else "siege" if re.search(r"\bsiege\b", m) else ""


def build_clusters(claims):
    raw = defaultdict(list)
    for c in claims:
        if c["claim_type"] != "participated" or not c.get("date_start") or len(c["date_start"]) < 10:
            continue
        w = words_of(c["event_mention"])
        if not w or w <= {"duty", "there", "camp", "garrison"}:
            continue
        raw[(frozenset(w), container_tag(c["event_mention"]), c["date_start"], c["date_end"] or c["date_start"])].append(c)
    # merge clusters with identical words whose date spans overlap
    by_words = defaultdict(list)
    for (w, tag, d0, d1), cs in raw.items():
        a, b = iso(d0), iso(d1) or iso(d0)
        if a is None:
            continue                           # impossible date (e.g. Feb 30 from a scan error)
        by_words[(w, tag)].append([a, max(a, b or a), cs])
    clusters = []
    for w, spans in by_words.items():
        spans.sort(key=lambda s: s[0])
        cur = None
        for d0, d1, cs in spans:
            if cur and d0 <= cur[1] + timedelta(days=1):
                cur[1] = max(cur[1], d1)
                cur[2] += cs
            else:
                cur = [d0, d1, list(cs)]
                clusters.append((w, cur))
    out = []
    for i, ((w, tag), (d0, d1, cs)) in enumerate(clusters):
        dating = Counter((c["date_start"], c["date_end"] or c["date_start"]) for c in cs).most_common(1)[0][0]
        names = Counter(re.sub(r"[,.]?\s*$", "", c["event_mention"]) for c in cs)
        out.append({"cluster_id": f"cl{i:05d}", "words": sorted(w), "tag": tag, "name": names.most_common(1)[0][0],
                    "variants": [n for n, _ in names.most_common(6)],
                    "date_start": dating[0], "date_end": dating[1],
                    "span_start": d0.isoformat(), "span_end": d1.isoformat(),
                    "regiments": len({c["unit_id"] for c in cs}), "mentions": len(cs),
                    "_claims": cs})
    return out


# ------------------------------------------------------------------ Wikidata
def wd_dates(r):
    def one(v, p):
        if not v:
            return None, None
        d = date.fromisoformat(v[:10])
        p = int(p) if p else 11
        if p >= 11:
            return d, d
        if p == 10:
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            return date(d.year, d.month, 1), nxt - timedelta(days=1)
        return None, None                      # year only: too vague to match on
    s0, s1 = one(r.get("start"), r.get("start_prec"))
    e0, e1 = one(r.get("end"), r.get("end_prec"))
    p0, p1 = one(r.get("pit"), r.get("pit_prec"))
    lo = s0 or p0
    hi = e1 or s1 or p1
    if lo and not e1 and hi == lo:
        hi = lo + timedelta(days=7)        # only a start date: allow a multi-day battle
    return lo, hi


_STATES = None


def state_at(lon, lat):
    """US state containing a point (Natural Earth admin-1 outlines in data/external/naturalearth), or None."""
    global _STATES
    if _STATES is None:
        _STATES = []
        p = Path(__file__).resolve().parents[1] / "data/external/naturalearth/ne_10m_admin_1_states_provinces_lakes.geojson"
        try:
            from shapely.geometry import Point, shape
            from shapely.prepared import prep
            for f in json.load(open(p, encoding="utf-8"))["features"]:
                if f["properties"].get("adm0_a3") == "USA" and f.get("geometry"):
                    g = shape(f["geometry"])
                    _STATES.append((f["properties"].get("postal"), g.bounds, prep(g)))
            _STATES.append(("_point", Point))
        except Exception:
            _STATES = [("_point", None)]
    Point = _STATES[-1][1]
    if Point is None:
        return None
    pt = Point(lon, lat)
    for st, (x0, y0, x1, y1), g in _STATES[:-1]:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and g.contains(pt):
            return st
    return None


def load_wikidata(path):
    rows = json.load(open(path, encoding="utf-8"))
    out = []
    for r in rows:
        names = [r.get("label") or ""] + [a for a in (r.get("aliases") or "").split("|") if a]
        lo, hi = wd_dates(r)
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r.get("coord") or "")
        sts = {ST_ABBR[x.strip()] for x in (r.get("place_labels") or "").split("|") if x.strip() in ST_ABBR}
        mm = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r.get("coord") or "")
        if mm:
            st = state_at(float(mm.group(1)), float(mm.group(2)))
            if st:
                sts.add(st)
        out.append({"qid": QID.search(r["b"]).group(0), "label": r.get("label"), "names": names, "states": sts,
                    "words": set().union(*(words_of(n) for n in names)) if names else set(),
                    "lo": lo, "hi": hi, "lon": float(m.group(1)) if m else None,
                    "lat": float(m.group(2)) if m else None,
                    "classes": [QID.search(c).group(0) for c in (r.get("classes") or "").split("|") if QID.search(c)],
                    "parts": [QID.search(c).group(0) for c in (r.get("parts") or "").split("|") if QID.search(c)]})
    return out


def match_wikidata(cl, wd_index, wd):
    d0, d1 = iso(cl["date_start"]), iso(cl["date_end"]) or iso(cl["date_start"])
    w = set(cl["words"])
    best = []
    for i in set().union(*(wd_index.get(x, set()) for x in w)):
        e = wd[i]
        if not e["lo"]:
            continue
        hi = e["hi"] or e["lo"]
        if e["lo"] > d1 + timedelta(days=2) or hi < d0 - timedelta(days=2):
            continue
        common = w & e["words"]
        if common <= GENERIC:
            continue                    # 'Mallory's Cross Roads' shares only 'cross roads' with Brice's Cross Roads
        score = len(common) / len(w) - 0.01 * min(abs((e["lo"] - d0).days), 20)
        # tie-break only (never decides the 0.6 threshold): the whole battle over its "First Day" sub-item
        tie = 0.01 * min(abs(((e["hi"] or e["lo"]) - d1).days), 20) + 0.02 * len(e["words"] - w)
        is_camp = "campaign" in cl["name"].lower()
        if is_camp != ("Q831663" in e["classes"]):
            score -= 0.6
        # a long operation that merely contains a short battle is not the same event
        c_span = (d1 - d0).days
        e_span = ((e["hi"] or e["lo"]) - e["lo"]).days
        if c_span >= 14 and e_span <= 31 and c_span > 3 * (e_span + 1):   # was e_span <= 7: 'N. Y. Harbor' 1863-65 took Cold Harbor
            continue
        best.append((round(score, 3), -round(tie, 3), i))
    best.sort(reverse=True)
    best = [(sc, i) for sc, _, i in best]
    if not best or best[0][0] < 0.6:
        return None, best
    return best[0][1], best


# ------------------------------------------------------------------ Dyer's index events
def load_index_events(path):
    ev = [json.loads(l) for l in open(path, encoding="utf-8")]
    for e in ev:
        e["_words"] = set().union(*(words_of(n) for n in e["names"])) if e["names"] else set()
        e["_lo"] = iso(e["date_start"])
        e["_hi"] = iso(e["date_end"], end=True) or e["_lo"]
    return ev


def match_index(cl, ix_index, ix):
    d0, d1 = iso(cl["date_start"]), iso(cl["date_end"]) or iso(cl["date_start"])
    w = set(cl["words"])
    best = []
    for i in set().union(*(ix_index.get(x, set()) for x in w)):
        e = ix[i]
        if not e["_lo"] or e["_lo"] > d1 + timedelta(days=1) or e["_hi"] < d0 - timedelta(days=1):
            continue
        # best single name, scored against the longer of the two names ('Maryland' vs 'Maryland Heights' = 0.5)
        score = max((len(w & nw) / max(len(w), len(nw)) for nw in (words_of(n) for n in e["names"]) if nw), default=0)
        if e["type"] in ("battle", "siege", "campaign", "engagement"):
            score += 0.1
        score -= 0.01 * min(abs((e["_lo"] - d0).days), 20)
        best.append((round(score, 3), i))
    best.sort(reverse=True)
    if not best or best[0][0] < 0.6:
        return None
    return best[0][1]


def main(claims_path, wd_path, index_events_path, out_dir):
    out = Path(out_dir)
    claims = [json.loads(l) for l in open(claims_path, encoding="utf-8")]
    clusters = build_clusters(claims)
    wd = load_wikidata(wd_path)
    wd_index = defaultdict(set)
    for i, e in enumerate(wd):
        for x in e["words"]:
            wd_index[x].add(i)
    ix = load_index_events(index_events_path)
    ix_index = defaultdict(set)
    for i, e in enumerate(ix):
        for x in e["_words"]:
            ix_index[x].add(i)

    wd_used = Counter()
    state_rejects = [0]
    with open(out / "canonical_events.jsonl", "w", encoding="utf-8") as f, \
            open(out / "mention_to_event.jsonl", "w", encoding="utf-8") as g:
        for cl in clusters:
            wi, cands = match_wikidata(cl, wd_index, wd)
            ii = match_index(cl, ix_index, ix)
            # the same town name in two states: the Wikidata item must be in the state the mentions or Dyer's index give
            if wi is not None and wd[wi].get("states"):
                cst = {ix[ii]["state"]} if ii is not None and ix[ii].get("state") else set()
                for v in [cl.get("name", "")] + list(cl.get("variants") or []):
                    m = re.search(r",\s*(w\. va|n\. c|s\. c|n\. m|i\. t|d\. c|va|md|pa|tenn|ky|ga|ala|miss|la|ark|mo|tex|fla|ind|ohio|kan)\.?\s*$", v.lower())
                    if m:
                        cst.add(MENTION_ST[m.group(1)])
                cst |= {"WV" for x in cst if x == "VA"} | {"VA" for x in cst if x == "WV"}
                if cst and not (cst & wd[wi]["states"]):
                    state_rejects[0] += 1
                    wi = None
            rec = {k: v for k, v in cl.items() if not k.startswith("_")}
            if wi is not None:
                e = wd[wi]
                wd_used[e["qid"]] += cl["mentions"]
                rec.update({"wikidata": e["qid"], "wikidata_label": e["label"], "wikidata_aliases": e["names"][1:],
                            "lat": e["lat"], "lon": e["lon"]})
            if ii is not None:
                e = ix[ii]
                rec.update({"dyer_index_event": e["event_id"], "dyer_names": e["names"], "state": e["state"],
                            "dyer_type": e["type"]})
            cl["_wd"], cl["_ix"] = wi, ii
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for c in cl["_claims"]:
                g.write(json.dumps({"unit_id": c["unit_id"], "mention": c["event_mention"],
                                    "date_start": c["date_start"], "cluster_id": cl["cluster_id"],
                                    "wikidata": rec.get("wikidata")}, ensure_ascii=False) + "\n")

    total = sum(c["mentions"] for c in clusters)
    def share(pred):
        return sum(c["mentions"] for c in clusters if pred(c)) / total
    big = [c for c in clusters if c["regiments"] >= 20]
    rep = [f"Dated regimental battle mentions: {total}; clusters: {len(clusters)} "
           f"({len(big)} with 20+ regiments, covering {share(lambda c: c['regiments'] >= 20):.0%} of mentions)",
           f"Mentions in clusters anchored to Wikidata (coordinates + standard name): {share(lambda c: c['_wd'] is not None):.0%}",
           f"Mentions in clusters anchored to Dyer's index (state, type, alternate names): {share(lambda c: c['_ix'] is not None):.0%}",
           f"Mentions anchored to either: {share(lambda c: c['_wd'] is not None or c['_ix'] is not None):.0%}",
           f"Clusters with 20+ regiments anchored to Wikidata: {sum(1 for c in big if c['_wd'] is not None)} of {len(big)}",
           f"Wikidata events matched by at least one cluster: {len(wd_used)} of {len(wd)}",
           f"Wikidata matches rejected: item in another state than the mentions: {state_rejects[0]}", "",
           "Largest clusters and their anchors:"]
    for c in sorted(clusters, key=lambda c: -c["regiments"])[:40]:
        wl = wd[c["_wd"]]["label"] if c["_wd"] is not None else "-- no Wikidata match"
        il = " / ".join(ix[c["_ix"]]["names"]) if c["_ix"] is not None else "--"
        rep.append(f"  {c['regiments']:>4}  {c['date_start']}  {c['name'][:42]:<42}  WD: {wl[:40]:<40}  Dyer: {il[:50]}")
    rep += ["", "Clusters with 20+ regiments and no Wikidata match:"]
    for c in sorted([c for c in big if c["_wd"] is None], key=lambda c: -c["regiments"])[:60]:
        rep.append(f"  {c['regiments']:>4}  {c['date_start']}..{c['date_end']}  {c['name']}")
    rep += ["", "Clusters merged under one Wikidata event (name variants found):"]
    groups = defaultdict(list)
    for c in clusters:
        if c["_wd"] is not None:
            groups[c["_wd"]].append(c)
    multi = sorted([(i, cs) for i, cs in groups.items() if len({tuple(c['words']) for c in cs}) > 1],
                   key=lambda x: -sum(c["mentions"] for c in x[1]))
    for i, cs in multi[:30]:
        rep.append(f"  {wd[i]['label']}: " + " | ".join(sorted({c['name'] for c in cs})[:6]))
    rep += ["", "Most-cited Wikidata events not matched to any cluster (no date in Wikidata, or named differently):"]
    unmatched = [e for e in wd if e["qid"] not in wd_used]
    rep += [f"  {e['qid']:<10} {e['label']}  ({e['lo']})" for e in unmatched[:40]]
    (out / "anchor_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:7]))


if __name__ == "__main__":
    main(*(sys.argv[1:5] or paths.defaults("anchor_events")))
