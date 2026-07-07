# 選股策略與回測改進 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正四個既有回測的方法論缺陷（進場時點、除權息、統計顯著性、train/serve 偏差）、補上旗艦策略「轉機接力」與借券雷達/空頭撤退的回測、建立每日推播訊號的自動成效追蹤，讓所有策略的 edge 判斷有統計依據。

**Architecture:** 新增共用模組 `backtest_lib.py`（成本模型 + bootstrap 統計 + 日期配對基準 + 價格面板），把 4 個既有回測腳本改成吃 v2 價格快取（含開盤價 + 還原價 + 除權息日），再以同一套 lib 新寫 2 個回測與 1 個成效追蹤器。策略端修 4 個正確性 bug（Layer 2 盤前視窗錯位、GM 快取過期、除權息假訊號、主力雷達用到已淘汰評分）。

**Tech Stack:** Python 3.10 stdlib + numpy（intraday_sim 已引入，允許）。測試用 stdlib `unittest`（沿用 `tests/` 現有慣例，`python3 -m unittest`）。資料源 FinMind v4（sponsor token，已驗證 `TaiwanStockPriceAdj` 與 `TaiwanStockDividend` 可用）。

## Global Constraints

- **每個 task 完成後必須同步更新 `README.md` 對應章節**（使用者明確要求：改 code 必須同步改 README，不能只 commit code）。
- **所有新增/修改的 crontab 行必須帶 `FINMIND_TOKEN=` 環境變數**（歷史教訓：漏掉會靜默失敗）。
- FinMind token 取得方式沿用現有 `_token()` 模式：先讀 `FINMIND_TOKEN` 環境變數，否則從 `crontab -l` 解析。
- 測試框架：stdlib `unittest`，檔案放 `tests/test_*.py`，跑法 `python3 -m unittest tests.test_xxx -v`。打真 API 的測試要 `@unittest.skipUnless(TOKEN, ...)`（見 `tests/test_finmind_client.py` 慣例）。
- 回測 JSON 輸出**保留所有既有欄位**（dashboard 網頁讀取），新欄位只增不刪。
- 日期格式：回測腳本內部 `YYYYMMDD`、FinMind API `YYYY-MM-DD`——與現況一致，轉換點註明。
- 成交量單位：FinMind `Trading_Volume` = 股（shares），與現有 panel 一致；張 = 股/1000。
- Git：每個 task 至少一個 commit，訊息用中文、格式仿 `git log`（例：`回測: 加 bootstrap CI + 日期配對基準`）。
- **多重比較紀律**（working agreement）：本計畫只「修正衡量方式」，**不調整任何策略參數**。參數調整屬後續工作，且必須用 2026-03 前資料調參、2026-03 後資料驗證（見 Backlog）。

---

## 背景與診斷（為什麼要做這些）

實作者不需要重新驗證這些發現，但改到相關檔案時請對照確認行號（行號基於 commit `40a4269`）。

### 現有四個回測的結果（2026-06 底跑的數字）

| 回測 | 樣本 | 關鍵數字 | 問題 |
|------|------|---------|------|
| 強勢股第二波 (`tw_second_wave_backtest.py`) | 688 episodes，全市場 1991 檔，2025-01~2026-06 | H=5 淨超額 **-0.64%**、H=10 **-0.87%**、H=20 **+1.22%**；中位數超額 **全負** (-2.38/-2.66/-3.38%)；edge +0.43/+1.26/+5.55% | edge 為正主要因為基準（隨機股票日）是 -1.07~-4.33%（小型股 2025-26 跑輸大盤）；均值被右尾少數大贏家拉起，**中位數 episode 是輸的**。無 CI、無顯著性檢定 |
| 主力雷達 (`tw_broker_radar_backtest.py`) | 55 episodes（2026-05-10 起累積） | entry=next H=5 超額 +2.85%、edge +4.31%、勝率 59% | 樣本極小（H=20 只剩 21），無 CI；基準抽樣期間與事件日期分布不匹配 |
| 族群熱力 (`tw_concept_backtest.py`) | 63 個 rebalance 點 | IC 0.128~0.194（IC>0 比例 71-79%）、L2 累積淨超額 75.6/171/334% | rebalance=5 天但 H=10/20 → **期間重疊**，累積報酬與 MaxDD/Calmar 被灌水（H=20 重疊 4 倍）；L2 選股與正式版有 train/serve 偏差（見下） |
| 盤中模擬 (`tw_intraday_sim_backtest.py`) | 800 + 6240 測試點 | 方向命中 51.6%（但 base rate 43% 上漲 → **永遠猜跌就有 57%**）；skill_vs_zero **-2.4%**；信心帶覆蓋 41%（目標 50）/69%（目標 80） | 回測誠實地顯示**無預測力**，但 `/intraday-sim` 頁面照常呈現模擬 → 使用者可能誤信。屬 Backlog（本計畫不動它） |

### 回測方法論缺陷（全部回測共通）

1. **進場價不可實現**。第二波訊號是盤前 07:40 用昨收算的，最早能成交的是**今日開盤價**；回測卻用「訊號日收盤→H 日後收盤」（`tw_second_wave_backtest.py:110-116`），把隔夜跳空全算進去。主力雷達至少提供 `--entry next`（隔日收盤），但沒有隔日**開盤**。而價格快取 `backtest_prices_all.json` 每列只有 `{date, close, volume}`——**沒有開盤價**，想修也修不了 → 必須先擴 schema（Task 2）。
2. **除權息污染**。全部價格來自 FinMind `TaiwanStockPrice`（未還原）。(a) 報酬衡量：持有期跨除息日的報酬被低估（配 5% 息顯示 -5%）；(b) 訊號偵測：除權息缺口會偽造第二波的「急跌 15-25%」（F3），**7-9 月除權息旺季是系統性假訊號來源**——`tw_second_wave.py:147` 註解「Raw close is correct」只考慮到還原價會扭曲 pattern 形狀，沒考慮除權缺口偽造 pattern。已驗證 sponsor token 可用 `TaiwanStockPriceAdj` 與 `TaiwanStockDividend`（`tw_dormant_giants.py` 與 README 中「PriceAdj 需付費」的註記已過時）。
3. **無統計顯著性**。所有回測只報均值/勝率，無 CI、無 t-stat。主力雷達 n=55、第二波中位數與均值方向相反——沒有 CI 根本無法判斷 edge 是不是雜訊。
4. **基準期間錯位**。主力雷達的隨機基準（`tw_broker_radar_backtest.py:53-76`）在 2026-03 之後的**全部**日子均勻抽樣，但事件集中在 2026-05~07；若期間內市場 regime 變化，edge 失真。正確做法：**與事件同日期**抽隨機股票（date-matched）。
5. **Episode 去重不一致**。第二波用「連續觸發取首日」（`prev_fire`），主力雷達用「H 日 cooldown」。統一成 cooldown 法。
6. **參數雙份維護**。`tw_second_wave_backtest.py:93-97` 手抄 `tw_second_wave.py` 的 argparse 預設值（註解自己說「與 add_argument 預設一致」）——漂移風險。
7. **成本模型過簡**。一律 0.4%。台股實際：手續費 0.1425%×2×折扣 + 證交稅 0.3%（6 折 → 0.471%），且無滑價敏感度。

### Train/serve 偏差（回測測的不是正式版跑的）

8. **族群熱力 L2 選股**：正式版 `analyze_concept` 先過 `filter_liquid_stocks`（20d 均量 ≥500 張，`concept_momentum/concept_momentum.py:247`）再取 leaders；回測 `tw_concept_backtest.py:288-296` **不過流動性濾網**直接 `extract_leaders`。
9. **族群 ret_20d 口徑**：正式版排序用**成交額加權指數**的 20 日報酬（`concept_momentum.py:271-272` + `analyze_all` 424）；回測 filter 變體用**等權成員均值**（`tw_concept_backtest.py:173-183`）。兩個排名不同。
10. **主力雷達的概念強勢股來源**：`tw_broker_monitor.py:116-117` 仍用 `sustainability_score >= 70` 挑強勢族群，但正式選股已改成 C 變體（`passes_gate` + `ret_20d`，`concept_momentum.py:189-191`）——用到已淘汰的評分。

### 正式訊號的正確性 bug

11. **Layer 2 盤前模式視窗錯位一天**。`tw_limitup_signal.py` 的 A/D 訊號設計是「px[-1]=漲停日本身、px[-2]=前日」（standalone 盤後模式正確）。但 `tw_daily_screen.py` 盤前 07:30 呼叫時 target=今日、資料只到昨收 → px[-1]=**昨日**被當成「漲停日」，於是 A 檢查的是前日~大前日的漲幅（`signal_a_relay` 只迴圈 i∈(-2,-3,-4)，`tw_limitup_signal.py:423`）、D 用的是**前日**量（`signal_d_volume` 用 px[-2]，`:497`）——**昨天剛發生的漲幅與量能永遠不進 A/D**。對「明日續攻」預測而言，最新一根 K 棒才是最重要的接力證據。
12. **GM 快取 30 天過期**（`tw_turnaround_screener.py:85-90`）。財報季（5/15、8/14、11/14、3/31 死線）新季報公告後，Layer 1 仍可能用舊季報跑到 30 天。
13. **Layer 2 C 訊號（HiStock 7 日分點）沒有歷史參數**（`HISTOCK_URL` `:53` 無日期參數，cache key 卻含 target_date）——`--date` 回看歷史日會拿到**當前** 7 日資料。live 每日跑不受影響；但任何回顧分析都會拿錯籌碼。修法：文件化限制 + `--date` 非今日時對 C 回傳「無資料」（不給錯的）。
14. **`tw_daily_screen.py` docstring 說 cron 19:00**（`:3`），README 說 07:30（實際 crontab 07:30）——文件不一致，順手修。

### 覆蓋缺口（該有回測而沒有的）

15. **轉機接力（TR）——旗艦盤前策略，完全沒有回測**。Layer 1 四個濾網全部是純函數（`margin_passes`/`volume_passes`/`short_passes`/`ma60_passes` 都吃 list 回 bool）→ 可以像第二波一樣 import 正式偵測函數做 point-in-time 重建。財報要處理**公告時滯**（用法定死線：Q1→5/15、Q2→8/14、Q3→11/14、年報→翌年 3/31）。Layer 2 的 A/B/D 可從價格/SBL 歷史重建；C（分點）無公開歷史，誠實跳過並註明。
16. **借券雷達 / 空頭撤退——每天推播，無回測**。兩者資料（`TaiwanStockSecuritiesLending` / `TaiwanDailyShortSaleBalances`）FinMind 有完整歷史 → 完全可回測。
17. **推播訊號無自動成效追蹤**。README 明寫「後照鏡學習」但目前是手動。5 個歷史快取（`concept_momentum/cache/{turnaround_relay,second_wave,broker_radar,lending_radar,short_retreat}_history/`）已累積約 40 個交易日，schema 已確認（見 Task 12），可以自動算每個推播標的的 T+1/5/10/20 實際超額報酬。
    - ⚠ date 欄位語意不一致（已實測）：`turnaround_relay_history/20260706.json` 內 `date="20260703"`（**資料日**）；`second_wave_history/20260706.json` 內 `date="20260706"`（**執行日**）。追蹤器要分策略正規化。

### 統計品質備註（給實作者的判讀背景）

- 主力雷達的 Pearson 相關係數算在 **n=5 個交易日**上（`tw_broker_lookup.py:212-216`，days 預設 5）——n=5 時 corr≥0.5 的機率在無關聯下約 4 成，此門檻幾乎無過濾力。屬策略設計問題，放 Backlog（改了會讓已累積的事件歷史不可比）。
- 全市場 universe 來自**當前** `TaiwanStockInfo`（`tw_second_wave.py:89-119`）→ 已下市股不在回測 universe（倖存者偏差）。2025-26 影響有限，本計畫在報告中標註 universe 定義，完整處理放 Backlog。

---

## File Structure（本計畫新增/修改）

```
~/project/tw_stock_tools/
├── backtest_lib.py                     # 新增：成本/統計/去重/面板/基準（Task 1）
├── backtest_prices.py                  # 新增：v2 價格快取 builder + loader（Task 2）
├── tw_second_wave.py                   # 修改：FILTER_DEFAULTS 單一來源 + 除權息 guard（Task 3, 4）
├── tw_second_wave_backtest.py          # 修改：v2 快取/next-open/CI/分年（Task 3）
├── tw_broker_radar_backtest.py         # 修改：date-matched 基準 + CI（Task 5）
├── tw_concept_backtest.py              # 修改：流動性 parity + ret_20d parity + 非重疊 L2（Task 6）
├── tw_limitup_signal.py                # 修改：anchor 對齊 + --mode（Task 7）
├── tw_daily_screen.py                  # 修改：傳 --mode premarket + docstring（Task 7）
├── tw_turnaround_screener.py           # 修改：TR_DEFAULTS + GM TTL（Task 8, 10）
├── tw_broker_monitor.py                # 修改：passes_gate 選強勢族群（Task 9）
├── tw_turnaround_backtest.py           # 新增：轉機接力回測（Task 10）
├── tw_lending_backtest.py              # 新增：借券雷達+空頭撤退回測（Task 11）
├── finmind_client.py                   # 修改：加 fetch_dividend_ex_dates（Task 4）
├── concept_momentum/signal_outcomes.py          # 新增：訊號成效追蹤器核心（Task 12）
├── concept_momentum/run_outcomes.py             # 新增：追蹤器 CLI + TG 推播（Task 12）
├── concept_momentum/signal_outcomes_renderer.py # 新增：dashboard tab 渲染（Task 12）
├── tests/test_backtest_lib.py          # 新增（Task 1）
├── tests/test_limitup_anchor.py        # 新增（Task 7）
├── tests/test_signal_outcomes.py       # 新增（Task 12）
└── bt_cache/                           # 新增：回測共用資料快取（gitignore，Task 2/10/11）
```

依賴順序：Task 1 → 2 → 3 →（4~9 任意順序，彼此獨立）→ 10 → 11 → 12。Task 4/7/8/9 不依賴 lib，可穿插執行。

---

### Task 1: `backtest_lib.py` — 共用統計與成本工具

**Files:**
- Create: `backtest_lib.py`
- Test: `tests/test_backtest_lib.py`

**Interfaces（後續 task 依賴這些簽名）:**
- Produces: `cost_roundtrip_pct(discount=0.6, slippage_bp=0.0) -> float`（%）
- Produces: `t_stat(xs: list[float]) -> float`
- Produces: `bootstrap_ci(xs, n_boot=5000, alpha=0.05, seed=7) -> tuple[float, float]`
- Produces: `block_bootstrap_ci(xs, block: int, n_boot=5000, alpha=0.05, seed=7) -> tuple[float, float]`
- Produces: `dedup_cooldown(fires: list[int], cooldown: int) -> list[int]`
- Produces: `summarize_events(abs_rets, exc_rets, cost, edge_samples=None) -> dict`（鍵：`n, abs_mean, exc_mean, exc_med, exc_ci, t, net, win, beat, cost[, edge_mean, edge_ci]`）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_backtest_lib.py
"""backtest_lib 單元測試 — 全部合成資料，不打 API。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_lib as bl


class TestCost(unittest.TestCase):
    def test_default_cost(self):
        # 0.1425*0.6*2 + 0.3 = 0.471
        self.assertAlmostEqual(bl.cost_roundtrip_pct(), 0.471, places=3)

    def test_slippage(self):
        # 加 10bp 單邊滑價 → +0.2%
        self.assertAlmostEqual(
            bl.cost_roundtrip_pct(slippage_bp=10) - bl.cost_roundtrip_pct(), 0.2, places=6)


class TestStats(unittest.TestCase):
    def test_bootstrap_ci_covers_mean(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
        lo, hi = bl.bootstrap_ci(xs, seed=7)
        self.assertLess(lo, 3.0)
        self.assertGreater(hi, 3.0)
        self.assertLess(hi - lo, 1.5)

    def test_bootstrap_deterministic(self):
        xs = [0.5, -1.2, 3.3, 0.1, -0.7, 2.2]
        self.assertEqual(bl.bootstrap_ci(xs, seed=7), bl.bootstrap_ci(xs, seed=7))

    def test_t_stat_zero_mean(self):
        self.assertAlmostEqual(bl.t_stat([-1.0, 1.0, -1.0, 1.0]), 0.0)

    def test_block_bootstrap_runs(self):
        xs = list(range(30))
        lo, hi = bl.block_bootstrap_ci(xs, block=4, seed=7)
        self.assertLess(lo, 14.5)
        self.assertGreater(hi, 14.5)


class TestDedup(unittest.TestCase):
    def test_cooldown(self):
        # 觸發於 5,6,7,30,31,60；cooldown 20 → 5, 30, 60... 30-5=25>20 ✓, 60-30=30>20 ✓
        self.assertEqual(bl.dedup_cooldown([5, 6, 7, 30, 31, 60], 20), [5, 30, 60])

    def test_cooldown_boundary(self):
        # 差距恰等於 cooldown 不放行（需 > cooldown）
        self.assertEqual(bl.dedup_cooldown([0, 20, 21], 20), [0, 21])


class TestSummary(unittest.TestCase):
    def test_summarize_keys(self):
        s = bl.summarize_events([1.0, -2.0, 3.0], [0.5, -1.0, 2.0], cost=0.471)
        for k in ("n", "abs_mean", "exc_mean", "exc_med", "exc_ci", "t",
                  "net", "win", "beat", "cost"):
            self.assertIn(k, s)
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["net"], round(0.5 - 0.471, 2))

    def test_summarize_empty(self):
        self.assertEqual(bl.summarize_events([], [], 0.4), {"n": 0})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_backtest_lib -v`
Expected: `ModuleNotFoundError: No module named 'backtest_lib'`

- [ ] **Step 3: 實作 `backtest_lib.py`**

```python
#!/usr/bin/env python3
"""backtest_lib — 回測共用工具：成本模型、統計顯著性、episode 去重。

所有回測腳本 (second_wave / broker_radar / concept / turnaround / lending)
共用此模組，統一：
  - 成本假設：手續費 0.1425%×2×折扣 + 證交稅 0.3% + 滑價
  - 顯著性：percentile bootstrap CI、t-stat、moving-block bootstrap（重疊序列用）
  - episode 去重：cooldown 法（觸發後 N 根 K 棒內不再進場）
"""
import statistics

import numpy as np

FEE_PCT = 0.1425   # 券商手續費 % (單邊, 未折扣)
TAX_PCT = 0.30     # 證交稅 % (賣出)


def cost_roundtrip_pct(discount: float = 0.6, slippage_bp: float = 0.0) -> float:
    """買+賣一趟總成本 (%)。預設 6 折手續費、零滑價 → 0.471%。"""
    return FEE_PCT * discount * 2 + TAX_PCT + slippage_bp * 2 / 100.0


def t_stat(xs: list) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    sd = statistics.stdev(xs)
    return statistics.mean(xs) / (sd / n ** 0.5) if sd > 0 else 0.0


def bootstrap_ci(xs, n_boot: int = 5000, alpha: float = 0.05, seed: int = 7):
    """均值的 percentile bootstrap 信賴區間。回 (lo, hi)。"""
    if not xs:
        return (0.0, 0.0)
    a = np.asarray(xs, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    means = a[idx].mean(axis=1)
    return (float(np.percentile(means, alpha / 2 * 100)),
            float(np.percentile(means, (1 - alpha / 2) * 100)))


def block_bootstrap_ci(xs, block: int, n_boot: int = 5000,
                       alpha: float = 0.05, seed: int = 7):
    """Moving-block bootstrap — 給重疊期間序列 (自相關) 的均值 CI。"""
    n = len(xs)
    if n == 0:
        return (0.0, 0.0)
    block = max(1, min(block, n))
    a = np.asarray(xs, dtype=np.float64)
    rng = np.random.default_rng(seed)
    nblk = -(-n // block)  # ceil(n/block)
    starts = rng.integers(0, n - block + 1, size=(n_boot, nblk))
    means = np.empty(n_boot)
    for b in range(n_boot):
        seq = np.concatenate([a[s:s + block] for s in starts[b]])[:n]
        means[b] = seq.mean()
    return (float(np.percentile(means, alpha / 2 * 100)),
            float(np.percentile(means, (1 - alpha / 2) * 100)))


def dedup_cooldown(fires: list, cooldown: int) -> list:
    """fires = 同一檔股票已排序的觸發索引。觸發後 cooldown 根內不再進場。"""
    out, last = [], None
    for i in fires:
        if last is None or i - last > cooldown:
            out.append(i)
            last = i
    return out


def summarize_events(abs_rets, exc_rets, cost, edge_samples=None) -> dict:
    """事件研究摘要。edge_samples = 每事件 (超額 − 同日隨機基準)，可選。"""
    n = len(exc_rets)
    if n == 0:
        return {"n": 0}
    lo, hi = bootstrap_ci(exc_rets)
    out = {
        "n": n,
        "abs_mean": round(statistics.mean(abs_rets), 2),
        "exc_mean": round(statistics.mean(exc_rets), 2),
        "exc_med": round(statistics.median(exc_rets), 2),
        "exc_ci": [round(lo, 2), round(hi, 2)],
        "t": round(t_stat(exc_rets), 2),
        "net": round(statistics.mean(exc_rets) - cost, 2),
        "win": round(sum(1 for x in abs_rets if x > 0) / n * 100, 0),
        "beat": round(sum(1 for x in exc_rets if x > 0) / n * 100, 0),
        "cost": cost,
    }
    if edge_samples:
        elo, ehi = bootstrap_ci(edge_samples)
        out["edge_mean"] = round(statistics.mean(edge_samples) - cost, 2)
        out["edge_ci"] = [round(elo - cost, 2), round(ehi - cost, 2)]
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `python3 -m unittest tests.test_backtest_lib -v`
Expected: 全部 PASS（9 tests）

- [ ] **Step 5: README 增「回測共用工具」小節（在「資料源文件」前）+ commit**

README 增加：backtest_lib 的用途、成本模型公式（0.1425%×2×折扣+0.3%+滑價，預設 0.471%）、「所有回測統一報 bootstrap 95% CI 與中位數」。

```bash
git add backtest_lib.py tests/test_backtest_lib.py README.md
git commit -m "回測: 新增 backtest_lib (成本模型/bootstrap CI/episode 去重)"
```

---

### Task 2: v2 價格快取 — 開盤價 + 還原價 + 除權息日

**Files:**
- Create: `backtest_prices.py`
- Create（產出物）: `bt_cache/backtest_prices_v2.json`（gitignore）
- Modify: `.gitignore`（加 `bt_cache/`）

**Interfaces:**
- Produces: `build_cache_v2(start="2025-01-01", workers=4) -> dict`（抓全市場，寫檔並回傳）
- Produces: `load_panel(start="2025-01-01") -> PricePanel`（無快取或 start 不符則自動 build）
- Produces: `class PricePanel`:
  - `.stocks: dict[code, {"code","name","rows"}]`，row = `{"date":"YYYYMMDD","open","close","volume","aopen","aclose"}`（open/close 未還原、aopen/aclose 還原；缺還原資料時為 0.0）
  - `.ex_dates: dict[code, set[str]]`（除權息交易日 YYYYMMDD）
  - `.tx_dates: list[str]`、`.taiex: dict[date, {"open","close"}]`
  - `.fwd(code, date, h, entry="next_open") -> tuple[float, float] | None`（(個股報酬%, TAIEX 報酬%)；entry=`next_open`：隔日還原開盤進、第 h 日還原收盤出；entry=`signal_close`：訊號日還原收盤進）
  - `.matched_baseline(date, h, k=100, entry="next_open", seed=7) -> float | None`（**同一交易日**隨機 k 檔的平均前向超額）
- Consumes: `tw_second_wave.load_universe("all")`（現有函數）、`backtest_lib`（無）

- [ ] **Step 1: 寫實作**

```python
#!/usr/bin/env python3
"""backtest_prices — v2 回測價格面板。

v1 (concept_momentum/cache/backtest_prices_all.json) 只有 close/volume，
無法做「隔日開盤進場」也無法算還原報酬。v2 每檔存：
  open/close   — TaiwanStockPrice（未還原；訊號偵測用，與正式篩選器同口徑）
  aopen/aclose — TaiwanStockPriceAdj（還原；報酬衡量用）
  ex_dates     — TaiwanStockDividend 除權息交易日（訊號除污用）
TAIEX 只有 open/close（指數無還原問題）。

用法：
  python3 backtest_prices.py --start 2025-01-01          # build/refresh
  python3 backtest_prices.py --start 2025-01-01 --force  # 強制重抓
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tw_second_wave import load_universe  # noqa: E402

BT_CACHE = os.path.join(HERE, "bt_cache")
os.makedirs(BT_CACHE, exist_ok=True)
PANEL_PATH = os.path.join(BT_CACHE, "backtest_prices_v2.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    import subprocess
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    return ""


def _fm(dataset: str, data_id: str, start: str, token: str) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": dataset, "data_id": data_id,
                                "start_date": start, "token": token})
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{FINMIND}?{q}", timeout=30) as r:
                return json.loads(r.read().decode()).get("data", [])
        except Exception:
            time.sleep(2)
    return []


def _fetch_one(code: str, name: str, start: str, token: str):
    raw = _fm("TaiwanStockPrice", code, start, token)
    adj = _fm("TaiwanStockPriceAdj", code, start, token)
    div = _fm("TaiwanStockDividend", code, "2024-01-01", token)
    adj_by = {r["date"]: r for r in adj}
    rows = []
    for r in raw:
        c = r.get("close")
        if not c or float(c) <= 0:
            continue
        a = adj_by.get(r["date"], {})
        rows.append({
            "date": r["date"].replace("-", ""),
            "open": float(r.get("open") or 0),
            "close": float(c),
            "volume": float(r.get("Trading_Volume") or 0),
            "aopen": float(a.get("open") or 0),
            "aclose": float(a.get("close") or 0),
        })
    rows.sort(key=lambda x: x["date"])
    ex = set()
    for d in div:
        for k in ("CashExDividendTradingDate", "StockExDividendTradingDate"):
            v = (d.get(k) or "").strip()
            if v:
                ex.add(v.replace("-", ""))
    return rows, sorted(ex)


def build_cache_v2(start: str = "2025-01-01", workers: int = 4, force: bool = False) -> dict:
    if not force and os.path.exists(PANEL_PATH):
        with open(PANEL_PATH) as f:
            c = json.load(f)
        if c.get("start") == start and c.get("schema") == 2:
            print(f"[cache] v2 面板 {len(c['stocks'])} 檔（--force 可重抓）", file=sys.stderr)
            return c
    token = _token()
    uni = load_universe("all")
    print(f"[fetch] v2 面板：{len(uni)} 檔 × 3 datasets（約 30-60 分鐘）…", file=sys.stderr)
    stocks, ex_dates = {}, {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch_one, code, name, start, token): (code, name)
                for code, name in uni}
        for fut in as_completed(futs):
            code, name = futs[fut]
            done += 1
            try:
                rows, ex = fut.result()
            except Exception as e:
                print(f"  [ERR] {code}: {e}", file=sys.stderr)
                continue
            if len(rows) >= 60:
                stocks[code] = {"code": code, "name": name, "rows": rows}
                ex_dates[code] = ex
            if done % 100 == 0:
                print(f"  {done}/{len(uni)} (有效 {len(stocks)})", file=sys.stderr)
    tx = _fm("TaiwanStockPrice", "TAIEX", start, token)
    taiex = [{"date": r["date"].replace("-", ""),
              "open": float(r.get("open") or r.get("close") or 0),
              "close": float(r.get("close") or 0)}
             for r in tx if r.get("close")]
    c = {"schema": 2, "start": start, "stocks": stocks,
         "ex_dates": ex_dates, "taiex": taiex}
    with open(PANEL_PATH, "w") as f:
        json.dump(c, f)
    print(f"[fetch] 完成 {len(stocks)} 檔 → {PANEL_PATH}", file=sys.stderr)
    return c


class PricePanel:
    def __init__(self, cache: dict):
        self.stocks = cache["stocks"]
        self.ex_dates = {k: set(v) for k, v in cache.get("ex_dates", {}).items()}
        self.taiex = {r["date"]: r for r in cache["taiex"]}
        self.tx_dates = sorted(self.taiex)
        self.tx_idx = {d: i for i, d in enumerate(self.tx_dates)}
        self._by_code = {}
        self._codes_on = {}
        for code, s in self.stocks.items():
            didx = {r["date"]: i for i, r in enumerate(s["rows"])}
            self._by_code[code] = (s["rows"], didx)
            for d, i in didx.items():
                self._codes_on.setdefault(d, []).append((code, i))

    def fwd(self, code, date, h, entry="next_open"):
        rows, didx = self._by_code.get(code, (None, None))
        if rows is None or date not in didx or date not in self.tx_idx:
            return None
        i, ti = didx[date], self.tx_idx[date]
        if i + h >= len(rows) or ti + h >= len(self.tx_dates):
            return None
        if entry == "next_open":
            e = rows[i + 1].get("aopen") or 0
            tx_e = self.taiex[self.tx_dates[ti + 1]]
            tx0 = tx_e.get("open") or tx_e["close"]
        else:  # signal_close
            e = rows[i].get("aclose") or 0
            tx0 = self.taiex[date]["close"]
        x = rows[i + h].get("aclose") or 0
        tx1 = self.taiex[self.tx_dates[ti + h]]["close"]
        if e <= 0 or x <= 0 or tx0 <= 0 or tx1 <= 0:
            return None
        return ((x / e - 1) * 100, (tx1 / tx0 - 1) * 100)

    def matched_baseline(self, date, h, k=100, entry="next_open", seed=7):
        pool = self._codes_on.get(date, [])
        if not pool:
            return None
        rng = random.Random(f"{seed}:{date}:{h}:{entry}")
        vals = []
        for code, _ in rng.sample(pool, min(k, len(pool))):
            r = self.fwd(code, date, h, entry)
            if r is not None:
                vals.append(r[0] - r[1])
        return statistics.mean(vals) if vals else None

    def has_ex_dividend(self, code, d_from, d_to) -> bool:
        """[d_from, d_to] (YYYYMMDD, 含) 內有無除權息交易日。"""
        return any(d_from <= d <= d_to for d in self.ex_dates.get(code, ()))


def load_panel(start: str = "2025-01-01") -> PricePanel:
    return PricePanel(build_cache_v2(start))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    build_cache_v2(args.start, workers=args.workers, force=args.force)
```

- [ ] **Step 2: 建快取並抽查資料品質**

Run: `cd ~/project/tw_stock_tools && FINMIND_TOKEN=$(crontab -l | grep -o 'FINMIND_TOKEN=[^ ]*' | head -1 | cut -d= -f2) python3 backtest_prices.py --start 2025-01-01`
Expected: 約 30-60 分鐘後 `[fetch] 完成 ~1900+ 檔`。

Run 抽查（2330 有 aopen/aclose、除息日在 ex_dates；6/2026 台積電除息可對照）:
```bash
python3 - <<'EOF'
import json
c = json.load(open('bt_cache/backtest_prices_v2.json'))
s = c['stocks']['2330']; r = s['rows'][-1]
assert r['aopen'] > 0 and r['aclose'] > 0 and r['open'] > 0, r
assert c['ex_dates'].get('2330'), '2330 應有除權息日'
assert c['taiex'][-1]['open'] > 0
print('OK', len(c['stocks']), '檔;', '2330 ex_dates:', c['ex_dates']['2330'][-3:])
EOF
```
Expected: `OK ...`。若 `aopen` 全 0 → 檢查 `TaiwanStockPriceAdj` 欄位名（實測 2026-07 回傳 `open/max/min/close`）。

- [ ] **Step 3: gitignore + README「檔案位置總覽」加 `bt_cache/` + commit**

```bash
echo 'bt_cache/' >> .gitignore
git add backtest_prices.py .gitignore README.md
git commit -m "回測: v2 價格面板 (開盤+還原價+除權息日, PricePanel)"
```

---

### Task 3: 第二波回測 v2 — 隔日開盤進場、除權息 guard、CI、分年

**Files:**
- Modify: `tw_second_wave.py`（頂部加 `FILTER_DEFAULTS`，argparse 讀它）
- Modify: `tw_second_wave_backtest.py`（大改：面板/進場/統計）

**Interfaces:**
- Consumes: `backtest_prices.load_panel`, `PricePanel.fwd/matched_baseline/has_ex_dividend`, `backtest_lib.summarize_events/cost_roundtrip_pct/dedup_cooldown`
- Produces: `tw_second_wave.FILTER_DEFAULTS: dict`（11 個偵測參數的單一來源）
- Produces: 回測 JSON `result.horizons.{h}` 新增鍵 `exc_ci, t, edge_mean, edge_ci, n_skipped_div, per_year`；既有鍵全保留。新增頂層 `result.entry`（"next_open"｜"signal_close"）

- [ ] **Step 1: `tw_second_wave.py` 抽出參數單一來源**

在 `tw_second_wave.py` 的 `CACHE_DIR` 定義後加：

```python
# 偵測參數單一來源 — argparse 與回測共用（勿在他處手抄預設值）
FILTER_DEFAULTS = dict(
    rally_min_gain=0.30, peak_lookback=60, drop_min=0.15, drop_max=0.25,
    min_drop_days=5, max_drop_days=15, min_recovery_days=1,
    max_recovery_days=10, recovery_min_gain=0.05, recovery_vol_ratio=0.7,
    max_today_vs_peak=0.98,
)
```

`main()` 內 11 個 `p.add_argument(..., default=0.30, ...)` 改成 `default=FILTER_DEFAULTS["rally_min_gain"]` 等（逐一對應，不改任何數值）。

- [ ] **Step 2: 驗證 CLI 行為不變**

Run: `python3 tw_second_wave.py --universe 2313 --quiet | head -5`
Expected: 與改前相同輸出格式（有無候選皆可，不噴錯即可）。

- [ ] **Step 3: 改寫 `tw_second_wave_backtest.py` 核心**

保留 shebang/docstring 架構（docstring 更新：v2 快取、next_open 進場、除權息 guard、CI）。替換內容重點——完整檔案結構如下：

```python
#!/usr/bin/env python3
"""強勢股第二波 回測 v2 — 事件研究。

v2 相對 v1 的差異：
  - 進場：預設『訊號隔日還原開盤價』(--entry next_open)。訊號 07:40 盤前產生，
    隔日開盤是最早可實現的成交價；v1 的訊號日收盤進場把隔夜跳空算進去（不可實現）。
  - 報酬：還原價 (aopen/aclose)，跨除息的持有期不再低估。
  - 訊號除污：偵測窗 (peak→signal) 內有除權息交易日的 episode 剔除
    （未還原收盤的除權缺口會偽造 F3 急跌）— 剔除數記在 n_skipped_div。
  - 統計：bootstrap 95% CI + t-stat + 中位數 + 分年 (2025/2026)。
  - 基準：與事件同日期的隨機股票日 (date-matched)。
偵測邏輯不變：import 正式 detect_second_wave point-in-time 跑。
"""
import argparse
import json
import os
import sys
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                  # noqa: E402
from backtest_prices import load_panel                     # noqa: E402
from tw_second_wave import detect_second_wave, FILTER_DEFAULTS  # noqa: E402

DEFAULT_ARGS = Namespace(**FILTER_DEFAULTS)
MIN_HISTORY = 135


def run(horizons, cost, entry="next_open", dedup_days=None, start="2025-01-01",
        baseline_k=100):
    panel = load_panel(start)
    max_h = max(horizons)
    cooldown = dedup_days if dedup_days is not None else max_h
    events = []          # (code, date, i)
    n_signal_days = 0
    n_skipped_div = 0

    for code, s in panel.stocks.items():
        rows = s["rows"]
        if len(rows) < MIN_HISTORY + max_h:
            continue
        fires = []
        for i in range(MIN_HISTORY, len(rows) - max_h):
            res = detect_second_wave(rows[:i + 1], DEFAULT_ARGS)
            if res is None:
                continue
            n_signal_days += 1
            # 除權息 guard：偵測窗 (peak_date, signal_date] 有除權息 → 假急跌
            if panel.has_ex_dividend(code, res["peak_date"], rows[i]["date"]):
                n_skipped_div += 1
                continue
            fires.append(i)
        for i in bl.dedup_cooldown(fires, cooldown):
            events.append((code, rows[i]["date"], i))

    summary = {"n_signal_days": n_signal_days, "n_episodes": len(events),
               "n_skipped_div": n_skipped_div, "entry": entry, "cost": cost,
               "start": panel.tx_dates[0], "end": panel.tx_dates[-1],
               "universe": len(panel.stocks), "universe_label": "全市場",
               "horizons": {}}
    print(f"\n{'='*60}\n第二波 回測 v2  entry={entry}  cost={cost}%"
          f"\n universe {len(panel.stocks)} 檔・{panel.tx_dates[0]}~{panel.tx_dates[-1]}"
          f"\n 訊號 {n_signal_days} 股票日 → 除權息剔除 {n_skipped_div} → "
          f"episodes {len(events)}\n{'='*60}")

    for h in horizons:
        absr, excr, edges, dates = [], [], [], []
        by_year = {}
        for code, date, _i in events:
            r = panel.fwd(code, date, h, entry)
            if r is None:
                continue
            sr, tr = r
            b = panel.matched_baseline(date, h, k=baseline_k, entry=entry)
            absr.append(sr); excr.append(sr - tr); dates.append(date)
            if b is not None:
                edges.append(sr - tr - b)
            by_year.setdefault(date[:4], []).append(sr - tr)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        s["per_year"] = {y: {"n": len(v),
                             "exc_mean": round(sum(v) / len(v), 2),
                             "exc_ci": [round(x, 2) for x in bl.bootstrap_ci(v)]}
                         for y, v in sorted(by_year.items())}
        # 權益曲線（沿用 v1 呈現：非複利累加淨超額）
        order = sorted(range(len(dates)), key=lambda k: dates[k])
        eq, cum = [], 0.0
        for k in order:
            cum += excr[k] - cost
            eq.append({"date": dates[k], "cum": round(cum, 2)})
        s["equity"] = eq
        summary["horizons"][h] = s
        if s["n"]:
            print(f"\n【H={h}d】n={s['n']}  絕對 {s['abs_mean']:+.2f}% (勝率 {s['win']:.0f}%)")
            print(f"  超額均 {s['exc_mean']:+.2f}%  中位 {s['exc_med']:+.2f}%  "
                  f"95%CI [{s['exc_ci'][0]:+.2f}, {s['exc_ci'][1]:+.2f}]  t={s['t']:.2f}")
            print(f"  扣成本淨超額 {s['net']:+.2f}%  "
                  f"⭐edge {s.get('edge_mean', 0):+.2f}% CI {s.get('edge_ci')}")
            for y, v in s["per_year"].items():
                print(f"    {y}: n={v['n']} 超額 {v['exc_mean']:+.2f}% CI {v['exc_ci']}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--entry", default="next_open",
                    choices=["next_open", "signal_close"])
    ap.add_argument("--slippage-bp", type=float, default=0.0)
    ap.add_argument("--dedup-days", type=int, default=None,
                    help="episode cooldown 交易日數 (預設 = max horizon)")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    cost = (bl.cost_roundtrip_pct(slippage_bp=args.slippage_bp)
            if args.cost == bl.cost_roundtrip_pct() else args.cost)
    s = run(args.horizon, cost, entry=args.entry, dedup_days=args.dedup_days,
            start=args.start)
    if args.json_out:
        from datetime import datetime
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "params": {"horizons": args.horizon, "cost": cost,
                                  "entry": args.entry, "universe": "all"},
                       "result": s}, f, ensure_ascii=False)
        print(f"\n[json] 寫入 {args.json_out}", file=sys.stderr)
```

注意：v1 的 `--universe concepts`（192 檔小樣本）與 `--no-dedup` 模式移除——v2 一律全市場面板 + cooldown 去重（README 說明此變更）。舊 JSON 鍵 `abs_mean/exc_mean/exc_med/net/win/beat/equity` 全部保留；`baseline/edge` 改為 `edge_mean/edge_ci`（dashboard 顯示處同步改，見 Step 5）。

- [ ] **Step 4: 跑回測 + 對照 v1 結果 sanity check**

Run: `FINMIND_TOKEN=... python3 tw_second_wave_backtest.py --json-out concept_momentum/cache/second_wave_backtest.json`
Expected 檢查點：
- `n_skipped_div > 0`（2025-2026 涵蓋兩個除權息季，若為 0 → ex_dates 沒載入，回查）
- episodes 數量級與 v1 (688) 相近（±40%；cooldown 法會比 prev_fire 法略少）
- `entry=next_open` 的 `exc_mean` 預期**低於** v1 的收盤進場（跳空吃掉一部分）——這是修正，不是退步
- 每個 h 印出 CI；`exc_ci` 若跨 0 → README 結論寫「該 horizon 無統計顯著 edge」

- [ ] **Step 5: dashboard 顯示新欄位**

`concept_momentum/app.py` 搜 `second-wave-backtest` route/template：摘要卡加「中位數」「95% CI」「t」「除權息剔除數」，edge 顯示改用 `edge_mean` + `edge_ci`（找不到鍵時 fallback 舊鍵 `edge`，避免舊 JSON 壞頁面）。

- [ ] **Step 6: README 第二波回測章節改寫 + commit**

README 說明：進場口徑（next_open）、成本 0.471%、除權息 guard、CI 判讀（CI 含 0 = 不顯著）、v1→v2 數字不可直接比較的原因。

```bash
git add tw_second_wave.py tw_second_wave_backtest.py concept_momentum/app.py README.md
git commit -m "second-wave 回測 v2: 隔日開盤進場+還原報酬+除權息guard+bootstrap CI"
```

---

### Task 4: 第二波 live 篩選器 — 除權息 guard

**Files:**
- Modify: `finmind_client.py`（加 `fetch_dividend_ex_dates`）
- Modify: `tw_second_wave.py`（`process_one` 加 guard）
- Test: `tests/test_finmind_client.py`（加一個 case）

**Interfaces:**
- Produces: `finmind_client.fetch_dividend_ex_dates(code, start_date, token) -> list[str]`（回 `YYYY-MM-DD` 除權息交易日，Cash+Stock 合併去重排序）

- [ ] **Step 1: 加測試（真 API，skipUnless TOKEN）**

在 `tests/test_finmind_client.py` 的 TestFinmindClient 加：

```python
    def test_dividend_ex_dates_2330(self):
        """2330 每年 3/6/9/12 月除息，2026 上半年至少一次。"""
        dates = finmind_client.fetch_dividend_ex_dates("2330", "2026-01-01", TOKEN)
        self.assertTrue(any(d.startswith("2026-") for d in dates), dates)
```

Run: `python3 -m unittest tests.test_finmind_client -v` → 新 case FAIL（AttributeError）。

- [ ] **Step 2: `finmind_client.py` 實作**

仿照該檔既有 fetch 函數風格，底層走既有的 `_call(dataset, params, token)`（`finmind_client.py:20`）：

```python
def fetch_dividend_ex_dates(stock_id: str, start_date: str, token: str) -> list[str]:
    """TaiwanStockDividend → 除權息「交易日」清單 (YYYY-MM-DD, 現金+股票合併去重)。"""
    data = _call("TaiwanStockDividend", {
        "data_id": stock_id,
        "start_date": start_date,
    }, token)
    out = set()
    for r in data:
        for k in ("CashExDividendTradingDate", "StockExDividendTradingDate"):
            v = (r.get(k) or "").strip()
            if v:
                out.add(v)
    return sorted(out)
```

- [ ] **Step 3: `tw_second_wave.py` `process_one` 加 guard**

```python
def process_one(code: str, name: str, args) -> dict | None:
    yh = fetch_yahoo_6mo(code)
    if not yh or not yh.get("rows"):
        return None
    sig = detect_second_wave(yh["rows"], args)
    if not sig:
        return None
    # 除權息 guard：peak→今日 之間有除權息交易日 → 急跌可能是除權缺口，剔除
    token = os.environ.get("FINMIND_TOKEN", "")
    if token:
        try:
            ex = _ex_dates_cached(code, token)      # 新 helper，見下
            if any(sig["peak_date"] <= d <= yh["rows"][-1]["date"] for d in ex):
                return None
        except Exception as e:
            print(f"[WARN] dividend guard {code}: {e}", file=sys.stderr)
    return {"code": code, "name": name, "market": yh.get("market", ""), **sig}
```

新 helper（放 `fetch_yahoo_6mo` 之後；快取 7 天避免每天 3000 次呼叫）：

```python
def _ex_dates_cached(code: str, token: str) -> list[str]:
    p = os.path.join(CACHE_DIR, f"div_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        with open(p) as f:
            return json.load(f)
    sys.path.insert(0, HERE)
    import finmind_client
    start = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")
    ex = finmind_client.fetch_dividend_ex_dates(code, start, token)
    with open(p, "w") as f:
        json.dump(ex, f)
    return ex
```

日期格式注意：live rows 的 date 是 `YYYY-MM-DD`（FinMind 原格式），`fetch_dividend_ex_dates` 也回 `YYYY-MM-DD` → 直接字串比較可行。

- [ ] **Step 4: 驗證**

Run: `python3 -m unittest tests.test_finmind_client -v` → PASS。
Run: `FINMIND_TOKEN=... python3 tw_second_wave.py --universe all --quiet | head -20` → 正常出報告；再跑一次應走 div cache（秒回）。7-9 月除權息季預期候選數比沒 guard 時少。

- [ ] **Step 5: README（第二波章節加「除權息 guard」說明 + 限制聲明更新）+ commit**

```bash
git add finmind_client.py tw_second_wave.py tests/test_finmind_client.py README.md
git commit -m "second-wave: 除權息 guard (急跌若含除權缺口則剔除)"
```

---

### Task 5: 主力雷達回測 — date-matched 基準 + CI

**Files:**
- Modify: `tw_broker_radar_backtest.py`

**Interfaces:**
- Consumes: `backtest_prices.load_panel`（取代 `PRICE_ALL` v1 快取 + 自建 baseline）、`backtest_lib.summarize_events`
- Produces: JSON `horizons.{h}` 增 `exc_ci, t, edge_mean, edge_ci`；保留舊鍵。`entry` 預設改 `next`

- [ ] **Step 1: 改寫 `run()`**

改動點（保留 `load_events()` 不動）：
1. 刪 `baseline_fwd()` 與 `PRICE_ALL`；改用 `panel = load_panel()`。
2. 事件價格不再另行 `fetch_closes`——直接用 panel（panel 涵蓋 2025-01 起；若事件日不在 panel（新股）→ skip 並計數）。
3. 每事件：`r = panel.fwd(code, date, h, entry_mode)`，`entry_mode`: `--entry next` → `"next_open"`（隔日**開盤**，比 v1 的隔日收盤更貼近「18:00 看到訊號、隔天開盤買」）；`--entry signal` → `"signal_close"`（保留對照）。
4. 每事件配 `panel.matched_baseline(date, h, entry=entry_mode)` → edge_samples。
5. 彙總改 `bl.summarize_events(absr, excr, cost=bl.cost_roundtrip_pct(), edge_samples=edges)`；加 `--cost` 參數。
6. 去重邏輯保留（同股 cooldown max_h）但改成先按 (code, date) 排序後用 `bl.dedup_cooldown` 於該股的 panel 索引上。
7. 印出樣本量警語：`if s["n"] < 30: print("  ⚠ 樣本 <30，CI 很寬，結論僅供參考")`。

- [ ] **Step 2: 跑 + sanity**

Run: `FINMIND_TOKEN=... python3 tw_broker_radar_backtest.py --entry next --json-out concept_momentum/cache/broker_radar_backtest.json`
Expected: n 與現況相近（~55 episodes，H=20 遞減）；每 h 有 CI；`edge_mean` 與 v1 `edge`（+3~8%）同數量級——若差一個數量級回查 baseline。

- [ ] **Step 3: dashboard `/broker-radar-backtest` 顯示 CI + 樣本量警語；README 主力雷達回測章節更新（含「事件由已部署訊號版本產生，改訊號參數後歷史事件不可比」的告示）+ commit**

```bash
git add tw_broker_radar_backtest.py concept_momentum/app.py README.md
git commit -m "broker-radar 回測: date-matched 基準 + bootstrap CI, entry 預設隔日開盤"
```

---

### Task 6: 族群熱力回測 — train/serve parity + 非重疊 L2

**Files:**
- Modify: `tw_concept_backtest.py`

**Interfaces:**
- Consumes: `concept_momentum.filter_liquid_stocks, build_concept_index`（既有）、`backtest_lib.block_bootstrap_ci, bootstrap_ci`
- Produces: JSON 每 h 增 `ic_ci`（block bootstrap）、`l2_ci`；`equity/max_dd/calmar/total` 改由**非重疊** rebalance 計算（`rebalance_h = max(rebalance, h)`）

- [ ] **Step 1: parity 修正（兩處）**

(a) `ret_20d_score` 改成與正式版同口徑（成交額加權指數報酬）：

```python
def ret_20d_score(theme_info: dict, stocks: dict, t: str) -> float:
    """與正式版 analyze_all 同口徑：成交額加權概念指數的 20d 報酬。"""
    trunc = []
    for c in theme_info.get("stocks", []):
        s = stocks.get(c)
        if not s:
            continue
        rows = _truncate_rows(s["rows"], t)
        if len(rows) >= 21:
            trunc.append({**s, "rows": rows})
    trunc = filter_liquid_stocks(trunc)          # 正式版同款流動性濾網
    if len(trunc) < 3:
        return 0.0
    idx = build_concept_index(trunc)             # 預設 turnover-weighted，同正式版
    vals = [p["value"] for p in idx]
    if len(vals) < 21 or vals[-21] <= 0:
        return 0.0
    return (vals[-1] / vals[-21] - 1) * 100
```

import 行改：`from concept_momentum import (compute_score_for_date, extract_leaders, _truncate_rows, compute_breadth, compute_volume_ratio, filter_liquid_stocks, build_concept_index)`。
(b) L2 選股加流動性濾網——`run_backtest` 內 leaders 段：

```python
            for tk, info, sc in scored[:topk]:
                codes = info.get("stocks", [])
                cstocks = [{**stocks[c], "rows": _truncate_rows(stocks[c]["rows"], t)}
                           for c in codes if c in stocks
                           and len(_truncate_rows(stocks[c]["rows"], t)) >= 20]
                cstocks = filter_liquid_stocks(cstocks)     # ← 新增：與正式版對齊
                for ld in extract_leaders(cstocks, top_n=5):
```

同時 `_theme_breadth_vol` 也加 `trunc = filter_liquid_stocks(trunc)`（正式版 `analyze_concept` 的廣度/量能算在濾後成員上）。

- [ ] **Step 2: 非重疊 L2 + IC block bootstrap**

`run_backtest` 內：
1. IC 迴圈維持現狀（IC 允許重疊觀察），但彙總時加 `ic_ci = bl.block_bootstrap_ci(R["ic"], block=-(-h // rebalance))`。
2. L2 改成**每 h 用自己的非重疊 rebalance 網格**：

```python
    # L2 用非重疊網格（否則 5 天 rebalance × 20 天持有 → 報酬重複計 4 次，
    # total/max_dd/calmar 全部灌水）
    idxs_l2 = {h: list(range(20, len(dates) - h, max(rebalance, h))) for h in horizons}
```

L2 的計算搬到獨立迴圈（對每個 h 走 `idxs_l2[h]`，score/leaders 邏輯同前），`l2_ret` 序列因此不重疊 → `total/max_dd/vol/calmar` 直接可信；加 `l2_ci = bl.bootstrap_ci(R["l2_ret"])`。
3. 印出時標注：`print(f"  (L2 非重疊 rebalance={max(rebalance,h)}d, n={len(R['l2_ret'])})")`。

- [ ] **Step 3: 跑三變體 + 對照**

Run: `FINMIND_TOKEN=... python3 tw_concept_backtest.py --json-out concept_momentum/cache/concept_backtest.json`（會自動跑 strategy/benchmark/filter）
Expected: IC 幾乎不變（~0.13-0.19）；**L2 total 大幅下降是預期**（H=20 從 334% 掉到 ~1/4 量級），README 記錄原因（舊值重疊灌水）。filter 變體仍應 ≥ benchmark（若不再成立 → C 變體採用決策需要重新評估，把兩者數字都寫進 README 讓使用者決定）。

- [ ] **Step 4: dashboard `/concept-backtest` 加 `ic_ci/l2_ci` 顯示 + README 族群熱力回測章節改寫（新舊不可比對照表）+ commit**

```bash
git add tw_concept_backtest.py concept_momentum/app.py README.md
git commit -m "concept 回測: 流動性/ret20d parity + L2 非重疊 + block-bootstrap IC CI"
```

---

### Task 7: Layer 2 盤前/盤後 anchor 對齊

**Files:**
- Modify: `tw_limitup_signal.py`
- Modify: `tw_daily_screen.py`
- Test: `tests/test_limitup_anchor.py`

**Interfaces:**
- Produces: `signal_a_relay(px, anchor=None)`, `signal_d_volume(px, anchor=None)`——`anchor` = 「被解釋/被預測那一天」在 px 的索引；`None` → `len(px)-1`（盤後 standalone，行為與現在完全相同）；盤前模式傳 `len(px)`。
- Produces: CLI `--mode {auto,premarket,postclose}`（預設 auto：有 `--codes/--codes-file` → premarket，否則 postclose）
- Produces: `score_stock(..., mode="postclose")`；json-out 增 `"mode"` 欄位

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_limitup_anchor.py
"""A/D 訊號的 anchor 對齊：盤前模式必須看得到最新一根 K 棒。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tw_limitup_signal import signal_a_relay, signal_d_volume


def _px(closes, volumes=None, opens=None):
    volumes = volumes or [1000] * len(closes)
    opens = opens or closes
    return [{"date": f"2026-06-{i+1:02d}", "open": o, "close": c,
             "high": c, "low": c, "volume": v}
            for i, (c, v, o) in enumerate(zip(closes, volumes, opens))]


class TestAnchorA(unittest.TestCase):
    def test_premarket_sees_latest_bar_jump(self):
        # 最新一根 +9.9%，之前全平 → 盤前(anchor=len)應 ✅，盤後(預設)應 ❌
        closes = [100.0] * 10 + [109.9]
        px = _px(closes)
        ok_post, _ = signal_a_relay(px)                    # 舊行為：不含最新根
        ok_pre, _ = signal_a_relay(px, anchor=len(px))     # 盤前：含最新根
        self.assertFalse(ok_post)
        self.assertTrue(ok_pre)

    def test_postclose_unchanged(self):
        # 倒數第 2 根 +6% → 盤後模式維持 ✅ (與現有行為一致)
        closes = [100.0] * 9 + [106.0, 106.5]
        ok, _ = signal_a_relay(_px(closes))
        self.assertTrue(ok)


class TestAnchorD(unittest.TestCase):
    def test_premarket_uses_latest_volume(self):
        # 最新一根量 3x 均量 → 盤前 ✅；盤後看倒數第 2 根(量=均量的1.0x) 也 ✅
        vols = [1000] * 24 + [1000, 3000]
        closes = [100.0] * 26
        ok_pre, msg = signal_d_volume(_px(closes, vols), anchor=26)
        self.assertTrue(ok_pre, msg)
        # 最新根爆量但倒數第2根縮量 → 盤後 ❌、盤前 ✅
        vols2 = [1000] * 24 + [400, 3000]
        ok_post, _ = signal_d_volume(_px(closes, vols2))
        ok_pre2, _ = signal_d_volume(_px(closes, vols2), anchor=26)
        self.assertFalse(ok_post)
        self.assertTrue(ok_pre2)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_limitup_anchor -v` → FAIL（signal_a_relay 不收 anchor 參數）。

- [ ] **Step 2: 重構 A/D 為 anchor 制**

```python
def signal_a_relay(px: list[dict], anchor: int | None = None) -> tuple[bool, str]:
    """A 漲停接力: 被預測日 (anchor) 之前 3 根 K 棒任一日漲幅 ≥ +5%，
    且 anchor 前一日盤中未崩 ≤ -4%。
    anchor=None → len(px)-1 (盤後 standalone：px[-1] 是漲停日本身，行為同舊版)。
    盤前模式傳 len(px)：「今天」還沒發生，最新 K 棒 (昨日) 是訊號來源之一。"""
    if anchor is None:
        anchor = len(px) - 1
    if anchor < 4:
        return False, "(資料不足)"
    gains = []
    for j in (anchor - 1, anchor - 2, anchor - 3):
        if j - 1 < 0:
            break
        c, prev = px[j]["close"], px[j - 1]["close"]
        if prev > 0 and c > 0:
            gains.append((c - prev) / prev * 100)
    if not gains:
        return False, "(無前日)"
    max_gain = max(gains)
    ref = px[anchor - 1]
    ref_open = ref.get("open") or ref["close"]
    if ref_open > 0:
        intraday = (ref["close"] - ref_open) / ref_open * 100
        if intraday <= -4.0:
            return False, f"前日盤中崩 {intraday:.1f}%"
    if max_gain >= 9.5:
        return True, f"近 3 日內漲停 +{max_gain:.1f}%"
    if max_gain >= 5.0:
        return True, f"近 3 日強勢 +{max_gain:.1f}%"
    return False, f"近 3 日最大 {max_gain:+.1f}%"


def signal_d_volume(px: list[dict], anchor: int | None = None) -> tuple[bool, str]:
    """D 量能蓄勢: anchor 前一日量 / 20d 均量 ≥ 1.0 或 / 60d 均量 ≥ 1.5。"""
    if anchor is None:
        anchor = len(px) - 1
    if anchor < 22:
        return False, "(資料不足)"
    prev_vol = px[anchor - 1].get("volume") or 0
    win20 = px[anchor - 21:anchor - 1]
    avg20 = sum((r.get("volume") or 0) for r in win20) / 20
    if avg20 <= 0:
        return False, "(無均量)"
    ratio20 = prev_vol / avg20
    ratio60 = ratio20
    if anchor >= 62:
        win60 = px[anchor - 61:anchor - 1]
        avg60 = sum((r.get("volume") or 0) for r in win60) / 60
        if avg60 > 0:
            ratio60 = prev_vol / avg60
    if ratio20 >= 1.0:
        return True, f"前日量 {ratio20:.1f}x 20d / {ratio60:.1f}x 60d"
    if ratio60 >= 1.5:
        return True, f"前日量 {ratio60:.1f}x 60d ({ratio20:.1f}x 20d)"
    return False, f"前日量 {ratio20:.1f}x 20d / {ratio60:.1f}x 60d"
```

（舊版 `signal_a_relay` 對 `i-1` 的邊界式 `abs(i - 1) <= len(px)` 有 off-by-one 潛在越界，anchor 制順帶修掉。）

- [ ] **Step 3: `score_stock` + `main` 接 mode**

`score_stock(code, name, target_date, token, quiet=False, mode="postclose")`：

```python
    anchor = len(px) if mode == "premarket" else None
    a_ok, a_msg = signal_a_relay(px, anchor=anchor)
    ...
    d_ok, d_msg = signal_d_volume(px, anchor=anchor)
```

B/C 不變（本來就用最新可得資料）。`main()`：加 `--mode` 參數（`auto/premarket/postclose`，default auto）；`mode = "premarket" if (args.codes or args.codes_file) else "postclose"`（auto 時）；傳進 `score_stock`；`--json-out` 的 dict 加 `"mode": mode`。`tw_daily_screen.py` 的 cmd2 加 `"--mode", "premarket"`（顯式，不靠 auto）；順手把 `tw_daily_screen.py:3` docstring 的 `cron 19:00` 改 `cron 07:30`。

- [ ] **Step 4: 驗證**

Run: `python3 -m unittest tests.test_limitup_anchor -v` → PASS。
Run: `FINMIND_TOKEN=... python3 tw_limitup_signal.py --codes 2330,2317 --quiet | head -30` → 正常輸出（auto→premarket）。
Run: `FINMIND_TOKEN=... python3 tw_limitup_signal.py --date 2026-06-30 --limit 5 --quiet | head -30` → standalone 掃描不變（postclose）。

- [ ] **Step 5: C 訊號歷史限制的止血**

`fetch_histock_7d` 開頭加：

```python
    today = datetime.now().strftime("%Y-%m-%d")
    if target_date != today:
        # HiStock branch.aspx 無日期參數，只能拿「現在」的 7 日視窗；
        # 回看歷史日會拿到錯的籌碼 → 不給錯資料，回空
        return {"buyers": [], "sellers": []}
```

（cache 已存的歷史日檔案不管；此後 `--date` 回看時 C 一律 `(無籌碼)`＝不加分。）

- [ ] **Step 6: README（Layer 2 章節：mode 語意、A/D 視窗定義、C 的歷史限制、「2026-07 之後的 abcd_score 與之前不可直接比較」）+ commit**

```bash
git add tw_limitup_signal.py tw_daily_screen.py tests/test_limitup_anchor.py README.md
git commit -m "limitup: 盤前/盤後 anchor 對齊 (盤前 A/D 納入最新K棒) + C 歷史回看止血"
```

---

### Task 8: GM 快取財報季 TTL

**Files:**
- Modify: `tw_turnaround_screener.py`（`fetch_quarterly_margins`）

- [ ] **Step 1: 實作**

`fetch_quarterly_margins` 上方加：

```python
# 財報公告死線: 年報 3/31、Q1 5/15、Q2 8/14、Q3 11/14。
# 死線前後的窗口內快取縮短到 3 天，其餘 21 天（原 30 天會讓新季報最多晚 30 天生效）。
_EARNINGS_WINDOWS = [(325, 410), (505, 525), (805, 825), (1105, 1125)]  # (MMDD, MMDD)


def _margin_cache_ttl(now=None) -> int:
    now = now or datetime.now()
    md = now.month * 100 + now.day
    for lo, hi in _EARNINGS_WINDOWS:
        if lo <= md <= hi:
            return 3 * 86400
    return 21 * 86400
```

`fetch_quarterly_margins` 內 `if time.time() - mtime < 30 * 86400:` 改 `if time.time() - mtime < _margin_cache_ttl():`。

- [ ] **Step 2: 驗證 + commit**

Run: `python3 - <<'EOF'
import sys, datetime; sys.path.insert(0, '/home/kun/project/tw_stock_tools')
from tw_turnaround_screener import _margin_cache_ttl
assert _margin_cache_ttl(datetime.datetime(2026, 5, 10)) == 3 * 86400
assert _margin_cache_ttl(datetime.datetime(2026, 8, 20)) == 3 * 86400
assert _margin_cache_ttl(datetime.datetime(2026, 7, 6)) == 21 * 86400
print('OK')
EOF`
Expected: `OK`

```bash
git add tw_turnaround_screener.py README.md
git commit -m "turnaround: GM 快取財報季 TTL 3 天 (原 30 天會用到過期季報)"
```

（README Layer 1 章節加一行說明。）

---

### Task 9: 主力雷達改用正式選股口徑挑強勢族群

**Files:**
- Modify: `tw_broker_monitor.py`（`get_strong_concept_stocks`）

- [ ] **Step 1: 實作**

`get_strong_concept_stocks(min_score=70.0, top_themes=8)` 內，`strong_themes` 計算改：

```python
    # 正式選股 2026-06 起改 C 變體 (passes_gate + ret_20d)，sustainability_score
    # 已降為參考欄 — 這裡跟進：取通過門檻族群按 ret_20d 前 top_themes 名。
    gated = [r for r in results if r.get("passes_gate")]
    if gated:
        gated.sort(key=lambda r: r.get("ret_20d", 0), reverse=True)
        strong_themes = [r["theme_key"] for r in gated[:top_themes]]
    else:
        # 舊結果檔沒有 passes_gate 欄位 → fallback 原邏輯
        strong_themes = [r["theme_key"] for r in results
                         if r.get("sustainability_score", 0) >= min_score]
```

`main()` 加 `--concept-top-themes`（default 8）傳入。

- [ ] **Step 2: 驗證 + commit**

Run: `python3 -c "
import sys; sys.path.insert(0, '/home/kun/project/tw_stock_tools')
from tw_broker_monitor import get_strong_concept_stocks
codes = get_strong_concept_stocks()
print(len(codes), '檔', codes[:10])"`
Expected: 非空清單（今日 analysis json 存在時）。

```bash
git add tw_broker_monitor.py README.md
git commit -m "broker-monitor: 概念強勢股改 passes_gate+ret_20d (跟進 C 變體)"
```

---

### Task 10: 轉機接力 Layer 1（+A/B/D overlay）回測 — 旗艦補洞

**Files:**
- Modify: `tw_turnaround_screener.py`（頂部加 `TR_DEFAULTS`，argparse 讀它——同 Task 3 模式）
- Create: `tw_turnaround_backtest.py`
- 產出物: `bt_cache/fs_{code}.json`、`bt_cache/sbl_{code}.json`（gitignore 已涵蓋）

**Interfaces:**
- Consumes: `tw_turnaround_screener.margin_passes/volume_passes/ma60_passes/short_passes`（純函數，import 正式邏輯）、`tw_limitup_signal.signal_a_relay/signal_b_short_cover/signal_d_volume`（Task 7 後的 anchor 版）、`backtest_prices.load_panel`、`backtest_lib`
- Produces: `tw_turnaround_screener.TR_DEFAULTS = dict(gm_pp=1.5, gm_qoq=2, vol_ratio=1.3, sbl_decline=0.95, ma_accel_days=5, ma_curv_ratio=0.5)`
- Produces: JSON `concept_momentum/cache/turnaround_backtest.json`，結構 `{generated, params, result:{n_episodes, n_stocks_gm_pass, horizons:{h: summarize_events 輸出 + per_year}, layer2:{"ge2":{...}, "lt2":{...}}}}`

**財報 point-in-time 規則（核心，寫進 docstring）**：FinMind `TaiwanStockFinancialStatements` 的 `date` 是**季度期末日**，不是公告日。回測中季報的「可用日」用法定申報死線（保守——多數公司提早公告，故此規則**低估**可實現 edge，不會高估）：

| 季末 | 可用日 |
|------|--------|
| 3/31 | 當年 5/15 |
| 6/30 | 當年 8/14 |
| 9/30 | 當年 11/14 |
| 12/31 | 翌年 3/31 |

- [ ] **Step 1: `TR_DEFAULTS` 重構（同 Task 3 Step 1 模式），跑 `python3 tw_turnaround_screener.py --universe 2330 --quiet` 確認行為不變**

- [ ] **Step 2: 寫 `tw_turnaround_backtest.py`**

```python
#!/usr/bin/env python3
"""轉機接力 Layer 1 回測 — 事件研究 (point-in-time)。

Layer 1 四濾網 import 正式篩選器的純函數，逐日 as-of 重建：
  A 毛利率  : TaiwanStockFinancialStatements，季報可用日=法定死線 (見下表)
  B 量能    : v2 價格面板 rows[:i+1] (未還原 close/volume，與正式版 Yahoo 同口徑)
  D 季線    : 同上
  C 借券賣出: TaiwanDailyShortSaleBalances as-of 截斷
Layer 2 overlay：A/B/D 三訊號 (C 分點無公開歷史，誠實跳過) 以盤前 anchor 語意
在每個 Layer 1 事件日評分，比較 abd>=2 與 <2 兩組的前向表現 → 回答
「Layer 2 有沒有在 Layer 1 之上加值」。

進場：訊號日隔日還原開盤 (07:30 盤前推播 → 當日開盤可成交)。
成本/CI/基準：backtest_lib (同第二波 v2)。

季報可用日: 3/31→5/15, 6/30→8/14, 9/30→11/14, 12/31→翌年3/31 (保守)。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                            # noqa: E402
from backtest_prices import load_panel, BT_CACHE, _token, _fm        # noqa: E402
from tw_turnaround_screener import (TR_DEFAULTS, margin_passes,      # noqa: E402
                                    volume_passes, ma60_passes, short_passes)
from tw_limitup_signal import (signal_a_relay, signal_b_short_cover,  # noqa: E402
                               signal_d_volume)


def _avail(qend: str) -> str:
    """季末日 YYYY-MM-DD → 可用日 YYYYMMDD (法定申報死線)。"""
    y, m = int(qend[:4]), int(qend[5:7])
    return {3: f"{y}0515", 6: f"{y}0814", 9: f"{y}1114", 12: f"{y+1}0331"}[m]


def fetch_fs(code: str, token: str) -> list[dict]:
    """季毛利率 + 可用日。快取 30 天。回 [{date, avail, gross_margin}] 升冪。"""
    p = os.path.join(BT_CACHE, f"fs_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 30 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanStockFinancialStatements", code, "2023-07-01", token)
    byq = {}
    for r in data:
        if r.get("date") and r.get("type") in ("Revenue", "GrossProfit"):
            byq.setdefault(r["date"], {})[r["type"]] = r.get("value")
    out = []
    for d in sorted(byq):
        q = byq[d]
        rev, gp = q.get("Revenue"), q.get("GrossProfit")
        if rev and gp is not None and rev > 0:
            out.append({"date": d, "avail": _avail(d),
                        "gross_margin": gp / rev * 100})
    json.dump(out, open(p, "w"))
    return out


def fetch_sbl(code: str, token: str) -> list[dict]:
    """借券賣出+融券餘額全歷史。快取 7 天。回 short_passes 相容格式 (張)。"""
    p = os.path.join(BT_CACHE, f"sbl_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanDailyShortSaleBalances", code, "2024-10-01", token)
    out = []
    for r in data:
        d = r.get("date")
        if not d:
            continue
        sbl = (r.get("SBLShortSalesCurrentDayBalance") or 0) / 1000
        mgn = (r.get("MarginShortSalesCurrentDayBalance") or 0) / 1000
        out.append({"date": d.replace("-", ""), "balance": sbl,
                    "sbl": sbl, "margin": mgn})
    out.sort(key=lambda x: x["date"])
    json.dump(out, open(p, "w"))
    return out


def run(horizons, cost, start="2025-01-01", entry="next_open"):
    token = _token()
    panel = load_panel(start)
    p = argparse.Namespace(**TR_DEFAULTS)
    max_h = max(horizons)
    events = []            # (code, date, i, abd_score)
    n_gm_pass_stocks = 0

    codes = sorted(panel.stocks)
    for n_done, code in enumerate(codes):
        if (n_done + 1) % 200 == 0:
            print(f"  {n_done+1}/{len(codes)} events={len(events)}", file=sys.stderr)
        fs = fetch_fs(code, token)
        if not fs:
            continue
        avails = [q["avail"] for q in fs]
        # 快篩：任一時點的「最近 4 季」有沒有可能過 A — 全期間都不過就跳過
        ever = False
        for k in range(4, len(fs) + 1):
            ok, _ = margin_passes(fs[k - 4:k], p.gm_pp, p.gm_qoq)
            if ok:
                ever = True
                break
        if not ever:
            continue
        n_gm_pass_stocks += 1
        sbl = fetch_sbl(code, token)
        sbl_dates = [r["date"] for r in sbl]
        rows = panel.stocks[code]["rows"]
        fires, scores = [], {}
        import bisect
        for i in range(70, len(rows) - max_h):
            t = rows[i]["date"]
            navail = bisect.bisect_right(avails, t)
            pit = fs[:navail][-4:]
            ok_a, _ = margin_passes(pit, p.gm_pp, p.gm_qoq)
            if not ok_a:
                continue
            ok_b, _ = volume_passes(rows[:i + 1], p.vol_ratio)
            if not ok_b:
                continue
            ok_d, _ = ma60_passes(rows[:i + 1], accel_days=p.ma_accel_days,
                                  curvature_min_ratio=p.ma_curv_ratio)
            if not ok_d:
                continue
            nsbl = bisect.bisect_right(sbl_dates, t)
            ok_c, _ = short_passes(sbl[:nsbl], p.sbl_decline)
            if not ok_c:
                continue
            fires.append(i)
            # Layer 2 overlay: A/B/D 盤前語意 (anchor = 已收盤 K 棒數)
            a_ok, _ = signal_a_relay(rows[:i + 1], anchor=i + 1)
            b_ok, _ = signal_b_short_cover(sbl[:nsbl])
            d_ok, _ = signal_d_volume(rows[:i + 1], anchor=i + 1)
            scores[i] = int(a_ok) + int(b_ok) + int(d_ok)
        for i in bl.dedup_cooldown(fires, max_h):
            events.append((code, rows[i]["date"], i, scores[i]))

    print(f"\nGM 可能過關股數 {n_gm_pass_stocks} / {len(codes)}；"
          f"episodes {len(events)}", file=sys.stderr)
    result = {"n_episodes": len(events), "n_stocks_gm_pass": n_gm_pass_stocks,
              "entry": entry, "cost": cost, "horizons": {}, "layer2": {}}
    for h in horizons:
        absr, excr, edges = [], [], []
        grp = {"ge2": {"abs": [], "exc": []}, "lt2": {"abs": [], "exc": []}}
        by_year = {}
        for code, date, _i, sc in events:
            r = panel.fwd(code, date, h, entry)
            if r is None:
                continue
            sr, tr = r
            absr.append(sr); excr.append(sr - tr)
            by_year.setdefault(date[:4], []).append(sr - tr)
            b = panel.matched_baseline(date, h, entry=entry)
            if b is not None:
                edges.append(sr - tr - b)
            g = grp["ge2" if sc >= 2 else "lt2"]
            g["abs"].append(sr); g["exc"].append(sr - tr)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        s["per_year"] = {y: {"n": len(v), "exc_mean": round(sum(v)/len(v), 2),
                             "exc_ci": [round(x, 2) for x in bl.bootstrap_ci(v)]}
                         for y, v in sorted(by_year.items())}
        result["horizons"][h] = s
        result["layer2"][h] = {k: bl.summarize_events(v["abs"], v["exc"], cost)
                               for k, v in grp.items()}
        if s.get("n"):
            print(f"\n【H={h}d】n={s['n']} 超額 {s['exc_mean']:+.2f}% "
                  f"CI {s['exc_ci']} t={s['t']} 淨 {s['net']:+.2f}% "
                  f"edge {s.get('edge_mean')}")
            for k, lab in (("ge2", "ABD≥2"), ("lt2", "ABD<2")):
                g = result["layer2"][h][k]
                if g.get("n"):
                    print(f"    {lab}: n={g['n']} 超額 {g['exc_mean']:+.2f}% "
                          f"CI {g['exc_ci']}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--entry", default="next_open",
                    choices=["next_open", "signal_close"])
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    r = run(args.horizon, args.cost, start=args.start, entry=args.entry)
    if args.json_out:
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "params": {"horizons": args.horizon, "cost": args.cost,
                              "entry": args.entry, **TR_DEFAULTS},
                   "result": r},
                  open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[json] 寫入 {args.json_out}", file=sys.stderr)
```

- [ ] **Step 3: 小樣本煙霧測試（先別跑全市場）**

臨時把 `codes = sorted(panel.stocks)` 改 `codes = ["2330", "3105", "4576", "3491", "3406", "6166"]`（README 記載 2026-04-29 曾通過的股票）跑一次：
Run: `FINMIND_TOKEN=... python3 tw_turnaround_backtest.py`
Expected: 不噴錯、events > 0（這幾檔 2026-04 前後應有事件）、Layer2 分組有數字。改回全市場。

- [ ] **Step 4: 全市場跑（首跑 FS+SBL 抓取 ~1-2 小時，之後快取）**

Run: `FINMIND_TOKEN=... python3 tw_turnaround_backtest.py --json-out concept_momentum/cache/turnaround_backtest.json 2>&1 | tail -30`
Expected 檢查點：
- episodes 數量級：數百～上千（若 <20 → PIT 截斷或可用日規則有 bug；若 >5000 → cooldown 沒生效）
- 與現實對照：`turnaround_relay_history/` 近 40 天 Layer 1 每天約 3-10 檔 → 全年推算數百 episodes 合理
- `layer2.ge2 vs lt2`：這是「Layer 2 是否加值」的第一個量化答案，數字直接寫進 README

- [ ] **Step 5: 對照 live 歷史（半自動驗證）**

寫一段臨時腳本比對：取 `concept_momentum/cache/turnaround_relay_history/2026*.json` 內 `layer1_passed` 的 (date, code)，對照回測在同日的事件集合，印出 overlap%（≥50% 即可——法定死線規則比實際公告晚、Yahoo/FinMind 量能微差都會造成差異；<30% 就要查 bug）。結果數字記進 README 的回測章節（透明化 PIT 重建與 live 的差距）。

- [ ] **Step 6: dashboard `/turnaround-backtest` 頁（完全仿 `/second-wave-backtest` 的 route+template 模式，多一個 Layer2 ge2/lt2 對照表）+ README 新章節「轉機接力回測」+ commit**

```bash
git add tw_turnaround_screener.py tw_turnaround_backtest.py concept_momentum/app.py README.md
git commit -m "轉機接力回測: Layer1 point-in-time 事件研究 + Layer2 ABD overlay"
```

---

### Task 11: 借券雷達 + 空頭撤退 回測

**Files:**
- Create: `tw_lending_backtest.py`
- 產出物: `bt_cache/lend_{code}.json`

**Interfaces:**
- Consumes: `backtest_prices.load_panel/_fm/_token/BT_CACHE`、`backtest_lib`、Task 10 的 `fetch_sbl`（從 `tw_turnaround_backtest` import）
- Produces: JSON `concept_momentum/cache/lending_backtest.json`：`{generated, result:{sbl_retreat:{all:{h:...}, up_only:{h:...}}, lending_surge:{low_rate:{h:...}, high_rate:{h:...}}}}`

**訊號定義（對齊 `tw_lending_monitor.py` 的 live 規則）**：
- 空頭撤退：`當日借券賣出餘額 / 前日 - 1 ≤ -10%`；子集 `up_only` = 且當日個股收漲（live 推播的「轉多訊號」分組）。
- 借券雷達：`當日議借量 > 前 5 日均量 × 2` 且 量加權平均利率 `<1%` 或 `>7%`（`low_rate` / `high_rate` 分開統計——兩者方向含義不同）。資料 `TaiwanStockSecuritiesLending`（先 `grep -n "def fetch_securities_lending" finmind_client.py` 確認欄位名：實測含 `transaction_type`（定價/競價/議借）、`volume`（張）、`fee_rate`）。

- [ ] **Step 1: 寫腳本**

```python
#!/usr/bin/env python3
"""借券雷達 + 空頭撤退 回測 — 事件研究 (point-in-time)。

兩個盤後推播策略的歷史驗證 (live 規則見 tw_lending_monitor.py)：
  空頭撤退: SBL 餘額日減 ≥10% (all / up_only 兩組)
  借券雷達: 議借量 > 5d 均 × 2 且 利率 <1% (low_rate) 或 >7% (high_rate)
訊號於盤後資料產生 → 進場 = 隔日還原開盤。統計/成本/基準同 backtest_lib。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                     # noqa: E402
from backtest_prices import load_panel, _fm, _token, BT_CACHE  # noqa: E402
from tw_turnaround_backtest import fetch_sbl                   # noqa: E402


def fetch_lending(code: str, token: str) -> dict:
    """議借 (negotiated) 日彙總: {date(YYYYMMDD): {vol(張), rate(量加權%)}}。快取 7 天。"""
    p = os.path.join(BT_CACHE, f"lend_{code}.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        return json.load(open(p))
    data = _fm("TaiwanStockSecuritiesLending", code, "2024-12-01", token)
    agg = {}
    for r in data:
        # 只取議借 (與 live 借券雷達同口徑)；欄位名以 finmind_client 實測為準
        if "議借" not in str(r.get("transaction_type", "")):
            continue
        d = (r.get("date") or "").replace("-", "")
        v = float(r.get("volume") or 0)
        rate = float(r.get("fee_rate") or 0)
        if not d or v <= 0:
            continue
        a = agg.setdefault(d, {"vol": 0.0, "rv": 0.0})
        a["vol"] += v
        a["rv"] += v * rate
    out = {d: {"vol": a["vol"], "rate": a["rv"] / a["vol"]}
           for d, a in agg.items() if a["vol"] > 0}
    json.dump(out, open(p, "w"))
    return out


def _study(events, panel, horizons, cost, label):
    """events = [(code, dateYYYYMMDD)] → {h: summary}。"""
    out = {}
    for h in horizons:
        absr, excr, edges = [], [], []
        for code, date in events:
            r = panel.fwd(code, date, h, "next_open")
            if r is None:
                continue
            sr, tr = r
            absr.append(sr); excr.append(sr - tr)
            b = panel.matched_baseline(date, h)
            if b is not None:
                edges.append(sr - tr - b)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        out[h] = s
        if s.get("n"):
            print(f"  [{label} H={h}] n={s['n']} 超額 {s['exc_mean']:+.2f}% "
                  f"CI {s['exc_ci']} 淨 {s['net']:+.2f}% edge {s.get('edge_mean')}")
    return out


def run(horizons, cost, min_balance_zhang=200):
    token = _token()
    panel = load_panel()
    max_h = max(horizons)
    ev_sbl_all, ev_sbl_up = [], []
    ev_low, ev_high = [], []
    codes = sorted(panel.stocks)
    for n, code in enumerate(codes):
        if (n + 1) % 200 == 0:
            print(f"  {n+1}/{len(codes)}", file=sys.stderr)
        rows, didx = panel._by_code[code]
        # ── 空頭撤退：SBL 日減 ≥10%（前日餘額 ≥ min_balance 張，避免小基數雜訊）
        sbl = fetch_sbl(code, token)
        fires_all, fires_up = [], []
        for j in range(1, len(sbl)):
            prev, cur = sbl[j - 1]["balance"], sbl[j]["balance"]
            d = sbl[j]["date"]
            if prev < min_balance_zhang or d not in didx:
                continue
            if (cur - prev) / prev <= -0.10:
                i = didx[d]
                fires_all.append(i)
                if i > 0 and rows[i]["close"] > rows[i - 1]["close"]:
                    fires_up.append(i)
        for i in bl.dedup_cooldown(sorted(set(fires_all)), max_h):
            ev_sbl_all.append((code, rows[i]["date"]))
        for i in bl.dedup_cooldown(sorted(set(fires_up)), max_h):
            ev_sbl_up.append((code, rows[i]["date"]))
        # ── 借券雷達：議借量 >5d均×2 + 利率帶
        lend = fetch_lending(code, token)
        ldates = sorted(lend)
        for j in range(5, len(ldates)):
            d = ldates[j]
            if d not in didx:
                continue
            prev5 = [lend[ldates[k]]["vol"] for k in range(j - 5, j)]
            avg5 = sum(prev5) / 5
            cur = lend[d]
            if avg5 <= 0 or cur["vol"] <= avg5 * 2:
                continue
            i = didx[d]
            if cur["rate"] < 1.0:
                ev_low.append((code, rows[i]["date"], i))
            elif cur["rate"] > 7.0:
                ev_high.append((code, rows[i]["date"], i))
    # 議借事件 cooldown（per code）
    def _dedup(evs):
        by = {}
        for code, date, i in evs:
            by.setdefault(code, []).append(i)
        out = []
        for code, fires in by.items():
            rows, _ = panel._by_code[code]
            for i in bl.dedup_cooldown(sorted(set(fires)), max_h):
                out.append((code, rows[i]["date"]))
        return out
    ev_low, ev_high = _dedup(ev_low), _dedup(ev_high)

    print(f"\n空頭撤退 all={len(ev_sbl_all)} up_only={len(ev_sbl_up)}  "
          f"議借 low={len(ev_low)} high={len(ev_high)}")
    return {
        "sbl_retreat": {"all": _study(ev_sbl_all, panel, horizons, cost, "撤退all"),
                        "up_only": _study(ev_sbl_up, panel, horizons, cost, "撤退up")},
        "lending_surge": {"low_rate": _study(ev_low, panel, horizons, cost, "議借<1%"),
                          "high_rate": _study(ev_high, panel, horizons, cost, "議借>7%")},
        "params": {"min_balance_zhang": min_balance_zhang, "cost": cost},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--min-balance", type=int, default=200)
    ap.add_argument("--json-out")
    args = ap.parse_args()
    r = run(args.horizon, args.cost, args.min_balance)
    if args.json_out:
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "result": r}, open(args.json_out, "w", encoding="utf-8"),
                  ensure_ascii=False)
        print(f"[json] 寫入 {args.json_out}", file=sys.stderr)
```

- [ ] **Step 2: 欄位名核實**（寫死前先跑）

Run: `FINMIND_TOKEN=... python3 -c "
from backtest_prices import _fm, _token
rows = _fm('TaiwanStockSecuritiesLending', '2313', '2026-05-08', _token())
print(rows[0] if rows else 'EMPTY')"`
Expected: 印出一列 → 核對 `transaction_type/volume/fee_rate` 鍵名，與 `fetch_lending` 不符就改 code（`tests/test_finmind_client.py` 有 2313 5/8 議借 190 張的已知值可對照）。

- [ ] **Step 3: 小樣本煙霧測試（codes 臨時縮到 50 檔）→ 全市場跑 → 寫 JSON**

Run: `FINMIND_TOKEN=... python3 tw_lending_backtest.py --json-out concept_momentum/cache/lending_backtest.json 2>&1 | tail -20`
Expected: 空頭撤退 all 事件數千（-10% 日變不罕見）、up_only 較少；議借 high/low 各數十~數百。任何一組 n<30 標「樣本不足」。

- [ ] **Step 4: dashboard 頁 `/lending-backtest`（仿既有回測頁；四組各一表）+ README 新章節（重點：`up_only` vs `all` 的差異就是「借券減少且今日上漲=轉多」這條 live 分組規則的驗證）+ commit**

```bash
git add tw_lending_backtest.py concept_momentum/app.py README.md
git commit -m "借券雷達+空頭撤退 回測: 事件研究 (SBL日減10% / 議借爆量×利率帶)"
```

---

### Task 12: 推播訊號成效追蹤器（自動後照鏡）

**Files:**
- Create: `concept_momentum/signal_outcomes.py`（純函數核心）
- Create: `concept_momentum/run_outcomes.py`（CLI：算 + 存 + TG 推播）
- Test: `tests/test_signal_outcomes.py`
- Modify: `concept_momentum/app.py`（新 tab「📈 訊號成效」）
- Modify: crontab（每週一 08:10）

**Interfaces:**
- Produces: `signal_outcomes.load_signals(cache_root) -> list[dict]`——正規化 5 個 history dir 成 `{strategy, signal_date, entry_date, code, meta}`
- Produces: `signal_outcomes.compute_outcomes(signals, px_fetch, taiex_rows, horizons=(1,5,10,20)) -> dict`
- Produces: `concept_momentum/cache/signal_outcomes.json`

**Date 正規化規則（實測各 history 的 date 語意，勿改）：**

| 策略 dir | date 欄位語意 | list 欄位 | entry_date 規則 |
|----------|--------------|----------|----------------|
| `turnaround_relay_history` | **資料日**（前一交易日；實測檔名 20260706 內容 date=20260703） | `candidates` | date 之後的下一個交易日 |
| `second_wave_history` | **執行日**（盤前；實測 20260706=20260706） | `candidates` | ≥ date 的第一個交易日 |
| `broker_radar_history` | 資料日（盤後 18:00） | `stocks` | date 之後的下一個交易日 |
| `lending_radar_history` | 資料日（盤後 16:00） | `stocks` | date 之後的下一個交易日 |
| `short_retreat_history` | 資料日（盤後 21:30） | `stocks` | date 之後的下一個交易日 |

entry 價 = entry_date 的**還原開盤價**（早上看到推播、開盤買的最保守可實現口徑）；成效 = T+h 收盤（還原）報酬 − TAIEX 同窗報酬。
**T+h 慣例（與回測 `panel.fwd` 對齊）**：h 從 entry 日起算，出場 = `trading_dates[entry_idx + h - 1]` 的收盤——即 **h=1 是進場當日的開盤→收盤**，h=5 約一週。

- [ ] **Step 1: 寫失敗測試（合成 fixture，不打 API）**

```python
# tests/test_signal_outcomes.py
"""訊號成效追蹤器 — date 正規化與報酬計算。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "concept_momentum"))
import signal_outcomes as so


def _mkroot():
    root = tempfile.mkdtemp()
    tr = os.path.join(root, "turnaround_relay_history")
    sw = os.path.join(root, "second_wave_history")
    os.makedirs(tr); os.makedirs(sw)
    # TR: 檔名=執行日, date=資料日 (週五) → entry 應為下一交易日 (週一 0706)
    json.dump({"date": "20260703", "candidates": [
        {"code": "2425", "name": "承啟", "layer1_passed": True, "abcd_score": 4}]},
        open(os.path.join(tr, "20260706.json"), "w"))
    # SW: date=執行日 (週一) → entry 應為 ≥date 第一個交易日 = 0706
    json.dump({"date": "20260706", "candidates": [
        {"code": "8043", "name": "蜜望實", "second_wave_score": 0.0267,
         "drop_pct": 0.22, "volume_ratio": 1.65}]},
        open(os.path.join(sw, "20260706.json"), "w"))
    return root


TRADING = ["20260702", "20260703", "20260706", "20260707", "20260708",
           "20260709", "20260710", "20260713"]


class TestNormalize(unittest.TestCase):
    def test_entry_dates(self):
        sigs = so.load_signals(_mkroot(), trading_dates=TRADING)
        by = {(s["strategy"], s["code"]): s for s in sigs}
        self.assertEqual(by[("turnaround_relay", "2425")]["entry_date"], "20260706")
        self.assertEqual(by[("second_wave", "8043")]["entry_date"], "20260706")
        self.assertEqual(by[("turnaround_relay", "2425")]["meta"]["abcd_score"], 4)


class TestOutcome(unittest.TestCase):
    def test_returns(self):
        # 慣例：h=1 = 進場日開→收 (100→101 = +1%)；h=2 = 隔日收 (100→103 = +3%)
        px = {"2425": {"20260706": {"aopen": 100.0, "aclose": 101.0},
                       "20260707": {"aopen": 102.0, "aclose": 103.0}}}
        taiex = {d: {"open": 100.0, "close": 100.0} for d in TRADING}
        sigs = [{"strategy": "turnaround_relay", "code": "2425",
                 "signal_date": "20260703", "entry_date": "20260706", "meta": {}}]
        out = so.compute_outcomes(sigs, lambda c: px.get(c, {}), taiex,
                                  trading_dates=TRADING, horizons=(1, 2))
        rec = out["signals"][0]
        self.assertAlmostEqual(rec["ret"]["1"]["abs"], 1.0, places=4)
        self.assertAlmostEqual(rec["ret"]["2"]["abs"], 3.0, places=4)
        self.assertAlmostEqual(rec["ret"]["2"]["exc"], 3.0, places=4)


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_signal_outcomes -v` → FAIL（module 不存在）。

- [ ] **Step 2: 實作 `signal_outcomes.py`**

```python
"""訊號成效追蹤 — 把 5 個推播歷史 dir 的每筆訊號配上 T+h 實際報酬 (後照鏡自動化)。

date 語意 (實測，勿信直覺)：
  turnaround_relay / broker_radar / lending_radar / short_retreat: date=資料日 → entry=下一交易日
  second_wave: date=執行日 (盤前) → entry=≥date 第一個交易日
entry 價 = entry_date 還原開盤；成效 = T+h 還原收盤報酬 − TAIEX 同窗。
"""
from __future__ import annotations
import bisect
import json
import os

STRATS = {
    "turnaround_relay": ("turnaround_relay_history", "candidates", "after"),
    "second_wave": ("second_wave_history", "candidates", "on_or_after"),
    "broker_radar": ("broker_radar_history", "stocks", "after"),
    "lending_radar": ("lending_radar_history", "stocks", "after"),
    "short_retreat": ("short_retreat_history", "stocks", "after"),
}


def _entry_date(date: str, rule: str, trading_dates: list[str]) -> str | None:
    if rule == "after":
        i = bisect.bisect_right(trading_dates, date)
    else:  # on_or_after
        i = bisect.bisect_left(trading_dates, date)
    return trading_dates[i] if i < len(trading_dates) else None


def load_signals(cache_root: str, trading_dates: list[str]) -> list[dict]:
    out, seen = [], set()
    for strat, (dirname, field, rule) in STRATS.items():
        d = os.path.join(cache_root, dirname)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(d, fn)))
            except (OSError, json.JSONDecodeError):
                continue
            date = str(data.get("date") or fn[:8])
            for item in data.get(field, []):
                code = str(item.get("code") or "")
                if not code:
                    continue
                key = (strat, date, code)
                if key in seen:      # 同訊號同日只算一次
                    continue
                seen.add(key)
                entry = _entry_date(date, rule, trading_dates)
                if entry is None:
                    continue
                meta = {k: v for k, v in item.items() if k not in ("code", "name")}
                meta["name"] = item.get("name", code)
                out.append({"strategy": strat, "signal_date": date,
                            "entry_date": entry, "code": code, "meta": meta})
    return out


def compute_outcomes(signals: list[dict], px_fetch, taiex: dict,
                     trading_dates: list[str], horizons=(1, 5, 10, 20)) -> dict:
    """px_fetch(code) -> {dateYYYYMMDD: {"aopen","aclose"}}；taiex[date] -> {"open","close"}。"""
    tx_idx = {d: i for i, d in enumerate(trading_dates)}
    recs = []
    for s in signals:
        px = px_fetch(s["code"])
        e = s["entry_date"]
        if e not in px or e not in tx_idx:
            continue
        e_px = px[e].get("aopen") or 0
        tx0 = taiex.get(e, {}).get("open") or taiex.get(e, {}).get("close") or 0
        if e_px <= 0 or tx0 <= 0:
            continue
        ei = tx_idx[e]
        ret = {}
        for h in horizons:
            if ei + h - 1 >= len(trading_dates):
                continue
            xd = trading_dates[ei + h - 1]          # T+h = entry 起第 h 個交易日收盤
            x = px.get(xd, {}).get("aclose") or 0
            tx1 = taiex.get(xd, {}).get("close") or 0
            if x <= 0 or tx1 <= 0:
                continue
            sr = (x / e_px - 1) * 100
            tr = (tx1 / tx0 - 1) * 100
            ret[str(h)] = {"abs": round(sr, 2), "exc": round(sr - tr, 2)}
        if ret:
            recs.append({**s, "ret": ret})
    # 彙總 per strategy × horizon
    agg = {}
    for r in recs:
        a = agg.setdefault(r["strategy"], {str(h): {"abs": [], "exc": []}
                                           for h in horizons})
        for h, v in r["ret"].items():
            a[h]["abs"].append(v["abs"])
            a[h]["exc"].append(v["exc"])
    summary = {}
    for strat, hs in agg.items():
        summary[strat] = {}
        for h, v in hs.items():
            n = len(v["exc"])
            if not n:
                continue
            summary[strat][h] = {
                "n": n,
                "abs_mean": round(sum(v["abs"]) / n, 2),
                "exc_mean": round(sum(v["exc"]) / n, 2),
                "exc_med": round(sorted(v["exc"])[n // 2], 2),
                "win": round(sum(1 for x in v["abs"] if x > 0) / n * 100, 0),
                "beat": round(sum(1 for x in v["exc"] if x > 0) / n * 100, 0),
            }
    return {"signals": recs, "summary": summary}
```

- [ ] **Step 3: 跑單元測試** → `python3 -m unittest tests.test_signal_outcomes -v` PASS

- [ ] **Step 4: `run_outcomes.py` CLI**

功能（仿 `run_daily.py` 的結構與 TG 發送）：
1. TAIEX + 交易日曆：FinMind `TaiwanStockPrice` `TAIEX` 自 2026-04-01（快取 `cache/outcomes_px/TAIEX.json` 1 天）。
2. `px_fetch(code)`：FinMind `TaiwanStockPriceAdj` 自 2026-04-01 → `{date: {aopen, aclose}}`，快取 `cache/outcomes_px/{code}.json` 1 天（unique codes 目前 ~40 天 × 5 策略約數百檔，sponsor 沒問題）。
3. `load_signals` + `compute_outcomes` → 寫 `cache/signal_outcomes.json`（含 `generated`）。
4. `--telegram`：推摘要（每策略一行 × h=1/5/20：`n / 超額均 / 勝率`；TR 額外分 `abcd_score>=3` vs `<3` 兩行——meta 裡有 abcd_score）。TG 發送函數直接抄 `tw_second_wave.py` 的 `send_telegram`（同 chat_id 預設 `-5229750819`）。
5. 額外彙總（寫進 JSON，dashboard 用）：TR 按 `abcd_score` 分桶、SW 按 `second_wave_score` 三分位分桶的 summary——直接回答「4/4 是否優於 3/4」「score 高低有沒有差」。

- [ ] **Step 5: 手動跑一次**

Run: `FINMIND_TOKEN=... python3 concept_momentum/run_outcomes.py`
Expected: `cache/signal_outcomes.json` 生成；summary 各策略 n>0（turnaround_relay 約 40 天 × 每天 3-10 檔；second_wave 類似）。抽 2-3 筆對 Yahoo/看盤軟體人工核對報酬方向。

- [ ] **Step 6: dashboard tab「📈 訊號成效」**

`app.py` 仿「🌅 盤前訊號」tab 的 route/render 模式（讀 `premarket_signals_renderer.py` 依樣寫 `signal_outcomes_renderer.py`）：每策略一張表（h=1/5/10/20 的 n/超額/勝率/贏大盤率）+ TR abcd 分桶表 + 最近 20 筆訊號明細（code/日期/T+5 超額）。

- [ ] **Step 7: crontab + README + commit**

```bash
crontab -l | { cat; echo '10 8 * * 1 TG_BOT_TOKEN=<既有值> FINMIND_TOKEN=<既有值> /usr/bin/python3 /home/kun/project/tw_stock_tools/concept_momentum/run_outcomes.py --telegram >> /home/kun/project/tw_stock_tools/outcomes.log 2>&1'; } | crontab -
```
（`<既有值>` 從現有 crontab 行複製——**必帶 FINMIND_TOKEN**。）
README 加「訊號成效追蹤」章節（date 正規化表、entry 口徑、cron 時間）。

```bash
git add concept_momentum/signal_outcomes.py concept_momentum/run_outcomes.py \
        concept_momentum/signal_outcomes_renderer.py concept_momentum/app.py \
        tests/test_signal_outcomes.py README.md
git commit -m "訊號成效追蹤器: 5 策略推播自動配 T+h 實際報酬 (自動後照鏡) + 週報"
```

---

## Backlog（本計畫不做；每項應開獨立 plan）

實作者請把此清單原樣抄進 README 的「未來改進」區（或獨立 `docs/superpowers/specs/` 檔），讓後續 session 有據可查：

1. **盤中模擬 (intraday-sim) 的處置**：回測已證明無方向 skill（skill_vs_zero -2.4%，方向命中 51.6% vs 「永遠猜跌」57%）且信心帶過窄（41% vs 目標 50%）。選項：(a) `/intraday-sim` 頁面頂部加紅字告示「回測顯示無方向預測力，僅供情境想像」；(b) 加寬帶寬重新校準；(c) 下架。至少做 (a)。
2. **主力雷達訊號設計**：Pearson corr 算在 n=5 天上幾乎無過濾力（`tw_broker_lookup.py:212`）。bsr_cache 已累積 40+ 天 → 可改 `--days 10`。注意：改參數後 `broker_radar_history` 新舊事件不可混合回測，需重新累積 1-2 個月再評估。改前先用現行回測基準線存檔。
3. **參數敏感度掃描**：對第二波 7 條件、TR 6 參數做 grid 掃描 + walk-forward（2025 調參 / 2026 驗證）。必須在 Task 3/10 之後做（有了可信的衡量才有調參的意義）。
4. **倖存者偏差**：universe 改用含下市股的清單（FinMind `TaiwanStockInfo` 含 `date` 欄位可判斷；或 TWSE 下市公司名單），回測面板補抓已下市股票價格。
5. **美台聯動多重比較**：`--scan` 對 ~190 檔挑最高相關 = winner's curse。輸出加 split-half 驗證欄（前半窗 vs 後半窗 corr 同號才標「穩定」）。
6. **turnaround screener 資料源**：Yahoo → FinMind（其他工具 2026-05-11 已遷移，`tw_turnaround_screener.py:40` 還在用 Yahoo，rate-limit 靜默跳過會讓 universe 每天不同）。同時加「抓取失敗計數」到輸出——區分「無候選」與「資料斷線」。
7. **組合層模擬**：事件研究之上加簡單組合模擬（同時最多 K 檔、等權、資金重複使用規則），回答「這些策略疊起來的資金曲線長怎樣」。
8. **沉睡巨人 / 美台聯動 回測**：沉睡巨人持有期長（月~年），需要不同的評估框架（6m/12m horizon + 觸發稀少）；美台聯動是配對訊號非選股訊號。各開獨立 plan。
9. **dormant_giants 還原價來源**：Yahoo adjclose → FinMind `TaiwanStockPriceAdj`（sponsor 已可用，README 註記過時）。

---

## 驗收清單（全部 task 完成後）

- [ ] `python3 -m unittest discover tests -v` 全綠
- [ ] 4 個既有回測 JSON 重新生成，dashboard 4 頁正常顯示 CI/中位數
- [ ] `turnaround_backtest.json` + `lending_backtest.json` 存在且 dashboard 有頁
- [ ] `signal_outcomes.json` 存在、TG 收到一次週報格式訊息（可手動觸發）
- [ ] README 所有對應章節已更新（含新舊回測數字不可比的說明）
- [ ] crontab 新行帶 FINMIND_TOKEN
- [ ] 第二波 7-9 月除權息季的候選清單 spot-check：不再出現「除息缺口股」
