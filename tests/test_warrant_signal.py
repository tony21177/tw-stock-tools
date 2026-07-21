import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_signal as ws


def _day(date, bull, bear):
    return {"date": date, "underlyings": {
        "2308": {"bull_turnover": bull, "bear_turnover": bear,
                 "bull_vol": 0, "bear_vol": 0, "n_warrants": 1,
                 "issuers": {}, "top_warrants": []}}}


class TestSignal(unittest.TestCase):
    def test_surge_and_bull_direction(self):
        # 前 20 日總量 100（bull80/bear20，bull_share 0.8），今日爆量到 400、
        # bull_share 升到 0.95 → delta +0.15 → bull
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 380, 20))
        rows = ws.build_signal_rows(days)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertAlmostEqual(r["surge_ratio"], 4.0, places=1)
        self.assertGreater(r["bull_share_delta"], 0.10)
        self.assertEqual(r["direction"], "bull")

    def test_bear_direction(self):
        # 今日認售/熊證放量 → bull_share 大降 → bear
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 100, 300))  # 總量 400 爆量, bull_share 0.25
        rows = ws.build_signal_rows(days)
        self.assertEqual(rows[0]["direction"], "bear")

    def test_neutral_when_balanced(self):
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 320, 80))  # 爆量但 bull_share 仍 0.8, delta 0
        rows = ws.build_signal_rows(days)
        self.assertEqual(rows[0]["direction"], "neutral")

    def test_no_surge_excluded(self):
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 90, 20))  # 沒爆量
        self.assertEqual(ws.build_signal_rows(days), [])
