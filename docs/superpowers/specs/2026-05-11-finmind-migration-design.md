# Design Spec — FinMind Sponsor Tier Migration

**Date:** 2026-05-11
**Author:** kun (tony21177) + Claude
**Repo:** tw_stock_tools

## 1. Goal

Migrate tw_stock_tools data sources to FinMind sponsor tier where it makes the system simpler, faster, and more reliable. Two phases:

- **Phase A — Lending data** (`tw_lending_lookup.py` + `tw_lending_monitor.py`): replace direct TWSE SBL API calls with FinMind to eliminate TWSE rate-limit issues that caused the chip skill to misreport zero transactions on 2026-05-11.
- **Phase C — Daily price data**: replace Yahoo Finance per-stock chart calls in (`tw_second_wave.py`, `tw_dormant_giants.py`, `concept_momentum/data_fetcher.py`, `tw_limitup_signal.py`) with FinMind `TaiwanStockPrice` for a unified data source.

Phase B (broker BSR) is explicitly out of scope after probing FinMind sponsor — the tier does not include per-broker buy/sell data. Per-broker stays on TWSE/TPEx direct scraping (ddddocr + Playwright).

## 2. Out of Scope

- Per-broker BSR (分點) migration — FinMind sponsor lacks the dataset
- US-stock data in `tw_us_correlation.py` (Yahoo only; FinMind has no US data)
- News data in `concept_momentum/news_fetcher.py` (FinMind doesn't have rich news)
- Index data (`^TWII`) — Yahoo already works; FinMind has it but no compelling reason to switch
- Schema changes downstream of fetchers — existing in-memory shapes preserved (drop-in replacement)

## 3. FinMind Sponsor Datasets Used

### Phase A datasets (lending)

| Replacing | FinMind dataset | Tier verified |
|-----------|-----------------|---------------|
| TWSE `t13sa710` 借券交易明細 | `TaiwanStockSecuritiesLending` | ✅ sponsor (probed 2026-05-11) |
| TWSE `t13sa870` 還券明細 | `TaiwanStockSecuritiesLending` (same dataset; transaction_type filter) | ✅ |
| TWSE `TWT93U` + TPEx 借券賣出餘額 | `TaiwanDailyShortSaleBalances` | ✅ sponsor |

### Phase C datasets (prices)

| Replacing | FinMind dataset | Tier verified |
|-----------|-----------------|---------------|
| Yahoo `chart/{code}.TW` daily OHLCV | `TaiwanStockPrice` | ✅ sponsor (already used in market_breadth) |

### Verified Schemas

`TaiwanStockSecuritiesLending` (probe with `2313` on 2026-05-08):
```json
{
  "date": "2026-05-08",
  "stock_id": "2313",
  "transaction_type": "議借",  // 議借 / 競價 / 定價 / 還券 / ...
  "volume": 190,                // 張 (lots) — confirmed; NOT shares
  "fee_rate": 1.75,             // %
  "close": 253.5,
  "original_return_date": "2026-11-06",
  "original_lending_period": 182  // days
}
```

`TaiwanDailyShortSaleBalances` (probe with `2313` on 2026-05-08):
```json
{
  "stock_id": "2313",
  "MarginShortSalesPreviousDayBalance": 520000,  // 信用交易融券前日餘額 (股)
  "MarginShortSalesShortSales": 177000,
  "MarginShortSalesShortCovering": 138000,
  "MarginShortSalesStockRedemption": 0,
  "MarginShortSalesCurrentDayBalance": 559000,
  "MarginShortSalesQuota": 297955147,
  "SBLShortSalesPreviousDayBalance": 21919000,    // 借券賣出前日餘額 (股)
  "SBLShortSalesShortSales": 826000,              // 當日借券賣出 (股)
  "SBLShortSalesReturns": 912000,                 // 當日還券 (股)
  "SBLShortSalesAdjustments": 0,                  // 調整 (股)
  "SBLShortSalesCurrentDayBalance": 21833000,     // 當日餘額 (股)
  "SBLShortSalesQuota": 28064452,
  "SBLShortSalesShortCovering": 0,
  "date": "2026-05-08"
}
```

Unit notes:
- `TaiwanStockSecuritiesLending.volume` is in 張 (lots) — verified by cross-checking 2026-05-08 borrow volume 190 against TWSE published value.
- `TaiwanDailyShortSaleBalances` all *ShortSales*/Balance fields are in 股 (shares); divide by 1000 → 張. Cross-check: SBLShortSalesCurrentDayBalance 21,833,000 ÷ 1000 = 21,833 張, matches TWSE.

`TaiwanStockPrice` schema is the same as already used in market_breadth — `{date, stock_id, Trading_Volume, Trading_money, open, max, min, close, spread, Trading_turnover}`. 18-year history confirmed (2008-01-02 onward for 2330).

## 4. Migration Strategy

### Approach: Per-tool drop-in replacement

For each tool, replace the data-fetching function body while keeping the existing return shape. Downstream code (analysis, format) is untouched.

- Pro: contained changes; one tool at a time; no analysis-code regression risk
- Con: 4-5 tools to touch
- This is the right approach per "isolation and clarity" — each fetcher is a unit with a clear interface.

Phase A first, Phase C second. Phase A is more urgent (chip skill correctness) and smaller scope (2 files).

### Verification approach (user-required at every step)

For each tool's fetcher migration, the implementation task must:

1. **Side-by-side test** — before swapping the call site, run new fetcher and old fetcher side-by-side for the same input (stock + date range). Compare returned dicts field-by-field. Document any deltas.
2. **Tolerance rules** — exact-match required for: stock codes, dates, broker IDs (where applicable), volumes (張), prices (close). For floats (rates), tolerance ±0.01.
3. **Failing comparison blocks commit** — if old and new diverge on a known sample, do not swap call sites; investigate first.
4. **Comparison sample** — minimum 3 stocks × 5 days each:
   - 2313 華通 (active SBL stock, large data)
   - 1268 漢來美食 (low-activity SBL stock, edge case)
   - 2330 台積電 (mega-cap, sanity)
   - Dates: latest 5 trading days
5. **Smoke test after swap** — run the full tool end-to-end on the same samples; output should match prior runs except for known schema improvements.

### Cache strategy

- `margin_cache/` (existing) used by lending_monitor — keep file naming compatible, just change fetcher backend
- `concept_momentum/cache/prices/` and `taiex.json` (existing) — preserve naming and shape so downstream tools don't break

## 5. File-by-File Plan

### Phase A — Lending (2 files)

#### `tw_lending_lookup.py`
- Replace `fetch_lending_transactions()` body (currently calls `www.twse.com.tw/SBL/t13sa710`) → FinMind `TaiwanStockSecuritiesLending`
- Replace `fetch_return_details()` body (currently `t13sa870`) → same FinMind dataset (filter by transaction_type/end_lending)
- Replace `fetch_twse_sbl_balance()` body + `fetch_tpex_sbl_balance()` body → FinMind `TaiwanDailyShortSaleBalances`
- Keep return-dict shapes identical (downstream `format_report()` unchanged)
- Add fallback: if FinMind returns empty, try TWSE direct as warm-fail (one retry per source)

#### `tw_lending_monitor.py`
- Same fetcher replacements as above (the file imports from tw_lending_lookup.py internals or has its own copies — verify during implementation)
- Watch the `--mode lending` (議借異常) + `--mode sbl` (餘額大減) flows — both should still work end-to-end

### Phase C — Daily prices (4 files)

#### `tw_second_wave.py`
- Replace Yahoo `chart/{code}.TW` fetcher with FinMind `TaiwanStockPrice`
- The tool needs ~6 months history per stock; FinMind handles trivially

#### `tw_dormant_giants.py`
- Replace Yahoo `chart/{code}.TW?range=18y` with FinMind `TaiwanStockPrice` from 2008-01-01
- FinMind sponsor confirmed to have 2008+ data for 2330; assume same for others

#### `concept_momentum/data_fetcher.py`
- Replace Yahoo `chart/{code}.TW` per-stock 3-month fetcher with FinMind `TaiwanStockPrice`
- Affects daily concept momentum cron — verify after swap that dashboard generates correctly

#### `tw_limitup_signal.py`
- Inspect during implementation to see which calls are TW vs US (some may stay Yahoo)
- TW-stock Yahoo calls → FinMind

### Removed dependencies

After successful Phase A:
- `www.twse.com.tw/SBL/*` API calls eliminated from lending tools (TWSE rate-limit no longer affects chip skill)

After successful Phase C:
- Yahoo Finance `.TW`/`.TWO` dependency reduced to: index `^TWII` only (in concept_momentum) + US tickers (in tw_us_correlation)

## 6. Architecture Changes

### New shared module

To avoid duplicating the FinMind fetch boilerplate across 6 files, create:

`finmind_client.py` (top-level, in `~/project/tw_stock_tools/`)

```python
"""Thin FinMind v4 API client. Each function returns parsed JSON 'data' list
in FinMind's native schema; callers translate to their own shapes.

Functions:
  fetch_securities_lending(stock_id, start_date, end_date, token) -> list[dict]
  fetch_short_sale_balances(stock_id, start_date, end_date, token) -> list[dict]
  fetch_stock_price(stock_id, start_date, end_date, token) -> list[dict]
  fetch_short_sale_balances_all(date, token) -> list[dict]  # whole-market for one day

Built-in retry: HTTP 429 → sleep 60s, retry once. Other errors raise RuntimeError.
"""
```

This is a thin pass-through (no schema translation, no caching), so each caller stays in control of its own data flow but shares the boilerplate.

### Caching

- Lending: rely on existing log files for history; no new cache needed
- Prices: existing `concept_momentum/cache/prices/{code}_{date}.json` continues to work — just the fetcher backend changes

## 7. Data Flow After Migration

```
Phase A:
  /chip 2313 → tw_lending_lookup.py
    → finmind_client.fetch_securities_lending('2313', start, end, token)
    → finmind_client.fetch_short_sale_balances('2313', start, end, token)
    → format dicts identical to today (no downstream change)

  cron 16:00 lending radar → tw_lending_monitor.py
    → same finmind_client calls
    → --json-out lending_radar_history (already wired)

  cron 21:30 short retreat → tw_lending_monitor.py --mode sbl
    → finmind_client.fetch_short_sale_balances_all(today, token)
    → --json-out short_retreat_history (already wired)

Phase C:
  concept_momentum 17:00 cron → data_fetcher.fetch_all_concepts
    → for each stock: finmind_client.fetch_stock_price(code, start, end, token)
    → cache to existing prices/ dir with same JSON shape

  tw_second_wave.py 07:40 cron → fetch_universe_prices
    → finmind_client.fetch_stock_price(...)

  tw_dormant_giants.py CLI → fetch_18yr_history
    → finmind_client.fetch_stock_price(...)
```

## 8. Verification Per Phase

### Phase A acceptance criteria

1. Side-by-side `tw_lending_lookup.py 2313 --date 20260508` before vs after migration → identical output structure (every line of the report matches; minor formatting OK)
2. Same for `1268` (low activity) and `2330` (mega-cap)
3. End-to-end smoke: `tw_lending_monitor.py --mode lending` produces non-empty output and the JSON file shape unchanged
4. `/chip 2313` after migration shows the 5/11 borrow data **without needing retry** (proves TWSE rate-limit no longer blocks)
5. Remove紀律 6 (TWSE retry) from chip skill once verified — and update memory

### Phase C acceptance criteria

1. `tw_second_wave.py --quiet` — candidate list before vs after migration: identical codes and scores
2. `tw_dormant_giants.py` — top candidates list identical (closes shifted by ≤0.5% tolerance for old data that may have adjustments)
3. `concept_momentum/run_daily.py --skip-fetch` then **with-fetch** — same dashboard rendered: 概念熱力 ranking unchanged, 大盤寬度 unchanged (already uses FinMind, no regression)

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| FinMind 429 rate-limit during Phase C bulk fetch (concept_momentum has ~190 stocks) | Built-in retry in finmind_client; 0.3s delay between calls; sponsor tier ~3000 req/hr limit (vs 600 register) leaves plenty headroom |
| `TaiwanStockSecuritiesLending` doesn't include 還券 (return) events | Need to verify during implementation — if not, fall back to TWSE for returns or skip return detail in lending_lookup |
| Yahoo vs FinMind price differences (adjusted vs raw) | Compare carefully in verification step; FinMind `TaiwanStockPrice` returns raw close, Yahoo `chart` returns adjclose by default — may need `TaiwanStockPriceAdj` instead |
| Historical depth coverage gap (sub-2010 stocks) | Verify on the actual dormant-giant candidate list before swapping; if gap, keep Yahoo for old data, FinMind for new |
| Two cache name collisions (margin_cache used by both lending and margin) | Verify during implementation; rename if needed |

## 10. Implementation Order

1. Phase A first — smaller, more urgent, validates the migration pattern
2. After Phase A complete + chip skill紀律 6 removed → Phase C
3. Each phase ends with a real-data verification + commit + chip-skill update if applicable

## 11. Documentation Updates

After each phase:
- `README.md` — update data-source notes in affected tool sections
- `concept_momentum/README.md` — note FinMind usage for prices if Phase C ships
- Memory — add `reference_finmind_migration.md` if useful for future sessions
- Chip skill — remove紀律 6 (TWSE retry) after Phase A verified

## 12. Decision Log

- **Phase B (broker BSR) cancelled** — confirmed via FinMind 91-dataset probe on 2026-05-11 that no per-broker dataset exists at sponsor tier. User chose Option A (keep TWSE BSR scrapers as-is).
- **Drop-in fetcher replacement, not full rewrite** — preserve existing dict shapes to keep blast radius small.
- **Per-tool migration, not big-bang** — each tool tested side-by-side, committed independently. Easier rollback if a tool regresses.
- **Shared `finmind_client.py`** — DRY for boilerplate, but no schema-translation logic in it (callers stay in control).
