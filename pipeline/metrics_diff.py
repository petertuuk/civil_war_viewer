"""Compare the metrics of two builds (roadmap T1.2): which headline numbers moved, with the tripwires called out.

    python3 pipeline/metrics_diff.py <reference dir> <new dir>

Both are project-shaped: <dir>/data/scores/metrics/*.json (written by metrics.py). Nested numbers are flattened to "script.key.sub".
Prints every metric that changed (reference -> new, difference), metrics only on one side, and a TRIPWIRE line for the ones that
the hand-offs say to watch after a change: two_places, fast jumps, outside_state, test-set recall, claims per extractor, linked
participations. Exit status 0 when nothing changed, 1 otherwise.
"""
import json
import sys
from pathlib import Path

TRIPWIRES = ("consistency_checks.rows_by_check.two_places", "consistency_checks.outside_state", "consistency_checks.test_set_misses",
             "fast_jumps.stats.fast jumps", "score_gold.by_side.", "db.claims_by_extracted_by.", "db.participated.", "db.unit_at.")


def flat(prefix, v, out):
    if isinstance(v, dict):
        for k, x in v.items():
            flat(f"{prefix}.{k}", x, out)
    else:
        out[prefix] = v


def load(d):
    out = {}
    for p in sorted(Path(d, "data/scores/metrics").glob("*.json")):
        flat(p.stem, json.load(open(p, encoding="utf-8")), out)
    return out


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    A, B = load(argv[0]), load(argv[1])
    if not A or not B:
        print(f"no metrics found in {'reference' if not A else 'new'} (expected data/scores/metrics/*.json)")
        return 2
    changed = [(k, A[k], B[k]) for k in sorted(set(A) & set(B)) if A[k] != B[k]]
    only_a, only_b = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    for k, a, b in changed:
        diff = f" ({b - a:+g})" if isinstance(a, (int, float)) and isinstance(b, (int, float)) else ""
        trip = "TRIPWIRE  " if k.startswith(TRIPWIRES) else "           "
        print(f"{trip}{k}: {a} -> {b}{diff}")
    for k in only_a:
        print(f"           only in reference: {k} = {A[k]}")
    for k in only_b:
        print(f"           only in new: {k} = {B[k]}")
    print(f"metrics compared: {len(set(A) & set(B))}; changed {len(changed)} "
          f"({sum(k.startswith(TRIPWIRES) for k, _, _ in changed)} tripwires); only in reference {len(only_a)}; only in new {len(only_b)}")
    return 1 if (changed or only_a or only_b) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
