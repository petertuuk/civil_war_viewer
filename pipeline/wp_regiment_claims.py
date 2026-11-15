"""Participation claims from the battle lists in Wikipedia infoboxes of Confederate unit articles.

Article -> unit: the title parsed for number, state and arm ("33rd Alabama Infantry Regiment") against the NPS unit
list (consolidated, local-defense, short-term and militia namesakes set aside, as nps_links.resolve_ambiguous does),
or a named unit through data/manual/unit_aliases.psv. Infobox "battles" links -> events: each link target is resolved
through Wikipedia redirects to its Wikidata item, then to the event anchored to that item (events.jsonl "wikidata").
Wikipedia text is CC BY-SA: only the fact "unit listed at battle", with article and revision, is stored.

Usage: python pipeline/wp_regiment_claims.py data/wikipedia/regiments data/events data/external/acw_battle_data/nps_units.csv \
          data/scores/dyer_to_nps.csv data/wikipedia/claims_wp_regiments.jsonl
"""
import csv, json, re, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
import nps_links  # noqa: E402

UA = {"User-Agent": "civil-war-viewer/0.1 (personal research project)"}
STATES = cwv_states.table("Name", "CODE", "AL", "AR", "FL", "GA", "KY", "LA", "MD", "MS", "MO", "NC", "SC", "TN",
                                          "TX", "VA", "AZ", ("Confederate", "CS"), ("Cherokee", "OK"),
                                          ("Choctaw", "OK"), ("Creek", "OK"), ("Chickasaw", "OK"), ("Seminole", "OK"))
ARM = {"Infantry": ("R", "I"), "Cavalry": ("R", "C"), "Mounted Infantry": ("R", "I"), "Mounted Rifles": ("R", "C"),
       "Artillery": ("R", "A"), "Heavy Artillery": ("R", "A"), "Partisan Rangers": ("R", "C"), "Sharpshooters": ("B", "I")}


def api(**kw):
    kw.update(format="json", formatversion="2")
    req = urllib.request.Request("https://en.wikipedia.org/w/api.php", data=urllib.parse.urlencode(kw).encode(), headers=UA)
    for i in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(15 * (i + 1))
    raise SystemExit("rate limited")


def main(regdir, events_dir, units_csv, d2n, out):
    regdir = Path(regdir)
    pages = [json.loads(l) for l in open(regdir / "pages.jsonl", encoding="utf-8")]
    pages = [p for p in pages if p["text"]]
    units = list(csv.DictReader(open(units_csv, encoding="utf-8")))
    by = defaultdict(list)
    for u in units:
        if u["belligerent"] == "Confederate":
            try:
                by[(u["state"], int(u["ordinal"] or 0), u["type"], u["func"])].append(u)
            except ValueError:
                pass
    _, code2dyer, _ = nps_links.load(d2n)

    def unit_for(title):
        t = re.sub(r"\s*\((?:Confederate|CSA|C\.S\.A\.)\)", "", title)
        m = re.match(r"^(\d+)(?:st|nd|rd|th|d)\s+(?:\(\w[^)]*\)\s+)?(.+?)\s+(Mounted Infantry|Mounted Rifles|Heavy Artillery|Partisan Rangers|Infantry|Cavalry|Artillery|Sharpshooters)(?:\s+(Regiment|Battalion))?", t)
        if m:
            num, st, arm, kind = int(m.group(1)), m.group(2).strip(), m.group(3), m.group(4) or "Regiment"
            if st not in STATES:
                return None, "state"
            typ, func = ARM[arm]
            typ = "B" if kind == "Battalion" else typ
            cands = by.get((STATES[st], num, typ, func), [])
            if len(cands) > 1:
                code = nps_links.resolve_ambiguous("AMBIGUOUS:" + "|".join(c["unit_code"] for c in cands), units_csv)
                cands = [c for c in cands if c["unit_code"] == code]
            return (cands[0]["unit_code"], "number") if len(cands) == 1 else (None, f"{len(cands)} candidates")
        code = nps_links.alias_code(t, "Confederate")
        return (code, "alias") if code else (None, "named")

    # links in infobox battles
    links_of, stats = {}, Counter()
    for p in pages:
        m = re.search(r"\|\s*battles\s*=(.*?)(?:\n\s*\|\s*[a-z_]+\s*=|\n\}\})", p["text"], re.S)
        if not m:
            stats["no battles field"] += 1; continue
        links = [l.split("|")[0].strip() for l in re.findall(r"\[\[([^\]]+)\]\]", m.group(1))]
        links = [l for l in links if l and not l.startswith(("File:", "Image:")) and l != "American Civil War"]
        if links:
            links_of[p["title"]] = (p["revid"], links)
    targets = sorted({l for _, ls in links_of.values() for l in ls})
    cache_p = regdir / "link_qids.json"                   # link target -> Wikidata item; only new targets go to the API
    qid = json.load(open(cache_p, encoding="utf-8")) if cache_p.exists() else {}
    new = [t for t in targets if t not in qid]
    for i in range(0, len(new), 50):
        r = api(action="query", prop="pageprops", ppprop="wikibase_item", redirects="1", titles="|".join(new[i:i + 50]))
        canon = {x["from"]: x["to"] for x in r["query"].get("redirects", [])}
        canon.update({x["from"]: x["to"] for x in r["query"].get("normalized", [])})
        items = {p["title"]: (p.get("pageprops") or {}).get("wikibase_item") for p in r["query"]["pages"]}
        for t in new[i:i + 50]:
            c = canon.get(t, t); c = canon.get(c, c)
            qid[t] = items.get(c)
        time.sleep(2)
    json.dump(qid, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False)
    events = [json.loads(l) for l in open(Path(events_dir) / "events.jsonl", encoding="utf-8")]
    ev_of_q = {}
    for e in events:
        if e.get("wikidata"):
            if e["wikidata"] not in ev_of_q or e["regiments"] > ev_of_q[e["wikidata"]]["regiments"]:
                ev_of_q[e["wikidata"]] = e
    n = 0
    with open(out, "w", encoding="utf-8") as f:
        for title, (revid, links) in links_of.items():
            code, how = unit_for(title)
            stats[f"unit by {how}" if code else f"unit not found: {how}"] += 1
            if not code:
                continue
            uid = code2dyer.get(code) or f"nps:{code}"
            for l in links:
                e = ev_of_q.get(qid.get(l))
                if not e:
                    stats["link: no event"] += 1; continue
                stats["link: event"] += 1
                f.write(json.dumps({"claim_type": "participated", "unit_id": uid, "unit_mention": title, "side": "Confederate",
                                    "event_mention": l, "event_id": e["event_id"], "date_start": e["date_start"],
                                    "date_end": e["date_end"], "date_precision": "day" if len(e["date_start"] or "") == 10 else "month",
                                    "confidence": 0.7, "source_span": title, "source_ref": f"{title} (rev {revid})",
                                    "extracted_by": "wikitext:infobox_battles_v1"}, ensure_ascii=False) + "\n")
                n += 1
    print(dict(stats)); print("claims", n, "link targets", len(targets), "with Wikidata item", sum(1 for v in qid.values() if v))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("wp_regiment_claims")))
