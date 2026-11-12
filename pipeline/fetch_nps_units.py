"""Fetch NPS Soldiers and Sailors unit histories (resumable, cached).

Usage:
  python3 pipeline/fetch_nps_units.py data/external/acw_battle_data/nps_units.csv data/nps \
      [--side Confederate] [--limit 0] [--seconds 160] [--workers 3]

Each page is cached as data/nps/html/<unit_code>.html, so reruns resume.
Then every cached page is parsed into data/nps/units.jsonl:
  unit_code, side, state, name, header, overview (plain text),
  battle_links (CWSAC codes linked in the text, e.g. PA002 = Gettysburg), empty (no overview).
"""
import argparse, csv, html, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://www.nps.gov/civilwar/search-battle-units-detail.htm?battleUnitCode={}"
UA = "CivilWarViewer/0.2 (personal history research; python urllib)"


def fetch(code, cache):
    p = cache / f"{code}.html"
    if p.exists() and p.stat().st_size > 1000:
        return "cached"
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL.format(code), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                p.write_bytes(r.read())
            return "fetched"
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    return "failed"


def parse(code, text):
    # Overview runs up to Soldiers:; Union pages split it into Overview: and Service: <dd>s
    # (the Service part holds most battle links), so take everything and keep the labels.
    m = re.search(r"Overview:\s*</dt>\s*<dd>(.*?)<dt>\s*Soldiers", text, re.S | re.I) or \
        re.search(r"Overview:\s*</dt>\s*<dd>(.*?)</dl>", text, re.S | re.I) or \
        re.search(r"Overview:(.*?)<dt>Soldiers", text, re.S | re.I)
    body = m.group(1) if m else ""
    body = re.sub(r"<dt>\s*([A-Za-z ]+:)\s*</dt>", r" \1 ", body, flags=re.I)
    links = sorted({x.upper() for x in re.findall(r"battleCode=([a-z]{2}\d{3}[a-z]?)", body, re.I)})
    plain = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    head = None   # unit name and side come from nps_units.csv
    return {"overview": plain, "battle_links": links,
            "header": html.unescape(re.sub(r"<[^>]+>", "", head.group(1))).strip() if head else "",
            "page_name": html.unescape(re.sub(r"<[^>]+>", "", head.group(2))).strip() if head else ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("units_csv"); ap.add_argument("out_dir")
    ap.add_argument("--side", default="Confederate", help="Confederate, US, or all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=160, help="stop fetching after this long (resume later)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-parse", action="store_true", help="fetch only")
    a = ap.parse_args()
    out = Path(a.out_dir); cache = out / "html"; cache.mkdir(parents=True, exist_ok=True)
    units = [u for u in csv.DictReader(open(a.units_csv, encoding="utf-8"))
             if (a.side == "all" or u["belligerent"] == a.side) and u["duplicate"] != "1"]
    if a.limit:
        units = units[:a.limit]
    have = set(p[:-5] for p in __import__("os").listdir(cache))          # one listing, not thousands of stats
    todo = [u["unit_code"] for u in units if u["unit_code"] not in have]
    t0, stats = time.time(), {"fetched": 0, "failed": 0}
    with ThreadPoolExecutor(a.workers) as ex:
        futs = []
        for code in todo:
            if time.time() - t0 > a.seconds:
                break
            futs.append(ex.submit(fetch, code, cache))
            time.sleep(1.0 / a.workers)          # about one request per second per worker
        for f in futs:
            stats[f.result()] = stats.get(f.result(), 0) + 1
    have = set(p[:-5] for p in __import__("os").listdir(cache))
    left = sum(1 for u in units if u["unit_code"] not in have)
    if a.no_parse:
        print(f"this run: {stats}; selected units {len(units)}; cached {len(have)}; left {left}")
        return
    rows = []
    for u in units:
        p = cache / f"{u['unit_code']}.html"
        if u["unit_code"] in have:
            r = parse(u["unit_code"], p.read_text(encoding="utf-8", errors="replace"))
            rows.append({"unit_code": u["unit_code"], "side": u["belligerent"], "state": u["state"],
                         "name": u["unit_name"], "type": u["type"], **r,
                         "empty": not r["overview"] or "contains no history" in r["overview"]})
    with open(out / "units.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    words = [len(r["overview"].split()) for r in rows if r["overview"] and not r["empty"]]
    print(f"this run: {stats}; selected units {len(units)}; cached {len(rows)}; left {left}")
    print(f"with overview text: {len(words)}; empty: {sum(1 for r in rows if r['empty'])}; "
          f"median words {sorted(words)[len(words)//2] if words else 0}; "
          f"with battle links: {sum(1 for r in rows if r['battle_links'])}")


if __name__ == "__main__":
    main()
