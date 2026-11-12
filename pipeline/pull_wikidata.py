"""Pull American Civil War events from Wikidata (re-runnable).

Usage:
  python3 pipeline/pull_wikidata.py --test                 # can we reach Wikidata?
  python3 pipeline/pull_wikidata.py data/wikidata          # full pull
  python3 pipeline/pull_wikidata.py data/wikidata --offline  # rebuild from cached raw responses

Step 1 finds candidate items with several small discovery queries:
  partof : anything linked to the war (Q8676) by part-of (P361), any depth
  typed  : battles, sieges, campaigns, military operations, naval battles in the
           US or CSA dated 1861-1865, even with no part-of link
  typed_direct : same without subclass closure (fallback if 'typed' times out)
Step 2 fetches details in batches: English label and aliases, coordinates,
dates with precision (P585, P580, P582), part-of, classes, P131 (admin area,
with labels), P276 (location, with labels), P1448 official name, P1813 short name.

Output (same row format as before, plus new fields; official and short names
are also merged into 'aliases' so anchor_events.py picks them up unchanged):
  <out>/wikidata_civil_war_events_v2.json
  <out>/pull_report.txt
  <out>/raw/*.json   (cached responses, for --offline)
Only the standard library is used.
"""
import argparse, json, sys, time, urllib.parse, urllib.request
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "CivilWarViewer/0.2 (personal history research; python urllib)"
WAR = "Q8676"
COUNTRIES = "wd:Q30 wd:Q81931"                     # USA, Confederate States
CLASSES = ("wd:Q178561 wd:Q188055 wd:Q831663 "      # battle, siege, military campaign
           "wd:Q645883 wd:Q1261499 wd:Q476807")     # military operation, naval battle, military raid
DATE_FILTER = 'FILTER(?t >= "1861-01-01T00:00:00Z"^^xsd:dateTime && ?t < "1866-01-01T00:00:00Z"^^xsd:dateTime)'

DISCOVERY = {
    "partof": f"SELECT DISTINCT ?b WHERE {{ ?b wdt:P361+ wd:{WAR} . }}",
    "subclasses": f"""SELECT DISTINCT ?sub WHERE {{ VALUES ?cls {{ {CLASSES} }} ?sub wdt:P279* ?cls . }}""",
    "typed": None,   # built from the subclasses result (P279* inline times out)
    "typed_direct": f"""SELECT DISTINCT ?b WHERE {{
  VALUES ?cls {{ {CLASSES} }} VALUES ?c {{ {COUNTRIES} }}
  ?b wdt:P31 ?cls ; wdt:P17 ?c .
  {{ ?b wdt:P585 ?t }} UNION {{ ?b wdt:P580 ?t }}
  {DATE_FILTER} }}""",
    "typed_geo": None,    # event classes, 1861-65, coordinates inside the US box (many lack P17)
    "typed_desc": None,   # event classes whose English description mentions the Civil War
    "conflict": f"""SELECT DISTINCT ?b WHERE {{
  ?b wdt:P607 wd:{WAR} . FILTER NOT EXISTS {{ ?b wdt:P31 wd:Q5 }} }}""",  # items whose 'conflict' is the war (not people)
}

DETAILS = """SELECT ?b
  (SAMPLE(?lab) AS ?label)
  (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
  (SAMPLE(?co) AS ?coord)
  (SAMPLE(?pit0) AS ?pit) (SAMPLE(?pitp0) AS ?pit_prec)
  (SAMPLE(?st0) AS ?start) (SAMPLE(?stp0) AS ?start_prec)
  (SAMPLE(?en0) AS ?end) (SAMPLE(?enp0) AS ?end_prec)
  (GROUP_CONCAT(DISTINCT ?part; separator="|") AS ?parts)
  (GROUP_CONCAT(DISTINCT ?cls; separator="|") AS ?classes)
  (GROUP_CONCAT(DISTINCT ?loc; separator="|") AS ?locs)
  (GROUP_CONCAT(DISTINCT ?locLab; separator="|") AS ?loc_labels)
  (GROUP_CONCAT(DISTINCT ?pl; separator="|") AS ?places)
  (GROUP_CONCAT(DISTINCT ?plLab; separator="|") AS ?place_labels)
  (GROUP_CONCAT(DISTINCT ?off; separator="|") AS ?official_names)
  (GROUP_CONCAT(DISTINCT ?sh; separator="|") AS ?short_names)
WHERE {
  VALUES ?b { %s }
  OPTIONAL { ?b rdfs:label ?lab FILTER(LANG(?lab) = "en") }
  OPTIONAL { ?b skos:altLabel ?alias FILTER(LANG(?alias) = "en") }
  OPTIONAL { ?b wdt:P625 ?co }
  OPTIONAL { ?b p:P585/psv:P585 [ wikibase:timeValue ?pit0 ; wikibase:timePrecision ?pitp0 ] }
  OPTIONAL { ?b p:P580/psv:P580 [ wikibase:timeValue ?st0 ; wikibase:timePrecision ?stp0 ] }
  OPTIONAL { ?b p:P582/psv:P582 [ wikibase:timeValue ?en0 ; wikibase:timePrecision ?enp0 ] }
  OPTIONAL { ?b wdt:P361 ?part }
  OPTIONAL { ?b wdt:P31 ?cls }
  OPTIONAL { ?b wdt:P131 ?loc . OPTIONAL { ?loc rdfs:label ?locLab FILTER(LANG(?locLab) = "en") } }
  OPTIONAL { ?b wdt:P276 ?pl . OPTIONAL { ?pl rdfs:label ?plLab FILTER(LANG(?plLab) = "en") } }
  OPTIONAL { ?b wdt:P1448 ?off }
  OPTIONAL { ?b wdt:P1813 ?sh }
} GROUP BY ?b"""


REFRESH = False


def run(query, raw_path, offline, tries=4):
    if offline or (not REFRESH and Path(raw_path).exists() and Path(raw_path).stat().st_size > 50):
        return json.load(open(raw_path, encoding="utf-8"))   # resume from cache
    data = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for attempt in range(tries):
        req = urllib.request.Request(ENDPOINT, data=data, headers={
            "User-Agent": UA, "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                js = json.load(r)
            raw_path.write_text(json.dumps(js), encoding="utf-8")
            return js
        except Exception as e:                       # 429/5xx/timeouts: back off and retry
            wait = 5 * 2 ** attempt
            print(f"  attempt {attempt+1} failed ({e}); retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


def val(b, k):
    v = b.get(k)
    return v["value"] if v else ""


def test():
    try:
        js = run("SELECT ?x WHERE { BIND(1 AS ?x) }", Path("/dev/null"), False, tries=1)
    except Exception as e:
        js = None
    print("Wikidata query service reachable" if js else "Wikidata NOT reachable (check network allowlist)")
    return 0 if js else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", nargs="?", default="data/wikidata")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="ignore cached raw responses")
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--old", default="data/wikidata/wikidata_civil_war_events.json")
    a = ap.parse_args()
    if a.test:
        return test()
    global REFRESH
    REFRESH = a.refresh
    out = Path(a.out_dir); raw = out / "raw"; raw.mkdir(parents=True, exist_ok=True)

    found, report, subs = {}, [], []
    for name, q in DISCOVERY.items():
        if name == "subclasses":
            js = run(q, raw / "discover_subclasses.json", a.offline)
            subs = sorted({val(b, "sub").rsplit("/", 1)[1] for b in js["results"]["bindings"]}) if js else []
            report.append(f"subclasses of the event classes: {len(subs)}")
            continue
        if name == "typed":
            if not subs:
                continue
            q = (f"SELECT DISTINCT ?b WHERE {{ VALUES ?cls {{ {' '.join('wd:' + s for s in subs)} }} "
                 f"VALUES ?c {{ {COUNTRIES} }} ?b wdt:P31 ?cls ; wdt:P17 ?c . "
                 f"{{ ?b wdt:P585 ?t }} UNION {{ ?b wdt:P580 ?t }} {DATE_FILTER} }}")
        if name in ("typed_geo", "typed_desc"):
            if not subs:
                continue
            vals = " ".join("wd:" + s for s in subs)
            if name == "typed_geo":
                q = (f"SELECT DISTINCT ?b WHERE {{ VALUES ?cls {{ {vals} }} ?b wdt:P31 ?cls ; wdt:P625 ?co . "
                     f"{{ ?b wdt:P585 ?t }} UNION {{ ?b wdt:P580 ?t }} {DATE_FILTER} "
                     f"BIND(geof:longitude(?co) AS ?lon) BIND(geof:latitude(?co) AS ?lat) "
                     f"FILTER(?lon > -125 && ?lon < -66 && ?lat > 24 && ?lat < 50) }}")
            else:
                q = (f"SELECT DISTINCT ?b WHERE {{ VALUES ?cls {{ {vals} }} ?b wdt:P31 ?cls ; schema:description ?d . "
                     f"FILTER(LANG(?d) = 'en' && (CONTAINS(LCASE(?d), 'american civil war') || CONTAINS(LCASE(?d), 'u.s. civil war') "
                     f"|| CONTAINS(LCASE(?d), 'confedera'))) }}")
        print(f"discovery: {name}")
        js = run(q, raw / f"discover_{name}.json", a.offline)
        if js is None:
            report.append(f"discovery {name}: FAILED (timeout or network)"); continue
        qids = {val(b, "b").rsplit("/", 1)[1] for b in js["results"]["bindings"]}
        for q_ in qids:
            found.setdefault(q_, set()).add(name)
        report.append(f"discovery {name}: {len(qids)} items")
    qids = sorted(found, key=lambda q: int(q[1:]))
    report.append(f"distinct candidate items: {len(qids)}")

    rows = []
    for i in range(0, len(qids), a.batch):
        chunk = qids[i:i + a.batch]
        print(f"details {i}-{i+len(chunk)} of {len(qids)}")
        import hashlib
        h = hashlib.md5(" ".join(chunk).encode()).hexdigest()[:10]       # cache key = batch content
        js = run(DETAILS % " ".join("wd:" + q for q in chunk), raw / f"details_{h}.json", a.offline)
        if js is None:
            report.append(f"details batch {i}: FAILED"); continue
        for b in js["results"]["bindings"]:
            r = {k: val(b, k) for k in ("b", "label", "aliases", "coord", "pit", "pit_prec", "start",
                                         "start_prec", "end", "end_prec", "parts", "classes", "locs",
                                         "loc_labels", "places", "place_labels",
                                         "official_names", "short_names")}
            for k in ("pit_prec", "start_prec", "end_prec"):
                r[k] = int(r[k]) if r[k] else None
            extra = [n for n in (r["official_names"] + "|" + r["short_names"]).split("|") if n]
            names = [x for x in r["aliases"].split("|") if x]
            r["aliases"] = "|".join(dict.fromkeys(names + [n for n in extra if n != r["label"]]))
            r["found_by"] = "|".join(sorted(found[r["b"].rsplit("/", 1)[1]]))
            rows.append({k: v for k, v in r.items() if v not in ("", None)} | {"b": r["b"]})
        if not a.offline:
            time.sleep(1)                             # be polite to the public endpoint

    # items found only via 'conflict' are units, ships, weapons, people, fiction: keep them apart
    def off_period(r):   # not linked by part-of, and dated outside 1860-66 (Swiss, Polish 'confederations' etc.)
        y = (r.get("start") or r.get("pit") or "")[:4]
        return "partof" not in r["found_by"] and y.isdigit() and not 1860 <= int(y) <= 1866
    other = [r for r in rows if r["found_by"] == "conflict" or off_period(r)]
    rows = [r for r in rows if not (r["found_by"] == "conflict" or off_period(r))]
    (out / "wikidata_civil_war_other_v2.json").write_text(json.dumps(other, ensure_ascii=False, indent=0), encoding="utf-8")
    report.append(f"items set apart (conflict-only units/ships/weapons, or dated outside 1860-66): {len(other)}")
    path = out / "wikidata_civil_war_events_v2.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    new = {r["b"].rsplit("/", 1)[1] for r in rows}
    try:
        old = {r["b"].rsplit("/", 1)[1] for r in json.load(open(a.old, encoding="utf-8"))}
        report.append(f"previous file: {len(old)} items; new: {len(new)}; added {len(new-old)}; "
                      f"no longer found {len(old-new)}")
    except FileNotFoundError:
        pass
    report += [f"with coordinates: {sum(1 for r in rows if r.get('coord'))}",
               f"with a day-precision date: {sum(1 for r in rows if (r.get('pit_prec') or 0) >= 11 or (r.get('start_prec') or 0) >= 11)}",
               f"with P131 admin area: {sum(1 for r in rows if r.get('locs'))}",
               f"with official/short names: {sum(1 for r in rows if r.get('official_names') or r.get('short_names'))}",
               f"wrote {path}"]
    (out / "pull_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    sys.exit(main())
