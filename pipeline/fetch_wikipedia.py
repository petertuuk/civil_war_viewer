"""Fetch English Wikipedia wikitext for a category's articles, or for given titles.

Usage:
  python3 pipeline/fetch_wikipedia.py --category "American Civil War orders of battle" data/wikipedia/oob.jsonl
  python3 pipeline/fetch_wikipedia.py --titles-file titles.txt data/wikipedia/battles.jsonl
Output: one JSON row per page: title, pageid, revid, timestamp, wikitext (CC BY-SA 4.0; keep attribution).
Resumable: titles already in the output are skipped.
"""
import argparse, json, time, urllib.parse, urllib.request
from pathlib import Path

API = "https://en.wikipedia.org/w/api.php"
UA = "CivilWarViewer/0.2 (personal history research; python urllib)"


def api(**p):
    p.update(format="json", formatversion=2)
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(p), headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Wikipedia API failed")


def category_titles(cat):
    out, cont = [], {}
    while True:
        r = api(action="query", list="categorymembers", cmtitle="Category:" + cat, cmlimit=500, cmtype="page", **cont)
        out += [m["title"] for m in r["query"]["categorymembers"]]
        if "continue" not in r:
            return out
        cont = {"cmcontinue": r["continue"]["cmcontinue"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("--category"); ap.add_argument("--titles-file")
    a = ap.parse_args()
    titles = category_titles(a.category) if a.category else [t.strip() for t in open(a.titles_file, encoding="utf-8") if t.strip()]
    out = Path(a.out)
    have = {json.loads(l)["title"] for l in open(out, encoding="utf-8")} if out.exists() else set()
    todo = [t for t in titles if t not in have]
    with open(out, "a", encoding="utf-8") as f:
        for i in range(0, len(todo), 20):
            batch = todo[i:i + 20]
            try:
                pages = api(action="query", prop="revisions", rvprop="ids|timestamp|content", rvslots="main",
                            titles="|".join(batch), redirects=1)["query"]["pages"]
            except RuntimeError:
                pages = []
                for one in batch:                              # fall back to one title at a time
                    try:
                        pages += api(action="query", prop="revisions", rvprop="ids|timestamp|content", rvslots="main",
                                     titles=one, redirects=1)["query"]["pages"]
                    except RuntimeError:
                        print("failed:", one)
            for p in pages:
                if "revisions" not in p:
                    continue
                rv = p["revisions"][0]
                f.write(json.dumps({"title": p["title"], "pageid": p["pageid"], "revid": rv["revid"],
                                    "timestamp": rv["timestamp"], "wikitext": rv["slots"]["main"]["content"],
                                    "license": "CC BY-SA 4.0", "url": "https://en.wikipedia.org/wiki/" + p["title"].replace(" ", "_")},
                                   ensure_ascii=False) + "\n")
            time.sleep(1)
    print(f"titles {len(titles)}; already had {len(have)}; fetched now {len(todo)}")


if __name__ == "__main__":
    main()
