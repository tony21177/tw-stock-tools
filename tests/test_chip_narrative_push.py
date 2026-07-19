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


class TestWatchlist(unittest.TestCase):
    def test_load(self):
        cfg = push.load_watchlist()
        self.assertIn("codes", cfg)
        self.assertTrue(cfg["codes"])
        self.assertIn(cfg["mode"], ("full", "quick"))


if __name__ == "__main__":
    unittest.main()
