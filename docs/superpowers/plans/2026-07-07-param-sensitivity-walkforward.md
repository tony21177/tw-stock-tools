# 參數敏感度掃描 + Walk-Forward 驗證 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 對「強勢股第二波」(11 參數) 與「轉機接力 Layer 1」(6 參數) 做 one-at-a-time 參數敏感度掃描，以 IS (2025-01~2026-03) / OOS (2026-04~今) 切窗防過擬合，產出敏感度報告頁 — **只提案、不自動改任何 live 預設參數**。

**Architecture:** 兩個既有回測的 `run()` 增加 (a) 參數覆蓋注入 (b) 事件層日期切窗彙總（一次全期掃描同時產 IS/OOS 兩組統計，掃描次數減半）。新 `tw_param_sweep.py` 驅動掃描：spec 定義每參數候選值、逐 run 快取可續跑、彙總成單一 JSON。dashboard 新頁畫敏感度曲線。

**Tech Stack:** 沿用 2026-07-06 計畫的全部基礎（backtest_lib / backtest_prices v2 面板 / FILTER_DEFAULTS / TR_DEFAULTS）。純 CPU 重算，除 TR 的 FS/SBL 快取外零新增 API 呼叫。stdlib unittest。

## Global Constraints

（繼承 2026-07-06 計畫全部約束，另加：）
- **絕對不改任何 live 預設參數**。掃描結論以「提案」形式寫進 README 與頁面，由使用者決定是否採納。
- **多重比較紀律**：任何「更優組合」必須同時滿足 (a) IS 上優於預設 (b) OOS 上不劣於預設 (edge_mean 且 n 不崩) 才能標記為候選提案；只在 IS 贏的組合標「⚠ 疑似過擬合」。
- 每個 task 完成後同步更新 README；dashboard 新頁所有術語用 `_BACKTEST_GLOSSARY` + `_glossary_section` 解釋（含新詞：one-at-a-time、IS/OOS、walk-forward、參數懸崖）。
- 跑批 detached（nohup + log 輪詢）；每 run 結果落檔，中斷可續跑。
- 回測 JSON 既有欄位只增不刪。

---

## 背景

2026-07-06 計畫修好了「尺」（進場口徑/除息/CI/基準），現在才輪到「調參」有意義。現行參數全部是手調（第二波 base 在 2313 案例、TR 在 2026-04 樣本），從未做過敏感度或樣本外驗證。要回答的問題：
1. 每個參數在預設值鄰域是「平坦」（robust）還是「懸崖」（脆弱、疑似過擬合單一歷史）？
2. 有沒有 IS+OOS 雙贏的更優鄰域值得提案？
3. 參數變嚴 → episodes 掉 → CI 爆寬的 trade-off 長怎樣（顯示 n 與 CI，不只均值）。

Runtime 預算：第二波每 run 全市場 ~8-15 min CPU、TR 每 run ~5-10 min（資料全快取）。掃描規模（見 Task B2 spec）約 22+12=34 runs ≈ 4-7 小時 → overnight 跑批，逐 run 落檔。

## File Structure

```
├── tw_second_wave_backtest.py   # 修改：run(params_override, windows) 注入 + 切窗彙總（Task B1）
├── tw_turnaround_backtest.py    # 修改：同上（Task B1）
├── tw_param_sweep.py            # 新增：掃描 driver + spec + 彙總（Task B2）
├── bt_cache/sweep/              # 每 run 快取（gitignore 已涵蓋 bt_cache/）
├── concept_momentum/app.py      # 修改：/param-sweep 頁（Task B3）
├── tests/test_param_sweep.py    # 新增（Task B1/B2）
└── README.md                    # 各 task 同步
```

依賴順序：1 → 2 → 3 →（4 跑批+結論）。

---

### Task 1: 兩個回測的參數注入 + 日期切窗彙總

**Files:**
- Modify: `tw_second_wave_backtest.py`
- Modify: `tw_turnaround_backtest.py`
- Test: `tests/test_param_sweep.py`（先建檔，本 task 放 windows 切分的純函數測試）

**Interfaces:**
- Produces: `tw_second_wave_backtest.run(horizons, cost, entry="next_open", dedup_days=None, start="2025-01-01", baseline_k=100, params_override=None, windows=None)`
  - `params_override: dict|None` — 覆蓋 `FILTER_DEFAULTS` 的子集：`DEFAULT_ARGS = Namespace(**{**FILTER_DEFAULTS, **(params_override or {})})` 移進 run() 內組裝（module-level DEFAULT_ARGS 移除，`__main__` 不變行為）。
  - `windows: dict[str, tuple[str, str]]|None` — 例 `{"IS": ("20250101","20260331"), "OOS": ("20260401","20991231")}`。None 時行為與現在完全相同（單一全期 summary，JSON schema 不變）。給定時：`summary["windows"] = {label: {h: summarize_events(該窗內 events...)}}`，事件按 **entry date**（即訊號日 `date` 欄位）落窗；全期 `horizons` 照舊輸出。
- Produces: `tw_turnaround_backtest.run(horizons, cost, start, entry, params_override=None, windows=None)` — 同語意，覆蓋 `TR_DEFAULTS`（`p = argparse.Namespace(**{**TR_DEFAULTS, **(params_override or {})})`）。windows 彙總同上（layer2 分組可只在全期算，windows 內不必分 ge2/lt2）。
- Produces: 共用純函數 `split_by_window(events_with_dates: list[tuple], windows: dict) -> dict[label, list]`（放 `backtest_lib.py`，兩回測共用；event tuple 第 2 位是 YYYYMMDD date）。

- [ ] **Step 1: 失敗測試（純函數 + 注入語意）**

```python
# tests/test_param_sweep.py
"""參數注入與切窗彙總 — 合成資料，不打 API、不跑全市場。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import backtest_lib as bl


class TestSplitByWindow(unittest.TestCase):
    def test_split(self):
        events = [("A", "20250601", 1), ("B", "20260315", 2), ("C", "20260501", 3)]
        w = {"IS": ("20250101", "20260331"), "OOS": ("20260401", "20991231")}
        out = bl.split_by_window(events, w)
        self.assertEqual([e[0] for e in out["IS"]], ["A", "B"])
        self.assertEqual([e[0] for e in out["OOS"]], ["C"])

    def test_boundary_inclusive(self):
        events = [("A", "20260331", 1), ("B", "20260401", 2)]
        w = {"IS": ("20250101", "20260331"), "OOS": ("20260401", "20991231")}
        out = bl.split_by_window(events, w)
        self.assertEqual(len(out["IS"]), 1)
        self.assertEqual(len(out["OOS"]), 1)


class TestParamsOverride(unittest.TestCase):
    def test_second_wave_namespace_merge(self):
        from tw_second_wave import FILTER_DEFAULTS
        merged = {**FILTER_DEFAULTS, **{"drop_min": 0.10}}
        self.assertEqual(merged["drop_min"], 0.10)
        self.assertEqual(merged["drop_max"], FILTER_DEFAULTS["drop_max"])


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest tests.test_param_sweep -v` → FAIL（`split_by_window` 不存在）。

- [ ] **Step 2: `backtest_lib.split_by_window` 實作**

```python
def split_by_window(events, windows):
    """events = [(..., date_yyyymmdd, ...)]，date 在 tuple index 1。
    windows = {label: (from, to)} 含兩端。回 {label: [events]}。"""
    out = {k: [] for k in windows}
    for ev in events:
        d = ev[1]
        for label, (lo, hi) in windows.items():
            if lo <= d <= hi:
                out[label].append(ev)
    return out
```

- [ ] **Step 3: 兩個回測 run() 改造**（各自：Namespace 合併移入 run；events 收集後若 windows 給定，用 `bl.split_by_window` 對每窗把該窗 events 重跑「fwd+matched_baseline+summarize_events」彙總迴圈——把現有的 per-horizon 彙總抽成內部函數 `_summarize_window(events_subset, h)` 供全期與各窗共用，避免複製貼上）。`__main__` 加 `--is-end`（預設空=不切窗；給定如 `20260331` 時自動組 windows IS/OOS）。JSON：windows 存在時多 `result.windows` 鍵。

- [ ] **Step 4: 驗證** — 單元測試綠；`python3 tw_second_wave_backtest.py --help` 出現 --is-end；抽查：`--is-end 20260331` 小跑（暫時縮 universe 50 檔驗證 windows 鍵存在後還原，不 commit 縮限）；無 windows 時 JSON 與改造前 schema 一致（diff 既有 cache JSON 的 keys）。

- [ ] **Step 5: README（兩回測章節各加 --is-end 說明）+ commit** `回測: 參數注入 + IS/OOS 切窗彙總 (掃描基礎)`

---

### Task 2: `tw_param_sweep.py` 掃描 driver

**Files:**
- Create: `tw_param_sweep.py`
- Test: `tests/test_param_sweep.py`（追加 spec 完整性測試）

**掃描 spec（寫死在檔內，one-at-a-time：固定其餘為預設）：**

```python
SWEEP_SPEC = {
    "second_wave": {
        "rally_min_gain":    [0.20, 0.30, 0.45],
        "drop_min":          [0.10, 0.15, 0.20],
        "drop_max":          [0.22, 0.25, 0.30],
        "min_drop_days":     [3, 5, 8],
        "max_drop_days":     [12, 15, 20],
        "max_recovery_days": [7, 10, 15],
        "recovery_min_gain": [0.03, 0.05, 0.08],
        "recovery_vol_ratio": [0.5, 0.7, 1.0],
        "max_today_vs_peak": [0.95, 0.98],
    },                       # 9 參數（peak_lookback/min_recovery_days 固定 — 結構性參數）
    "turnaround": {
        "gm_pp":       [1.0, 1.5, 2.5],
        "gm_qoq":      [1, 2, 3],
        "vol_ratio":   [1.15, 1.3, 1.5],
        "sbl_decline": [0.90, 0.95, 1.00],
        "ma_curv_ratio": [0.0, 0.5, 1.0],
    },                       # 5 參數（ma_accel_days 固定）
}
WINDOWS = {"IS": ("20250101", "20260331"), "OOS": ("20260401", "20991231")}
```

（中間值=現行預設 → 預設 run 各策略只跑一次共用。總 runs：second_wave 8×2+1+1=18、turnaround 5×2+1=11，共 29 — 以 driver 依 spec 動態計算為準。）

**Interfaces:**
- Produces: CLI `python3 tw_param_sweep.py [--strategy second_wave|turnaround|both] [--horizon 20] [--json-out ...]`
- 每 run 快取 `bt_cache/sweep/{strategy}__{param}__{value}.json`（預設組合存 `{strategy}__default__.json`）；存在即跳過（resumable）。
- 彙總 JSON `concept_momentum/cache/param_sweep.json`：
  `{generated, windows, strategies: {strat: {default: {IS:{...}, OOS:{...}}, params: {param: [{value, is_default, IS: {n, exc_mean, exc_ci, edge_mean, edge_ci}, OOS: {...}}]}, proposals: [...], overfit_flags: [...]}}`
- 提案規則（寫進程式，機械判定）：候選值相對預設 `IS.edge_mean 提升 ≥1.0pp 且 OOS.edge_mean ≥ 預設的 OOS.edge_mean − 0.5pp 且 OOS.n ≥ 30` → `proposals`；只 IS 贏 → `overfit_flags`。

- [ ] **Step 1: spec 測試**（追加到 tests/test_param_sweep.py：每參數候選含預設值、值有序、runs 數計算正確）
- [ ] **Step 2: driver 實作** — import 兩回測的 run()；每 run `run(horizons=[args.horizon], cost=bl.cost_roundtrip_pct(), params_override={param: value}, windows=WINDOWS)` → 抽 `result.windows` 存快取；進度列印 `[run k/30] strat param=value → IS edge X / OOS edge Y (n a/b)`；彙總+提案判定+json-out。
- [ ] **Step 3: 煙霧測試**（--strategy turnaround 先跑 1-2 個 run 驗證流程，TR 較快）
- [ ] **Step 4: commit** `參數掃描 driver (one-at-a-time × IS/OOS, resumable)`

---

### Task 3: dashboard `/param-sweep` 頁 + README

- 每策略一組敏感度小圖（或表）：每參數一行 — 候選值 × (IS edge / OOS edge / OOS n)，預設值加粗，proposals 綠標、overfit_flags 紅標。若 plotly 圖工程大，表格版即可（先求資訊正確）。
- 術語表：one-at-a-time、IS/OOS（樣本內/外）、walk-forward、參數懸崖/平坦、提案規則白話。
- 頁首固定告示：「本頁為提案性質 — live 參數未變更；採納請人工確認」。
- Flask test client 驗證；README 新章節「參數敏感度掃描」。
- commit `dashboard: /param-sweep 敏感度頁 + 術語`

### Task 4: 全量跑批 + 結論

- `nohup python3 tw_param_sweep.py --json-out concept_momentum/cache/param_sweep.json > bt_cache/sweep.log 2>&1 &`（~4-7 小時，輪詢）
- 完成後：README 補結論段（robust/脆弱參數清單、proposals/overfit_flags 各幾個、對使用者的建議）；若 proposals 非空 → 明確列出「建議人工評估的參數變更」但不改 code。
- commit `參數掃描結論 (README + param_sweep.json)`

## 驗收清單

- [ ] `python3 -m unittest discover tests` 分支相關全綠
- [ ] 無 windows 參數時兩回測 JSON schema 與改造前一致（dashboard 舊頁不受影響）
- [ ] param_sweep.json 30 runs 全數落檔；/param-sweep 頁 render 200 + 術語表
- [ ] README：--is-end 用法 + 掃描結論；live 預設參數 0 變更（git diff 確認 FILTER_DEFAULTS/TR_DEFAULTS 未動）
