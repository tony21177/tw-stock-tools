import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_signal_backtest as bt


class TestForwardReturn(unittest.TestCase):
    CLOSES = {"2308": {"20260701": 100.0, "20260702": 102.0,
                       "20260703": 105.0, "20260704": 108.0,
                       "20260705": 110.0, "20260708": 121.0}}

    def test_forward_return(self):
        # 20260701 收 100 → +3 交易日(20260704) 收 108 → +8%
        r = bt.forward_return(self.CLOSES, "2308", "20260701", 3)
        self.assertAlmostEqual(r, 8.0, places=1)

    def test_insufficient(self):
        self.assertIsNone(bt.forward_return(self.CLOSES, "2308",
                                            "20260708", 5))


class TestEvaluate(unittest.TestCase):
    def _days(self, bull, bear):
        base = [{"date": f"202606{i:02d}", "underlyings":
                 {"2308": {"bull_turnover": 80, "bear_turnover": 20}}}
                for i in range(1, 21)]
        base.append({"date": "20260701", "underlyings":
                     {"2308": {"bull_turnover": bull, "bear_turnover": bear}}})
        return base

    def test_bull_signal_counts_win(self):
        days = self._days(380, 20)   # bull 訊號 on 20260701
        closes = {"2308": {"20260701": 100.0, "20260702": 103.0,
                           "20260703": 106.0, "20260704": 109.0,
                           "20260705": 112.0, "20260708": 115.0}}
        # 每個 signal_date 需要 day_files 前綴 → evaluate 內部逐日切
        res = bt.evaluate(days, closes, horizon=3, surge_min=2.0)
        self.assertEqual(res["bull"]["n"], 1)
        self.assertEqual(res["bull"]["win_rate"], 1.0)  # +9% > 0


class TestSweep(unittest.TestCase):
    def test_sweep_grid(self):
        days = [{"date": f"202606{i:02d}", "underlyings":
                 {"2308": {"bull_turnover": 80, "bear_turnover": 20}}}
                for i in range(1, 21)]
        days.append({"date": "20260701", "underlyings":
                     {"2308": {"bull_turnover": 380, "bear_turnover": 20}}})
        closes = {"2308": {d["date"]: 100.0 + i for i, d in enumerate(days)}}
        grid = bt.sweep(days, closes, horizons=[1, 3],
                        surge_grid=[2.0, 3.0], delta_grid=[0.10])
        # 2 horizons × 2 surge × 1 delta = 4 組
        self.assertEqual(len(grid), 4)
        self.assertTrue(all("bull" in g and "horizon" in g for g in grid))
