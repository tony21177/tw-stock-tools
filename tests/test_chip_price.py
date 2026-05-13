"""Unit tests for chip-price analysis (parser, stage, fingerprint)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from bsr_scraper import _parse_bsr_csv_with_prices, _parse_bsr_date


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


class TestParseBsrDate(unittest.TestCase):
    def test_roc_year_three_digit(self):
        # 115/05/12 → ROC 115 = AD 2026 → "20260512"
        csv = "證券代號 ,2313,證券名稱 ,華通\n115/05/12,日期\n序,...\n"
        self.assertEqual(_parse_bsr_date(csv), "20260512")

    def test_roc_year_two_digit(self):
        # 99/05/12 → ROC 99 = AD 2010 → "20100512"
        self.assertEqual(_parse_bsr_date(SAMPLE_CSV), "20100512")

    def test_single_digit_month_day_padded(self):
        csv = "header\n115/5/3,日期\nrest\n"
        self.assertEqual(_parse_bsr_date(csv), "20260503")

    def test_missing_date_returns_empty(self):
        csv = "header\nno date here\nrest\n"
        self.assertEqual(_parse_bsr_date(csv), "")

    def test_empty_text_returns_empty(self):
        self.assertEqual(_parse_bsr_date(""), "")


class TestBrokerConcentrationBand(unittest.TestCase):
    def test_tight_cluster_narrows_to_few_cells(self):
        from tw_chip_price import broker_concentration_band
        # 80% of buy volume sits in $258-$262 (3 cells, 8500 of 10000)
        cells = [
            {"price": 246.0, "buy": 500, "sell": 0},
            {"price": 250.0, "buy": 1000, "sell": 0},
            {"price": 258.0, "buy": 3000, "sell": 0},
            {"price": 260.0, "buy": 3000, "sell": 0},
            {"price": 262.0, "buy": 2500, "sell": 0},
        ]
        band = broker_concentration_band(cells, side="buy", threshold=0.7)
        # Need 70% of 10000 = 7000. Smallest window covering 7000+:
        # $258-$262 covers 8500 (3 cells, $4 wide).
        self.assertEqual(band["core_low"], 258.0)
        self.assertEqual(band["core_high"], 262.0)
        self.assertEqual(band["core_volume"], 8500)
        self.assertAlmostEqual(band["core_pct"], 0.85, places=2)
        self.assertEqual(band["total_volume"], 10000)

    def test_returns_none_for_zero_side_volume(self):
        from tw_chip_price import broker_concentration_band
        cells = [
            {"price": 100.0, "buy": 0, "sell": 500},  # all sells, no buys
        ]
        self.assertIsNone(
            broker_concentration_band(cells, side="buy", threshold=0.7)
        )

    def test_single_cell_returns_zero_width(self):
        from tw_chip_price import broker_concentration_band
        cells = [{"price": 100.0, "buy": 5000, "sell": 0}]
        band = broker_concentration_band(cells, side="buy", threshold=0.7)
        self.assertEqual(band["core_low"], 100.0)
        self.assertEqual(band["core_high"], 100.0)
        self.assertEqual(band["core_pct"], 1.0)

    def test_sell_side_works_same_way(self):
        from tw_chip_price import broker_concentration_band
        cells = [
            {"price": 100.0, "buy": 0, "sell": 100},
            {"price": 110.0, "buy": 0, "sell": 800},
            {"price": 111.0, "buy": 0, "sell": 600},
            {"price": 120.0, "buy": 0, "sell": 100},
        ]
        # 70% of 1600 = 1120. $110-$111 covers 1400 (2 cells, $1 wide).
        band = broker_concentration_band(cells, side="sell", threshold=0.7)
        self.assertEqual(band["core_low"], 110.0)
        self.assertEqual(band["core_high"], 111.0)


class TestBrokerTopCells(unittest.TestCase):
    def test_top_3_by_buy_volume(self):
        from tw_chip_price import broker_top_cells
        cells = [
            {"price": 100.0, "buy": 500, "sell": 100},
            {"price": 102.0, "buy": 5000, "sell": 0},
            {"price": 105.0, "buy": 1500, "sell": 200},
            {"price": 108.0, "buy": 800, "sell": 0},
            {"price": 110.0, "buy": 0, "sell": 1000},
        ]
        top = broker_top_cells(cells, side="buy", n=3)
        self.assertEqual([c["price"] for c in top], [102.0, 105.0, 108.0])

    def test_excludes_zero_volume_on_chosen_side(self):
        from tw_chip_price import broker_top_cells
        cells = [
            {"price": 100.0, "buy": 500, "sell": 0},
            {"price": 110.0, "buy": 0, "sell": 1000},
        ]
        # Only $100 has buy > 0
        top = broker_top_cells(cells, side="buy", n=3)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["price"], 100.0)


class TestHistoryArchive(unittest.TestCase):
    def setUp(self):
        import tempfile, tw_chip_price
        self.tmp = tempfile.mkdtemp(prefix="chip_price_history_test_")
        # Patch HISTORY_DIR for isolation
        self._orig_dir = tw_chip_price.HISTORY_DIR
        tw_chip_price.HISTORY_DIR = self.tmp

    def tearDown(self):
        import shutil, tw_chip_price
        tw_chip_price.HISTORY_DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_record(self, code: str, date: str, top_buyer_id: str = "A") -> dict:
        return {
            "stock_code": code,
            "name": code,
            "date": date,
            "ohlc": {"open": 100.0, "high": 110.0, "low": 100.0, "close": 105.0},
            "total_buy_shares": 1000000,
            "total_sell_shares": 1000000,
            "top_cells": [],
            "stage": {"early": [], "mid": [], "late": []},
            "fingerprint": {
                "top_buyers": [{"broker_id": top_buyer_id, "broker_name": "X",
                                "net_shares": 1000, "avg_price": 100.0,
                                "price_range": (100.0, 110.0)}],
                "top_sellers": [],
            },
        }

    def test_save_and_load_roundtrip(self):
        from tw_chip_price import save_history, load_history
        save_history(self._make_record("2313", "20260512"))
        out = load_history("2313", days=10, base_dir=self.tmp)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["date"], "20260512")

    def test_load_returns_newest_first(self):
        from tw_chip_price import save_history, load_history
        for d in ("20260508", "20260512", "20260510"):
            save_history(self._make_record("2313", d))
        out = load_history("2313", days=10, base_dir=self.tmp)
        self.assertEqual([r["date"] for r in out],
                         ["20260512", "20260510", "20260508"])

    def test_save_prunes_to_keep_window(self):
        from tw_chip_price import save_history, load_history
        for d in ("20260501", "20260502", "20260503", "20260504",
                  "20260505", "20260506", "20260507", "20260508",
                  "20260509", "20260510", "20260511", "20260512"):
            save_history(self._make_record("2313", d), days_to_keep=10)
        out = load_history("2313", days=20, base_dir=self.tmp)
        # 12 written, only 10 kept (newest 10)
        self.assertEqual(len(out), 10)
        self.assertEqual(out[0]["date"], "20260512")
        self.assertEqual(out[-1]["date"], "20260503")

    def test_load_isolates_by_stock_code(self):
        from tw_chip_price import save_history, load_history
        save_history(self._make_record("2313", "20260512"))
        save_history(self._make_record("2330", "20260512"))
        self.assertEqual(len(load_history("2313", base_dir=self.tmp)), 1)
        self.assertEqual(len(load_history("9999", base_dir=self.tmp)), 0)

    def test_save_skips_when_missing_keys(self):
        from tw_chip_price import save_history, load_history
        save_history({"stock_code": "2313"})  # missing date
        save_history({"date": "20260512"})  # missing stock_code
        self.assertEqual(load_history("2313", base_dir=self.tmp), [])


class TestTimeStageBreakdown(unittest.TestCase):
    def test_buckets_by_time_not_price(self):
        from tw_chip_price import time_stage_breakdown
        # Same price ($100) traded at two different times:
        # broker A buys 1000 early (minute 30 = ~09:30)
        # broker B sells 800 late  (minute 240 = ~13:00)
        # Both at $100 — price-quartile stage would group them together;
        # time-stage should split them.
        rows = [
            {"broker_id": "A", "broker_name": "A", "price": 100.0,
             "buy": 1000, "sell": 0},
            {"broker_id": "B", "broker_name": "B", "price": 100.0,
             "buy": 0, "sell": 800},
        ]
        # Note: price_to_time map has ONE entry per price. So we can't model
        # "same price traded at 2 different times" with the current map shape.
        # Test the simpler case: distinct prices land in distinct zones.
        rows2 = [
            {"broker_id": "A", "broker_name": "A", "price": 100.0,
             "buy": 1000, "sell": 0},   # price → 30 min
            {"broker_id": "B", "broker_name": "B", "price": 105.0,
             "buy": 500, "sell": 0},    # price → 135 min (mid)
            {"broker_id": "C", "broker_name": "C", "price": 110.0,
             "buy": 0, "sell": 800},    # price → 240 min (late)
        ]
        price_to_time = {100.0: 30.0, 105.0: 135.0, 110.0: 240.0}
        result = time_stage_breakdown(rows2, price_to_time,
                                       session_minutes=270.0)
        early_bids = [r["broker_id"] for r in result["early"]]
        mid_bids = [r["broker_id"] for r in result["mid"]]
        late_bids = [r["broker_id"] for r in result["late"]]
        self.assertIn("A", early_bids)
        self.assertIn("B", mid_bids)
        self.assertIn("C", late_bids)
        # A is only in early, not in mid/late
        self.assertNotIn("A", mid_bids)
        self.assertNotIn("A", late_bids)

    def test_skips_rows_without_time_mapping(self):
        from tw_chip_price import time_stage_breakdown
        rows = [
            {"broker_id": "A", "broker_name": "A", "price": 100.0,
             "buy": 1000, "sell": 0},
            {"broker_id": "B", "broker_name": "B", "price": 999.0,
             "buy": 500, "sell": 0},  # 999 not in map → dropped
        ]
        price_to_time = {100.0: 30.0}
        result = time_stage_breakdown(rows, price_to_time)
        all_bids = ([r["broker_id"] for r in result["early"]]
                    + [r["broker_id"] for r in result["mid"]]
                    + [r["broker_id"] for r in result["late"]])
        self.assertIn("A", all_bids)
        self.assertNotIn("B", all_bids)

    def test_empty_map_returns_empty_zones(self):
        from tw_chip_price import time_stage_breakdown
        rows = [{"broker_id": "A", "broker_name": "A", "price": 100.0,
                 "buy": 1000, "sell": 0}]
        result = time_stage_breakdown(rows, {})
        self.assertEqual(result, {"early": [], "mid": [], "late": []})


class TestBrokerWashCandidates(unittest.TestCase):
    def test_detects_high_sell_low_buy_pattern(self):
        from tw_chip_price import broker_wash_candidates
        # Broker A: sold 5000 @$245, bought 3000 @$238 → wash_score positive
        # Broker B: sold 100 @$240, bought 8000 @$245 → wash_score negative
        # Broker C: only buys 5000 @$240 → one-sided, skipped
        rows = [
            {"broker_id": "A", "broker_name": "A", "price": 245.0,
             "buy": 0, "sell": 5000},
            {"broker_id": "A", "broker_name": "A", "price": 238.0,
             "buy": 3000, "sell": 0},
            {"broker_id": "B", "broker_name": "B", "price": 240.0,
             "buy": 0, "sell": 100},
            {"broker_id": "B", "broker_name": "B", "price": 245.0,
             "buy": 8000, "sell": 0},
            {"broker_id": "C", "broker_name": "C", "price": 240.0,
             "buy": 5000, "sell": 0},
        ]
        result = broker_wash_candidates(
            rows, day_low=235.0, day_high=250.0, top_n=5, min_each_side=50,
        )
        # Only A qualifies (B has negative wash, C is one-sided)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["broker_id"], "A")
        self.assertEqual(result[0]["buy_shares"], 3000)
        self.assertEqual(result[0]["sell_shares"], 5000)
        self.assertAlmostEqual(result[0]["sell_avg"], 245.0, places=2)
        self.assertAlmostEqual(result[0]["buy_avg"], 238.0, places=2)
        # day range = 15, gap = 7 → wash_score ≈ 0.467
        self.assertAlmostEqual(result[0]["wash_score"], 7.0 / 15.0, places=2)
        self.assertEqual(result[0]["price_gap"], 7.0)
        self.assertEqual(result[0]["net_shares"], -2000)

    def test_skips_one_sided_brokers(self):
        from tw_chip_price import broker_wash_candidates
        rows = [
            {"broker_id": "A", "broker_name": "A", "price": 245.0,
             "buy": 0, "sell": 5000},
            {"broker_id": "B", "broker_name": "B", "price": 238.0,
             "buy": 3000, "sell": 0},
        ]
        # A is pure seller, B is pure buyer → no wash candidates
        result = broker_wash_candidates(
            rows, day_low=235.0, day_high=250.0, min_each_side=50,
        )
        self.assertEqual(result, [])

    def test_skips_negative_wash_score(self):
        from tw_chip_price import broker_wash_candidates
        # A bought higher than sold (追漲後賣) — negative wash, excluded
        rows = [
            {"broker_id": "A", "broker_name": "A", "price": 240.0,
             "buy": 0, "sell": 200},
            {"broker_id": "A", "broker_name": "A", "price": 248.0,
             "buy": 3000, "sell": 0},
        ]
        result = broker_wash_candidates(
            rows, day_low=235.0, day_high=250.0, min_each_side=100,
        )
        self.assertEqual(result, [])


class TestBrokerBandProgression(unittest.TestCase):
    def setUp(self):
        import tempfile, tw_chip_price
        self.tmp = tempfile.mkdtemp(prefix="chip_price_progress_test_")
        self._orig_dir = tw_chip_price.HISTORY_DIR
        tw_chip_price.HISTORY_DIR = self.tmp

    def tearDown(self):
        import shutil, tw_chip_price
        tw_chip_price.HISTORY_DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_history(self, code: str, date: str,
                       broker_id: str, cells: list[dict]) -> None:
        record = {
            "stock_code": code,
            "date": date,
            "fingerprint": {
                "top_buyers": [{
                    "broker_id": broker_id,
                    "broker_name": broker_id,
                    "cells": cells,
                }],
                "top_sellers": [],
            },
        }
        from tw_chip_price import save_history
        save_history(record, days_to_keep=10)

    def test_progression_returns_per_day_band(self):
        from tw_chip_price import broker_band_progression
        # 3 days with shifting buy band
        self._write_history("2313", "20260510", "1480", [
            {"price": 245.0, "buy": 2000, "sell": 0},
            {"price": 250.0, "buy": 3000, "sell": 0},
        ])
        self._write_history("2313", "20260511", "1480", [
            {"price": 252.0, "buy": 2000, "sell": 0},
            {"price": 256.0, "buy": 3000, "sell": 0},
        ])
        self._write_history("2313", "20260512", "1480", [
            {"price": 260.0, "buy": 3000, "sell": 0},
            {"price": 263.0, "buy": 2000, "sell": 0},
        ])
        prog = broker_band_progression("2313", "1480", side="buy", n_days=5)
        self.assertEqual(len(prog), 3)
        # Sorted asc by date
        self.assertEqual([p["date"] for p in prog],
                         ["20260510", "20260511", "20260512"])
        # Lows should shift upward
        lows = [p["low"] for p in prog]
        self.assertLess(lows[0], lows[1])
        self.assertLess(lows[1], lows[2])

    def test_progression_skips_days_without_broker(self):
        from tw_chip_price import broker_band_progression
        # Broker 1480 only appears 5/10, missing 5/11
        self._write_history("2313", "20260510", "1480", [
            {"price": 245.0, "buy": 5000, "sell": 0},
        ])
        # Day with different top buyer
        self._write_history("2313", "20260511", "9999", [
            {"price": 250.0, "buy": 5000, "sell": 0},
        ])
        prog = broker_band_progression("2313", "1480", side="buy", n_days=5)
        # Only 5/10 has 1480 — should return single entry
        self.assertEqual(len(prog), 1)
        self.assertEqual(prog[0]["date"], "20260510")

    def test_progression_empty_when_no_history(self):
        from tw_chip_price import broker_band_progression
        self.assertEqual(
            broker_band_progression("9999", "1480", side="buy", n_days=5),
            [],
        )


class TestContinuityFooter(unittest.TestCase):
    def setUp(self):
        import tempfile, tw_chip_price
        self.tmp = tempfile.mkdtemp(prefix="chip_price_cont_test_")
        self._orig_dir = tw_chip_price.HISTORY_DIR
        tw_chip_price.HISTORY_DIR = self.tmp

    def tearDown(self):
        import shutil, tw_chip_price
        tw_chip_price.HISTORY_DIR = self._orig_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _record(self, date: str, top_buyer_ids: list[str],
                top_seller_ids: list[str]) -> dict:
        return {
            "stock_code": "2313",
            "date": date,
            "fingerprint": {
                "top_buyers": [{"broker_id": bid, "broker_name": bid}
                               for bid in top_buyer_ids],
                "top_sellers": [{"broker_id": sid, "broker_name": sid}
                                for sid in top_seller_ids],
            },
        }

    def test_continuity_counts_appearances(self):
        from tw_chip_price import save_history, _format_continuity
        # 3 history days: 高盛 (G) in top 3 buyers on 2 of them
        save_history(self._record("20260510", ["G", "X"], ["K"]))
        save_history(self._record("20260511", ["G", "Y"], ["K"]))
        save_history(self._record("20260509", ["Z"], ["K"]))
        today = self._record("20260512", ["G"], ["K"])
        lines = _format_continuity(today, days=5)
        joined = "\n".join(lines)
        self.assertIn("近 3", joined)
        self.assertIn("G 2/3", joined)
        self.assertIn("K 3/3", joined)

    def test_empty_history_returns_empty_list(self):
        from tw_chip_price import _format_continuity
        today = self._record("20260512", ["G"], ["K"])
        self.assertEqual(_format_continuity(today, days=5), [])


class TestInferBsrTradingDate(unittest.TestCase):
    def test_returns_empty_when_no_rows(self):
        from tw_chip_price import infer_bsr_trading_date
        self.assertEqual(infer_bsr_trading_date("2313", []), "")

    def test_returns_empty_when_no_token(self):
        from tw_chip_price import infer_bsr_trading_date
        import tw_chip_price as mod
        original = mod._get_token
        mod._get_token = lambda: ""
        try:
            rows = [{"price": 100.0, "buy": 1000, "sell": 0}]
            self.assertEqual(infer_bsr_trading_date("2313", rows), "")
        finally:
            mod._get_token = original

    def test_matches_day_by_volume(self):
        """Stub finmind_client; confirm volume match wins over price-range."""
        from tw_chip_price import infer_bsr_trading_date
        import tw_chip_price as mod
        original_token = mod._get_token
        original_finmind = sys.modules.get("finmind_client")
        mod._get_token = lambda: "stub_token"
        import types
        fake = types.SimpleNamespace()
        fake.fetch_stock_price = lambda code, start, end, token: [
            {"date": "2026-05-11", "max": 254.5, "min": 242.0, "Trading_Volume": 81477797},
            {"date": "2026-05-12", "max": 264.5, "min": 246.0, "Trading_Volume": 93921908},
            {"date": "2026-05-13", "max": 258.5, "min": 237.0, "Trading_Volume": 91042000},
        ]
        sys.modules["finmind_client"] = fake
        try:
            bsr_rows = [{"price": 246.0, "buy": 93921908, "sell": 0}]
            result = infer_bsr_trading_date("2313", bsr_rows, target="20260513")
            self.assertEqual(result, "20260512")
        finally:
            mod._get_token = original_token
            if original_finmind is not None:
                sys.modules["finmind_client"] = original_finmind
            else:
                sys.modules.pop("finmind_client", None)


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


class TestTopCells(unittest.TestCase):
    ROWS = [
        # Big buy cells at low prices (early)
        {"broker_id": "G", "broker_name": "高盛", "price": 100.0, "buy": 10000, "sell": 0},
        {"broker_id": "G", "broker_name": "高盛", "price": 119.0, "buy": 2000, "sell": 0},
        # Big sell cells at high prices (late)
        {"broker_id": "K", "broker_name": "國泰", "price": 120.0, "buy": 0, "sell": 8000},
        # Small noise
        {"broker_id": "X", "broker_name": "X", "price": 110.0, "buy": 100, "sell": 50},
    ]

    def test_top_cells_sorted_by_abs_volume(self):
        from tw_chip_price import top_cells
        result = top_cells(self.ROWS, top_n=3)
        # Largest cell is 高盛 @100 buy 10000
        self.assertEqual(result[0]["broker_id"], "G")
        self.assertEqual(result[0]["price"], 100.0)
        self.assertEqual(result[0]["volume"], 10000)
        self.assertEqual(result[0]["side"], "buy")

    def test_direction_tag_price_fallback(self):
        from tw_chip_price import top_cells
        # No price_to_time → fall back to price-quartile labels:
        # 高盛 buy at $100 (low 25% of [100,120]) → 低檔搶進
        # 國泰 sell at $120 (high 25%) → 高檔倒貨
        result = top_cells(self.ROWS, top_n=4, low=100.0, high=120.0)
        early_buy = [r for r in result
                     if r["broker_id"] == "G" and r["price"] == 100.0][0]
        self.assertEqual(early_buy["zone"], "early")
        self.assertIn("低檔搶進", early_buy["tag"])
        late_sell = [r for r in result
                     if r["broker_id"] == "K" and r["price"] == 120.0][0]
        self.assertEqual(late_sell["zone"], "late")
        self.assertIn("高檔倒貨", late_sell["tag"])

    def test_direction_tag_time_based(self):
        from tw_chip_price import top_cells
        # With price_to_time, tags describe REAL time-of-day, not price level.
        # Map prices to minutes from 09:00 open (session 270 min):
        #   $100 was traded mostly late in session (minute 240)
        #   $120 was traded mostly early in session (minute 30)
        # So buy@$100 → "尾盤買進" (late zone), sell@$120 → "早盤賣壓" (early)
        # Price-only logic would give the opposite labels.
        price_to_time = {100.0: 240.0, 119.0: 100.0, 120.0: 30.0, 110.0: 135.0}
        result = top_cells(self.ROWS, top_n=4, low=100.0, high=120.0,
                            price_to_time=price_to_time)
        c100_buy = [r for r in result
                    if r["broker_id"] == "G" and r["price"] == 100.0][0]
        self.assertEqual(c100_buy["zone"], "late")
        self.assertIn("尾盤買進", c100_buy["tag"])
        c120_sell = [r for r in result
                     if r["broker_id"] == "K" and r["price"] == 120.0][0]
        self.assertEqual(c120_sell["zone"], "early")
        self.assertIn("早盤賣壓", c120_sell["tag"])


class TestFormatReport(unittest.TestCase):
    def test_report_includes_header_and_sections(self):
        from tw_chip_price import format_report
        data = {
            "stock_code": "2313",
            "name": "華通",
            "date": "20260512",
            "ohlc": {"open": 246.0, "high": 264.5, "low": 246.0, "close": 260.0},
            "total_buy_shares": 93922000,
            "total_sell_shares": 93922000,
            "top_cells": [
                {"broker_id": "1480", "broker_name": "美商高盛",
                 "price": 246.5, "side": "buy", "volume": 8200000,
                 "zone": "early", "tag": "⬇ 早盤搶低"},
            ],
            "stage": {"early": [], "mid": [], "late": []},
            "fingerprint": {"top_buyers": [], "top_sellers": []},
        }
        report = format_report(data)
        # Header
        self.assertIn("2313", report)
        self.assertIn("華通", report)
        self.assertIn("246.00", report)
        self.assertIn("260.00", report)
        # Top cells section
        self.assertIn("Top", report)
        self.assertIn("8,200", report)  # 8200000 shares / 1000 = 8200 張
        self.assertIn("早盤搶低", report)
        # Section headers
        self.assertIn("三階段", report)
        self.assertIn("價格指紋", report)

    def test_negative_net_shares_formats_correctly(self):
        from tw_chip_price import _fmt_zhang
        # -1500 should render as "-1", not "-2" (no floor-div bug)
        self.assertEqual(_fmt_zhang(-1500), "-1")
        # -2999 should render as "-2"
        self.assertEqual(_fmt_zhang(-2999), "-2")
        # Positive still works
        self.assertEqual(_fmt_zhang(8200000), "8,200")
        # Zero
        self.assertEqual(_fmt_zhang(0), "0")

    def test_format_report_handles_partial_stage(self):
        from tw_chip_price import format_report
        data = {
            "stock_code": "0000",
            "name": "test",
            "date": "20260512",
            "ohlc": {"open": 100.0, "high": 110.0, "low": 100.0, "close": 105.0},
            "total_buy_shares": 1000000,
            "total_sell_shares": 1000000,
            "top_cells": [],
            # Note: missing "mid" and "late" keys
            "stage": {"early": []},
            "fingerprint": {"top_buyers": [], "top_sellers": []},
        }
        # Should not raise KeyError
        report = format_report(data)
        self.assertIn("三階段", report)


if __name__ == "__main__":
    unittest.main()
