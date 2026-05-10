import os
import json
import tempfile
import unittest
from concept_momentum.lending_history import (
    load_lending_radar_rows,
    load_short_retreat_rows,
)


class TestLendingRadar(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def test_consecutive_count(self):
        self._write("20260507", [{"code": "3491", "name": "昇達科",
                                    "lending_zhang": 1280, "ratio_5d": 4.2,
                                    "rate_pct": 8.5}])
        self._write("20260508", [{"code": "3491", "name": "昇達科",
                                    "lending_zhang": 800, "ratio_5d": 3.5,
                                    "rate_pct": 7.0}])
        rows = load_lending_radar_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "3491")
        self.assertEqual(rows[0]["consecutive_days"], 2)
        self.assertEqual(rows[0]["lending_zhang"], 800)  # latest

    def test_empty(self):
        rows = load_lending_radar_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        self.assertEqual(rows, [])


class TestShortRetreat(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def test_sort_by_balance_change_asc(self):
        # Most negative first (biggest空頭撤退)
        self._write("20260508", [
            {"code": "2313", "name": "華通",
             "balance_change_pct": -11.9, "today_change_pct": 1.6},
            {"code": "3491", "name": "昇達科",
             "balance_change_pct": -14.7, "today_change_pct": 0.0},
        ])
        rows = load_short_retreat_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        # 3491 should come first (more negative balance_change)
        self.assertEqual(rows[0]["code"], "3491")
        self.assertEqual(rows[1]["code"], "2313")


if __name__ == "__main__":
    unittest.main()
