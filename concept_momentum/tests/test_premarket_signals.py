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


class TestPremarketRenderer(unittest.TestCase):
    def test_render_with_data(self):
        from concept_momentum.premarket_signals_renderer import render_table
        tr_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "layer1_passed": True, "abcd_score": 4, "consecutive_days": 3}]
        sw_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "second_wave_score": 8.5, "drop_pct": -22.0,
                    "volume_ratio": 5.16, "consecutive_days": 2}]
        html = render_table(tr_rows, sw_rows)
        # both stocks shown
        self.assertIn("轉機接力", html)
        self.assertIn("強勢股第二波", html)
        self.assertIn("2313", html)
        self.assertIn("4", html)
        self.assertIn("8.5", html)
        self.assertIn("-22.0", html)
        self.assertIn("5.16", html)

    def test_render_both_empty(self):
        from concept_momentum.premarket_signals_renderer import render_table
        html = render_table([], [])
        self.assertIn("近 10 個交易日無候選", html)

    def test_render_one_section_empty(self):
        from concept_momentum.premarket_signals_renderer import render_table
        tr_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "layer1_passed": True, "abcd_score": 4, "consecutive_days": 3}]
        html = render_table(tr_rows, [])
        # TR section has data; 2W section shows empty msg
        self.assertIn("2313", html)
        # Empty msg appears for 2W only
        self.assertEqual(html.count("近 10 個交易日無候選"), 1)


if __name__ == "__main__":
    unittest.main()
