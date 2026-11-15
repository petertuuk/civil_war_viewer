"""common.py: distance, speed test, dates, state boxes."""
import unittest
from datetime import date

import _path  # noqa: F401
import common as C


class Distance(unittest.TestCase):
    def test_km_known_pair(self):
        """Washington DC to Richmond VA is about 160 km."""
        self.assertAlmostEqual(C.km((38.9072, -77.0369), (37.5407, -77.4360)), 158, delta=6)

    def test_km_zero_and_symmetric(self):
        a, b = (35.0, -85.0), (36.0, -86.0)
        self.assertEqual(C.km(a, a), 0)
        self.assertAlmostEqual(C.km(a, b), C.km(b, a), places=9)


class SpeedTest(unittest.TestCase):
    def test_too_fast_boundaries(self):
        self.assertFalse(C.too_fast(C.MIN_KM, 0))
        self.assertTrue(C.too_fast(C.MIN_KM + 1, 0))
        self.assertFalse(C.too_fast(C.MAX_KMDAY * 3, 3))
        self.assertTrue(C.too_fast(C.MAX_KMDAY * 3 + 1, 3))

    def test_allowance_widens_the_limit(self):
        d = C.MAX_KMDAY * 2 + 40
        self.assertTrue(C.too_fast(d, 2))
        self.assertFalse(C.too_fast(d, 2, allow_km=50))


class Dates(unittest.TestCase):
    def test_parse_date_precisions(self):
        self.assertEqual(C.parse_date("1863-07-03"), date(1863, 7, 3))
        self.assertEqual(C.parse_date("1863-07"), date(1863, 7, 1))
        self.assertEqual(C.parse_date("1863-07", end=True), date(1863, 7, 31))
        self.assertEqual(C.parse_date("1863-12", end=True), date(1863, 12, 31))
        self.assertEqual(C.parse_date("1864", end=True), date(1864, 12, 31))
        self.assertEqual(C.parse_date("1864-02", end=True), date(1864, 2, 29))

    def test_parse_date_empty(self):
        self.assertIsNone(C.parse_date(None))
        self.assertIsNone(C.parse_date(""))

    def test_day_num_precision(self):
        d, slack = C.day_num("1861-04-12")
        self.assertEqual(slack, 0)
        self.assertEqual(C.day_num("1861-04-13")[0] - d, 1)
        self.assertEqual(C.day_num("1861-04")[1], 15)
        self.assertEqual(C.day_num("1861")[1], 180)
        self.assertEqual(C.day_num(None), (None, 0))

    def test_first_day(self):
        self.assertEqual(C.first_day("1862-09"), date(1862, 9, 1))
        self.assertEqual(C.first_day("1862-09-17"), date(1862, 9, 17))
        self.assertIsNone(C.first_day(None))
        self.assertIsNone(C.first_day("1862"))


class StateBoxes(unittest.TestCase):
    def test_in_state(self):
        self.assertTrue(C.in_state("TN", 36.16, -86.78))        # Nashville
        self.assertFalse(C.in_state("TN", 38.9, -77.0))         # Washington
        self.assertIsNone(C.in_state("TN", None, -86.0))

    def test_va_and_wv_count_as_one(self):
        self.assertTrue(C.in_state("VA", 39.27, -80.34))        # Grafton, WV
        self.assertTrue(C.in_state("WV", 37.5, -77.4))          # Richmond, VA

    def test_unknown_state_is_none(self):
        self.assertIsNone(C.in_state("ZZ", 36.0, -86.0))


class StableIds(unittest.TestCase):
    def test_same_parts_same_id_and_prefix_and_length(self):
        a = C.stable_id("ev", "Battle of X", "1862-04-06")
        self.assertEqual(a, C.stable_id("ev", "Battle of X", "1862-04-06"))
        self.assertTrue(a.startswith("ev") and len(a) == 2 + 8)
        self.assertEqual(len(C.stable_id("ev", "a", n=12)), 2 + 12)

    def test_different_parts_different_id_and_order_matters(self):
        self.assertNotEqual(C.stable_id("ev", "a", "b"), C.stable_id("ev", "b", "a"))
        self.assertNotEqual(C.stable_id("ev", "a", "b"), C.stable_id("ev", "a", "c"))

    def test_none_counts_as_empty_but_position_is_kept(self):
        self.assertEqual(C.stable_id("x", "a", None), C.stable_id("x", "a", ""))
        self.assertNotEqual(C.stable_id("x", "a", None, "b"), C.stable_id("x", "a", "b", None))

    def test_known_value(self):
        """Pins the algorithm: sha1 of the parts joined by '|'. Changing it would renumber every id."""
        self.assertEqual(C.stable_id("c", "a", "b", n=8), "c" + __import__("hashlib").sha1(b"a|b").hexdigest()[:8])


class ClaimFingerprint(unittest.TestCase):
    base = dict(extracted_by="regex:or_org_v1", unit_key="us-3-co-cav", claim_type="participated", date_start="1862-04-06",
                locator="p. 12", span="Company G, 3d Colorado Cavalry", obj="Shiloh")

    def fp(self, **kw):
        a = dict(self.base); a.update(kw)
        return C.claim_fingerprint(a["extracted_by"], a["unit_key"], a["claim_type"], a["date_start"], a["locator"], a["span"], a["obj"])

    def test_stable(self):
        self.assertEqual(self.fp(), self.fp())
        self.assertEqual(len(self.fp()), 1 + 12)

    def test_every_part_matters(self):
        base = self.fp()
        for k, v in (("extracted_by", "x"), ("unit_key", "x"), ("claim_type", "commanded"), ("date_start", "1862-04-07"),
                     ("locator", "p. 13"), ("span", "other words"), ("obj", "Corinth")):
            self.assertNotEqual(base, self.fp(**{k: v}), k)

    def test_span_counts_only_its_first_80_characters(self):
        long = "x" * 80
        self.assertEqual(self.fp(span=long + "AAA"), self.fp(span=long + "BBB"))
        self.assertNotEqual(self.fp(span="y" + long), self.fp(span="z" + long))
        self.assertNotEqual(self.fp(span="x" * 79 + "A"), self.fp(span="x" * 79 + "B"))   # the 80th character still counts

    def test_none_span_and_obj_allowed(self):
        self.assertEqual(self.fp(span=None, obj=None), self.fp(span="", obj=""))


if __name__ == "__main__":
    unittest.main()
