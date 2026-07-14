"""族群資金流 計算核心單元測試。"""
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "concept_momentum"))

from concept_money_flow import (classify_flow_tag, aggregate_day, inst_streak,
                                rolling_5d_cum, build_view_rows,
                                FLOW_SHARE_PP, FLOW_INST_NTD)

THEMES = {
    "T_A": {"name_zh": "主題A", "stocks": ["1111", "2222"]},
    "T_B": {"name_zh": "主題B", "stocks": ["2222", "3333"]},  # 2222 屬兩主題
}


def _inst(date, code, name, buy, sell):
    return {"date": date, "stock_id": code, "name": name, "buy": buy, "sell": sell}


def _px(date, code, close, money):
    return {"date": date, "stock_id": code, "close": close, "Trading_money": money}


class TestClassifyFlowTag(unittest.TestCase):
    def test_quadrants(self):
        self.assertEqual(classify_flow_tag(0.5, 3.0), "🔥")
        self.assertEqual(classify_flow_tag(0.5, -3.0), "⚠")
        self.assertEqual(classify_flow_tag(-0.5, 3.0), "🧲")
        self.assertEqual(classify_flow_tag(-0.5, -3.0), "❄")

    def test_boundary_counts_as_signal(self):
        # 恰等於門檻 → 達門檻（比照 classify_tier 慣例）
        self.assertEqual(classify_flow_tag(FLOW_SHARE_PP, FLOW_INST_NTD), "🔥")

    def test_below_threshold_dash(self):
        self.assertEqual(classify_flow_tag(0.14, 3.0), "—")
        self.assertEqual(classify_flow_tag(0.5, 0.49), "—")

    def test_none_fail_open(self):
        self.assertEqual(classify_flow_tag(None, 3.0), "—")
        self.assertEqual(classify_flow_tag(0.5, None), "—")


class TestAggregateDay(unittest.TestCase):
    def setUp(self):
        d = "2026-07-13"
        # 數字刻意取「億」級，round(x/1e8, 2) 後仍非零 — 否則斷言形同 0.0==0.0
        self.inst_rows = [
            # 1111：外資買 1000 萬股、投信賣 200 萬股（×收盤 100 → +10 億 / -2 億）
            _inst(d, "1111", "Foreign_Investor", 10_000_000, 0),
            _inst(d, "1111", "Investment_Trust", 0, 2_000_000),
            # 2222：自營兩科目各買 50 萬股（×收盤 50 → 合計 +0.5 億）
            _inst(d, "2222", "Dealer_self", 500_000, 0),
            _inst(d, "2222", "Dealer_Hedging", 500_000, 0),
            # 3333：有法人資料但（下方）無收盤價 → missing
            _inst(d, "3333", "Foreign_Investor", 100, 0),
            # 次日夾帶列 — 必須被過濾（若沒過濾，外資會再 +10 億）
            _inst("2026-07-14", "1111", "Foreign_Investor", 10_000_000, 0),
        ]
        self.price_rows = [
            _px(d, "1111", 100.0, 5_000_000),
            _px(d, "2222", 50.0, 3_000_000),
            # 3333 缺收盤
            # 非 4 位數代號 → 不計入全市場成交額
            _px(d, "00878", 20.0, 999_000_000),
            # 非族群的 4 位數股 → 計入全市場成交額
            _px(d, "9999", 10.0, 2_000_000),
            # 次日夾帶列 — 必須被過濾
            _px("2026-07-14", "1111", 101.0, 7_000_000),
        ]

    def test_aggregate(self):
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES)
        self.assertEqual(day["date"], "20260713")
        # 全市場成交額 = 1111 + 2222 + 9999（排除 00878、排除次日列）
        self.assertEqual(day["market_turnover_ntd"], 10_000_000)
        a = day["themes"]["T_A"]
        # T_A 淨流 = 1111 外資 +10億、投信 -2億 + 2222 自營 +0.5億 = +8.5億
        self.assertAlmostEqual(a["inst_net_ntd"], 8.5)
        self.assertAlmostEqual(a["foreign_net_ntd"], 10.0)
        self.assertAlmostEqual(a["trust_net_ntd"], -2.0)
        self.assertEqual(a["turnover_ntd"], 8_000_000)
        self.assertAlmostEqual(a["mkt_share_pct"], round(8_000_000 / 10_000_000 * 100, 3))
        self.assertEqual(a["missing"], [])
        b = day["themes"]["T_B"]
        self.assertIn("3333", b["missing"])  # 缺收盤 → 金額跳過並記 missing
        # T_B 淨流只含 2222 自營 +0.5 億
        self.assertAlmostEqual(b["inst_net_ntd"], 0.5)

    def test_next_day_rows_filtered(self):
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES)
        # 若次日列未被過濾，T_A 外資會變 +20 億
        self.assertAlmostEqual(day["themes"]["T_A"]["foreign_net_ntd"], 10.0)


class TestStreakAndRolling(unittest.TestCase):
    def test_streak(self):
        self.assertEqual(inst_streak([1.0, 2.0, 3.0]), 3)
        self.assertEqual(inst_streak([1.0, -1.0, -2.0]), -2)
        self.assertEqual(inst_streak([1.0, 0.0, 2.0]), 1)  # 0 中斷
        self.assertEqual(inst_streak([0.0]), 0)
        self.assertEqual(inst_streak([]), 0)

    def test_rolling_5d(self):
        self.assertEqual(rolling_5d_cum([1, 1, 1, 1, 1, 1]), [1, 2, 3, 4, 5, 5])


class TestBuildViewRows(unittest.TestCase):
    def _day(self, yyyymmdd, net, share):
        return {"date": yyyymmdd, "market_turnover_ntd": 1e10, "themes": {
            "T_A": {"inst_net_ntd": net, "foreign_net_ntd": net, "trust_net_ntd": 0.0,
                     "turnover_ntd": 1e8, "mkt_share_pct": share, "missing": []}}}

    def test_share_vs_20d_and_fields(self):
        # 21 天：前 20 天占比 1.0、今天 1.5 → share_vs_20d = +0.5
        days = [self._day(f"202606{i:02d}", 1.0, 1.0) for i in range(1, 21)]
        days.append(self._day("20260701", 2.0, 1.5))
        rows = build_view_rows(days, {"T_A": {"name_zh": "主題A", "stocks": ["1111"]}})
        r = rows[0]
        self.assertEqual(r["theme_key"], "T_A")
        self.assertAlmostEqual(r["share_vs_20d"], 0.5)
        self.assertEqual(r["share_samples"], 20)
        self.assertEqual(r["streak"], 21)
        self.assertAlmostEqual(r["net_5d"], 1.0 * 4 + 2.0)
        self.assertEqual(r["tag"], "🔥")
        self.assertEqual(len(r["spark"]), 21)

    def test_insufficient_history(self):
        days = [self._day("20260701", 1.0, 1.2), self._day("20260702", 1.0, 1.5)]
        rows = build_view_rows(days, {"T_A": {"name_zh": "主題A", "stocks": ["1111"]}})
        self.assertEqual(rows[0]["share_samples"], 1)  # 只有 1 天 prior
        self.assertAlmostEqual(rows[0]["share_vs_20d"], 0.3)

    def test_empty(self):
        self.assertEqual(build_view_rows([], THEMES), [])

    def test_sorted_by_net_desc(self):
        themes = {"T_A": {"name_zh": "A", "stocks": []}, "T_B": {"name_zh": "B", "stocks": []}}
        day = {"date": "20260701", "market_turnover_ntd": 1e10, "themes": {
            "T_A": {"inst_net_ntd": 1.0, "foreign_net_ntd": 1.0, "trust_net_ntd": 0.0,
                     "turnover_ntd": 1e8, "mkt_share_pct": 1.0, "missing": []},
            "T_B": {"inst_net_ntd": 5.0, "foreign_net_ntd": 5.0, "trust_net_ntd": 0.0,
                     "turnover_ntd": 1e8, "mkt_share_pct": 1.0, "missing": []}}}
        rows = build_view_rows([day], themes)
        self.assertEqual([r["theme_key"] for r in rows], ["T_B", "T_A"])


if __name__ == "__main__":
    unittest.main()
