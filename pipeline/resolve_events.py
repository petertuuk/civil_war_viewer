"""Group Dyer's event index into canonical events, then resolve regimental battle mentions to them.

Step 1, grouping. Index entries in the same state, with the same dates and a fighting
type (battle, engagement, action, combat, assault, attack, siege) or both campaigns,
become one canonical event with several names: Bull Run / Manassas, Antietam /
Sharpsburg, Hatcher's Run / Dabney's Mill. Skirmishes are never merged by date alone,
since many happened in one state on one day.

Step 2, resolution. Each 'participated' claim from Part III is matched to canonical
events whose dates overlap (within a day) and whose names share the distinctive words
of the place. A state named in the mention must agree. One clear winner = resolved;
several close candidates = ambiguous; none = unresolved.

Usage:
    python pipeline/resolve_events.py data/dyers/event_index.jsonl data/dyers/claims_rules.jsonl data/dyers
Writes events.jsonl, event_resolution.jsonl and resolution_report.txt.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

FIGHT = {"battle", "engagement", "action", "combat", "assault", "attack", "siege"}
SPELLING = [(r"spottsylvania", "spotsylvania"), (r"kenesaw", "kennesaw"), (r"chattahoochie", "chattahoochee"),
            (r"\bmission ridge", "missionary ridge"), (r"stone'?s river", "stones river"), (r"\bmills\b", "mill"),
            (r"court\s*house|c\.\s*h\.?", "courthouse"), (r"\bmt\.?\s", "mount "), (r"\bft\.?\s", "fort "),
            (r"averysboro|averasborough", "averasboro"), (r"reconnoissance", "reconnaissance"),
            (r"peach tree", "peachtree"), (r"borough\b", "boro"), (r"boydton plank road", "boydton plank road"), (r"\bst\.?\s", "saint ")]
STATE_HINT = {"va": "VA", "md": "MD", "pa": "PA", "ga": "GA", "tenn": "TN", "ky": "KY", "ala": "AL", "miss": "MS",
              "la": "LA", "ark": "AR", "mo": "MO", "n c": "NC", "s c": "SC", "w va": "WV", "fla": "FL", "tex": "TX",
              "texas": "TX", "ind t": "IT", "i t": "IT", "kan": "KS", "n m": "NM", "n mex": "NM", "dak": "DT",
              "minn": "MN", "ohio": "OH", "ind": "IN", "ill": "IL"}
LEAD = re.compile(r"^(?:battles?|engagements?|actions?|skirmish(?:es)?|combats?|affairs?|siege|assaults?|attacks?|"
                  r"operations|expedition|reconnaissance|reconnoissance|raid|scout|occupation|capture|pursuit|"
                  r"advance|demonstrations?|campaign|near|about|against|on|at|of|to|from|in|the|and|line|"
                  r"before|front|around|up|down|with|toward|towards)\b[\s,]*", re.I)
STOP = {"the", "of", "and", "at", "on", "to", "near", "river", "creek", "road", "station", "landing", "va", "ga",
        "tenn", "md", "pa", "ky", "miss", "ala", "la", "ark", "mo", "n", "s", "c", "w", "fla", "campaign",
        "battle", "battles", "operations", "line", "s", "lines", "front", "against", "from", "mill", "house"}


def iso(s, end=False):
    if not s:
        return None
    p = [int(x) for x in s.split("-")]
    if len(p) == 2:
        if end:
            nxt = date(p[0] + (p[1] == 12), p[1] % 12 + 1, 1)
            return date.fromordinal(nxt.toordinal() - 1)
        return date(p[0], p[1], 1)
    try:
        return date(*p)
    except ValueError:
        return None


def norm(s):
    s = (s or "").lower()
    for a, b in SPELLING:
        s = re.sub(a, b, s)
    return s


def core_words(s):
    s = norm(s)
    s = re.sub(r"\([^)]*\)", " ", s)
    words = re.findall(r"[a-z]+", s.replace("'", ""))
    return {w for w in words if w not in STOP and len(w) > 2}


def state_hint(mention):
    m = re.search(r"(?:,|\()\s*((?:[nsw]\.\s*)?[a-z]+\.?(?:\s*[a-z]\.)?)\s*\)?\s*$", (mention or "").lower())
    if not m:
        return None
    key = re.sub(r"[.\s]+", " ", m.group(1)).strip()
    return STATE_HINT.get(key)


def type_class(t):
    if t in FIGHT:
        return "fight"
    if t == "campaign":
        return "campaign"
    return t


# ------------------------------------------------------------------ step 1: grouping
def group_events(index_rows):
    ev = [r for r in index_rows if r["kind"] == "event"]
    groups = defaultdict(list)
    singles = []
    for r in ev:
        tc = type_class(r["type"])
        if r["date_start"] and r["state"] and tc in ("fight", "campaign"):
            groups[(r["state"], r["date_start"], r["date_end"], tc)].append(r)
        else:
            singles.append([r])
    canon = []
    for key, rows in groups.items():
        # Battles and campaigns on the same dates in one state are the same event under several names.
        # Smaller fights join only when they share a word with a name already in the group, since
        # busy days held several separate actions (McDowell and Sewell's Point, May 8, 1862).
        core = [r for r in rows if r["type"] in ("battle", "campaign", "siege")]
        rest = [r for r in rows if r not in core]
        clusters = [core] if core else []
        for r in rest:
            w = core_words(r["place"])
            for c in clusters:
                if any(w & core_words(x["place"]) for x in c):
                    c.append(r)
                    break
            else:
                clusters.append([r])
        canon += clusters
    canon += singles
    events = []
    for i, rows in enumerate(sorted(canon, key=lambda rs: (rs[0]["date_start"] or "9999", rs[0]["place"]))):
        names = []
        for r in rows:
            n = re.sub(r"\s+", " ", r["place"]).strip()
            if n not in names:
                names.append(n)
        rank = {"battle": 0, "siege": 1, "campaign": 1, "engagement": 2, "combat": 3, "action": 3, "assault": 4, "attack": 4}
        main = sorted(rows, key=lambda r: rank.get(r["type"], 9))[0]
        events.append({"event_id": f"ev{i:05d}", "name": names[0] if len(names) == 1 else " / ".join(names),
                       "names": names, "type": main["type"], "state": main["state"],
                       "date_start": main["date_start"], "date_end": main["date_end"],
                       "index_ids": [r["id"] for r in rows], "pages": sorted({r["page"] for r in rows})})
    return events


# ------------------------------------------------------------------ step 2: resolution
import difflib
_FUZZ = {}


def fuzzy(word, vocab):
    """Close spellings of a word in the index vocabulary (OCR: 'spottsvlvania')."""
    if word not in _FUZZ:
        _FUZZ[word] = difflib.get_close_matches(word, vocab, n=3, cutoff=0.8) if len(word) >= 5 else []
    return _FUZZ[word]


def build_lookup(events):
    by_word = defaultdict(set)
    for i, e in enumerate(events):
        e["_words"] = set().union(*(core_words(n) for n in e["names"])) if e["names"] else set()
        e["_d0"], e["_d1"] = iso(e["date_start"]), iso(e["date_end"], end=True) or iso(e["date_start"], end=True)
        for w in e["_words"]:
            by_word[w].add(i)
    return by_word


def candidates(claim, events, by_word):
    m = claim.get("event_mention") or ""
    core = LEAD.sub("", norm(m))
    while LEAD.match(core):
        core = LEAD.sub("", core)
    words = core_words(core)
    if not words:
        return [], words
    d0, d1 = iso(claim.get("date_start")), iso(claim.get("date_end"), end=True)
    if not d0:
        return [], words
    d1 = d1 or d0
    st = state_hint(m)
    pool = set()
    vocab = by_word.keys()
    expanded = set(words)
    for w in words:
        if w in by_word:
            pool |= by_word[w]
        else:
            for f in fuzzy(w, list(vocab)):
                pool |= by_word[f]
                expanded.add(f)
    out = []
    for i in pool:
        e = events[i]
        if not e["_d0"]:
            continue
        if e["_d0"].toordinal() > d1.toordinal() + 1 or (e["_d1"] or e["_d0"]).toordinal() < d0.toordinal() - 1:
            continue
        if st and e["state"] and st != e["state"]:
            continue
        common = expanded & e["_words"]
        if not common:
            continue
        name_score = min(1.0, len(common) / len(words))
        # prefer same span and fighting events when the mention names a battle
        span_pen = abs(e["_d0"].toordinal() - d0.toordinal()) + abs((e["_d1"] or e["_d0"]).toordinal() - d1.toordinal())
        is_campaign_m = "campaign" in m.lower()
        type_bonus = 0.15 if (is_campaign_m == (e["type"] == "campaign")) else -0.3
        if e["type"] in FIGHT and re.search(r"battle|assault|siege", m, re.I):
            type_bonus += 0.1
        score = name_score + type_bonus - min(span_pen, 30) * 0.01
        out.append((round(score, 3), i))
    return sorted(out, reverse=True), words


def resolve(claims, events):
    by_word = build_lookup(events)
    results = []
    for c in claims:
        if c["claim_type"] != "participated" or not c.get("date_start"):
            continue
        cands, words = candidates(c, events, by_word)
        if not cands:
            status, best = "unresolved", None
        elif len(cands) == 1 or cands[0][0] - cands[1][0] >= 0.1:
            status, best = ("resolved" if cands[0][0] >= 0.5 else "weak"), cands[0][1]
        else:
            status, best = "ambiguous", cands[0][1]
        results.append({"unit_id": c["unit_id"], "mention": c["event_mention"], "date_start": c["date_start"],
                        "date_end": c["date_end"], "status": status,
                        "event_id": events[best]["event_id"] if best is not None else None,
                        "event_name": events[best]["name"] if best is not None else None,
                        "score": cands[0][0] if cands else None,
                        "alternatives": [events[i]["event_id"] for _, i in cands[1:4]]})
    return results


def main(index_path, claims_path, out_dir):
    out = Path(out_dir)
    index_rows = [json.loads(l) for l in open(index_path, encoding="utf-8")]
    events = group_events(index_rows)
    claims = [json.loads(l) for l in open(claims_path, encoding="utf-8")]
    res = resolve(claims, events)

    with open(out / "events.jsonl", "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps({k: v for k, v in e.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
    with open(out / "event_resolution.jsonl", "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    multi = [e for e in events if len(e["names"]) > 1]
    st = Counter(r["status"] for r in res)
    uses = Counter(r["event_id"] for r in res if r["status"] == "resolved")
    unres = Counter(re.sub(r"[,.]?\s*\(?[A-Z][a-z]{0,4}\.?\)?$", "", r["mention"]) for r in res if r["status"] == "unresolved")
    via_alias = Counter()
    ev_by_id = {e["event_id"]: e for e in events}
    for r in res:
        if r["status"] == "resolved" and len(ev_by_id[r["event_id"]]["names"]) > 1:
            via_alias[(r["mention"], r["event_name"])] += 1
    rep = [f"Index entries: {sum(1 for r in index_rows if r['kind'] == 'event')}; canonical events: {len(events)}; "
           f"events with more than one name: {len(multi)}", "",
           f"Regimental battle mentions with dates: {len(res)}"]
    rep += [f"  {k:<11} {v:>6}  {v / len(res):.0%}" for k, v in st.most_common()]
    rep += ["", "Events with more than one name (first 60, by date):"]
    rep += [f"  {e['date_start']}  {e['state'] or '--'}  {e['type']:<10} {' | '.join(e['names'])}" for e in multi[:60]]
    rep += ["", "Most-cited resolved events:"]
    rep += [f"  {n:>5}  {ev_by_id[i]['date_start']}  {ev_by_id[i]['name']}" for i, n in uses.most_common(25)]
    rep += ["", "Mentions resolved to multi-name events (sample):"]
    rep += [f"  {n:>4}  {m!r} -> {name}" for (m, name), n in via_alias.most_common(30)]
    rep += ["", "Most common unresolved mentions:"]
    rep += [f"  {n:>5}  {m}" for m, n in unres.most_common(40)]
    amb = [r for r in res if r["status"] == "ambiguous"][:25]
    rep += ["", "Ambiguous (sample):"]
    rep += [f"  {r['date_start']}  {r['mention']!r} -> {r['event_name']} (+{len(r['alternatives'])} more)" for r in amb]
    (out / "resolution_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:8]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
