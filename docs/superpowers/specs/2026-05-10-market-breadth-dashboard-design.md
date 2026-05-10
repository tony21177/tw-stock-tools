# Design Spec — 台股大盤與市場寬度數據看板

**Date:** 2026-05-10
**Author:** kun (tony21177) + Claude
**Repo:** tw_stock_tools
**Target:** Add market overview/breadth dashboard to existing concept_momentum web UI

## 1. Goal

Add a daily market overview table to the existing `concept_momentum/` dashboard, showing 13 metrics per trading day for the last 60 days. Lets the user see at a glance:

- Where the index is (level + day-over-day change)
- How broad the move is (% of stocks above 20/50/200-day MAs, count of new 200-day highs)
- Who is putting money in or pulling out (foreign / trust / dealer institutional flow + total)
- What retail margin investors are doing (margin balance + day-over-day delta)

Three combined views answer the question "is this a healthy uptrend, narrow rally, or distribution?"

## 2. Out of Scope

- Intraday updates (table refreshes once per trading day after market close)
- Telegram push (table is web-only; user opens dashboard to view)
- Sector/concept-level breadth (the existing concept_momentum tab covers that)
- Drill-down per-stock from the table (links/popups not required)
- Mobile-specific layout (responsive horizontal scroll is enough per AC)
- Historical backfill beyond 200 days (200 days is the deepest MA we compute, so anything older adds no signal)

## 3. Final Column Definition (13 columns)

| # | Column | Source | Format |
|---|--------|--------|--------|
| 1 | 日期 | from data | YYYY/MM/DD |
| 2 | 加權指數 | Yahoo `^TWII` close | int with comma, e.g. 31,840 |
| 3 | 漲跌幅% | derived from index close vs prev day | +/-X.XX% |
| 4 | 股價>20MA% | computed on universe | XX.X% |
| 5 | 股價>50MA% | computed on universe | XX.X% |
| 6 | 股價>200MA% | computed on universe | XX.X% |
| 7 | 200日新高數 | computed on universe | int |
| 8 | 外資(億) | FinMind 三大法人 buy-sell | +X.XX |
| 9 | 投信(億) | FinMind | +X.XX |
| 10 | 自營(億) | FinMind | +X.XX |
| 11 | 法人合計(億) | sum of 8+9+10 | +X.XX |
| 12 | 融資(億) | TWSE 大盤每日融資使用金額 (TWSE OpenAPI) + TPEx 同上，相加 (億 NTD) | int with comma |
| 13 | 融資增減(億) | day-over-day delta of column 12 (today − yesterday) | +X.XX |

## 3.1 Metric Formulas (explicit definitions to avoid ambiguity)

- **漲跌幅%** = `(today_close − previous_trading_day_close) / previous_trading_day_close × 100`. Computed on `^TWII` index, not weighted average.
- **股價>NMA%** = `count(stocks where today_close > rolling_mean(close, N)) / count(stocks_with_>=N_days_history) × 100`. N ∈ {20, 50, 200}. Stocks without N days of history are excluded from the denominator (prevents divide-by-zero on new IPOs).
- **200日新高數** = `count(stocks where today_close > max(close[t-200 : t-1]))`. The lookback window excludes today, so today's close beats the prior 200 days' max. Stocks with < 200 days history are excluded.
- **融資增減** = today's 融資(億) − yesterday's 融資(億). If yesterday's value is missing, render `—`.

## 4. Data Sources & Universe

### Universe (for breadth metrics 4-7)
- **上市 + 上櫃 普通股 4 位數代號** (~1,700 stocks)
- Excludes ETF/REITs/權證 (warrant)/槓桿反向 ETF (5/6 位代號 like 00665L)
- Excludes new listings with < 200 days history (skipped from 200MA calc only; still counted in 20/50MA)

### Sources
- **Index level + change**: Yahoo Finance `^TWII` daily close (already cached in `concept_momentum/cache/taiex.json`)
- **Universe daily prices** (NEW): FinMind `TaiwanStockPrice` — call once per trading day with no `data_id` returns all stocks for that day. Backfill ~200 days = 200 calls. Free tier supports this (~600 calls/hour).
- **三大法人**: FinMind `TaiwanStockInstitutionalInvestorsBuySell` — daily aggregate already at market level, no per-stock summing needed.
- **融資使用金額 (大盤)**: TWSE OpenAPI `MI_MARGN_TOTAL` (or equivalent endpoint serving 「融資使用金額」直接的億 NTD 整體數字) + TPEx 對應 endpoint，兩數字相加為當日大盤融資金額。Backfill via FinMind `TaiwanTotalMarginPurchaseShortSale` (dataset for daily aggregate, no per-stock loop needed).

## 5. Architecture

```
concept_momentum/
├── market_breadth.py            ← NEW: orchestrator
│   ├── fetch_universe_day(date) ← FinMind 1 day, all stocks
│   ├── compute_breadth(date)    ← reads last-200-day cache, returns 13 metrics
│   └── ensure_backfill()        ← lazy backfill 200 days on first run
│
├── market_breadth_renderer.py   ← NEW: table HTML
│   └── render_table(rows: list[dict]) → str (HTML <table>...)
│
├── cache/
│   ├── market_universe/
│   │   └── {YYYYMMDD}.json      ← {stocks: [{code, market, close}, ...]}
│   ├── market_breadth/
│   │   └── {YYYYMMDD}.json      ← all 13 metrics for that day
│   └── (existing) taiex.json, prices/, etc.
│
├── concept_charts.py            ← MODIFY generate_html(): inject new "📊 大盤寬度" tab
│
└── run_daily.py                 ← MODIFY: after concept analysis, call market_breadth.run_today()
```

### Module boundaries
- **`market_breadth.py`** owns data fetch + metric computation. Pure functions returning dicts. No HTML or rendering concerns.
- **`market_breadth_renderer.py`** owns HTML rendering only. Takes list-of-dicts and returns HTML string. No data fetch.
- **`concept_charts.py:generate_html()`** orchestrates page assembly — doesn't know about breadth internals.

## 6. Data Flow

```
[17:00 cron]
   ↓
run_daily.py  → analyze_all (concept momentum, existing)
              → compute_rerating, etc. (existing)
              → market_breadth.run_today():
                    1. ensure_backfill()  (skip if cache complete)
                    2. fetch_universe_day(today)  (1 FinMind call)
                    3. fetch_institutional_today()  (1 FinMind call)
                    4. fetch_margin_today()  (1 FinMind call)
                    5. compute_breadth(today)
                    6. save cache/market_breadth/{today}.json
              → load last 60 days from cache/market_breadth/
              → market_breadth_renderer.render_table(rows)
              → concept_charts.generate_html(..., breadth_table_html=...)
              → write dashboard.html with new tab injected
```

## 7. Caching Strategy

### Two-tier cache:
1. **`cache/market_universe/{YYYYMMDD}.json`** — daily price snapshot of all ~1,700 stocks. Used as source of truth for breadth. Once written, immutable.

2. **`cache/market_breadth/{YYYYMMDD}.json`** — fully computed 13-metric row for that day. Lookup-friendly for table rendering.

### Backfill logic:
- On first run, detect missing `cache/market_universe/*.json` files for last 200 trading days, fetch sequentially with 0.5s delay.
- Existing dates skipped.
- After backfill, build `cache/market_breadth/*.json` for last 60 days (only days with ≥200 days of universe history can compute 200MA correctly; earlier days will have null 200MA% which renders as "—").

### Daily incremental:
- Each cron run only fetches 1 new day of universe + computes 1 new breadth row.
- Prior days' breadth rows are NEVER regenerated (immutable post-write) — saves time.

### Cache size estimate:
- Universe: 200 days × ~70 KB = 14 MB
- Breadth: 60 days × ~1 KB = 60 KB
- Total: ~14 MB, fine.

## 8. UI Integration

### Tab structure (after change):
```
[📊 大盤寬度] [🔥 概念熱力] [📈 趨勢] [🔄 Rerating] ...
   ↑ NEW, default-selected
```

### Table HTML (rendered server-side):
```html
<div class="tab-content active" id="market-breadth">
  <h2>📊 大盤寬度</h2>
  <p class="meta">最近 60 個交易日 | 寬度池 = 上市+上櫃 普通股 4 位代號 (~1,700 檔)</p>
  <div class="table-scroll">
    <table class="market-breadth">
      <thead>
        <tr><th>日期</th><th>加權</th><th>漲跌%</th>
            <th>>20MA%</th><th>>50MA%</th><th>>200MA%</th><th>200新高</th>
            <th>外資</th><th>投信</th><th>自營</th><th>法人合計</th>
            <th>融資</th><th>融資±</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>2026/05/10</td>
          <td>31,840</td>
          <td class="pos">+1.23%</td>
          <td>67.5%</td><td>54.2%</td><td>71.0%</td><td>32</td>
          <td class="pos">+45.20</td><td class="neg">-3.50</td>
          <td class="pos">+8.10</td><td class="pos">+49.80</td>
          <td>2,894</td><td class="pos">+12.30</td>
        </tr>
        ...
      </tbody>
    </table>
  </div>
</div>
```

### CSS (reuse existing classes):
- `.pos` (red, +) and `.neg` (green, -) from existing dashboard.html
- Apply to columns 3, 8, 9, 10, 11, 13 only (per AC 2)
- Other absolute-value columns (2, 4-7, 12) use default text color

### Tab switching:
- Existing dashboard already has tabs (`<div class="tabs">`); inject "大盤寬度" as first tab
- Default-active class moves from current first tab to new market-breadth tab

## 9. Error & Edge-Case Handling

### Per AC 3:
- **Empty cache** (no breadth data ever): Show empty-state message inside table area:
  ```html
  <p class="empty-state">目前尚無數據，請稍後再試</p>
  ```
  Do NOT render `<table>` element.

- **Missing cell in a row** (e.g., FinMind hasn't published 三大法人 yet): Render `—` (em-dash) in that cell. Do not break formatting. Continue rendering other cells normally.

- **Stock with < 200 days history**: Excluded from 200MA% denominator only. Counted in 20/50MA% normally. Documented in tooltip.

- **No price for `^TWII`** (data outage): Skip whole row for that day; do NOT show a row with all `—`.

- **FinMind rate-limit hit during backfill**: Catch HTTP 429, sleep 60s, retry once; if still fails, log warning and continue (next day's cron will pick up).

### Defensive defaults:
- All breadth percentages clipped to [0, 100]; NaN treated as missing → `—`.
- Negative 漲跌幅% rendered with explicit `-` sign.
- Zero values rendered as "0.00%" (not "—") to differentiate "computed but zero" vs "no data".

## 10. Testing & Acceptance

### AC 1 — Data integrity & sort
- Render with 60 rows, verify first row is most recent date, descending order
- All 13 columns present in `<thead>` and each `<tbody>` row
- Percent columns show 1-2 decimal places

### AC 2 — Color logic
- For 漲跌幅%, 法人合計, 融資增減: `>0` → red (`.pos`), `<0` → green (`.neg`), `=0` → default
- Spot-test individual cells with positive/negative/zero data

### AC 3 — Edge cases
- Empty cache → friendly message, no broken layout
- Mock missing 法人 data on day X → row X shows `—` in 法人 cells, other cells fine
- Stock count < expected → 200MA% renders correctly with adjusted denominator

### Regression checks
- Existing concept_momentum tab still renders correctly
- Tab switching JavaScript still works for all tabs
- Mobile horizontal scroll works (manual eyeball check)

## 11. Performance Targets

- **First-time backfill**: < 5 min (200 FinMind calls × 0.5s delay = 100s + computation)
- **Daily incremental** (post-backfill): < 30s (1 FinMind call + 1 breadth computation + render)
- **Page load**: < 2s (table is server-side rendered, no client-side data fetch)

## 12. Documentation Updates

After implementation:
- Update `README.md` § 11 (concept_momentum) to mention the market breadth tab
- Update `concept_momentum/README.md` with breadth metric definitions
- Add memory note about new dashboard tab so chip skill / future queries know it exists

## 13. Rollout Steps

1. Implement `market_breadth.py` (fetch + compute)
2. Implement `market_breadth_renderer.py` (HTML table)
3. Modify `concept_charts.py` to accept breadth_table_html param + inject tab
4. Modify `run_daily.py` to call market_breadth before generate_html
5. Test with `--skip-fetch` on existing cache; verify table renders
6. Run real backfill (200 days) — monitor for FinMind rate limits
7. Verify dashboard.html visible at http://localhost:5000/
8. Update README + memory
9. Commit + push to GitHub

## 14. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| FinMind tier doesn't include needed datasets | Verified TaiwanStockPrice + InstitutionalInvestors are free; margin via TaiwanStockMarginPurchaseShortSale also free |
| Rate-limited during backfill | 0.5s delay + 429 retry; if persistent, pause and resume next cron run |
| Universe mismatch (FinMind vs TWSE list) | Cross-check 4-digit-only filter; spot-check with known tickers |
| Cache disk usage | 14 MB acceptable; ignored in .gitignore |
| Existing dashboard regression | Keep changes additive (new files + injection point); don't refactor existing tabs |

## 15. Decision Log

- **Q1**: Universe = 上市+上櫃 4 位數代號 (~1,700 檔). User-confirmed B over alternatives.
- **Q2**: 60 trading days display history. User-confirmed B.
- **Q3**: 200日新高 uses **close** price, not intraday high. User-confirmed A.
- **Q4**: New tab placed at **top** (default visible). User-confirmed A.
- **Q5**: 三大法人 split into 4 columns (外資/投信/自營/合計) instead of 1. User-confirmed B + 加總.
