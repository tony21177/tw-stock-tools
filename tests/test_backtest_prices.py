"""PricePanel.fwd 視窗對齊測試 — 合成資料，不打 API。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest_prices import PricePanel

DATES = ["20260701", "20260702", "20260703", "20260706", "20260707"]


def _panel(stock_dates):
    rows = [{"date": d, "open": 100.0, "close": 100.0, "volume": 1000,
             "aopen": 100.0 + i, "aclose": 101.0 + i}
            for i, d in enumerate(stock_dates)]
    cache = {
        "schema": 2, "start": "2026-07-01",
        "stocks": {"9999": {"code": "9999", "name": "測試", "rows": rows}},
        "ex_dates": {"9999": ["20260615"]},
        "taiex": [{"date": d, "open": 200.0, "close": 200.0} for d in DATES],
    }
    return PricePanel(cache)


class TestFwdAlignment(unittest.TestCase):
    def test_normal_next_open(self):
        p = _panel(DATES)
        # signal 0701, h=2: entry 0702 aopen=101, exit 0703 aclose=103
        sr, tr = p.fwd("9999", "20260701", 2, "next_open")
        self.assertAlmostEqual(sr, (103.0 / 101.0 - 1) * 100, places=6)
        self.assertAlmostEqual(tr, 0.0, places=6)

    def test_suspended_exit_returns_none(self):
        # 個股 0703 停牌 (市場有開) → h=2 出場日 0703 無 bar → None
        p = _panel(["20260701", "20260702", "20260706", "20260707"])
        self.assertIsNone(p.fwd("9999", "20260701", 2, "next_open"))

    def test_suspended_entry_returns_none(self):
        # 個股 0702 停牌 → next_open 進場日無 bar → None
        p = _panel(["20260701", "20260703", "20260706", "20260707"])
        self.assertIsNone(p.fwd("9999", "20260701", 2, "next_open"))

    def test_h_zero_returns_none(self):
        p = _panel(DATES)
        self.assertIsNone(p.fwd("9999", "20260701", 0, "next_open"))

    def test_signal_close_entry(self):
        p = _panel(DATES)
        # signal 0701 (aclose=101), h=1 exit 0702 (aclose=102)
        sr, tr = p.fwd("9999", "20260701", 1, "signal_close")
        self.assertAlmostEqual(sr, (102.0 / 101.0 - 1) * 100, places=6)

    def test_has_ex_dividend_inclusive(self):
        p = _panel(DATES)
        self.assertTrue(p.has_ex_dividend("9999", "20260615", "20260615"))
        self.assertFalse(p.has_ex_dividend("9999", "20260616", "20260701"))


if __name__ == "__main__":
    unittest.main()
