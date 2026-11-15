"""The comparison and metrics tools and review_import's guard, run as the command line runs them, on small made-up folders."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PIPE = Path(__file__).resolve().parent.parent


def run(script, *args, cwd=None, env=None):
    e = dict(os.environ, **(env or {}))
    p = subprocess.run([sys.executable, str(PIPE / script), *map(str, args)], capture_output=True, text=True, cwd=cwd, env=e)
    return p.returncode, p.stdout + p.stderr


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_db(path, claim_rows, stamp="2026-01-01T00:00:00"):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE claim (id INTEGER PRIMARY KEY, text TEXT, extracted_at TEXT)")
    con.execute("CREATE TABLE source (id INTEGER PRIMARY KEY, title TEXT, fetched_at TEXT)")
    con.execute("CREATE TABLE override (id INTEGER PRIMARY KEY, why TEXT, created_at TEXT)")
    con.executemany("INSERT INTO claim VALUES (?,?,?)", [(i, t, stamp) for i, t in claim_rows])
    con.execute("INSERT INTO source VALUES (1,'Dyer', ?)", (stamp,))
    con.execute("INSERT INTO override VALUES (1,'moved', ?)", (stamp,))
    con.commit()
    con.close()


class CompareBuilds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ref, self.new = Path(self.tmp.name, "ref"), Path(self.tmp.name, "new")
        for d in (self.ref, self.new):
            write(d / "data/events/events.jsonl", '{"a": 1}\n{"a": 2}\n')
            write(d / "viewer/war/data/units.json", "{}")
            make_db(d / "civil_war.db", [(1, "x"), (2, "y")])

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_builds_exit_zero(self):
        code, out = run("compare_builds.py", self.ref, self.new)
        self.assertEqual(code, 0, out)
        self.assertIn("IDENTICAL", out)

    def test_changed_file_is_named_and_exits_one(self):
        write(self.new / "data/events/events.jsonl", '{"a": 1}\n{"a": 3}\n')
        code, out = run("compare_builds.py", self.ref, self.new)
        self.assertEqual(code, 1)
        self.assertIn("data/events/events.jsonl", out)
        self.assertIn('"a": 3', out)

    def test_extra_and_missing_files(self):
        write(self.new / "data/scores/extra.txt", "x")
        (self.ref / "viewer/war/data/units.json").unlink()
        code, out = run("compare_builds.py", self.ref, self.new, "--files-only")
        self.assertEqual(code, 1)
        self.assertIn("only in new: data/scores/extra.txt", out)
        self.assertIn("only in new: viewer/war/data/units.json", out)

    def test_database_time_stamps_are_ignored(self):
        make_db(self.new / "civil_war.db.tmp", [(1, "x"), (2, "y")], stamp="2030-05-05T10:00:00")
        os.replace(self.new / "civil_war.db.tmp", self.new / "civil_war.db")
        code, out = run("compare_builds.py", self.ref, self.new, "--db-only")
        self.assertEqual(code, 0, out)

    def test_database_row_difference_is_found(self):
        os.remove(self.new / "civil_war.db")
        make_db(self.new / "civil_war.db", [(1, "x"), (2, "CHANGED")])
        code, out = run("compare_builds.py", self.ref, self.new, "--db-only")
        self.assertEqual(code, 1)
        self.assertIn("claim", out)
        self.assertIn("differ", out)

    def test_external_and_review_images_are_skipped(self):
        write(self.new / "data/external/gnis/big.tsv", "changed")
        write(self.new / "data/review/img/card1.png", "changed")
        code, out = run("compare_builds.py", self.ref, self.new, "--files-only")
        self.assertEqual(code, 0, out)


class ClaimsDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a, self.b = Path(self.tmp.name, "a.jsonl"), Path(self.tmp.name, "b.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def claim(unit="u1", mention="Nashville", d0="1863-01-01", d1="1863-02-01", **kw):
        return dict(unit_id=unit, claim_type="unit_at", place_mention=mention, date_start=d0, date_end=d1, source_span="Duty at " + mention,
                    extracted_at="now", **kw)

    def dump(self, path, rows):
        write(path, "".join(json.dumps(r) + "\n" for r in rows))

    def test_identical_exit_zero_and_ignored_fields(self):
        self.dump(self.a, [self.claim()])
        self.dump(self.b, [dict(self.claim(), extracted_at="later", note="n")])
        code, out = run("claims_diff.py", self.a, self.b)
        self.assertEqual(code, 0, out)

    def test_added_removed_changed(self):
        self.dump(self.a, [self.claim(), self.claim("u2", "Memphis")])
        self.dump(self.b, [self.claim(d1="1863-03-01"), self.claim("u3", "Atlanta")])
        code, out = run("claims_diff.py", self.a, self.b)
        self.assertEqual(code, 1)
        self.assertIn("u1", out)
        self.assertIn("date_end", out)          # the changed field
        self.assertIn("u2", out)                # removed
        self.assertIn("u3", out)                # added

    def test_units_filter(self):
        self.dump(self.a, [self.claim("keep1"), self.claim("other")])
        self.dump(self.b, [self.claim("keep1", d1="1863-09-09"), self.claim("other", d1="1863-09-09")])
        code, out = run("claims_diff.py", self.a, self.b, "--units", "keep")
        self.assertIn("keep1", out)
        self.assertNotIn("other", out)

    def test_reads_derived_json_format(self):
        c = {"type": "unit_at", "place_mention": "Atlanta", "date_start": "1864-07-01", "span": "x", "unit": {"nps_code": "CTN0001RI01"}}
        write(self.a, json.dumps({"claims": [c]}))
        write(self.b, json.dumps({"claims": [dict(c, date_end="1864-08-01")]}))
        self.a, self.b = self.a.rename(self.a.with_suffix(".json")), self.b.rename(self.b.with_suffix(".json"))
        code, out = run("claims_diff.py", self.a, self.b)
        self.assertEqual(code, 1)
        self.assertIn("CTN0001RI01", out)


class Metrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ref, self.new = Path(self.tmp.name, "ref"), Path(self.tmp.name, "new")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, root, script, obj):
        write(Path(root, "data/scores/metrics", script + ".json"), json.dumps(obj))

    def test_record_writes_sorted_json_and_never_raises(self):
        sys.path.insert(0, str(PIPE))
        try:
            import metrics
            d = Path(self.tmp.name, "m")
            os.environ["CWV_METRICS_DIR"] = str(d)
            metrics.record("demo", b=2, a={"y": 1, "x": 0})
            self.assertEqual(json.loads((d / "demo.json").read_text()), {"a": {"x": 0, "y": 1}, "b": 2})
            self.assertLess((d / "demo.json").read_text().index('"a"'), (d / "demo.json").read_text().index('"b"'))
            os.environ["CWV_METRICS_DIR"] = "/proc/definitely/not/writable"
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                metrics.record("demo", a=1)                     # prints a note, does not raise
            self.assertIn("not written", buf.getvalue())
        finally:
            os.environ.pop("CWV_METRICS_DIR", None)

    def test_diff_identical_exit_zero(self):
        for r in (self.ref, self.new):
            self.put(r, "fast_jumps", {"stats": {"fast jumps": 805}})
        code, out = run("metrics_diff.py", self.ref, self.new)
        self.assertEqual(code, 0, out)

    def test_diff_flags_tripwire(self):
        self.put(self.ref, "fast_jumps", {"stats": {"fast jumps": 805}, "rows": 5})
        self.put(self.new, "fast_jumps", {"stats": {"fast jumps": 812}, "rows": 6})
        code, out = run("metrics_diff.py", self.ref, self.new)
        self.assertEqual(code, 1)
        trip = [l for l in out.splitlines() if "fast jumps" in l]
        self.assertTrue(trip and trip[0].startswith("TRIPWIRE"), out)
        self.assertIn("(+7)", trip[0])
        rows = [l for l in out.splitlines() if "fast_jumps.rows" in l]
        self.assertFalse(rows[0].startswith("TRIPWIRE"))

    def test_diff_reports_one_sided_metrics(self):
        self.put(self.ref, "a", {"n": 1})
        self.put(self.new, "a", {"n": 1, "m": 2})
        code, out = run("metrics_diff.py", self.ref, self.new)
        self.assertEqual(code, 1)
        self.assertIn("only in new: a.m", out)

    def test_diff_without_metrics_exits_two(self):
        code, out = run("metrics_diff.py", self.ref, self.new)
        self.assertEqual(code, 2)


class ReviewImportGuard(unittest.TestCase):
    ANSWERS = [
        {"case_id": "c1", "kind": "year", "unit_id": "u1", "mention": "Battle of X", "date": "1862-05-01", "shift": 1, "answer": "shift", "at": "t"},
        {"case_id": "c2", "kind": "year", "unit_id": "u2", "mention": "Battle of Y", "date": "1862-06-01", "shift": -1, "answer": "keep", "at": "t"},
        {"case_id": "c3", "kind": "ocr", "unit_id": "u3", "ocr": "Aug", "before": "left on the", "printed": "Aug", "answer": "reading", "at": "t"},
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data/dyers").mkdir(parents=True)
        self.dec = self.root / "decisions.jsonl"
        write(self.dec, "".join(json.dumps(a) + "\n" for a in self.ANSWERS))

    def tearDown(self):
        self.tmp.cleanup()

    def files(self):
        return {p.name: p.read_bytes() for p in (self.root / "data/dyers").glob("*.jsonl")}

    def test_full_input_imports_and_is_stable(self):
        code, out = run("review_import.py", self.dec, self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("withdrawn 0", out)
        first = self.files()
        code, out = run("review_import.py", self.dec, self.root)
        self.assertEqual((code, self.files()), (0, first))

    def test_incomplete_input_is_refused_and_writes_nothing(self):
        run("review_import.py", self.dec, self.root)
        before = self.files()
        short = self.root / "short.jsonl"
        write(short, json.dumps(self.ANSWERS[0]) + "\n")
        code, out = run("review_import.py", short, self.root)
        self.assertEqual(code, 1)
        self.assertIn("c2", out)
        self.assertIn("c3", out)
        self.assertNotIn("c1\n", out.split("case ids:")[-1])
        self.assertEqual(self.files(), before)

    def test_allow_withdraw_drops_them(self):
        run("review_import.py", self.dec, self.root)
        short = self.root / "short.jsonl"
        write(short, json.dumps(self.ANSWERS[0]) + "\n")
        code, out = run("review_import.py", short, self.root, "--allow-withdraw")
        self.assertEqual(code, 0, out)
        self.assertIn("withdrawn 2", out)
        years = [json.loads(l) for l in (self.root / "data/dyers/year_decisions.jsonl").read_text().splitlines()]
        self.assertEqual([y["case_id"] for y in years], ["c1"])

    def test_cant_tell_is_not_a_decision(self):
        write(self.dec, json.dumps(dict(self.ANSWERS[0], answer="cant_tell")) + "\n")
        code, out = run("review_import.py", self.dec, self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("can't tell 1", out)


if __name__ == "__main__":
    unittest.main()
