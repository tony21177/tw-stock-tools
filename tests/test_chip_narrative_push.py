"""Tests for concept_momentum/chip_narrative_push.py (LINE 推播)."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import chip_narrative_push as push  # noqa: E402


class TestStripMarkdown(unittest.TestCase):
    def test_bold_and_headers(self):
        src = "## 標題\n**重點**文字 **A** 與 **B**"
        out = push._strip_markdown(src)
        self.assertEqual(out, "標題\n重點文字 A 與 B")


class TestDelegatesToLinePush(unittest.TestCase):
    def test_aliases(self):
        import line_push
        self.assertIs(push._split_chunks, line_push.split_chunks)
        self.assertIs(push.push_line, line_push.push_text)


class TestCacheDataComplete(unittest.TestCase):
    def test_intraday_same_day_incomplete(self):
        # 當日 21:30 前產生 → 融資/借券不全
        self.assertFalse(push._cache_data_complete(
            {"generated_at": "2026-07-20 16:46:18"}, "20260720"))

    def test_same_day_after_cutoff_complete(self):
        self.assertTrue(push._cache_data_complete(
            {"generated_at": "2026-07-20 22:05:00"}, "20260720"))
        self.assertTrue(push._cache_data_complete(
            {"generated_at": "2026-07-20 21:30:00"}, "20260720"))

    def test_next_day_complete(self):
        self.assertTrue(push._cache_data_complete(
            {"generated_at": "2026-07-21 04:43:00"}, "20260720"))

    def test_missing_timestamp_treated_complete(self):
        self.assertTrue(push._cache_data_complete({}, "20260720"))
        self.assertTrue(push._cache_data_complete(
            {"generated_at": "garbage"}, "20260720"))


class TestWatchlist(unittest.TestCase):
    def test_load(self):
        cfg = push.load_watchlist()
        self.assertIn("codes", cfg)
        self.assertTrue(cfg["codes"])
        self.assertIn(cfg["mode"], ("full", "quick"))


if __name__ == "__main__":
    unittest.main()
