"""Load a hand-converted sample (24th Michigan Infantry, 1862-1865) into the
claims schema and print the unit's derived track.

Usage:  python load_sample.py            (writes sample.db next to this file)

The claims below were converted by hand from the regiment's dated service
record (civilwarintheeast.com, which follows Dyer's Compendium). Coordinates
are approximate representative points entered by hand for this test.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "sample.db"
NOW = datetime.now().isoformat(timespec="seconds")

if DB.exists():
    DB.unlink()
con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys = ON")
con.executescript((HERE / "schema.sql").read_text())


def ins(table, **cols):
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = con.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", tuple(cols.values()))
    return cur.lastrowid


# --- sources -----------------------------------------------------------------
S_WEB = ins("source", title="24th Michigan Infantry Regiment timeline", kind="website",
            url="https://civilwarintheeast.com/us-regiments-batteries/michigan/24th-michigan/",
            fetched_at=NOW, notes="Dated service record following Dyer's Compendium")
S_DYER = ins("source", title="A Compendium of the War of the Rebellion (Dyer, 1908)",
             kind="compendium", citation="Vol. 3, Michigan infantry", public_domain=1)
S_MANUAL = ins("source", title="Hand-entered coordinates for schema test", kind="manual")

# --- canonical entities ------------------------------------------------------
USA = ins("side", name="United States")
CSA = ins("side", name="Confederate States")

U24 = ins("unit", side_id=USA, echelon="regiment", branch="infantry", state="MI", number=24,
          display_name="24th Michigan Infantry")
IRON = ins("unit", side_id=USA, echelon="brigade", branch="infantry",
           display_name="Iron Brigade", notes="Numbered 1st or 4th Brigade, 1st Division, 1st Corps at different times")

MORROW = ins("person", display_name="Henry A. Morrow", side_id=USA)
EDWARDS = ins("person", display_name="Albert M. Edwards", side_id=USA)

P = {}
def place(key, name, kind, state, lat, lon, prec, geom=None):
    P[key] = ins("place", display_name=name, kind=kind, state=state, lat=lat, lon=lon,
                 precision_m=prec, geometry_json=geom)

place("detroit", "Detroit", "town", "MI", 42.331, -83.046, 3000)
place("washington", "Washington", "town", "DC", 38.895, -77.036, 5000)
place("frederick", "Frederick", "town", "MD", 39.414, -77.411, 2000)
place("sharpsburg", "Sharpsburg", "town", "MD", 39.458, -77.749, 2000)
place("warrenton", "Warrenton", "town", "VA", 38.714, -77.795, 2000)
place("rfp_rr", "Richmond, Fredericksburg & Potomac Railroad (Aquia Creek section)", "railroad", "VA",
      38.39, -77.43, 10000,
      '{"type":"LineString","coordinates":[[-77.40,38.47],[-77.46,38.30]]}')
place("falmouth", "Falmouth", "town", "VA", 38.324, -77.468, 1500)
place("fredericksburg", "Fredericksburg", "town", "VA", 38.303, -77.461, 2000)
place("fitzhugh", "Fitzhugh's Crossing", "ford", "VA", 38.27, -77.43, 2000)
place("chancellorsville", "Chancellorsville", "crossroads", "VA", 38.311, -77.635, 2000)
place("gettysburg", "Gettysburg", "town", "PA", 39.831, -77.231, 2000)
place("manassas_gap", "Manassas Gap", "other", "VA", 38.92, -78.08, 5000)
place("haymarket", "Haymarket", "town", "VA", 38.812, -77.636, 2000)
place("mine_run", "Mine Run", "river", "VA", 38.33, -77.79, 5000)
place("wilderness", "The Wilderness", "region", "VA", 38.31, -77.75, 4000)
place("spotsylvania", "Spotsylvania Court House", "town", "VA", 38.201, -77.589, 2000)
place("jericho_mills", "Jericho Mills", "ford", "VA", 37.93, -77.53, 3000)
place("totopotomoy", "Totopotomoy Creek", "river", "VA", 37.67, -77.33, 4000)
place("bethesda", "Bethesda Church", "crossroads", "VA", 37.64, -77.29, 2000)
place("cold_harbor", "Cold Harbor", "crossroads", "VA", 37.59, -77.29, 2000)
place("petersburg", "Petersburg", "town", "VA", 37.227, -77.402, 3000)
place("globe_tavern", "Globe Tavern", "crossroads", "VA", 37.17, -77.40, 2000)
place("burgess_mill", "Burgess Mill", "crossroads", "VA", 37.12, -77.50, 3000)
place("springfield", "Springfield", "town", "IL", 39.799, -89.644, 3000)

E = {}
def event(key, kind, name, parent=None):
    E[key] = ins("event", kind=kind, display_name=name, parent_event_id=E.get(parent))

event("fredericksburg", "battle", "Battle of Fredericksburg")
event("mud_march", "march", "Mud March")
event("chanc_campaign", "campaign", "Chancellorsville Campaign")
event("fitzhugh", "engagement", "Fitzhugh's Crossing", "chanc_campaign")
event("chancellorsville", "battle", "Battle of Chancellorsville", "chanc_campaign")
event("gb_campaign", "campaign", "Gettysburg Campaign")
event("gettysburg", "battle", "Battle of Gettysburg", "gb_campaign")
event("bristoe", "campaign", "Bristoe Campaign")
event("haymarket", "engagement", "Haymarket", "bristoe")
event("mine_run", "campaign", "Mine Run Campaign")
event("overland", "campaign", "Overland Campaign")
event("wilderness", "battle", "Battle of the Wilderness", "overland")
event("spotsylvania", "battle", "Battle of Spotsylvania Court House", "overland")
event("north_anna", "battle", "Battle of North Anna", "overland")
event("totopotomoy", "battle", "Battle of Totopotomoy Creek", "overland")
event("cold_harbor", "battle", "Battle of Cold Harbor", "overland")
event("petersburg", "siege", "Siege of Petersburg")
event("weldon", "battle", "Battle of Globe Tavern", "petersburg")
event("boydton", "battle", "Battle of Boydton Plank Road", "petersburg")
event("lincoln_funeral", "political", "Lincoln funeral")

# --- claims ------------------------------------------------------------------
def claim(ctype, table, span, conf=0.9, status="accepted", src=S_WEB, note=None, **detail):
    cid = ins("claim", claim_type=ctype, source_id=src, source_span=span, confidence=conf,
              extracted_by="manual", extracted_at=NOW, status=status, review_note=note)
    ins(table, claim_id=cid, **detail)
    return cid

M24 = "24th Michigan"

def at(place_key, mention, start, end=None, prec="day", presence="present", span=None, conf=0.9):
    claim("unit_at", "claim_unit_at", span or f"{mention} {start}", conf,
          unit_mention=M24, unit_id=U24, place_mention=mention, place_id=P[place_key],
          presence=presence, date_start=start, date_end=end or start, date_precision=prec)

def numbers(span, src=S_WEB, event_key=None, event_mention=None, scope="event", note=None, conf=0.9, **n):
    claim("unit_numbers", "claim_unit_numbers", span, conf, src=src, note=note,
          unit_mention=M24, unit_id=U24, event_mention=event_mention,
          event_id=E[event_key] if event_key else None, scope=scope, **n)

def fought(event_key, mention, start, end, prec="day", place_key=None, **losses):
    claim("participated", "claim_participated", f"{mention} {start}..{end}",
          unit_mention=M24, unit_id=U24, event_mention=mention, event_id=E[event_key],
          date_start=start, date_end=end, date_precision=prec)
    if losses:
        numbers(f"{mention}: losses", event_key=event_key, event_mention=mention, **losses)
    if place_key:
        claim("event_at", "claim_event_at", f"{mention} at {place_key}", src=S_MANUAL,
              event_mention=mention, event_id=E[event_key], place_mention=place_key,
              place_id=P[place_key], date_start=start, date_end=end, date_precision=prec)

def attached(mention, start, prec, parent_id, status="accepted", note=None):
    claim("subordinate_to", "claim_subordinate_to", f"Attached to {mention}", status=status, note=note,
          unit_mention=M24, unit_id=U24, parent_mention=mention, parent_unit_id=parent_id,
          date_start=start, date_end=None, date_precision=prec)

# Names
for name, ntype in [("24th Michigan Infantry", "standard"), ("24th Mich. Inf.", "abbreviation"),
                    ("Detroit and Wayne County Regiment", "nickname")]:
    claim("known_as", "claim_known_as", name, entity_type="unit", entity_id=U24, name=name, name_type=ntype)
for key, name, ntype in [("overland", "Campaign from the Rapidan to the James River", "alias"),
                         ("weldon", "Weldon Railroad", "union"),
                         ("boydton", "Hatcher's Run", "alias"),
                         ("boydton", "Burgess Mill", "alias")]:
    claim("known_as", "claim_known_as", name, entity_type="event", entity_id=E[key], name=name, name_type=ntype)

# Command
claim("commanded", "claim_commanded", "Col. Henry A. Morrow", person_mention="Col. Henry A. Morrow",
      person_id=MORROW, unit_mention=M24, unit_id=U24, date_start="1862-08-15", date_precision="day")
claim("commanded", "claim_commanded", "Capt. Albert M. Edwards assumes command", person_mention="Capt. Albert M. Edwards",
      person_id=EDWARDS, unit_mention=M24, unit_id=U24, date_start="1863-07-01", date_precision="day")

# Hierarchy (open-ended: each attachment lasts until the next one)
DEFW = ins("unit", side_id=USA, echelon="department", display_name="Defenses of Washington")
attached("Defences of Washington", "1862-08-29", "day", DEFW)
attached("1st Brigade, 1st Division, 1st Corps, Army of the Potomac", "1862-10-01", "month", IRON,
         note="Iron Brigade was numbered 4th Brigade at this date in other sources; numbering conflict")
attached("4th Brigade, 1st Division, 1st Corps", "1862-11-01", "month", IRON)
attached("1st Brigade, 1st Division, 1st Corps", "1863-06-01", "month", IRON)
attached("1st Brigade, 4th Division, 5th Corps", "1864-03-01", "month", IRON)
attached("3rd Brigade, 3rd Division, 5th Corps", "1864-08-01", "month", None, status="pending",
         note="Reorganization; which canonical brigade?")
attached("1st Brigade, 3rd Division, 5th Corps", "1864-09-01", "month", None, status="pending",
         note="Reorganization; which canonical brigade?")

# Movements and stations
at("detroit", "Detroit", "1862-08-15", span="Organized at Detroit, mustered in")
at("washington", "Washington, D.C.", "1862-08-29", presence="arrived")
at("frederick", "Frederick, Md.", "1862-10-01", presence="arrived")
at("sharpsburg", "Sharpsburg, Md.", "1862-10-06", presence="arrived")
at("warrenton", "Warrenton, Va.", "1862-10-20", "1862-11-06", presence="en_route")
at("rfp_rr", "Richmond, Fredericksburg & Aquia Creek Railroad", "1862-11-25", "1862-12-06", presence="along")
at("falmouth", "Falmouth", "1862-12-06", "1862-12-11", presence="en_route")
at("manassas_gap", "Manassas Gap, Va.", "1863-07-05", "1863-07-24", presence="en_route",
   span="Pursuit of Lee to Manassas Gap")
at("springfield", "Springfield, Ill.", "1865-04-01", "1865-04-30", prec="month",
   span="Detached to Springfield, Ill.; escort at Lincoln funeral", conf=0.7)

# Battles and campaigns
fought("fredericksburg", "Battle of Fredericksburg", "1862-12-12", "1862-12-15", place_key="fredericksburg")
fought("mud_march", "Mud March", "1863-01-20", "1863-01-24")
fought("chanc_campaign", "Chancellorsville Campaign", "1863-04-27", "1863-05-06")
fought("fitzhugh", "Fitzhugh's Crossing", "1863-04-29", "1863-04-30", place_key="fitzhugh")
fought("chancellorsville", "Battle of Chancellorsville", "1863-05-02", "1863-05-05", place_key="chancellorsville")
fought("gb_campaign", "Gettysburg Campaign", "1863-06-11", "1863-07-24")
fought("gettysburg", "Battle of Gettysburg", "1863-07-01", "1863-07-03", place_key="gettysburg",
       casualties_total=363)
fought("bristoe", "Bristoe Campaign", "1863-10-09", "1863-10-22")
fought("haymarket", "Haymarket", "1863-10-19", "1863-10-19", place_key="haymarket")
fought("mine_run", "Mine Run Campaign", "1863-11-26", "1863-12-02", place_key="mine_run")
fought("overland", "Campaign from the Rapidan to the James River", "1864-05-04", "1864-06-15")
fought("wilderness", "Battle of the Wilderness", "1864-05-05", "1864-05-07", place_key="wilderness")
fought("spotsylvania", "Spotsylvania Court House", "1864-05-08", "1864-05-21", place_key="spotsylvania")
fought("north_anna", "North Anna River (Jericho Mills)", "1864-05-23", "1864-05-26", place_key="jericho_mills")
fought("totopotomoy", "Totopotomoy", "1864-05-28", "1864-05-31", place_key="totopotomoy")
fought("cold_harbor", "Cold Harbor", "1864-06-01", "1864-06-12", place_key="cold_harbor")
fought("petersburg", "Siege of Petersburg", "1864-06-16", "1865-04-02", place_key="petersburg")
fought("weldon", "Weldon Railroad", "1864-08-18", "1864-08-21", place_key="globe_tavern")
fought("boydton", "Boydton Plank Road, Hatcher's Run", "1864-10-27", "1864-10-28", place_key="burgess_mill")
fought("lincoln_funeral", "Escort at funeral of President Lincoln", "1865-04-01", "1865-05-31", prec="month")

# Whole-war losses (Dyer): now storable as a unit_numbers claim
numbers("Regiment lost during service 12 Officers and 177 Enlisted men killed and mortally wounded "
        "and 3 Officers and 136 Enlisted men by disease", src=S_DYER, scope="whole_service",
        killed=189, died_disease=139)

con.commit()

# --- derived track: every dated, located point for the unit, in order ---------
TRACK_SQL = """
SELECT d0, d1, place, lat, lon, what FROM (
  SELECT a.date_start d0, a.date_end d1, p.display_name place, p.lat, p.lon,
         a.presence || ': ' || a.place_mention what
  FROM claim_unit_at a JOIN claim c ON c.id = a.claim_id
  JOIN place p ON p.id = a.place_id
  WHERE a.unit_id = :u AND c.status = 'accepted' AND a.portion = 'whole'
  UNION ALL
  SELECT pa.date_start, pa.date_end, p.display_name, p.lat, p.lon,
         e.kind || ': ' || e.display_name
  FROM claim_participated pa JOIN claim c ON c.id = pa.claim_id
  JOIN event e ON e.id = pa.event_id
  JOIN claim_event_at ea ON ea.event_id = e.id
  JOIN claim c2 ON c2.id = ea.claim_id AND c2.status = 'accepted'
  JOIN place p ON p.id = ea.place_id
  WHERE pa.unit_id = :u AND c.status = 'accepted' AND e.kind <> 'campaign' AND pa.portion = 'whole'
) ORDER BY d0
"""

print("24th Michigan Infantry: derived track\n")
print(f"{'start':<11} {'end':<11} {'lat':>7} {'lon':>8}  what")
for d0, d1, place_name, lat, lon, what in con.execute(TRACK_SQL, {"u": U24}):
    print(f"{d0:<11} {d1 or '':<11} {lat:7.3f} {lon:8.3f}  {what}")

print("\nClaims by type and status:")
for row in con.execute("SELECT claim_type, status, COUNT(*) FROM claim GROUP BY 1, 2 ORDER BY 1, 2"):
    print(f"  {row[0]:<15} {row[1]:<9} {row[2]}")

print("\nReview queue:")
for row in con.execute("""SELECT c.id, c.claim_type, c.source_span, c.review_note FROM claim c
                          WHERE c.status = 'pending' OR c.review_note IS NOT NULL"""):
    print(f"  #{row[0]} {row[1]}: {row[2]!r} -> {row[3]}")

print("\nIron Brigade hierarchy for the 24th, by date:")
for row in con.execute("""SELECT s.date_start, s.parent_mention, u.display_name FROM claim_subordinate_to s
                          LEFT JOIN unit u ON u.id = s.parent_unit_id ORDER BY s.date_start"""):
    print(f"  from {row[0]}: {row[1]:<58} -> {row[2] or '(unresolved)'}")
con.close()
