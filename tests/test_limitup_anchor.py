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


if __name__ == "__main__":
    unittest.main()
