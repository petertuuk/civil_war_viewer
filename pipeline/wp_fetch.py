"""Fetch Wikipedia search hits or plain-text extracts (with revision ids) for reading articles during review.
Usage: python pipeline/wp_fetch.py search "query" ... | python pipeline/wp_fetch.py text3000 "Title" ...
The API rate-limits quickly (HTTP 429): it backs off, and callers should pause ~8 s between articles."""
import urllib.request, urllib.error, urllib.parse, json, sys
UA={"User-Agent":"civil-war-viewer/0.1 (personal research project)"}
import time
def api(**kw):
    kw.update(format="json")
    r=urllib.request.Request("https://en.wikipedia.org/w/api.php?"+urllib.parse.urlencode(kw),headers=UA)
    for i in range(6):
        try:
            return json.load(urllib.request.urlopen(r,timeout=30))
        except urllib.error.HTTPError as e:
            if e.code!=429: raise
            time.sleep(10*(i+1))
    raise SystemExit("rate limited")
mode=sys.argv[1]
if mode=="search":
    for q in sys.argv[2:]:
        res=api(action="query",list="search",srsearch=q,srlimit=6)
        print(q,"=>",[h["title"] for h in res["query"]["search"]])
else:
    for t in sys.argv[2:]:
        res=api(action="query",prop="extracts|revisions",rvprop="ids",explaintext=1,titles=t,redirects=1)
        for p in res["query"]["pages"].values():
            ex=p.get("extract","")
            print("=====",p.get("title"),"rev",(p.get("revisions") or [{}])[0].get("revid"),len(ex))
            print(ex[:int(sys.argv[1][4:] or 3000)] if mode.startswith("text") else "")
