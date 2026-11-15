# Snippet tests

Run from the project folder, no data needed (they take a second):

    python3 -m unittest discover -s pipeline/tests -v

Each test is a short piece of source text and the behaviour a past fix established; the docstring names the case and where it came
from (the hand-offs in the Project docs). Rule: **a rule fix comes with a test in the same session**; a test that fails after a
change means the change broke an earlier fix, not that the test is out of date (check the case first).

Standard library only (`pytest` is not installed in the remote shell). Tests import the scripts' own functions and patterns; where a
rule sits inside a long `main()` and cannot be called alone, add its test after the function is split (roadmap T3.3) and list it below.

Files: `test_extract_dyers.py` and `test_extract_dyers_more.py` (Dyer's text rules), `test_fix_years.py`, `test_or_parsing.py`,
`test_state_stations.py`, `test_common.py` (distance, speed test, dates, state boxes, `stable_id`, `claim_fingerprint`), `test_refcheck.py` (stale generated-file check), `test_unit_registry.py` (unit id registry), `test_paths.py` (default arguments equal what rebuild.sh passes), `test_states.py` (the state table builder, and that every table the scripts build from it keeps the disagreements listed in `cwv/states.py`), `test_tools.py` (compare_builds, claims_diff,
metrics, and review_import's withdraw guard, run as command lines on small made-up folders).

Pending (need the T3.3 split or Wikidata/db fixtures): the whole-sentence behaviour of the Confederate-government skip in
`extract_state_stations.py` (only its pattern is tested), year-run shifts in `fix_years.main` (only `misprints()` is tested).
