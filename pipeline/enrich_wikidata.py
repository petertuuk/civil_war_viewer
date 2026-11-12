"""Fill gaps in the Wikidata event file from Wikipedia infoboxes.

Usage: python3 pipeline/enrich_wikidata.py data/wikidata/wikidata_civil_war_events_v2.json data/wikipedia/infobox_by_qid.json \
           data/wikidata/wikidata_civil_war_events_v2_enriched.json
Coordinates: filled when Wikidata has none. Dates: filled only when Wikidata has no day-precision date and the
infobox gives a range of 14 days or less (campaign ranges like "March-July 1862" parse badly).
Filled fields are marked coord_source / date_source = "wikipedia".
"""
import json, sys
from datetime import date


def main(wd_path, ib_path, out):
    wd = json.load(open(wd_path, encoding="utf-8")); ib = json.load(open(ib_path, encoding="utf-8"))
    n = {"coords": 0, "dates": 0}
    for r in wd:
        i = ib.get(r["b"].rsplit("/", 1)[1], {})
        if not r.get("coord") and i.get("lat") is not None:
            r["coord"] = f"Point({i['lon']} {i['lat']})"; r["coord_source"] = "wikipedia"; n["coords"] += 1
        has_day = (r.get("pit_prec") or 0) >= 11 or (r.get("start_prec") or 0) >= 11
        if not has_day and i.get("date_start"):
            s, e = date.fromisoformat(i["date_start"]), date.fromisoformat(i["date_end"])
            if 0 <= (e - s).days <= 14:
                r["start"], r["start_prec"] = i["date_start"] + "T00:00:00Z", 11
                r["end"], r["end_prec"] = i["date_end"] + "T00:00:00Z", 11
                r["date_source"] = "wikipedia"; n["dates"] += 1
    json.dump(wd, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(n)


if __name__ == "__main__":
    main(*sys.argv[1:4])
