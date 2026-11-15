"""cwv/states.py: the table builder, the master names, and every table the scripts build from it."""
import ast
import unittest
from pathlib import Path

import _path  # noqa: F401
from cwv import states

PIPELINE = Path(__file__).resolve().parents[1]


def table_calls():
    """(script, variable, Call node) for every `X = cwv_states.table(...)` in the pipeline scripts."""
    out = []
    for f in sorted(PIPELINE.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                    and n.value.func.attr == "table" and getattr(n.value.func.value, "id", "") == "cwv_states"):
                out.append((f.name, n.targets[0].id, n.value))
    return out


class Master(unittest.TestCase):
    def test_codes_and_names_are_unique(self):
        self.assertEqual(len(set(states.NAME.values())), len(states.NAME))
        self.assertTrue(all(len(c) == 2 and c.isupper() for c in states.NAME))

    def test_known_entries(self):
        self.assertEqual(states.NAME["DC"], "District of Columbia")
        self.assertEqual(states.NAME["DT"], "Dakota")
        self.assertEqual(states.NAME["IT"], "Indian Territory")
        self.assertEqual(states.NAME["WV"], "West Virginia")
        self.assertEqual(len(states.NAME), 51)


class Table(unittest.TestCase):
    def test_spellings(self):
        self.assertEqual(states.table("Name", "CODE", "NC"), {"North Carolina": "NC"})
        self.assertEqual(states.table("NAME", "CODE", "NC"), {"NORTH CAROLINA": "NC"})
        self.assertEqual(states.table("name", "CODE", "NC"), {"north carolina": "NC"})
        self.assertEqual(states.table("snake", "CODE", "NC"), {"north_carolina": "NC"})
        self.assertEqual(states.table("CODE", "Name", "NC"), {"NC": "North Carolina"})
        self.assertEqual(states.table("code", "NAME", "NC"), {"nc": "NORTH CAROLINA"})

    def test_order_is_the_order_given(self):
        self.assertEqual(list(states.table("Name", "CODE", "WV", "VA", "AL")), ["West Virginia", "Virginia", "Alabama"])

    def test_literal_pairs_stay_in_place(self):
        t = states.table("Name", "CODE", "AL", ("Indian Territory", "OK"), "AR")
        self.assertEqual(list(t.items()), [("Alabama", "AL"), ("Indian Territory", "OK"), ("Arkansas", "AR")])

    def test_unknown_code_is_an_error(self):
        with self.assertRaises(KeyError):
            states.table("Name", "CODE", "ZZ")


class ScriptTables(unittest.TestCase):
    def test_the_scripts_use_it(self):
        found = {(s, v) for s, v, _ in table_calls()}
        self.assertGreaterEqual(len(found), 16)
        self.assertIn(("gnis_index.py", "STATES"), found)
        self.assertIn(("build_db.py", "ST"), found)

    def test_every_table_builds_and_has_no_repeated_entry(self):
        for script, var, call in table_calls():
            with self.subTest(script=script, var=var):
                args = [a.value if isinstance(a, ast.Constant) else ast.literal_eval(a) for a in call.args]
                built = states.table(*args)
                self.assertGreater(len(built), 5)
                codes = [a for a in args[2:] if isinstance(a, str)]
                self.assertEqual(len(codes), len(set(codes)), "a state is listed twice")

    def test_known_disagreements_are_kept(self):
        """Dakota is DT for Dyer's and SD for the mention resolver; these are source decisions, see states.py."""
        tabs = {(s, v): states.table(*[ast.literal_eval(a) for a in c.args]) for s, v, c in table_calls()}
        self.assertEqual(tabs[("build_db.py", "ST")]["DAKOTA"], "DT")
        self.assertEqual(tabs[("resolve_mentions.py", "HOME")]["dakota"], "SD")
        self.assertEqual(tabs[("extract_nps_histories.py", "STATES")]["Indian Territory"], "OK")
        self.assertEqual(tabs[("places_inventory.py", "FULL")]["indian territory"], "IT")
        self.assertEqual(tabs[("or_stations.py", "STATE_WORDS")]["Washington"], "DC")
        self.assertEqual(tabs[("gnis_index.py", "STATES")]["Washington"], "WA")


if __name__ == "__main__":
    unittest.main()
