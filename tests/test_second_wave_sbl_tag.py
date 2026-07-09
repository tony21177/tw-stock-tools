"""第二波「借券急跌變化」標記單元測試。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tw_second_wave import classify_sbl_tag, SBL_TAG_DROP, SBL_TAG_RISE


class TestClassifySblTag(unittest.TestCase):
    def test_drop(self):
        self.assertEqual(classify_sbl_tag(-8.0), "借↓")

    def test_rise(self):
        self.assertEqual(classify_sbl_tag(8.0), "借↑")

    def test_flat(self):
        self.assertEqual(classify_sbl_tag(0.0), "—")

    def test_none(self):
        self.assertEqual(classify_sbl_tag(None), "—")

    def test_drop_boundary(self):
        # 恰等於 -5.0 → 借↓
        self.assertEqual(classify_sbl_tag(SBL_TAG_DROP), "借↓")

    def test_rise_boundary(self):
        # 恰等於 +5.0 → 借↑
        self.assertEqual(classify_sbl_tag(SBL_TAG_RISE), "借↑")


if __name__ == "__main__":
    unittest.main()
