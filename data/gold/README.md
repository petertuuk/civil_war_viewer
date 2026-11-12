# Hand-checked test set (answer keys)

One file per regiment in units/*.txt. Written by reading the sources, not by running the pipeline.
Scored with pipeline/score_gold.py against civil_war.db.

Header lines `key: value`:
- unit, side, db_unit (the database unit id this key is scored against), same_as (other database ids that are really this unit: duplicates to be merged)
- organized, ended (YYYY-MM-DD; ended_how)
- sources (what was read), complete (yes = every engagement the sources give is listed, so extra database claims count against precision; no = battle-level only, extras go to review)

Item lines `T start[/end] | name | sources | note`:
- T = P engaged (battle, action, skirmish, siege, assault, capture, campaign, expedition, raid, reconnaissance, operations, pursuit, demonstration);
  M = named movement or march (matching it is neither required nor an error); ? = doubtful (a source lists it but it is unlikely or unconfirmed: not required, not an error)
- dates YYYY-MM-DD or YYYY-MM; source codes: dyers (Dyer's text, checked against the page image where noted), nps (NPS unit history), wiki (Wikipedia regiment article), know (general knowledge of the event: used only to date items a source names without a date)
- note: portion (detachment, Cos. A-B, reserve) or a reading note
