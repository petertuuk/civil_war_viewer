"""refcheck.py: stale generated files are caught before the database is built (roadmap T2.3)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import refcheck as R

NAMES = ["Battle of Shiloh", "Siege of Vicksburg", "Battle of Antietam", "Battle of Gettysburg", "Battle of Chickamauga",
         "Battle of Fredericksburg", "Battle of Chancellorsville", "Battle of Stones River"]


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class Project:
    """A tiny project folder: events ev00000.., an OR claim file with 30 rows that name their event."""

    def __init__(self, tmp, shift=0, drop_events=()):
        self.P = Path(tmp)
        events = [dict(event_id=f"ev{i:05d}", name=n) for i, n in enumerate(NAMES)]
        write_jsonl(self.P / "data/events/events.jsonl", events)
        # the OR file was made for the original numbering; shift = how far the events moved since
        rows = []
        for k in range(30):
            i = k % len(NAMES)
            rows.append(dict(claim_type="participated", event_id=f"ev{i:05d}", event_mention=NAMES[i].replace("Battle of ", "")))
        write_jsonl(self.P / "data/or/claims_or.jsonl", rows)
        if shift or drop_events:
            moved = [dict(e, event_id=f"ev{(int(e['event_id'][2:]) + shift) % len(NAMES):05d}") for e in events if e["event_id"] not in drop_events]
            write_jsonl(self.P / "data/events/events.jsonl", moved)


class RefCheck(unittest.TestCase):
    def run_check(self, **kw):
        with tempfile.TemporaryDirectory() as t:
            Project(t, **kw)
            lines = []
            ok = R.run(t, say=lines.append)
            res, _ = R.check(t)
            return ok, "\n".join(lines), res

    def test_consistent_project_passes(self):
        ok, out, res = self.run_check()
        self.assertTrue(ok, out)
        self.assertEqual(res[0]["missing"], 0)
        self.assertEqual(res[0]["disagree"], 0)

    def test_ids_moved_by_one_fail_and_name_the_stage(self):
        """One event more or fewer upstream moves every later id: the OR file's rows now point at other events."""
        ok, out, res = self.run_check(shift=1)
        self.assertFalse(ok)
        self.assertIn("STALE", out)
        self.assertIn("data/or/claims_or.jsonl  -> stage or", out)

    def test_id_missing_from_events_fails(self):
        ok, out, res = self.run_check(drop_events={"ev00007"})
        self.assertFalse(ok)
        self.assertEqual(res[0]["missing"], 3)          # 30 rows with ids 0-7 in turn: ev00007 appears in rows 7, 15 and 23
        self.assertIn("missing", out)

    def test_alias_names_are_tolerated(self):
        """A few rows whose text uses another name for the event (Ox Hill / Chantilly) are not a stale file."""
        with tempfile.TemporaryDirectory() as t:
            Project(t)
            rows = [json.loads(l) for l in (Path(t) / "data/or/claims_or.jsonl").read_text().splitlines()]
            rows[0]["event_mention"] = "Sharpsburg"            # 1 of 30 rows disagrees (3%): under the 5% limit
            write_jsonl(Path(t) / "data/or/claims_or.jsonl", rows)
            self.assertTrue(R.run(t, say=lambda s: None))

    def test_a_fifth_of_rows_disagreeing_is_stale(self):
        with tempfile.TemporaryDirectory() as t:
            Project(t)
            rows = [json.loads(l) for l in (Path(t) / "data/or/claims_or.jsonl").read_text().splitlines()]
            for r in rows[:6]:
                r["event_mention"] = "Sharpsburg"              # 6 of 30 (20%) are over the 5% limit
            write_jsonl(Path(t) / "data/or/claims_or.jsonl", rows)
            self.assertFalse(R.run(t, say=lambda s: None))

    def test_allow_lets_a_stale_build_go_on(self):
        with tempfile.TemporaryDirectory() as t:
            Project(t, shift=1)
            lines = []
            self.assertTrue(R.run(t, allow=True, say=lines.append))
            self.assertIn("CWV_ALLOW_STALE=1", "\n".join(lines))

    def test_words_ignore_generic_terms(self):
        self.assertFalse(R.words("Battle of the Campaign"))
        self.assertTrue(R.agrees("Shiloh", dict(name="Battle of Shiloh")))
        self.assertTrue(R.agrees("Ox Hill", dict(name="Battle of Chantilly", dyer_name="Ox Hill, Va")))
        self.assertFalse(R.agrees("Shiloh", dict(name="Siege of Vicksburg")))


if __name__ == "__main__":
    unittest.main()
