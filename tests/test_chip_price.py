"""Unit tests for chip-price analysis (parser, stage, fingerprint)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from bsr_scraper import _parse_bsr_csv_with_prices


# Realistic CSV slice — left/right two-record pairs, broker like "1020合　　庫"
SAMPLE_CSV = """\
證券代號 ,2313,證券名稱 ,華通
99/05/12,日期
序,證券商,成交單價,買進股數,賣出股數,,序,證券商,成交單價,買進股數,賣出股數
1,1020合　　庫,249.00,5000,0,,2,1020合　　庫,251.00,0,1000
3,1020合　　庫,251.50,0,1000,,4,8888國泰敦南,264.00,0,3100
"""


class TestParseBsrCsvWithPrices(unittest.TestCase):
    def test_basic_two_pair_row(self):
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        # 4 records expected from 2 lines × 2 pairs
        self.assertEqual(len(rows), 4)

    def test_first_row_shape(self):
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        r = rows[0]
        self.assertEqual(r["broker_id"], "1020")
        self.assertEqual(r["broker_name"], "合 庫")  # double-width space collapsed
        self.assertEqual(r["price"], 249.0)
        self.assertEqual(r["buy"], 5000)
        self.assertEqual(r["sell"], 0)

    def test_skips_blank_broker(self):
        # Add a row with empty broker column — should be dropped
        csv_with_blank = SAMPLE_CSV + "5,,255.00,1000,0,,6,1020合　　庫,256.00,2000,0\n"
        rows = _parse_bsr_csv_with_prices(csv_with_blank)
        # Blank pair skipped, only the right side of last line counted: 4 existing + 1 right-side = 5
        self.assertEqual(len(rows), 5)
        broker_ids = [r["broker_id"] for r in rows]
        self.assertNotIn("", broker_ids)

    def test_broker_id_extraction(self):
        # broker like "8888國泰敦南" — id is first 4 chars
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        last = [r for r in rows if r["broker_id"] == "8888"]
        self.assertEqual(len(last), 1)
        self.assertEqual(last[0]["broker_name"], "國泰敦南")
        self.assertEqual(last[0]["price"], 264.0)
        self.assertEqual(last[0]["sell"], 3100)


class TestOhlcFromFinmind(unittest.TestCase):
    def test_returns_dict_with_required_keys(self):
        from tw_chip_price import get_ohlc
        result = get_ohlc("2330")
        # Real network — skip if no token or bad day
        if not result:
            self.skipTest("No FINMIND_TOKEN or no recent OHLC data")
        for k in ("open", "high", "low", "close"):
            self.assertIn(k, result)
            self.assertGreater(result[k], 0)


if __name__ == "__main__":
    unittest.main()
