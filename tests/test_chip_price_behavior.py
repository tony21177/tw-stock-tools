"""Tests for tw_chip_price 分點行為分類 (broker behavior classification)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from tw_chip_price import (  # noqa: E402
    classify_broker_type,
    _behavior_tags,
    _broker_day_stats,
    build_behavior_view,
    _format_behavior,
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


class TestBehaviorTags(unittest.TestCase):
    LOW, HIGH, THR = 235.0, 248.0, 150_000

    def _tags(self, buy, sell, buy_avg, sell_avg, prev_net=0):
        stat = {"buy": buy, "sell": sell,
                "buy_avg": buy_avg, "sell_avg": sell_avg}
        return _behavior_tags(stat, self.LOW, self.HIGH, self.THR, prev_net)

    def test_day_trade(self):
        tags = self._tags(2_883_000, 3_290_000, 240.2, 242.0)
        self.assertIn("當沖", tags)

    def test_next_day_dump(self):
        # 高盛 pattern: 昨淨 +6,041張 → 今淨 -2,565張
        tags = self._tags(1_058_000, 3_623_000, 243.5, 241.2,
                          prev_net=6_041_000)
        self.assertIn("隔日沖", tags)

    def test_next_day_dump_requires_prev_data(self):
        tags = self._tags(1_058_000, 3_623_000, 243.5, 241.2, prev_net=None)
        self.assertNotIn("隔日沖", tags)

    def test_next_day_dump_small_sell_not_tagged(self):
        # bought big yesterday but only trimmed a little today
        tags = self._tags(0, 160_000, 0.0, 241.0, prev_net=6_000_000)
        self.assertNotIn("隔日沖", tags)

    def test_pure_dump(self):
        # 永豐匯立 pattern: 買 2張 / 賣 1,319張
        tags = self._tags(2_000, 1_319_000, 244.8, 241.7)
        self.assertIn("純倒貨", tags)

    def test_dip_buy_and_chase(self):
        low_tags = self._tags(400_000, 0, 236.5, 0.0)   # 位階 ~12%
        self.assertTrue(any(t.startswith("低接") for t in low_tags))
        hi_tags = self._tags(400_000, 0, 244.9, 0.0)    # 位階 ~76%
        self.assertTrue(any(t.startswith("追高") for t in hi_tags))

    def test_below_threshold_no_tags(self):
        self.assertEqual(self._tags(50_000, 40_000, 246.0, 236.0), [])


def _row(bid, name, price, buy=0, sell=0):
    return {"broker_id": bid, "broker_name": name, "price": price,
            "buy": buy, "sell": sell}


class TestBuildBehaviorView(unittest.TestCase):
    def setUp(self):
        # Today: foreign dip-buyer, foreign next-day dumper, retail chaser,
        # domestic pure dumper. Volumes sized so thr = BEHAVIOR_MIN_SHARES.
        self.rows = [
            _row("1470", "台灣摩根", 236.0, buy=1_730_000),
            _row("1480", "美商高盛", 241.2, sell=2_565_000),
            _row("9800", "永豐金", 243.6, buy=423_000),
            _row("9600", "永豐匯立", 241.7, buy=2_000, sell=1_319_000),
            _row("9100", "群益", 241.0, buy=129_000),
        ]
        self.prev = [_row("1480", "美商高盛", 240.0, buy=6_041_000)]

    def test_grouping_and_tags(self):
        v = build_behavior_view(self.rows, 235.0, 248.0,
                                prev_rows=self.prev, prev_date="20260715")
        self.assertEqual(v["prev_date"], "20260715")
        self.assertEqual(v["foreign"]["net"], 1_730_000 - 2_565_000)
        self.assertEqual([s["broker_id"] for s in v["foreign"]["buys"]],
                         ["1470"])
        self.assertEqual([s["broker_id"] for s in v["foreign"]["sells"]],
                         ["1480"])
        self.assertEqual(v["retail"]["net"], 423_000)
        self.assertEqual([s["broker_id"] for s in v["next_day_dump"]],
                         ["1480"])
        gs = v["next_day_dump"][0]
        self.assertIn("隔日沖", gs["tags"])
        dumper = [s for s in v["domestic"]["sells"]
                  if s["broker_id"] == "9600"][0]
        self.assertIn("純倒貨", dumper["tags"])

    def test_no_prev_rows_disables_next_day_dump(self):
        v = build_behavior_view(self.rows, 235.0, 248.0)
        self.assertEqual(v["prev_date"], "")
        self.assertEqual(v["next_day_dump"], [])
        gs = [s for s in v["foreign"]["sells"] if s["broker_id"] == "1480"][0]
        self.assertIsNone(gs["prev_net"])

    def test_json_serializable(self):
        v = build_behavior_view(self.rows, 235.0, 248.0,
                                prev_rows=self.prev, prev_date="20260715")
        json.dumps(v, ensure_ascii=False)


class TestFormatBehavior(unittest.TestCase):
    def test_render(self):
        rows = [
            _row("1470", "台灣摩根", 236.0, buy=1_730_000),
            _row("1480", "美商高盛", 241.2, sell=2_565_000),
            _row("9800", "永豐金", 243.6, buy=423_000),
        ]
        prev = [_row("1480", "美商高盛", 240.0, buy=6_041_000)]
        v = build_behavior_view(rows, 235.0, 248.0,
                                prev_rows=prev, prev_date="20260715")
        text = "\n".join(_format_behavior(v))
        self.assertIn("【🧭 分點行為分類】", text)
        self.assertIn("2026/07/15", text)
        self.assertIn("🌏 外資分點 合計淨", text)
        self.assertIn("🏠 散戶指標分點", text)
        self.assertIn("隔日沖名單: 美商高盛(-2,565)", text)
        self.assertIn("先驗未回測", text)

    def test_render_without_prev(self):
        v = build_behavior_view(
            [_row("1470", "台灣摩根", 236.0, buy=1_730_000)], 235.0, 248.0)
        text = "\n".join(_format_behavior(v))
        self.assertIn("無前日 BSR cache", text)


if __name__ == "__main__":
    unittest.main()
