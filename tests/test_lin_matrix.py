"""Tests for lin_matrix — 林則行矩陣偵測."""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import lin_matrix as lm  # noqa: E402


def _bars(specs, start_day=1):
    """specs: [(high, low, close, volume)] → series (日升冪)."""
    out = []
    for i, (h, l, c, v) in enumerate(specs):
        out.append({"date": f"2026{(start_day+i):04d}"[:8].ljust(8, "0")
                    if False else f"202601{start_day+i:02d}",
                    "open": c, "high": h, "low": l, "close": c, "volume": v})
    return out


def _box(days, hi, lo, vol, close=None):
    """低量橫向震盪箱 days 天。收盤沿平緩正弦在 [lo,hi] 間來回(小日步、
    收在高點),以通過形狀閘(平坦、上下緣皆測試、無山頭、單日變動小、
    盤末不崩);high/low 固定 hi/lo。"""
    mid = (hi + lo) / 2
    amp = (hi - lo) / 2
    w = 2 * math.pi / 11
    phase = 11 / 4 - (days - 1)      # 使最後一根收在正弦峰(近天花板)
    out = []
    for i in range(days):
        c = close if close is not None else round(mid + amp * math.sin(w * (i + phase)), 2)
        out.append({"date": f"box{i}", "open": c, "high": hi, "low": lo,
                    "close": c, "volume": vol})
    return out


class TestDetectMatrix(unittest.TestCase):
    def test_low_volume_box_detected(self):
        # 前段高量 100，箱型 70 天低量 30、幅度 10% → ⭐
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 110, 100, 30)   # amp (110-100)/100 = 10%
        m = lm.detect_matrix(pre + box)
        self.assertIsNotNone(m)
        self.assertEqual(m["ceiling"], 110)
        self.assertEqual(m["floor"], 100)
        self.assertEqual(m["amp_pct"], 10.0)
        self.assertEqual(m["tier"], "⭐")           # ≤15%
        self.assertGreaterEqual(m["days"], 60)

    def test_amplitude_over_15_excluded(self):
        # 嚴格 15%:幅度 25% 的寬箱不再算矩陣
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 125, 100, 30)   # amp 25% > 15% → 排除
        self.assertIsNone(lm.detect_matrix(pre + box))

    def test_amplitude_at_15_included(self):
        # 邊界:幅度剛好 15% 仍算矩陣(⭐)
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 115, 100, 30)   # amp 15% → 通過
        m = lm.detect_matrix(pre + box)
        self.assertIsNotNone(m)
        self.assertEqual(m["amp_pct"], 15.0)
        self.assertEqual(m["tier"], "⭐")

    def test_high_amplitude_excluded(self):
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 140, 100, 30)   # amp 40% > 15% → 排除
        self.assertIsNone(lm.detect_matrix(pre + box))

    def test_mountain_shape_excluded(self):
        # 山形:收盤先漲到中段做頭(112)再跌回(3045 台灣大型態)。
        # 幅度/量都合格,但中段明顯高於兩端 → 形狀閘擋掉。
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        n = 70
        box = []
        for i in range(n):
            # 三角形 profile:兩端 100、中央 112(帶寬 100~112)
            c = 100 + 12 * (1 - abs(i - n / 2) / (n / 2))
            box.append({"date": f"m{i}", "open": c, "high": round(c, 2),
                        "low": round(c, 2), "close": round(c, 2), "volume": 30})
        self.assertIsNone(lm.detect_matrix(pre + box))

    def test_valley_shape_excluded(self):
        # V 谷:收盤先跌到中段觸底(100)再回升(5403 中菲型態)。
        # 幅度/量合格,但中段明顯低於兩端 → 對稱形狀閘擋掉。
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        n = 70
        box = []
        for i in range(n):
            # V profile:兩端 112、中央 100
            c = 100 + 12 * (abs(i - n / 2) / (n / 2))
            box.append({"date": f"v{i}", "open": c, "high": round(c, 2),
                        "low": round(c, 2), "close": round(c, 2), "volume": 30})
        self.assertIsNone(lm.detect_matrix(pre + box))

    def test_flat_oscillating_box_included(self):
        # 對照組:同帶寬但平坦來回震盪 → 通過形狀閘
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        self.assertIsNotNone(lm.detect_matrix(pre + _box(70, 112, 100, 30)))

    def test_avg_atr_reported(self):
        # 箱型每根 高110/低100/收105。首根昨收=箱前 80 →
        # TR=max(10,|110-80|=30,|100-80|=20)=30;其餘 TR=max(10,5,5)=10。
        # atr=(30+69×10)/70=10.29;mid=105 → atr_pct=9.8%
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 110, 100, 30)
        m = lm.detect_matrix(pre + box)
        self.assertEqual(m["atr"], 10.29)
        self.assertEqual(m["atr_pct"], 9.8)

    def test_high_volume_not_settled_excluded(self):
        # 箱型量 90 ≈ 前段 100 → 非低量沉澱(90 ≥ 100×0.8=80) → 排除
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(70, 110, 100, 90)
        self.assertIsNone(lm.detect_matrix(pre + box))

    def test_too_short_excluded(self):
        box = _box(40, 110, 100, 30)   # < MIN_BOX_DAYS(60)
        self.assertIsNone(lm.detect_matrix(box))


class TestClassify(unittest.TestCase):
    def _setup(self):
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(69, 110, 100, 30)
        return pre, box

    def test_breakout(self):
        pre, box = self._setup()
        # 今日收盤 115 > 天花板 110，量 90 = 箱均 30 的 3 倍 → 突破
        today = {"date": "brk", "open": 111, "high": 116, "low": 111,
                 "close": 115, "volume": 90}
        s = pre + box + [today]
        m = lm.detect_matrix(s, as_of_idx=len(s) - 2)   # 用突破前一天的箱
        c = lm.classify(s, m)
        self.assertTrue(c["breakout"])
        self.assertEqual(c["vol_mult"], 3.0)

    def test_volume_too_low_no_breakout(self):
        pre, box = self._setup()
        today = {"date": "brk", "open": 111, "high": 116, "low": 111,
                 "close": 115, "volume": 40}   # 40/30 = 1.3x < 2
        s = pre + box + [today]
        m = lm.detect_matrix(s, as_of_idx=len(s) - 2)
        self.assertFalse(lm.classify(s, m)["breakout"])

    def test_volume_too_high_no_breakout(self):
        pre, box = self._setup()
        today = {"date": "brk", "open": 111, "high": 116, "low": 111,
                 "close": 115, "volume": 400}  # 400/30 = 13x > 10
        s = pre + box + [today]
        m = lm.detect_matrix(s, as_of_idx=len(s) - 2)
        self.assertFalse(lm.classify(s, m)["breakout"])

    def test_near_ceiling(self):
        pre, box = self._setup()
        # 今日收盤 109(箱內、位階 (109-100)/(110-100)=0.9 ≥0.8)
        today = {"date": "nc", "open": 108, "high": 109.5, "low": 108,
                 "close": 109, "volume": 30}
        s = pre + box + [today]
        m = lm.detect_matrix(s, as_of_idx=len(s) - 2)
        c = lm.classify(s, m)
        self.assertFalse(c["breakout"])
        self.assertTrue(c["near_ceiling"])
        self.assertAlmostEqual(c["box_pos"], 0.9)


class TestBuildSignals(unittest.TestCase):
    def test_three_buckets(self):
        pre = [{"date": f"p{i}", "open": 80, "high": 80, "low": 80,
                "close": 80, "volume": 100} for i in range(70)]
        box = _box(69, 110, 100, 30)
        # A: 突破  B: 貼天花板  C: 箱中央
        A = pre + box + [{"date": "d", "open": 111, "high": 116, "low": 111,
                          "close": 115, "volume": 90}]
        B = pre + box + [{"date": "d", "open": 108, "high": 109, "low": 108,
                          "close": 109, "volume": 30}]
        C = pre + box + [{"date": "d", "open": 105, "high": 105, "low": 105,
                          "close": 105, "volume": 30}]
        sig = lm.build_signals({"1111": A, "2222": B, "3333": C},
                               {"1111": "甲", "2222": "乙", "3333": "丙"},
                               fut_codes={"1111"})   # 只有 1111 有個股期
        self.assertEqual([r["code"] for r in sig["breakout"]], ["1111"])
        self.assertEqual([r["code"] for r in sig["watch"]], ["2222"])
        self.assertEqual({r["code"] for r in sig["boxed"]}, {"2222", "3333"})
        self.assertEqual(sig["breakout"][0]["name"], "甲")
        self.assertTrue(sig["breakout"][0]["has_fut"])       # 1111 標注
        self.assertFalse(sig["watch"][0]["has_fut"])         # 2222 未標


if __name__ == "__main__":
    unittest.main()


class TestStacked(unittest.TestCase):
    def test_two_layer_stack(self):
        # 低箱 [80~88] 70天 → 突破 → 高箱 [100~110] 70天(今日在高箱)
        low_pre = [{"date": f"lp{i}", "open": 60, "high": 60, "low": 60,
                    "close": 60, "volume": 100} for i in range(70)]
        lseq = [80, 84, 88, 84]      # 低箱收盤震盪
        low_box = [{"date": f"lb{i}", "open": lseq[i % 4], "high": 88, "low": 80,
                    "close": lseq[i % 4], "volume": 25} for i in range(70)]
        hseq = [100, 105, 110, 105]  # 高箱收盤震盪
        high_box = [{"date": f"hb{i}", "open": hseq[i % 4], "high": 110,
                     "low": 100, "close": hseq[i % 4], "volume": 30}
                    for i in range(70)]
        s2 = low_pre + low_box + high_box
        top = lm.detect_matrix(s2)            # 最新 = 高箱
        self.assertIsNotNone(top)
        self.assertEqual(top["ceiling"], 110)
        layers = lm.count_stacked(s2, top)
        self.assertGreaterEqual(layers, 2)    # 高箱 + 低箱
