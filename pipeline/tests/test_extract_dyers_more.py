"""extract_dyers.py, second set: the year and place rules of the 2026-11-14 addendum."""
import unittest

import _path  # noqa: F401
import extract_dyers as X
from test_extract_dyers import claims_of, find


class TillDateNextYear(unittest.TestCase):
    def test_till_april_after_december_is_next_year(self):
        """72nd NY: 'Battle of Fredericksburg, December 12-15. At Falmouth till April 27.' left all of 1863 in 1862."""
        cl = claims_of("Organized at New York October 10, 1862. SERVICE.— Battle of Fredericksburg, Va., December 12-15. "
                       "At Falmouth till April 27. Moved to Aquia Creek.")
        stay = find(cl, "unit_at", place_mention="Falmouth")
        self.assertEqual([(c["date_start"], c["date_end"]) for c in stay], [("1862-12-15", "1863-04-27")])

    def test_till_a_few_months_back_is_a_stay_inside_the_item_before(self):
        """'Red River Campaign March 23-May 22. At Alexandria till April 12': an earlier month only 1 month back is not next year
        (the rule needs 5 months or more)."""
        cl = claims_of("Organized at Albany January 5, 1864. SERVICE.— Red River Campaign March 23-May 22. At Alexandria till April 12.")
        alex = find(cl, "unit_at", place_mention="Alexandria")
        self.assertTrue(alex and all((c["date_end"] or "").startswith("1864") for c in alex), alex)

    def test_close_month_stays_in_same_year(self):
        """'till June' after 'March' is the same year."""
        cl = claims_of("Organized at Albany January 5, 1862. SERVICE.— Duty at Washington till March 10. Duty at Alexandria till June 2.")
        alex = find(cl, "unit_at", place_mention="Alexandria")
        self.assertTrue(alex and alex[0]["date_end"] == "1862-06-02", alex)


class PrintedYearBefore1861(unittest.TestCase):
    def test_year_1860_ignored(self):
        """'Mustered out July 1, 1860' (Dyer's misprint): the date is read in the run's own year, not 1860."""
        cl = claims_of("Organized at Boston June 1, 1861. Mustered out July 1, 1860. Duty at Washington till June 10, 1861.")
        self.assertFalse([c for c in cl if (c.get("date_start") or "").startswith("1860")])
        out = find(cl, "unit_at", date_start="1861-07-01")
        self.assertEqual([c["place_mention"] for c in out], ["Boston"])


class PlaceTail(unittest.TestCase):
    def test_what_the_unit_did_is_not_the_place(self):
        cases = {
            "Duty at Camp Douglas engaged in guarding prisoners": "Camp Douglas",
            "Duty at Fort Delaware employed as guard": "Fort Delaware",
            "Provost duty at Memphis, Tenn., arriving there": "Memphis, Tenn",
            "Duty at Lookout Mountain building hospitals, running mills": "Lookout Mountain",
        }
        for desc, want in cases.items():
            with self.subTest(desc=desc):
                self.assertEqual(X.place_from(desc), want)

    def test_trailing_and_dropped(self):
        self.assertEqual(X.place_from("Duty at Nashville and"), "Nashville")

    def test_joined_at_takes_the_place_after_at(self):
        """'..., and joined Brigade at Cold Harbor, Va': the place is Cold Harbor."""
        self.assertEqual(X.place_from("Moved to White House and joined Brigade at Cold Harbor, Va"), "Cold Harbor, Va")


class StationedWords(unittest.TestCase):
    def test_stationed_is_a_station_word(self):
        cl = claims_of("Organized at Detroit September, 1862. SERVICE.— Moved to Nashville, Tenn., November 1. "
                       "Stationed at Nashville till July, 1863.")
        st = find(cl, "unit_at", place_mention="Nashville")
        self.assertTrue(any(c["date_end"] == "1863-07" for c in st), st)


class MusteredOutWithoutPlace(unittest.TestCase):
    def test_mustered_out_placed_at_last_place_named(self):
        """2,258 'Mustered out' claims had no place before the rule; the last named place gets it at lower confidence."""
        cl = claims_of("Organized at Detroit September, 1862. SERVICE.— Duty at Camp Douglas till June 20, 1865. Mustered out June 30, 1865.")
        mo = find(cl, "unit_at", date_start="1865-06-30")
        self.assertEqual([c["place_mention"] for c in mo], ["Camp Douglas"])
        self.assertLess(mo[0]["confidence"], 0.8)

    def test_skipped_when_no_place_named_within_60_days(self):
        cl = claims_of("Organized at Detroit September, 1862. SERVICE.— Duty at Camp Douglas till March, 1863. Mustered out June 30, 1865.")
        self.assertEqual(find(cl, "unit_at", date_start="1865-06-30"), [])


class ParseDate(unittest.TestCase):
    def test_range_inside_one_month(self):
        cl = claims_of("Organized at Albany January 5, 1862. SERVICE.— Battle of Antietam, Md., September 16-17.")
        ev = find(cl, "participated", event_mention="Antietam")
        self.assertEqual([(c["date_start"], c["date_end"]) for c in ev], [("1862-09-16", "1862-09-17")])


if __name__ == "__main__":
    unittest.main()
