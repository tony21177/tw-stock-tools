"""Tests for chip_cache_builder — 動態分點快取清單 (offline)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import chip_cache_builder as b  # noqa: E402


class TestBuildUniverse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        # concepts.json
        concepts = {"_meta": {}, "themes": {
            "AI": {"name_zh": "AI", "stocks": ["2330", "2454", "3711"]},
            "PCB": {"name_zh": "PCB", "stocks": ["2313", "3037"]}}}
        with open(os.path.join(d, "concepts.json"), "w") as f:
            json.dump(concepts, f)
        # second_wave dir
        swdir = os.path.join(d, "sw")
        os.makedirs(swdir)
        with open(os.path.join(swdir, "20260720.json"), "w") as f:
            json.dump({"candidates": [{"code": "6517"}, {"code": "2313"}]}, f)
        # watchlist
        with open(os.path.join(d, "watch.json"), "w") as f:
            json.dump({"codes": ["2313", "3491", "6488"]}, f)
        self._orig = (b.CONCEPTS, b.SECOND_WAVE_DIR, b.WATCHLIST)
        b.CONCEPTS = os.path.join(d, "concepts.json")
        b.SECOND_WAVE_DIR = swdir
        b.WATCHLIST = os.path.join(d, "watch.json")

    def tearDown(self):
        b.CONCEPTS, b.SECOND_WAVE_DIR, b.WATCHLIST = self._orig
        self.tmp.cleanup()

    def test_union_and_sources(self):
        uni = b.build_universe(token="", hot_n=0)   # 無 token → 無熱門
        self.assertEqual(uni["counts"]["族群"], 5)
        self.assertEqual(uni["counts"]["強勢"], 2)
        self.assertEqual(uni["counts"]["watch"], 3)
        # union dedupe: 2330,2454,3711,2313,3037,6517,3491,6488 = 8
        self.assertEqual(len(uni["codes"]), 8)
        # 2313 出現在族群+強勢+watch 三處
        self.assertEqual(set(uni["sources"]["2313"]), {"族群", "強勢", "watch"})
        # 6488 只在 watch
        self.assertEqual(uni["sources"]["6488"], ["watch"])

    def test_hot_excludes_etf_and_ranks(self):
        rows = [
            {"stock_id": "2330", "date": "2026-07-20", "Trading_money": 9e10},
            {"stock_id": "0050", "date": "2026-07-20", "Trading_money": 8e10},
            {"stock_id": "2303", "date": "2026-07-20", "Trading_money": 5e10},
            {"stock_id": "12345", "date": "2026-07-20", "Trading_money": 4e10},
        ]
        with mock.patch.object(b, "datetime") as dt:
            dt.now.return_value.strftime.return_value = "2026-07-20"
            with mock.patch("finmind_client._call", return_value=rows,
                            create=True):
                import finmind_client
                with mock.patch.object(finmind_client, "_call",
                                       return_value=rows):
                    hot = b._hot_codes("tok", 5)
        # 0050(ETF) 與 12345(5位數) 排除，剩 2330/2303
        self.assertEqual(hot, {"2330", "2303"})


class TestCachedToday(unittest.TestCase):
    def test_cached_detection(self):
        with tempfile.TemporaryDirectory() as d:
            orig = b.BSR_CACHE
            b.BSR_CACHE = d
            try:
                self.assertFalse(b._cached_today("2313", "20260721"))
                open(os.path.join(d, "2313_20260721_prices.json"), "w").close()
                self.assertTrue(b._cached_today("2313", "20260721"))
            finally:
                b.BSR_CACHE = orig


if __name__ == "__main__":
    unittest.main()
