"""Tests for tw_market_overnight — 明天大盤預期."""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import tw_market_overnight as mo  # noqa: E402


def _synthetic_raw(n=260, beta=0.4, noise=0.3, seed=1):
    """造:美股隔夜 = 正弦訊號;TWII 隔天 ≈ beta×SOX隔夜 + 小雜訊。
    US 日期比 TW 早一天(交錯),讓 prior() 對到。"""
    us_price = [100.0]
    tw_close = [10000.0]
    tw_open = [10000.0]
    us_rows, tw_rows = [], []
    # 交錯日期:US 在偶數日、TW 在奇數日(YYYYMMDD 用序號模擬)
    for i in range(1, n):
        # 決定性「隨機」訊號
        s = math.sin(i * 0.7) * 2 + math.cos(i * 0.31)      # 美股隔夜%
        us_price.append(us_price[-1] * (1 + s / 100))
        nz = math.sin(i * 3.3 + seed) * noise                # 台股雜訊
        cc = beta * s + nz                                    # 台股收-收%
        tw_close.append(tw_close[-1] * (1 + cc / 100))
        tw_open.append(tw_close[-2] * (1 + (beta * s * 0.9) / 100))
    for i in range(n):
        usd = f"2025{(i * 2) // 100 + 1:02d}{(i * 2) % 100 + 1:02d}"
        us_rows.append({"date": usd, "open": us_price[i], "close": us_price[i]})
    for i in range(n):
        twd = f"2025{(i * 2 + 1) // 100 + 1:02d}{(i * 2 + 1) % 100 + 1:02d}"
        tw_rows.append({"date": twd, "open": tw_open[i], "close": tw_close[i]})
    raw = {s: [dict(r) for r in us_rows] for s in mo.US_SYMBOLS}
    raw[mo.TWII] = tw_rows
    return raw


class TestMarketOvernight(unittest.TestCase):
    def test_build_dataset_shapes(self):
        raw = _synthetic_raw()
        rows, feats = mo.build_dataset(raw)
        self.assertEqual(feats, mo.US_SYMBOLS)
        self.assertGreater(len(rows), 100)
        # 每列:(date, feat[4], cc, gap)
        d, f, cc, gap = rows[0]
        self.assertEqual(len(f), 4)
        self.assertIsInstance(cc, float)

    def test_backtest_direction_beats_coin(self):
        # 造了 SOX→TWII 正相關 → 方向命中應遠高於 50%
        raw = _synthetic_raw(beta=0.5, noise=0.2)
        bt = mo.backtest(raw, window=100)
        self.assertIn("cc", bt)
        self.assertGreater(bt["cc"]["dir_hit_pct"], 65)
        self.assertGreater(bt["cc"]["skill_vs_zero_pct"], 0)

    def test_predict_next_keys(self):
        raw = _synthetic_raw()
        p = mo.predict_next(raw, window=100)
        self.assertNotIn("error", p)
        self.assertIn("cc", p)
        for k in ("pred", "p10", "p25", "p75", "p90", "up_prob"):
            self.assertIn(k, p["cc"])
        # 帶單調:p10<=p25<=p75<=p90
        c = p["cc"]
        self.assertLessEqual(c["p10"], c["p25"])
        self.assertLessEqual(c["p25"], c["p75"])
        self.assertLessEqual(c["p75"], c["p90"])

    def test_band_calibration_reasonable(self):
        # 校準帶:25-75% 覆蓋應接近 50(±15)
        raw = _synthetic_raw(beta=0.4, noise=0.4)
        bt = mo.backtest(raw, window=100)
        cov = bt["cc"]["cover_2575_pct"]
        self.assertGreater(cov, 30)
        self.assertLess(cov, 70)


if __name__ == "__main__":
    unittest.main()
