"""第二波分層標記單元測試。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tw_second_wave import classify_tier, TIER_EARLY_TVP, TIER_BIG_TURNOVER_NTD


class TestClassifyTier(unittest.TestCase):
    def test_star(self):
        self.assertEqual(classify_tier(0.85, 2_000_000_000), "⭐")

    def test_early_small(self):
        self.assertEqual(classify_tier(0.85, 100_000_000), "◐")

    def test_late(self):
        self.assertEqual(classify_tier(0.95, 2_000_000_000), "▽")

    def test_tvp_boundary_is_late(self):
        # 恰等於 0.88 → 不算早期
        self.assertEqual(classify_tier(TIER_EARLY_TVP, 2_000_000_000), "▽")

    def test_turnover_boundary_is_star(self):
        # 恰等於門檻 → 算大額
        self.assertEqual(classify_tier(0.80, TIER_BIG_TURNOVER_NTD), "⭐")


if __name__ == "__main__":
    unittest.main()
