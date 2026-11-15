#!/bin/bash
# Rebuild everything downstream of the cleaned Dyer's text. Run from the project folder:
#   bash pipeline/rebuild.sh [stage ...]     stages: units dyers events links or datelines db checks war review (default: dyers events links or datelines db checks)
# Human review: answers from the review page -> data/review/decisions.jsonl -> python3 pipeline/review_import.py data/review/decisions.jsonl,
#   then units (OCR readings) or dyers (years) and everything after; 'review' remakes the cards (data/review/cases.json, img/).
# GNIS index: python3 pipeline/gnis_index.py <unzipped GNIS dir> data/external/gnis/gnis_index.tsv (once; see that file)
# Forts GNIS lacks: python3 pipeline/forts_gazetteer.py data/external/forts data/external/gnis/gnis_index.tsv data/external/gnis/gnis_extra.tsv (read with the index by gnis_index.index_lines)
# build_db.py first runs refcheck.py and stops when a generated file points at event ids that no longer match events.jsonl (rerun the stage it names).
#   In the chain after a change at dyers/events, the FIRST db build is made from the old OR files on purpose: run it as  CWV_ALLOW_STALE=1 bash pipeline/rebuild.sh db
# The remote-device shell allows ~170 s per call: run one or two stages per call there. Stages whose inputs have not
# changed since their last good run are skipped (pipeline/stamps.py); FORCE=1 bash pipeline/rebuild.sh ... runs them anyway.
set -eo pipefail   # a failing step stops the rebuild even when piped into tail
export PYTHONHASHSEED=0   # same inputs, same outputs (set and dict-of-set order otherwise varies run to run: ties, examples)
W=data/wikidata/wikidata_civil_war_events_v2_enriched.json
DB=${DB:-$HOME/db/civil_war.db}
stages=${@:-dyers events links or datelines db checks}
stages=$(echo " $stages " | sed 's/ db / db_build db_finish /g')   # db = db_build + db_finish
# Every step's full output goes to data/scores/build.log; the screen shows its last N lines (step N cmd ...) or first N (stephead N cmd ...).
# Never pipe a step into grep or head here: with pipefail a grep that matches nothing stops the stage silently, and head can cut a step
# off with SIGPIPE. tail and awk read to the end. (Errors go to stderr, not into the log, as before.)
LOG="$PWD/data/scores/build.log"
mkdir -p data/scores
[ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5000000 ] && mv -f "$LOG" "$LOG.prev"
step()     { local n=$1; shift; echo "\$ $*" >> "$LOG"; "$@" | tee -a "$LOG" | tail -n "$n"; }
stephead() { local n=$1; shift; echo "\$ $*" >> "$LOG"; "$@" | tee -a "$LOG" | awk -v n="$n" 'NR<=n'; }
for s in $stages; do
  echo "== $s"
  # skip a stage whose inputs have not changed since its last good run (pipeline/stamps.py; FORCE=1 runs everything)
  if python3 pipeline/stamps.py check "$s"; then echo "   inputs unchanged since its last run: skipped"; continue; fi
  case $s in
    units)
      python3 pipeline/fix_units.py data/dyers/units.jsonl data/dyers/unit_overrides.jsonl data/nps_us/units.jsonl data/dyers/units_fixed.jsonl
      step 2 python3 pipeline/score_dyers_vs_cwss.py data/dyers data/external/acw_battle_data data/scores
      step 2 python3 pipeline/match_witnesses.py data/dyers/units_fixed.jsonl data/nps_us/units.jsonl data/scores/dyer_to_nps.csv data/cwa/cwa_units.json data/witness/matches.json
      step 2 python3 pipeline/vote_witnesses.py data/dyers/units_fixed.jsonl data/witness/matches.json data/nps_us/units.jsonl data/cwa/cwa_units.json data/dyers/units_clean.jsonl ;;
    dyers)
      step 1 python3 pipeline/extract_dyers.py data/dyers/units_clean.jsonl data/dyers/claims_rules_raw.jsonl
      python3 pipeline/fix_years.py data/dyers/claims_rules_raw.jsonl $W data/dyers/claims_rules.jsonl data/dyers/fix_years_report.txt ;;
    events)
      step 2 python3 pipeline/anchor_events.py data/dyers/claims_rules.jsonl $W data/dyers/events.jsonl data/dyers
      step 1 python3 pipeline/apply_ai_resolutions.py data/dyers/canonical_events.jsonl $W data/ai data/ai
      step 2 python3 pipeline/merge_events.py data/dyers data/ai data/events $W
      step 1 python3 pipeline/places_inventory.py data/dyers data/events data/places
      step 5 python3 pipeline/geocode.py data/places data/external/gnis/gnis_index.tsv data/events
      step 3 python3 pipeline/resolve_mentions.py data/places data/external/gnis/gnis_index.tsv data/dyers data/events data/places/mention_resolution.jsonl data/scores/mention_resolution.txt ;;
    links)
      step 2 python3 pipeline/score_dyers_vs_cwss.py data/dyers data/external/acw_battle_data data/scores ;;
    or)
      if [ -f ~/db/civil_war.db ]; then step 3 python3 pipeline/resolve_namesakes.py data/or/placements.jsonl data/external/acw_battle_data/nps_units.csv ~/db/civil_war.db data/scores/namesakes_report.txt; else echo "resolve_namesakes skipped: no database yet (run db, then or again)"; fi
      if [ -f ~/db/civil_war.db ]; then step 3 python3 pipeline/resolve_namesakes.py data/wikipedia/oob_placements.jsonl data/external/acw_battle_data/nps_units.csv ~/db/civil_war.db data/scores/namesakes_wikipedia.txt data/wikipedia/oob_battles.json data/events/events.jsonl; fi
      step 1 python3 pipeline/or_to_claims.py data/or/placements.jsonl data/or/tables.jsonl data/scores/dyer_to_nps.csv data/events data/or/claims_or.jsonl
      step 1 python3 pipeline/compare_oob.py data/wikipedia/oob_placements.jsonl data/or/claims_or.jsonl data/events data/wikipedia data/scores/oob_vs_or.txt
      step 1 python3 pipeline/wikipedia_to_claims.py data/wikipedia/oob_placements.jsonl data/wikipedia/oob_battles.json data/scores/dyer_to_nps.csv data/events data/wikipedia/claims_wikipedia.jsonl
      step 1 python3 pipeline/wp_regiment_claims.py data/wikipedia/regiments data/events data/external/acw_battle_data/nps_units.csv data/scores/dyer_to_nps.csv data/wikipedia/claims_wp_regiments.jsonl
      step 1 python3 pipeline/or_stations.py data/or/placements.jsonl data/or/tables.jsonl data/manual/or_regions.psv data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/external/acw_battle_data/nps_units.csv data/derived/or_stations.json
      step 1 python3 pipeline/extract_nps_histories.py data/nps/units.jsonl data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/derived/nps_confederate_histories.json
      step 1 python3 pipeline/extract_state_histories.py data/external/state_histories data/events/events.jsonl data/external/acw_battle_data/nps_units.csv data/derived/state_histories.json data/scores/state_histories_report.txt
      step 3 python3 pipeline/extract_state_stations.py data/external/state_histories data/external/acw_battle_data/nps_units.csv data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/derived/state_stations.json data/scores/state_stations_report.txt data/events/events.jsonl
      step 1 python3 pipeline/nps_battles_to_claims.py data/external/acw_battle_data $W data/scores/dyer_to_nps.csv data/events data/nps/claims_nps_battles.jsonl
      step 1 python3 pipeline/check_confederate.py data/or/claims_or.jsonl data/events data/external/acw_battle_data data/nps/units.jsonl data/scores/confederate_check.txt
      if [ -f ~/db/civil_war.db ]; then stephead 8 python3 pipeline/battle_monuments.py ~/db/civil_war.db data/external/battles data/battles data/scores/battle_monuments.txt; else echo "battle_monuments skipped: no database yet"; fi ;;
    datelines)   # ~105 s: run it alone
      if [ -d ~/or/txt ]; then step 1 python3 pipeline/or_datelines.py ~/or/txt data/or/volumes.json data/or/placements.jsonl data/or/tables.jsonl data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/external/acw_battle_data/nps_units.csv data/or/datelines.jsonl data/derived/or_datelines.json; else echo "or_datelines skipped: no OR texts in ~/or/txt (kept data/derived/or_datelines.json)"; fi
      if [ -f ~/db/civil_war.db ]; then stephead 6 python3 pipeline/validate_datelines.py ~/db/civil_war.db data/derived/or_datelines.json; fi ;;
    db|db_build|db_finish)   # db = db_build + db_finish (~110-170 s together: on a busy machine run the two halves in separate calls)
      if [ "$s" != db_finish ]; then
        mkdir -p "$(dirname "$DB")"; rm -f "$DB.new" "$DB.new-journal"
        (cd pipeline && step 2 python3 build_db.py .. "$DB.new")
        mv -f "$DB.new" "$DB"; rm -f "$DB-journal"     # a build cut off midway never replaces the last good database
      fi
      if [ "$s" != db_build ]; then
        python3 pipeline/event_context_check.py "$DB" data/external/gnis/gnis_index.tsv data/scores/event_relocations.csv
        step 1 python3 pipeline/brigade_inference.py "$DB" data/scores/brigade_inference.txt
        stephead 4 python3 pipeline/score_gold.py "$DB" data/gold/units data/events/events.jsonl data/scores/gold_scores.txt data/scores/gold_detail.jsonl
      fi ;;
    war)
      python3 pipeline/export_war.py "$DB" viewer/war/data ;;
    review)   # cards for the review page (artifact "Dyer's Review Queue"); needs the Dyer's scan, not in the work copy
      SRC=${SOURCES:-$HOME/mnt/civil_war_viewer/sources}
      python3 pipeline/review_cases.py "$SRC/08697590_3359_djvu.xml" "$SRC/dyers_compendium.pdf" data/review ;;
    checks)
      python3 pipeline/db_checks.py "$DB" > data/scores/db_checks.txt
      step 1 python3 pipeline/db_metrics.py "$DB"
      stephead 1 python3 pipeline/fast_jumps.py "$DB" data/scores/fast_jumps.csv data/scores/fast_jumps.txt
      stephead 3 python3 pipeline/consistency_checks.py "$DB" . data/scores/consistency.txt data/scores/review_queue.csv
      cp "$DB" civil_war.db; echo "copied to civil_war.db" ;;
  esac
  python3 pipeline/stamps.py save "$s"
done
