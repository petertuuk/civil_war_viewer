# Pipeline scripts

One line per script, from its docstring (regenerate the lists when scripts change). `rebuild.sh <stage>` runs the stages; run it in the local work copy (see `workcopy.py`).

Stages in order: `units` → `dyers` → `events` → `links` → `or` → `datelines` → `db` (= `db_build` + `db_finish`) → `checks` → `war`. After a change anywhere, run `events or datelines db checks war` (a second `or datelines` after a db change): stages whose inputs have not changed are skipped (`stamps.py`; `FORCE=1` runs them all).

## Rebuild stages

| Script | Stage | What it does |
| --- | --- | --- |
| `fix_units.py` | units | Apply hand-checked unit corrections to the segmented Dyer's units, before linking, matching and voting. |
| `match_witnesses.py` | units | Match each Dyer's unit to its clean transcriptions (NPS page, Civil War Archive entry) by content. |
| `score_dyers_vs_cwss.py` | units | Link Dyer's units to NPS unit codes, and score Dyer's battle extraction against the NPS/CWSS units-engaged table (which the NPS compiled from Dyer's). |
| `vote_witnesses.py` | units | Clean Dyer's OCR text by word-level voting against hand-typed transcriptions. |
| `extract_dyers.py` | dyers | Rule-based claim extraction from Dyer's Compendium unit entries (no AI). |
| `fix_years.py` | dyers | Correct years Dyer's text leaves out and the year tracker got wrong. |
| `anchor_events.py` | events | Build canonical events from regimental mention clusters and anchor them to Wikidata and Dyer's index. |
| `apply_ai_resolutions.py` | events | Apply AI (historical-knowledge) resolutions to canonical event clusters. |
| `geocode.py` | events | Geocode the places inventory (data/places/places_inventory.csv) against GNIS (data/external/gnis/gnis_index.tsv). |
| `merge_events.py` | events | Merge duplicate event clusters into events, and link events to parents. |
| `places_inventory.py` | events | Inventory distinct places (name + state) mentioned in Dyer's, ready for geocoding. |
| `resolve_mentions.py` | events | Resolve ambiguous Dyer's place mentions per unit, from the unit's own route. |
| `check_confederate.py` | or | Compare Confederate units at single battles across three sources. |
| `compare_oob.py` | or | Link Wikipedia order-of-battle placements to events, and compare them with the Official Records. |
| `extract_nps_histories.py` | or | Dated positions from the NPS unit histories of Confederate units (Crute, Units of the Confederate States Army, via the NPS Soldiers and Sailors Database; data/nps/units.jsonl "over… |
| `extract_state_histories.py` | or | Battle participation from public-domain state unit histories (data/external/state_histories; see its README) |
| `extract_state_stations.py` | or | Dated positions (camped, stationed, ordered to, at X on a date) from the same state histories; years anchored to battle dates (data/derived/state_stations.json) |
| `nps_battles_to_claims.py` | or | Confederate battle participation from the NPS Soldiers and Sailors battle unit lists. |
| `or_stations.py` | or | Positions from Official Records organization tables |
| `or_to_claims.py` | or | Turn Official Records organization placements into claims. |
| `resolve_namesakes.py` | or | Tell namesake regiments apart in the Official Records organization tables by their brigade-mates. |
| `wikipedia_to_claims.py` | or | Turn Wikipedia order-of-battle placements into claims (a second source beside the Official Records). |
| `wp_regiment_claims.py` | or | Participation claims from the battle lists in Wikipedia infoboxes of Confederate unit articles. |
| `or_datelines.py` | datelines | Positions from the headings of Official Records letters and reports |
| `validate_datelines.py` | datelines | Check letter-heading claims (data/derived/or_datelines.json) against the same unit's other one-day positions in the database (unit_at with a single date, not from letter headings; … |
| `brigade_inference.py` | db | Infer participation from brigade companions. |
| `build_db.py` | db | Build the claims database (SQLite) from every pipeline output. |
| `event_context_check.py` | db | Move events that were geocoded to the wrong namesake town, using where their own units were. |
| `score_gold.py` | db | Score civil_war.db against the hand-checked test set (data/gold/units/*.txt). |
| `consistency_checks.py` | checks | Impossibility checks on civil_war.db and one review queue for everything that needs a person. |
| `db_checks.py` | checks | Sanity checks and agreement report on the claims database. |
| `fast_jumps.py` | checks | Fast jumps |
| `export_war.py` | war | Whole-war export for the map |

## Human review
Review page: artifact "Dyer's Review Queue" (https://claude.ai/artifact/Gqs91QQg7PqurevSbEn1uy, slug 804badf5-c8a6-4f20-aba2-58c07997c5d8). One card per case, answers kept in the artifact's db (collection `decisions`, owner-only).

| Script | Stage | What it does |
|---|---|---|
| `review_cases.py` | review | Cards from cases the pipeline cannot settle: Dyer's OCR flags (scan crop with the spot marked, readings from OCR/NPS/CWA) and year shifts fix_years.py refused (stretch, matched event, neighbours). Writes data/review/cases.json + img/. |
| `review_import.py` | by hand | Answers (data/review/decisions.jsonl, dumped from the artifact's db) -> data/dyers/flag_decisions.jsonl (vote_witnesses) and data/dyers/year_decisions.jsonl (fix_years). Then rebuild from units / dyers on, and republish the page's cases.json after `review`. |

## Shared modules

| Script | Used by | What it does |
| --- | --- | --- |
| `build_viewer.py` | used by export_war | Assemble a self-contained map page |
| `common.py` | used by brigade_inference, consistency_checks, event_context_check, export_war… | Small helpers shared by the pipeline scripts |
| `event_membership.py` | used by merge_events | Event membership |
| `manual_claims.py` | used by build_db | Load hand-made or uploaded claims (data/manual/*.json; generated ones in the same format |
| `nps_links.py` | used by build_db, nps_battles_to_claims, or_to_claims, wikipedia_to_claims… | Dyer's unit <-> NPS unit code links, cleaned. |
| `parse_or_organization.py` | used by parse_or_all | Parse an Official Records "Organization of ..." table into unit placements. |
| `resolve_events.py` | used by anchor_events, fix_years | Group Dyer's event index into canonical events, then resolve regimental battle mentions to them. |
| `theater.py` | used by build_db | Theater of an order-of-battle placement |
| `unit_match.py` | used by parse_or_all, parse_wikipedia_oob | Second-pass unit matcher for names the regiment matcher misses. |

## One-time tools (downloads, source parsing, map layers)

| Script | What it does |
| --- | --- |
| `basemap.py` | Period-neutral basemap for a map window, from Natural Earth (public domain): state outlines, coastline, |
| `battle_positions.py` | Positions of units inside a battle from battlefield monuments and markers mapped in OpenStreetMap. |
| `enrich_wikidata.py` | Fill gaps in the Wikidata event file from Wikipedia infoboxes. |
| `fetch_nps_units.py` | Fetch NPS Soldiers and Sailors unit histories (resumable, cached). |
| `fetch_wikipedia.py` | Fetch English Wikipedia wikitext for a category's articles, or for given titles. |
| `fetch_wp_regiments.py` | Fetch Wikipedia articles on Confederate units (wikitext), for infobox battle lists. |
| `forts_gazetteer.py` | Forts missing from GNIS, as extra GNIS-index rows (data/external/gnis/gnis_extra.tsv), read by every GNIS loader |
| `gnis_index.py` | Compact GNIS gazetteer for geocoding: official and variant names of the feature types a Civil War place |
| `locate_or_tables.py` | Find "Organization of ..." tables in Official Records Series I text files. |
| `parse_event_index.py` | Parse Dyer's Part II alphabetical index (printed pp. 595-659) into an event catalog. |
| `parse_or_all.py` | Parse every located Official Records organization table into unit placements. |
| `parse_wikipedia_oob.py` | Parse Wikipedia "order of battle" articles into unit placements. |
| `pull_wikidata.py` | Pull American Civil War events from Wikidata (re-runnable). |
| `segment_dyers.py` | Segment Part III (Regimental Histories) of Dyer's Compendium into one entry per unit. |
| `terrain.py` | Shaded relief for a map window, from AWS Terrain Tiles (terrarium PNG elevation, public domain sources: SRTM, USGS NED). |
| `wikipedia_infobox.py` | Read battle infoboxes from English Wikipedia for our Wikidata events. |
| `stamps.py` | Skip rebuild stages whose inputs have not changed (called by rebuild.sh around each stage). |
| `cwv/params.py` | Named numbers of the pipeline (speed test, day limits, distances, extractor confidences), one line each; changing one changes outputs (roadmap T3.8). |
| `cwv/paths.py` | Where things live (`ROOT`, `DB`, `OR_TXT`, `SOURCES`, the most used files) and the arguments rebuild.sh gives each script, used when a script is started with none: `python3 pipeline/export_war.py` (roadmap T3.6). |
| `cwv/states.py` | The 48 states, DC and the two period regions (Dakota, Indian Territory) with their codes, and `table()`, which builds the name→code / code→name tables 15 scripts used to spell out each; where the sources disagree (Dakota DT/SD, Indian Territory OK/IT, Washington WA/DC) the table that has it keeps it, listed in the file's docstring (roadmap T3.1a). The abbreviation tables ("ala", "n. c") are not here yet. |
| `workcopy.py` | Work in a local copy of the project; write back only what changed. |
| `wp_fetch.py` | Fetch Wikipedia search hits or plain-text extracts (with revision ids) for reading articles during review. |

## Checks (run by hand)

| Script | What it does |
| --- | --- |
| `coverage.py` | Map coverage on sample days, from the exported viewer data (viewer/war/data): units per side with a fix covering the |
| `score_extraction.py` | Score extracted claims for one unit against a hand-made answer key. |
| `teleports.py` | Count 'teleports' in units' Dyer's position records: consecutive located mentions (by date) more than 300 km apart |
| `validate_mention_resolution.py` | Check resolved Dyer's mentions (data/places/mention_resolution.jsonl) against independent positions of the same unit |
| `validate_state_histories.py` | Score state-history battle claims (data/scores/state_histories_report.jsonl, written by extract_state_histories.py) |

Retired scripts (early schema tests, scratch croppers, the old track builder) are in `_archive/pipeline/` at the project root.
