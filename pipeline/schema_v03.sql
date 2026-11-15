-- Schema v0.3: additive changes on top of schema.sql (v0.2). Nothing existing is altered.

-- Identifiers of an entity in other systems: Dyer's unit id, NPS unit code, Wikidata QID,
-- pipeline event id, place key. One entity can have many; lookups go through here.
CREATE TABLE external_id (
    entity_type  TEXT NOT NULL CHECK (entity_type IN ('unit','place','event','person','source')),
    entity_id    INTEGER NOT NULL,
    scheme       TEXT NOT NULL,       -- 'dyer', 'nps', 'wikidata', 'pipeline_event', 'place_key', 'cwsac'
    value        TEXT NOT NULL,
    PRIMARY KEY (scheme, value, entity_type)
);
CREATE INDEX external_id_entity ON external_id(entity_type, entity_id);

-- Where in the source a claim comes from: page, table id, article revision.
ALTER TABLE claim ADD COLUMN locator TEXT;

-- Order of command when several commanders are listed (0 = first), and casualty marks
-- from Wikipedia: k killed, mw mortally wounded, w wounded, c captured (combinations like 'w&c').
ALTER TABLE claim_commanded ADD COLUMN seq INTEGER;
ALTER TABLE claim_commanded ADD COLUMN casualty TEXT;

-- The parent chain as parsed: {"brigade":..., "division":..., "corps":..., "army":...}
ALTER TABLE claim_subordinate_to ADD COLUMN parent_path_json TEXT;

-- Indexes for the viewer and the agreement views
CREATE INDEX cp_unit_event ON claim_participated(unit_id, event_id);
CREATE INDEX cp_event ON claim_participated(event_id);
CREATE INDEX cua_unit ON claim_unit_at(unit_id, date_start);
CREATE INDEX cst_unit ON claim_subordinate_to(unit_id, date_start);
CREATE INDEX cc_unit ON claim_commanded(unit_id);
CREATE INDEX cc_person ON claim_commanded(person_id);
CREATE INDEX claim_source ON claim(source_id);

-- Participation with the number of independent source kinds behind each (unit, event) pair
CREATE VIEW v_participation_support AS
SELECT cp.unit_id, cp.event_id,
       COUNT(*) AS claims,
       COUNT(DISTINCT s.kind) AS source_kinds,
       GROUP_CONCAT(DISTINCT s.kind) AS kinds,
       MAX(c.confidence) AS best_confidence
FROM claim_participated cp JOIN claim c ON c.id = cp.claim_id JOIN source s ON s.id = c.source_id
WHERE cp.unit_id IS NOT NULL AND cp.event_id IS NOT NULL
GROUP BY cp.unit_id, cp.event_id;

-- Commanders by unit with their sources
CREATE VIEW v_unit_commanders AS
SELECT cc.unit_id, cc.person_id, p.display_name AS person, cc.person_mention, cc.seq, cc.casualty,
       cc.date_start, cc.date_end, s.title AS source, c.confidence
FROM claim_commanded cc JOIN claim c ON c.id = cc.claim_id JOIN source s ON s.id = c.source_id
LEFT JOIN person p ON p.id = cc.person_id;

-- ---------------------------------------------------------------------------------------------------------------
-- 9. Event part of event (added 2026-11-11). Membership is a claim, from any source; no fixed levels: depth is
--    whatever the graph says. One claim per event is marked preferred; event.parent_event_id mirrors it.
CREATE TABLE IF NOT EXISTS claim_part_of (
    claim_id         INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    event_mention    TEXT NOT NULL,
    event_id         INTEGER REFERENCES event(id),
    parent_mention   TEXT NOT NULL,
    parent_event_id  INTEGER REFERENCES event(id),
    preferred        INTEGER NOT NULL DEFAULT 0,
    dates_ok         INTEGER                -- child's dates fall inside the parent's (+-3 days)
);
CREATE INDEX IF NOT EXISTS claim_part_of_event ON claim_part_of(event_id);
CREATE INDEX IF NOT EXISTS claim_part_of_parent ON claim_part_of(parent_event_id);

-- Participation rolled up through preferred membership: a unit in a battle is in its campaign (never the reverse).
-- depth 0 = the event claimed; claims = supporting participation claims; via_events = distinct claimed events below.
CREATE VIEW IF NOT EXISTS v_participation_rollup AS
WITH RECURSIVE up(unit_id, event_id, via_event_id, depth, claim_id) AS (
    SELECT p.unit_id, p.event_id, p.event_id, 0, p.claim_id
    FROM claim_participated p JOIN claim c ON c.id = p.claim_id
    WHERE p.unit_id IS NOT NULL AND p.event_id IS NOT NULL AND c.status <> 'rejected'
    UNION
    SELECT up.unit_id, e.parent_event_id, up.via_event_id, up.depth + 1, up.claim_id
    FROM up JOIN event e ON e.id = up.event_id
    WHERE e.parent_event_id IS NOT NULL AND up.depth < 8
)
SELECT unit_id, event_id, MIN(depth) AS depth, COUNT(DISTINCT claim_id) AS claims,
       COUNT(DISTINCT via_event_id) AS via_events
FROM up GROUP BY unit_id, event_id;

-- Identity of a claim across rebuilds: hash of extractor, unit key, type, date, locator and the first 80 characters of the span
-- (common.claim_fingerprint). Decisions about single claims attach to it (roadmap T4.2, T4.5).
ALTER TABLE claim ADD COLUMN fingerprint TEXT;
CREATE INDEX claim_fingerprint ON claim(fingerprint);
