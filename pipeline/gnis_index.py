"""Compact GNIS gazetteer for geocoding: official and variant names of the feature types a Civil War place
name can be (towns, forts, crossings, gaps, summits, streams, ...), in the states and territories of the war.

Inputs (USGS GNIS, public domain), unzipped from https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/:
  DomesticNames/DomesticNames_National_Text.zip, Topical/HistoricalFeatures_National_Text.zip,
  Topical/AllNames_National_Text.zip (variant names: former names like "Pigeon's Ranch")
Usage: python pipeline/gnis_index.py <gnis_dir> data/external/gnis/gnis_index.tsv
Columns: norm name, state, lat, lon, class, county, feature id, name as printed, official|variant|historical
"""
import csv, glob, re, sys
from pathlib import Path

STATES = {"Alabama": "AL", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
          "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Idaho": "ID", "Illinois": "IL",
          "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
          "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
          "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
          "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
          "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
          "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
KEEP = {"Populated Place", "Civil", "Military", "Crossing", "Gap", "Summit", "Ridge", "Stream", "Spring", "Island", "Swamp",
        "Valley", "Bend", "Bar", "Cape", "Bay", "Channel", "Falls", "Rapids", "Flat", "Woods", "Plain", "Gut", "Basin",
        "Range", "Slope", "Area", "Levee", "Canal", "Cliff", "Lake", "Beach"}


def norm(s):
    s = (s or "").lower().replace("(historical)", " ")
    s = s.replace("’", "'").replace("'s ", "s ").replace("'", "")
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bmount\b", "mt", s)
    s = re.sub(r"\bcourthouse\b|\bc\.?\s*h\b\.?", "court house", s)
    s = re.sub(r"\bcrossroads?\b", "cross roads", s)
    s = re.sub(r"\bstation\b", "station", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main(gdir, out):
    gdir = Path(gdir)
    feats = {}
    files = [(p, "official") for p in glob.glob(str(gdir / "**/DomesticNames_National.txt"), recursive=True)] + \
            [(p, "historical") for p in glob.glob(str(gdir / "**/HistoricalFeatures_National.txt"), recursive=True)]
    for p, kind in files:
        for r in csv.DictReader(open(p, encoding="utf-8-sig"), delimiter="|"):
            st = STATES.get(r["state_name"])
            if not st or r["feature_class"] not in KEEP:
                continue
            try:
                lat, lon = float(r["prim_lat_dec"]), float(r["prim_long_dec"])
            except ValueError:
                continue
            if not lat:
                continue
            feats[r["feature_id"]] = (st, lat, lon, r["feature_class"], r["county_name"], r["feature_name"], kind)
    rows = 0
    with open(out, "w", encoding="utf-8") as f:
        for fid, (st, lat, lon, cl, co, nm, kind) in feats.items():
            f.write("\t".join([norm(nm), st, f"{lat:.5f}", f"{lon:.5f}", cl, co, fid, nm, kind]) + "\n"); rows += 1
        for p in glob.glob(str(gdir / "**/AllNames_National.txt"), recursive=True):
            for r in csv.DictReader(open(p, encoding="utf-8-sig"), delimiter="|"):
                if r["feature_name_official"] == "Official" or r["feature_id"] not in feats:
                    continue
                st, lat, lon, cl, co, nm, _ = feats[r["feature_id"]]
                if norm(r["feature_name"]) == norm(nm):
                    continue
                f.write("\t".join([norm(r["feature_name"]), st, f"{lat:.5f}", f"{lon:.5f}", cl, co, r["feature_id"],
                                   r["feature_name"], "variant"]) + "\n"); rows += 1
    print("features kept:", len(feats), "index rows:", rows)


if __name__ == "__main__":
    main(*sys.argv[1:])
