"""Where things live (roadmap T3.6): one place for the folder, the database, the OR texts and the files passed around most.

    ROOT        the project (or work-copy) folder: two levels above this file
    DB          environment DB, else ~/db/civil_war.db (what rebuild.sh and stamps.py use)
    OR_TXT      environment OR_TXT, else ~/or/txt (the Official Records texts)
    SOURCES     environment SOURCES, else ~/mnt/civil_war_viewer/sources (the Dyer's scan; review_cases.py)
    GNIS_INDEX, NPS_UNITS, GEOCODED, EVENTS, WIKIDATA, ...   the files most scripts take as arguments

A script keeps taking its paths as command-line arguments, exactly as rebuild.sh passes them. Called with no arguments it uses
DEFAULT_ARGS[<script name>], which lists what rebuild.sh passes (tests/test_paths.py compares the two, so they cannot drift):

    main(*(sys.argv[1:] or paths.defaults("export_war")))

Left out on purpose: build_db.py (run from pipeline/ with ".."), resolve_namesakes.py (two different calls) and stamps.py.
Paths are absolute, so a script can be started from any folder. rebuild.sh's battle_monuments, validate_datelines and or_datelines
lines write ~/db/civil_war.db and ~/or/txt instead of $DB; with DB and OR_TXT unset the two are the same.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
DB = Path(os.environ.get("DB") or HOME / "db" / "civil_war.db")
OR_TXT = Path(os.environ.get("OR_TXT") or HOME / "or" / "txt")
SOURCES = Path(os.environ.get("SOURCES") or HOME / "mnt" / "civil_war_viewer" / "sources")


def R(rel):
    """A path inside the project folder."""
    return ROOT / rel


WIKIDATA = R("data/wikidata/wikidata_civil_war_events_v2_enriched.json")
GNIS_INDEX = R("data/external/gnis/gnis_index.tsv")
NPS_UNITS = R("data/external/acw_battle_data/nps_units.csv")
ACW_DATA = R("data/external/acw_battle_data")
GEOCODED = R("data/places/geocoded.csv")
EVENTS = R("data/events/events.jsonl")
EVENTS_DIR = R("data/events")
PLACES_DIR = R("data/places")
DYERS_DIR = R("data/dyers")
SCORES_DIR = R("data/scores")
DYER_TO_NPS = R("data/scores/dyer_to_nps.csv")
OR_PLACEMENTS = R("data/or/placements.jsonl")
OR_TABLES = R("data/or/tables.jsonl")
AI_DIR = R("data/ai")
WAR_DATA = R("viewer/war/data")

# What rebuild.sh passes to each script (generated from it once; tests/test_paths.py keeps the two equal).
DEFAULT_ARGS = {
    "anchor_events": (R("data/dyers/claims_rules.jsonl"), WIKIDATA, R("data/dyers/events.jsonl"), DYERS_DIR),
    "apply_ai_resolutions": (R("data/dyers/canonical_events.jsonl"), WIKIDATA, AI_DIR, AI_DIR),
    "battle_monuments": (DB, R("data/external/battles"), R("data/battles"), R("data/scores/battle_monuments.txt")),
    "brigade_inference": (DB, R("data/scores/brigade_inference.txt")),
    "check_confederate": (R("data/or/claims_or.jsonl"), EVENTS_DIR, ACW_DATA, R("data/nps/units.jsonl"), R("data/scores/confederate_check.txt")),
    "compare_oob": (R("data/wikipedia/oob_placements.jsonl"), R("data/or/claims_or.jsonl"), EVENTS_DIR, R("data/wikipedia"), R("data/scores/oob_vs_or.txt")),
    "consistency_checks": (DB, ROOT, R("data/scores/consistency.txt"), R("data/scores/review_queue.csv")),
    "db_checks": (DB,),
    "db_metrics": (DB,),
    "event_context_check": (DB, GNIS_INDEX, R("data/scores/event_relocations.csv")),
    "export_war": (DB, WAR_DATA),
    "extract_dyers": (R("data/dyers/units_clean.jsonl"), R("data/dyers/claims_rules_raw.jsonl")),
    "extract_nps_histories": (R("data/nps/units.jsonl"), GEOCODED, GNIS_INDEX, R("data/derived/nps_confederate_histories.json")),
    "extract_state_histories": (R("data/external/state_histories"), EVENTS, NPS_UNITS, R("data/derived/state_histories.json"), R("data/scores/state_histories_report.txt")),
    "extract_state_stations": (R("data/external/state_histories"), NPS_UNITS, GEOCODED, GNIS_INDEX, R("data/derived/state_stations.json"), R("data/scores/state_stations_report.txt"), EVENTS),
    "fast_jumps": (DB, R("data/scores/fast_jumps.csv"), R("data/scores/fast_jumps.txt")),
    "fix_units": (R("data/dyers/units.jsonl"), R("data/dyers/unit_overrides.jsonl"), R("data/nps_us/units.jsonl"), R("data/dyers/units_fixed.jsonl")),
    "fix_years": (R("data/dyers/claims_rules_raw.jsonl"), WIKIDATA, R("data/dyers/claims_rules.jsonl"), R("data/dyers/fix_years_report.txt")),
    "geocode": (PLACES_DIR, GNIS_INDEX, EVENTS_DIR),
    "match_witnesses": (R("data/dyers/units_fixed.jsonl"), R("data/nps_us/units.jsonl"), DYER_TO_NPS, R("data/cwa/cwa_units.json"), R("data/witness/matches.json")),
    "merge_events": (DYERS_DIR, AI_DIR, EVENTS_DIR, WIKIDATA),
    "nps_battles_to_claims": (ACW_DATA, WIKIDATA, DYER_TO_NPS, EVENTS_DIR, R("data/nps/claims_nps_battles.jsonl")),
    "or_datelines": (OR_TXT, R("data/or/volumes.json"), OR_PLACEMENTS, OR_TABLES, GEOCODED, GNIS_INDEX, NPS_UNITS, R("data/or/datelines.jsonl"), R("data/derived/or_datelines.json")),
    "or_stations": (OR_PLACEMENTS, OR_TABLES, R("data/manual/or_regions.psv"), GEOCODED, GNIS_INDEX, NPS_UNITS, R("data/derived/or_stations.json")),
    "or_to_claims": (OR_PLACEMENTS, OR_TABLES, DYER_TO_NPS, EVENTS_DIR, R("data/or/claims_or.jsonl")),
    "places_inventory": (DYERS_DIR, EVENTS_DIR, PLACES_DIR),
    "resolve_mentions": (PLACES_DIR, GNIS_INDEX, DYERS_DIR, EVENTS_DIR, R("data/places/mention_resolution.jsonl"), R("data/scores/mention_resolution.txt")),
    "review_cases": (SOURCES / "08697590_3359_djvu.xml", SOURCES / "dyers_compendium.pdf", R("data/review")),
    "score_dyers_vs_cwss": (DYERS_DIR, ACW_DATA, SCORES_DIR),
    "score_gold": (DB, R("data/gold/units"), EVENTS, R("data/scores/gold_scores.txt"), R("data/scores/gold_detail.jsonl")),
    "validate_datelines": (DB, R("data/derived/or_datelines.json")),
    "vote_witnesses": (R("data/dyers/units_fixed.jsonl"), R("data/witness/matches.json"), R("data/nps_us/units.jsonl"), R("data/cwa/cwa_units.json"), R("data/dyers/units_clean.jsonl")),
    "wikipedia_to_claims": (R("data/wikipedia/oob_placements.jsonl"), R("data/wikipedia/oob_battles.json"), DYER_TO_NPS, EVENTS_DIR, R("data/wikipedia/claims_wikipedia.jsonl")),
    "wp_regiment_claims": (R("data/wikipedia/regiments"), EVENTS_DIR, NPS_UNITS, DYER_TO_NPS, R("data/wikipedia/claims_wp_regiments.jsonl")),
}


def defaults(script):
    """The command-line arguments rebuild.sh gives `script`, as strings."""
    return [str(a) for a in DEFAULT_ARGS[script]]
