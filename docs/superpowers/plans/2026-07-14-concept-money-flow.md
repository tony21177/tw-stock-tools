# 族群資金流入流出 (Concept Money Flow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 concept_momentum dashboard 新增「族群資金流」：34 個主題板塊每日的三大法人淨買賣金額 + 成交額占比輪動 + 四象限交叉標記，含 dashboard 分頁、動能表兩欄、Telegram 推播、60 日回補。

**Architecture:** 新模組 `concept_money_flow.py`（抓取+計算+日檔 I/O+CLI）與 `concept_money_flow_renderer.py`（純渲染），日檔存 `cache/money_flow/{yyyymmdd}.json`（同 `market_breadth/` 模式），掛進既有 17:00 `run_daily.py`（不加新 cron）。衍生欄位（占比vs20日均、連續天數、標記、5日累計）由讀取端從 60 個日檔現算、不落地。

**Tech Stack:** Python 3 標準庫（urllib、json）、FinMind API（sponsor tier，單日全市場查詢）、Flask（既有 app.py）、unittest。

**Spec:** `docs/superpowers/specs/2026-07-14-concept-money-flow-design.md`（已與使用者逐段核可）。

## Global Constraints

- 門檻常數：`FLOW_SHARE_PP = 0.15`（pp）、`FLOW_INST_NTD = 0.5`（億）。恰等於門檻視為「達門檻」（比照 `classify_tier` 慣例）。門檻為先驗設定、未經回測 — 所有面向使用者的文案都要註明。
- 法人金額 = 淨股數 × 收盤價，是**近似值** — 術語表與 TG 摘要都要講明。
- FinMind name 欄位對應：外資 = `Foreign_Investor` + `Foreign_Dealer_Self`；投信 = `Investment_Trust`；自營 = `Dealer_self` + `Dealer_Hedging`（自營計入總計但不單獨顯示）。
- fail-open：API 失敗/法人未發布 → **不寫日檔**、stderr warning；絕不寫空檔（repo 教訓：never cache empty API responses）。
- FinMind `start_date=end_date=X` 查詢會夾帶次日列 — 一律過濾 `row["date"] == date_iso`（比照 `market_breadth.py:241-247` 的 off-by-one 修正）。
- 全市場成交額只計 4 位數字代號（排除 ETF/權證，比照 `market_breadth.fetch_universe_one_day` 的 `re.fullmatch(r"\d{4}", code)`）。
- 交易日來源用 `cache/taiex.json`（`market_breadth._twii_trading_dates` 既有 helper），**不用** trading_calendar.json（該檔只含 2026 年，taiex 覆蓋更長且是 market_breadth 已驗證模式）— 此為對 spec 第 3 節的小幅偏離，理由如上。
- 測試風格：unittest、放 `tests/`、開頭 `sys.path.insert` 加 repo root 與 `concept_momentum/` 兩個路徑。
- 每個 task 一個 commit；commit message 中文、格式比照 repo 慣例（如 `feat: ...`）。
- app.py / renderer 改動後必須 `systemctl --user restart concept-dashboard.service`。
- README 必須同步更新（repo 硬規則）。
- 不碰 `tw_param_sweep.py` / `tests/test_param_sweep.py`（他人 WIP）。

---

### Task 1: 計算核心 — `concept_money_flow.py` 純函式

**Files:**
- Create: `concept_momentum/concept_money_flow.py`
- Test: `tests/test_concept_money_flow.py`

**Interfaces:**
- Consumes: 無（純函式 + 常數）
- Produces（後續 task 依賴的精確簽名）:
  - `FLOW_SHARE_PP: float = 0.15`, `FLOW_INST_NTD: float = 0.5`, `YI = 1e8`, `FLOW_DIR: str`
  - `classify_flow_tag(share_vs_20d: float|None, inst_net_ntd: float|None) -> str` — 回 `"🔥"|"⚠"|"🧲"|"❄"|"—"`
  - `aggregate_day(date_yyyymmdd: str, inst_rows: list[dict], price_rows: list[dict], themes: dict) -> dict` — 回日檔 dict
  - `inst_streak(nets: list[float]) -> int` — 尾端連續淨買天數（淨賣為負）
  - `rolling_5d_cum(nets: list[float]) -> list[float]`
  - `build_view_rows(day_files: list[dict], themes: dict) -> list[dict]` — 每列含 keys：`theme_key, name_zh, tag, inst_net_ntd, foreign_net_ntd, trust_net_ntd, net_5d, streak, mkt_share_pct, share_vs_20d, share_samples, spark, missing`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_concept_money_flow.py`：

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd /home/kun/project/tw_stock_tools && python3 -m pytest tests/test_concept_money_flow.py -v 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'concept_money_flow'`

- [ ] **Step 3: 實作**

建立 `concept_momentum/concept_money_flow.py`（本 task 只寫到 `build_view_rows` 為止；抓取/I/O/CLI 是 Task 2）：

```python
#!/usr/bin/env python3
"""族群資金流入流出 — 每日快取 + 計算 + CLI 回補

資料源（FinMind sponsor tier，單日全市場各一次呼叫）：
  TaiwanStockInstitutionalInvestorsBuySell — 三大法人買賣超（單位：股數）
  TaiwanStockPrice — 收盤價 + 成交金額 (Trading_money)

法人金額 = 淨股數 × 當日收盤價（近似值；實際成交價分布在盤中）。
日檔 cache/money_flow/{yyyymmdd}.json；衍生欄位（占比vs20日均、連續天數、
標記、5日累計）由讀取端從日檔序列現算、不落地 — 回補順序不影響快取正確性。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_DIR = os.path.join(HERE, "cache", "money_flow")
FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

YI = 1e8  # 億 NTD

# 四象限交叉判讀門檻 — 先驗設定、未經回測驗證（上線累積數據後可校準）
FLOW_SHARE_PP = 0.15   # |占比 vs 20日均| >= 0.15pp 才算熱度升/降
FLOW_INST_NTD = 0.5    # |法人淨流| >= 0.5 億才算法人買/賣

# FinMind name 欄位 → 法人身分（Foreign_Dealer_Self 依 TWSE 慣例併外資）
_FOREIGN = {"Foreign_Investor", "Foreign_Dealer_Self"}
_TRUST = {"Investment_Trust"}
_DEALER = {"Dealer_self", "Dealer_Hedging"}


def classify_flow_tag(share_vs_20d: float | None, inst_net_ntd: float | None) -> str:
    """占比變化 × 法人淨流 四象限。缺值或未達門檻 → '—'（fail-open）。"""
    if share_vs_20d is None or inst_net_ntd is None:
        return "—"
    if abs(share_vs_20d) < FLOW_SHARE_PP or abs(inst_net_ntd) < FLOW_INST_NTD:
        return "—"
    if share_vs_20d > 0:
        return "🔥" if inst_net_ntd > 0 else "⚠"
    return "🧲" if inst_net_ntd > 0 else "❄"


def _to_iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def aggregate_day(date_yyyymmdd: str, inst_rows: list[dict],
                  price_rows: list[dict], themes: dict) -> dict:
    """單日全市場原始列 → 族群加總日檔 dict。

    inst_rows 單位是股數；金額 = 淨股數 × 收盤價（近似）。
    全市場成交額只計 4 位數字代號（排除 ETF/權證）。
    FinMind start=end 查詢會夾帶次日列 — 這裡按 date 過濾。
    """
    date_iso = _to_iso(date_yyyymmdd)

    net: dict[str, dict] = {}  # code -> {"f","t","d"} 淨股數
    for row in inst_rows:
        if row.get("date") != date_iso:
            continue
        code = str(row.get("stock_id", ""))
        name = row.get("name", "")
        n = float(row.get("buy", 0) or 0) - float(row.get("sell", 0) or 0)
        slot = net.setdefault(code, {"f": 0.0, "t": 0.0, "d": 0.0})
        if name in _FOREIGN:
            slot["f"] += n
        elif name in _TRUST:
            slot["t"] += n
        elif name in _DEALER:
            slot["d"] += n

    close: dict[str, float] = {}
    money: dict[str, float] = {}
    market_turnover = 0.0
    for row in price_rows:
        if row.get("date") != date_iso:
            continue
        code = str(row.get("stock_id", ""))
        if not re.fullmatch(r"\d{4}", code):
            continue
        m = float(row.get("Trading_money", 0) or 0)
        money[code] = m
        market_turnover += m
        c = row.get("close")
        if c and c > 0:
            close[code] = float(c)

    out_themes = {}
    for tkey, tval in themes.items():
        f_ntd = t_ntd = d_ntd = 0.0
        turnover = 0.0
        missing = []
        for code in tval.get("stocks", []):
            code = str(code)
            turnover += money.get(code, 0.0)
            px = close.get(code)
            if px is None:
                missing.append(code)  # 無收盤價 → 金額跳過（占比不受影響）
                continue
            slot = net.get(code)
            if slot:
                f_ntd += slot["f"] * px
                t_ntd += slot["t"] * px
                d_ntd += slot["d"] * px
        inst = f_ntd + t_ntd + d_ntd
        out_themes[tkey] = {
            "inst_net_ntd": round(inst / YI, 2),
            "foreign_net_ntd": round(f_ntd / YI, 2),
            "trust_net_ntd": round(t_ntd / YI, 2),
            "turnover_ntd": turnover,
            "mkt_share_pct": (round(turnover / market_turnover * 100, 3)
                               if market_turnover > 0 else None),
            "missing": missing,
        }
    return {"date": date_yyyymmdd, "market_turnover_ntd": market_turnover,
            "themes": out_themes}


def inst_streak(nets: list[float]) -> int:
    """尾端起算的連續淨流入天數；連續流出為負；0 中斷、空序列回 0。"""
    if not nets or nets[-1] == 0:
        return 0
    sign = 1 if nets[-1] > 0 else -1
    n = 0
    for v in reversed(nets):
        if v != 0 and (v > 0) == (sign > 0):
            n += 1
        else:
            break
    return n * sign


def rolling_5d_cum(nets: list[float]) -> list[float]:
    """5 日滾動累計（前 4 天不足就用現有天數）— sparkline 用。"""
    return [round(sum(nets[max(0, i - 4):i + 1]), 2) for i in range(len(nets))]


def build_view_rows(day_files: list[dict], themes: dict) -> list[dict]:
    """由舊到新的日檔 list → 最新一日的 view rows（依法人淨流降冪）。

    衍生欄位在此現算：share_vs_20d（今日占比 − 前 20 日均，樣本不足用現有
    天數並回報 share_samples）、streak、net_5d、spark（5日滾動累計，最多 60 點）。
    """
    if not day_files:
        return []
    latest = day_files[-1]
    rows = []
    for tkey, tval in themes.items():
        series_net: list[float] = []
        series_share: list[float | None] = []
        for df in day_files:
            td = df.get("themes", {}).get(tkey)
            if td is None:
                continue
            series_net.append(td.get("inst_net_ntd") or 0.0)
            series_share.append(td.get("mkt_share_pct"))
        cur = latest.get("themes", {}).get(tkey)
        if cur is None or not series_net:
            continue
        prior_shares = [s for s in series_share[:-1] if s is not None][-20:]
        share_vs_20d = None
        if series_share[-1] is not None and prior_shares:
            share_vs_20d = round(series_share[-1] - sum(prior_shares) / len(prior_shares), 3)
        row = {
            "theme_key": tkey,
            "name_zh": tval.get("name_zh", tkey),
            "inst_net_ntd": cur["inst_net_ntd"],
            "foreign_net_ntd": cur["foreign_net_ntd"],
            "trust_net_ntd": cur["trust_net_ntd"],
            "net_5d": round(sum(series_net[-5:]), 2),
            "streak": inst_streak(series_net),
            "mkt_share_pct": cur.get("mkt_share_pct"),
            "share_vs_20d": share_vs_20d,
            "share_samples": len(prior_shares),
            "spark": rolling_5d_cum(series_net)[-60:],
            "missing": cur.get("missing", []),
        }
        row["tag"] = classify_flow_tag(share_vs_20d, row["inst_net_ntd"])
        rows.append(row)
    rows.sort(key=lambda r: -(r["inst_net_ntd"] or 0))
    return rows
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_concept_money_flow.py -v 2>&1 | tail -15`
Expected: 全部 PASS（12 個測試）

- [ ] **Step 5: Commit**

```bash
git add concept_momentum/concept_money_flow.py tests/test_concept_money_flow.py
git commit -m "feat: 族群資金流計算核心（法人淨流/占比/四象限標記/衍生欄位）"
```

---

### Task 2: 抓取 + 日檔 I/O + CLI 回補

**Files:**
- Modify: `concept_momentum/concept_money_flow.py`（接在 Task 1 程式碼之後）
- Test: `tests/test_concept_money_flow.py`（追加 I/O 測試）

**Interfaces:**
- Consumes: Task 1 的 `aggregate_day`；`market_breadth._twii_trading_dates(end_date, days)`（既有，讀 taiex.json）
- Produces:
  - `load_themes() -> dict` — 讀 `cache/concepts.json` 回 `["themes"]`
  - `day_path(yyyymmdd: str) -> str`
  - `run_day(date_yyyymmdd: str, token: str, themes: dict|None = None, verbose: bool = True, force: bool = False) -> dict|None` — 抓+算+寫日檔；已存在跳過（回快取內容）；非交易日/法人未發布回 `None` 不寫檔
  - `load_flow_days(end_yyyymmdd: str, days: int = 60) -> list[dict]` — 由舊到新
  - `backfill(token: str, end_yyyymmdd: str, days: int = 60, delay_seconds: float = 1.0, verbose: bool = True) -> int`
  - CLI：`python3 concept_money_flow.py [--date YYYYMMDD] [--backfill N] [--force]`

- [ ] **Step 1: 追加失敗測試**

在 `tests/test_concept_money_flow.py` 末尾（`if __name__` 之前）追加：

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_concept_money_flow.py -v 2>&1 | tail -8`
Expected: 新 3 個測試 FAIL（`AttributeError: ... has no attribute 'day_path'` 之類），Task 1 的 12 個仍 PASS

- [ ] **Step 3: 實作**

在 `concept_momentum/concept_money_flow.py` 末尾追加：

```python
# ---------------------------------------------------------------- I/O 層


def load_themes() -> dict:
    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        return json.load(f)["themes"]


def day_path(yyyymmdd: str) -> str:
    return os.path.join(FLOW_DIR, f"{yyyymmdd}.json")


def _fetch_finmind(dataset: str, date_iso: str, token: str) -> list[dict]:
    """單日全市場查詢（sponsor tier）。API/quota 錯誤 raise RuntimeError。"""
    params = {"dataset": dataset, "start_date": date_iso,
              "end_date": date_iso, "token": token}
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"FinMind HTTP {e.code} {dataset} {date_iso}: {body[:200]}")
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind error {dataset} {date_iso}: {payload.get('msg', '')}")
    return payload.get("data", [])


def run_day(date_yyyymmdd: str, token: str, themes: dict | None = None,
            verbose: bool = True, force: bool = False) -> dict | None:
    """抓當日全市場兩個 dataset → aggregate → 寫日檔。

    已存在（且非 force）→ 跳過並回快取內容。
    法人未發布/非交易日（inst 空）或成交額為 0 → 不寫檔、回 None（fail-open，
    絕不寫空檔）。API 錯誤（402 quota / 斷線）→ raise，由呼叫端決定。
    """
    os.makedirs(FLOW_DIR, exist_ok=True)
    path = day_path(date_yyyymmdd)
    if os.path.exists(path) and not force:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 已存在，跳過", flush=True)
        with open(path) as f:
            return json.load(f)
    if themes is None:
        themes = load_themes()
    date_iso = _to_iso(date_yyyymmdd)
    inst_rows = [r for r in
                 _fetch_finmind("TaiwanStockInstitutionalInvestorsBuySell",
                                date_iso, token)
                 if r.get("date") == date_iso]
    if not inst_rows:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 法人資料尚未發布或非交易日 — 不寫檔",
                  flush=True)
        return None
    price_rows = _fetch_finmind("TaiwanStockPrice", date_iso, token)
    day = aggregate_day(date_yyyymmdd, inst_rows, price_rows, themes)
    if day["market_turnover_ntd"] <= 0:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 無成交金額資料 — 不寫檔", flush=True)
        return None
    with open(path, "w") as f:
        json.dump(day, f, ensure_ascii=False)
    if verbose:
        print(f"[money_flow] wrote {path}", flush=True)
    return day


def load_flow_days(end_yyyymmdd: str, days: int = 60) -> list[dict]:
    """讀 <= end_date 的最近 `days` 個日檔，由舊到新。壞檔跳過。"""
    if not os.path.isdir(FLOW_DIR):
        return []
    files = sorted(f for f in os.listdir(FLOW_DIR)
                   if f.endswith(".json") and f[:8] <= end_yyyymmdd)[-days:]
    out = []
    for fname in files:
        try:
            with open(os.path.join(FLOW_DIR, fname)) as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def backfill(token: str, end_yyyymmdd: str, days: int = 60,
             delay_seconds: float = 1.0, verbose: bool = True) -> int:
    """回補最近 `days` 個交易日（交易日來源 = taiex.json，比照 market_breadth）。

    已存在跳過（resumable，中斷重跑安全）。單日失敗記 log 續跑。
    """
    from market_breadth import _twii_trading_dates
    dates = _twii_trading_dates(end_yyyymmdd, days)
    themes = load_themes()
    written = 0
    for d in dates:
        if os.path.exists(day_path(d)):
            continue
        try:
            day = run_day(d, token, themes=themes, verbose=verbose)
        except Exception as e:
            print(f"[money_flow] {d} 失敗: {e}", file=sys.stderr, flush=True)
            time.sleep(delay_seconds)
            continue
        if day:
            written += 1
        time.sleep(delay_seconds)
    if verbose:
        print(f"[money_flow] 回補完成，新寫 {written} 日", flush=True)
    return written


def main():
    from datetime import datetime
    p = argparse.ArgumentParser(description="族群資金流 日檔快取（抓取+回補）")
    p.add_argument("--date", help="單日 YYYYMMDD（預設今天）")
    p.add_argument("--backfill", type=int, metavar="N", help="回補最近 N 個交易日")
    p.add_argument("--force", action="store_true", help="已存在也重抓")
    args = p.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("需要 FINMIND_TOKEN 環境變數", file=sys.stderr)
        sys.exit(1)
    if args.backfill:
        backfill(token, datetime.now().strftime("%Y%m%d"), days=args.backfill)
    else:
        d = args.date or datetime.now().strftime("%Y%m%d")
        run_day(d, token, force=args.force)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_concept_money_flow.py -v 2>&1 | tail -8`
Expected: 全部 PASS（15 個測試）

- [ ] **Step 5: 單日 live 煙霧測試（1 個交易日、2 次 API 呼叫）**

Run: `cd /home/kun/project/tw_stock_tools/concept_momentum && FINMIND_TOKEN=$(grep FINMIND_TOKEN ~/.env 2>/dev/null | cut -d= -f2) python3 concept_money_flow.py --date 20260713 && python3 -c "
import json
d = json.load(open('cache/money_flow/20260713.json'))
print('themes:', len(d['themes']), '市場成交額(億):', round(d['market_turnover_ntd']/1e8))
top = sorted(d['themes'].items(), key=lambda kv: -kv[1]['inst_net_ntd'])[:3]
for k, v in top: print(k, v['inst_net_ntd'], '億, 占比', v['mkt_share_pct'], '%')
"`

（FINMIND_TOKEN 來源依環境實況 — cron 已有設定方式，找不到就看 `crontab -l` 裡的寫法。）
Expected: themes: 34、市場成交額為千億級合理數字、Top3 法人淨流為個位數~數十億的合理數字。**人工 sanity check：與當日新聞的法人買賣超方向不矛盾。**

- [ ] **Step 6: Commit**

```bash
git add concept_momentum/concept_money_flow.py tests/test_concept_money_flow.py
git commit -m "feat: 族群資金流抓取層 + 日檔 I/O + CLI 回補（resumable, fail-open）"
```

---

### Task 3: Renderer + Telegram 摘要

**Files:**
- Create: `concept_momentum/concept_money_flow_renderer.py`
- Test: `tests/test_concept_money_flow_renderer.py`

**Interfaces:**
- Consumes: Task 1 `build_view_rows` 的 row dict（keys 見 Task 1 Produces）、常數 `FLOW_SHARE_PP`/`FLOW_INST_NTD`
- Produces:
  - `render_tab(view_rows: list[dict], asof: str) -> str` — 排行表+sparkline+圖例+使用時機盒（分頁與獨立頁共用 body）
  - `render_flow_cells(theme_key: str, flow_map: dict|None) -> str` — 動能表用的兩個 `<td>`
  - `build_tg_summary(view_rows: list[dict], date_str: str) -> str` — Telegram 文字
  - `_sparkline_svg(values: list[float]) -> str`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_concept_money_flow_renderer.py`：

```python
"""族群資金流 renderer 單元測試。"""
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "concept_momentum"))

from concept_money_flow_renderer import (render_tab, render_flow_cells,
                                         build_tg_summary, _sparkline_svg)


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
    def test_top5_and_warn(self):
        rows = ([_row(f"流入{i}", 10.0 - i) for i in range(6)]
                + [_row("出貨王", -3.1, tag="⚠", share_vs=0.6)]
                + [_row(f"流出{i}", -5.0 - i, tag="❄", streak=-6) for i in range(6)])
        msg = build_tg_summary(rows, "2026-07-14")
        self.assertIn("💰 族群資金流 2026-07-14", msg)
        self.assertIn("流入 Top5", msg)
        self.assertIn("流出 Top5", msg)
        self.assertNotIn("流入5", msg)   # 第 6 名不出現
        self.assertIn("⚠ 出貨疑慮", msg)
        self.assertIn("出貨王", msg)
        self.assertIn("連6日賣超", msg)   # streak<=-5 的異常提示

    def test_empty_sides(self):
        msg = build_tg_summary([_row("A", 2.0)], "2026-07-14")
        self.assertIn("（無）", msg)  # 流出側


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python3 -m pytest tests/test_concept_money_flow_renderer.py -v 2>&1 | tail -5`
Expected: `ModuleNotFoundError: No module named 'concept_money_flow_renderer'`

- [ ] **Step 3: 實作**

建立 `concept_momentum/concept_money_flow_renderer.py`：

```python
"""族群資金流 renderer — 排行表 + sparkline + 動能表欄位 + TG 摘要（純渲染）。"""

from concept_money_flow import FLOW_SHARE_PP, FLOW_INST_NTD

_TAG_DESC = {
    "🔥": "真流入：成交額占比升 + 法人買（熱度與真金同向）",
    "⚠": "出貨疑慮：成交額占比升 + 法人賣（散戶接刀風險）",
    "🧲": "低調吸收：成交額占比降 + 法人買（沒人注意但法人默默買）",
    "❄": "退潮：成交額占比降 + 法人賣（熱度與資金雙離開）",
    "—": "未達門檻，不強行分類",
}

_THRESHOLD_NOTE = (f"門檻：占比變化 ±{FLOW_SHARE_PP}pp 且 法人淨流 ±{FLOW_INST_NTD}億，"
                   "未達則標 —。門檻為先驗設定、未經回測驗證。")


def _sparkline_svg(values: list[float], width: int = 120, height: int = 28) -> str:
    """inline SVG 折線（法人淨流 5 日滾動累計）；跨 0 畫灰色零線。<2 點回 '—'。"""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return "—"
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1.0
    n = len(vals)

    def x(i):
        return round(i * (width - 2) / (n - 1) + 1, 1)

    def y(v):
        return round(height - 2 - (v - vmin) * (height - 4) / (vmax - vmin), 1)

    pts = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(vals))
    zero = ""
    if vmin < 0 < vmax:
        zy = y(0)
        zero = (f'<line x1="1" y1="{zy}" x2="{width - 1}" y2="{zy}" '
                f'stroke="#ccc" stroke-width="1"/>')
    return (f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" style="vertical-align:middle;">'
            f'{zero}<polyline points="{pts}" fill="none" '
            f'stroke="#1f77b4" stroke-width="1.5"/></svg>')


def _fmt_streak(streak: int) -> str:
    if streak > 0:
        return f"買{streak}日"
    if streak < 0:
        return f"賣{-streak}日"
    return "—"


def render_tab(view_rows: list[dict], asof: str) -> str:
    """排行表（34 主題全列，依法人淨流降冪）+ 圖例 + 使用時機盒。"""
    if not view_rows:
        return ('<p class="empty-state" style="text-align:center;padding:20px;color:#888;">'
                '尚無資金流資料 — 請先執行 '
                '<code>python3 concept_money_flow.py --backfill 60</code></p>')
    parts = [
        f'<p class="meta">資料至 {asof} | 法人淨流 = 淨股數 × 收盤價（近似值）</p>',
        '<div class="table-scroll" style="overflow-x:auto;">',
        '<table class="market-breadth">',
        '<thead><tr>'
        '<th title="主題板塊（concepts.json，一檔可屬多主題）">族群</th>'
        '<th title="占比變化 × 法人淨流 交叉判讀：'
        '&#10;🔥 真流入（占比升+法人買）&#10;⚠ 出貨疑慮（占比升+法人賣，散戶接刀）'
        '&#10;🧲 低調吸收（占比降+法人買）&#10;❄ 退潮（占比降+法人賣）'
        f'&#10;&#10;{_THRESHOLD_NOTE}">標記</th>'
        '<th title="族群內每檔（外資+投信+自營）淨買賣股數 × 當日收盤價 加總，單位億元。'
        '正=淨買（流入）。注意是近似值：法人實際成交價分布在盤中">今日法人淨流(億)</th>'
        '<th title="外資（含外資自營）單獨的淨流金額（億）">外資(億)</th>'
        '<th title="投信單獨的淨流金額（億）。自營商計入總計但不單獨列（多為避險單、雜訊高）">投信(億)</th>'
        '<th title="最近 5 個交易日法人淨流合計（億）">5日累計(億)</th>'
        '<th title="法人連續淨買/淨賣天數（尾端起算，0 中斷）">連續</th>'
        '<th title="族群成交金額 ÷ 全市場（上市櫃 4 位數普通股）成交金額。'
        '一檔可屬多主題 → 各族群占比加總會超過 100%">今日占比%</th>'
        '<th title="今日占比 − 過去 20 個交易日平均占比（百分點 pp）。正=熱度升。'
        '歷史不足 20 日時用現有天數平均並標 *">占比vs20日均(pp)</th>'
        '<th title="法人淨流 5 日滾動累計的 60 日走勢（灰線=0）">60日趨勢</th>'
        '</tr></thead><tbody>']
    for r in view_rows:
        net = r.get("inst_net_ntd") or 0.0
        cls = "pos" if net > 0 else ("neg" if net < 0 else "")
        sv = r.get("share_vs_20d")
        star = "*" if r.get("share_samples", 0) < 20 else ""
        sv_txt = f"{sv:+.2f}{star}" if sv is not None else "—"
        sv_cls = "pos" if (sv or 0) > 0 else ("neg" if (sv or 0) < 0 else "")
        share = r.get("mkt_share_pct")
        share_txt = f"{share:.2f}" if share is not None else "—"
        parts.append(
            '<tr>'
            f'<td>{r["name_zh"]}</td>'
            f'<td title="{_TAG_DESC.get(r.get("tag", "—"), "")}">{r.get("tag", "—")}</td>'
            f'<td class="{cls}">{net:+.1f}</td>'
            f'<td>{r.get("foreign_net_ntd", 0) or 0:+.1f}</td>'
            f'<td>{r.get("trust_net_ntd", 0) or 0:+.1f}</td>'
            f'<td>{r.get("net_5d", 0) or 0:+.1f}</td>'
            f'<td>{_fmt_streak(r.get("streak", 0))}</td>'
            f'<td>{share_txt}</td>'
            f'<td class="{sv_cls}">{sv_txt}</td>'
            f'<td>{_sparkline_svg(r.get("spark", []))}</td>'
            '</tr>')
    parts.append('</tbody></table></div>')
    parts.append(
        '<p style="font-size:0.8em; color:#888; margin:4px 0 0;">'
        '🔥 真流入（占比升+法人買）　⚠ 出貨疑慮（占比升+法人賣）　'
        '🧲 低調吸收（占比降+法人買）　❄ 退潮（占比降+法人賣）　— 未達門檻<br>'
        f'{_THRESHOLD_NOTE}　占比欄標 * = 歷史樣本不足 20 日'
        '</p>')
    parts.append(
        '<p style="font-size:0.8em; color:#a06000; background:#fdf6e8; '
        'padding:6px 10px; border-radius:4px; margin:6px 0 0;">'
        '📌 <b>使用時機與限制</b>：本頁是<b>輪動觀察工具、非買賣訊號</b>——法人買不代表會漲。'
        '法人金額 = 淨股數 × 收盤價，是<b>近似</b>值；'
        '占比會因單一權值股爆量而失真（例：台積電同時屬多個主題）；'
        '一檔可屬多主題 → 占比加總 &gt;100%、族群間金額會重複計算；'
        '四象限門檻未經回測驗證，累積數據後才能校準。</p>')
    return "\n".join(parts)


def render_flow_cells(theme_key: str, flow_map: dict | None) -> str:
    """動能排行表用的兩個 <td>：法人淨流(億) + 標記。無資料回 — 。"""
    r = (flow_map or {}).get(theme_key)
    if not r:
        return "<td>—</td><td>—</td>"
    net = r.get("inst_net_ntd") or 0.0
    cls = "pos" if net > 0 else ("neg" if net < 0 else "")
    tag = r.get("tag", "—")
    return (f'<td class="{cls}">{net:+.1f}</td>'
            f'<td title="{_TAG_DESC.get(tag, "")}">{tag}</td>')


def _tg_row(r: dict) -> str:
    streak = r.get("streak", 0)
    s = f" 連{abs(streak)}日" if abs(streak) >= 2 else ""
    sv = r.get("share_vs_20d")
    sv_txt = f" 占比{sv:+.2f}pp" if sv is not None else ""
    return (f"{r.get('tag', '—')} {r['name_zh']} {r['inst_net_ntd']:+.1f}億"
            f"(外{r['foreign_net_ntd']:+.1f} 投{r['trust_net_ntd']:+.1f}){s}{sv_txt}")


def build_tg_summary(view_rows: list[dict], date_str: str) -> str:
    """Telegram 文字摘要：流入/流出 Top5 + ⚠ 出貨疑慮 + 連續 ≥5 日異常。"""
    lines = [f"💰 族群資金流 {date_str}",
             "法人淨流=淨股數×收盤價(近似) | 標記門檻未經回測",
             "━━━━━━━━━━━━"]
    pos = [r for r in view_rows if (r.get("inst_net_ntd") or 0) > 0][:5]
    neg = sorted([r for r in view_rows if (r.get("inst_net_ntd") or 0) < 0],
                 key=lambda r: r["inst_net_ntd"])[:5]
    lines.append("流入 Top5:")
    if pos:
        for r in pos:
            lines.append(f"  {_tg_row(r)}")
    else:
        lines.append("  （無）")
    lines.append("\n流出 Top5:")
    if neg:
        for r in neg:
            lines.append(f"  {_tg_row(r)}")
    else:
        lines.append("  （無）")
    warns = [r for r in view_rows if r.get("tag") == "⚠"]
    if warns:
        lines.append("\n⚠ 出貨疑慮（熱度升但法人賣）:")
        for r in warns:
            sv = r.get("share_vs_20d")
            sv_txt = f"占比{sv:+.2f}pp " if sv is not None else ""
            lines.append(f"  {r['name_zh']} {sv_txt}法人{r['inst_net_ntd']:+.1f}億")
    streaky = [r for r in view_rows if abs(r.get("streak", 0)) >= 5]
    if streaky:
        lines.append("\n📌 連續 ≥5 日:")
        for r in streaky:
            side = "買超" if r["streak"] > 0 else "賣超"
            lines.append(f"  {r['name_zh']} 連{abs(r['streak'])}日{side}")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m pytest tests/test_concept_money_flow_renderer.py tests/test_concept_money_flow.py -v 2>&1 | tail -8`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add concept_momentum/concept_money_flow_renderer.py tests/test_concept_money_flow_renderer.py
git commit -m "feat: 族群資金流 renderer（排行表+sparkline+動能表欄位+TG 摘要）"
```

---

### Task 4: app.py — `/money-flow` 獨立頁 + 術語表

**Files:**
- Modify: `concept_momentum/app.py`（`_BACKTEST_GLOSSARY.update` 區塊約 4433 行附近；route 加在 `/signal-outcomes` route 之後、`if __name__` 之前）

**Interfaces:**
- Consumes: `concept_money_flow.load_flow_days/load_themes/build_view_rows`、`concept_money_flow_renderer.render_tab`、既有 `_glossary_section(keys)`
- Produces: GET `/money-flow` 頁面；術語表新 keys：`"法人淨流 (億)"`, `"成交額占比"`, `"資金流標記 (🔥/⚠/🧲/❄)"`, `"占比 vs 20日均 (pp)"`

- [ ] **Step 1: 加術語表條目**

在 app.py 既有的 `_BACKTEST_GLOSSARY.update({...})`（約 4433 行）之後，新增一個 update 區塊：

```python
_BACKTEST_GLOSSARY.update({
    "法人淨流 (億)": (
        "外資（含外資自營）+ 投信 + 自營商 當日淨買賣「股數」× 當日收盤價，"
        "加總成金額（億元）。正 = 淨買（資金流入）、負 = 淨賣（流出）。"
        "注意這是<b>近似值</b>：法人實際成交價分布在盤中各時點，這裡統一用收盤價換算。"
        "資料源 FinMind TaiwanStockInstitutionalInvestorsBuySell（原始單位是股數）。"),
    "成交額占比": (
        "族群成交金額 ÷ 全市場（上市櫃 4 位數普通股）成交金額 × 100%。"
        "代表市場資金的「注意力」有多少放在這個族群，不分買賣方向。"
        "一檔股票可屬多個主題 → 各族群占比加總會超過 100%；"
        "單一權值股爆量（如台積電）會讓它所屬的每個主題占比同時失真。"),
    "資金流標記 (🔥/⚠/🧲/❄)": (
        "占比變化與法人淨流的交叉判讀：🔥 占比升+法人買 = 真流入（熱度與真金同向）；"
        "⚠ 占比升+法人賣 = 出貨疑慮（人氣升但法人倒貨，散戶接刀風險）；"
        "🧲 占比降+法人買 = 低調吸收（沒人注意但法人默默買）；"
        "❄ 占比降+法人賣 = 退潮（熱度與資金雙離開）。"
        "門檻：占比變化 ±0.15pp 且 法人淨流 ±0.5 億，未達門檻標 —（不強行分類）。"
        "<b>門檻為先驗設定、未經回測驗證</b>，累積數據後才能校準。"),
    "占比 vs 20日均 (pp)": (
        "今日成交額占比 − 過去 20 個交易日的平均占比，單位百分點 (pp)。"
        "例：某族群平常占全市場成交額 3.0%、今日 3.8% → +0.8pp，熱度明顯升。"
        "歷史不足 20 日時用現有天數平均並標 *（樣本不足，數字較不穩）。"),
})
```

- [ ] **Step 2: 加 route**

在 `/signal-outcomes` route（約 4965 行）之後加：

```python
@app.route("/money-flow")
def money_flow_page():
    import concept_money_flow as cmf
    import concept_money_flow_renderer as cmfr
    from datetime import datetime as _dt
    day_files = cmf.load_flow_days(_dt.now().strftime("%Y%m%d"), days=60)
    rows = []
    asof = "—"
    if day_files:
        try:
            rows = cmf.build_view_rows(day_files, cmf.load_themes())
            asof = day_files[-1]["date"]
        except Exception:
            rows = []
    body = cmfr.render_tab(rows, asof)
    glossary = _glossary_section(["法人淨流 (億)", "成交額占比",
                                  "資金流標記 (🔥/⚠/🧲/❄)", "占比 vs 20日均 (pp)"])
    css = """
<style>
body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#f5f5f7; margin:0; padding:16px; }
h2 { font-size:1.4em; margin:0 0 4px; }
p.meta { font-size:0.85em; color:#666; margin:0 0 12px; }
.table-scroll { overflow-x:auto; }
table.market-breadth { width:100%; border-collapse:collapse; background:#fff;
  border-radius:8px; overflow:hidden; margin-bottom:16px;
  box-shadow:0 2px 8px rgba(0,0,0,0.05); font-size:0.88em; }
table.market-breadth th,
table.market-breadth td { padding:6px 10px; border-bottom:1px solid #eee;
  text-align:right; }
table.market-breadth th { background:#fafafa; font-weight:600; text-align:center; }
table.market-breadth td:first-child,
table.market-breadth th:first-child { text-align:left; }
.pos { color:#0a7e0a; }
.neg { color:#c30; }
a { color:#007aff; text-decoration:none; }
a:hover { text-decoration:underline; }
</style>"""
    return f"""<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>💰 族群資金流</title>
{css}
</head><body>
<p><a href="/">&larr; 返回主控板</a></p>
<h2>💰 族群資金流（最近 60 個交易日）</h2>
{body}
{glossary}
</body></html>"""
```

（`_glossary_section` 是既有函式，key 不存在會被靜默丟掉 — Step 4 的驗證會抓這種錯。）

- [ ] **Step 3: 重啟 dashboard 服務**

Run: `systemctl --user restart concept-dashboard.service && sleep 2`

- [ ] **Step 4: 驗證**

Run:
```bash
curl -s http://localhost:5000/money-flow | grep -c "尚無資金流資料\|法人淨流"
curl -s http://localhost:5000/money-flow | grep -c "未經回測"
```
Expected: 兩個都 ≥1（Task 2 Step 5 已寫入 20260713 單日檔 → 表格會有資料但占比欄多為 `*` 樣本不足；若環境無該檔則顯示 empty state — 兩者都算過）。四個術語 key 都要出現：`curl -s http://localhost:5000/money-flow | grep -o "法人淨流 (億)\|成交額占比\|資金流標記\|占比 vs 20日均" | sort -u` 應列出 4 個。

- [ ] **Step 5: Commit**

```bash
git add concept_momentum/app.py
git commit -m "feat: /money-flow 族群資金流獨立頁 + 4 條術語表白話條目"
```

---

### Task 5: 回補 60 個交易日（live 執行）

**Files:** 無程式碼改動 — 執行 Task 2 的 CLI 並驗證資料品質。

**Interfaces:**
- Consumes: Task 2 CLI
- Produces: `cache/money_flow/` 下 ~60 個日檔，供 Task 6 的 dashboard 烤製與 `/money-flow` 使用

- [ ] **Step 1: 執行回補（~120 次 API 呼叫，量小）**

Run: `cd /home/kun/project/tw_stock_tools/concept_momentum && FINMIND_TOKEN=<依環境取得，同 Task 2 Step 5> python3 concept_money_flow.py --backfill 60 2>&1 | tail -5`
Expected: `回補完成，新寫 5X 日`（含 Task 2 已寫的 20260713 會跳過；今天 20260714 若 16:00 後跑會成功、更早則「尚未發布」跳過 — 都正常）。若中途 quota 402：等 quota window 重跑同指令即可（resumable）。

- [ ] **Step 2: 資料品質驗證**

Run:
```bash
python3 - <<'EOF'
import json, os
d = sorted(os.listdir('cache/money_flow'))
print('日檔數:', len(d), '首尾:', d[0], d[-1])
import concept_money_flow as cmf
days = cmf.load_flow_days(d[-1][:8], days=60)
rows = cmf.build_view_rows(days, cmf.load_themes())
print('view rows:', len(rows))
full = [r for r in rows if r['share_samples'] >= 20]
print('樣本足 20 日的主題數:', len(full))
tags = {}
for r in rows: tags[r['tag']] = tags.get(r['tag'], 0) + 1
print('標記分布:', tags)
top = rows[0]
print('今日最大流入:', top['name_zh'], top['inst_net_ntd'], '億, streak', top['streak'])
EOF
```
Expected: 日檔數 ≈60、view rows = 34、樣本足的主題 = 34（回補後全部有 20 日歷史）、標記分布合理（大多數 `—`，少數 🔥/❄）。**Sanity check：市場成交額每億檔約 3000-6000 億、單族群單日法人淨流通常 <100 億 — 若出現千億級族群淨流，單位換算有 bug，停下來查。**

- [ ] **Step 3: 再驗 `/money-flow` 頁（現在有完整數據）**

Run: `curl -s http://localhost:5000/money-flow | grep -c "<svg"`
Expected: ≥30（每個主題一條 sparkline）

- [ ] **Step 4: Commit（只有 log/無程式碼就跳過；cache 是 gitignored）**

Run: `git status --short` — 若無 tracked 檔案變動，本 task 不 commit。

---

### Task 6: run_daily + concept_charts 掛載（分頁 tab、動能表兩欄、TG 推播）

**Files:**
- Modify: `concept_momentum/run_daily.py`（import 區、main() 的 market_breadth 段之後、`--telegram` 推播段）
- Modify: `concept_momentum/concept_charts.py`（`generate_html` 簽名約 340 行、g-flow tab group 約 620-628 行、tab-content 區約 666-675 行、主表 thead 約 685-697 行、table_rows 迴圈約 494-511 行、module import 區）

**Interfaces:**
- Consumes: `concept_money_flow.run_day/load_flow_days/build_view_rows`、`concept_money_flow_renderer.render_tab/render_flow_cells/build_tg_summary`
- Produces: `generate_html(..., money_flow_html: str = "", money_flow_map: dict | None = None)` 新簽名；dashboard.html 新 tab `moneyflow`；TG 新推播訊息

- [ ] **Step 1: concept_charts.py — import 與簽名**

module 頂部 import 區（其他 import 旁）加：

```python
from concept_money_flow_renderer import render_flow_cells
```

`generate_html` 簽名（約 340 行）改為：

```python
def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str,
                  breadth_table_html: str = "",
                  broker_radar_html: str = "",
                  premarket_signals_html: str = "",
                  lending_history_html: str = "",
                  money_flow_html: str = "",
                  money_flow_map: dict | None = None) -> str:
```

- [ ] **Step 2: concept_charts.py — nav tab + tab content**

g-flow tab group（`訊號監控 · 依時段`，約 620-628 行）的 `tab-group-items` 內、`📈 訊號成效` 那行之前，加：

```html
      <div class="tab" onclick="showTab('moneyflow')">💰 族群資金流 (17:00)</div>
```

tab-content 區（`tab-lending` div 之後、`tab-snap` 之前）加（注意整段在 f-string 內，字面大括號要寫 `{{ }}`，插值 `{money_flow_html}` 單括號）：

```html
<div id="tab-moneyflow" class="tab-content chart-wrap">
  <h2>💰 族群資金流（最近 60 個交易日）</h2>
  <p class="meta">法人淨流 = 淨股數 × 收盤價（近似）| 每日 17:00 更新 |
     <a href="/money-flow">→ 獨立頁（即時、含完整術語表）</a></p>
  {money_flow_html}
</div>
```

- [ ] **Step 3: concept_charts.py — 主表兩欄**

thead（約 696 行 `評分` th 之後）加：

```html
      <th title="族群當日三大法人淨買賣金額（億；淨股數×收盤價近似）— 詳見 💰 族群資金流分頁">法人淨流(億)</th>
      <th title="資金流標記：🔥 真流入（占比升+法人買）/ ⚠ 出貨疑慮（占比升+法人賣）/ 🧲 低調吸收（占比降+法人買）/ ❄ 退潮（占比降+法人賣）/ — 未達門檻。門檻 占比±0.15pp+法人±0.5億（先驗設定，未經回測）">資金流</th>
```

table_rows 迴圈（約 510 行 `sustainability_score` td 之後）加：

```python
            {render_flow_cells(r.get('theme_key', ''), money_flow_map)}
```

（table_rows 是 f-string 累加 — 直接在 `</tr>` 前插入這個插值。）

- [ ] **Step 4: run_daily.py — import 與計算掛載**

import 區（`from lending_history_renderer import ...` 之後）加：

```python
from concept_money_flow import (run_day as run_money_flow,
                                load_flow_days, build_view_rows)
from concept_money_flow_renderer import (render_tab as render_money_flow_tab,
                                         build_tg_summary as build_money_flow_summary)
```

main() 中 market_breadth 段（`breadth_html = render_table(rows)` 之後、「Strategy history tabs」之前）加：

```python
    # 族群資金流 — 抓當日 + 渲染（fail-open：失敗只 log，dashboard 顯示到最後有資料日）
    money_flow_html = ""
    money_flow_map = {}
    mf_summary = ""
    if finmind_token:
        print("計算族群資金流...", file=sys.stderr)
        try:
            run_money_flow(target_yyyymmdd, finmind_token, verbose=True)
        except Exception as e:
            print(f"[WARN] money_flow: {e}", file=sys.stderr)
        mf_days = load_flow_days(target_yyyymmdd, days=60)
        if mf_days:
            mf_rows = build_view_rows(mf_days, concepts["themes"])
            money_flow_html = render_money_flow_tab(mf_rows, mf_days[-1]["date"])
            money_flow_map = {r["theme_key"]: r for r in mf_rows}
            # 只有「今天」的資料真的存在才推 TG（勿推 stale 或空資料）
            if mf_days[-1]["date"] == target_yyyymmdd:
                mf_summary = build_money_flow_summary(mf_rows, target_date)
```

`generate_html(...)` 呼叫（約 337 行）加兩個參數：

```python
    html_path = generate_html(
        results, taiex, target_date,
        breadth_table_html=breadth_html,
        broker_radar_html=broker_html,
        premarket_signals_html=premarket_html,
        lending_history_html=lending_html,
        money_flow_html=money_flow_html,
        money_flow_map=money_flow_map,
    )
```

- [ ] **Step 5: run_daily.py — TG 推播**

`--telegram` 段、業務轉型推播（`ok5 = send_telegram_text(drift_summary, ...)`) 之後加：

```python
        ok_mf = True
        if mf_summary:
            time.sleep(1)
            print("推送族群資金流摘要...", file=sys.stderr)
            ok_mf = send_telegram_text(mf_summary, bot_token, args.chat_id)
```

並把總結判斷 `if ok1 and ok_trend and ok2 and ok3 and ok4 and ok5:` 改為：

```python
        if ok1 and ok_trend and ok2 and ok3 and ok4 and ok5 and ok_mf:
```

- [ ] **Step 6: 重生成 dashboard 驗證（不推 TG）**

Run: `cd /home/kun/project/tw_stock_tools/concept_momentum && FINMIND_TOKEN=<同前> python3 run_daily.py --skip-fetch 2>&1 | tail -5`
Expected: 正常跑完印出 `HTML: .../dashboard.html`，stderr 出現「計算族群資金流...」。

Run:
```bash
grep -c "tab-moneyflow\|showTab('moneyflow')" templates/dashboard.html
grep -c "法人淨流(億)" templates/dashboard.html
curl -s http://localhost:5000/ | grep -c "族群資金流"
```
Expected: 第一個 ≥2（tab 按鈕+內容 div）、第二個 ≥1（主表新欄）、第三個 ≥2。瀏覽器層面：主控板 tab 列「訊號監控」群組出現「💰 族群資金流 (17:00)」且點開有表格。

- [ ] **Step 7: 全測試迴歸**

Run: `cd /home/kun/project/tw_stock_tools && python3 -m pytest tests/ -v 2>&1 | tail -8`
Expected: 新舊測試全 PASS（`test_chip_price` 既有 2 個 error、`test_param_sweep` 他人 WIP — 維持原狀即可，不新增紅字）。

- [ ] **Step 8: Commit**

```bash
git add concept_momentum/run_daily.py concept_momentum/concept_charts.py
git commit -m "feat: 族群資金流掛進 run_daily（dashboard 分頁+動能表兩欄+TG 推播）"
```

---

### Task 7: README 更新 + 收尾

**Files:**
- Modify: `concept_momentum/README.md`（功能清單/分頁清單處）
- Modify: `README.md`（repo 根，若有 dashboard 功能總表）

**Interfaces:**
- Consumes: 前面所有 task 的最終行為
- Produces: 文件

- [ ] **Step 1: concept_momentum/README.md**

在功能/分頁清單加一節（措辭比照既有節奏）：

```markdown
### 💰 族群資金流（2026-07-14 加入）

34 個主題板塊每日的資金流入流出：

- **法人淨流（億）**：族群內每檔（外資+投信+自營）淨買賣股數 × 收盤價加總。近似值（實際成交價分布盤中）。
- **成交額占比**：族群成交額 ÷ 全市場（4 位數普通股）成交額；「占比 vs 20 日均」看熱度輪動。
- **四象限標記**：🔥 真流入（占比升+法人買）/ ⚠ 出貨疑慮（占比升+法人賣）/ 🧲 低調吸收 / ❄ 退潮。
  門檻 `FLOW_SHARE_PP=0.15`pp、`FLOW_INST_NTD=0.5` 億 — **先驗設定，未經回測驗證**。

入口：dashboard「訊號監控」群組 tab（17:00 烤入）＋ `/money-flow` 獨立頁（即時）＋ 動能排行表兩欄 ＋ 每日 TG 摘要（流入/流出 Top5、⚠、連續 ≥5 日）。

資料：`cache/money_flow/{yyyymmdd}.json`（一天一檔；FinMind 單日全市場 2 次呼叫）。
回補：`python3 concept_money_flow.py --backfill 60`（resumable、已存在跳過、需 FINMIND_TOKEN）。
Fail-open：法人未發布/API 失敗不寫檔，dashboard 顯示到最後有資料日。
限制：一檔可屬多主題（占比加總 >100%）；權值股爆量會使占比失真；輪動觀察工具、非買賣訊號。
```

- [ ] **Step 2: repo 根 README**

若根 README 有 dashboard 頁面/功能清單，加一行 `💰 族群資金流 — 族群法人淨流+成交額占比輪動（/money-flow）`；沒有對應清單就跳過。

- [ ] **Step 3: 最終驗證清單**

```bash
cd /home/kun/project/tw_stock_tools
python3 -m pytest tests/test_concept_money_flow.py tests/test_concept_money_flow_renderer.py -q
curl -s http://localhost:5000/money-flow | grep -c "使用時機與限制"
curl -s http://localhost:5000/ | grep -c "族群資金流"
```
Expected: 測試全綠、兩個 grep 都 ≥1。

- [ ] **Step 4: Commit**

```bash
git add concept_momentum/README.md README.md
git commit -m "docs: README 補族群資金流功能說明（指標定義/入口/回補/限制）"
```

---

## 驗收總表（對照 spec）

| Spec 節 | 對應 task |
|---|---|
| §2 指標定義（法人淨流/占比/標記/門檻常數） | Task 1 |
| §3 資料流/日檔/回補/邊界 fail-open | Task 2, 5 |
| §4a 分頁（表格/sparkline/術語/使用時機） | Task 3, 4, 6 |
| §4b 動能表兩欄 | Task 3, 6 |
| §4c TG 推播（Top5/⚠/連續≥5/無資料不推） | Task 3, 6 |
| §5 模組切分 | Task 1-4, 6 |
| §6 測試 | Task 1, 2, 3, 6(迴歸) |
| §7 慣例（README/restart/cron 不新增） | Task 4(restart), 7 |

注意事項（給執行者）：
- 今晚 17:00 cron 會自然跑到新掛載 — 若當天實作完成，明早檢查 `daily.log` 與 TG 是否出現「💰 族群資金流」訊息。
- dashboard tab 版內容是 17:00 烤入 dashboard.html 的；`/money-flow` 獨立頁即時。
- 不要手動對使用者的 TG chat 推測試訊息；驗證靠單元測試 + 今晚 cron。
