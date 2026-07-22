"""Tests for warrant_push (權證量能觀察 LINE 推播)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import warrant_push as wp  # noqa: E402


def _row(code, direction="neutral", surge=3.0, share=1.0, delta=0.0):
    return {"code": code, "warrant_turnover": 5e8, "surge_ratio": surge,
            "bull_share": share, "bull_share_20d": share - delta,
            "bull_share_delta": delta, "direction": direction}


DAY = {"date": "20260721", "underlyings": {
    "2646": {"issuers": {"永豐": 3.9e5, "群益": 1.3e5}, "close": 22.0,
             "top_warrants": [{"code": "073997", "name": "星宇永豐65購01",
                               "issuer": "永豐", "side": "bull",
                               "turnover": 3e5, "close": 1.73}],
             "n_warrants": 12},
    "8045": {"issuers": {"國票": 2e5}, "top_warrants": [], "n_warrants": 3}}}


class TestBuildMessage(unittest.TestCase):
    def test_disclaimer_and_stocks(self):
        msg = wp.build_message([_row("2646", surge=8.5),
                                _row("8045", "bull", surge=8.0,
                                     share=0.9, delta=0.2)], DAY, top=8)
        self.assertIn("權證量能觀察 2026/07/21", msg)
        self.assertIn("回測無預測 edge", msg)      # disclaimer present
        self.assertIn("非買賣訊號", msg)
        self.assertIn("2646", msg)
        self.assertIn("8.5x", msg)
        self.assertIn("永豐", msg)
        self.assertIn("🔥偏多", msg)               # 8045 bull
        self.assertIn("/warrant-signal", msg)

    def test_main_warrant_terms_in_line(self):
        terms = {"073997": {"strike": 31.57, "expiry": "20270505",
                            "conver": 0.5}}
        msg = wp.build_message([_row("2646", surge=8.5)], DAY, top=8,
                               terms=terms)
        self.assertIn("權證價$1.73", msg)
        self.assertIn("履約$31.57", msg)
        self.assertIn("距到期288天", msg)
        self.assertIn("行使0.5", msg)

    def test_top_limit(self):
        rows = [_row(f"{1000+i}", surge=9.0 - i) for i in range(12)]
        msg = wp.build_message(rows, {"date": "20260721", "underlyings": {}},
                               top=5)
        # only 5 stock lines (each starts with "  1")
        stock_lines = [l for l in msg.split("\n") if l.startswith("  1")]
        self.assertEqual(len(stock_lines), 5)

    def test_empty_rows(self):
        msg = wp.build_message([], {"date": "20260721", "underlyings": {}})
        self.assertIn("回測無預測 edge", msg)
        self.assertIn("今日無爆量現股", msg)


class TestConfig(unittest.TestCase):
    def test_load_recipients_shape(self):
        r = wp.load_recipients()
        self.assertIsInstance(r, list)


if __name__ == "__main__":
    unittest.main()
