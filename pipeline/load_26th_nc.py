"""Third schema test: 26th North Carolina Infantry (Confederate), 1861-1865.

Run after load_sample.py (and optionally load_21st_ohio.py). Reuses the
eastern battles already loaded for the 24th Michigan, so the two regiments
share events. Prints the 26th's track, its command chain at Gettysburg, who
was in the fight at Herbst (McPherson's) Woods, a nested-loss check, the
"Hatcher's Run" name collision, and every claim that strained the schema.

Claims converted by hand from the regiment's dated timeline on
civilwarintheeast.com (a modern compilation, not public domain).
Coordinates are approximate representative points entered by hand.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
NOW = datetime.now().isoformat(timespec="seconds")
con = sqlite3.connect(HERE / "sample.db")
con.execute("PRAGMA foreign_keys = ON")


def ins(table, **cols):
    keys, marks = ", ".join(cols), ", ".join("?" for _ in cols)
    return con.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", tuple(cols.values())).lastrowid

def one(sql, *args):
    return con.execute(sql, args).fetchone()[0]


CSA = one("SELECT id FROM side WHERE name = 'Confederate States'")
U24 = one("SELECT id FROM unit WHERE display_name = '24th Michigan Infantry'")

S = ins("source", title="26th North Carolina Infantry Regiment timeline", kind="website",
        url="https://civilwarintheeast.com/confederate-regiments/north-carolina/26th-north-carolina-infantry-regiment/",
        fetched_at=NOW, notes="Modern compilation from regimental histories; not public domain")
S_MANUAL = ins("source", title="Hand-entered coordinates, 26th NC test", kind="manual")

# --- units: regiment, brigades named for commanders, departments, and a full chain
NC26 = ins("unit", side_id=CSA, echelon="regiment", branch="infantry", state="NC", number=26,
           display_name="26th North Carolina Infantry")
U = {}
def unit(key, echelon, name, notes=None):
    U[key] = ins("unit", side_id=CSA, echelon=echelon, branch="infantry" if echelon == "brigade" else "mixed",
                 display_name=name, notes=notes)

unit("dept_nc", "department", "Department of North Carolina")
unit("dist_pamlico", "department", "District of Pamlico")
unit("ransom", "brigade", "French's / Ransom's Brigade", "Named for successive commanders")
unit("pettigrew", "brigade", "Pettigrew's Brigade", "Later known by other commanders' names; not in this source")
unit("heth", "division", "Heth's Division")
unit("third_corps", "corps", "Third Corps, Army of Northern Virginia")
unit("anv", "army", "Army of Northern Virginia")

PERSON = {}
for key, nm in [("vance", "Zebulon B. Vance"), ("burgwyn", "Henry K. Burgwyn Jr."), ("lane", "John R. Lane"),
                ("jones", "John T. Jones"), ("adams", "James T. Adams"), ("cureton", "Thomas J. Cureton")]:
    PERSON[key] = ins("person", display_name=nm, side_id=CSA)

# --- places: reuse existing ones by name, add new ------------------------------------
P = {}
def place(key, name, kind, state, lat, lon, prec):
    P[key] = ins("place", display_name=name, kind=kind, state=state, lat=lat, lon=lon, precision_m=prec)
def existing_place(key, name):
    P[key] = one("SELECT id FROM place WHERE display_name = ?", name)

for key, nm in [("gettysburg", "Gettysburg"), ("wilderness", "The Wilderness"),
                ("spotsylvania", "Spotsylvania Court House"), ("jericho_mills", "Jericho Mills"),
                ("cold_harbor", "Cold Harbor"), ("petersburg", "Petersburg"),
                ("globe_tavern", "Globe Tavern"), ("burgess_mill", "Burgess Mill"), ("mine_run", "Mine Run")]:
    existing_place(key, nm)

place("crabtree", "Camp Crabtree, near Raleigh", "camp", "NC", 35.82, -78.70, 4000)
place("fort_macon", "Fort Macon", "fort", "NC", 34.698, -76.678, 500)
place("carolina_city", "Between Morehead City and Carolina City", "camp", "NC", 34.72, -76.75, 4000)
place("new_bern", "New Bern", "town", "NC", 35.108, -77.044, 3000)
place("oak_grove", "King's School House", "crossroads", "VA", 37.53, -77.31, 2000)
place("malvern_hill", "Malvern Hill", "battlefield", "VA", 37.41, -77.25, 2000)
place("blounts_creek", "Blount's Creek", "river", "NC", 35.42, -77.08, 4000)
place("richmond", "Richmond", "town", "VA", 37.541, -77.436, 4000)
place("herbst_woods", "Herbst Woods", "battlefield", "PA", 39.835, -77.248, 300)
place("cemetery_ridge", "Cemetery Ridge (the stone wall)", "battlefield", "PA", 39.812, -77.235, 300)
place("falling_waters", "Falling Waters", "town", "WV", 39.58, -77.89, 3000)
place("bristoe", "Bristoe Station", "town", "VA", 38.72, -77.54, 2000)
place("reams", "Reams Station", "crossroads", "VA", 37.10, -77.41, 2000)
place("peebles", "Peebles' Farm", "battlefield", "VA", 37.18, -77.47, 2000)
place("hatchers_run", "Hatcher's Run (Dabney's Mill)", "battlefield", "VA", 37.14, -77.48, 2000)
place("fort_stedman", "Fort Stedman", "fort", "VA", 37.235, -77.367, 500)
place("five_forks", "Five Forks", "crossroads", "VA", 37.14, -77.62, 1500)
place("amelia", "Amelia Court House", "town", "VA", 37.34, -77.98, 2000)
place("appomattox", "Appomattox Court House", "town", "VA", 37.377, -78.796, 1500)

# --- events: reuse the 24th Michigan's battles where they are the same event --------
E = {}
def existing_event(key, name):
    E[key] = one("SELECT id FROM event WHERE display_name = ?", name)
def event(key, kind, name, parent=None):
    E[key] = ins("event", kind=kind, display_name=name, parent_event_id=E.get(parent))

for key, nm in [("gb_campaign", "Gettysburg Campaign"), ("gettysburg", "Battle of Gettysburg"),
                ("bristoe_campaign", "Bristoe Campaign"), ("mine_run", "Mine Run Campaign"),
                ("overland", "Overland Campaign"), ("wilderness", "Battle of the Wilderness"),
                ("spotsylvania", "Battle of Spotsylvania Court House"), ("north_anna", "Battle of North Anna"),
                ("cold_harbor", "Battle of Cold Harbor"), ("petersburg", "Siege of Petersburg"),
                ("globe_tavern", "Battle of Globe Tavern"), ("boydton", "Battle of Boydton Plank Road")]:
    existing_event(key, nm)

event("new_bern", "battle", "Battle of New Bern")
event("seven_days", "campaign", "Seven Days Battles")
event("oak_grove", "battle", "Battle of Oak Grove", "seven_days")
event("malvern_hill", "battle", "Battle of Malvern Hill", "seven_days")
event("nb_wash", "campaign", "New Bern and Washington Campaign")
event("blounts_creek", "engagement", "Blount's Creek", "nb_wash")
event("herbst_woods", "engagement", "Fight at Herbst Woods (July 1)", "gettysburg")
event("picketts_charge", "engagement", "Pickett's Charge (July 3)", "gettysburg")
event("falling_waters", "engagement", "Falling Waters", "gb_campaign")
event("bristoe_station", "battle", "Battle of Bristoe Station", "bristoe_campaign")
event("reams", "battle", "Second Battle of Reams Station", "petersburg")
event("peebles", "battle", "Battle of Peebles' Farm", "petersburg")
event("hatchers_run", "battle", "Battle of Hatcher's Run", "petersburg")
event("fort_stedman", "battle", "Battle of Fort Stedman", "petersburg")
event("appomattox_campaign", "campaign", "Appomattox Campaign")
event("five_forks", "battle", "Battle of Five Forks", "appomattox_campaign")
event("petersburg_final", "battle", "Third Battle of Petersburg", "appomattox_campaign")
event("appomattox", "political", "Surrender at Appomattox Court House", "appomattox_campaign")

# --- claim helpers ----------------------------------------------------------------
def claim(ctype, table, span, conf=0.9, status="accepted", src=S, note=None, **detail):
    cid = ins("claim", claim_type=ctype, source_id=src, source_span=span, confidence=conf,
              extracted_by="manual", extracted_at=NOW, status=status, review_note=note)
    ins(table, claim_id=cid, **detail)

def at(mention, place_key, start, end=None, prec="day", presence="present", note=None,
       portion="whole", portion_detail=None):
    claim("unit_at", "claim_unit_at", f"{mention} {start}", note=note, unit_mention="26th NC", unit_id=NC26,
          place_mention=mention, place_id=P[place_key], presence=presence,
          portion=portion, portion_detail=portion_detail,
          date_start=start, date_end=end or start, date_precision=prec)

def numbers(span, event_key=None, event_mention=None, scope="event", note=None, conf=0.9,
            unit_id=NC26, unit_mention="26th NC", **n):
    claim("unit_numbers", "claim_unit_numbers", span, conf, note=note, unit_mention=unit_mention,
          unit_id=unit_id, event_mention=event_mention, event_id=E[event_key] if event_key else None,
          scope=scope, **n)

def fought(event_key, mention, start, end, place_key=None, prec="day", note=None, unit_id=NC26,
           unit_mention="26th NC", conf=0.9, portion="whole", portion_detail=None, **n):
    claim("participated", "claim_participated", f"{mention} {start}..{end}", conf, note=note,
          unit_mention=unit_mention, unit_id=unit_id, event_mention=mention, event_id=E[event_key],
          portion=portion, portion_detail=portion_detail,
          date_start=start, date_end=end, date_precision=prec)
    if n:
        numbers(f"{mention}: numbers", event_key=event_key, event_mention=mention,
                unit_id=unit_id, unit_mention=unit_mention, **n)
    if place_key and not con.execute("SELECT 1 FROM claim_event_at WHERE event_id = ?", (E[event_key],)).fetchone():
        claim("event_at", "claim_event_at", f"{mention} at {place_key}", src=S_MANUAL,
              event_mention=mention, event_id=E[event_key], place_mention=place_key,
              place_id=P[place_key], date_start=start, date_end=end, date_precision=prec)

def attached(child_id, child_mention, parent_key, mention, start, end=None, prec="month", note=None):
    claim("subordinate_to", "claim_subordinate_to", f"{child_mention}: {mention}", note=note,
          unit_mention=child_mention, unit_id=child_id, parent_mention=mention, parent_unit_id=U[parent_key],
          date_start=start, date_end=end, date_precision=prec)

def commanded(person_key, mention, unit_id, start, end=None, prec="day", conf=0.9, note=None):
    claim("commanded", "claim_commanded", mention, conf, note=note, person_mention=mention,
          person_id=PERSON[person_key], unit_mention="26th NC", unit_id=unit_id,
          date_start=start, date_end=end, date_precision=prec)

def name(entity_type, entity_id, text, ntype):
    claim("known_as", "claim_known_as", text, entity_type=entity_type, entity_id=entity_id, name=text, name_type=ntype)

# --- names --------------------------------------------------------------------------
name("unit", NC26, "26th North Carolina Infantry", "standard")
name("unit", NC26, "26th Regiment North Carolina Troops", "official")
name("place", P["herbst_woods"], "McPherson's Woods", "alias")
name("event", E["oak_grove"], "King's School House", "confederate")
name("event", E["peebles"], "Jones' Farm", "confederate")
name("event", E["peebles"], "Pegram's Farm", "alias")
name("event", E["peebles"], "Squirrel Level Road", "alias")
name("event", E["boydton"], "Burgess' Mill", "confederate")
name("event", E["hatchers_run"], "Hatcher's Run", "standard")
name("unit", U["dist_pamlico"], "District of Pimlico", "alias")   # source's spelling

# --- hierarchy: one attachment string becomes a chain of immediate-parent claims -----
attached(NC26, "26th NC", "dept_nc", "Department of North Carolina", "1861-09", "1861-12")
attached(NC26, "26th NC", "dist_pamlico", "District of Pamlico, Dept. of N.C.", "1862-01", "1862-03")
attached(U["dist_pamlico"], "District of Pamlico", "dept_nc", "Dept. of N.C.", "1862-01", "1862-06")
attached(NC26, "26th NC", "ransom", "French's-Ransom's Brigade", "1862-03", "1862-09")
attached(NC26, "26th NC", "pettigrew", "Pettigrew's Brigade", "1862-09", None)
attached(U["pettigrew"], "Pettigrew's Brigade", "heth", "Heth's Division", "1863-06", None)
attached(U["heth"], "Heth's Division", "third_corps", "3rd Corps", "1863-06", None)
attached(U["third_corps"], "Third Corps", "anv", "Army of Northern Virginia", "1863-06", None)
claim("subordinate_to", "claim_subordinate_to", "Pettigrew's Brigade, French's Command, Dept. of NC and Southern Va.",
      status="pending", note="Brigade's parent was a shifting regional command ('French's Command', "
      "'D. H. Hill's command', 'Dept. of Richmond'); each needs its own department unit",
      unit_mention="Pettigrew's Brigade", unit_id=U["pettigrew"], parent_mention="French's Command",
      parent_unit_id=None, date_start="1862-09", date_end="1863-02", date_precision="month")

# --- command ---------------------------------------------------------------------
commanded("vance", "Col. Zebulon B. Vance", NC26, "1861-08-27", "1862-09-08")
commanded("burgwyn", "Col. Henry K. Burgwyn", NC26, "1862-09-08", "1863-07-01")
commanded("jones", "Lt. Col. John T. Jones", U["pettigrew"], "1863-07-03", "1863-07-03", conf=0.6,
          note="Source says Jones 'led the brigade' after the July 1 losses; a regimental officer "
               "commanding a brigade temporarily")
commanded("lane", "Col. John R. Lane", NC26, "1863-11", None, prec="month")
commanded("adams", "Maj. James T. Adams", NC26, "1865-03-15", "1865-04-09", prec="month")
commanded("cureton", "Thomas J. Cureton", NC26, "1865-03", "1865-04", prec="month", conf=0.5,
          note="Led the regiment while Adams commanded the brigade: overlapping command periods")

# --- stations ------------------------------------------------------------------------
at("Crabtree, near Raleigh", "crabtree", "1861-08-27")
at("Fort Macon", "fort_macon", "1861-09-02", "1861-11-30", presence="present")
at("Winter quarters, Morehead City-Carolina City", "carolina_city", "1861-12-01", "1862-02-28", prec="month")
at("Richmond", "richmond", "1863-05-01", "1863-06-15", presence="present", prec="day")

# --- battles, with the source's per-event numbers ------------------------------------------
fought("new_bern", "New Bern", "1862-03-14", "1862-03-14", "new_bern", casualties_total=87)
fought("seven_days", "Seven Days", "1862-06-25", "1862-07-01", killed=6, wounded=40)
fought("oak_grove", "King's School House", "1862-06-25", "1862-06-25", "oak_grove", killed=2, wounded=5)
fought("malvern_hill", "Malvern Hill", "1862-07-01", "1862-07-01", "malvern_hill",
       killed=7, wounded=53, missing_captured=1,
       note="Child losses (2+7 killed) exceed the Seven Days total (6 killed): sources disagree or overlap")
fought("nb_wash", "New Bern and Washington Campaign", "1863-03-01", "1863-04-30", prec="month",
       killed=7, wounded=11, missing_captured=71)
fought("blounts_creek", "Blount's Creek", "1863-04-11", "1863-04-11", "blounts_creek")
fought("gb_campaign", "Gettysburg Campaign", "1863-06-15", "1863-07-14")
fought("gettysburg", "Gettysburg", "1863-07-01", "1863-07-03", strength=843,
       killed=172, wounded=443, missing_captured=72, casualties_total=687)
fought("herbst_woods", "Herbst Woods", "1863-07-01", "1863-07-01", "herbst_woods",
       killed=86, wounded=502, casualties_total=588)
fought("herbst_woods", "Herbst Woods (opponent named in 26th NC source)", "1863-07-01", "1863-07-01",
       unit_id=U24, unit_mention="24th Michigan", conf=0.8,
       note="Claim about the 24th Michigan extracted from a 26th NC source; opponents are "
            "recorded by sharing the sub-battle event, not by a separate claim type")
fought("picketts_charge", "Pickett's Charge", "1863-07-03", "1863-07-03", "cemetery_ridge", casualties_total=99)
fought("falling_waters", "Falling Waters", "1863-07-10", "1863-07-10", "falling_waters",
       wounded=2, missing_captured=59,
       note="Source dates this July 10; the action at Falling Waters was July 14. Date conflict for review")
fought("bristoe_campaign", "Bristoe Campaign", "1863-10-09", "1863-11-07", prec="month")
fought("bristoe_station", "Bristoe Station", "1863-10-14", "1863-10-14", "bristoe",
       killed=19, wounded=76, missing_captured=84)
fought("mine_run", "Mine Run Campaign", "1863-11-26", "1863-12-02")
fought("wilderness", "Wilderness", "1864-05-05", "1864-05-06", killed=13, wounded=15, missing_captured=20)
fought("spotsylvania", "Spotsylvania Court House", "1864-05-08", "1864-05-21", killed=6, wounded=15)
at("Detached to gather corn for artillery horses", "spotsylvania", "1864-05-08", "1864-05-21",
   portion="detachment", portion_detail="Detail sent to gather corn")
fought("north_anna", "North Anna", "1864-05-22", "1864-05-26", missing_captured=2)
fought("cold_harbor", "Cold Harbor", "1864-06-01", "1864-06-03", killed=6, wounded=10)
fought("petersburg", "Siege of Petersburg", "1864-06-15", "1865-04-02")
fought("globe_tavern", "Globe Tavern", "1864-08-21", "1864-08-21")
fought("reams", "Reams' Station", "1864-08-25", "1864-08-25", "reams", killed=1, wounded=18)
fought("peebles", "Jones' Farm & Squirrel Level Road", "1864-09-30", "1864-10-02", "peebles")
fought("boydton", "Burgess' Mill", "1864-10-27", "1864-10-27")
fought("hatchers_run", "Hatcher's Run", "1865-02-05", "1865-02-07", "hatchers_run", killed=2, wounded=3)
fought("fort_stedman", "Fort Stedman", "1865-03-25", "1865-03-25", "fort_stedman", missing_captured=6)
fought("five_forks", "Five Forks", "1865-04-01", "1865-04-01", "five_forks", wounded=1, missing_captured=1)
fought("petersburg_final", "Final assault on Petersburg", "1865-04-02", "1865-04-02", "petersburg",
       wounded=2, missing_captured=42)
at("Amelia Court House", "amelia", "1865-04-04")
numbers("Amelia Court House: 9 captured", scope="at_date", date_start="1865-04-04", date_end="1865-04-04",
        date_precision="day", missing_captured=9)
fought("appomattox", "Appomattox Court House", "1865-04-09", "1865-04-09", "appomattox",
       strength=130, wounded=1, note="Surrendered 10 officers and 120 men: strength at surrender")

numbers("May 1864: recruited back to 760 men", scope="at_date", date_start="1864-05-01",
        date_end="1864-05-31", date_precision="month", strength=760)
numbers("274 killed or died of wounds, 332 died of disease, 775 captured, 70 died in captivity",
        scope="whole_service", killed=274, died_disease=332, missing_captured=775, died_captivity=70)
place("city_point", "City Point", "town", "VA", 37.31, -77.28, 2000)
at("Regimental band captured, taken to City Point", "city_point", "1865-04-03",
   portion="detachment", portion_detail="Regimental band")
NOT_STORED = [
    "Apr 21, 1862: reorganized 'for the war' and officers re-elected (same unit continues; no link needed)",
]
con.commit()

# --- report ------------------------------------------------------------------------
TRACK_SQL = (HERE / "load_sample.py").read_text().split('TRACK_SQL = """')[1].split('"""')[0]
print("26th North Carolina Infantry: derived track\n")
print(f"{'start':<11} {'end':<11} {'lat':>7} {'lon':>8}  what")
for d0, d1, _, lat, lon, what in con.execute(TRACK_SQL, {"u": NC26}):
    print(f"{d0:<11} {d1 or '':<11} {lat:7.3f} {lon:8.3f}  {what}")

print("\nCommand chain on 1863-07-01 (immediate-parent claims, followed upward):")
chain = con.execute("""
WITH RECURSIVE up(uid, depth) AS (
  SELECT ?, 0
  UNION ALL
  SELECT s.parent_unit_id, depth + 1 FROM up
  JOIN claim_subordinate_to s ON s.unit_id = up.uid
  JOIN claim c ON c.id = s.claim_id AND c.status = 'accepted'
  WHERE s.parent_unit_id IS NOT NULL
    AND s.date_start <= '1863-07' AND (s.date_end IS NULL OR s.date_end >= '1863-07'))
SELECT u.display_name FROM up JOIN unit u ON u.id = up.uid ORDER BY depth""", (NC26,)).fetchall()
print("  " + "  ->  ".join(r[0] for r in chain))

print("\nUnits recorded at the fight at Herbst Woods (either side):")
for row in con.execute("""SELECT u.display_name, s.name, n.casualties_total, src.title FROM claim_participated p
                          JOIN unit u ON u.id = p.unit_id JOIN side s ON s.id = u.side_id
                          JOIN claim c ON c.id = p.claim_id JOIN source src ON src.id = c.source_id
                          LEFT JOIN claim_unit_numbers n ON n.unit_id = p.unit_id AND n.event_id = p.event_id
                          WHERE p.event_id = ?""", (E["herbst_woods"],)):
    print(f"  {row[0]:<30} {row[1]:<20} casualties {row[2] or '?':<5} (from: {row[3]})")

print("\nNested losses at Gettysburg (parent vs children):")
parent = one("SELECT casualties_total FROM claim_unit_numbers WHERE unit_id=? AND event_id=?", NC26, E["gettysburg"])
kids = one("""SELECT SUM(p.casualties_total) FROM claim_unit_numbers p JOIN event e ON e.id = p.event_id
              WHERE p.unit_id = ? AND e.parent_event_id = ?""", NC26, E["gettysburg"])
print(f"  battle total {parent}; sum of July 1 + July 3 actions {kids}: "
      f"{'consistent' if parent == kids else 'MISMATCH'}; a viewer must not add both levels")

print("\nWhich events are called \"Hatcher's Run\"?")
for row in con.execute("""SELECT e.display_name, MIN(pa.date_start) FROM claim_known_as k
                          JOIN event e ON e.id = k.entity_id AND k.entity_type = 'event'
                          LEFT JOIN claim_participated pa ON pa.event_id = e.id
                          WHERE k.name = 'Hatcher''s Run' GROUP BY e.id"""):
    print(f"  {row[0]} (first dated {row[1]})")

print("\nWhere the schema strained (26th NC claims with review notes):")
for cid, ctype, status, note in con.execute(
        "SELECT id, claim_type, status, review_note FROM claim WHERE source_id IN (?,?) "
        "AND review_note IS NOT NULL", (S, S_MANUAL)):
    print(f"  #{cid} {ctype} [{status}]\n      {note}")
print("\nNumbers not tied to a single event:")
for row in con.execute("""SELECT scope, date_start, strength, killed, died_disease, missing_captured, died_captivity
                          FROM claim_unit_numbers WHERE unit_id = ? AND event_id IS NULL""", (NC26,)):
    print(f"  {row[0]:<14} {row[1] or '':<11} strength={row[2]} killed={row[3]} disease={row[4]} "
          f"captured={row[5]} died_in_captivity={row[6]}")
print("\nNot stored (no claim type):")
for line in NOT_STORED:
    print("  - " + line)
con.close()
