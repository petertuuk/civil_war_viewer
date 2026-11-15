"""Counts from civil_war.db for the metrics file (roadmap T1.2): what the build produced, as numbers that should not move by accident.

    python3 pipeline/db_metrics.py civil_war.db        -> data/scores/metrics/db.json

Rows per table; claims per extractor (extracted_by) and per type and status; participations linked / unlinked to a unit and to an
event; unit_at claims without a place or unit. Read-only.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwv import paths  # noqa: E402
from metrics import record  # noqa: E402


def main(dbp):
    db = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    q = lambda sql: db.execute(sql).fetchall()
    tables = [r[0] for r in q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    rows = {t: q(f'SELECT COUNT(*) FROM "{t}"')[0][0] for t in tables}
    part = q("SELECT COUNT(*), SUM(event_id IS NULL), SUM(unit_id IS NULL), SUM(event_id IS NULL OR unit_id IS NULL) FROM claim_participated")[0]
    uat = q("SELECT COUNT(*), SUM(place_id IS NULL), SUM(unit_id IS NULL) FROM claim_unit_at")[0]
    fp = q("SELECT COUNT(*), COUNT(fingerprint), COUNT(DISTINCT fingerprint) FROM claim")[0]
    dup = q("SELECT COALESCE(SUM(c), 0) FROM (SELECT COUNT(*) c FROM claim WHERE fingerprint IS NOT NULL GROUP BY fingerprint HAVING COUNT(*) > 1)")[0][0]
    record("db",
           rows=rows,
           fingerprints={"claims": fp[0], "with_fingerprint": fp[1], "distinct": fp[2], "claims_sharing_a_fingerprint": dup},
           claims_by_extracted_by=dict(q("SELECT extracted_by, COUNT(*) FROM claim GROUP BY 1")),
           claims_by_type=dict(q("SELECT claim_type, COUNT(*) FROM claim GROUP BY 1")),
           claims_by_status=dict(q("SELECT status, COUNT(*) FROM claim GROUP BY 1")),
           participated={"total": part[0], "event_unlinked": part[1], "unit_unlinked": part[2], "either_unlinked": part[3]},
           unit_at={"total": uat[0], "no_place": uat[1], "no_unit": uat[2]})
    print(f"fingerprints: {fp[1]} of {fp[0]} claims, {fp[2]} distinct, {dup} claims share one with another claim ({100 * dup / max(1, fp[0]):.2f}%)")
    print(f"db metrics: {sum(rows.values())} rows in {len(tables)} tables; participated {part[0]} ({part[1]} without event); "
          f"unit_at {uat[0]} ({uat[1]} without place)")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or paths.defaults("db_metrics")))
