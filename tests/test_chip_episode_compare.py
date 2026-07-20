"""Tests for chip_episode_compare — 兩波籌碼對比 (offline, no FinMind)."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import chip_episode_compare as cec  # noqa: E402


def _mk_series():
    # 兩波簡化資料：波1 100→60→80(築底), 波2 200→120(下跌中)
    price, sbl, fnet, margin = {}, {}, {}, {}
    # 波1 下跌
    for i, (d, p, sb, f, m) in enumerate([
        ("2025-03-21", 100, 1000, 0, 4000),
        ("2025-04-15", 80, 1200, -50, 3900),
        ("2025-06-03", 60, 1500, -30, 3800),   # 低點
        ("2025-07-15", 70, 3000, -200, 4100),  # 築底：借券暴增
        ("2025-08-29", 80, 3500, -400, 4200),
    ]):
        price[d], sbl[d], fnet[d], margin[d] = p, sb, f, m
    # 波2 下跌中
    for d, p, sb, f, m in [
        ("2026-05-29", 200, 1400, 100, 3400),
        ("2026-06-20", 150, 2500, -1500, 3300),
        ("2026-07-07", 120, 3600, -2000, 3200),  # 低點(至今)
        ("2026-07-20", 122, 3550, -400, 3260),
    ]:
        price[d], sbl[d], fnet[d], margin[d] = p, sb, f, m
    return {"price": price, "sbl": sbl, "fnet": fnet, "margin": margin}


class TestSegStats(unittest.TestCase):
    def setUp(self):
        self.s = _mk_series()

    def test_fall_segment(self):
        seg = cec._seg_stats(self.s, "2025-03-21", "2025-06-03")
        self.assertEqual(seg["px0"], 100)
        self.assertEqual(seg["px1"], 60)
        self.assertEqual(seg["px_chg_pct"], -40.0)
        self.assertEqual(seg["f_cum"], -80)   # 0-50-30
        self.assertEqual(seg["sbl0"], 1000)
        self.assertEqual(seg["sbl1"], 1500)

    def test_base_segment_sbl_surge(self):
        seg = cec._seg_stats(self.s, "2025-06-03", "2025-08-29")
        self.assertEqual(seg["px_chg_pct"], round((80/60-1)*100, 1))
        self.assertEqual(seg["sbl_peak"], 3500)   # 築底借券暴增

    def test_margin_kept_as_lots(self):
        # 融資不得再 /1000 — 原生張
        seg = cec._seg_stats(self.s, "2025-03-21", "2025-08-29")
        self.assertEqual(seg["mgn0"], 4000)
        self.assertEqual(seg["mgn_peak"], 4200)


class TestBuildEpisode(unittest.TestCase):
    def test_finds_trough_and_splits(self):
        s = _mk_series()
        ep = cec.build_episode("X", "2025-03-21", "2025-08-31", s)
        self.assertEqual(ep["peak_px"], 100)
        self.assertEqual(ep["low_date"], "2025-06-03")
        self.assertEqual(ep["low_px"], 60)
        self.assertTrue(ep["fall"])
        self.assertTrue(ep["base"])   # 有築底段
        self.assertEqual(ep["fall"]["px_chg_pct"], -40.0)

    def test_ongoing_episode_no_base(self):
        s = _mk_series()
        ep = cec.build_episode("X", "2026-05-29", "2026-07-20", s)
        self.assertEqual(ep["low_date"], "2026-07-07")
        # 低點後仍有 2 天(反彈) → base 存在但小
        self.assertEqual(ep["fall"]["px_chg_pct"], -40.0)


class TestBuildCompare(unittest.TestCase):
    def test_offline_with_mocked_series(self):
        s = _mk_series()
        with mock.patch.object(cec, "fetch_series", return_value=s):
            data = cec.build_compare("3491",
                                     [("2025-03-21", "2025-08-31"),
                                      ("2026-05-29", "2026-07-20")],
                                     token="fake")
        self.assertEqual(len(data["episodes"]), 2)
        self.assertEqual(len(data["series"]), len(s["price"]))
        self.assertEqual(data["asof"], "2026-07-20")

    def test_no_token(self):
        with mock.patch.object(cec, "_token", return_value=""):
            data = cec.build_compare("3491", [("2025-03-21", "2025-08-31")])
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
