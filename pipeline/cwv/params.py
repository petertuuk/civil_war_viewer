"""Named numbers of the pipeline (roadmap T3.8). Each has one line saying what it is; the values are exactly the ones that stood as
literals in the scripts before (checked by comparing the code of every changed script with the old code, constants filled in).

Changing a value here changes outputs: rerun the stages that import this package (stamps.py notices) and compare with a reference.
Not here: the weights of source ranking and the one-off numbers inside a single formula; the viewer (index.html) has its own copies of
MARCH_GAP_DAYS and STALE_DAYS and they must match.
"""

# --- impossible moves: common.too_fast, the fast-jump and two-places checks, teleports ----------------------------------------------
MIN_KM = 300                    # a move shorter than this is never called impossible (rail and steamer reach it in a day)
MAX_KMDAY = 250                 # and a longer one is impossible only above this many km per day
TWO_PLACES_KM = 150             # one unit, whole, in two events on the same days this far apart (consistency_checks)
FRONT_TRIP_DAYS = 45            # a unit's first days are left out of fast-jump and teleport checks (the trip to the front)
FAST_JUMP_PREC_MAX_M = 25000    # fast jumps ignore positions less precise than this (metres)
SUPPORT_DAYS = 10               # a jump is "supported" by the unit's other positions within this many days ...
SUPPORT_KM = 50                 # ... and this many km of each end

# --- export_war: choosing and drawing a unit's position (index.html repeats MARCH_GAP_DAYS and STALE_DAYS) -----------------------------
MARCH_GAP_DAYS = 21             # up to this many days between a unit's own fixes the map draws a march between them
STALE_DAYS = 10                 # up to this many days after the last fix the unit is still drawn (marked stale)
CAMPAIGN_DAYS = 20              # a claim spanning more days than this is a campaign, not a position (a siege is kept)
LOOSE_SPAN_DAYS = 31            # a fix spanning up to this many days is the unit's own; longer ones are drawn loose
COARSE_M = 10000                # a fix this imprecise or worse (a corps headquarters) is "coarse" and ranks last
MONUMENT_M = 500                # a fix this precise or better counts as monument grade
SHORT_SPAN_DAYS = 3             # a fix spanning more days than this ranks below a shorter one

# --- distances used to place places and tell namesakes apart ----------------------------------------------------------------------
GEOCODE_FEATURE_KM = 150        # geocode: a match this far from the event's context is rejected (other features)
GEOCODE_TOWN_KM = 300           # ... (a town, when several towns of the state fit)
GEOCODE_ONLY_TOWN_KM = 500      # ... (the state's only town of that name)
GEOCODE_GENERIC_KM = 75         # ... (a name with a generic word dropped: Harrison's Landing is not Harrison)
STATION_PREV_KM = 400           # state-history stations: a place within this of the previous claim is preferred
STATION_STALE_KM = 700          # ... with no previous claim in the chapter, one this near the last known one is taken
STATION_JUMP_KM = 400           # ... a claim this far from the previous one within 3 days is skipped
NAMESAKE_FAR_KM = 400           # resolve_namesakes: a namesake this far from the row's brigade-mates is far
NAMESAKE_NEAR_KM = 200          # ... and one within this is near
NAMESAKE_MATES_DAYS = 30        # ... brigade-mates' positions count within this many days of the row
NAMESAKE_UNIT_DAYS = 60         # ... a namesake's own position counts within this many days
SERVICE_SLACK_DAYS = 30         # build_db: secondary claims this far outside a unit's Dyer's service are rejected

# --- confidence of claims written by the extractors (0-1) --------------------------------------------------------------------------
DYERS_BASE_CONF = 0.8           # Dyer's dated item (items_from)
DYERS_UNDATED_CONF = 0.3        # Dyer's item with no date
DYERS_ROLLED_PENALTY = 0.3      # subtracted when the years of the entry had to be rolled over
DYERS_CONF_FLOOR = 0.1          # confidence never goes below this when a listed-out-of-order date is repaired
DYERS_ORDER_PENALTY = 0.1       # ... and loses this
DYERS_NO_PLACE_FACTOR = 0.8     # multiplied in when no place is named and the last place is used
DYERS_MOVE_FACTOR = 0.8         # a movement claim (left/en route/arrived) is this much less certain than its item
DYERS_EVENT_DISCOUNT = 0.1      # a participation claim loses this against its item
DYERS_KNOWN_AS_CONF = 0.6       # "see ..." known-as claim
DYERS_ASSIGNED_CONF = 0.85      # "assigned to ..." subordinate_to claim
DYERS_ATTACHED_CONF = 0.3       # undated "attached to ..." subordinate_to claim
DYERS_NUMBERS_EVENT_CONF = 0.75 # numbers (killed, wounded) tied to one event
DYERS_NUMBERS_TOTAL_CONF = 0.95 # whole-service losses
DYERS_LOW_CONF = 0.5            # below this a claim is counted as low confidence in the run's statistics
DATELINE_CONF = {"regiment": 0.65, "brigade": 0.6, "division": 0.5, "corps": 0.4}   # OR dateline claims, by echelon of the signer
STATION_AT_CONF = 0.55          # state history: "at <place>, <date>"
STATION_STAY_CONF = 0.6         # ... a staying verb (remained, occupied)
STATION_MOVE_CONF = 0.45        # ... a movement verb (the destination on the date)
STATION_MONTH_PENALTY = 0.1     # ... less when the date is only a month
EVENT_ROUTE_CONF = 0.6          # event position taken from the route of its participants
EVENT_GEOCODE_CONF = 0.6        # event position taken from the gazetteer
EVENT_WIKIDATA_CONF = 0.9       # event position from Wikidata
EVENT_OTHER_CONF = 0.5          # event position from any other source
EVENT_NAME_CONF = 0.8           # Dyer's name for a merged event
POS_DIVISION_CONF = 0.5         # position inside a battle: division level
POS_BRIGADE_CONF = 0.6          # ... brigade level
POS_CAMP_CONF = 0.8             # ... a camp (regiment level)
POS_REGIMENT_CONF = 0.85        # ... any other regiment-level placement
