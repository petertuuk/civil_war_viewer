"""Small helpers shared by the pipeline scripts: distance, dates, the GNIS index.

too_fast(km, days)  the one test for an impossible move: over 300 km and faster than 250 km a day (rail and steamer
                    moves are allowed; the same day counts as one day); allow_km widens it by a place's precision
km(a, b)            great-circle distance in km between (lat, lon) pairs (haversine, Earth diameter 12,742 km)
D0, day_num(s)      day number from 1861-01-01 and its slack: '1862-10-05' -> (n, 0); '1862-10' -> (mid-month, 15);
                    '1862' -> (July 1, 180); None or unparsable -> (None, 0)
parse_date(s, end)  date of an ISO string at day / month / year precision: a month or a year gives its first day, or its
                    last with end=True; an impossible day ("1863-02-30") gives the 28th; None -> None
first_day(s)        a day, or the 1st of a month ('1862-10' -> 1862-10-01); None when it does not parse
gnis_rows(path)     the GNIS index rows (with data/external/gnis/gnis_extra.tsv after them):
                    (norm name, state, lat, lon, class, county, id, name, kind)
"""
import math
from datetime import date, timedelta
from pathlib import Path

D0 = date(1861, 1, 1)
MIN_KM, MAX_KMDAY = 300, 250


def too_fast(d_km, days, allow_km=0.0):
    return d_km - allow_km > max(MIN_KM, MAX_KMDAY * max(1, days))


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1, h)))


def day_num(s):
    if not s:
        return None, 0
    p = s[:10].split("-")
    try:
        if len(p) == 3:
            return (date(int(p[0]), int(p[1]), int(p[2])) - D0).days, 0
        if len(p) == 2:
            return (date(int(p[0]), int(p[1]), 15) - D0).days, 15
        return (date(int(p[0]), 7, 1) - D0).days, 180
    except ValueError:
        return None, 0


def parse_date(s, end=False):
    if not s:
        return None
    p = [int(x) for x in s[:10].split("-")]
    try:
        if len(p) == 3:
            return date(*p)
        if len(p) == 2:
            return (date(p[0] + (p[1] == 12), p[1] % 12 + 1, 1) - timedelta(days=1)) if end else date(p[0], p[1], 1)
        return date(p[0], 12, 31) if end else date(p[0], 1, 1)
    except ValueError:
        return date(p[0], p[1], 28)


def first_day(s):
    s = (s or "")[:10]
    if len(s) == 7:
        s += "-01"
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def gnis_rows(path):
    from gnis_index import index_lines
    for line in index_lines(path):
        f = line.rstrip("\n").split("\t")
        yield (f[0], f[1], float(f[2]), float(f[3]), f[4], *f[5:])


def gnis_by_name(path, classes=None):
    """name -> [(state, lat, lon, class)] (classes: keep only these feature classes)."""
    from collections import defaultdict
    G = defaultdict(list)
    for nm, st, lat, lon, cl, *_ in gnis_rows(path):
        if classes is None or cl in classes:
            G[nm].append((st, lat, lon, cl))
    return G


def gnis_by_name_state(path, classes=None):
    """(name, state) -> [(lat, lon, class)]."""
    from collections import defaultdict
    G = defaultdict(list)
    for nm, st, lat, lon, cl, *_ in gnis_rows(path):
        if classes is None or cl in classes:
            G[(nm, st)].append((lat, lon, cl))
    return G
