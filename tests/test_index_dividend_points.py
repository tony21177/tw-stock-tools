"""Tests for index_dividend_points — 結算前除息點數精算."""
import os
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import index_dividend_points as idp  # noqa: E402


class TestSettlement(unittest.TestCase):
    def test_third_wednesday(self):
        # 2026-07: 1號=週三 → 第三個週三 = 7/15
        self.assertEqual(idp.third_wednesday(2026, 7), date(2026, 7, 15))
        # 2026-08: 1號=週六 → 第一個週三 8/5 → 第三個 8/19
        self.assertEqual(idp.third_wednesday(2026, 8), date(2026, 8, 19))

    def test_front_settlement_by_contract(self):
        self.assertEqual(
            idp.front_settlement(date(2026, 7, 22), "202608"),
            date(2026, 8, 19))

    def test_front_settlement_by_asof_before(self):
        # 7/10 未過本月第三週三(7/15) → 本月結算
        self.assertEqual(idp.front_settlement(date(2026, 7, 10)),
                         date(2026, 7, 15))

    def test_front_settlement_by_asof_after(self):
        # 7/22 已過 7/15 → 次月(8/19)
        self.assertEqual(idp.front_settlement(date(2026, 7, 22)),
                         date(2026, 8, 19))


class TestComputePoints(unittest.TestCase):
    def _divs(self, mapping):
        return lambda sid: mapping.get(sid, [])

    def test_single_heavyweight(self):
        # 指數 20000，台積電權重 40%(市值 40 兆/總100兆)，股價 1000，
        # 現金股利 20/股 → 點數 = 20000 × 0.4 × (20/1000) = 160
        top = [{"stock_id": "2330", "market_value": 40e12}]
        divs = self._divs({"2330": [{"ex_date": "2026-08-01", "cash": 20.0}]})
        r = idp.compute_points(20000, 100e12, top, "2026-08-19", "2026-07-22",
                               divs, {"2330": 1000.0})
        self.assertAlmostEqual(r["points"], 160.0, places=1)
        self.assertEqual(r["coverage_pct"], 40.0)
        self.assertEqual(r["n_div"], 1)
        self.assertEqual(r["detail"][0]["code"], "2330")

    def test_ex_date_outside_window_ignored(self):
        top = [{"stock_id": "2330", "market_value": 40e12}]
        # 除息日在結算日之後 → 不算
        divs = self._divs({"2330": [{"ex_date": "2026-09-01", "cash": 20.0}]})
        r = idp.compute_points(20000, 100e12, top, "2026-08-19", "2026-07-22",
                               divs, {"2330": 1000.0})
        self.assertEqual(r["points"], 0.0)
        self.assertEqual(r["n_div"], 0)

    def test_ex_date_already_passed_ignored(self):
        top = [{"stock_id": "2330", "market_value": 40e12}]
        # 除息日 = 今天(含)之前 → 不算(asof_iso < ex 才算)
        divs = self._divs({"2330": [{"ex_date": "2026-07-22", "cash": 20.0}]})
        r = idp.compute_points(20000, 100e12, top, "2026-08-19", "2026-07-22",
                               divs, {"2330": 1000.0})
        self.assertEqual(r["points"], 0.0)

    def test_missing_price_skipped(self):
        top = [{"stock_id": "9999", "market_value": 10e12}]
        divs = self._divs({"9999": [{"ex_date": "2026-08-01", "cash": 5.0}]})
        r = idp.compute_points(20000, 100e12, top, "2026-08-19", "2026-07-22",
                               divs, {})  # 無股價
        self.assertEqual(r["points"], 0.0)

    def test_multiple_stocks_and_coverage(self):
        top = [{"stock_id": "2330", "market_value": 40e12},
               {"stock_id": "2317", "market_value": 5e12}]
        divs = self._divs({
            "2330": [{"ex_date": "2026-08-01", "cash": 20.0}],
            "2317": [{"ex_date": "2026-08-05", "cash": 5.0}]})
        r = idp.compute_points(20000, 100e12, top, "2026-08-19", "2026-07-22",
                               divs, {"2330": 1000.0, "2317": 200.0})
        # 2330: 160；2317: 20000×0.05×(5/200)=25 → 185
        self.assertAlmostEqual(r["points"], 185.0, places=1)
        self.assertEqual(r["coverage_pct"], 45.0)   # (40+5)/100


if __name__ == "__main__":
    unittest.main()
