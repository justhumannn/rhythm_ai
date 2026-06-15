from __future__ import annotations

import unittest

from web_app.bpm import select_canonical_tempo


class BpmSelectionTests(unittest.TestCase):
    def test_promotes_supported_half_time_candidate(self):
        scores = [
            (100.0, 91.0),
            (90.0, 182.0),
            (50.0, 120.0),
        ]

        self.assertEqual(
            select_canonical_tempo(scores, min_bpm=60.0, max_bpm=360.0),
            182.0,
        )

    def test_promotes_supported_one_third_tempo_candidate(self):
        scores = [
            (100.0, 70.0),
            (89.0, 105.0),
            (77.0, 210.0),
            (62.0, 140.0),
        ]

        self.assertEqual(
            select_canonical_tempo(scores, min_bpm=60.0, max_bpm=360.0),
            210.0,
        )

    def test_keeps_slow_tempo_without_harmonic_support(self):
        scores = [
            (100.0, 78.0),
            (60.0, 156.0),
            (55.0, 234.0),
        ]

        self.assertEqual(
            select_canonical_tempo(scores, min_bpm=60.0, max_bpm=360.0),
            78.0,
        )


if __name__ == "__main__":
    unittest.main()
