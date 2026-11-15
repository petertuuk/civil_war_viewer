"""extract_state_stations.py: sentences that must not become positions. Pattern level only (the rest sits in main(), roadmap T3.3)."""
import unittest

import _path  # noqa: F401
import extract_state_stations as S


class SkipPattern(unittest.TestCase):
    def test_government_convention_sentences_skipped(self):
        """26th NC: 'the Confederacy of Southern States, organized at Montgomery' is a government, not the regiment."""
        self.assertTrue(S.SKIP.search("The Confederacy of Southern States, organized at Montgomery, was a government."))

    def test_detachments_skipped(self):
        self.assertTrue(S.SKIP.search("Companies A and B were detached to Richmond."))

    def test_regiment_sentence_kept(self):
        self.assertFalse(S.SKIP.search("The regiment camped at Manassas in July."))


if __name__ == "__main__":
    unittest.main()
