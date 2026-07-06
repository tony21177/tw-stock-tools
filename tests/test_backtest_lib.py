"""backtest_lib 單元測試 — 全部合成資料，不打 API。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_lib as bl


class TestCost(unittest.TestCase):
    def test_default_cost(self):
        # 0.1425*0.6*2 + 0.3 = 0.471
        self.assertAlmostEqual(bl.cost_roundtrip_pct(), 0.471, places=3)

    def test_slippage(self):
        # 加 10bp 單邊滑價 → +0.2%
        self.assertAlmostEqual(
            bl.cost_roundtrip_pct(slippage_bp=10) - bl.cost_roundtrip_pct(), 0.2, places=6)


class TestStats(unittest.TestCase):
    def test_bootstrap_ci_covers_mean(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
        lo, hi = bl.bootstrap_ci(xs, seed=7)
        self.assertLess(lo, 3.0)
        self.assertGreater(hi, 3.0)
        self.assertLess(hi - lo, 1.5)

    def test_bootstrap_deterministic(self):
        xs = [0.5, -1.2, 3.3, 0.1, -0.7, 2.2]
        self.assertEqual(bl.bootstrap_ci(xs, seed=7), bl.bootstrap_ci(xs, seed=7))

    def test_t_stat_zero_mean(self):
        self.assertAlmostEqual(bl.t_stat([-1.0, 1.0, -1.0, 1.0]), 0.0)

    def test_block_bootstrap_runs(self):
        xs = list(range(30))
        lo, hi = bl.block_bootstrap_ci(xs, block=4, seed=7)
        self.assertLess(lo, 14.5)
        self.assertGreater(hi, 14.5)


class TestDedup(unittest.TestCase):
    def test_cooldown(self):
        # 觸發於 5,6,7,30,31,60；cooldown 20 → 5, 30, 60... 30-5=25>20 ✓, 60-30=30>20 ✓
        self.assertEqual(bl.dedup_cooldown([5, 6, 7, 30, 31, 60], 20), [5, 30, 60])

    def test_cooldown_boundary(self):
        # 差距恰等於 cooldown 不放行（需 > cooldown）
        self.assertEqual(bl.dedup_cooldown([0, 20, 21], 20), [0, 21])


class TestSummary(unittest.TestCase):
    def test_summarize_keys(self):
        s = bl.summarize_events([1.0, -2.0, 3.0], [0.5, -1.0, 2.0], cost=0.471)
        for k in ("n", "abs_mean", "exc_mean", "exc_med", "exc_ci", "t",
                  "net", "win", "beat", "cost"):
            self.assertIn(k, s)
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["net"], round(0.5 - 0.471, 2))

    def test_summarize_empty(self):
        self.assertEqual(bl.summarize_events([], [], 0.4), {"n": 0})


if __name__ == "__main__":
    unittest.main()
