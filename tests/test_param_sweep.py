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


class TestSweepSpec(unittest.TestCase):
    """tw_param_sweep.SWEEP_SPEC 完整性測試 — 每參數候選須含現行預設值、
    值須遞增排序、動態算出的 run 數須符合『每參數 (len(值)-1) 加總 +1』公式。"""

    def test_second_wave_defaults_in_candidates(self):
        from tw_second_wave import FILTER_DEFAULTS
        from tw_param_sweep import SWEEP_SPEC
        for param, values in SWEEP_SPEC["second_wave"].items():
            self.assertIn(FILTER_DEFAULTS[param], values,
                          f"second_wave.{param} 候選值缺現行預設 {FILTER_DEFAULTS[param]}")

    def test_turnaround_defaults_in_candidates(self):
        from tw_turnaround_screener import TR_DEFAULTS
        from tw_param_sweep import SWEEP_SPEC
        for param, values in SWEEP_SPEC["turnaround"].items():
            self.assertIn(TR_DEFAULTS[param], values,
                          f"turnaround.{param} 候選值缺現行預設 {TR_DEFAULTS[param]}")

    def test_values_sorted_ascending(self):
        from tw_param_sweep import SWEEP_SPEC
        for strat, params in SWEEP_SPEC.items():
            for param, values in params.items():
                self.assertEqual(values, sorted(values),
                                  f"{strat}.{param} 候選值未遞增排序: {values}")

    def test_planned_run_count_matches_formula(self):
        """N = sum_over_params(len(values) - 1) + 1（預設組共用只跑一次）。
        用公式現算 expected，不寫死數字，驗證 driver 動態算出的 plan_runs() 長度一致。"""
        from tw_param_sweep import SWEEP_SPEC, plan_runs
        for strat, params in SWEEP_SPEC.items():
            expected = sum(len(values) - 1 for values in params.values()) + 1
            actual = len(plan_runs(strat))
            self.assertEqual(actual, expected,
                              f"{strat}: 動態 run 數不符公式 expected={expected} actual={actual}")


if __name__ == "__main__":
    unittest.main()
