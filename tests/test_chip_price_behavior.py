"""Tests for tw_chip_price 分點行為序列 (multi-day broker behavior series)."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from tw_chip_price import (  # noqa: E402
    classify_broker_type,
    _broker_day_stats,
    _load_day_broker_stats,
    build_behavior_series,
    _format_behavior,
    _fmt_k,
)


class TestClassifyBrokerType(unittest.TestCase):
    def test_foreign(self):
        for name in ["台灣摩根", "摩根大通", "美商高盛", "港商野村",
                     "美林", "瑞銀", "花旗環球", "上海匯豐", "新加坡商瑞銀"]:
            self.assertEqual(classify_broker_type(name), "foreign", name)

    def test_domestic_prefix_beats_foreign_fragment(self):
        # 群益高盛 is a 群益 branch, not Goldman Sachs
        self.assertEqual(classify_broker_type("群益高盛"), "domestic")
        self.assertEqual(classify_broker_type("永豐匯立"), "domestic")

    def test_retail_proxy(self):
        self.assertEqual(classify_broker_type("永豐金"), "retail_proxy")
        self.assertEqual(classify_broker_type("國泰敦南"), "retail_proxy")
        # but 永豐金 branches are plain domestic
        self.assertEqual(classify_broker_type("永豐金板橋"), "domestic")

    def test_space_stripping(self):
        self.assertEqual(classify_broker_type("瑞　銀"), "foreign")
        self.assertEqual(classify_broker_type("合 庫"), "domestic")


def _row(bid, name, price, buy=0, sell=0):
    return {"broker_id": bid, "broker_name": name, "price": price,
            "buy": buy, "sell": sell}


def _write_prices(cache_dir, code, date, rows):
    with open(os.path.join(cache_dir, f"{code}_{date}_prices.json"),
              "w") as f:
        json.dump({"date": date, "stock_code": code, "rows": rows}, f,
                  ensure_ascii=False)


def _write_plain(cache_dir, code, date, brokers):
    with open(os.path.join(cache_dir, f"{code}_{date}.json"), "w") as f:
        json.dump({"date": date, "stock_code": code, "brokers": brokers}, f,
                  ensure_ascii=False)


class TestLoadDayBrokerStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_prices_file_preferred(self):
        _write_prices(self.dir, "2313", "20260716", [
            _row("1480", "美商高盛", 241.0, buy=1000_000, sell=200_000),
            _row("1480", "美商高盛", 243.0, buy=0, sell=800_000),
        ])
        s = _load_day_broker_stats("2313", "20260716", cache_dir=self.dir)
        gs = s["1480"]
        self.assertEqual(gs["net"], 0)
        self.assertAlmostEqual(gs["buy_avg"], 241.0)
        self.assertAlmostEqual(gs["sell_avg"], 242.6)

    def test_plain_fallback_no_avgs(self):
        _write_plain(self.dir, "2313", "20260714",
                     {"9800": {"name": "元 大", "buy": 500_000,
                               "sell": 100_000}})
        s = _load_day_broker_stats("2313", "20260714", cache_dir=self.dir)
        self.assertEqual(s["9800"]["net"], 400_000)
        self.assertEqual(s["9800"]["buy_avg"], 0.0)
        self.assertEqual(s["9800"]["broker_name"], "元大")

    def test_missing_returns_none(self):
        self.assertIsNone(
            _load_day_broker_stats("2313", "20260701", cache_dir=self.dir))


class TestBuildBehaviorSeries(unittest.TestCase):
    """3-day window: 高盛 buys big day2 then dumps day3 (隔日沖 pattern
    visible in the sequence); 台灣摩根 buys every day; 永豐金 chases on
    day3; day1 is plain-cache only (no avgs)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        _write_plain(self.dir, "2313", "20260714", {
            "1470": {"name": "台灣摩根", "buy": 800_000, "sell": 0},
            "1480": {"name": "美商高盛", "buy": 100_000, "sell": 150_000},
        })
        _write_prices(self.dir, "2313", "20260715", [
            _row("1470", "台灣摩根", 244.0, buy=6_066_000),
            _row("1480", "美商高盛", 243.0, buy=6_041_000),
            _row("9A00", "永豐金", 244.0, sell=562_000),
        ])
        _write_prices(self.dir, "2313", "20260716", [
            _row("1470", "台灣摩根", 241.6, buy=1_730_000),
            _row("1480", "美商高盛", 241.2, buy=1_058_000,
                 sell=3_623_000),
            _row("9A00", "永豐金", 243.6, buy=423_000),
            _row("9216", "凱基信義", 241.8, sell=2_147_000),
        ])
        self.ohlc = {
            "20260715": {"low": 240.0, "high": 248.0, "close": 247.0},
            "20260716": {"low": 235.0, "high": 248.0, "close": 236.5},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _view(self):
        return build_behavior_series("2313", "20260716", days=10,
                                     ohlc_map=self.ohlc,
                                     cache_dir=self.dir)

    def test_window_and_groups(self):
        v = self._view()
        self.assertEqual(v["dates"], ["20260714", "20260715", "20260716"])
        foreign_ids = [b["broker_id"] for b in v["groups"]["foreign"]]
        self.assertIn("1470", foreign_ids)
        self.assertIn("1480", foreign_ids)
        self.assertEqual(
            [b["broker_id"] for b in v["groups"]["domestic_sell"]],
            ["9216"])
        self.assertEqual(
            [b["broker_id"] for b in v["groups"]["retail"]], ["9A00"])

    def test_series_sequence_and_cum(self):
        v = self._view()
        gs = next(b for b in v["groups"]["foreign"]
                  if b["broker_id"] == "1480")
        nets = [s["net"] for s in gs["series"]]
        self.assertEqual(nets, [-50_000, 6_041_000, -2_565_000])
        self.assertEqual(gs["cum_net"], sum(nets))
        self.assertEqual(gs["today_net"], -2_565_000)

    def test_pos_uses_dominant_side_and_needs_ohlc(self):
        v = self._view()
        gs = next(b for b in v["groups"]["foreign"]
                  if b["broker_id"] == "1480")
        d1, d2, d3 = gs["series"]
        self.assertIsNone(d1["pos"])          # plain cache: no avg prices
        self.assertAlmostEqual(d2["pos"], 0.38, places=2)  # buy 243 in 240-248
        self.assertAlmostEqual(d3["pos"], 0.48, places=2)  # sell 241.2 in 235-248

    def test_missing_day_is_none(self):
        # 台灣摩根 absent on no day here, but 凱基信義 only traded day3
        v = self._view()
        kgi = v["groups"]["domestic_sell"][0]
        self.assertIsNone(kgi["series"][0]["net"])
        self.assertIsNone(kgi["series"][1]["net"])
        self.assertEqual(kgi["series"][2]["net"], -2_147_000)

    def test_foreign_and_retail_nets_today(self):
        v = self._view()
        self.assertEqual(v["foreign_net_today"],
                         1_730_000 + 1_058_000 - 3_623_000)
        self.assertEqual(v["retail_net_today"], 423_000)

    def test_no_cache_for_trading_date_returns_empty(self):
        v = build_behavior_series("2313", "20260720", days=10,
                                  ohlc_map=self.ohlc, cache_dir=self.dir)
        # 20260720 has no cache file → window ends at 0716 which isn't
        # the requested trading date → empty view
        self.assertEqual(v, {})

    def test_json_serializable(self):
        json.dumps(self._view(), ensure_ascii=False)

    def test_stale_duplicate_day_dropped(self):
        # Non-trading-day fetch caches the prior day's data under a new
        # date (2026-07-10 incident: 215/215 files duplicated 07/09) —
        # identical whole-day (buy, sell) signature must drop the later
        # date from the axis entirely.
        with tempfile.TemporaryDirectory() as d:
            brokers = {"1480": {"name": "美商高盛", "buy": 500_000,
                                "sell": 0}}
            _write_plain(d, "2313", "20260709", brokers)
            _write_plain(d, "2313", "20260710", brokers)  # stale dup
            _write_plain(d, "2313", "20260713",
                         {"1480": {"name": "美商高盛", "buy": 300_000,
                                   "sell": 0}})
            v = build_behavior_series("2313", "20260713", days=10,
                                      cache_dir=d)
            self.assertEqual(v["dates"], ["20260709", "20260713"])
            gs = v["groups"]["foreign"][0]
            self.assertEqual([s["net"] for s in gs["series"]],
                             [500_000, 300_000])


class TestFormatBehavior(unittest.TestCase):
    def test_render_series(self):
        tmp = tempfile.TemporaryDirectory()
        _write_prices(tmp.name, "2313", "20260715", [
            _row("1480", "美商高盛", 243.0, buy=6_041_000)])
        _write_prices(tmp.name, "2313", "20260716", [
            _row("1480", "美商高盛", 241.2, sell=2_565_000),
            _row("9800", "元大", 242.0, buy=5_649_000, sell=8_109_000)])
        v = build_behavior_series(
            "2313", "20260716", days=10,
            ohlc_map={"20260716": {"low": 235.0, "high": 248.0,
                                   "close": 236.5}},
            cache_dir=tmp.name)
        text = "\n".join(_format_behavior(v))
        tmp.cleanup()
        self.assertIn("【🧭 分點行為 — 近2日連續買賣序列】", text)
        self.assertIn("🌏 外資分點 今日合計 -2,565 張", text)
        self.assertIn("07/15 +6.0k", text)
        self.assertIn("07/16 -2.6k@48%", text)
        self.assertIn("07/15 —", text)   # 元大 missing on day1
        self.assertIn("內資今日賣方", text)
        self.assertIn("經驗 proxy", text)
        # no rigid rule tags anymore
        self.assertNotIn("[隔日沖]", text)
        self.assertNotIn("[當沖]", text)

    def test_empty_view_renders_nothing(self):
        self.assertEqual(_format_behavior({}), [])


class TestFmtK(unittest.TestCase):
    def test_compact(self):
        self.assertEqual(_fmt_k(6_041_000), "+6.0k")
        self.assertEqual(_fmt_k(-2_565_000), "-2.6k")
        self.assertEqual(_fmt_k(156_000), "+156")
        self.assertEqual(_fmt_k(-50_000), "-50")


if __name__ == "__main__":
    unittest.main()
