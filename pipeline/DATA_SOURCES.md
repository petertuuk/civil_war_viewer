# Data sources: where everything comes from

Inventory for a future `bootstrap` script (backlog: rebuild the project on a fresh machine from a clone). Written
2026-11-13 from the fetch-script docstrings, the data folders and the design brief. It lists every input that git does
not hold (`.gitignore` leaves out `sources/`, `data/external/` and most of `data/`), where it comes from, how it was
fetched and what is still manual. Items marked **CONFIRM** were inferred, not read from a script or a README.

Fetching notes (from the hand-off): the device shell reaches archive.org, Wikipedia, Wikidata, USGS S3, AWS terrain
tiles, arcgis.com, npgallery.nps.gov, GitHub raw; it does NOT reach nps.gov (so `fetch_nps_units.py` must run on a
machine that does), and hmdb.org returns 403 to scripts (do not fetch it). Use the User-Agent `CivilWarViewer/0.2`; no
names or emails in requests.

## 1. In git: nothing to fetch

Hand-made inputs: `data/gold/**`, `data/manual/*.psv` + `sample_regiments.json`, `data/dyers/unit_overrides.jsonl`,
`flag_decisions.jsonl`, `data/ai/event_resolutions_batch*.psv` + `cluster_keys_v1.jsonl`, `data/places/place_overrides.csv`,
`data/or/table_overrides.psv` + `volumes.json` (the 111 archive.org ids), `data/battles/osm_gettysburg_monuments.json`,
`data/wikidata/*.json` (pulled and enriched Wikidata events).

## 2. Source documents (not in git; re-downloadable)

| Local path | Source | How fetched | Read by |
| --- | --- | --- | --- |
| `sources/08697590_3359_djvu.xml` (168 MB), `..._chocr.html.gz`, `dyers_compendium.pdf`, `dyers_compendium.txt` | Dyer's *Compendium of the War of the Rebellion* (1908), Internet Archive item `08697590.3359.emory.edu` (https://archive.org/details/08697590.3359.emory.edu) | manual download; no script. **CONFIRM** exact file URLs (`https://archive.org/download/08697590.3359.emory.edu/<file>`) | `segment_dyers.py`, `parse_event_index.py` |
| `~/or/txt/<id>.txt` (111 files, scratch, not in the project) | *Official Records* Series I, archive.org items listed in `data/or/volumes.json` | `https://archive.org/download/<id>/<id>_djvu.txt`, then collapse whitespace with `sed -i -E 's/[ \t]+/ /g; s/^ //; s/ $//'` (one-off command in the hand-off, "Fresh session setup") | `locate_or_tables.py`, `parse_or_all.py`, `or_datelines.py` |
| `data/external/state_histories/*.txt` | archive.org djvu texts: `cu31924092908536`, `cu31924092908544`, `historiesofsever03clar`, `cu31924092908569`, `historiesofsever05clar` (Clark, NC regiments v.1-5), `officialstatisti03miss` (Rowland, Mississippi 1908 v.3). Also on disk but not in its README: `cu31924028794042`, `cu31924032778700` (**CONFIRM** titles: presumably the Tennessee and Alabama histories) | `curl -sSL -A CivilWarViewer/0.2 https://archive.org/download/<id>/<id>_djvu.txt`, whitespace collapsed (README in that folder) | `extract_state_histories.py` |

## 3. Datasets fetched by a script

| Local path | Source | Script and command | Notes |
| --- | --- | --- | --- |
| `data/external/acw_battle_data/` (CSVs incl. `nps_units.csv`, `cwsac_*`, `cwss_*`, `dyer_engagements.csv`) | Jeffrey B. Arnold, `acw_battle_data`: https://github.com/jrnold/acw_battle_data (figshare DOI 10.6084/m9.figshare.1515995); ODC-BY / BSD | `git clone`, then the built CSVs. No script; the tool `invoke build` needs conda | **CONFIRM** which commit or figshare version was used, and whether the CSVs come from a build or a download; pin it. `data/external/_to_delete_failed_git_clone` is a failed attempt |
| `data/nps/html/*.html`, `data/nps/units.jsonl` (Confederate) | NPS Soldiers and Sailors, `https://www.nps.gov/civilwar/search-battle-units-detail.htm?battleUnitCode=<code>` | `python3 pipeline/fetch_nps_units.py data/external/acw_battle_data/nps_units.csv data/nps --side Confederate` (resumable, cached; 3,579 pages) | nps.gov is not reachable from the device shell |
| `data/nps_us/html.tgz`, `units.jsonl` (Union) | same site | probably the same script with `--side US` (**CONFIRM**; stored as a tarball) | read by `vote_witnesses.py`, `match_witnesses.py` |
| `data/wikidata/` | Wikidata SPARQL | `python3 pipeline/pull_wikidata.py data/wikidata` (`--test`, `--offline` from `raw/`); rate-limited | output is in git |
| `data/wikipedia/oob.jsonl`, `battles.jsonl`, `infobox_by_qid.json` | English Wikipedia (CC BY-SA 4.0) | `fetch_wikipedia.py --category "American Civil War orders of battle" data/wikipedia/oob.jsonl`; `wikipedia_infobox.py data/wikidata/wikidata_civil_war_events_v2.json data/wikipedia`; then `enrich_wikidata.py`; then `parse_wikipedia_oob.py` | `battle_titles.txt` is the titles list for the infobox step |
| `data/wikipedia/regiments/` | Wikipedia, Category:Units and formations of the Confederate States Army (depth 3) | `python pipeline/fetch_wp_regiments.py data/wikipedia/regiments` (resumable) | |
| `data/external/gnis/gnis_index.tsv` (+ `gnis_extra.tsv`) | USGS GNIS, public domain: `https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/` files `DomesticNames/DomesticNames_National_Text.zip`, `Topical/HistoricalFeatures_National_Text.zip`, `Topical/AllNames_National_Text.zip` | unzip, then `python pipeline/gnis_index.py <gnis_dir> data/external/gnis/gnis_index.tsv` | the raw zips are not kept in the project |
| `data/external/forts/` | Wikidata (`wikidata_forts.rq` -> `wikidata_forts.csv`) and OpenStreetMap via Overpass (`osm_forts.ql` -> `osm_forts_petersburg_washington.json`), both fetched 2026-11-12 | queries are saved beside the outputs; then `python pipeline/forts_gazetteer.py data/external/forts data/external/gnis/gnis_index.tsv data/external/gnis/gnis_extra.tsv` | Overpass is often overloaded |
| `data/external/naturalearth/*.geojson` | Natural Earth 1:10m (public domain): admin-1 states, coastline, lakes, rivers | no script; **CONFIRM** URL (naturalearthdata.com or its GitHub mirror) | only the map's basemap; `basemap.py` |
| terrain relief | AWS Terrain Tiles (terrarium PNG) | `terrain.py W,S,E,N zoom out.png`; the viewer also fetches tiles live | no local store |

## 4. Battle detail (`data/external/battles/`)

Read by `battle_monuments.py` (report: `data/scores/battle_monuments.txt`).

| File | Source | Fetch |
| --- | --- | --- |
| `npgallery_monuments.jsonl` | NPS NPGallery "Civil War Monuments and Markers Digital Collection" (https://npgallery.nps.gov/): listing `SearchResults?pagesize=500&page=N&collection=<id>` embeds JSON; detail pages carry the coordinates (minus sign missing on longitudes) | raw parse was done by hand in a session; **CONFIRM** the collection id and keep the fetch code |
| `shiloh_tablets_0/1/2.json` | "ShilohWeb" ArcGIS FeatureServer, `https://services2.arcgis.com/MPzXAppZq4kTyKOS/arcgis/rest/services/ShilohWeb/FeatureServer` (layers 0, 1, 2) | ArcGIS REST query; no script |
| `ga_markers.json` (2,190 markers) | Georgia Historical Society marker layer, `services8.arcgis.com/mPCcw2QHTvtUPtyA/.../GA_Historical_Markers/FeatureServer/0` (https://historicalmarkers.georgiahistory.com/) | ArcGIS REST query; no script; **CONFIRM** the full path |
| `osm_antietam_monuments.json` | OpenStreetMap (ODbL), OSM API `api/0.6/map?bbox=` in about 0.03-degree tiles (Overpass was overloaded) | no script |
| `ga_markers_read.psv` | **Hand-read** (137 markers, 127 placements). Not re-fetchable: back it up | manual |
| `aotw/` (`areas.json`, `map_*.html`) | in progress in another session (started 2026-11-14 01:50 UTC): extracting unit locations during battles from published maps. Per Peter, 2026-11-13 | **CONFIRM** which maps (the folder name `aotw` is unexplained), where they come from and how they were fetched, once that session documents it |
| `data/battles/osm_gettysburg_monuments.json` (in git) | OpenStreetMap via Overpass | `battle_positions.py` docstring |

## 5. Hand-collected, no fetch script

- `data/cwa/cwa_pages.tgz`, `cwa_units.json`: Civil War Archive unit-history pages (`Unreghst_*.htm`; **CONFIRM** site,
  presumably civilwararchive.com). A checking witness only; the site claims copyright, so keep pointers, not text.
- `data/witness/` (crops and pages of Dyer's scans for hand-checking) and `data/witness/matches.json`: matches are rebuilt by
  `rebuild.sh units`; the crops were made by archived scripts (`_archive/pipeline/flag_crops.py`, `crop_units_scratch.py`).
- Derived but slow: `data/dyers/units.jsonl` (from `segment_dyers.py`), `data/dyers/event_index.jsonl` (`parse_event_index.py`),
  `data/or/tables.jsonl` + `placements.jsonl` (`locate_or_tables.py`, `parse_or_all.py`), `data/wikipedia/oob_placements.jsonl`.
  These parse steps are not in `rebuild.sh` (it starts from `units`).

## 6. Draft order for a bootstrap script

1. Clone the repo (hand-made inputs arrive with it).
2. Download: Dyer's files (`sources/`), the 111 OR texts, the state-history texts, `acw_battle_data` (pinned), GNIS zips.
3. Fetch: NPS unit pages (on a machine that reaches nps.gov), Wikipedia (OOB, regiments, infoboxes), Wikidata, forts queries,
   battle sources (section 4), Natural Earth.
4. Build indexes and parse: `gnis_index.py`, `forts_gazetteer.py`, `segment_dyers.py`, `parse_event_index.py`,
   `locate_or_tables.py`, `parse_or_all.py`, `parse_wikipedia_oob.py`.
5. `rebuild.sh` stages: `units dyers events links`, then `db`, then `or`, `datelines`, `db` again (per the hand-off: on a
   fresh scratch `or` and `datelines` need a built db), then `checks war`.
6. Compare the result with the current `civil_war.db` (claim counts, `data/scores/gold_scores.txt`) before trusting it.

Back up first, whatever else happens: `sources/` (if the exact files cannot be re-fetched), `data/witness`, `data/cwa`,
`data/nps_us`, `data/external/battles/ga_markers_read.psv` and the other raw battle files.
