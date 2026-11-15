"""Map coverage on sample days, from the exported viewer data (viewer/war/data): units per side with a fix covering the
day, split by kind (fix flag 0 known, 1 loose; segment from a derived estimate 2 brigade / 3 campaign). Moving
(between two fixes <= 21 days apart) is counted separately.
Usage: python pipeline/coverage.py viewer/war/data [YYYY-MM-DD ...]"""
from cwv import params
import json, sys
from collections import Counter
from datetime import date

DAYS = ["1861-07-21", "1862-06-30", "1862-12-13", "1863-07-31", "1863-08-15", "1863-12-31", "1864-02-15", "1864-04-30",
        "1864-08-15", "1864-12-31", "1865-04-09"]


def main(d, *days):
    units = json.load(open(f"{d}/units.json"))["units"]
    side = {k: ("Union", "Confederate")[v[1]] if isinstance(v[1], int) and v[1] in (0, 1) else str(v[1]) for k, v in units.items()}
    print(f"{'day':10s} {'side':12s} known loose est.brig est.camp moving")
    for ds in days or DAYS:
        t = (date.fromisoformat(ds) - date(1861, 1, 1)).days
        y = json.load(open(f"{d}/y{ds[:4]}.json"))
        fx = y["fixes"]
        c = Counter()
        for uid, segs in y["seg"].items():
            segs = sorted(segs)
            kind = None
            for i, s in enumerate(segs):
                if s[0] <= t <= s[1]:
                    f = fx[s[2]]
                    kind = {0: "known", 1: "loose", 2: "est.brig", 3: "est.camp"}.get(f[4], "known")
                    break
                if i and segs[i - 1][1] < t < s[0] and s[0] - segs[i - 1][1] <= params.MARCH_GAP_DAYS:
                    kind = "moving"; break
            if kind:
                c[(side.get(uid), kind)] += 1
        for sd in ("Union", "Confederate"):
            print(f"{ds:10s} {sd:12s} " + " ".join(f"{c[(sd, k)]:5d}" for k in ("known", "loose", "est.brig", "est.camp", "moving")))


if __name__ == "__main__":
    main(*sys.argv[1:])
