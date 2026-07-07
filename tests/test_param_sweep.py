#!/usr/bin/env python3
"""參數注入與切窗彙總 — 合成資料，不打 API、不跑全市場。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_lib as bl


class TestSplitByWindow(unittest.TestCase):
    def test_split(self):
        events = [("A", "20250601", 1), ("B", "20260315", 2), ("C", "20260501", 3)]
        w = {"IS": ("20250101", "20260331"), "OOS": ("20260401", "20991231")}
        out = bl.split_by_window(events, w)
        self.assertEqual([e[0] for e in out["IS"]], ["A", "B"])
        self.assertEqual([e[0] for e in out["OOS"]], ["C"])

    def test_boundary_inclusive(self):
        events = [("A", "20260331", 1), ("B", "20260401", 2)]
        w = {"IS": ("20250101", "20260331"), "OOS": ("20260401", "20991231")}
        out = bl.split_by_window(events, w)
        self.assertEqual(len(out["IS"]), 1)
        self.assertEqual(len(out["OOS"]), 1)


class TestParamsOverride(unittest.TestCase):
    def test_second_wave_namespace_merge(self):
        from tw_second_wave import FILTER_DEFAULTS
        merged = {**FILTER_DEFAULTS, **{"drop_min": 0.10}}
        self.assertEqual(merged["drop_min"], 0.10)
        self.assertEqual(merged["drop_max"], FILTER_DEFAULTS["drop_max"])


if __name__ == "__main__":
    unittest.main()
