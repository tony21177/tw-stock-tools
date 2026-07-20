"""族群資金流 renderer 單元測試。"""
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "concept_momentum"))

from concept_money_flow_renderer import (render_tab, render_flow_cells,
                                         build_tg_summary, _sparkline_svg, _tg_row)


def _row(name, net, tag="🔥", streak=3, share_vs=0.5, foreign=None, trust=None):
    return {"theme_key": name, "name_zh": name, "tag": tag,
            "inst_net_ntd": net, "foreign_net_ntd": foreign if foreign is not None else net,
            "trust_net_ntd": trust if trust is not None else 0.0,
            "net_5d": net * 3, "streak": streak, "mkt_share_pct": 2.5,
            "share_vs_20d": share_vs, "share_samples": 20,
            "spark": [1.0, 2.0, -1.0], "missing": []}


class TestRenderTab(unittest.TestCase):
    def test_contains_key_columns_and_caveats(self):
        html = render_tab([_row("主題A", 18.3)], "20260714")
        for token in ["主題A", "法人淨流", "占比", "🔥", "+18.3",
                      "近似", "未經回測", "使用時機", "20260714", "<svg"]:
            self.assertIn(token, html)

    def test_empty_state(self):
        html = render_tab([], "—")
        self.assertIn("backfill", html)

    def test_insufficient_samples_star(self):
        # 只檢查 <tbody> 內文 — footer 圖例本來就含「樣本不足」字樣，不能全文比對
        full = _row("主題A", 5.0)
        tbody = render_tab([full], "20260714").split("<tbody>")[1].split("</tbody>")[0]
        self.assertNotIn("*", tbody)
        part = _row("主題B", 5.0)
        part["share_samples"] = 7
        tbody2 = render_tab([part], "20260714").split("<tbody>")[1].split("</tbody>")[0]
        self.assertIn("*", tbody2)


def _fv():
    return {
        "asof": "20260714",
        "recent": [
            {"date": "20260710", "twse": None, "tpex": None, "total": None},
            {"date": "20260713", "twse": -120.5, "tpex": 15.3, "total": -105.2},
            {"date": "20260714", "twse": 80.1, "tpex": -3.2, "total": 76.9},
        ],
        "top_buy": [{"code": "2330", "name": "台積電", "mkt": "上市", "ntd": 55.2}],
        "top_sell": [{"code": "2454", "name": "聯發科", "mkt": "上市", "ntd": -31.8}],
    }


class TestForeignSection(unittest.TestCase):
    def test_rendered_with_foreign_view(self):
        html = render_tab([_row("主題A", 5.0)], "20260714", foreign_view=_fv())
        for token in ["外資買賣超", "上市", "上櫃", "買超 Top", "賣超 Top",
                      "台積電", "聯發科", "+55.2", "-31.8", "+80.1", "-120.5"]:
            self.assertIn(token, html)
        # 舊檔 None 值容忍：顯示 — 而非 crash
        self.assertIn("—", html)

    def test_no_foreign_view_no_section(self):
        html = render_tab([_row("主題A", 5.0)], "20260714")
        self.assertNotIn("外資買賣超", html)
        html2 = render_tab([_row("主題A", 5.0)], "20260714", foreign_view=None)
        self.assertNotIn("買超 Top", html2)


class TestSparkline(unittest.TestCase):
    def test_svg(self):
        svg = _sparkline_svg([1.0, -2.0, 3.0])
        self.assertIn("<svg", svg)
        self.assertIn("polyline", svg)
        self.assertIn("<line", svg)  # 有跨 0 → 畫零線

    def test_degenerate(self):
        self.assertEqual(_sparkline_svg([]), "—")
        self.assertEqual(_sparkline_svg([1.0]), "—")


class TestFlowCells(unittest.TestCase):
    def test_cells(self):
        m = {"T_A": _row("T_A", 3.2)}
        cells = render_flow_cells("T_A", m)
        self.assertIn("+3.2", cells)
        self.assertIn("🔥", cells)

    def test_missing_theme(self):
        self.assertEqual(render_flow_cells("NOPE", {}), "<td>—</td><td>—</td>")
        self.assertEqual(render_flow_cells("NOPE", None), "<td>—</td><td>—</td>")


class TestTgSummary(unittest.TestCase):
    def test_top5_ranked_by_share_not_inst(self):
        # 排序主鍵是 share_vs_20d（占比），不是 inst_net_ntd。占比由高到低
        # 命名（匯入0 占比最高），streak=0 避免污染連續區。
        rows = ([_row(f"匯入{i}", 10.0 - i, streak=0, share_vs=1.0 - i * 0.1)
                 for i in range(6)]
                + [_row(f"流出{i}", -5.0 - i, tag="❄", streak=0,
                        share_vs=-0.5 - i * 0.1) for i in range(6)])
        msg = build_tg_summary(rows, "2026-07-14")
        inflow = msg.split("資金匯入 Top5")[1].split("資金流出 Top5")[0]
        outflow = msg.split("資金流出 Top5")[1]
        # 匯入榜：占比最高的匯入0 在首、第 6 名匯入5 被擠掉
        self.assertIn("匯入0", inflow)
        self.assertIn("占比+1.00pp", inflow)
        self.assertIn("法人+10.0億", inflow)   # 法人淨流仍在（輔助）
        self.assertNotIn("匯入5", inflow)
        # 流出榜：占比最負的流出5 在首、第 6 名流出0 被擠掉
        self.assertIn("流出5", outflow)
        self.assertNotIn("流出0", outflow)

    def test_warn_and_streak_sections(self):
        rows = ([_row("出貨王", -3.1, tag="⚠", share_vs=0.6)]
                + [_row("連跌王", -5.0, tag="❄", streak=-6, share_vs=-0.3)])
        msg = build_tg_summary(rows, "2026-07-14")
        self.assertIn("⚠ 出貨疑慮", msg)
        self.assertIn("出貨王", msg)
        self.assertIn("連6日賣超", msg)

    def test_none_share_excluded_from_ranking(self):
        # share_vs_20d=None（樣本不足）不進榜
        rows = [_row("有占比", 2.0, share_vs=0.3),
                _row("無占比", 99.0, share_vs=None)]
        msg = build_tg_summary(rows, "2026-07-14")
        self.assertIn("有占比", msg)
        self.assertNotIn("無占比", msg)

    def test_empty_sides(self):
        msg = build_tg_summary([_row("A", 2.0, share_vs=0.3)], "2026-07-14")
        self.assertIn("（無）", msg)  # 流出側

    def test_none_fields_do_not_crash(self):
        r = _row("缺值", 2.0, share_vs=0.4)
        r["foreign_net_ntd"] = None
        r["trust_net_ntd"] = None
        msg = build_tg_summary([r], "2026-07-14")
        self.assertIn("缺值", msg)
        self.assertIn("外+0.0", msg)


if __name__ == "__main__":
    unittest.main()
