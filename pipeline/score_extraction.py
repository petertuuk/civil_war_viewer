"""Score extracted claims for one unit against a hand-made answer key.

Matching is deliberately forgiving about wording and strict about dates:
  * unit_at / participated: same start month, start day within 2 days, and the
    names share a distinctive word (or overlap by at least a third). A claim of
    either type can match an answer of either type: whether "Advance to Falmouth"
    is a movement or an operation is a judgment call, so a type mismatch is
    reported separately instead of counted as a miss.
  * subordinate_to: same brigade/division/corps numbers (or same named command)
    and overlapping months.
  * unit_numbers: same scope and the same values for the fields both carry.

Usage:
    python pipeline/score_extraction.py claims.jsonl <unit_id> gold.json
"""
import json
import re
import sys
from collections import defaultdict

STOP = {"the", "of", "at", "to", "on", "in", "and", "battle", "battles", "near", "va", "md", "pa", "ky", "tenn",
        "ga", "ala", "ohio", "mich", "ill", "d", "c", "n", "s", "army", "operations", "duty", "moved", "action",
        "s", "campaign", "line", "river", "creek"}


def words(s):
    s = (s or "").lower().replace("spottsylvania", "spotsylvania").replace("kenesaw", "kennesaw")
    return {w for w in re.findall(r"[a-z]+", s) if w not in STOP and len(w) > 2}


def names_match(a, b):
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    common = wa & wb
    return bool(common) and (len(common) / min(len(wa), len(wb)) >= 0.34)


def ymd(s):
    if not s:
        return None
    parts = s.split("-")
    return int(parts[0]), int(parts[1]), (int(parts[2]) if len(parts) > 2 else None)


def dates_match(a, b):
    a, b = ymd(a), ymd(b)
    if not a or not b or a[:2] != b[:2]:
        return False
    return a[2] is None or b[2] is None or abs(a[2] - b[2]) <= 2


def parent_key(s):
    s = s.lower()
    nums = re.findall(r"(\d+)(?:st|nd|rd|th|d)\s+(brigade|division|army corps|corps)", s)
    if nums:
        return tuple((n, k.replace("army ", "")) for n, k in nums)
    return tuple(sorted(words(s)))


def months_overlap(a0, a1, b0, b1):
    def m(s, default):
        t = ymd(s)
        return t[0] * 12 + t[1] if t else default
    return m(a0, -1) <= m(b1, 10 ** 6) and m(b0, -1) <= m(a1, 10 ** 6)


def match(c, g):
    ct, gt = c["claim_type"], g["type"]
    if ct in ("unit_at", "participated") and gt in ("unit_at", "participated"):
        cn = c.get("place_mention") or c.get("event_mention")
        return dates_match(c.get("date_start"), g.get("date_start")) and names_match(cn, g["mention"])
    if ct == gt == "subordinate_to":
        return parent_key(c["parent_mention"]) == parent_key(g["mention"]) and \
            months_overlap(c.get("date_start"), c.get("date_end"), g.get("date_start"), g.get("date_end"))
    if ct == gt == "unit_numbers":
        if c.get("scope") != g.get("scope"):
            return False
        keys = [k for k in ("killed", "died_disease", "casualties_total", "strength") if c.get(k) and g.get(k)]
        return bool(keys) and all(c[k] == g[k] for k in keys)
    return False


def score(claims, gold):
    claims = [c for c in claims if c["claim_type"] in ("unit_at", "participated", "subordinate_to", "unit_numbers")]
    used, hits, type_mismatch = set(), [], []
    for gi, g in enumerate(gold):
        for ci, c in enumerate(claims):
            if ci in used or not match(c, g):
                continue
            used.add(ci)
            hits.append((g, c))
            if c["claim_type"] != g["type"]:
                type_mismatch.append((g, c))
            break
    hit_g = {id(g) for g, _ in hits}
    missed = [g for g in gold if id(g) not in hit_g]
    extra = [c for ci, c in enumerate(claims) if ci not in used]
    return hits, missed, extra, type_mismatch


def report(unit_id, claims, gold):
    hits, missed, extra, mism = score(claims, gold)
    by = defaultdict(lambda: [0, 0])
    for g in gold:
        by[g["type"]][1] += 1
    for g, _ in hits:
        by[g["type"]][0] += 1
    lines = [f"== {unit_id}", f"answer key: {len(gold)} claims; extracted: {len(claims)}; matched: {len(hits)} "
             f"({len(hits) / len(gold):.0%} of the key)"]
    for t, (h, n) in sorted(by.items()):
        lines.append(f"  {t:<15} {h}/{n}")
    if mism:
        lines.append(f"  type differs on {len(mism)} matches (movement vs operation): "
                     + "; ".join(f"{g['mention']} [{g['type']}->{c['claim_type']}]" for g, c in mism[:6]))
    lines.append("  missed:")
    lines += [f"    {g['type']:<14} {g.get('date_start')}  {g.get('mention')}" for g in missed] or ["    none"]
    dated_extra = [c for c in extra if c.get("date_start")]
    lines.append(f"  extracted but not in the key ({len(extra)}, {len(dated_extra)} dated):")
    lines += [f"    {c['claim_type']:<14} {c.get('date_start')}  "
              f"{c.get('place_mention') or c.get('event_mention') or c.get('parent_mention')}" for c in extra]
    return "\n".join(lines), len(hits), len(gold)


if __name__ == "__main__":
    src, unit_id, gold_path = sys.argv[1:4]
    claims = [json.loads(l) for l in open(src, encoding="utf-8")]
    claims = [c for c in claims if c["unit_id"] == unit_id]
    print(report(unit_id, claims, json.load(open(gold_path)))[0])
