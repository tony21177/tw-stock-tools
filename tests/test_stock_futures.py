"""Tests for tw_stock_futures — 個股期火熱排行."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import tw_stock_futures as sf  # noqa: E402

MAP = {
    "CC": {"stock": "2303", "name": "聯電", "is_fut": True},
    "CD": {"stock": "2330", "name": "台積電", "is_fut": True},
    "DX": {"stock": "3231", "name": "緯創", "is_fut": True},
    "MT": {"stock": "", "name": "小台指", "is_fut": False},  # 指數期
}


def _row(fid, cd, close, pct, vol, oi, hi, lo, sess="position",
         date="2026-07-24"):
    return {"date": date, "futures_id": fid, "contract_date": cd,
            "close": close, "spread_per": pct, "volume": vol,
            "open_interest": oi, "max": hi, "min": lo,
            "trading_session": sess}


class TestAggregate(unittest.TestCase):
    def test_sum_across_months(self):
        rows = [_row("CCF", "202608", 128.5, -8.87, 40000, 90000, 130, 127),
                _row("CCF", "202609", 128.0, -8.9, 4068, 11396, 130, 127)]
        agg = sf._agg_by_futures(rows, "2026-07-24")
        self.assertEqual(agg["CCF"]["vol"], 44068)      # 加總
        self.assertEqual(agg["CCF"]["oi"], 101396)
        self.assertEqual(agg["CCF"]["close"], 128.5)    # 近月
        self.assertEqual(agg["CCF"]["pct"], -8.87)

    def test_near_month_pref_position(self):
        rows = [_row("CDF", "202608", 2420, 0.67, 6000, 22000, 2421, 2384,
                     sess="after_market"),
                _row("CDF", "202608", 2420, 0.67, 11, 22906, 2421, 2384,
                     sess="position")]
        agg = sf._agg_by_futures(rows, "2026-07-24")
        self.assertEqual(agg["CDF"]["close"], 2420)


class TestBuildRanking(unittest.TestCase):
    def _today(self):
        return [
            _row("CCF", "202608", 128.5, -8.87, 44068, 101396, 132, 126),
            _row("CDF", "202608", 2362, -2.11, 6011, 22906, 2400, 2350),
            _row("DXF", "202608", 179, 1.99, 12640, 8553, 185, 170),
            _row("MTF", "202608", 20000, -1.0, 99999, 5000, 20100, 19900),
        ]

    def _prev(self):
        return [
            _row("CCF", "202607", 141, -1.0, 35771, 106390, 143, 140,
                 date="2026-07-23"),
            _row("CDF", "202607", 2413, -0.5, 6428, 23000, 2420, 2400,
                 date="2026-07-23"),
            _row("DXF", "202607", 175, 0.5, 5000, 9000, 176, 173,
                 date="2026-07-23"),
        ]

    def test_ranks_by_volume_excludes_index(self):
        r = sf.build_ranking(self._today(), self._prev(), MAP,
                             "2026-07-24", "2026-07-23")
        fids = [x["fid"] for x in r]
        self.assertNotIn("MTF", fids)                # 指數期排除(is_fut False)
        self.assertEqual(fids[0], "CCF")             # 量最大
        self.assertEqual(r[0]["stock"], "2303")
        self.assertEqual(r[0]["name"], "聯電")

    def test_vol_oi_change(self):
        r = sf.build_ranking(self._today(), self._prev(), MAP,
                             "2026-07-24", "2026-07-23")
        cc = next(x for x in r if x["fid"] == "CCF")
        self.assertEqual(cc["vol_chg"], 44068 - 35771)
        self.assertEqual(cc["oi_chg"], 101396 - 106390)

    def test_flags(self):
        r = sf.build_ranking(self._today(), self._prev(), MAP,
                             "2026-07-24", "2026-07-23")
        cc = next(x for x in r if x["fid"] == "CCF")
        self.assertTrue(cc["f_hot"])                 # 量前N
        self.assertTrue(cc["f_pct_top"])             # |−8.87| 大 → 前十
        # DXF 量排名躍升: prev 第3名(5000) → today 第2名 → jump 1, 但門檻30
        dx = next(x for x in r if x["fid"] == "DXF")
        self.assertIsNotNone(dx["rank_jump"])

    def test_no_prev_no_change(self):
        r = sf.build_ranking(self._today(), [], MAP,
                             "2026-07-24", "2026-07-23")
        self.assertIsNone(r[0]["vol_chg"])
        self.assertFalse(r[0]["f_rank_jump"])


if __name__ == "__main__":
    unittest.main()
