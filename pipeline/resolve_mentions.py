"""Resolve ambiguous Dyer's place mentions per unit, from the unit's own route.

geocode.py gives each place name ONE location for the whole war, chosen from where all units that mention it were. A
name without a state ("Alexandria") pools Alexandria, Va. and Alexandria, La.; a name with several namesakes in its
state, or none in GNIS, gets one compromise. Here each mention of a unit is resolved on its own:

1. Observations per unit, in date order: its Dyer's unit_at mentions (data/places/place_mentions.jsonl, source
   unit_at) and the located events it fought in (Wikidata-located events, data/events/events.jsonl lat/lon).
   An observation is an anchor when its place is clear: geocoded by override, seed, or GNIS with one candidate, with a
   state. Otherwise it is ambiguous: no state, a 'context' estimate, several GNIS namesakes, or not located at all.
2. Candidates for an ambiguous mention: every GNIS place (towns, forts, crossings, locales, ...) and every geocoded
   place of the same name (geocode.forms variants), in the written state (Va. also W. Va.) or, with no state, any state.
3. The route: a minimum-cost path through the observations (Viterbi). Moving d km in t days costs d/1000 plus
   d/500 plus (d - (150 + 250 t)) / 100 for the distance beyond rail or boat moves (regiments went to the front by rail); month-precision dates get 15 days
   of slack. A stateless town in the unit's own state gets a bonus (Dyer's "Organized at Rutland" for a Vermont
   regiment): 2.0 within 45 days of its first observation, else 0.5; a state the earlier passes only inferred
   (state_source not 'explicit') is a preference, not a limit: 1.5 when inferred from the unit's own context, 0.5 from
   the war-wide majority: "Franklin" guessed as Va. for a regiment in
   Louisiana. Anchors need a written state (or an override / Wikidata seed). GNIS 'Civil' features count (New England towns
   are filed as townships); state names do not. Forward and backward passes give, for each mention and candidate, the cost of the best route through it;
   the margin is the runner-up candidate's extra cost.
4. A pick is kept when its margin is >= MARGIN (a clear winner) and it lies near the unit's route: within
   150 + 30 t km (t = days to the nearer anchor) + half the distance between the anchors before and after, of the
   point on the straight line between them at that date, at most 800 km; a lone candidate within 150 km (a
   home-state town is exempt). State names ("Arkansas") are not resolved to towns named after them. A lone GNIS namesake far from
   the route (Upton's Hill, Va. is not in GNIS; one in Massachusetts is) fails this. Otherwise the mention keeps geocode.py's answer.

5. Events located only by their name: the units that fought there vote with their routes (see phase 2 in the code);
   data/places/event_resolution.jsonl, used by build_db.py for those events' locations. Small events (< 20 units)
   with Wikidata or approximate coordinates are tested first: if their units' clear positions within 45 days (clear Dyer's places, other events with a clear location) make
   them a mean detour over SUSPECT_DETOUR, they are not anchors and go to the vote too (replaces_coords).
6. A clear place (anchor) may still be the wrong location: its namesakes (within the written state, if any) are
   candidates at ANCHOR_SWITCH (gainesville|VA carried the Texas coordinates of a wrong Wikidata seed); a switch with margin >= ANCHOR_MARGIN (3.0: a margin of 1.8 moved Savannah, Ga. to a north Georgia namesake) is written like a resolution (was 'anchor').

7. Pooled 'context' places of a name with no state ("alexandria|?": a median of every unit's positions, near
   Petersburg): a mention no candidate settles gets the median of the unit's own clear positions within 30 days
   (class 'unit_context', 25 km). When the pooled point is beyond rail / boat reach of the unit's anchors within 30
   days (a same-day anchor only if it is an event), the best route pick is taken at margin >= MARGIN / 2, else the
   mention is detached (was 'off_route', no coordinates; build_db keeps the claim without a place). Lone GNIS
   namesakes (Fort Rice, Dakota for the Petersburg fort) are left alone: as often the anchor is a mismatched event.

Also writes data/places/unit_tracks.jsonl (each Dyer's unit's dated points: day numbers from 1861-01-01, slack,
lat, lon) for or_datelines.py.
Writes data/places/mention_resolution.jsonl (unit, date, raw, place_key -> name, state, lat, lon, precision_m, margin,
was) and a report. build_db.py uses it for Dyer's unit_at claims.
Usage: python pipeline/resolve_mentions.py data/places data/external/gnis/gnis_index.tsv data/dyers data/events \
    data/places/mention_resolution.jsonl data/scores/mention_resolution.txt
"""
import csv, json, math, re, sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from cwv import states as cwv_states  # noqa: E402
from geocode import forms, SAME, generic_dropped  # noqa: E402
from common import km, day_num as day, D0, gnis_by_name, too_fast  # noqa: E402
from gnis_index import norm  # noqa: E402

MARGIN = 1.0
ROUTE_NEAR, ROUTE_FAR = 100, 300    # km from the straight line between the anchors before and after
SMALL_EVENT, SUSPECT_DETOUR, ANCHOR_SWITCH, ANCHOR_MARGIN = 20, 2.0, 2.5, 3.0
EV_MARGIN, EV_MEAN = 1.0, 0.4   # EV_MEAN 0.4 ~ a 100 km detour: the true place may be missing from GNIS (White House Landing)
CLASS_COST = {"Populated Place": 0.0, "Military": 0.0, "geocoded": 0.0, "Locale": 0.3, "Crossing": 0.3,
              "Civil": 0.3, "Gap": 0.5, "Summit": 0.8, "Ridge": 0.8, "Island": 0.5, "Stream": 1.0}
PREC = {"Populated Place": 2000, "Military": 1500, "geocoded": 3000, "Locale": 3000, "Crossing": 2000, "Civil": 10000,
        "Gap": 2000, "Summit": 3000, "Ridge": 5000, "Island": 3000, "Stream": 15000}
import os
DEBUG_UNIT = os.environ.get("RM_DEBUG")


HOME = cwv_states.table("snake", "CODE", "AL", "AR", "CA", "CO", "CT", ("dakota", "SD"), "DE", "DC", "FL", "GA",
                                         "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
                                         "MO", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "OH", "OR", "PA", "RI",
                                         "TN", "TX", "VT", "VA", "WA", "WV", "WI")
GUESS_BONUS = 1.5     # the state geocoding inferred from the mention's context
HOME_BONUS = 0.5      # a stateless town in the unit's own state: Dyer's leaves the state off "Organized at Rutland"


def rival(tot, cs, distinct_km=25):
    """Margin of the best candidate over the best one that is a different place (more than distinct_km away): GNIS and
    the geocoded seed often give the same town twice (Alexandria, La. at -92.445 and -92.45), which is no rival."""
    b = cs[tot[0][1]]
    for t, j in tot[1:]:
        if km(b[1:3], cs[j][1:3]) > distinct_km:
            return t - tot[0][0]
    return 99.0


def step(a, b, ta, tb, slack):
    dk = km(a, b)
    t = max(2, tb - ta) + slack     # Dyer's often dates a move by one day for both ends ("Lynnfield ... Baltimore July 22")
    return dk / 500 + max(0.0, dk - (150 + 250 * t)) / 100


OUT_DAYS, OUT_SHARE = 10, 0.6
AREA_KINDS = ("campaign", "operation", "expedition", "march", "siege")   # areas, not points (as fast_jumps.py)


def out_of_reach(eid, ll, e0, e1, tracks, exclude=None, units=None, both=False):
    """How many of an event's units (with a clear position within OUT_DAYS before or after it) cannot have been at ll:
    over 300 km from the position before and the one after and faster than 250 km a day (fast_jumps.py's test). Returns
    (out of reach, units tested). A unit fails when either side fails (both=True: both sides; one side tested when it
    has only one)."""
    n_imp = n_used = 0
    for u in units if units is not None else ():
        tr = [a for a in tracks.get(u) or [] if exclude is None or (a[5] if len(a) > 5 else None) != exclude]
        prv = [a for a in tr if a[1] <= e0 and e0 - a[1] <= OUT_DAYS]
        nxt = [a for a in tr if a[0] >= e1 and a[0] - e1 <= OUT_DAYS]
        if not prv and not nxt:
            continue
        n_used += 1
        # the jump test of fast_jumps.py: over 300 km and faster than 250 km a day (the same day counts as one)
        far = [too_fast(km(a[3:5], ll), e0 - a[1] + a[2]) for a in prv[-1:]] + \
              [too_fast(km(ll, b[3:5]), b[0] - e1 + b[2]) for b in nxt[:1]]
        if (all(far) if both else any(far)):
            n_imp += 1
    return n_imp, n_used


def main(places_dir, gnis_p, dyers_dir, events_dir, out_p, rep_p):
    places_dir, dyers_dir, events_dir = Path(places_dir), Path(dyers_dir), Path(events_dir)
    geo = {g["place_key"]: g for g in csv.DictReader(open(places_dir / "geocoded.csv", encoding="utf-8"))}
    G = defaultdict(list)
    for nm, cs in gnis_by_name(gnis_p, CLASS_COST).items():
        G[nm] += cs
    for k, g in geo.items():                     # geocoded places by name too (overrides: Chicago, White House Landing)
        if g["lat"] and g["method"] in ("override", "seed", "gnis") and g["state"]:
            for f in forms(g["name"])[:1]:
                G[f].append((g["state"], float(g["lat"]), float(g["lon"]), "geocoded"))

    def clear(g, st):
        return bool(g) and bool(g.get("lat")) and st not in ("", "?") and (
            g["method"] in ("override", "seed") or (g["method"] == "gnis" and " 1 candidates" in g["detail"]))

    STATE_NAMES = {k.replace("_", " ") for k in HOME} | {"west virginia", "indian territory", "arizona", "utah", "dakota",
                                                          "new mexico", "colorado", "nebraska", "idaho", "montana"}

    def candidates(name, st):
        sts = SAME.get(st, {st}) if st not in ("", "?") else None
        out = {}
        if norm(re.sub(r"\(.*?\)", " ", name)).strip() in STATE_NAMES:
            return []                           # "Arkansas", "Maine": the state, not a town named after it
        for f in forms(name):
            if generic_dropped(name, f):
                continue                        # "Harrison's Landing" is not any town called Harrison
            for s, a, b, cl in G.get(f, []):
                if sts is not None and s not in sts:
                    continue
                k = (round(a, 1), round(b, 1))
                if k not in out or CLASS_COST[cl] < CLASS_COST[out[k][3]]:
                    out[k] = (s, a, b, cl)
            if out:
                break                           # the first (fullest) name form that GNIS knows
        return list(out.values())

    obs = defaultdict(list)                     # unit -> [(t0, t1, slack, kind, payload)]
    seen = set()
    for l in open(places_dir / "place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] != "unit_at" or not m.get("unit"):
            continue
        key = (m["unit"], m.get("date"), m["raw"])
        if key in seen:
            continue                            # build_db uses the first place of a mention
        seen.add(key)
        t0, sl = day(m.get("date"))
        if m.get("arrival"):                    # a move: at its destination on the arrival date ("Moved to Memphis,
            t0, sl = day(m["arrival"])          # thence march to Chattanooga, Sept. 27-Nov. 20" is Chattanooga on Nov. 20)
        if t0 is None:
            continue
        pk = m["place_key"]; st = pk.split("|")[1]; g = geo.get(pk)
        written = m.get("state_source") == "explicit"
        if not written and st not in ("", "?"):
            m["guess"], st = st, "?"            # a state inferred from context ("Franklin" -> Va.) is a preference only
        if clear(g, st) and (written or (g or {}).get("method") in ("override", "seed")):
            obs[m["unit"]].append((t0, t0, sl, "anchor", [(st, float(g["lat"]), float(g["lon"]), "anchor")], dict(m, st=st, g=g)))
        else:
            obs[m["unit"]].append((t0, t0, sl, "amb", None, dict(m, st=st, g=g)))
    # located events each unit fought in
    m2c = {}
    for l in open(dyers_dir / "mention_to_event.jsonl", encoding="utf-8"):
        m = json.loads(l); m2c[(m["unit_id"], m["mention"], m["date_start"])] = m["cluster_id"]
    c2e = {json.loads(l)["cluster_id"]: json.loads(l)["event_id"] for l in open(events_dir / "cluster_to_event.jsonl", encoding="utf-8")}
    evloc, evsmall = {}, set()
    for l in open(events_dir / "events.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if e.get("lat") is not None and e.get("date_start"):
            evloc[e["event_id"]] = (e["lat"], e["lon"], e["date_start"], e.get("date_end") or e["date_start"])
            if (e.get("regiments") or 0) < SMALL_EVENT:
                evsmall.add(e["event_id"])
    ev_units = defaultdict(set)
    for l in open(dyers_dir / "claims_rules.jsonl", encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] != "participated":
            continue
        eid_ = c2e.get(m2c.get((c["unit_id"], c.get("event_mention"), c.get("date_start"))))
        if eid_:
            ev_units[eid_].add(c["unit_id"])
    # a small event with Wikidata or approximate coordinates is suspect when the units that fought there all have clear
    # positions far from it (Dyer's "Gainesville" of Oct. 1862 matched to the Great Hanging at Gainesville, Texas): it
    # is not used as an anchor and goes to the vote of phase 2 like an event located only by its name
    clear_tr = defaultdict(list)
    for unit, os_ in obs.items():
        for o in os_:
            if o[3] == "anchor":
                clear_tr[unit].append((o[0], o[1], o[2], o[4][0][1], o[4][0][2]))
    # ... and the unit's other events with a clear location: a large located battle, or a name with one GNIS match
    ev_top = {}
    for l in open(places_dir / "place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] == "event" and m.get("event_id"):
            ev_top.setdefault(m["event_id"], Counter())[m["place_key"]] += m.get("weight", 1)
    ev_clear = {}
    for eid, cnt in ev_top.items():
        pk = cnt.most_common(1)[0][0]; g = geo.get(pk)
        if g and g.get("lat") and (g["method"] in ("override", "seed") or (g["method"] == "gnis" and " 1 candidates" in g["detail"])):
            ev_clear[eid] = (float(g["lat"]), float(g["lon"]))
    ev_dates = {}
    for l in open(events_dir / "events.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if e.get("date_start"):
            ev_dates[e["event_id"]] = e
            if e["event_id"] in evloc and e["event_id"] not in evsmall:
                ev_clear[e["event_id"]] = (e["lat"], e["lon"])
    for eid, uids in ev_units.items():
        if eid in ev_clear and eid in ev_dates:
            t0, sl0 = day(ev_dates[eid]["date_start"]); t1, _ = day(ev_dates[eid].get("date_end") or ev_dates[eid]["date_start"])
            if t0 is not None:
                for u in uids:
                    clear_tr[u].append((t0, t1 if t1 is not None else t0, sl0, ev_clear[eid][0], ev_clear[eid][1], eid))
    for u in clear_tr:
        clear_tr[u].sort(key=lambda a: a[0])
    suspects = {}
    for eid in evloc:
        lat, lon, ds, de = evloc[eid]
        e0, _ = day(ds); e1, _ = day(de)
        if e0 is None:
            continue
        e1 = e1 if e1 is not None else e0
        dets = []
        for u in ev_units.get(eid, ()):
            tr = [a for a in clear_tr.get(u) or [] if (a[5] if len(a) > 5 else None) != eid]
            prv = [a for a in tr if a[1] <= e0 and e0 - a[1] <= 45]; nxt = [a for a in tr if a[0] >= e1 and a[0] - e1 <= 45]
            if prv and nxt:
                a, b = prv[-1], nxt[0]
                dets.append(step(a[3:5], (lat, lon), a[1], e0, a[2]) + step((lat, lon), b[3:5], e1, b[0], b[2])
                            - step(a[3:5], b[3:5], a[1], b[0], a[2] + b[2]))
        if eid in evsmall:
            if (len(dets) >= 2 and sum(dets) / len(dets) > SUSPECT_DETOUR) or (len(dets) == 1 and dets[0] > 2 * SUSPECT_DETOUR):
                suspects[eid] = round(sum(dets) / len(dets), 2)
        elif ev_dates.get(eid, {}).get("kind") not in AREA_KINDS and e1 - e0 <= 7:
            # a larger event: suspect when most of its units cannot reach it at all (out_of_reach)
            n_imp, n_used = out_of_reach(eid, (lat, lon), e0, e1, clear_tr, exclude=eid, units=ev_units.get(eid, ()))
            if n_used >= 3 and n_imp >= OUT_SHARE * n_used:
                suspects[eid] = round(sorted(dets)[len(dets) // 2], 2) if dets else 99.0
    n_large_suspects = sum(1 for e in suspects if e not in evsmall)
    for l in open(dyers_dir / "claims_rules.jsonl", encoding="utf-8"):
        c = json.loads(l)
        if c["claim_type"] != "participated":
            continue
        eid_ = c2e.get(m2c.get((c["unit_id"], c.get("event_mention"), c.get("date_start"))))
        e = evloc.get(eid_) if eid_ not in suspects else None
        if e:
            t0, _ = day(e[2]); t1, _ = day(e[3])
            if t0 is not None:
                obs[c["unit_id"]].append((t0, t1 or t0, 0, "anchor", [("", e[0], e[1], "event")], None))

    stats, out = Counter(), []
    for unit, os_ in obs.items():
        os_.sort(key=lambda o: (o[0], o[3] != "anchor"))
        anchors = [i for i, o in enumerate(os_) if o[3] == "anchor"]
        if not anchors:
            stats["units without anchors"] += 1
            continue
        # candidate lists
        home = HOME.get(unit.split("/")[0])
        C = []
        for n_obs, o in enumerate(os_):
            if o[3] == "anchor":
                alts = []
                if o[5] is not None:            # a clear Dyer's place may still be the wrong namesake ("Washington")
                    a0 = o[4][0]
                    wst = o[5]["st"] if o[5].get("state_source") == "explicit" else "?"   # never out of a written state
                    alts = [c[:4] + (ANCHOR_SWITCH,) for c in candidates(o[5]["name"], wst)
                            if km(a0[1:3], c[1:3]) > 50]
                C.append(o[4] + alts)
            else:
                m = o[5]
                cs = candidates(m["name"], m["st"])
                if m["st"] in ("", "?"):
                    edge = o[0] - os_[0][0] <= 45                     # organized: at home (mustered out: often in the field)
                    hb = (2.0 if edge else HOME_BONUS) if home else 0
                    gb = GUESS_BONUS if m.get("state_source") in ("unit_context", "list") else 0.5   # 'global' guesses are weaker
                    cs = [c[:3] + (c[3], -(hb if c[0] == home else 0) - (gb if c[0] == m.get("guess") else 0))
                          for c in cs]
                C.append(cs)
        idx = [i for i, cs in enumerate(C) if cs]          # observations that take part in the route
        if len(idx) < 2:
            continue
        # Viterbi forward / backward over idx
        F, B = [], [None] * len(idx)
        for n, i in enumerate(idx):
            em = [CLASS_COST.get(c[3], 0) + (c[4] if len(c) > 4 else 0) for c in C[i]]
            if n == 0:
                F.append(em); continue
            p = idx[n - 1]; sl = os_[p][2] + os_[i][2]
            F.append([em[j] + min(F[-1][k] + step(C[p][k][1:3], C[i][j][1:3], os_[p][1], os_[i][0], sl)
                                  for k in range(len(C[p]))) for j in range(len(C[i]))])
        B[-1] = [0.0] * len(C[idx[-1]])
        for n in range(len(idx) - 2, -1, -1):
            i, q = idx[n], idx[n + 1]; sl = os_[i][2] + os_[q][2]
            emq = [CLASS_COST.get(c[3], 0) + (c[4] if len(c) > 4 else 0) for c in C[q]]
            B[n] = [min(B[n + 1][k] + emq[k] + step(C[i][j][1:3], C[q][k][1:3], os_[i][1], os_[q][0], sl)
                        for k in range(len(C[q]))) for j in range(len(C[i]))]
        for n, i in enumerate(idx):
            o = os_[i]
            if o[3] == "anchor":
                if len(C[i]) > 1:
                    tot = sorted((F[n][j] + B[n][j], j) for j in range(len(C[i])))
                    if tot[0][1] != 0 and km(C[i][tot[0][1]][1:3], C[i][0][1:3]) > 25 and rival(tot, C[i]) >= ANCHOR_MARGIN:
                        best = C[i][tot[0][1]]; m = o[5]; a0 = C[i][0]
                        stats["anchors switched to a namesake"] += 1
                        out.append({"unit": unit, "date": m.get("date"), "raw": m["raw"], "place_key": m["place_key"],
                                    "name": m["name"], "state": best[0], "lat": round(best[1], 5), "lon": round(best[2], 5),
                                    "precision_m": PREC.get(best[3], 3000), "class": best[3],
                                    "margin": round(min(rival(tot, C[i]), 99), 2), "candidates": len(C[i]),
                                    "was": "anchor", "moved_km": round(km(a0[1:3], best[1:3]))})
                continue
            m = o[5]
            stats["ambiguous mentions with candidates"] += 1
            tot = sorted((F[n][j] + B[n][j], j) for j in range(len(C[i])))
            best = C[i][tot[0][1]]
            margin = rival(tot, C[i])
            # reach: the pick must lie near the unit's route between its anchors (linear in time between the anchor
            # before and the one after); a home-state town is exempt (organized / mustered out there)
            pa = [x for x in anchors if x < i][-1:]; na = [x for x in anchors if x > i][:1]
            if pa and na:
                a, b = os_[pa[0]], os_[na[0]]
                f = 0.5 if b[0] == a[1] else min(1, max(0, (o[0] - a[1]) / (b[0] - a[1])))
                route = (a[4][0][1] + f * (b[4][0][1] - a[4][0][1]), a[4][0][2] + f * (b[4][0][2] - a[4][0][2]))
                tn = min(abs(o[0] - a[1]), abs(b[0] - o[0])) + o[2]
                span = km(a[4][0][1:3], b[4][0][1:3])
            else:
                a = os_[(pa or na)[0]]
                route = a[4][0][1:3]; tn = abs(o[0] - a[0]) + o[2]; span = 0
            dev = km(route, best[1:3])
            lim = 150 if len(C[i]) == 1 else min(150 + 30 * tn + 0.5 * span, 800)   # a lone namesake: near the route
            reach_ok = dev <= lim or (home and best[0] == home and m["st"] in ("", "?"))
            # a small cost margin still decides when the pick is on the unit's route and every other place of that
            # name is far off it (Alexandria, La. for the Red River regiments, margin 0.93 over Alexandria, Miss.)
            rv = [C[i][j] for _, j in tot[1:] if km(best[1:3], C[i][j][1:3]) > 25]
            g = m["g"] or {}
            # the place geocode.py would give this mention (pooled over all units: "Alexandria" with no state is a
            # median near Petersburg; Fort Rice, Dakota is GNIS's only Fort Rice): impossible for this unit when it is
            # too fast to reach from the nearest anchor on each side (common.too_fast, the test of fast_jumps.py)
            # (anchors within 30 days count; a far one says little)
            def impossible(p):
                ends = [(max(0, os_[x][0] - o[0], o[0] - os_[x][1]), os_[x]) for x in pa + na]   # days outside its span
                # same day: only a located event counts (Dyer's lists a unit's moves under one date)
                ends = [(dt, e) for dt, e in ends if dt <= 30 and (dt > 0 or e[5] is None)]
                return bool(ends) and all(too_fast(km(e[4][0][1:3], p), dt + e[2] + o[2]) for dt, e in ends)
            if DEBUG_UNIT and unit == DEBUG_UNIT:
                print("DBG", m.get("date"), m["raw"], m.get("state_source"), g.get("lat"), [ (os_[x][0], os_[x][1], os_[x][4][0][1:3]) for x in pa+na], o[0], margin, reach_ok, len(C[i]))
            # only geocode.py's pooled 'context' medians: a lone GNIS namesake that is impossible here is as often right
            # with a wrongly matched event as the anchor (Duvall's Bluff vs "Jonesboro"); those wait for the gazetteer
            # ... and a GNIS place for a state the text never wrote ("At Burkesville" after Appomattox took Burkesville,
            # Ky., the state other units wrote; 2026-11-14)
            pooled = (g.get("method") == "context" and m["place_key"].endswith("|?")) or bool(m.get("guess"))
            cur_bad = pooled and bool(g.get("lat")) and impossible((float(g["lat"]), float(g["lon"])))
            def detach(why):
                stats[why] += 1
                out.append({"unit": unit, "date": m.get("date"), "raw": m["raw"], "place_key": m["place_key"],
                            "name": m["name"], "state": None, "lat": None, "lon": None, "precision_m": None,
                            "class": None, "margin": round(min(margin, 99), 2), "candidates": len(C[i]),
                            "was": "off_route", "moved_km": None})
            # geocode.py's 'context' place is a median over every unit that wrote the name ("Alexandria" with no state:
            # a point near Petersburg); for a mention no candidate settles, the median of this unit's own clear
            # positions within 30 days is the better estimate (25 km precision, like the pooled one)
            def local(why):
                if not pooled or (g.get("method") != "context" and not cur_bad):
                    return False                 # a key with a written state ("harrisons landing|VA") pools one real place;
                                                 # a GNIS place for an unwritten state is replaced only when impossible
                near = [os_[x][4][0][1:3] for x in anchors
                        if max(0, os_[x][0] - o[0], o[0] - os_[x][1]) <= 30 and not impossible(os_[x][4][0][1:3])]
                if not near:
                    return False
                la = sorted(p_[0] for p_ in near)[len(near) // 2]; lo = sorted(p_[1] for p_ in near)[len(near) // 2]
                stats[why] += 1
                moved = km((float(g["lat"]), float(g["lon"])), (la, lo)) if g.get("lat") else None
                out.append({"unit": unit, "date": m.get("date"), "raw": m["raw"], "place_key": m["place_key"],
                            "name": m["name"], "state": None, "lat": round(la, 5), "lon": round(lo, 5),
                            "precision_m": 25000, "class": "unit_context", "margin": round(min(margin, 99), 2),
                            "candidates": len(C[i]), "was": g.get("method") or "none", "moved_km": None if moved is None else round(moved)})
                return True
            if margin < MARGIN and not (pa and na and dev <= ROUTE_NEAR and margin >= MARGIN / 4
                                        and all(km(route, c[1:3]) >= ROUTE_FAR for c in rv)):
                if cur_bad and reach_ok and margin >= MARGIN / 2 and not impossible(best[1:3]):
                    stats["resolved: pooled place impossible, best route pick taken (small margin)"] += 1
                    if DEBUG_UNIT == "picks":
                        print("PICK", unit, m.get("date"), m["raw"][:40], g.get("method"), g.get("lat"), g.get("lon"), "->", best[:3], round(margin, 2))
                elif local("pooled context place -> the unit's own context (no clear pick)"):
                    continue
                elif cur_bad:
                    detach("detached: pooled place impossible for the unit's route, no clear pick"); continue
                else:
                    stats["kept: no clear winner"] += 1; continue
            elif margin < MARGIN:
                stats["resolved by the route line (small margin)"] += 1
            if not reach_ok:
                if local("pooled context place -> the unit's own context (pick out of reach)"):
                    continue
                if cur_bad:
                    detach("detached: pooled place impossible, pick out of reach"); continue
                stats["kept: pick out of reach of the unit's anchors"] += 1; continue
            was = (g.get("method") or "none", float(g["lat"]) if g.get("lat") else None, float(g["lon"]) if g.get("lat") else None)
            moved = None if was[1] is None else km((was[1], was[2]), best[1:3])
            if was[1] is not None and moved < 5:
                stats["resolved: same as before"] += 1
            elif was[1] is None:
                stats["resolved: newly located"] += 1
            else:
                stats["resolved: moved"] += 1
            out.append({"unit": unit, "date": m.get("date"), "raw": m["raw"], "place_key": m["place_key"], "name": m["name"],
                        "state": best[0], "lat": round(best[1], 5), "lon": round(best[2], 5),
                        "precision_m": PREC.get(best[3], 3000), "class": best[3], "margin": round(min(margin, 99), 2),
                        "candidates": len(C[i]), "was": was[0], "moved_km": None if moved is None else round(moved)})
    with open(out_p, "w", encoding="utf-8") as fo:
        for r in out:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- phase 2: events located only by their name (no Wikidata coordinates): the units that fought there vote
    # with their routes. Each unit's anchors (clear places, located battles, its confident resolutions above); for each
    # candidate namesake, the detour it costs the unit (prev anchor -> candidate -> next anchor, minus prev -> next);
    # the candidate with the lowest summed detour wins if it leads by EV_MARGIN (2x with one unit) and the mean detour
    # of the units is under EV_MEAN.
    track = defaultdict(list)
    for unit, os_ in obs.items():
        for o in os_:
            if o[3] == "anchor":
                track[unit].append((o[0], o[1], o[2], o[4][0][1], o[4][0][2]))
    for r in out:
        t0, sl = day(r["date"])
        if t0 is not None and r["lat"] is not None:
            track[r["unit"]].append((t0, t0, sl, r["lat"], r["lon"]))
    for u in track:
        track[u].sort()
    evinfo, evnames = {}, defaultdict(Counter)
    for l in open(events_dir / "events.jsonl", encoding="utf-8"):
        e = json.loads(l)
        if (e.get("lat") is None or e["event_id"] in suspects) and e.get("date_start"):
            evinfo[e["event_id"]] = e
    for l in open(places_dir / "place_mentions.jsonl", encoding="utf-8"):
        m = json.loads(l)
        if m["source"] == "event" and m.get("event_id") in evinfo:
            st = m["place_key"].split("|")[1]
            evnames[m["event_id"]][(m["name"], st if m.get("state_source") == "explicit" else "?",
                                    st if m.get("state_source") != "explicit" else None, m["place_key"])] += m.get("weight", 1)
    est, eout = Counter(), []
    for eid, e in evinfo.items():
        units = ev_units.get(eid, set())
        if not units or not evnames.get(eid):
            continue
        e0, _ = day(e["date_start"]); e1, _ = day(e.get("date_end") or e["date_start"])
        if e0 is None:
            continue
        e1 = e1 if e1 is not None else e0
        (name, st, guess, pk), _ = evnames[eid].most_common(1)[0]
        cs = candidates(name, st)
        if len(cs) < 1:
            continue
        est["events with candidates"] += 1
        tot = [0.0] * len(cs); used = 0
        for u in units:
            tr = track.get(u) or []
            prv = [a for a in tr if a[1] <= e0 and e0 - a[1] <= 60]
            nxt = [a for a in tr if a[0] >= e1 and a[0] - e1 <= 60]
            prv = prv[-1] if prv else None; nxt = nxt[0] if nxt else None
            if not prv and not nxt:
                continue
            used += 1
            for j, c in enumerate(cs):
                cost = 0.0
                if prv:
                    cost += step(prv[3:5], c[1:3], prv[1], e0, prv[2])
                if nxt:
                    cost += step(c[1:3], nxt[3:5], e1, nxt[0], nxt[2])
                if prv and nxt:
                    cost -= step(prv[3:5], nxt[3:5], prv[1], nxt[0], prv[2] + nxt[2])
                tot[j] += min(cost, 10.0)
        if not used:
            est["no unit with a position within 60 days"] += 1; continue
        for j, c in enumerate(cs):
            tot[j] += CLASS_COST.get(c[3], 0) - (GUESS_BONUS if guess and c[0] == guess else 0)
        order = sorted(range(len(cs)), key=lambda j: tot[j])
        b = order[0]; margin = rival([(tot[j], j) for j in order], cs)
        if margin < (EV_MARGIN if used >= 2 else 2 * EV_MARGIN):
            est["kept: no clear winner"] += 1; continue
        if (tot[b] + (GUESS_BONUS if guess and cs[b][0] == guess else 0)) / used > EV_MEAN:
            est["kept: winner is a detour for its units"] += 1; continue
        g = geo.get(pk) or {}
        was = (float(g["lat"]), float(g["lon"])) if g.get("lat") and g.get("method") in ("gnis", "override", "seed") else None
        if eid in suspects:
            was, g = (e["lat"], e["lon"]), {"method": f"{e.get('coord_source')} (suspect, mean detour {suspects[eid]})"}
        moved = km(was, cs[b][1:3]) if was else None
        est["same as before" if moved is not None and moved < 5 else ("newly located" if was is None else "moved")] += 1
        eout.append({"event_id": eid, "event": e["name"], "date": e["date_start"], "name": name, "state": cs[b][0],
                     "lat": round(cs[b][1], 5), "lon": round(cs[b][2], 5), "precision_m": PREC.get(cs[b][3], 3000),
                     "class": cs[b][3], "margin": round(min(margin, 99), 2), "units": used, "candidates": len(cs),
                     "place_key": pk, "moved_km": None if moved is None else round(moved), "was": "none" if was is None else g["method"],
                     "replaces_coords": eid in suspects})
    # an event the vote leaves where it was (its suspect coordinates, or the pooled place of its name that build_db.py
    # would use: "Flint River Station" at the Flint River's mouth, "Blountsville" in Montgomery Co., Tenn.) is not
    # placed at all when most of its units cannot reach that place (2+ units tested): was 'off_route', no coordinates
    placed = {r["event_id"] for r in eout}
    track2 = defaultdict(list, {u: list(v) for u, v in track.items()})     # + the events the vote just placed
    for r in eout:
        t0_, sl_ = day(r["date"])
        if t0_ is not None:
            for u in ev_units.get(r["event_id"], ()):
                track2[u].append((t0_, t0_, sl_, r["lat"], r["lon"], r["event_id"]))
    for u in track2:
        track2[u].sort(key=lambda a: a[0])
    for eid, e in evinfo.items():
        if eid in placed or e.get("kind") in AREA_KINDS:
            continue
        ll = None
        if eid in suspects:
            ll = (e["lat"], e["lon"])
        else:
            for (nm_, st_, gs_, pk_), _ in evnames.get(eid, Counter()).most_common(3):
                g = geo.get(pk_) or {}
                est_ = e.get("state")
                if g.get("lat") and est_ and g.get("state") and g["state"] != est_ and {g["state"], est_} != {"VA", "WV"}:
                    continue
                if g.get("lat") and g.get("method") in ("gnis", "override", "seed"):
                    ll = (float(g["lat"]), float(g["lon"])); break
        if ll is None:
            continue
        e0, _ = day(e["date_start"]); e1, _ = day(e.get("date_end") or e["date_start"])
        if e0 is None or (e1 or e0) - e0 > 7:
            continue                     # a long operation is an area, not a point (as fast_jumps.py)
        n_imp, n_used = out_of_reach(eid, ll, e0, e1 if e1 is not None else e0, track2, units=ev_units.get(eid, ()))
        if n_used >= 2 and n_imp >= OUT_SHARE * n_used:
            est["not placed: its place is out of its units' reach"] += 1
            eout.append({"event_id": eid, "event": e["name"], "date": e["date_start"], "name": e["name"], "state": None,
                         "lat": None, "lon": None, "precision_m": None, "class": None, "margin": None, "units": n_used,
                         "candidates": None, "place_key": None, "moved_km": None, "was": "off_route",
                         "out_of_reach": n_imp, "replaces_coords": eid in suspects})
    # a unit matched to an event it cannot have fought: its clear positions within OUT_DAYS before and after agree with
    # each other (within 150 km) and both fail the jump test against the event (the 11th Illinois, in Louisiana, matched
    # to Jonesborough, Ga.): data/places/participation_off_route.jsonl; build_db.py unlinks that participation
    evpt = {eid: (v[0], v[1]) for eid, v in evloc.items() if eid not in suspects}
    for r in eout:
        if r["lat"] is not None:
            evpt[r["event_id"]] = (r["lat"], r["lon"])
    off_part = []
    for eid, ll in evpt.items():
        e = ev_dates.get(eid)
        if not e or e.get("kind") in AREA_KINDS:
            continue
        e0, _ = day(e["date_start"]); e1, _ = day(e.get("date_end") or e["date_start"])
        if e0 is None or (e1 or e0) - e0 > 7:
            continue
        e1 = e1 if e1 is not None else e0
        for u in ev_units.get(eid, ()):
            tr = [a for a in clear_tr.get(u) or [] if (a[5] if len(a) > 5 else None) != eid]
            prv = [a for a in tr if a[1] <= e0 and e0 - a[1] <= OUT_DAYS]
            nxt = [a for a in tr if a[0] >= e1 and a[0] - e1 <= OUT_DAYS]
            if not prv or not nxt:
                continue
            a, b = prv[-1], nxt[0]
            if km(a[3:5], b[3:5]) <= 150 and out_of_reach(eid, ll, e0, e1, {u: [a, b]}, units=[u], both=True)[0]:
                off_part.append({"unit": u, "event_id": eid, "event": e["name"], "date": e["date_start"],
                                 "before": [round(a[3], 3), round(a[4], 3)], "after": [round(b[3], 3), round(b[4], 3)]})
    with open(Path(out_p).with_name("participation_off_route.jsonl"), "w", encoding="utf-8") as fo:
        for r in off_part:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    est["participations off the unit's route (unlinked)"] = len(off_part)
    # a suspect Wikidata match that the vote moves far away was a different action of the same name (the Great Hanging at
    # Gainesville, Texas for Dyer's Gainesville, Va.): merge_events.py detaches it on the next build (Dyer's own name, no
    # Wikidata coordinates). Entries carry forward while the event stays detached; delete a line to undo one.
    rdp = events_dir / "route_detached.jsonl"
    old = {}
    if rdp.exists():
        for l in open(rdp, encoding="utf-8"):
            r = json.loads(l); old[(r["wikidata"], tuple(r["clusters"]))] = r
    allev = {}
    for l in open(events_dir / "events.jsonl", encoding="utf-8"):
        e = json.loads(l); allev[e["event_id"]] = e
    det = []
    for e in allev.values():
        if e.get("detach_reason") == "route":
            r = old.get((e["wikidata_detached"], tuple(e["clusters"]))) or next(
                (r for (q, cl), r in old.items() if q == e["wikidata_detached"] and set(cl) & set(e["clusters"])), None)
            if r:
                det.append(dict(r, clusters=e["clusters"]))
    for r in eout:
        e = allev[r["event_id"]]
        if r["replaces_coords"] and r["lat"] is not None and e.get("wikidata") and (r["moved_km"] or 0) > 100:
            det.append({"wikidata": e["wikidata"], "clusters": e["clusters"], "wikidata_name": e["name"],
                        "dyer_name": e.get("dyer_name"), "date": e["date_start"], "units": r["units"],
                        "mean_detour": suspects.get(r["event_id"]), "moved_km": r["moved_km"],
                        "placed_at": f"{r['name']}, {r['state']}"})
    with open(rdp, "w", encoding="utf-8") as fo:
        for r in det:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats["events: Wikidata matches detached by the routes (route_detached.jsonl)"] = len(det)
    for eid, dt in sorted(suspects.items(), key=lambda a: -a[1]):
        e = allev[eid]
        stats[f"  suspect {eid} {e['date_start']} {e['name']} ({e.get('coord_source')}, mean detour {dt}): "
              f"{next(('not placed' if r['lat'] is None else 're-placed') for r in eout if r['event_id'] == eid) if any(r['event_id'] == eid for r in eout) else 'kept'}"] = 1
    with open(Path(out_p).with_name("event_resolution.jsonl"), "w", encoding="utf-8") as fo:
        for r in eout:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    # unit tracks for other resolvers (or_datelines.py): anchors, confident resolutions, events placed by the vote
    for r in eout:
        t0, sl = day(r["date"])
        if t0 is not None and r["lat"] is not None:
            for u in ev_units.get(r["event_id"], ()):
                track[u].append((t0, t0, sl, r["lat"], r["lon"]))
    with open(Path(out_p).with_name("unit_tracks.jsonl"), "w", encoding="utf-8") as fo:
        for u, tr in track.items():
            fo.write(json.dumps({"unit": u, "points": [[a[0], a[1], a[2], round(a[3], 4), round(a[4], 4)]
                                                       for a in sorted(tr)]}) + "\n")
    for k, v in est.items():
        stats["events: " + k] = v
    stats["events: suspect coordinates (small events, units far away)"] = len(suspects) - n_large_suspects
    stats["events: larger events suspect (most units out of reach)"] = n_large_suspects
    stats["events: suspects re-placed by the vote"] = sum(1 for r in eout if r["replaces_coords"] and r["lat"] is not None)
    rep = [f"{k}: {v}" for k, v in stats.most_common()]
    open(rep_p, "w").write("\n".join(rep) + "\n")
    print("\n".join(rep))


if __name__ == "__main__":
    main(*(sys.argv[1:] or paths.defaults("resolve_mentions")))
