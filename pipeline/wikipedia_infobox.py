"""Read battle infoboxes from English Wikipedia for our Wikidata events.

Usage: python3 pipeline/wikipedia_infobox.py data/wikidata/wikidata_civil_war_events_v2.json data/wikipedia
1. Wikidata QID -> enwiki title (wbgetentities sitelinks), cached in data/wikipedia/qid_enwiki.json
2. Fetch wikitext (fetch_wikipedia.py style, cached in data/wikipedia/battles.jsonl)
3. Parse infobox: coordinates ({{coord|...}} DMS or decimal), date range, place, strength/casualty text
Writes data/wikipedia/infobox_by_qid.json: qid -> {title, lat, lon, date_start, date_end, place, ...}
"""
import json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parse_or_all import parse_date

UA = "CivilWarViewer/0.2 (personal history research; python urllib)"


def get(url):
    for a in range(4):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60))
        except Exception:
            time.sleep(3 * (a + 1))
    raise RuntimeError(url)


def coord(t):
    m = re.search(r"\{\{\s*[Cc]oord\s*\|([^}]*)\}\}", t)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split("|") if p.strip() and "=" not in p]
    try:
        if "N" in parts or "S" in parts:
            i = parts.index("N") if "N" in parts else parts.index("S")
            lat = sum(float(x) / 60 ** k for k, x in enumerate(parts[:i])) * (1 if parts[i] == "N" else -1)
            j = parts.index("W") if "W" in parts else parts.index("E")
            lon = sum(float(x) / 60 ** k for k, x in enumerate(parts[i + 1:j])) * (-1 if parts[j] == "W" else 1)
        else:
            lat, lon = float(parts[0]), float(parts[1])
        return round(lat, 5), round(lon, 5)
    except (ValueError, IndexError):
        return None


def field(box, name):
    m = re.search(r"\|\s*" + name + r"\s*=\s*(.*?)(?=\n\s*\|\s*[a-z_0-9]+\s*=|\n\}\})", box, re.S | re.I)
    if not m:
        return ""
    v = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", m.group(1), flags=re.S)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{(?:start date|end date|start and end dates)\|([^}]*)\}\}", lambda x: " ".join(x.group(1).split("|")), v, flags=re.I)
    return re.sub(r"<[^>]+>|''+|\{\{[^{}]*\}\}", " ", v).replace("&ndash;", "-").replace("–", "-").strip()


def main(wd_path, wdir):
    wdir = Path(wdir)
    qids = sorted({r["b"].rsplit("/", 1)[1] for r in json.load(open(wd_path, encoding="utf-8"))})
    cache = wdir / "qid_enwiki.json"
    titles = json.load(open(cache)) if cache.exists() else {}
    need = [q for q in qids if q not in titles]
    for i in range(0, len(need), 50):
        r = get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(need[i:i + 50]),
                "props": "sitelinks", "sitefilter": "enwiki", "format": "json"}))
        for q, ent in r.get("entities", {}).items():
            titles[q] = ent.get("sitelinks", {}).get("enwiki", {}).get("title")
        time.sleep(0.5)
    json.dump(titles, open(cache, "w"), indent=0)
    tl = [t for t in titles.values() if t]
    (wdir / "battle_titles.txt").write_text("\n".join(tl), encoding="utf-8")
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).parent / "fetch_wikipedia.py"), "--titles-file", str(wdir / "battle_titles.txt"),
                    str(wdir / "battles.jsonl")], check=True)
    pages = {json.loads(l)["title"]: json.loads(l) for l in open(wdir / "battles.jsonl", encoding="utf-8")}
    out, n = {}, {"titles": len(tl), "pages": 0, "infobox": 0, "coord": 0, "date": 0}
    for q, t in titles.items():
        p = pages.get(t)
        if not p:
            continue
        n["pages"] += 1
        w = p["wikitext"]
        bm = re.search(r"\{\{\s*Infobox (?:military conflict|military operation|battle)(.*?)\n\}\}", w, re.S | re.I)
        box = bm.group(1) if bm else ""
        c = coord(box) or coord(w[:6000])
        ds, de = parse_date(field(box, "date")) if box else (None, None)
        rec = {"title": t, "revid": p["revid"]}
        if box: n["infobox"] += 1
        if c: rec.update(lat=c[0], lon=c[1]); n["coord"] += 1
        if ds: rec.update(date_start=ds, date_end=de); n["date"] += 1
        if box:
            rec.update(place=field(box, "place")[:200], strength=field(box, "strength1")[:120] + " | " + field(box, "strength2")[:120],
                       casualties=field(box, "casualties1")[:160] + " | " + field(box, "casualties2")[:160])
        out[q] = rec
    json.dump(out, open(wdir / "infobox_by_qid.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(n)


if __name__ == "__main__":
    main(*sys.argv[1:3])
