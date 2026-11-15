"""fix_years.py: year corrections. Cases from the 2026-11-14 hand-off and addendum."""
import unittest
from collections import Counter, defaultdict
from datetime import date

import _path  # noqa: F401
import fix_years as F
from anchor_events import words_of


def wikidata(*events):
    """events: (label, lo, hi) -> (wd, index) as fix_years.main builds them."""
    wd = [{"label": l, "lo": lo, "hi": hi, "words": words_of(l), "classes": set()} for l, lo, hi in events]
    index = defaultdict(set)
    for i, e in enumerate(wd):
        for x in e["words"]:
            index[x].add(i)
    return wd, index


def claim(mention, d0, d1, span):
    return {"unit_id": "u", "claim_type": "participated", "event_mention": mention, "date_start": d0, "date_end": d1,
            "source_span": span, "confidence": 0.8}


class Misprints(unittest.TestCase):
    def fixture(self, with_wikidata=True):
        claims = [
            claim("Battle of Fredericksburg", "1862-12-12", "1862-12-15", "Battle of Fredericksburg December 12-15"),
            claim('Burnside\'s 2nd Campaign, "Mud March,"', "1865-01-20", "1865-01-24",
                  'Burnside\'s 2nd Campaign, "Mud March," January 20-24, 1865'),
            claim("Siege of Suffolk", "1865-04-12", "1865-05-04", "Siege of Suffolk April 12-May 4"),
            claim("Gettysburg", "1863-07-01", "1863-07-03", "Gettysburg July 1-3, 1863"),
        ]
        wd, index = wikidata(*([("Siege of Suffolk", date(1863, 4, 11), date(1863, 5, 4))] if with_wikidata else []))
        return claims, wd, index

    def test_mud_march_printed_1865_moves_to_1863(self):
        """15th Connecticut: the Mud March is printed 1865 in Dyer's itself; the stretch moves by -2 when Wikidata agrees."""
        claims, wd, index = self.fixture()
        segs, log = Counter(), []
        F.misprints("u", [0, 1, 2, 3], claims, wd, index, set(), segs, log)
        self.assertEqual([(c["date_start"], c["date_end"]) for c in claims],
                         [("1862-12-12", "1862-12-15"), ("1863-01-20", "1863-01-24"), ("1863-04-12", "1863-05-04"),
                          ("1863-07-01", "1863-07-03")])
        self.assertEqual(segs["misprinted year corrected"], 1)

    def test_nothing_moves_without_wikidata_agreement(self):
        """No Wikidata vote for the stretch: an out-of-order printed year alone is left for review, not corrected."""
        claims, wd, index = self.fixture(with_wikidata=False)
        before = [dict(c) for c in claims]
        segs, log = Counter(), []
        F.misprints("u", [0, 1, 2, 3], claims, wd, index, set(), segs, log)
        self.assertEqual(claims, before)
        self.assertEqual(segs["misprinted year corrected"], 0)


class NotAction(unittest.TestCase):
    def test_district_of_baton_rouge_is_duty_not_a_battle(self):
        """11th NY Cavalry: 'in the District of Baton Rouge' voted for the 1862 battle; it is a posting."""
        for m in ("in the District of Baton Rouge", "in the Defences of Washington", "Duty at Memphis"):
            self.assertTrue(F.NOT_ACTION.match(m), m)

    def test_real_actions_still_vote(self):
        for m in ("Battle of Fredericksburg", "Siege of Suffolk", "Gettysburg"):
            self.assertFalse(F.NOT_ACTION.match(m), m)


if __name__ == "__main__":
    unittest.main()
