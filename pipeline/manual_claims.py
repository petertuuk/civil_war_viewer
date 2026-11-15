"""Load hand-made or uploaded claims (data/manual/*.json; generated ones in the same format: data/derived/*.json) into the claims database, resolving the entities they
describe against what build_db.py has already loaded.

File format (one JSON object per file):
  {"about": "...",
   "sources": {"<key>": {"title", "kind", "citation"?, "url"?, "public_domain"?, "notes"?}},
   "claims": [{"type": one of the 8 claim types, "source": "<key>", "span": quoted text, "confidence": 0-1,
               "status": "accepted" | "pending" | "rejected", "note"?,
               entities, described rather than keyed:
                 "unit" / "parent" / "successor": {"side", "state" (2-letter), "number", "branch", "echelon",
                                                  "display_name", "dyer_id"?}
                 "event": {"name", "kind"?, "parent"?}     "place": {"display_name", "state"?, "kind"?, "lat"?, "lon"?, ...}
                 "person": {"name", "side"}                "entity": one of the above (known_as, with "entity_type")
               plus the claim table's own columns (unit_mention, event_mention, date_start, date_end, presence, ...)}]}

Resolution (Resolver): units by Dyer's id, else side + state + number + arm (+ term words); other units (brigades,
departments) by exact name, else created; events by distinctive name words with overlapping dates (+-3 days),
else created; places by name + state, else created from the given coordinates; persons by normalized name + side.
Every created entity is noted as created from a manual source. A claim whose key entity could not be resolved is
loaded as 'pending' with a review note instead of being dropped.
"""
import json, re
from datetime import date, timedelta
from pathlib import Path

STOP = {"battle", "battles", "campaign", "siege", "engagement", "action", "skirmish", "the", "near", "from", "with",
        "and", "affair", "operations", "against", "about", "expedition", "of", "at", "on", "to", "in", "first", "second"}
names_raw = {}
TABLE = {"unit_at": "claim_unit_at", "participated": "claim_participated", "subordinate_to": "claim_subordinate_to",
         "commanded": "claim_commanded", "event_at": "claim_event_at", "known_as": "claim_known_as",
         "succeeded_by": "claim_succeeded_by", "unit_numbers": "claim_unit_numbers"}


def words(s):
    return {w for w in re.findall(r"[a-z]{3,}", (s or "").lower().replace("'", "").replace("\u2019", "")) if w not in STOP}


def day(s, end=False):
    s = (s or "")[:10]
    try:
        if len(s) == 4: return date(int(s), 12 if end else 1, 31 if end else 1)
        if len(s) == 7:
            y, m = int(s[:4]), int(s[5:7])
            return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)) if end else date(y, m, 1)
        return date.fromisoformat(s)
    except ValueError:
        return None


class Resolver:
    def __init__(self, cur, side, xref, events, ev_id, person_of, note, reg=None):
        self.cur, self.side, self.xref, self.person_of, self.note = cur, side, xref, person_of, note
        self.reg = reg                                 # unit_registry.Registry: permanent numbers for the units created here
        self.ev = []                                   # (event db id, [name word sets], start, end, regiments, kind)
        global names_raw
        names_raw = {ev_id[e["event_id"]]: [n.lower() for n in (e["name"], e.get("dyer_name")) if n] for e in events}
        for e in events:
            names = [words(n) for n in (e["name"], e.get("dyer_name")) if n]
            self.ev.append((ev_id[e["event_id"]], names, day(e["date_start"]), day(e["date_end"], True) or day(e["date_start"]),
                            e.get("regiments", 0), (e.get("kind") or "").lower()))
        self.made = {"unit": 0, "event": 0, "place": 0}
        self.cache = {}

    # ---- units ----
    def unit(self, u):
        if not u: return None
        key = ("u", json.dumps(u, sort_keys=True))
        if key in self.cache: return self.cache[key]
        r = None
        if u.get("dyer_id"):
            r = self.xref[("unit", "dyer")].get(u["dyer_id"])
        if r is None and u.get("nps_code"):
            r = self.xref[("unit", "nps")].get(u["nps_code"])
        sid = self.side.get(u.get("side"))
        if r is None and u.get("number") and u.get("state"):
            rows = self.cur.execute(
                "SELECT u.id, u.display_name, u.branch, EXISTS(SELECT 1 FROM external_id x WHERE x.entity_type='unit' "
                "AND x.entity_id=u.id AND x.scheme='dyer') FROM unit u WHERE u.state=? AND u.number=? AND (? IS NULL OR u.side_id=?)",
                (u["state"], u["number"], sid, sid)).fetchall()
            br = (u.get("branch") or "").split()[-1:] or [""]
            rows = [x for x in rows if not u.get("branch") or (x[2] or "").endswith(br[0])] or rows
            want3 = bool(re.search(r"3 months|three months|\(3", u.get("display_name", ""), re.I))
            def rank(x):
                n = x[1].lower()
                qual = bool(re.search(r"month|militia|guard|colored|african|veteran|reserve|provisional|enrolled", n))
                return (want3 != bool(re.search(r"month", n)), qual and not want3, not x[3], len(n))
            if rows:
                r = sorted(rows, key=rank)[0][0]
        if r is None and u.get("display_name"):
            x = self.cur.execute("SELECT id FROM unit WHERE lower(display_name)=lower(?) AND (? IS NULL OR side_id=?)",
                                 (u["display_name"], sid, sid)).fetchone()
            if x: r = x[0]
            elif not u.get("number") or u.get("echelon") not in ("regiment", "battalion", "battery", "company"):
                sname = next((k for k, v in self.side.items() if v == sid), "")
                uid_ = self.reg.id_for(f"manual:{sname}|{u.get('echelon') or 'other'}|{u['display_name']}") if self.reg else None
                self.cur.execute("INSERT INTO unit(id, side_id, echelon, branch, state, number, display_name, notes) VALUES (?,?,?,?,?,?,?,?)",
                                 (uid_, sid, u.get("echelon") or "other", u.get("branch"), u.get("state"), u.get("number"),
                                  u["display_name"], self.note))
                r = self.cur.lastrowid; self.made["unit"] += 1
        self.cache[key] = r
        return r

    # ---- events ----
    def event(self, e, d0=None, d1=None):
        if not e: return None
        key = ("e", e["name"], d0, d1)
        if key in self.cache: return self.cache[key]
        import difflib
        w, a, b = words(e["name"]), day(d0), day(d1, True) or day(d0)
        def same(x, y):
            return x == y or (len(x) > 5 and len(y) > 5 and difflib.SequenceMatcher(None, x, y).ratio() >= 0.8)
        def sim(ew):                                 # overlap in both directions, near-spellings allowed
            hit = sum(1 for x in w if any(same(x, y) for y in ew))
            return hit / len(w | ew) if hit else 0, hit / len(w)
        best = None
        for eid, names, s, t, regs, ekind in self.ev:
            if not w: continue
            j, cov = max((sim(ew) for ew in names if ew), default=(0, 0))
            if cov < 0.5: continue
            if a and s and ((a - (t or s)).days > 3 or (s - (b or a)).days > 3): continue
            if not a and cov < 1: continue
            ov = 0.0
            if a and s:                              # date-range overlap (intersection over union)
                lo, hi = max(a, s), min(b or a, t or s)
                ov = max(0, (hi - lo).days + 1) / max(1, (max(b or a, t or s) - min(a, s)).days + 1)
            kind_ok = bool(e.get("kind")) and e["kind"].lower().startswith(ekind[:4]) if ekind else False
            cm = "campaign" if "campaign" in e["name"].lower() else "siege" if "siege" in e["name"].lower() else ""
            em = "campaign" if ekind == "campaign" or any("campaign" in str(x) for x in names_raw.get(eid, ())) else \
                 "siege" if ekind == "siege" or any("siege" in str(x) for x in names_raw.get(eid, ())) else ""
            k = (round(j, 2), cm == em, round(ov, 2), kind_ok, regs)
            if best is None or k > best[0]: best = (k, eid)
        r = best[1] if best else None
        if r is None:
            parent = self.event({"name": e["parent"]}, d0, d1) if e.get("parent") else None
            self.cur.execute("INSERT INTO event(kind, display_name, parent_event_id, notes) VALUES (?,?,?,?)",
                             (e.get("kind") or "other", e["name"], parent, self.note))
            r = self.cur.lastrowid; self.made["event"] += 1
            self.ev.append((r, [w], a, b, 0, (e.get("kind") or "").lower()))
            names_raw[r] = [e["name"].lower()]
        self.cache[key] = r
        return r

    # ---- places ----
    def place(self, p):
        if not p: return None
        key = ("p", p.get("display_name"), p.get("state"))
        if key in self.cache: return self.cache[key]
        x = self.cur.execute("SELECT id FROM place WHERE lower(display_name)=lower(?) AND (state IS ? OR ? IS NULL) "
                             "AND lat IS NOT NULL ORDER BY id LIMIT 1", (p["display_name"], p.get("state"), p.get("state"))).fetchone()
        if x and p.get("lat") is None:
            r = x[0]
        else:                                        # hand coordinates are kept as their own place, not merged in
            self.cur.execute("INSERT INTO place(display_name, kind, state, lat, lon, precision_m, geometry_json, notes) VALUES (?,?,?,?,?,?,?,?)",
                             (p["display_name"], p.get("kind") or "other", p.get("state"), p.get("lat"), p.get("lon"),
                              p.get("precision_m"), p.get("geometry_json"), self.note))
            r = self.cur.lastrowid; self.made["place"] += 1
        self.cache[key] = r
        return r

    def person(self, p):
        return self.person_of(p["name"], p.get("side") or "Union") if p else None


def load(P, cur, side, xref, events, ev_id, person_of, source, claim, n, reg=None):
    """Called from build_db.main after all other claims are in. Returns nothing; counts into n."""
    # hand-made claim files (data/manual) and generated ones in the same format (data/derived), in file-name order
    files = sorted([*(Path(P) / "data/manual").glob("*.json"), *(Path(P) / "data/derived").glob("*.json")], key=lambda f: f.name)
    for f in files:
        doc = json.load(open(f, encoding="utf-8"))
        rel = f"data/{f.parent.name}/{f.name}"
        R = Resolver(cur, side, xref, events, ev_id, person_of, f"created from manual source {rel}", reg)
        src = {k: source(s["title"], s.get("kind") or "manual", s.get("citation"), s.get("url"),
                         int(s.get("public_domain") or 0), s.get("notes")) for k, s in doc["sources"].items()}
        for c in doc["claims"]:
            t = c["type"]; cols, missing = {}, []
            d0, d1 = c.get("date_start"), c.get("date_end")
            for k, v in c.items():
                if k in ("type", "source", "span", "confidence", "status", "note", "extracted_by"): continue
                if k == "unit": cols["unit_id"] = R.unit(v); missing += [] if cols["unit_id"] else ["unit"]
                elif k == "parent": cols["parent_unit_id"] = R.unit(v)
                elif k == "successor": cols["successor_unit_id"] = R.unit(v)
                elif k == "event": cols["event_id"] = R.event(v, d0, d1); missing += [] if cols["event_id"] else ["event"]
                elif k == "place": cols["place_id"] = R.place(v)
                elif k == "person": cols["person_id"] = R.person(v)
                elif k == "entity":
                    et = c.get("entity_type")
                    cols["entity_id"] = {"unit": R.unit, "event": lambda e: R.event(e, d0, d1), "place": R.place,
                                         "person": R.person}[et](v)
                else: cols[k] = v
            for need, col in (("unit_mention", "unit"), ("event_mention", "event"), ("person_mention", "person"),
                              ("parent_mention", "parent"), ("successor_mention", "successor")):
                if col in c and need not in cols and TABLE[t] != "claim_known_as":
                    cols[need] = (c[col] or {}).get("display_name") or (c[col] or {}).get("name") or ""
            if t == "unit_at" and "place_mention" not in cols: cols["place_mention"] = (c.get("place") or {}).get("display_name", "")
            cid = claim(t, src[c["source"]], c.get("span"), c.get("confidence", 0.9), c.get("extracted_by") or "manual",
                        rel, TABLE[t], **cols)
            status = c.get("status", "accepted") if not missing else "pending"
            note = "; ".join(x for x in (c.get("note"), ("unresolved: " + ", ".join(missing)) if missing else None) if x) or None
            cur.execute("UPDATE claim SET status=?, review_note=? WHERE id=?", (status, note, cid))
            n[f"manual {t}"] += 1
            if missing: n["manual unresolved"] += 1
        for k, v in R.made.items():
            n[f"manual created {k}"] += v
