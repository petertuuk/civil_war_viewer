"""Official Records parsing: or_datelines.py and parse_or_organization.py. Cases from the 2026-11-14 addendum."""
import unittest

import _path  # noqa: F401
import or_datelines as O
import parse_or_organization as P


class Ordinals(unittest.TestCase):
    def test_ocr_damaged_twenty_first(self):
        """'Twenty -first' / 'Twenty;first' read as 21: the 21st Corps' headquarters at Manchester, Tenn. had put the First Corps'
        24th Michigan in Tennessee."""
        for t in ("Twenty -first", "Twenty;first", "Twenty-first", "twenty first"):
            self.assertEqual(O.ordnum(t), 21, t)

    def test_plain_ordinals(self):
        for t, n in (("Third", 3), ("3d", 3), ("Fourth", 4), ("Twenty-fourth", 24), ("One hundred and twenty-fourth", 124),
                     ("XII Corps", 12), ("Thied", 3)):
            self.assertEqual(O.ordnum(t), n, t)


class RunningHeads(unittest.TestCase):
    def test_chap_running_head_dropped(self):
        """'[Chap. XXX VII. ]' glued itself to a battery line and swallowed 'SECOND ARMY CORPS.'; it must disappear."""
        out = P.join_wrapped(["[Chap. XXX VII. ]", "FIRST ARMY CORPS.", "Maj. Gen. JOHN F. REYNOLDS."])
        self.assertEqual(out, ["FIRST ARMY CORPS.", "Maj. Gen. JOHN F. REYNOLDS."])

    def test_chap_running_head_does_not_glue_to_officer_line(self):
        """The real failure: a head without its '[' after a wrapped officer line ('Capt. T.') was joined to it as the rest
        of the name. Only the explicit Chap rule in join_wrapped stops that (checked by disabling the rule)."""
        out = P.join_wrapped(["Letcher Artillery, Capt. T.", "Chap. XXX VII. ]", "A. Brander."])
        self.assertEqual(out, ["Letcher Artillery, Capt. T. A. Brander."])

    def test_header_ocr_junk_cleaned(self):
        """'FOURTH ARMY" CORPS.g' (stray quote and letter) is read as the header 'FOURTH ARMY CORPS.'."""
        self.assertEqual(P.join_wrapped(["FOURTH ARMY\" CORPS.g"]), ["FOURTH ARMY CORPS."])


if __name__ == "__main__":
    unittest.main()
