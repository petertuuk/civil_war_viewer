"""Fetch Wikipedia articles on Confederate units (wikitext), for infobox battle lists.

1. Walk Category:Units and formations of the Confederate States Army by state or territory (depth 3).
2. Fetch the wikitext of every article in batches of 50 titles (one API call each), pausing between calls.
Writes data/wikipedia/regiments/titles.json and pages.jsonl ({title, revid, text}). Resumable: skips titles done.
Usage: python pipeline/fetch_wp_regiments.py data/wikipedia/regiments [max_batches]
Wikipedia text is CC BY-SA 4.0: only facts (the battles a unit is listed at) go into the database, with the
article and revision cited.
"""
import json, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

UA = {"User-Agent": "civil-war-viewer/0.1 (personal research project)"}
ROOT = "Category:Units and formations of the Confederate States Army by state or territory"


def api(**kw):
    kw.update(format="json", formatversion="2")
    req = urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(kw), headers=UA)
    for i in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(15 * (i + 1))
    raise SystemExit("rate limited")


def main(out, max_batches="999"):
    out = Path(out)
    tp = out / "titles.json"
    if tp.exists():
        titles = json.load(open(tp))
    else:
        titles, seen, todo = set(), set(), [(ROOT, 0)]
        while todo:
            cat, depth = todo.pop()
            if cat in seen:
                continue
            seen.add(cat)
            cont = {}
            while True:
                r = api(action="query", list="categorymembers", cmtitle=cat, cmlimit="500", cmtype="page|subcat", **cont)
                for m in r["query"]["categorymembers"]:
                    if m["ns"] == 14 and depth < 3 and "Union" not in m["title"]:
                        todo.append((m["title"], depth + 1))
                    elif m["ns"] == 0:
                        titles.add(m["title"])
                if "continue" in r:
                    cont = {"cmcontinue": r["continue"]["cmcontinue"]}
                else:
                    break
                time.sleep(1)
            time.sleep(1)
        titles = sorted(titles)
        json.dump(titles, open(tp, "w"))
        print("categories", len(seen), "articles", len(titles))
    pp = out / "pages.jsonl"
    done = set()
    if pp.exists():
        done = {json.loads(l)["title"] for l in open(pp, encoding="utf-8")}
    todo = [t for t in titles if t not in done]
    nb = 0
    with open(pp, "a", encoding="utf-8") as f:
        for i in range(0, len(todo), 50):
            if nb >= int(max_batches):
                break
            batch = todo[i:i + 50]
            r = api(action="query", prop="revisions", rvprop="content|ids", rvslots="main", titles="|".join(batch), redirects="1")
            got = set()
            for p in r["query"]["pages"]:
                rv = (p.get("revisions") or [{}])[0]
                txt = (rv.get("slots") or {}).get("main", {}).get("content")
                if txt:
                    f.write(json.dumps({"title": p["title"], "revid": rv.get("revid"), "text": txt}, ensure_ascii=False) + "\n")
                    got.add(p["title"])
            for t in batch:                         # redirected or missing: record so the run can resume past them
                if t not in got:
                    f.write(json.dumps({"title": t, "revid": None, "text": ""}) + "\n")
            nb += 1
            time.sleep(3)
    print("fetched batches", nb, "remaining", max(0, len(todo) - nb * 50))


if __name__ == "__main__":
    main(*sys.argv[1:])
