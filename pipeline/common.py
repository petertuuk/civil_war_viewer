"""Small helpers shared by the pipeline scripts: distance, dates, the GNIS index.

too_fast(km, days)  the one test for an impossible move: over 300 km and faster than 250 km a day (rail and steamer
                    moves are allowed; the same day counts as one day); allow_km widens it by a place's precision
km(a, b)            great-circle distance in km between (lat, lon) pairs (haversine, Earth diameter 12,742 km)
D0, day_num(s)      day number from 1861-01-01 and its slack: '1862-10-05' -> (n, 0); '1862-10' -> (mid-month, 15);
                    '1862' -> (July 1, 180); None or unparsable -> (None, 0)
parse_date(s, end)  date of an ISO string at day / month / year precision: a month or a year gives its first day, or its
                    last with end=True; an impossible day ("1863-02-30") gives the 28th; None -> None
first_day(s)        a day, or the 1st of a month ('1862-10' -> 1862-10-01); None when it does not parse
stable_id(prefix, *parts, n=8)   prefix + first n hex of the sha1 of the parts: ids that depend on content, not on position
claim_fingerprint(...)         stable_id of a claim (extracted_by, unit key, type, date, locator, first 80 characters of the span, object)
gnis_rows(path)     the GNIS index rows (with data/external/gnis/gnis_extra.tsv after them):
                    (norm name, state, lat, lon, class, county, id, name, kind)
"""
from cwv import params
import hashlib
import math
from datetime import date, timedelta
from pathlib import Path

D0 = date(1861, 1, 1)
MIN_KM, MAX_KMDAY = params.MIN_KM, params.MAX_KMDAY


def stable_id(prefix, *parts, n=8):
    """prefix + the first n hex characters of the sha1 of the parts joined by '|' (None counts as empty): an id that depends only on
    what the thing is, so it survives a rebuild and an unrelated change elsewhere in a list."""
    h = hashlib.sha1("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}{h[:n]}"


def claim_fingerprint(extracted_by, unit_key, claim_type, date_start, locator, span, obj=None):
    """The identity of a claim across rebuilds (roadmap T2.4): who extracted what kind of claim about which unit (or, with no unit,
    which event/person/name), when, from where in the source, from which words, and what it says about the subject (obj: the event,
    place, commander or parent named: without it a list of commanders or of battles under one heading shares one fingerprint, 6%
    of claims). Twelve hex characters: 300,000 claims make a chance collision of eight (32 bits) likely."""
    return stable_id("c", extracted_by, unit_key, claim_type, date_start, locator, (span or "")[:80], obj, n=12)


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


# Rough state / territory bounding boxes (lat0, lat1, lon0, lon1). Used as a sanity check: a place said to be in a
# state must not be located outside it (Boston, Mass. was put at the median of where its regiments were a month later,
# in Virginia). Territories map to the modern states they mostly cover.
STATE_BOX = {'AL': (30.1, 35.1, -88.6, -84.8), 'AR': (33.0, 36.6, -94.7, -89.6), 'AZ': (31.3, 37.0, -114.9, -109.0),
    'CA': (32.5, 42.0, -124.5, -114.1), 'CO': (37.0, 41.0, -109.1, -102.0), 'CT': (40.9, 42.1, -73.8, -71.7),
    'DE': (38.4, 39.9, -75.8, -75.0), 'DC': (38.7, 39.1, -77.2, -76.9), 'FL': (24.4, 31.0, -87.7, -80.0),
    'GA': (30.3, 35.0, -85.7, -80.8), 'IA': (40.3, 43.6, -96.7, -90.1), 'ID': (42.0, 49.0, -117.3, -111.0),
    'IL': (36.9, 42.6, -91.6, -87.0), 'IN': (37.7, 41.8, -88.1, -84.7), 'KS': (36.9, 40.1, -102.1, -94.5),
    'KY': (36.4, 39.2, -89.6, -81.9), 'LA': (28.9, 33.1, -94.1, -88.8), 'MA': (41.2, 42.9, -73.6, -69.9),
    'MD': (37.9, 39.8, -79.5, -75.0), 'ME': (43.0, 47.5, -71.1, -66.9), 'MI': (41.6, 48.3, -90.5, -82.1),
    'MN': (43.4, 49.4, -97.3, -89.4), 'MO': (35.9, 40.7, -95.8, -89.1), 'MS': (30.1, 35.1, -91.7, -88.1),
    'MT': (44.3, 49.0, -116.1, -104.0), 'NC': (33.8, 36.6, -84.4, -75.4), 'ND': (45.9, 49.0, -104.1, -96.5),
    'NE': (40.0, 43.0, -104.1, -95.3), 'NH': (42.7, 45.3, -72.6, -70.6), 'NJ': (38.9, 41.4, -75.6, -73.9),
    'NM': (31.3, 37.0, -109.1, -103.0), 'NV': (35.0, 42.0, -120.0, -114.0), 'NY': (40.4, 45.1, -79.8, -71.8),
    'OH': (38.4, 42.0, -84.9, -80.5), 'OK': (33.6, 37.0, -103.0, -94.4), 'OR': (42.0, 46.3, -124.6, -116.4),
    'PA': (39.7, 42.3, -80.6, -74.7), 'RI': (41.1, 42.1, -71.9, -71.1), 'SC': (32.0, 35.3, -83.4, -78.5),
    'SD': (42.5, 46.0, -104.1, -96.4), 'TN': (34.9, 36.7, -90.4, -81.6), 'TX': (25.8, 36.5, -106.7, -93.5),
    'UT': (37.0, 42.0, -114.1, -109.0), 'VA': (36.5, 39.5, -83.7, -75.2), 'VT': (42.7, 45.1, -73.5, -71.4),
    'WA': (45.5, 49.0, -124.8, -116.9), 'WI': (42.4, 47.1, -92.9, -86.2), 'WV': (37.2, 40.7, -82.7, -77.7),
    'WY': (41.0, 45.0, -111.1, -104.0)}
STATE_BOX['DT'] = (42.5, 49.0, -104.1, -96.4)
STATE_BOX['IT'] = STATE_BOX['OK']
STATE_BOX['NT'] = STATE_BOX['NM']


def in_state(st, lat, lon, pad=0.3):
    """True / False when the state's box is known (VA and WV count as one), None otherwise."""
    if lat is None or lon is None:
        return None
    sts = {"VA", "WV"} if st in ("VA", "WV") else {st}
    boxes = [STATE_BOX[x] for x in sts if x in STATE_BOX]
    if not boxes:
        return None
    return any(b[0] - pad <= lat <= b[1] + pad and b[2] - pad <= lon <= b[3] + pad for b in boxes)

