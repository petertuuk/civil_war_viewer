"""Per-unit diff of two claim files: what a rule change added, removed and changed, grouped by unit.

    python3 pipeline/claims_diff.py <old file> <new file> [--units SUBSTR ...] [--max-units N] [--examples N]

Files: a claims .jsonl (data/dyers/claims_rules.jsonl, data/dyers/claims_rules_raw.jsonl, data/or/claims_or.jsonl, ...: one claim per
line, "unit_id" and "claim_type") or a derived/manual .json ({"claims": [...]}, as in data/derived/*.json: "unit" and "type").

A claim is identified by (type, date_start, kind of mention, mention text, first 60 characters of its source span). The same identity
on both sides with other values (confidence, date_end, place, portion, ...) is "changed" and the differing fields are shown; an
identity on one side only is "added" or "removed". Claims that are exact duplicates are counted, so a doubled claim shows as added.

Output: units ordered by the number of differences (the first --max-units, default 30; --units keeps only units whose id or name
contains one of the given strings), each with counts and up to --examples (default 3) examples per kind; totals at the end.
Exit status 0 when nothing differs, 1 otherwise.
"""
import json, sys
from collections import Counter, defaultdict

IGNORE = {"extracted_at", "note"}       # fields that say nothing about the claim itself
MENTION_FIELDS = ("place_mention", "event_mention", "parent_mention", "person_mention", "name", "target_mention", "scope")


def load(path):
    if path.endswith(".json"):
        rows = json.load(open(path, encoding="utf-8"))["claims"]
    else:
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return rows


def unit_of(c):
    if c.get("unit_id") not in (None, ""):
        return str(c["unit_id"])
    u = c.get("unit")
    if isinstance(u, dict):
        return str(u.get("nps_code") or u.get("dyer_id") or u.get("display_name") or c.get("unit_mention") or "?")
    return str(c.get("unit_mention") or "?")


def identity(c):
    t = c.get("claim_type") or c.get("type")
    kind = next((f for f in MENTION_FIELDS if c.get(f) not in (None, "")), "")
    return (t, c.get("date_start") or "", kind, str(c.get(kind) or ""), (c.get("source_span") or c.get("span") or "")[:60])


def group(rows):
    g = defaultdict(lambda: defaultdict(list))
    for c in rows:
        g[unit_of(c)][identity(c)].append(c)
    return g


def fields_changed(a, b):
    out = []
    for k in sorted((set(a) | set(b)) - IGNORE):
        if a.get(k) != b.get(k):
            out.append(f"{k}: {json.dumps(a.get(k), ensure_ascii=False)[:80]} -> {json.dumps(b.get(k), ensure_ascii=False)[:80]}")
    return out


def describe(c):
    t = c.get("claim_type") or c.get("type")
    kind = next((f for f in MENTION_FIELDS if c.get(f) not in (None, "")), "")
    return f"{t} {c.get('date_start') or ''}..{c.get('date_end') or ''} {str(c.get(kind) or '')[:70]}"


def main(argv):
    pos, opts = [], {"--units": [], "--max-units": 30, "--examples": 3}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--units":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                opts["--units"].append(argv[i]); i += 1
            continue
        if a in ("--max-units", "--examples"):
            opts[a] = int(argv[i + 1]); i += 2; continue
        pos.append(a); i += 1
    if len(pos) != 2:
        print(__doc__); return 2
    A, B = group(load(pos[0])), group(load(pos[1]))
    tot = Counter()
    rows = []
    for u in set(A) | set(B):
        if opts["--units"] and not any(s.lower() in u.lower() for s in opts["--units"]):
            continue
        add, rem, chg = [], [], []
        a, b = A.get(u, {}), B.get(u, {})
        for k in set(a) | set(b):
            la, lb = a.get(k, []), b.get(k, [])
            for x, y in zip(la, lb):
                d = fields_changed(x, y)
                if d:
                    chg.append((x, d))
            rem += la[len(lb):]
            add += lb[len(la):]
        if add or rem or chg:
            rows.append((len(add) + len(rem) + len(chg), u, add, rem, chg))
            tot["added"] += len(add); tot["removed"] += len(rem); tot["changed"] += len(chg)
    rows.sort(key=lambda r: (-r[0], r[1]))
    n_ex = opts["--examples"]
    for n, u, add, rem, chg in rows[:opts["--max-units"]]:
        print(f"{u}: +{len(add)} -{len(rem)} ~{len(chg)}")
        for c in add[:n_ex]:
            print("   added:  ", describe(c))
        for c in rem[:n_ex]:
            print("   removed:", describe(c))
        for c, d in chg[:n_ex]:
            print("   changed:", describe(c), "|", "; ".join(d[:3]))
    if len(rows) > opts["--max-units"]:
        print(f"... {len(rows) - opts['--max-units']} more units")
    print(f"units with differences: {len(rows)}; claims added {tot['added']}, removed {tot['removed']}, changed {tot['changed']}"
          f" (old {sum(len(v) for g in A.values() for v in g.values())}, new {sum(len(v) for g in B.values() for v in g.values())} claims)")
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
