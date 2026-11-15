"""extract_dyers.py: Dyer's unit text in, claims out. Cases from the 2026-11-12..14 hand-offs and addendum."""
import unittest

import _path  # noqa: F401
import extract_dyers as X


def claims_of(text, uid="test/001_1st_regiment_infantry"):
    unit = {"id": uid, "text": text, "page_start": 1, "page_end": 1, "state": "TEST", "heading": "1st Regiment Infantry",
            "number": 1, "branch": "infantry", "kind": "regiment"}
    return X.extract(unit)


def find(claims, ctype, **kw):
    """Claims of a type whose fields equal kw (a string value matches when it is contained in the field)."""
    out = []
    for c in claims:
        if c["claim_type"] != ctype:
            continue
        if all((v in (c.get(k) or "")) if isinstance(v, str) and k.endswith("_mention") else c.get(k) == v for k, v in kw.items()):
            out.append(c)
    return out


class MonthDotYear(unittest.TestCase):
    def test_pattern_reads_period_as_comma(self):
        """11th NY Cavalry: OCR read the comma in 'March, 1864' as a period (131 places); it must not become a day 18."""
        self.assertEqual(X.MONTH_DOT_YEAR.sub(r"\1, \2", "Ordered to Dept. of the Gulf March. 1864, and duty"),
                         "Ordered to Dept. of the Gulf March, 1864, and duty")

    def test_year_kept_after_march_dot_1864(self):
        """The whole 1864 Gulf service of the 11th NY Cavalry sat in 1863 before the fix."""
        text = ("Organized at New York December, 1861. SERVICE.— Duty in the Defences of Washington, D. C., till March, 1864. "
                "Ordered to Dept. of the Gulf March. 1864, and duty in the District of LaFourche, La., till June. "
                "Action at New River, La., May 15.")
        cl = claims_of(text)
        gulf = find(cl, "unit_at", place_mention="Dept. of the Gulf")
        self.assertTrue(gulf and gulf[0]["date_start"] == "1864-03", gulf)
        riv = find(cl, "participated", event_mention="New River")
        self.assertTrue(riv and riv[0]["date_start"] == "1864-05-15", riv)


class LeftState(unittest.TestCase):
    TEXT = ("Organized at New Haven August 25, 1862. Left State for Washington, D. C., August 28. "
            "SERVICE.— Duty in the Defences of Washington, D. C., till September 17, 1862.")

    def test_departure_dated_at_organization_place(self):
        """'Left State for X, <date>': the day goes to the place the regiment left; the destination is kept undated."""
        cl = claims_of(self.TEXT)
        dep = find(cl, "unit_at", presence="departed")
        self.assertEqual([(c["place_mention"], c["date_start"]) for c in dep], [("New Haven", "1862-08-28")])

    def test_destination_has_no_date(self):
        cl = claims_of(self.TEXT)
        en = find(cl, "unit_at", presence="en_route")
        self.assertEqual([(c["place_mention"], c["date_start"]) for c in en], [("Washington, D. C", None)])


class DatesInOneSentence(unittest.TestCase):
    def test_x_and_y_far_apart_are_two_items(self):
        """'Manning's Plantation June 10 and July 20' is two days, not the range June 10-July 20 (Malvern Hill July 1 and Aug 5)."""
        text = ("Organized at New Orleans April 1, 1864. SERVICE.— Action at New River, La., May 15, 1864. "
                "Manning's Plantation June 10 and July 20. Orange Grove July 31.")
        mp = find(claims_of(text), "participated", event_mention="Manning's Plantation")
        self.assertEqual(sorted((c["date_start"], c["date_end"]) for c in mp),
                         [("1864-06-10", "1864-06-10"), ("1864-07-20", "1864-07-20")])

    def test_till_date_earlier_in_the_year_is_next_year(self):
        """72nd NY: 'At Falmouth till April 27' after December 12-15 ends in April of the NEXT year."""
        text = ("Organized at New York August 1, 1862. SERVICE.— Battle of Fredericksburg, Va., December 12-15. "
                "At Falmouth till April 27. Chancellorsville May 1-5.")
        cl = claims_of(text)
        fal = find(cl, "unit_at", place_mention="Falmouth")
        self.assertEqual([(c["date_start"], c["date_end"]) for c in fal], [("1862-12-15", "1863-04-27")])
        chan = find(cl, "participated", event_mention="Chancellorsville")
        self.assertEqual([c["date_start"] for c in chan], ["1863-05-01"])

    def test_printed_year_before_1861_is_ignored(self):
        """'Mustered out July 1, 1860' (a misprint for 1861): placed at the last place, in 1861."""
        text = ("Organized at Boston June 1, 1861. SERVICE.— Duty at Washington, D. C., till July 1, 1861. "
                "Mustered out July 1, 1860.")
        years = {c["date_start"][:4] for c in claims_of(text) if c.get("date_start")}
        self.assertEqual(years, {"1861"})


class Portions(unittest.TestCase):
    def test_companies_move_is_a_portion(self):
        """'Companies "B" and "G" moved to ...' is a portion (companies), not the whole regiment."""
        text = ('Organized at Boston June 1, 1861. SERVICE.— Companies "B" and "G" moved to Fort Monroe, Va., June 5, 1861. '
                "Battle of Bull Run July 21.")
        cl = claims_of(text)
        fm = find(cl, "unit_at", place_mention="Fort Monroe")
        self.assertEqual([c["portion"] for c in fm], ["companies"])
        bull = find(cl, "participated", event_mention="Bull Run")
        self.assertEqual([c["portion"] for c in bull], ["whole"])


class SentenceSplit(unittest.TestCase):
    def test_split_after_state_abbreviation_when_service_item_starts(self):
        """'Kingston, Ga. March to the sea' is two items; the abbreviation 'Ga.' does not hide the boundary."""
        self.assertEqual(X.split_sentences("Duty at Kingston, Ga. March to the sea November 15-December 10. Siege of Savannah."),
                         ["Duty at Kingston, Ga.", "March to the sea November 15-December 10.", "Siege of Savannah."])


if __name__ == "__main__":
    unittest.main()
