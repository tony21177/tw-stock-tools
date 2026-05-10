import os
import json
import tempfile
import unittest
from concept_momentum.premarket_signals import (
    load_turnaround_relay_rows,
    load_second_wave_rows,
)


class TestTurnaroundRelay(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, candidates):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "candidates": candidates}, f)

    def test_consecutive_count(self):
        self._write("20260506", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 3}])
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 4}])
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260507",
                                          lookback_days=10)
        match = [r for r in rows if r["code"] == "2313"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["consecutive_days"], 2)
        self.assertEqual(match[0]["abcd_score"], 4)  # latest day's score
        self.assertEqual(match[0]["latest_date"], "20260507")
        self.assertTrue(match[0]["layer1_passed"])

    def test_empty(self):
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260508",
                                          lookback_days=10)
        self.assertEqual(rows, [])

    def test_sort_latest_date_then_consecutive(self):
        # 2313 appears 5/6+5/7 (latest=5/7, streak=2)
        # 2330 appears only 5/8 (latest=5/8, streak=1)
        self._write("20260506", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 3}])
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 4}])
        self._write("20260508", [{"code": "2330", "name": "台積電",
                                   "layer1_passed": True, "abcd_score": 2}])
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260508",
                                          lookback_days=10)
        # 2330 should come first (later date)
        self.assertEqual(rows[0]["code"], "2330")
        self.assertEqual(rows[1]["code"], "2313")


class TestSecondWave(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, candidates):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "candidates": candidates}, f)

    def test_basic(self):
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "second_wave_score": 8.5,
                                   "drop_pct": -22.0, "volume_ratio": 5.16}])
        rows = load_second_wave_rows(self.tmpdir, end_date="20260507",
                                     lookback_days=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "2313")
        self.assertEqual(rows[0]["second_wave_score"], 8.5)
        self.assertEqual(rows[0]["consecutive_days"], 1)


if __name__ == "__main__":
    unittest.main()
