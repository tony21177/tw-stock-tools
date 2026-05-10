import os
import json
import math
import tempfile
import unittest
from concept_momentum.broker_radar_history import (
    composite_score,
    load_broker_radar_rows,
)


class TestCompositeScore(unittest.TestCase):
    def test_score_basic(self):
        # consecutive_days=5, top_broker_net=3000 張, margin_inc=500 張
        # top_factor = log(3001) ≈ 8.006
        # margin_factor = sqrt(500) ≈ 22.36
        # score = 5 * (8.006 + 22.36) / 2 ≈ 75.92
        s = composite_score(consecutive_days=5, top_broker_net_zhang=3000, margin_increase_zhang=500)
        self.assertAlmostEqual(s, 75.9, places=0)

    def test_score_negative_clipped_to_zero(self):
        # negative top_broker / negative margin → factors clipped to 0
        s = composite_score(consecutive_days=3, top_broker_net_zhang=-100, margin_increase_zhang=-200)
        self.assertEqual(s, 0.0)

    def test_score_zero_consecutive(self):
        s = composite_score(consecutive_days=0, top_broker_net_zhang=10000, margin_increase_zhang=10000)
        self.assertEqual(s, 0.0)


class TestLoader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_day(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def _stock(self, code, name, top_net, margin_inc):
        return {
            "code": code,
            "name": name,
            "current_balance": 100000,
            "margin_increase_zhang": margin_inc,
            "candidates": [
                {"broker_id": "9268", "broker_name": "凱基台北",
                 "active_days": 3, "total_net_zhang": top_net, "correlation": 0.8}
            ],
        }

    def test_consecutive_count_two_days(self):
        self._write_day("20260506", [self._stock("2330", "台積電", 1000, 200)])
        self._write_day("20260507", [self._stock("2330", "台積電", 1500, 250)])
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260507", lookback_days=10)

        # 2330 appears in both days → consecutive 2
        match = [r for r in rows if r["code"] == "2330"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["consecutive_days"], 2)
        self.assertEqual(match[0]["latest_date"], "20260507")
        # uses the LATEST day's margin/top values
        self.assertEqual(match[0]["margin_increase_zhang"], 250)
        self.assertEqual(match[0]["top_broker_net_zhang"], 1500)

    def test_consecutive_breaks_with_gap(self):
        # 2330 appears 5/06, missing 5/07, appears 5/08 → consecutive count = 1 (only most recent run)
        self._write_day("20260506", [self._stock("2330", "台積電", 1000, 200)])
        self._write_day("20260507", [self._stock("2317", "鴻海", 500, 100)])
        self._write_day("20260508", [self._stock("2330", "台積電", 1500, 250)])
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        match = [r for r in rows if r["code"] == "2330"]
        self.assertEqual(match[0]["consecutive_days"], 1)

    def test_sorted_by_score_desc(self):
        # 2330: 5 days * (1500張, 250張) = high
        # 2317: 1 day * (10000張, 1000張) = lower because consecutive_days=1
        for d in ["20260504", "20260505", "20260506", "20260507", "20260508"]:
            self._write_day(d, [self._stock("2330", "台積電", 1500, 250)])
        # 2317 only on the last day
        with open(os.path.join(self.tmpdir, "20260508.json")) as f:
            existing = json.load(f)
        existing["stocks"].append(self._stock("2317", "鴻海", 10000, 1000))
        with open(os.path.join(self.tmpdir, "20260508.json"), "w") as f:
            json.dump(existing, f)

        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        # First row should be 2330 (5-day persistence beats 2317's 1 day with bigger numbers)
        self.assertEqual(rows[0]["code"], "2330")

    def test_empty_dir(self):
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
