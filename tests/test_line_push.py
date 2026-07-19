"""Tests for line_push.py (LINE Messaging API 共用模組)."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import line_push  # noqa: E402


class TestSplitChunks(unittest.TestCase):
    def test_short_single_chunk(self):
        self.assertEqual(line_push.split_chunks("abc"), ["abc"])

    def test_splits_on_paragraphs(self):
        paras = ["p" * 300 for _ in range(5)]
        chunks = line_push.split_chunks("\n\n".join(paras), limit=700)
        self.assertTrue(all(len(c) <= 700 for c in chunks))
        self.assertEqual("".join(chunks).count("p"), 1500)

    def test_oversized_paragraph_hard_split(self):
        chunks = line_push.split_chunks("x" * 1200, limit=500)
        self.assertEqual([len(c) for c in chunks], [500, 500, 200])


class TestPushText(unittest.TestCase):
    def test_batches_of_five_messages(self):
        # 12 chunks → 3 API calls (5+5+2)
        text = "\n\n".join(["y" * 90 for _ in range(12)])
        fake_resp = mock.MagicMock()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        fake_resp.read = lambda: b"{}"
        with mock.patch.object(line_push, "LINE_TEXT_LIMIT", 100), \
             mock.patch.object(line_push.urllib.request, "urlopen",
                               return_value=fake_resp) as uo:
            ok = line_push.push_text(text, "tok", "uid")
        self.assertTrue(ok)
        self.assertEqual(uo.call_count, 3)

    def test_failure_returns_false(self):
        with mock.patch.object(line_push.urllib.request, "urlopen",
                               side_effect=OSError("boom")):
            self.assertFalse(line_push.push_text("hi", "tok", "uid"))


class TestResolveToken(unittest.TestCase):
    def test_static_token_wins(self):
        with mock.patch.dict(os.environ,
                             {"LINE_CHANNEL_TOKEN": "static-tok"}):
            self.assertEqual(line_push.resolve_token(), "static-tok")

    def test_mint_from_id_secret(self):
        env = {"LINE_CHANNEL_TOKEN": "", "LINE_CHANNEL_ID": "123",
               "LINE_CHANNEL_SECRET": "abc"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(line_push, "mint_token",
                               return_value="minted") as mt:
            self.assertEqual(line_push.resolve_token(), "minted")
        mt.assert_called_once_with("123", "abc")

    def test_no_creds_empty(self):
        env = {"LINE_CHANNEL_TOKEN": "", "LINE_CHANNEL_ID": "",
               "LINE_CHANNEL_SECRET": ""}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(line_push.resolve_token(), "")


if __name__ == "__main__":
    unittest.main()
