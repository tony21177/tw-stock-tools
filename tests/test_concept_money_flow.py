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

    def test_hedge_day_dash(self):
        # 對沖日：外資+66.6 vs 投信-66.8，淨流 +2.77 過絕對門檻但只佔總流量 2%
        # → 雜訊級殘差不給標記（2026-07-14 被動元件真實案例）
        self.assertEqual(classify_flow_tag(1.105, 2.77, gross_ntd=136.1), "—")

    def test_gross_ratio_boundary(self):
        # 淨流恰等於總流量 10% → 達門檻
        self.assertEqual(classify_flow_tag(0.5, 10.0, gross_ntd=100.0), "🔥")
        # 差一點 → —
        self.assertEqual(classify_flow_tag(0.5, 9.9, gross_ntd=100.0), "—")

    def test_gross_none_keeps_absolute_rule(self):
        # 不給 gross（舊呼叫方式）→ 只用絕對門檻，行為不變
        self.assertEqual(classify_flow_tag(0.5, 3.0), "🔥")
        # gross 很小時 max(0.5, 10%×gross) 仍以 0.5 億為下限
        self.assertEqual(classify_flow_tag(0.5, 0.5, gross_ntd=1.0), "🔥")
        self.assertEqual(classify_flow_tag(0.5, 0.49, gross_ntd=1.0), "—")


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


class TestForeignMarketSplitAndTop(unittest.TestCase):
    def setUp(self):
        d = "2026-07-13"
        self.inst_rows = [
            _inst(d, "1111", "Foreign_Investor", 10_000_000, 0),    # 上市 外資 +10 億
            _inst(d, "2222", "Foreign_Investor", 0, 1_000_000),     # 上櫃 外資 -0.5 億
            _inst(d, "9999", "Foreign_Investor", 2_000_000, 0),     # 上市 外資 +0.2 億
            _inst(d, "8888", "Investment_Trust", 5_000_000, 0),     # 投信 → 不入外資統計
            _inst(d, "7777", "Foreign_Investor", 1_000_000, 0),     # 無市場分類 → 不入上市櫃加總
            _inst(d, "0050", "Foreign_Investor", 50_000_000, 0),    # ETF：入市場加總、不入個股榜
            _inst(d, "00878", "Foreign_Investor", 10_000_000, 0),   # 5位數 ETF：同樣入加總不入榜
        ]
        self.price_rows = [
            _px(d, "1111", 100.0, 5_000_000),
            _px(d, "2222", 50.0, 3_000_000),
            _px(d, "9999", 10.0, 2_000_000),
            _px(d, "8888", 20.0, 1_000_000),
            _px(d, "7777", 30.0, 1_000_000),
            _px(d, "0050", 200.0, 9_000_000),
            _px(d, "00878", 20.0, 4_000_000),
        ]
        self.market_map = {"1111": "上市", "9999": "上市", "2222": "上櫃",
                           "8888": "上櫃", "0050": "上市", "00878": "上市"}
        self.names = {"1111": "甲公司", "2222": "乙公司", "9999": "丙公司"}

    def test_foreign_market_split(self):
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES,
                            market_map=self.market_map, names=self.names)
        fm = day["foreign_mkt"]
        # 1111 +10 + 9999 +0.2 + 0050 +100 + 00878 +2（ETF 含 5 位數都入加總）
        self.assertAlmostEqual(fm["twse_ntd"], 112.2)
        self.assertAlmostEqual(fm["tpex_ntd"], -0.5)   # 2222 -0.5
        # 7777 無分類：不進上市櫃加總

    def test_top_foreign_lists(self):
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES,
                            market_map=self.market_map, names=self.names)
        buy = day["top_foreign"]["buy"]
        sell = day["top_foreign"]["sell"]
        # 0050/00878 外資買很大但都是 ETF（00 開頭）→ 不入「個股」榜
        codes_all = [b["code"] for b in buy]
        self.assertNotIn("0050", codes_all)
        self.assertNotIn("00878", codes_all)
        self.assertEqual(buy[0]["code"], "1111")
        self.assertEqual(buy[0]["name"], "甲公司")
        self.assertEqual(buy[0]["mkt"], "上市")
        self.assertAlmostEqual(buy[0]["ntd"], 10.0)
        # 7777 有外資買但無分類 → 仍列入 top（mkt 標 ?），名稱 fallback 代號
        codes_buy = [b["code"] for b in buy]
        self.assertIn("7777", codes_buy)
        self.assertEqual(sell[0]["code"], "2222")
        self.assertAlmostEqual(sell[0]["ntd"], -0.5)
        # 投信單獨買的 8888 不在外資榜
        self.assertNotIn("8888", codes_buy)

    def test_without_maps_fields_absent(self):
        # 不給 maps（舊呼叫）→ 不產生新欄位，行為回溯相容
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES)
        self.assertNotIn("foreign_mkt", day)
        self.assertNotIn("top_foreign", day)

    def test_build_foreign_view(self):
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES,
                            market_map=self.market_map, names=self.names)
        old = {"date": "20260710", "market_turnover_ntd": 1.0, "themes": {}}  # 舊檔無新欄位
        from concept_money_flow import build_foreign_view
        fv = build_foreign_view([old, day])
        self.assertEqual(fv["asof"], "20260713")
        self.assertEqual(len(fv["recent"]), 2)
        self.assertIsNone(fv["recent"][0]["twse"])     # 舊檔 → None 容忍
        self.assertAlmostEqual(fv["recent"][1]["twse"], 112.2)
        self.assertAlmostEqual(fv["recent"][1]["total"], 112.2 - 0.5 + 0.3)  # 含無分類 7777 的 0.3
        self.assertEqual(fv["top_buy"][0]["code"], "1111")

    def test_parse_tpex_summary(self):
        from concept_money_flow import _parse_tpex_summary
        payload = {"tables": [{"data": [
            ["外資及陸資合計", "65,471,530,902", "72,016,337,696", "-6,544,806,794"],
            ["　外資自營商", "0", "0", "0"],
        ]}]}
        self.assertAlmostEqual(_parse_tpex_summary(payload), -65.45)
        self.assertIsNone(_parse_tpex_summary({"tables": [{"data": []}]}))
        self.assertIsNone(_parse_tpex_summary({}))

    def test_build_foreign_view_prefers_official(self):
        from concept_money_flow import build_foreign_view
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES,
                            market_map=self.market_map, names=self.names)
        day["foreign_mkt_official"] = {"twse_ntd": -14.15, "tpex_ntd": -65.45}
        fv = build_foreign_view([day])
        r = fv["recent"][-1]
        self.assertAlmostEqual(r["twse"], -14.15)   # 官方優先於近似 112.2
        self.assertAlmostEqual(r["tpex"], -65.45)
        self.assertAlmostEqual(r["total"], -79.6)   # 官方兩者齊 → 合計 = 相加
        self.assertTrue(r["official"])

    def test_build_foreign_view_fallback_approx(self):
        from concept_money_flow import build_foreign_view
        day = aggregate_day("20260713", self.inst_rows, self.price_rows, THEMES,
                            market_map=self.market_map, names=self.names)
        fv = build_foreign_view([day])   # 無官方欄位 → 近似回填
        r = fv["recent"][-1]
        self.assertAlmostEqual(r["twse"], 112.2)
        self.assertFalse(r["official"])

    def test_build_foreign_view_empty(self):
        from concept_money_flow import build_foreign_view
        self.assertIsNone(build_foreign_view([]))
        # 全部舊檔（無 top_foreign）→ None
        old = {"date": "20260710", "market_turnover_ntd": 1.0, "themes": {}}
        self.assertIsNone(build_foreign_view([old]))


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


import tempfile


class TestDayFileIO(unittest.TestCase):
    def setUp(self):
        import concept_money_flow as cmf
        self.cmf = cmf
        self._orig_dir = cmf.FLOW_DIR
        self.tmp = tempfile.TemporaryDirectory()
        cmf.FLOW_DIR = self.tmp.name

    def tearDown(self):
        self.cmf.FLOW_DIR = self._orig_dir
        self.tmp.cleanup()

    def _write(self, yyyymmdd):
        import json as _json
        with open(self.cmf.day_path(yyyymmdd), "w") as f:
            _json.dump({"date": yyyymmdd, "market_turnover_ntd": 1.0, "themes": {}}, f)

    def test_load_flow_days_sorted_and_capped(self):
        for d in ["20260703", "20260701", "20260702", "20260706"]:
            self._write(d)
        days = self.cmf.load_flow_days("20260703", days=2)
        # end_date 之後的檔被忽略；由舊到新；只取最後 2 個
        self.assertEqual([x["date"] for x in days], ["20260702", "20260703"])

    def test_load_flow_days_empty_dir(self):
        self.assertEqual(self.cmf.load_flow_days("20260703"), [])

    def test_run_day_skips_existing(self):
        self._write("20260701")
        # token 給空字串也不會打 API — 已存在直接回快取
        out = self.cmf.run_day("20260701", token="", verbose=False)
        self.assertEqual(out["date"], "20260701")

    def test_run_day_corrupt_file_refetches(self):
        # 壞檔不 crash：skip 分支 fall-through 到重抓路徑（fetch 打樁驗證有被呼叫）
        with open(self.cmf.day_path("20260701"), "w") as f:
            f.write("{truncated")
        calls = []
        orig = self.cmf._fetch_finmind
        self.cmf._fetch_finmind = lambda ds, di, tok: calls.append(ds) or []
        try:
            out = self.cmf.run_day("20260701", token="x", verbose=False)
        finally:
            self.cmf._fetch_finmind = orig
        self.assertIsNone(out)          # inst 空 → fail-open 不寫檔
        self.assertTrue(calls)          # 有走到重抓路徑


if __name__ == "__main__":
    unittest.main()
