"""Tests for warrant_signal_renderer (權證量能觀察頁)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import warrant_signal_renderer as wsr  # noqa: E402


def _row(code, direction="neutral", surge=3.0, share=1.0, delta=0.0):
    return {"code": code, "warrant_turnover": 5e8, "surge_ratio": surge,
            "bull_share": share, "bull_share_20d": share - delta,
            "bull_share_delta": delta, "direction": direction}


DAY = {"date": "20260721", "underlyings": {
    "2646": {"bull_turnover": 5e8, "bear_turnover": 0.0, "n_warrants": 12,
             "issuers": {"永豐": 3.9e5, "群益": 1.3e5, "國票": 0.8e5},
             "top_warrants": [{"code": "073997", "name": "星宇永豐65購01",
                               "issuer": "永豐", "side": "bull",
                               "turnover": 3.77e5}]}}}
BT = {"start": "20260421", "end": "20260721", "grid": []}


class TestCaveat(unittest.TestCase):
    def test_no_edge_disclosure_present(self):
        html = wsr.render_backtest_caveat(BT)
        self.assertIn("無預測 edge", html)
        self.assertIn("非買賣訊號", html)
        self.assertIn("04/21", html)   # period rendered

    def test_caveat_without_backtest(self):
        html = wsr.render_backtest_caveat(None)
        self.assertIn("無預測 edge", html)   # still discloses


class TestRenderPage(unittest.TestCase):
    def test_full_page(self):
        html = wsr.render_page([_row("2646", surge=8.5)], DAY, "20260721",
                               backtest=BT)
        self.assertIn("權證量能觀察", html)
        self.assertIn("無預測 edge", html)     # caveat box
        self.assertIn("2646", html)
        self.assertIn("8.5x", html)
        self.assertIn("⚡ 中性", html)
        self.assertIn("永豐", html)             # issuer distribution
        self.assertIn("星宇永豐65購01", html)   # top warrant in details
        self.assertIn("/warrant-signal", html)  # nav self-link

    def test_bull_bear_labels(self):
        html = wsr.render_page(
            [_row("1111", "bull", share=0.9, delta=0.2),
             _row("2222", "bear", share=0.6, delta=-0.3)],
            {"date": "20260721", "underlyings": {
                "1111": {"issuers": {}, "top_warrants": [], "n_warrants": 3},
                "2222": {"issuers": {}, "top_warrants": [], "n_warrants": 2}}},
            "20260721", backtest=BT)
        self.assertIn("🔥 偏多", html)
        self.assertIn("❄ 偏空", html)

    def test_empty_rows(self):
        html = wsr.render_page([], {}, "20260721", backtest=BT)
        self.assertIn("無預測 edge", html)      # caveat still shown
        self.assertIn("今日無權證爆量現股", html)


class TestTermsDisplay(unittest.TestCase):
    def test_days_to_expiry(self):
        self.assertEqual(wsr._days_to_expiry("20270505", "20260721"), 288)
        self.assertIsNone(wsr._days_to_expiry("bad", "20260721"))

    def test_in_out_call_put(self):
        self.assertEqual(wsr._in_out(30.0, 33.0, True), "價內10%")
        self.assertEqual(wsr._in_out(30.0, 33.0, False), "價外10%")
        self.assertEqual(wsr._in_out(None, 33.0, True), "")

    def test_terms_shown_in_details(self):
        day = {"date": "20260721", "underlyings": {"2646": {
            "name": "星宇航空", "close": 33.0, "issuers": {"永豐": 1e5},
            "n_warrants": 3, "top_warrants": [{"code": "073997",
                "name": "星宇永豐65購01", "issuer": "永豐", "side": "bull",
                "turnover": 3e5}]}}}
        terms = {"073997": {"strike": 31.57, "expiry": "20270505",
                            "conver": 0.5}}
        html = wsr.render_page([_row("2646", surge=8.5)], day, "20260721",
                               backtest=BT, terms=terms)
        self.assertIn("履約$31.57", html)
        self.assertIn("距到期288天", html)
        self.assertIn("行使0.5", html)

if __name__ == "__main__":
    unittest.main()
