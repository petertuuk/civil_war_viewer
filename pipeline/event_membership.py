"""Event membership: part_of claims (event within event), from several sources, and one preferred parent each.

Called at the end of merge_events.py. Sources (each candidate keeps its source and confidence):
  nps       NPS / CWSAC: each of the 384 surveyed battles is filed under a campaign ("Streight's Raid ... [April 1863]").
            Battle -> our event via Wikipedia title -> Wikidata label; campaign -> our container event by name words and
            dates, else a new campaign event.
  wikidata  "part of" (P361) on the Wikidata item an event is anchored to.
  anchor    a container cluster (campaign/siege) and a plain cluster anchored to the same Wikidata item are not merged:
            the plain one is part of the container; the Wikidata ID stays with whichever matches the item's class.
  dyers     Dyer's lists a campaign or siege, then the actions inside it ("Atlanta Campaign May to September.
            Tunnel Hill May 6-7. ..."): for each unit, an action dated inside an open container counts as a vote;
            kept when 2+ units and 30%+ of the action's units agree.
  ai        the parent named by the AI resolutions.
Preferred parent: among candidates whose dates contain the child's (+-3 days) and that would not make a cycle,
the narrowest container (Siege of Petersburg before the Richmond-Petersburg Campaign); ties by source rank.
No fixed levels: depth is whatever the graph says; event kind is descriptive only.
"""
import csv, json, re, collections
from datetime import date, timedelta
from pathlib import Path

RANK = {"nps": 5, "wikidata": 4, "anchor": 4, "dyers": 3, "ai": 2, "inferred": 1}
CONTAINER_Q = ("Q831663", "Q188055", "Q2001676")      # military campaign, siege, military operation


def d(s, end=False):
    s = (s or "")[:10]
    try:
        if len(s) == 7:
            y, m = int(s[:4]), int(s[5:7])
            return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)) if end else date(y, m, 1)
        return date.fromisoformat(s) if len(s) == 10 else None
    except ValueError:
        return None


def words(s):
    s = re.sub(r"\[.*?\]|\(.*?\)", " ", (s or "").lower()).replace("'", "").replace("\u2019", "")
    return {w for w in re.findall(r"[a-z]{3,}", s)
            if w not in {"campaign", "the", "and", "against", "operations", "battle", "siege", "of", "in", "on", "raid", "expedition"}}


def build(events, cs, conflicts, wd_path, proj, log):
    P = Path(proj)
    by_id = {e["event_id"]: e for e in events}
    by_q = {}
    for e in events:
        if e.get("wikidata"): by_q.setdefault(e["wikidata"], e)
    W = {}
    for r in json.load(open(wd_path, encoding="utf-8")):
        W.setdefault(r["b"].rsplit("/", 1)[1], r)
    tag = {e["event_id"]: next((cs[m].get("tag") for m in e["clusters"] if cs[m].get("tag")), "") for e in events}
    def is_container(e):
        q = W.get(e.get("wikidata") or "", {})
        return bool(tag.get(e["event_id"])) or e.get("kind") in ("campaign", "siege") or \
            any(c in (q.get("classes") or "") for c in CONTAINER_Q)
    cand = []                                             # (child id, parent id, source, conf, note)
    same = lambda a, b: re.sub(r"[^a-z]|\bbattle\b|\bof\b|\bthe\b", "", a.lower()) == re.sub(r"[^a-z]|\bbattle\b|\bof\b|\bthe\b", "", b.lower())
    def add(c, p, src, conf, note=""):
        # two events with the same name are a duplicate, not a membership ("Siege of Suffolk" in "Siege of Suffolk")
        if c and p and c != p and not same(by_id[c]["name"], by_id[p]["name"]): cand.append((c, p, src, conf, note))
    new_events = []
    def new_event(name, kind, d0, d1, src):
        e = {"event_id": f"ev{len(events) + len(new_events):05d}", "name": name, "kind": kind, "date_start": d0,
             "date_end": d1, "regiments": 0, "mentions": 0, "clusters": [], "source": src}
        new_events.append(e); by_id[e["event_id"]] = e; tag[e["event_id"]] = kind
        return e

    # anchor: same Wikidata item, container vs plain cluster -> membership, not merge
    for ca, cb, q in conflicts:
        ea, eb = by_id.get(conflicts[(ca, cb, q)][0]), by_id.get(conflicts[(ca, cb, q)][1])
        if not ea or not eb or ea is eb: continue
        cont, plain = (ea, eb) if tag.get(ea["event_id"]) else (eb, ea)
        q_is_container = any(c in (W.get(q, {}).get("classes") or "") for c in CONTAINER_Q)
        loser = plain if q_is_container else cont
        if loser.get("wikidata") == q:
            loser.pop("wikidata", None); loser["wikidata_detached"] = q
            loser["name"] = loser.get("dyer_name") or loser["name"]
        add(plain["event_id"], cont["event_id"], "anchor", 0.8, f"both anchored to {q}")
    by_q = {}
    for e in events:
        if e.get("wikidata"): by_q.setdefault(e["wikidata"], e)

    # wikidata part of
    for e in list(events):
        for pq in [x.rsplit("/", 1)[-1] for x in (W.get(e.get("wikidata") or "", {}).get("parts") or "").split("|") if x]:
            p = by_q.get(pq)
            if not p and pq in W:
                nm = (W[pq].get("label") or "").lower()
                p = next((x for x in events + new_events if x["name"].lower() == nm or x.get("wikidata_detached") == pq), None)
                if p and p is not e and not p.get("wikidata"): p["wikidata"] = pq; by_q[pq] = p
                if p is e: p = None
            if not p and pq in W and (W[pq].get("start") or W[pq].get("pit")):
                r = W[pq]; st = (r.get("start") or r.get("pit"))[:10]; en = (r.get("end") or st)[:10]
                if st[:4] <= "1865" and en[:4] >= "1861" and en[:4] <= "1866":
                    p = new_event(r.get("label") or pq, "campaign", st, en, "wikidata_parent")
                    p["wikidata"] = pq; by_q[pq] = p
            if p: add(e["event_id"], p["event_id"], "wikidata", 0.9, pq)

    # ai parents (linked by merge_events into parent_event before this runs)
    for e in events:
        if e.get("parent_event"):
            add(e["event_id"], e["parent_event"], "ai", 0.7, e.get("parent") or "")

    # nps / cwsac campaigns
    ar = P / "data/external/acw_battle_data"
    wiki = {r["cwsac_id"].upper(): r["wikipedia_title"].replace("_", " ") for r in csv.DictReader(open(ar / "nps_battles_to_wiki.csv", encoding="utf-8"))}
    lab = collections.defaultdict(list)
    for q, r in W.items():
        for nm in [r.get("label", "")] + (r.get("aliases") or "").split("|"):
            if nm: lab[nm.lower()].append(q)
    camps = {}
    for r in csv.DictReader(open(ar / "cwsac_campaigns.csv", encoding="utf-8")):
        try:
            camps[r["campaign"]] = (date(int(r["start_year"]), int(r["start_month"]), 1),
                                    d(f"{int(r['end_year']):04d}-{int(r['end_month']):02d}", True))
        except (ValueError, KeyError):
            pass
    containers = [e for e in events + new_events if is_container(e) or "campaign" in e["name"].lower()]
    camp_event = {}
    def find_campaign(name):
        if name in camp_event: return camp_event[name]
        a, b = camps.get(name, (None, None))
        w = words(re.sub(r"\b[A-Z][a-z]+['\u2019]s\b", " ", name))     # drop the commander: "Grant's Overland Campaign"
        w = w or words(name)
        best = None
        nps_siege = "siege" in name.lower()
        for e in containers:
            e_siege = tag.get(e["event_id"]) == "siege" or e.get("kind") == "siege" or "siege" in e["name"].lower()
            if e_siege != nps_siege: continue          # "Atlanta Campaign" is not the "Siege of Atlanta"
            jac, cont = 0, 0
            for k, ew in enumerate((words(e["name"]), words(e.get("dyer_name", "")))):
                if w and ew:                             # containment only against the event's main name
                    jac = max(jac, len(w & ew) / len(w | ew))
                    cont = max(cont, 1 if k == 0 and (w <= ew or ew <= w) and (w & ew) else 0)
            j = max(jac, cont)
            s0, s1 = d(e["date_start"]), d(e["date_end"], True) or d(e["date_start"])
            if a and s0 and (s0 > b + timedelta(days=15) or (s1 or s0) < a - timedelta(days=15)): continue
            if j >= 0.5 and (best is None or (round(jac, 2), cont, e.get("regiments", 0)) > best[0]):
                best = ((round(jac, 2), cont, e.get("regiments", 0)), e)   # exact name overlap before containment
        e = best[1] if best else (new_event(re.sub(r"\s*\[.*?\]\s*", "", name), "campaign", a.isoformat(), b.isoformat(), "nps_campaign") if a else None)
        if best and a:                                # NPS campaign months are the better container dates
            e0, e1 = d(e["date_start"]), d(e["date_end"], True) or d(e["date_start"])
            if e0 and a < e0: e["date_start"] = a.isoformat(); e["dates_widened"] = "nps"
            if e1 and b > e1: e["date_end"] = b.isoformat(); e["dates_widened"] = "nps"
        if e and not best: containers.append(e)
        camp_event[name] = e
        return e
    n_nps = 0
    for r in csv.DictReader(open(ar / "cwsac_battles.csv", encoding="utf-8")):
        t = wiki.get(r["battle"].upper())
        qs = (lab.get((t or "").lower()) or lab.get(re.sub(r"\s*\([^)]*\)\s*$", "", t or "").lower()) or []) if t else []
        bs, be = d(r.get("start_date")), d(r.get("end_date")) or d(r.get("start_date"))
        def near(ev):                                 # same name, same dates: 1864 Franklin is not 1863 Franklin
            a0, a1 = d(ev["date_start"]), d(ev["date_end"], True) or d(ev["date_start"])
            return not (bs and a0) or (a0 - timedelta(days=7) <= be and bs <= (a1 or a0) + timedelta(days=7))
        e = next((by_q[q] for q in qs if q in by_q and near(by_q[q])), None)
        if not e or not r.get("campaign"): continue
        p = find_campaign(r["campaign"])
        if p and p is not e:
            add(e["event_id"], p["event_id"], "nps", 0.9, r["campaign"]); n_nps += 1

    # dyers: unit-by-unit sequences
    m2c = {}
    for l in open(P / "data/dyers/mention_to_event.jsonl", encoding="utf-8"):
        m = json.loads(l); m2c[(m["unit_id"], m["mention"], m["date_start"])] = m["cluster_id"]
    c2e = {m: e["event_id"] for e in events for m in e["clusters"]}
    votes, units_of = collections.Counter(), collections.defaultdict(set)
    seq = collections.defaultdict(list)
    for l in open(P / "data/dyers/claims_rules.jsonl", encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] != "participated" or not c.get("date_start"): continue
        ev = c2e.get(m2c.get((c["unit_id"], c.get("event_mention"), c.get("date_start"))))
        if ev: seq[c["unit_id"]].append((ev, d(c["date_start"]), d(c.get("date_end") or c["date_start"], True)))
    for u, items in seq.items():
        opened = []
        for ev, a, b in items:
            units_of[ev].add(u)
            for pev, pa, pb in opened:
                if pev != ev and a and pa and pa - timedelta(days=1) <= a and (b or a) <= pb + timedelta(days=1) and (pb - pa) > ((b or a) - a):
                    votes[(ev, pev)] += 1
            if tag.get(ev) and a and b:
                opened = [o for o in opened if o[2] >= a] + [(ev, a, b)]
    for (c, p), v in votes.items():
        share = v / max(1, len(units_of[c]))
        if v >= 2 and share >= 0.3:
            add(c, p, "dyers", round(min(0.9, 0.5 + 0.4 * share), 2), f"{v} of {len(units_of[c])} units")

    # preferred parent: valid (dates contain, no cycle), narrowest, then source rank
    events.extend(new_events)
    for e in events: e.pop("parent_event", None)
    best_of = collections.defaultdict(list)
    for c, p, src, conf, note in cand: best_of[c].append((p, src, conf, note))
    parent = {}
    def span(eid):
        e = by_id[eid]; a = d(e["date_start"]); b = d(e["date_end"], True) or a
        return a, b
    def contains(p, c):
        (pa, pb), (ca, cb) = span(p), span(c)
        if not (pa and ca): return True
        return pa - timedelta(days=3) <= ca and (cb or ca) <= (pb or pa) + timedelta(days=3)
    def cycles(c, p):
        seen = set()
        while p and p not in seen:
            if p == c: return True
            seen.add(p); p = parent.get(p)
        return False
    out, bad_dates = [], 0
    order = sorted(best_of, key=lambda c: (span(c)[1] - span(c)[0]).days if span(c)[0] and span(c)[1] else 0)
    for c in order:
        opts = []
        for p, src, conf, note in best_of[c]:
            ok = contains(p, c)
            bad_dates += not ok
            if ok:
                a, b = span(p); width = (b - a).days if a and b else 99999
                opts.append((width, -RANK[src], -conf, p))
        opts.sort()
        for width, _, _, p in opts:
            if not cycles(c, p):
                parent[c] = p; break
        seen = set()
        for p, src, conf, note in best_of[c]:
            if (p, src) in seen: continue
            seen.add((p, src))
            out.append({"event_id": c, "parent_event_id": p, "source": src, "confidence": conf, "note": note,
                        "dates_ok": contains(p, c), "preferred": parent.get(c) == p})
    # inferred links: a child's wider candidate (from NPS, Wikidata or AI) contains its chosen parent, which has no
    # parent yet; needs 2+ different children agreeing (Savage's Station and others: Seven Days -> Peninsula Campaign)
    infer = collections.defaultdict(set)
    for c in order:
        if c not in parent: continue
        chosen = parent[c]
        for p, src, conf, note in best_of[c]:
            if p != chosen and src in ("nps", "wikidata", "ai") and contains(p, c) and contains(p, chosen):
                infer[(chosen, p)].add(c)
    for (chosen, p), kids_ in sorted(infer.items(), key=lambda kv: -len(kv[1])):
        if len(kids_) < 2 or chosen in parent or cycles(chosen, p) or same(by_id[chosen]["name"], by_id[p]["name"]): continue
        parent[chosen] = p
        out.append({"event_id": chosen, "parent_event_id": p, "source": "inferred", "confidence": 0.6,
                    "note": f"via {len(kids_)} members, e.g. {by_id[next(iter(kids_))]['name']}", "dates_ok": True, "preferred": True})
    for c, p in parent.items():
        by_id[c]["parent_event"] = p
    by_src = collections.Counter(o["source"] for o in out)
    report = [f"Membership (part_of) candidates: {len(out)} ({', '.join(f'{k} {v}' for k, v in sorted(by_src.items()))}); "
              f"dates outside the container: {bad_dates}; events with a preferred parent: {len(parent)}; "
              f"new container events: {len(new_events)} (NPS campaigns and Wikidata parents)"]
    return out, report
