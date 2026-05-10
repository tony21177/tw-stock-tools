import unittest
from concept_momentum.market_breadth import compute_breadth_for_day


def _make_history(closes_per_day: list[list[float]]) -> dict:
    """Build {code: [close_t-N, ..., close_t]} from per-day rows.

    closes_per_day[i] = list of stock closes on day i (oldest first).
    All days must have same number of stocks.
    """
    n_stocks = len(closes_per_day[0])
    return {
        f"{1000 + i:04d}": [day[i] for day in closes_per_day]
        for i in range(n_stocks)
    }


class TestComputeBreadth(unittest.TestCase):
    def test_simple_uptrend_breadth(self):
        # 3 stocks, 21 days history. All rising linearly → all above 20MA.
        closes_per_day = [[10.0 + i, 20.0 + i, 30.0 + i] for i in range(21)]
        history = _make_history(closes_per_day)
        result = compute_breadth_for_day(history)

        # All 3 stocks above 20-day MA on day 21 (the last)
        self.assertAlmostEqual(result["pct_above_20ma"], 100.0, places=1)

    def test_mixed_breadth(self):
        # Stock A: rising; Stock B: flat; Stock C: falling
        # On day 21:
        #   A close=30, mean=20 → above ✓
        #   B close=20, mean=20 → not above (>=, not strict)
        #   C close=10, mean=20 → below ✗
        closes_per_day = []
        for i in range(21):
            closes_per_day.append([10.0 + i, 20.0, 30.0 - i])
        history = _make_history(closes_per_day)
        result = compute_breadth_for_day(history)

        # 1 of 3 strictly above 20MA = 33.33%
        self.assertAlmostEqual(result["pct_above_20ma"], 33.33, places=1)

    def test_excludes_stocks_with_short_history(self):
        # Stock A: 21 days; Stock B: only 5 days (too short for 20MA)
        history = {
            "1000": [10.0 + i for i in range(21)],
            "1001": [50.0, 51.0, 52.0, 53.0, 54.0],
        }
        result = compute_breadth_for_day(history)

        # Only Stock A counted in 20MA; it's above → 100%
        self.assertAlmostEqual(result["pct_above_20ma"], 100.0, places=1)
        # 200MA pool is empty (no stock has 200 days)
        self.assertIsNone(result["pct_above_200ma"])

    def test_new_high_count(self):
        # Stock A: hits new 200-day high today; Stock B: doesn't
        # Need 201 days: prior 200 + today
        a_history = [50.0] * 200 + [60.0]   # today's 60 > prior max 50 → new high
        b_history = [70.0] * 200 + [65.0]   # today's 65 < prior max 70 → no
        history = {"1000": a_history, "1001": b_history}
        result = compute_breadth_for_day(history)

        self.assertEqual(result["new_high_200d"], 1)


if __name__ == "__main__":
    unittest.main()
