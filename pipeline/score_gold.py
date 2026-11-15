"""Score civil_war.db against the hand-checked test set (data/gold/units/*.txt).

For each regiment: recall of the answer key's engagements (P lines), how many were found
only through event membership (a battle claim covering a campaign line), claims resolved to
an event with the wrong dates, and, where the key is complete, precision (database events
for the unit that match no line of the key).

Usage: python pipeline/score_gold.py civil_war.db data/gold/units data/events/events.jsonl out.txt [detail.jsonl]
"""
from cwv import paths
import json, re, sqlite3, sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

STOP = {"the", "of", "at", "to", "on", "in", "and", "near", "battle", "battles", "va", "md", "pa", "ky", "tenn", "ga",
        "ala", "miss", "mo", "ark", "la", "tex", "fla", "n", "s", "c", "d", "w", "mich", "ohio", "ill", "action",
        "skirmish", "skirmishes", "affair", "engagement", "operations", "about", "against", "from", "with", "or",
        "line", "before", "court", "house", "h", "co", "cos", "first", "second", "third", "assault", "assaults",
        "capture", "occupation", "expedition", "reconnoissance", "reconnaissance", "campaign", "siege", "his", "army"}
SPELL = {"spottsylvania": "spotsylvania", "kenesaw": "kennesaw", "chattahoochie": "chattahoochee",
         "sumpter": "sumter", "opequan": "opequon", "legaresville": "legareville", "peeble": "peebles",
         "shephardstown": "shepherdstown", "maryes": "marye", "manassas": "bull", "sharpsburg": "antietam",
         "murfreesboro": "stones", "elkhorn": "pea", "mission": "missionary", "fairoaks": "seven",
         "averysboro": "averasboro", "jettersville": "jetersville", "lacy": "lacey", "glorietta": "glorieta",
         "canon": "canyon", "smithburg": "smithsburg", "littleton": "littlestown", "oostenaula": "oostanaula",
         "baldwin": "baldwyn", "forest": "forrest", "colliersville": "collierville", "lafayette": "fayette",
         "reconnoissance": "reconnaissance", "nottaway": "nottoway", "mckinzie": "mckenzie", "mckinzies": "mckenzies",
         "riddell": "riddells", "pittinger": "pittenger", "lavergne": "vergne", "readyville": "readyville",
         "sailors": "saylers", "sayler": "saylers", "sailor": "saylers", "dane": "ane", "poison": "poison",
         "springs": "spring", "ivey": "ivy", "iveys": "ivy", "gaines": "gaines", "golding": "goldings",
         "tunnell": "tunnel", "allegheny": "allegheny", "rockcastle": "rockcastle", "brucetown": "brucetown",
         "boies": "boise", "peachtree": "peach", "kennesaw": "kennesaw"}
CONTAINER = re.compile(r"\b(campaign|siege|operations|expedition|raid|pursuit)\b", re.I)


def words(s):
    s = (s or "").lower().replace("'s", "s").replace("’s", "s").replace("stone's", "stones")
    out = set()
    s = s.replace("la fayette", "fayette").replace("la grange", "lagrange").replace("la vergne", "vergne")
    for w in re.findall(r"[a-z]+", s):
        w = SPELL.get(w, w)
        if w not in STOP and len(w) > 2 and w != "tree":
            out.add(w)
    return out


def pdate(s, end=False):
    if not s:
        return None
    p = [int(x) for x in s.split("-")]
    if len(p) == 1:
        return date(p[0], 12, 31) if end else date(p[0], 1, 1)
    if len(p) == 2:
        if end:
            nxt = date(p[0] + (p[1] == 12), p[1] % 12 + 1, 1)
            return nxt - timedelta(days=1)
        return date(p[0], p[1], 1)
    for d in range(p[2], 0, -1):               # a bad day in a source date (February 30) is clamped
        try:
            return date(p[0], p[1], d)
        except ValueError:
            continue
    return date(p[0], p[1], 1)


def span(a, b):
    s, e = pdate(a), pdate(b or a, True)
    return (s, e) if s and e else None


def overlap(x, y, slack=3):
    if not x or not y:
        return False
    d = timedelta(days=slack)
    return x[0] - d <= y[1] and y[0] - d <= x[1]


def name_score(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    c = wa & wb
    return len(c) / min(len(wa), len(wb)) if c else 0.0


def unit_ids(head, c, name):
    """Database ids of the key's unit (and same_as units). `unit_key:` / `same_as_keys:` (Dyer's id or nps:CODE; permanent, see
    unit_registry.py) win over the older `db_unit:` / `same_as:` numbers, which are only checked."""
    def one(key):
        scheme, val = ("nps", key[4:]) if key.startswith("nps:") else ("dyer", key)
        r = c.execute("SELECT entity_id FROM external_id WHERE entity_type='unit' AND scheme=? AND value=?", (scheme, val)).fetchone()
        if not r:
            raise SystemExit(f"score_gold: {name}: unit key {key} is not in the database")
        return r[0]
    if "unit_key" in head:
        ids = [one(head["unit_key"])] + [one(k) for k in head.get("same_as_keys", "").replace(",", " ").split()]
        old = [int(head["db_unit"])] + [int(x) for x in head.get("same_as", "").replace(",", " ").split()] if "db_unit" in head else None
        if old and old != ids:
            print(f"score_gold: {name}: db_unit numbers {old} are out of date (keys give {ids}); the keys are used")
        return ids
    return [int(head["db_unit"])] + [int(x) for x in head.get("same_as", "").replace(",", " ").split()]


def read_key(p):
    head, items = {}, []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        if ln[:2] in ("P ", "M ", "? "):
            t, rest = ln[0], ln[2:]
            f = [x.strip() for x in rest.split("|")]
            d = f[0].split()[0] if f[0] else ""
            name = f[1] if len(f) > 1 else ""
            a, _, b = d.partition("/")
            items.append({"type": t, "start": a, "end": b or a, "span": span(a, b or a), "name": name,
                          "sources": (f[2].split() if len(f) > 2 else []), "note": f[3] if len(f) > 3 else ""})
        else:
            k, _, v = ln.partition(":")
            head[k.strip()] = v.strip()
    return head, items


SRC = {"regex:dyers_v1": "dyers", "regex:or_org_v1": "or", "wikitext:oob_v1": "wikipedia", "manual": "manual"}


def main(db, keys_dir, events_path, out_path, detail_path=None):
    ev_dates = {}
    for l in open(events_path, encoding="utf-8"):
        e = json.loads(l)
        ev_dates[e["event_id"]] = (e.get("date_start"), e.get("date_end"), e.get("name"))
    c = sqlite3.connect(db)
    pe = dict(c.execute("SELECT entity_id, value FROM external_id WHERE entity_type='event' AND scheme='pipeline_event'"))
    EV = {}
    for i, kind, name, parent in c.execute("SELECT id, kind, display_name, parent_event_id FROM event"):
        ds = ev_dates.get(pe.get(i), (None, None, None))
        EV[i] = {"name": name, "kind": kind, "parent": parent, "span": span(ds[0], ds[1])}
    lines, details, tot = [], [], Counter()
    by_side = defaultdict(Counter)
    for kp in sorted(Path(keys_dir).glob("*.txt")):
        head, items = read_key(kp)
        uids = unit_ids(head, c, kp.name)
        claims = c.execute(f"""SELECT cp.claim_id, cp.unit_id, cp.event_mention, cp.event_id, cp.date_start, cp.date_end, cl.extracted_by
            FROM claim_participated cp JOIN claim cl ON cl.id=cp.claim_id WHERE cp.unit_id IN ({','.join('?'*len(uids))})""", uids).fetchall()
        cl = [{"id": r[0], "unit": r[1], "mention": r[2], "event": r[3], "span": span(r[4], r[5]) or (EV.get(r[3], {}).get("span")),
               "src": SRC.get(r[6], r[6])} for r in claims]
        # candidate pairs (gold item, claim)
        pairs = []
        for gi, g in enumerate(items):
            gc = bool(CONTAINER.search(g["name"]))
            for ci, x in enumerate(cl):
                en = EV.get(x["event"], {}).get("name", "")
                nm, ne = name_score(g["name"], x["mention"]), name_score(g["name"], en)
                if max(nm, ne) < 0.34 or not overlap(g["span"], x["span"]):
                    continue
                xc = bool(CONTAINER.search(x["mention"] or "")) if nm >= 0.34 else bool(CONTAINER.search(en))
                pairs.append(((gc == xc), nm, ne, gi, ci))
        pairs.sort(reverse=True)
        # a claim supports one key line; a key line can take many claims (several sources) but only of its best kind
        g_claims, c_used = defaultdict(list), set()
        best_kind = {}
        for kind_ok, nm, ne, gi, ci in pairs:          # pass 1: one claim per line, best pairs first
            if ci in c_used or gi in g_claims:
                continue
            best_kind[gi] = kind_ok
            g_claims[gi].append(ci); c_used.add(ci)
        for kind_ok, nm, ne, gi, ci in pairs:          # pass 2: other sources' claims join a matched line
            if ci in c_used or gi not in g_claims or best_kind[gi] != kind_ok:
                continue
            g_claims[gi].append(ci); c_used.add(ci)
        # unit's events and their ancestors (for roll-up)
        unit_events = {x["event"] for x in cl if x["event"]}
        anc = set()
        for e in unit_events:
            p, k = EV.get(e, {}).get("parent"), 0
            while p and k < 8:
                anc.add(p); p = EV.get(p, {}).get("parent"); k += 1
        res = Counter()
        miss, misres, rolled = [], [], []
        src_found = defaultdict(Counter)
        for gi, g in enumerate(items):
            if g["type"] != "P":
                continue
            res["key"] += 1
            got = [cl[ci] for ci in g_claims.get(gi, [])]
            if got:
                ok = [x for x in got if x["event"] and (EV.get(x["event"], {}).get("span") is None
                      or overlap(g["span"], EV[x["event"]]["span"], 3))]
                res["found"] += 1
                if not ok:
                    res["misresolved"] += 1
                    misres.append((g, [(x["mention"], x["event"], EV.get(x["event"], {}).get("name"), EV.get(x["event"], {}).get("span")) for x in got]))
                for s in {x["src"] for x in got}:
                    src_found[s]["found"] += 1
                continue
            # roll-up: an ancestor of the unit's events matches this line
            hit = [a for a in anc if name_score(g["name"], EV[a]["name"]) >= 0.34 and overlap(g["span"], EV[a]["span"])]
            if hit:
                res["rolled"] += 1; rolled.append((g, EV[hit[0]]["name"]))
            else:
                res["missing"] += 1; miss.append(g)
        # precision: distinct events for the unit not matched to any line
        matched_events = {cl[ci]["event"] for gi in g_claims for ci in g_claims[gi]}
        def chain(e):
            out, p, k = [], EV.get(e, {}).get("parent"), 0
            while p and k < 8:
                out.append(p); p = EV.get(p, {}).get("parent"); k += 1
            return out
        matched_anc = {a for e in matched_events for a in chain(e)}
        extra_events, consistent = defaultdict(list), set()
        for i, x in enumerate(cl):
            if i in c_used or x["event"] in matched_events:
                continue
            e = x["event"]
            en = EV.get(e, {}).get("name", "") or x["mention"]
            if e and (set(chain(e)) & matched_events or e in matched_anc or any(
                    max(name_score(g["name"], en), name_score(g["name"], x["mention"])) >= 0.34 and overlap(g["span"], x["span"]) for g in items)):
                consistent.add(e); continue
            extra_events[e].append(x)
        n_events = len({x["event"] for x in cl} - consistent)
        complete = head.get("complete", "no").startswith("y")
        res["db_events"] = n_events; res["extra_events"] = len(extra_events)
        side = head.get("side", "?")
        for k in ("key", "found", "rolled", "missing", "misresolved", "db_events", "extra_events"):
            tot[k] += res[k]; by_side[side][k] += res[k]
        if complete:
            by_side[side]["prec_events"] += n_events; by_side[side]["prec_extra"] += len(extra_events)
        rec = (res["found"] + res["rolled"]) / max(1, res["key"])
        lines.append(f"\n## {head.get('unit')} (db {','.join(map(str, uids))}; key {'complete' if complete else 'battle-level'})")
        lines.append(f"  key lines {res['key']}: found {res['found']}, via membership {res['rolled']}, missing {res['missing']}"
                     f"  -> recall {rec:.0%};  resolved to wrong-dated event {res['misresolved']}")
        lines.append(f"  database events for unit {n_events}; matching no key line {len(extra_events)}"
                     + (f" -> precision {1 - len(extra_events) / max(1, n_events):.0%}" if complete else " (key not complete: review)"))
        lines.append("  found by source: " + ", ".join(f"{s} {v['found']}" for s, v in sorted(src_found.items())))
        for g in miss:
            lines.append(f"  MISSING   {g['start']}{'/' + g['end'] if g['end'] != g['start'] else ''} {g['name']} [{' '.join(g['sources'])}]")
        for g, a in rolled:
            lines.append(f"  ROLLED    {g['name']} <- {a}")
        for g, xs in misres:
            for m, e, en, sp in xs[:2]:
                lines.append(f"  WRONG-EV  {g['start']} {g['name']}: claim '{m}' -> ev {e} '{en}' {sp[0] if sp else ''}..{sp[1] if sp else ''}")
        for e, xs in sorted(extra_events.items(), key=lambda kv: str(kv[1][0]['span'])):
            x = xs[0]
            lines.append(f"  EXTRA     {x['span'][0] if x['span'] else '?'} '{x['mention']}' -> ev {e} '{EV.get(e, {}).get('name')}' [{','.join(sorted({y['src'] for y in xs}))}]")
        details.append({"unit": head.get("unit"), **res, "complete": complete})
    summ = ["Test set scores", f"regiments {len(details)}"]
    for side, t in sorted(by_side.items()):
        r = (t["found"] + t["rolled"]) / max(1, t["key"])
        summ.append(f"{side}: key lines {t['key']}, found {t['found']} + membership {t['rolled']} -> recall {r:.1%}; "
                    f"missing {t['missing']}; wrong-dated event {t['misresolved']}"
                    + (f"; precision (complete keys) {1 - t['prec_extra'] / max(1, t['prec_events']):.1%} of {t['prec_events']} events" if t["prec_events"] else ""))
    Path(out_path).write_text("\n".join(summ + lines) + "\n", encoding="utf-8")
    if detail_path:
        Path(detail_path).write_text("\n".join(json.dumps(d) for d in details) + "\n")
    from metrics import record
    record("score_gold", regiments=len(details),
           by_side={s: {**{k: t[k] for k in ("key", "found", "rolled", "missing", "misresolved", "prec_events", "prec_extra")},
                        "recall": round((t["found"] + t["rolled"]) / max(1, t["key"]), 4)} for s, t in sorted(by_side.items())})
    print("\n".join(summ))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("score_gold")))
