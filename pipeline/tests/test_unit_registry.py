"""unit_registry.py and score_gold.unit_ids: permanent unit numbers (roadmap T2.2)."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
import score_gold
import unit_registry as U


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name, "unit_ids.tsv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_file_numbers_from_one_in_order_and_saves_header(self):
        r = U.Registry(self.path)
        self.assertEqual([r.id_for("a/1"), r.id_for("nps:X"), r.id_for("a/1")], [1, 2, 1])
        self.assertEqual(r.save(), 2)
        text = self.path.read_text(encoding="utf-8").splitlines()
        self.assertTrue(text[0].startswith("#"))
        self.assertEqual(text[1:], ["a/1\t1", "nps:X\t2"])

    def test_existing_ids_never_change_and_new_ones_follow_the_largest(self):
        U.Registry(self.path)                       # nothing saved yet
        self.path.write_text("# h\nb/2\t7\na/1\t3\n", encoding="utf-8")
        r = U.Registry(self.path)
        self.assertEqual(r.id_for("a/1"), 3)
        self.assertEqual(r.id_for("c/9"), 8)        # after the largest ever issued (7), whatever order the build sees units in
        self.assertEqual(r.id_for("b/2"), 7)
        r.save()
        self.assertEqual(U.Registry(self.path).ids, {"b/2": 7, "a/1": 3, "c/9": 8})

    def test_a_unit_that_left_the_inputs_keeps_its_number_reserved(self):
        self.path.write_text("a/1\t1\nb/2\t2\n", encoding="utf-8")
        r = U.Registry(self.path)
        self.assertEqual(r.id_for("c/3"), 3)        # b/2 was not seen this time, c/3 does not reuse 2
        r.save()
        self.assertIn("b/2\t2", self.path.read_text(encoding="utf-8"))

    def test_save_without_news_leaves_the_file_alone(self):
        self.path.write_text("a/1\t1\n", encoding="utf-8")
        r = U.Registry(self.path)
        r.id_for("a/1")
        self.assertEqual(r.save(), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "a/1\t1\n")

    def test_keys_with_tabs_or_pipes_survive(self):
        r = U.Registry(self.path)
        k = "manual:Union|brigade|3rd Brigade, 2nd Division, XIV Corps"
        r.id_for(k)
        r.save()
        self.assertEqual(U.Registry(self.path).ids[k], 1)

    def test_duplicate_key_or_id_is_refused(self):
        self.path.write_text("a/1\t1\na/1\t2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            U.Registry(self.path)
        self.path.write_text("a/1\t1\nb/2\t1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            U.Registry(self.path)


class GoldKeys(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.execute("CREATE TABLE external_id(entity_type TEXT, entity_id INTEGER, scheme TEXT, value TEXT)")
        self.c.executemany("INSERT INTO external_id VALUES ('unit',?,?,?)", [(10, "dyer", "ohio/021_x"), (11, "nps", "UOH0021RI"), (12, "nps", "UNY0001YAL")])

    def test_keys_win_over_numbers(self):
        head = {"unit_key": "ohio/021_x", "db_unit": "10", "same_as_keys": "nps:UOH0021RI", "same_as": "11"}
        self.assertEqual(score_gold.unit_ids(head, self.c, "t.txt"), [10, 11])

    def test_out_of_date_number_is_reported_and_key_used(self):
        head = {"unit_key": "ohio/021_x", "db_unit": "3"}
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ids = score_gold.unit_ids(head, self.c, "t.txt")
        self.assertEqual(ids, [10])
        self.assertIn("out of date", buf.getvalue())

    def test_numbers_alone_still_work(self):
        self.assertEqual(score_gold.unit_ids({"db_unit": "10", "same_as": "11 12"}, self.c, "t.txt"), [10, 11, 12])

    def test_unknown_key_stops_with_the_file_name(self):
        with self.assertRaises(SystemExit) as cm:
            score_gold.unit_ids({"unit_key": "ohio/999_none"}, self.c, "oh_999.txt")
        self.assertIn("oh_999.txt", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
