"""Second schema test: 21st Ohio Infantry (3-months 1861 and 3-years 1861-65).

Run after load_sample.py; adds to sample.db and prints the 21st Ohio's track
and every place the schema strained (claims with review notes).

Claims converted by hand from Dyer's Compendium entries as transcribed on
generalstaff.org, plus the Chickamauga monument inscription. Coordinates are
approximate representative points entered by hand.
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


USA = con.execute("SELECT id FROM side WHERE name = 'United States'").fetchone()[0]

S_DYER = ins("source", title="Dyer's Compendium, Ohio infantry (generalstaff.org transcription)",
             kind="compendium", url="https://generalstaff.org/WFA/Dyers/OH_Inf_US.htm",
             fetched_at=NOW, public_domain=1)
S_MARKER = ins("source", title="21st Ohio Infantry monument, Chickamauga", kind="website",
               url="https://www.historicalmarkerproject.com/markers/HMD5Z_21st-ohio-infantry_Chickamauga-GA.html",
               fetched_at=NOW)
S_MANUAL = ins("source", title="Hand-entered coordinates, 21st Ohio test", kind="manual")

# --- units --------------------------------------------------------------------
OH3M = ins("unit", side_id=USA, echelon="regiment", branch="infantry", state="OH", number=21,
           display_name="21st Ohio Infantry (3 months)")
OH21 = ins("unit", side_id=USA, echelon="regiment", branch="infantry", state="OH", number=21,
           display_name="21st Ohio Infantry")

B = {}
def brigade(key, name, notes=None):
    B[key] = ins("unit", side_id=USA, echelon="brigade", branch="infantry", display_name=name, notes=notes)

brigade("kanawha", "Kanawha Brigade (Cox)")
brigade("ao_9", "9th Brigade, Army of the Ohio")
brigade("ao_7ind", "7th Independent Brigade, Army of the Ohio")
brigade("xiv_3_2", "3rd Brigade, 2nd Division, XIV Corps", "Called Sirwell's Brigade, Negley's Division at Chickamauga")
brigade("xiv_3_1", "3rd Brigade, 1st Division, XIV Corps")
brigade("xiv_1_1", "1st Brigade, 1st Division, XIV Corps")

STOUGHTON = ins("person", display_name="Dwella M. Stoughton", side_id=USA)

# --- places -------------------------------------------------------------------
P = {}
def place(key, name, kind, state, lat, lon, prec, geom=None):
    P[key] = ins("place", display_name=name, kind=kind, state=state, lat=lat, lon=lon,
                 precision_m=prec, geometry_json=geom)

place("cleveland_oh", "Camp Taylor, Cleveland", "camp", "OH", 41.499, -81.694, 5000)
place("cleveland_tn", "Cleveland", "town", "TN", 35.159, -84.877, 3000)
place("gallipolis", "Gallipolis", "town", "OH", 38.810, -82.202, 2000)
place("scary_creek", "Scary Creek", "river", "WV", 38.38, -81.83, 3000)
place("findlay", "Findlay (Camp Vance)", "camp", "OH", 41.044, -83.650, 3000)
place("nicholasville", "Nicholasville", "town", "KY", 37.881, -84.573, 2000)
place("ivy_mountain", "Ivy Mountain", "other", "KY", 37.62, -82.62, 5000)
place("bacon_creek", "Bacon Creek", "river", "KY", 37.37, -85.90, 5000)
place("nashville", "Nashville", "town", "TN", 36.162, -86.781, 3000)
place("huntsville", "Huntsville", "town", "AL", 34.730, -86.586, 2000)
place("athens", "Athens", "town", "AL", 34.803, -86.972, 2000)
place("wa_rr", "Western & Atlantic Railroad", "railroad", "GA", 34.4, -84.9, 40000,
      '{"type":"LineString","coordinates":[[-84.39,33.75],[-84.62,34.02],[-84.95,34.77],[-85.31,35.05]]}')
place("stones_river", "Stones River (Murfreesboro)", "battlefield", "TN", 35.876, -86.432, 2000)
place("murfreesboro", "Murfreesboro", "town", "TN", 35.846, -86.392, 2000)
place("chickamauga", "Chickamauga battlefield", "battlefield", "GA", 34.92, -85.26, 3000)
place("chattanooga", "Chattanooga", "town", "TN", 35.046, -85.309, 3000)
place("missionary_ridge", "Missionary Ridge", "other", "TN", 35.02, -85.26, 3000)
place("resaca", "Resaca", "town", "GA", 34.58, -84.94, 2000)
place("kennesaw", "Kennesaw Mountain", "other", "GA", 33.98, -84.58, 2000)
place("peachtree", "Peachtree Creek", "river", "GA", 33.81, -84.40, 2000)
place("atlanta", "Atlanta", "town", "GA", 33.749, -84.388, 3000)
place("savannah", "Savannah", "town", "GA", 32.081, -81.091, 3000)
place("averasboro", "Averasboro", "crossroads", "NC", 35.31, -78.67, 3000)
place("bentonville", "Bentonville", "crossroads", "NC", 35.30, -78.32, 2000)
place("raleigh", "Raleigh", "town", "NC", 35.780, -78.639, 3000)
place("washington", "Washington", "town", "DC", 38.895, -77.036, 5000)
place("louisville", "Louisville", "town", "KY", 38.253, -85.759, 3000)

# --- events (reuse none from the first sample; all western) -----------------
E = {}
def event(key, kind, name, parent=None):
    E[key] = ins("event", kind=kind, display_name=name, parent_event_id=E.get(parent))

event("scary_creek", "engagement", "Battle of Scary Creek")
event("ivy_mountain", "engagement", "Battle of Ivy Mountain")
event("andrews_raid", "expedition", "Andrews' Raid (Great Locomotive Chase)")
event("stones_river", "battle", "Battle of Stones River")
event("tullahoma", "campaign", "Tullahoma Campaign")
event("chick_campaign", "campaign", "Chickamauga Campaign")
event("chickamauga", "battle", "Battle of Chickamauga", "chick_campaign")
event("chatt_campaign", "campaign", "Chattanooga Campaign")
event("missionary_ridge", "battle", "Battle of Missionary Ridge", "chatt_campaign")
event("atlanta_campaign", "campaign", "Atlanta Campaign")
event("resaca", "battle", "Battle of Resaca", "atlanta_campaign")
event("kennesaw", "battle", "Battle of Kennesaw Mountain", "atlanta_campaign")
event("peachtree", "battle", "Battle of Peachtree Creek", "atlanta_campaign")
event("siege_atlanta", "siege", "Siege of Atlanta", "atlanta_campaign")
event("march_sea", "campaign", "Sherman's March to the Sea")
event("siege_savannah", "siege", "Siege of Savannah", "march_sea")
event("carolinas", "campaign", "Carolinas Campaign")
event("averasboro", "battle", "Battle of Averasboro", "carolinas")
event("bentonville", "battle", "Battle of Bentonville", "carolinas")
event("grand_review", "political", "Grand Review of the Armies")

# --- claim helpers --------------------------------------------------------------
def claim(ctype, table, span, conf=0.9, status="accepted", src=S_DYER, note=None, **detail):
    cid = ins("claim", claim_type=ctype, source_id=src, source_span=span, confidence=conf,
              extracted_by="manual", extracted_at=NOW, status=status, review_note=note)
    ins(table, claim_id=cid, **detail)

def at(unit_id, mention, place_key, start, end=None, prec="day", presence="present",
       conf=0.9, status="accepted", note=None, portion="whole", portion_detail=None):
    claim("unit_at", "claim_unit_at", f"{mention} {start}", conf, status, note=note,
          unit_mention="21st Ohio", unit_id=unit_id, place_mention=mention,
          place_id=P[place_key] if place_key else None, presence=presence,
          portion=portion, portion_detail=portion_detail,
          date_start=start, date_end=end or start, date_precision=prec)

def fought(unit_id, event_key, mention, start, end, place_key=None, prec="day", note=None, conf=0.9,
           portion="whole", portion_detail=None):
    claim("participated", "claim_participated", f"{mention} {start}..{end}", conf, note=note,
          unit_mention="21st Ohio", unit_id=unit_id, event_mention=mention, event_id=E[event_key],
          portion=portion, portion_detail=portion_detail,
          date_start=start, date_end=end, date_precision=prec)
    if place_key:
        claim("event_at", "claim_event_at", f"{mention} at {place_key}", src=S_MANUAL,
              event_mention=mention, event_id=E[event_key], place_mention=place_key,
              place_id=P[place_key], date_start=start, date_end=end, date_precision=prec)

def attached(mention, end, parent_key, start=None):
    # Dyer gives END dates ("to July, 1862"); start = previous end, filled by the parser
    claim("subordinate_to", "claim_subordinate_to", f"Attached to {mention}, to {end}",
          unit_mention="21st Ohio", unit_id=OH21, parent_mention=mention, parent_unit_id=B[parent_key],
          date_start=start, date_end=end, date_precision="month")

def name(entity_type, entity_id, text, ntype, src=S_DYER):
    claim("known_as", "claim_known_as", text, src=src, entity_type=entity_type,
          entity_id=entity_id, name=text, name_type=ntype)

# --- 3-months regiment -------------------------------------------------------------
at(OH3M, "Camp Taylor, Cleveland, Tenn.", None, "1861-04-27", status="pending", conf=0.3,
   note="Dyer prints 'Cleveland, Tenn.'; an Ohio regiment in April 1861 must be Cleveland, Ohio. "
        "Place left unresolved for review; candidates: cleveland_oh (likely), cleveland_tn")
at(OH3M, "Gallipolis, Ohio", "gallipolis", "1861-05-23", "1861-07-06", presence="present")
fought(OH3M, "scary_creek", "Scary Creek", "1861-07-17", "1861-07-17", "scary_creek")
claim("succeeded_by", "claim_succeeded_by", "Mustered out Aug 12, 1861; reorganized for three years at Findlay",
      unit_mention="21st Ohio (3 months)", unit_id=OH3M, successor_mention="21st Ohio (3 years)",
      successor_unit_id=OH21, kind="reorganized", succession_date="1861-09-19", date_precision="day")

# --- 3-years regiment --------------------------------------------------------------
name("unit", OH21, "21st Ohio Infantry", "standard")
name("unit", OH21, "21st Ohio Volunteer Infantry", "alias")
name("unit", B["xiv_3_2"], "Sirwell's Brigade", "nickname", src=S_MARKER)
name("unit", B["xiv_3_2"], "3rd Brigade, 2nd Division, Center 14th Army Corps", "official")
name("event", E["stones_river"], "Stone's River", "alias")
name("event", E["stones_river"], "Murfreesboro", "confederate")
name("event", E["missionary_ridge"], "Mission Ridge", "alias")
name("event", E["kennesaw"], "Kenesaw", "alias")
name("event", E["andrews_raid"], "Pittinger's Raid on Georgia State Railroad", "alias")

B["thomas"] = ins("unit", side_id=USA, echelon="department", display_name="Thomas' Command, Army of the Ohio")
attached("Thomas' Command, Army of the Ohio", "1861-11", "thomas")
attached("9th Brigade, Army of the Ohio", "1861-12", "ao_9")
attached("9th Brigade, 3rd Division, Army of the Ohio", "1862-07", "ao_9")
attached("7th Independent Brigade, Army of the Ohio", "1862-09", "ao_7ind")
attached("3rd Brigade, 2nd Division, Center 14th Army Corps, Army of the Cumberland", "1863-01", "xiv_3_2")
attached("3rd Brigade, 2nd Division, 14th Army Corps", "1863-10", "xiv_3_2")
attached("3rd Brigade, 1st Division, 14th Army Corps", "1865-06", "xiv_3_1")
attached("1st Brigade, 1st Division, 14th Army Corps", "1865-07", "xiv_1_1")

claim("commanded", "claim_commanded", "Lt. Col. Dwella M. Stoughton commanding", src=S_MARKER,
      person_mention="Lt. Col. Dwella M. Stoughton", person_id=STOUGHTON, unit_mention="21st Ohio",
      unit_id=OH21, date_start="1863-09-19", date_end="1863-09-20", date_precision="day")

at(OH21, "Findlay, Ohio", "findlay", "1861-09-19")
at(OH21, "Nicholasville, Ky.", "nicholasville", "1861-10-02", presence="departed",
   note="Dyer: 'Left State for Nicholasville' — the date is departure from Ohio, not arrival")
fought(OH21, "ivy_mountain", "Ivy's Mountain, Ky.", "1861-11-08", "1861-11-08", "ivy_mountain")
at(OH21, "Bacon Creek and Green River, Ky.", "bacon_creek", "1861-12-01", "1862-02-10", prec="month",
   note="Duty along a stretch of two rivers; one representative point")
at(OH21, "Nashville", "nashville", "1862-02-25", "1862-03-17")
at(OH21, "Huntsville, Ala.", "huntsville", "1862-04-11", presence="arrived")
fought(OH21, "andrews_raid", "Pittinger's Raid on Georgia State Railroad", "1862-04-07", "1862-04-12",
       "wa_rr", portion="detachment", portion_detail="Volunteers from several companies")
at(OH21, "Athens, Ala.", "athens", "1862-05-28", "1862-08-28")
at(OH21, "Nashville (siege)", "nashville", "1862-09-12", "1862-11-07")
fought(OH21, "stones_river", "Stone's River", "1862-12-30", "1863-01-03", "stones_river")
at(OH21, "Murfreesboro", "murfreesboro", "1863-01-04", "1863-06-23", prec="month")
fought(OH21, "tullahoma", "Tullahoma (Middle Tennessee) Campaign", "1863-06-23", "1863-07-07")
fought(OH21, "chick_campaign", "Chickamauga Campaign", "1863-08-16", "1863-09-22")
fought(OH21, "chickamauga", "Chickamauga", "1863-09-19", "1863-09-21", "chickamauga")
at(OH21, "Chattanooga (siege)", "chattanooga", "1863-09-24", "1863-11-23")
fought(OH21, "missionary_ridge", "Mission Ridge", "1863-11-25", "1863-11-25", "missionary_ridge")
place("ohio", "Ohio (veteran furlough)", "region", "OH", 40.4, -82.9, 150000)
place("dalton", "Rocky Face Ridge, near Dalton", "other", "GA", 34.80, -84.99, 5000)
at(OH21, "Veterans on furlough, Ohio", "ohio", "1864-01-01", "1864-03-31", prec="month", conf=0.6,
   portion="veterans", portion_detail="Reenlisted veterans on veteran furlough")
at(OH21, "Reconnaissance to Dalton, Ga. (non-veterans)", "dalton", "1864-02-22", "1864-02-27",
   portion="non_veterans")
fought(OH21, "atlanta_campaign", "Atlanta Campaign", "1864-05-01", "1864-09-08")
fought(OH21, "resaca", "Resaca", "1864-05-14", "1864-05-15", "resaca")
fought(OH21, "kennesaw", "Assault on Kenesaw", "1864-06-27", "1864-06-27", "kennesaw")
fought(OH21, "peachtree", "Peach Tree Creek", "1864-07-19", "1864-07-20", "peachtree")
fought(OH21, "siege_atlanta", "Siege of Atlanta", "1864-07-22", "1864-08-25", "atlanta")
claim("participated", "claim_participated", "Operations against Hood ... April 29 to November 3",
      conf=0.2, status="pending",
      note="Source date impossible (April precedes the Atlanta Campaign it follows); likely September 29. "
           "Needs a date-sanity check in the pipeline",
      unit_mention="21st Ohio", unit_id=OH21, event_mention="Operations against Hood in North Georgia",
      event_id=None, date_start="1864-04-29", date_end="1864-11-03", date_precision="day")
fought(OH21, "march_sea", "March to the sea", "1864-11-15", "1864-12-10")
fought(OH21, "siege_savannah", "Siege of Savannah", "1864-12-10", "1864-12-21", "savannah")
fought(OH21, "carolinas", "Campaign of the Carolinas", "1865-01-01", "1865-04-26", prec="month")
fought(OH21, "averasboro", "Taylor's Hole Creek, Averysboro, N.C.", "1865-03-16", "1865-03-16", "averasboro")
fought(OH21, "bentonville", "Bentonville, N.C.", "1865-03-19", "1865-03-21", "bentonville")
at(OH21, "Raleigh", "raleigh", "1865-04-14", presence="arrived")
fought(OH21, "grand_review", "Grand Review", "1865-05-24", "1865-05-24", "washington")
at(OH21, "Louisville, Ky.", "louisville", "1865-06-01", "1865-07-25", prec="month")

claim("unit_numbers", "claim_unit_numbers",
      "Regiment lost during service 6 Officers and 166 Enlisted men killed and mortally wounded "
      "and 2 Officers and 218 Enlisted men by disease. Total 392",
      unit_mention="21st Ohio", unit_id=OH21, scope="whole_service", killed=172, died_disease=220,
      casualties_total=392)

con.commit()

# --- report ---------------------------------------------------------------------
TRACK_SQL = (HERE / "load_sample.py").read_text().split('TRACK_SQL = """')[1].split('"""')[0]
print("21st Ohio Infantry (3 years): derived track\n")
print(f"{'start':<11} {'end':<11} {'lat':>7} {'lon':>8}  what")
for d0, d1, _, lat, lon, what in con.execute(TRACK_SQL, {"u": OH21}):
    print(f"{d0:<11} {d1 or '':<11} {lat:7.3f} {lon:8.3f}  {what}")

print("\nWhere the schema strained (21st Ohio claims with review notes):")
for cid, ctype, status, note in con.execute(
        "SELECT id, claim_type, status, review_note FROM claim WHERE source_id IN (?,?,?) "
        "AND review_note IS NOT NULL", (S_DYER, S_MARKER, S_MANUAL)):
    print(f"  #{cid} {ctype} [{status}]\n      {note}")
print("\nParts of the unit away from the main track:")
for row in con.execute("""SELECT a.portion, a.place_mention, a.date_start FROM claim_unit_at a
                          WHERE a.unit_id = ? AND a.portion <> 'whole'
                          UNION ALL SELECT pa.portion, pa.event_mention, pa.date_start FROM claim_participated pa
                          WHERE pa.unit_id = ? AND pa.portion <> 'whole' ORDER BY 3""", (OH21, OH21)):
    print(f"  {row[2]}  [{row[0]}] {row[1]}")
print("\nSuccession:")
for row in con.execute("""SELECT a.display_name, s.kind, b.display_name, s.succession_date FROM claim_succeeded_by s
                          JOIN unit a ON a.id = s.unit_id JOIN unit b ON b.id = s.successor_unit_id"""):
    print(f"  {row[0]} --{row[1]}--> {row[2]} ({row[3]})")
con.close()
