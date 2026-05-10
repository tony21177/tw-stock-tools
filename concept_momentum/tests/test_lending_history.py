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


class TestLendingRenderer(unittest.TestCase):
    def test_render_lending_radar(self):
        from concept_momentum.lending_history_renderer import render_table
        radar = [{"code": "3491", "name": "昇達科", "latest_date": "20260508",
                  "lending_zhang": 1280, "ratio_5d": 4.2, "rate_pct": 8.5,
                  "consecutive_days": 2}]
        retreat = []
        html = render_table(radar, retreat)
        self.assertIn("借券雷達", html)
        self.assertIn("空頭撤退", html)
        self.assertIn("3491", html)
        self.assertIn("1,280", html)
        self.assertIn("4.20x", html)
        # rate >7% should get pos class
        self.assertIn('class="pos">8.50%', html)

    def test_render_short_retreat_color(self):
        from concept_momentum.lending_history_renderer import render_table
        retreat = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "balance_change_pct": -11.9, "today_change_pct": 1.6,
                    "consecutive_days": 1}]
        html = render_table([], retreat)
        # balance_change negative → neg color
        self.assertIn('class="neg">-11.90%', html)
        # today_change positive → pos color
        self.assertIn('class="pos">+1.60%', html)

    def test_render_both_empty(self):
        from concept_momentum.lending_history_renderer import render_table
        html = render_table([], [])
        self.assertEqual(html.count("近 5 個交易日無候選"), 2)


if __name__ == "__main__":
    unittest.main()
