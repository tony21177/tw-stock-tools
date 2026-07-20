"""Tests for tw_margin_monitor 遞迴成本線 + MIS 即時價 parsing."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from tw_margin_monitor import (  # noqa: E402
    compute_recursive_cost,
    fetch_mis_price,
)


def _h(date, buy, balance):
    return {"date": date, "buy": buy, "sell": 0, "repay": 0,
            "balance": balance}


class TestRecursiveCost(unittest.TestCase):
    def test_single_buy_seeds_at_close(self):
        hist = [_h("20260101", 1000, 1000), _h("20260102", 0, 1000)]
        prices = {"20260101": 100.0, "20260102": 110.0}
        # 種子日成本 = 當日收盤 100；次日無買進 → 成本不變
        self.assertAlmostEqual(compute_recursive_cost(hist, prices), 100.0)

    def test_buy_averages_at_close(self):
        # day1 1000 @100 (seed) → day2 再買 1000 @120 → 成本 110
        hist = [_h("20260101", 1000, 1000), _h("20260102", 1000, 2000)]
        prices = {"20260101": 100.0, "20260102": 120.0}
        self.assertAlmostEqual(compute_recursive_cost(hist, prices), 110.0)

    def test_sell_removes_at_average_cost(self):
        # 成本 110 後賣掉一半（餘額 2000→1000, 無買進）→ 成本仍 110
        hist = [_h("20260101", 1000, 1000), _h("20260102", 1000, 2000),
                _h("20260103", 0, 1000)]
        prices = {"20260101": 100.0, "20260102": 120.0, "20260103": 90.0}
        self.assertAlmostEqual(compute_recursive_cost(hist, prices), 110.0)

    def test_zero_balance_resets(self):
        # 歸零後重新起算 → 成本 = 新一輪種子價
        hist = [_h("20260101", 1000, 1000), _h("20260102", 0, 0),
                _h("20260103", 500, 500), _h("20260104", 0, 500)]
        prices = {"20260101": 100.0, "20260102": 95.0,
                  "20260103": 80.0, "20260104": 85.0}
        self.assertAlmostEqual(compute_recursive_cost(hist, prices), 80.0)

    def test_missing_price_day_keeps_cost(self):
        hist = [_h("20260101", 1000, 1000), _h("20260102", 500, 1500),
                _h("20260103", 0, 1500)]
        prices = {"20260101": 100.0, "20260103": 130.0}  # 0102 缺價
        self.assertAlmostEqual(compute_recursive_cost(hist, prices), 100.0)

    def test_empty_returns_none(self):
        self.assertIsNone(compute_recursive_cost([], {}))
        self.assertIsNone(
            compute_recursive_cost([_h("20260101", 0, 0)], {}))


class TestMisPrice(unittest.TestCase):
    def _mock_resp(self, row):
        return {"msgArray": [row]}

    def test_trade_price_used(self):
        with mock.patch("tw_margin_monitor._http_get_json",
                        return_value=self._mock_resp(
                            {"z": "1230.0000", "y": "1355.0000",
                             "n": "昇達科"})):
            r = fetch_mis_price("3491")
        self.assertEqual(r["price"], 1230.0)
        self.assertEqual(r["prev_close"], 1355.0)
        self.assertEqual(r["market"], "上市")  # 第一個 ex 就命中

    def test_no_trade_falls_back_to_bid(self):
        with mock.patch("tw_margin_monitor._http_get_json",
                        return_value=self._mock_resp(
                            {"z": "-", "b": "1220.0000_1215.0000_",
                             "a": "-", "y": "1355.0000"})):
            r = fetch_mis_price("3491")
        self.assertEqual(r["price"], 1220.0)

    def test_bid_ask_midpoint(self):
        with mock.patch("tw_margin_monitor._http_get_json",
                        return_value=self._mock_resp(
                            {"z": "-", "b": "100.0000_", "a": "102.0000_",
                             "y": "99.0"})):
            r = fetch_mis_price("2330")
        self.assertEqual(r["price"], 101.0)

    def test_not_found_empty(self):
        with mock.patch("tw_margin_monitor._http_get_json",
                        return_value={"msgArray": []}):
            self.assertEqual(fetch_mis_price("9999"), {})


if __name__ == "__main__":
    unittest.main()
