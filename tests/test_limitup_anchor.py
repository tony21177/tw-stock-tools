"""A/D 訊號的 anchor 對齊：盤前模式必須看得到最新一根 K 棒。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tw_limitup_signal import signal_a_relay, signal_d_volume


def _px(closes, volumes=None, opens=None):
    volumes = volumes or [1000] * len(closes)
    opens = opens or closes
    return [{"date": f"2026-06-{i+1:02d}", "open": o, "close": c,
             "high": c, "low": c, "volume": v}
            for i, (c, v, o) in enumerate(zip(closes, volumes, opens))]


class TestAnchorA(unittest.TestCase):
    def test_premarket_sees_latest_bar_jump(self):
        # 最新一根 +9.9%，之前全平 → 盤前(anchor=len)應 ✅，盤後(預設)應 ❌
        closes = [100.0] * 10 + [109.9]
        px = _px(closes)
        ok_post, _ = signal_a_relay(px)                    # 舊行為：不含最新根
        ok_pre, _ = signal_a_relay(px, anchor=len(px))     # 盤前：含最新根
        self.assertFalse(ok_post)
        self.assertTrue(ok_pre)

    def test_postclose_unchanged(self):
        # 倒數第 2 根 +6% → 盤後模式維持 ✅ (與現有行為一致)
        closes = [100.0] * 9 + [106.0, 106.5]
        ok, _ = signal_a_relay(_px(closes))
        self.assertTrue(ok)


class TestAnchorD(unittest.TestCase):
    def test_premarket_uses_latest_volume(self):
        # 最新一根量 3x 均量 → 盤前 ✅；盤後看倒數第 2 根(量=均量的1.0x) 也 ✅
        vols = [1000] * 24 + [1000, 3000]
        closes = [100.0] * 26
        ok_pre, msg = signal_d_volume(_px(closes, vols), anchor=26)
        self.assertTrue(ok_pre, msg)
        # 最新根爆量但倒數第2根縮量 → 盤後 ❌、盤前 ✅
        vols2 = [1000] * 24 + [400, 3000]
        ok_post, _ = signal_d_volume(_px(closes, vols2))
        ok_pre2, _ = signal_d_volume(_px(closes, vols2), anchor=26)
        self.assertFalse(ok_post)
        self.assertTrue(ok_pre2)

    def test_postclose_len22_boundary(self):
        # 恰 22 根 K 棒：舊版允許 (len<22 才擋)，anchor=21 必須能算 D
        vols = [1000] * 21 + [3000]
        closes = [100.0] * 22
        ok, msg = signal_d_volume(_px(closes, vols))
        self.assertNotIn("資料不足", msg)

    def test_postclose_len62_60d_branch(self):
        # 恰 62 根：前日量 = 20d 均的 0.948x 但 60d 均的 1.684x → True
        # 數據設計：41 根 400量 + 19 根 1200量 + 1 根 1100量 + 1 根 1000量
        # prev_vol = vols[60] = 1100
        # win20 = vols[40:60] = [400] + [1200]*19 = sum 23200, avg 1160 → ratio 0.948 < 1.0
        # win60 = vols[0:60] = [400]*41 + [1200]*19 = sum 39200, avg 653.33 → ratio 1.684 >= 1.5
        vols = [400] * 41 + [1200] * 19 + [1100, 1000]
        closes = [100.0] * 62
        ok, msg = signal_d_volume(_px(closes, vols))
        self.assertTrue(ok, msg)
        self.assertIn("60d", msg)


if __name__ == "__main__":
    unittest.main()
