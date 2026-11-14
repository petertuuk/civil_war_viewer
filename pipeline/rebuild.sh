#!/bin/bash
# Rebuild everything downstream of the cleaned Dyer's text. Run from the project folder:
#   bash pipeline/rebuild.sh [stage ...]     stages: units dyers events links or datelines db checks war review (default: dyers events links or datelines db checks)
# Human review: answers from the review page -> data/review/decisions.jsonl -> python3 pipeline/review_import.py data/review/decisions.jsonl,
#   then units (OCR readings) or dyers (years) and everything after; 'review' remakes the cards (data/review/cases.json, img/).
# GNIS index: python3 pipeline/gnis_index.py <unzipped GNIS dir> data/external/gnis/gnis_index.tsv (once; see that file)
# Forts GNIS lacks: python3 pipeline/forts_gazetteer.py data/external/forts data/external/gnis/gnis_index.tsv data/external/gnis/gnis_extra.tsv (read with the index by gnis_index.index_lines)
# The remote-device shell allows ~170 s per call: run one or two stages per call there. Stages whose inputs have not
# changed since their last good run are skipped (pipeline/stamps.py); FORCE=1 bash pipeline/rebuild.sh ... runs them anyway.
set -eo pipefail   # a failing step stops the rebuild even when piped into tail
export PYTHONHASHSEED=0   # same inputs, same outputs (set and dict-of-set order otherwise varies run to run: ties, examples)
W=data/wikidata/wikidata_civil_war_events_v2_enriched.json
DB=${DB:-$HOME/db/civil_war.db}
stages=${@:-dyers events links or datelines db checks}
stages=$(echo " $stages " | sed 's/ db / db_build db_finish /g')   # db = db_build + db_finish
for s in $stages; do
  echo "== $s"
  # skip a stage whose inputs have not changed since its last good run (pipeline/stamps.py; FORCE=1 runs everything)
  if python3 pipeline/stamps.py check "$s"; then echo "   inputs unchanged since its last run: skipped"; continue; fi
  case $s in
    units)
      python3 pipeline/fix_units.py data/dyers/units.jsonl data/dyers/unit_overrides.jsonl data/nps_us/units.jsonl data/dyers/units_fixed.jsonl
      python3 pipeline/score_dyers_vs_cwss.py data/dyers data/external/acw_battle_data data/scores | tail -2
      python3 pipeline/match_witnesses.py data/dyers/units_fixed.jsonl data/nps_us/units.jsonl data/scores/dyer_to_nps.csv data/cwa/cwa_units.json data/witness/matches.json | tail -2
      python3 pipeline/vote_witnesses.py data/dyers/units_fixed.jsonl data/witness/matches.json data/nps_us/units.jsonl data/cwa/cwa_units.json data/dyers/units_clean.jsonl | tail -2 ;;
    dyers)
      python3 pipeline/extract_dyers.py data/dyers/units_clean.jsonl data/dyers/claims_rules_raw.jsonl | tail -1
      python3 pipeline/fix_years.py data/dyers/claims_rules_raw.jsonl $W data/dyers/claims_rules.jsonl data/dyers/fix_years_report.txt ;;
    events)
      python3 pipeline/anchor_events.py data/dyers/claims_rules.jsonl $W data/dyers/events.jsonl data/dyers | tail -2
      python3 pipeline/apply_ai_resolutions.py data/dyers/canonical_events.jsonl $W data/ai data/ai | tail -1
      python3 pipeline/merge_events.py data/dyers data/ai data/events $W | tail -2
      python3 pipeline/places_inventory.py data/dyers data/events data/places | tail -1
      python3 pipeline/geocode.py data/places data/external/gnis/gnis_index.tsv data/events | tail -5
      python3 pipeline/resolve_mentions.py data/places data/external/gnis/gnis_index.tsv data/dyers data/events data/places/mention_resolution.jsonl data/scores/mention_resolution.txt | grep resolved ;;
    links)
      python3 pipeline/score_dyers_vs_cwss.py data/dyers data/external/acw_battle_data data/scores | tail -2 ;;
    or)
      [ -f ~/db/civil_war.db ] && python3 pipeline/resolve_namesakes.py data/or/placements.jsonl data/external/acw_battle_data/nps_units.csv ~/db/civil_war.db data/scores/namesakes_report.txt | grep picked || echo "resolve_namesakes skipped: no database yet (run db, then or again)"
      [ -f ~/db/civil_war.db ] && python3 pipeline/resolve_namesakes.py data/wikipedia/oob_placements.jsonl data/external/acw_battle_data/nps_units.csv ~/db/civil_war.db data/scores/namesakes_wikipedia.txt data/wikipedia/oob_battles.json data/events/events.jsonl | grep picked
      python3 pipeline/or_to_claims.py data/or/placements.jsonl data/or/tables.jsonl data/scores/dyer_to_nps.csv data/events data/or/claims_or.jsonl | tail -1
      python3 pipeline/compare_oob.py data/wikipedia/oob_placements.jsonl data/or/claims_or.jsonl data/events data/wikipedia data/scores/oob_vs_or.txt | tail -1
      python3 pipeline/wikipedia_to_claims.py data/wikipedia/oob_placements.jsonl data/wikipedia/oob_battles.json data/scores/dyer_to_nps.csv data/events data/wikipedia/claims_wikipedia.jsonl | tail -1
      python3 pipeline/wp_regiment_claims.py data/wikipedia/regiments data/events data/external/acw_battle_data/nps_units.csv data/scores/dyer_to_nps.csv data/wikipedia/claims_wp_regiments.jsonl | tail -1
      python3 pipeline/or_stations.py data/or/placements.jsonl data/or/tables.jsonl data/manual/or_regions.psv data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/external/acw_battle_data/nps_units.csv data/derived/or_stations.json | tail -1
      python3 pipeline/extract_nps_histories.py data/nps/units.jsonl data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/derived/nps_confederate_histories.json | tail -1
      python3 pipeline/extract_state_histories.py data/external/state_histories data/events/events.jsonl data/external/acw_battle_data/nps_units.csv data/derived/state_histories.json data/scores/state_histories_report.txt | tail -1
      python3 pipeline/extract_state_stations.py data/external/state_histories data/external/acw_battle_data/nps_units.csv data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/derived/state_stations.json data/scores/state_stations_report.txt data/events/events.jsonl | grep "units with claims"
      python3 pipeline/nps_battles_to_claims.py data/external/acw_battle_data $W data/scores/dyer_to_nps.csv data/events data/nps/claims_nps_battles.jsonl | tail -1
      python3 pipeline/check_confederate.py data/or/claims_or.jsonl data/events data/external/acw_battle_data data/nps/units.jsonl data/scores/confederate_check.txt | tail -1
      [ -f ~/db/civil_war.db ] && python3 pipeline/battle_monuments.py ~/db/civil_war.db data/external/battles data/battles data/scores/battle_monuments.txt | head -8 || echo "battle_monuments skipped: no database yet" ;;
    datelines)   # ~105 s: run it alone
      [ -d ~/or/txt ] && python3 pipeline/or_datelines.py ~/or/txt data/or/volumes.json data/or/placements.jsonl data/or/tables.jsonl data/places/geocoded.csv data/external/gnis/gnis_index.tsv data/external/acw_battle_data/nps_units.csv data/or/datelines.jsonl data/derived/or_datelines.json | tail -1 || echo "or_datelines skipped: no OR texts in ~/or/txt (kept data/derived/or_datelines.json)"
      [ -f ~/db/civil_war.db ] && python3 pipeline/validate_datelines.py ~/db/civil_war.db data/derived/or_datelines.json | head -6 ;;
    db|db_build|db_finish)   # db = db_build + db_finish (~110-170 s together: on a busy machine run the two halves in separate calls)
      if [ "$s" != db_finish ]; then
        mkdir -p "$(dirname "$DB")"; rm -f "$DB.new" "$DB.new-journal"
        (cd pipeline && python3 build_db.py .. "$DB.new" | tail -2)
        mv -f "$DB.new" "$DB"; rm -f "$DB-journal"     # a build cut off midway never replaces the last good database
      fi
      if [ "$s" != db_build ]; then
        python3 pipeline/event_context_check.py "$DB" data/external/gnis/gnis_index.tsv data/scores/event_relocations.csv
        python3 pipeline/brigade_inference.py "$DB" data/scores/brigade_inference.txt | tail -1
        python3 pipeline/score_gold.py "$DB" data/gold/units data/events/events.jsonl data/scores/gold_scores.txt data/scores/gold_detail.jsonl | head -4
      fi ;;
    war)
      python3 pipeline/export_war.py "$DB" viewer/war/data ;;
    review)   # cards for the review page (artifact "Dyer's Review Queue"); needs the Dyer's scan, not in the work copy
      SRC=${SOURCES:-$HOME/mnt/civil_war_viewer/sources}
      python3 pipeline/review_cases.py "$SRC/08697590_3359_djvu.xml" "$SRC/dyers_compendium.pdf" data/review ;;
    checks)
      python3 pipeline/db_checks.py "$DB" > data/scores/db_checks.txt
      python3 pipeline/fast_jumps.py "$DB" data/scores/fast_jumps.csv data/scores/fast_jumps.txt | head -1
      python3 pipeline/consistency_checks.py "$DB" . data/scores/consistency.txt data/scores/review_queue.csv | head -3
      cp "$DB" civil_war.db; echo "copied to civil_war.db" ;;
  esac
  python3 pipeline/stamps.py save "$s"
done
