-- Civil War Viewer: claims database schema (draft v0.2)
-- v0.2 (after tests on 24th Michigan, 21st Ohio, 26th North Carolina):
--   * 'portion' on unit_at and participated (detachments, non-veterans, companies)
--   * merged_into -> succeeded_by, with kind (merged | reorganized)
--   * losses and strength moved out of participated into a new unit_numbers claim,
--     tied to an event or to a date range (covers war totals, strength at a date)
-- SQLite. Layers: sources (raw archive index) -> claims -> canonical entities.
-- Derived views (tracks, hierarchy) are built from accepted claims and are not stored here yet.

PRAGMA foreign_keys = ON;

------------------------------------------------------------------------------
-- 1. Sources (index into the raw archive; the documents themselves live on disk)
------------------------------------------------------------------------------
CREATE TABLE source (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN
                    ('compendium','official_records','regimental_history',
                     'state_record','government_list','website','manual')),
    citation      TEXT,            -- bibliographic citation, volume/page
    url           TEXT,
    archive_path  TEXT,            -- path to the saved copy in the raw archive
    fetched_at    TEXT,            -- ISO timestamp
    public_domain INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);

------------------------------------------------------------------------------
-- 2. Canonical entities (resolved; one row per real-world thing)
------------------------------------------------------------------------------
CREATE TABLE side (                -- belligerents, not hard-coded Union/Confederate
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE
);

CREATE TABLE unit (
    id              INTEGER PRIMARY KEY,
    side_id         INTEGER NOT NULL REFERENCES side(id),
    echelon         TEXT NOT NULL CHECK (echelon IN
                      ('company','battalion','regiment','battery','brigade',
                       'division','corps','army','department','other')),
    branch          TEXT CHECK (branch IN
                      ('infantry','cavalry','artillery','engineers','sharpshooters','mixed','other')),
    state           TEXT,          -- raising state for volunteer units, e.g. 'MI'
    number          INTEGER,       -- 24 for the 24th Michigan; NULL for named units
    display_name    TEXT NOT NULL, -- the one name the viewer shows
    notes           TEXT
);

CREATE TABLE place (
    id              INTEGER PRIMARY KEY,
    display_name    TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN
                      ('town','fort','ford','crossroads','battlefield','camp',
                       'river','railroad','region','other')),
    state           TEXT,
    lat             REAL,          -- representative point
    lon             REAL,
    precision_m     REAL,          -- rough radius of uncertainty in metres
    geometry_json   TEXT,          -- optional GeoJSON for lines/areas (railroads, regions)
    notes           TEXT
);

CREATE TABLE event (
    id              INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL CHECK (kind IN
                      ('campaign','battle','engagement','siege','operation',
                       'march','expedition','encampment','political','other')),
    display_name    TEXT NOT NULL,
    parent_event_id INTEGER REFERENCES event(id),  -- battle within campaign
    notes           TEXT
);

CREATE TABLE person (
    id              INTEGER PRIMARY KEY,
    display_name    TEXT NOT NULL,
    side_id         INTEGER REFERENCES side(id),
    notes           TEXT
);

------------------------------------------------------------------------------
-- 3. Claims: one header row per statement, one detail row in a type table.
--    Each detail row keeps the text as found (mention) and, once resolved,
--    the canonical id. Unresolved claims have NULL ids and wait for review.
--
--    Dates: ISO strings (YYYY-MM-DD) with a precision so "Oct. 1862" is
--    stored as 1862-10-01..1862-10-31, precision 'month'.
------------------------------------------------------------------------------
CREATE TABLE claim (
    id             INTEGER PRIMARY KEY,
    claim_type     TEXT NOT NULL CHECK (claim_type IN
                     ('unit_at','participated','subordinate_to','commanded',
                      'event_at','known_as','succeeded_by','unit_numbers','part_of')),
    source_id      INTEGER NOT NULL REFERENCES source(id),
    source_span    TEXT,           -- the exact text the claim came from
    confidence     REAL NOT NULL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
    extracted_by   TEXT NOT NULL,  -- 'manual', 'regex:v1', 'llm:<model>:<prompt-version>'
    extracted_at   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
                     ('pending','accepted','rejected','superseded')),
    review_note    TEXT
);
CREATE INDEX claim_type_status ON claim(claim_type, status);

-- Shared date columns are repeated per table to keep queries simple.
--
-- portion: which part of the unit the claim is about. 'whole' unless the
-- source says otherwise; portion_detail holds the source's words
-- ('Companies A and F', 'volunteers for the raid').

-- 1. Unit was at place, on a date or date range
CREATE TABLE claim_unit_at (
    claim_id       INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    unit_mention   TEXT NOT NULL,
    unit_id        INTEGER REFERENCES unit(id),
    place_mention  TEXT NOT NULL,
    place_id       INTEGER REFERENCES place(id),
    presence       TEXT NOT NULL DEFAULT 'present' CHECK (presence IN
                     ('present','arrived','departed','en_route','along')),
    portion        TEXT NOT NULL DEFAULT 'whole' CHECK (portion IN
                     ('whole','detachment','companies','veterans','non_veterans')),
    portion_detail TEXT,
    date_start     TEXT,
    date_end       TEXT,
    date_precision TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 2. Unit participated in event (numbers live in claim_unit_numbers)
CREATE TABLE claim_participated (
    claim_id         INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    unit_mention     TEXT NOT NULL,
    unit_id          INTEGER REFERENCES unit(id),
    event_mention    TEXT NOT NULL,
    event_id         INTEGER REFERENCES event(id),
    portion          TEXT NOT NULL DEFAULT 'whole' CHECK (portion IN
                       ('whole','detachment','companies','veterans','non_veterans')),
    portion_detail   TEXT,
    date_start       TEXT,
    date_end         TEXT,
    date_precision   TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 3. Unit was subordinate to unit, during a date range
CREATE TABLE claim_subordinate_to (
    claim_id        INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    unit_mention    TEXT NOT NULL,
    unit_id         INTEGER REFERENCES unit(id),
    parent_mention  TEXT NOT NULL,  -- e.g. '1st Brigade, 1st Division, 1st Corps'
    parent_unit_id  INTEGER REFERENCES unit(id),
    date_start      TEXT,
    date_end        TEXT,
    date_precision  TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 4. Person commanded unit, during a date range
CREATE TABLE claim_commanded (
    claim_id        INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    person_mention  TEXT NOT NULL,
    person_id       INTEGER REFERENCES person(id),
    unit_mention    TEXT NOT NULL,
    unit_id         INTEGER REFERENCES unit(id),
    date_start      TEXT,
    date_end        TEXT,
    date_precision  TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 5. Event occurred at place, during a date range
CREATE TABLE claim_event_at (
    claim_id        INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    event_mention   TEXT NOT NULL,
    event_id        INTEGER REFERENCES event(id),
    place_mention   TEXT,
    place_id        INTEGER REFERENCES place(id),
    date_start      TEXT,
    date_end        TEXT,
    date_precision  TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 6. Entity known as name (battles: by side; units: with date range)
CREATE TABLE claim_known_as (
    claim_id        INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('unit','place','event','person')),
    entity_id       INTEGER,        -- resolved canonical id
    name            TEXT NOT NULL,
    name_type       TEXT NOT NULL CHECK (name_type IN
                      ('standard','union','confederate','official','alias','abbreviation','nickname')),
    date_start      TEXT,
    date_end        TEXT
);

-- 7. Unit succeeded by unit, on a date (merged into it, or re-raised as it)
CREATE TABLE claim_succeeded_by (
    claim_id          INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    unit_mention      TEXT NOT NULL,
    unit_id           INTEGER REFERENCES unit(id),
    successor_mention TEXT NOT NULL,
    successor_unit_id INTEGER REFERENCES unit(id),
    kind              TEXT NOT NULL CHECK (kind IN ('merged','reorganized')),
    succession_date   TEXT,
    date_precision    TEXT CHECK (date_precision IN ('day','month','year'))
);

-- 8. Unit numbers: strength and losses, tied to an event OR a date range.
--    Event-level numbers for a parent event and its children may overlap;
--    derived views sum one level only, never both.
CREATE TABLE claim_unit_numbers (
    claim_id          INTEGER PRIMARY KEY REFERENCES claim(id) ON DELETE CASCADE,
    unit_mention      TEXT NOT NULL,
    unit_id           INTEGER REFERENCES unit(id),
    event_mention     TEXT,
    event_id          INTEGER REFERENCES event(id),
    date_start        TEXT,              -- for numbers not tied to an event
    date_end          TEXT,
    date_precision    TEXT CHECK (date_precision IN ('day','month','year')),
    scope             TEXT NOT NULL DEFAULT 'event' CHECK (scope IN
                        ('event','at_date','period','whole_service')),
    strength          INTEGER,           -- men present
    killed            INTEGER,           -- killed or mortally wounded
    wounded           INTEGER,
    missing_captured  INTEGER,
    died_disease      INTEGER,
    died_captivity    INTEGER,
    casualties_total  INTEGER,           -- when only a total is given
    CHECK (event_mention IS NOT NULL OR date_start IS NOT NULL OR scope = 'whole_service')
);

------------------------------------------------------------------------------
-- Overrides: hand fixes that always win and survive re-extraction
------------------------------------------------------------------------------
CREATE TABLE override (
    id           INTEGER PRIMARY KEY,
    target_table TEXT NOT NULL,     -- e.g. 'place'
    target_id    INTEGER NOT NULL,
    field        TEXT NOT NULL,     -- e.g. 'lat'
    value        TEXT,
    reason       TEXT,
    created_at   TEXT NOT NULL
);
