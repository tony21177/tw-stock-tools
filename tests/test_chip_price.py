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


class TestStageBreakdown(unittest.TestCase):
    SAMPLE_ROWS = [
        # Early zone (low quartile): $100-105
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 101.0, "buy": 5000, "sell": 0},
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 102.0, "buy": 0, "sell": 200},
        # Mid zone: $105-115
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 110.0, "buy": 1000, "sell": 0},
        {"broker_id": "C001", "broker_name": "外資C",
         "price": 112.0, "buy": 800, "sell": 0},
        # Late zone (high quartile): $115-120
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 118.0, "buy": 0, "sell": 1500},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 119.0, "buy": 300, "sell": 0},
    ]

    def test_three_zones_partition(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        # Zones: early [100, 105], mid (105, 115], late (115, 120]
        self.assertIn("early", result)
        self.assertIn("mid", result)
        self.assertIn("late", result)

    def test_early_zone_top_buyer(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        early = result["early"]
        # A001 bought 5000 in early; B001 sold 200
        a = [r for r in early if r["broker_id"] == "A001"][0]
        self.assertEqual(a["buy_shares"], 5000)
        self.assertEqual(a["sell_shares"], 0)
        b = [r for r in early if r["broker_id"] == "B001"][0]
        self.assertEqual(b["sell_shares"], 200)

    def test_late_zone_top_seller(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        late = result["late"]
        # B001 sold 1500 in late; A001 bought 300
        b = [r for r in late if r["broker_id"] == "B001"][0]
        self.assertEqual(b["sell_shares"], 1500)


class TestBrokerFingerprint(unittest.TestCase):
    ROWS = [
        # 外資A — 累積買在 $100 / $110，少量在 $119
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 100.0, "buy": 5000, "sell": 0},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 110.0, "buy": 3000, "sell": 0},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 119.0, "buy": 500, "sell": 0},
        # 散戶B — 賣出集中 $118-120
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 118.0, "buy": 0, "sell": 1500},
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 120.0, "buy": 0, "sell": 800},
    ]

    def test_returns_top_n_brokers(self):
        from tw_chip_price import broker_fingerprint
        result = broker_fingerprint(self.ROWS, top_n=2)
        self.assertEqual(len(result["top_buyers"]), 1)  # only A001 net+
        self.assertEqual(result["top_buyers"][0]["broker_id"], "A001")
        self.assertEqual(len(result["top_sellers"]), 1)  # only B001 net-
        self.assertEqual(result["top_sellers"][0]["broker_id"], "B001")

    def test_top_buyer_price_summary(self):
        from tw_chip_price import broker_fingerprint
        result = broker_fingerprint(self.ROWS, top_n=2)
        a = result["top_buyers"][0]
        # A001: total +8500張, avg cost ≈ (5000×100 + 3000×110 + 500×119) / 8500
        self.assertEqual(a["net_shares"], 8500)
        # Avg cost: (500000 + 330000 + 59500) / 8500 = 104.65
        self.assertAlmostEqual(a["avg_price"], 104.65, places=1)
        self.assertEqual(a["price_range"], (100.0, 119.0))


if __name__ == "__main__":
    unittest.main()
