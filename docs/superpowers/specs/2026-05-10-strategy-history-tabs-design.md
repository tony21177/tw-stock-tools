# Design Spec — 策略歷史榜三 tab (主力雷達 / 盤前訊號 / 借券動向)

**Date:** 2026-05-10
**Author:** kun (tony21177) + Claude
**Repo:** tw_stock_tools
**Target:** Add three new tabs to the existing concept_momentum web dashboard, each consuming an existing strategy's daily output and presenting it as a sortable history table.

## 1. Goal

Build on the established market_breadth tab pattern to surface three more strategies on the dashboard:

1. **🎯 主力雷達歷史榜** — Smart-money tracking. Stocks ranked by a composite score (consecutive days on the radar × magnitude of broker buying + margin increase). Lets the user see which stocks have been persistently accumulated by significant brokers.

2. **🌅 盤前訊號** — Pre-market signals from the two pre-market crons. Two stacked tables: 轉機接力 (TR) and 強勢股第二波. Both show the last 10 trading days of candidates with consecutive-appearance count.

3. **🌙 借券動向** — Securities-lending signals from the two SBL crons. Two stacked tables: 借券雷達 (議借爆量) and 空頭撤退 (借券賣餘大減). Both show the last 5 trading days.

All three tabs share the market_breadth tab's architecture: pure-function loader + pure-function renderer + injection point in `concept_charts.generate_html()`.

## 2. Out of Scope

- Historical backfill before deployment day (data sources are cron-driven; can't reconstruct past runs)
- Telegram push for the new views (web-only; the underlying strategies still push their own daily Telegram messages)
- Per-stock drill-down pages (that's the chip skill's territory)
- Mobile-specific layout (responsive horizontal scroll handles small screens)
- Real-time intraday updates (each tab refreshes once per cron run, same as concept_momentum)

## 3. Tab Definitions

### 3.1 主力雷達歷史榜

**Source:** `tw_broker_monitor.py` daily output (currently Telegram-only; will add `--json-out`)

**Columns:**

| # | Column | Format |
|---|--------|--------|
| 1 | 排名 | int |
| 2 | 代號 | "2330" |
| 3 | 名稱 | from `stock_names` |
| 4 | 連續天數 | int — number of consecutive recent days the stock appeared in the broker_monitor result |
| 5 | 最新入榜日期 | YYYY/MM/DD |
| 6 | Top 分點 (broker_id name) | "9268 凱基台北" |
| 7 | 區間 Top 分點累計淨買 | int 張 |
| 8 | 區間融資增量 | int 張 |
| 9 | 綜合分數 | float, rounded to 1 decimal |

**Composite score formula (Q1.5 = D 複合):**

```
top_factor = log(max(top_broker_net_zhang, 0) + 1)         # broker scale
margin_factor = sqrt(max(margin_total_increase_zhang, 0))  # margin scale
score = consecutive_days × (top_factor + margin_factor) / 2
```

If `top_broker_net_zhang` ≤ 0, `top_factor = 0` (no penalty for negative; the stock just shouldn't be on the radar in that case).
If `margin_total_increase` ≤ 0, `margin_factor = 0` (same reasoning).
Both factors are clipped to non-negative — defensively handles edge cases.

**Sort:** by `score` desc. Ties broken by `consecutive_days` desc, then `top_broker_net_zhang` desc.

**History depth:** 10 trading days lookback for consecutive-day computation. Display top 30 rows.

**Empty state:** "今日無主力雷達訊號" when no JSON files exist yet.

### 3.2 盤前訊號 (10 日歷史)

**Source:** `tw_daily_screen.py` (TR Layer 2) + `tw_second_wave.py` outputs (will add `--json-out`).

#### Sub-table A: 轉機接力 Layer 2 (ABCD)

| # | Column | Format |
|---|--------|--------|
| 1 | 代號 | "2330" |
| 2 | 名稱 | from `stock_names` |
| 3 | 入榜日期 | YYYY/MM/DD |
| 4 | Layer 1 通過 | bool ✓ |
| 5 | Layer 2 ABCD 分數 | int |
| 6 | 連續入榜天數 | int |

**Sort:** latest入榜日期 desc, 連續入榜天數 desc, ABCD 分數 desc.
**Display:** All candidates from past 10 days (typically 5-30 rows).

#### Sub-table B: 強勢股第二波

| # | Column | Format |
|---|--------|--------|
| 1 | 代號 | "2313" |
| 2 | 名稱 | from `stock_names` |
| 3 | 入榜日期 | YYYY/MM/DD |
| 4 | 第二波分數 | float |
| 5 | 急殺跌幅% | float (signed) |
| 6 | 量比 | float |
| 7 | 連續入榜天數 | int |

**Sort:** latest 入榜日期 desc, 連續入榜天數 desc, 第二波分數 desc.

**Empty state per sub-table:** "近 10 個交易日無候選" when empty.

### 3.3 借券動向 (5 日歷史)

**Source:** `tw_lending_monitor.py` (currently Telegram-only; will add `--json-out`).

#### Sub-table A: 借券雷達 (議借爆量)

| # | Column | Format |
|---|--------|--------|
| 1 | 代號 | "3491" |
| 2 | 名稱 | from `stock_names` |
| 3 | 入榜日期 | YYYY/MM/DD |
| 4 | 議借量 (張) | int |
| 5 | 5 日均量倍數 | float "5.2x" |
| 6 | 利率% | float (with sign coloring: red >7%, green <1%) |
| 7 | 連續入榜天數 | int |

**Sort:** latest入榜日期 desc, 連續入榜 desc, 議借量 desc.

#### Sub-table B: 空頭撤退 (借券賣餘大減)

| # | Column | Format |
|---|--------|--------|
| 1 | 代號 | "2313" |
| 2 | 名稱 | from `stock_names` |
| 3 | 入榜日期 | YYYY/MM/DD |
| 4 | 餘額變化% | float (signed; red >0%, green <0%) |
| 5 | 今日漲跌% | float (signed) |
| 6 | 連續入榜天數 | int |

**Sort:** 餘額變化% asc (most negative first = biggest空方撤退).

**Empty state per sub-table:** "近 5 個交易日無候選".

## 4. Data Flow

```
[Strategy cron runs]
  ↓
tw_broker_monitor.py    --json-out cache/broker_radar_history/{YYYYMMDD}.json
tw_daily_screen.py      --layer2-json-out cache/turnaround_relay_history/{YYYYMMDD}.json
tw_second_wave.py       --json-out cache/second_wave_history/{YYYYMMDD}.json
tw_lending_monitor.py   --mode lending --json-out cache/lending_radar_history/{YYYYMMDD}.json
tw_lending_monitor.py   --mode sbl     --json-out cache/short_retreat_history/{YYYYMMDD}.json

[17:00 cron — concept_momentum/run_daily.py]
  ↓
load_broker_radar_history(...)  → list of rows for last 10 days, computes consecutive-day count + composite score
load_premarket_signals(...)     → 轉機接力 + 2nd wave for last 10 days, with consecutive count
load_lending_history(...)       → 議借 + 空方撤退 for last 5 days, with consecutive count
  ↓
broker_radar_renderer.render_table(rows)  → HTML table
premarket_signals_renderer.render_table(tr_rows, sw_rows)  → HTML two-section
lending_history_renderer.render_table(lend_rows, retreat_rows)  → HTML two-section
  ↓
concept_charts.generate_html(...,
    broker_radar_html=...,
    premarket_signals_html=...,
    lending_history_html=...,
)  → dashboard.html
```

## 5. Architecture / File Structure

**Create:**

| File | Purpose |
|------|---------|
| `concept_momentum/broker_radar_history.py` | Load broker history JSONs, compute consecutive-day count + composite score, return list of dicts |
| `concept_momentum/broker_radar_renderer.py` | Pure render function: dict list → HTML table string |
| `concept_momentum/premarket_signals.py` | Load TR + second-wave history JSONs, compute consecutive count, return two lists |
| `concept_momentum/premarket_signals_renderer.py` | Render two stacked sub-tables (TR + 2W) |
| `concept_momentum/lending_history.py` | Load lending + sbl history JSONs, compute consecutive count, return two lists |
| `concept_momentum/lending_history_renderer.py` | Render two stacked sub-tables (議借 + 空頭撤退) |
| Tests: `concept_momentum/tests/test_broker_radar_history.py` etc. | Unit tests for compute + render functions |

**Modify:**

| File | Change |
|------|--------|
| `tw_broker_monitor.py` | Add `--json-out PATH` flag |
| `tw_lending_monitor.py` | Add `--json-out PATH` flag (writes mode-specific output) |
| `tw_second_wave.py` | Add `--json-out PATH` flag if missing |
| `tw_daily_screen.py` | Verify/extend Layer 2 JSON export; rename to `--layer2-json-out` if needed |
| `concept_momentum/concept_charts.py` | `generate_html()` signature: add 3 new optional `*_html` params, inject 3 new tabs |
| `concept_momentum/run_daily.py` | Call 3 history loaders + 3 renderers, pass into `generate_html()` |
| `crontab` | Add `--json-out` paths to each strategy's cron line |
| `.gitignore` | Add new cache dirs |
| `README.md` § 11 | Document the 3 new tabs |
| `~/.claude/projects/-home-kun/memory/` | Add memory note for the new dashboard tabs |

## 6. Cache Layout

```
concept_momentum/cache/
├── broker_radar_history/
│   └── {YYYYMMDD}.json     # tw_broker_monitor's daily output (after --json-out added)
├── turnaround_relay_history/
│   └── {YYYYMMDD}.json     # tw_daily_screen.py Layer 2 results
├── second_wave_history/
│   └── {YYYYMMDD}.json     # tw_second_wave.py results
├── lending_radar_history/
│   └── {YYYYMMDD}.json     # tw_lending_monitor.py --mode lending results
└── short_retreat_history/
    └── {YYYYMMDD}.json     # tw_lending_monitor.py --mode sbl results
```

All gitignored. No backfill needed (data is cron-driven; only "today onward" populates over time).

## 7. JSON Schema for Each History Cache

### broker_radar_history/{date}.json

```json
{
  "date": "20260510",
  "stocks": [
    {
      "code": "2330",
      "name": "台積電",
      "current_balance": 12345,
      "margin_increase_zhang": 500,
      "candidates": [
        {"broker_id": "9268", "broker_name": "凱基台北",
         "active_days": 5, "total_net_zhang": 3000, "correlation": 0.72,
         "buy_dates": ["20260506", "20260507", ...]}
      ]
    }
  ]
}
```

### turnaround_relay_history/{date}.json

```json
{
  "date": "20260510",
  "candidates": [
    {"code": "2313", "name": "華通",
     "layer1_passed": true,
     "abcd_score": 4,
     "abcd_breakdown": {"a": 1, "b": 1, "c": 1, "d": 1}}
  ]
}
```

### second_wave_history/{date}.json

```json
{
  "date": "20260510",
  "candidates": [
    {"code": "2313", "name": "華通",
     "second_wave_score": 8.5,
     "drop_pct": -22.0,
     "volume_ratio": 5.16}
  ]
}
```

### lending_radar_history/{date}.json

```json
{
  "date": "20260510",
  "stocks": [
    {"code": "3491", "name": "昇達科",
     "lending_zhang": 1280, "ratio_5d": 4.2, "rate_pct": 8.5}
  ]
}
```

### short_retreat_history/{date}.json

```json
{
  "date": "20260510",
  "stocks": [
    {"code": "2313", "name": "華通",
     "balance_change_pct": -11.9,
     "today_change_pct": 1.6}
  ]
}
```

## 8. UI Integration

Tab order in dashboard.html (after change):

```
[📊 大盤寬度] [🎯 主力雷達] [🌅 盤前訊號] [🌙 借券動向] [🔥 概念熱力] [📈 3 個月趨勢] [強勢族群領漲股] [完整排行]
   既有 (active)  新           新           新           既有        既有              既有              既有
```

Default-active stays on `tab-breadth` (大盤寬度). Logic: market overview first, then strategy signals (smart-money / pre-market / lending) sorted by execution time, then concept analytics.

CSS reuse: existing `.pos` / `.neg` / `.tab` / `.tab-content` / `.empty-state` classes. No new global styles needed.

## 9. Error & Edge-Case Handling

- **Missing history dir:** Empty state message, no `<table>`.
- **Empty cache day:** Skipped silently (not an error).
- **Corrupted JSON:** Logged warning, that day skipped.
- **Stock missing name (`stock_names.get` returns None):** fallback to "(未知)".
- **First-day after deployment:** Most rows show "連續 1 日". Acceptable; will fill in over days.
- **Strategy didn't run that day** (cron failure): No JSON for that day; consecutive-day count breaks → resets when cron resumes.

## 10. Testing & Acceptance

### Unit tests (per renderer + per loader)

- Each loader has 3 tests: empty dir, single-day, multi-day with consecutive count.
- Each renderer has 3 tests: empty input, single row, sort/order verification.

### Integration test

End-to-end smoke test in `run_daily.py --skip-fetch`:
- Generates `dashboard.html` containing all 8 tabs (5 existing + 3 new)
- New tabs render whatever cache is available (likely empty on first run, partial after a few days)

### Acceptance per tab

- AC1 (主力雷達歷史榜): Composite score formula verifiable on a known mock; sort order correct; consecutive-day count correct.
- AC2 (盤前訊號): Two sub-tables present; each sortable as specified; missing day breaks consecutive count.
- AC3 (借券動向): Two sub-tables present; rate column color-coded (red >7%, green <1%); 餘額變化% color-coded.

## 11. Implementation Order

1. Add `--json-out` to each strategy (5 changes total)
2. Add cron paths (1 crontab edit)
3. Build loaders (3 modules)
4. Build renderers (3 modules)
5. Wire into `concept_charts.generate_html()` and `run_daily.py`
6. Test end-to-end with mock data
7. Run real cron + watch dashboard fill in over days
8. Document (README + memory)

Estimated effort: 12-16 tasks total, similar to market_breadth deployment.

## 12. Decision Log

- **Q1 排序鍵 = C 複合分數**: Pure consecutive-day misses brokerage scale; pure scale misses persistence. Composite captures both.
- **Q1.5 規模量化 = D 複合**: log of broker net + sqrt of margin increase, averaged. Log/sqrt dampen extreme values; both terms required for high score.
- **Q2 盤前 layout = A 上下兩段**: Mobile-friendly, conceptually distinct strategies separated cleanly.
- **Q3 盤前 history = C 10 days**: Captures持續性 over ~2 weeks; longer window adds noise.
- **Q4 借券 layout = A 上下兩段**: Pattern consistency with Q2.
- **Q5 借券 history = B 5 days**: Lending signals are shorter-cycle than pre-market patterns.
