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


class TestSplitChunks(unittest.TestCase):
    def test_short_single_chunk(self):
        self.assertEqual(push._split_chunks("abc"), ["abc"])

    def test_splits_on_paragraphs(self):
        paras = ["p" * 300 for _ in range(5)]
        chunks = push._split_chunks("\n\n".join(paras), limit=700)
        self.assertTrue(all(len(c) <= 700 for c in chunks))
        self.assertEqual("".join(chunks).count("p"), 1500)

    def test_oversized_paragraph_hard_split(self):
        chunks = push._split_chunks("x" * 1200, limit=500)
        self.assertEqual([len(c) for c in chunks], [500, 500, 200])


class TestPushLine(unittest.TestCase):
    def test_batches_of_five_messages(self):
        # 12 chunks → 3 API calls (5+5+2)
        text = "\n\n".join(["y" * 90 for _ in range(12)])
        calls = []
        fake_resp = mock.MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        fake_resp.read = lambda: b"{}"
        with mock.patch.object(push, "LINE_TEXT_LIMIT", 100), \
             mock.patch.object(push.urllib.request, "urlopen",
                               return_value=fake_resp) as uo:
            ok = push.push_line(text, "tok", "uid")
        self.assertTrue(ok)
        self.assertEqual(uo.call_count, 3)

    def test_failure_returns_false(self):
        with mock.patch.object(push.urllib.request, "urlopen",
                               side_effect=OSError("boom")):
            self.assertFalse(push.push_line("hi", "tok", "uid"))


class TestWatchlist(unittest.TestCase):
    def test_load(self):
        cfg = push.load_watchlist()
        self.assertIn("codes", cfg)
        self.assertTrue(cfg["codes"])
        self.assertIn(cfg["mode"], ("full", "quick"))


if __name__ == "__main__":
    unittest.main()
