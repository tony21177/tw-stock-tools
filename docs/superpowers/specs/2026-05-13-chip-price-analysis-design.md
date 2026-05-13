# Design Spec — 籌碼價格分析 (chip-price)

**Date:** 2026-05-13
**Author:** kun (tony21177) + Claude
**Repo:** tw_stock_tools
**Target:** New CLI tool + user skill that analyzes a single stock's daily TWSE BSR (買賣日報表) with per-price-level detail, broken down by broker × price, to infer intraday timing of major buys/sells.

## 1. Goal

The existing `/chip` skill aggregates BSR to per-broker level (loses price detail). For a single stock on a single day, the TWSE BSR CSV actually contains `(broker, price, buy_shares, sell_shares)` triples. By preserving the price dimension, we can:

1. List **Top 10 大單 broker × 價格 cells** — the biggest single-(broker, price) buys and sells, the rough equivalent of "key intraday actors"
2. **Stage analysis** — split the day's price range into 3 zones (low 25% / middle 50% / high 25%) ≈ (early / mid / late session), show who bought/sold in each zone
3. **Per-broker fingerprint** — for Top 10 buyers and Top 10 sellers, show which price levels they accumulated/distributed at (sign of buying low/selling high, or chasing momentum)

Trigger: user says `XXXX籌碼價格` / `XXXX 籌碼價量` / `XXXX 分點價格` / `/chip-price XXXX` in Telegram.

## 2. Out of Scope

- True intraday tick-by-tick analysis (TWSE BSR has no actual timestamps; price is a proxy)
- Historical day-over-day comparison (BSR only available T+0 for the published day; once we cache it, can replay; first deployment may have limited history)
- TPEx (上櫃) per-price detail — depends on whether TPEx's CSV exposes the same columns; **try to support; fall back to aggregate if format differs**
- Real-time mid-day data (TWSE BSR publishes after close, typically 17:30-18:00)

## 3. Decision Log (from user input)

- **Q1 trigger phrases = A+B+C all** — Skill recognises any of:
  - `XXXX籌碼價格`
  - `XXXX 籌碼價量` / `XXXX 分點價格`
  - `/chip-price XXXX` slash command form
- **Q2 fetch strategy = C force re-fetch** — Always pull fresh BSR from TWSE for the requested stock. No cache-first read for per-price data (because the existing aggregate cache discarded prices, and the user wants the most up-to-date snapshot anyway).
- **Q3 output range = D (full set)** — All of: Top 10 大單 cells, stage analysis, per-broker fingerprint.
- **Q4 markets = A** — Support both TWSE (上市) and TPEx (上櫃). TPEx falls back to aggregate-only with a warning if its CSV doesn't expose per-price detail.

## 4. Architecture

```
~/project/tw_stock_tools/
├── tw_chip_price.py             ← NEW: CLI entry point
├── bsr_scraper.py               ← MODIFY: add fetch_bsr_with_prices()
│                                  (preserves per-price rows; original
│                                  fetch_bsr stays untouched for callers
│                                  that want aggregate only)
└── bsr_cache/
    └── {code}_{date}_prices.json ← NEW: per-price detail cache
                                    (distinct from existing aggregate cache)

~/.claude/skills/
└── chip-price/
    └── SKILL.md                 ← NEW: triggers on 籌碼價格 / 籌碼價量 / 分點價格
```

The new tool deliberately stays separate from `/chip` so the existing skill's "三線整合 (借券+分點+融資)" flow keeps its current scope, and `/chip-price` adds the price-level deep dive on demand.

## 5. Data Structure

### Per-price cache JSON shape (`bsr_cache/{code}_{date}_prices.json`)

```json
{
  "date": "20260512",
  "stock_code": "2313",
  "market": "TWSE",
  "open": 246.0,
  "high": 264.5,
  "low": 246.0,
  "close": 260.0,
  "total_buy_shares": 93922000,
  "total_sell_shares": 93922000,
  "rows": [
    {"broker_id": "1020", "broker_name": "合 庫",
     "price": 249.0, "buy": 5000, "sell": 0},
    {"broker_id": "1020", "broker_name": "合 庫",
     "price": 251.0, "buy": 0, "sell": 1000},
    ...
  ]
}
```

Each row is one `(broker, price)` cell as it appears in TWSE's CSV. `buy` and `sell` are in **shares (股)**, matching the CSV's native unit. Dashboard / skill output converts to 張 by dividing by 1000.

### CLI output (Telegram-friendly markdown)

```
2313 華通 籌碼價格分析 (2026/05/12)
開盤 $246.00 / 收盤 $260.00 / 高 $264.50 / 低 $246.00 (+7.44%)
總量 94 千張

【🔥 Top 10 大單 cells (broker × price)】
1. 1480 美商高盛 @$246.50 買 8,200張 ⬇ 早盤搶低
2. 1480 美商高盛 @$263.00 買 3,500張 ↗ 盤中追進
3. 8888 國泰敦南 @$264.00 賣 3,100張 ⬆ 高檔倒貨
...

【⏰ 三階段分析】
早盤 (低 25%: $246.00 ~ $250.63):
  🟢 買方主力: 高盛 +8,500張 / 瑞銀 +4,200張 / 摩根大通 +2,800張
  🔴 賣方主力: 國泰敦南 -600張 / 中信 -500張

盤中 (中 50%: $250.63 ~ $260.13):
  ... 主要分點 buy/sell

尾盤 (高 25%: $260.13 ~ $264.50):
  ... 主要分點 buy/sell

【🎯 Top 5 買超分點價格指紋】
1. 高盛 +11,837張 — 主力倉位在 $246-252 (低檔搶) 加 $260-264 (確認追漲)
2. 瑞銀 +5,810張 — 平均成本 $252.4，buy 全程分布
3. 摩根大通 +3,823張 — 加碼集中 $250-255 (盤中)
...

【🎯 Top 5 賣超分點價格指紋】
1. 國泰敦南 -1,376張 — 賣壓全在 $258+ (尾盤獲利)
2. 中信 -1,103張 — 賣壓在 $255-262 (盤中分批)
...

【判讀】
外資 5 大行 +26,374張 集中在低檔買進 → 確認多頭意圖
散戶分點高檔小幅賣出 → 部分人 fomo 套牢後止盈
```

## 6. CLI Interface

```bash
tw_chip_price.py 2313                       # today (force re-fetch)
tw_chip_price.py 2313 --date 20260512       # specific date (must have cache)
tw_chip_price.py 2313 --telegram            # push report to TG
tw_chip_price.py 2313 --json-out path.json  # also write structured output
tw_chip_price.py 2313 --no-fetch            # cache-only (fail if missing)
```

Output: text report to stdout. Optional Telegram push. Optional JSON for downstream tooling.

## 7. Scraper Modification

`bsr_scraper.py:_parse_bsr_csv()` currently aggregates `(broker)` → `{name, buy, sell}`. The new `_parse_bsr_csv_with_prices()` returns a list of rows preserving the price column. The existing aggregator stays untouched (multiple callers depend on it).

```python
def _parse_bsr_csv_with_prices(text: str) -> list[dict]:
    """Return [{broker_id, broker_name, price (float), buy (int shares),
    sell (int shares)}] preserving per-price detail."""
    ...
```

And a new fetch wrapper:

```python
def fetch_bsr_with_prices(stock_code: str, max_attempts: int = 10) -> dict:
    """Same flow as fetch_bsr but returns {date, stock_code, market, ohlc,
    total_buy_shares, total_sell_shares, rows: [...per-price rows...]}."""
```

The OHLC fields (open/high/low/close) come from a Yahoo / FinMind side call so we have the price range needed for stage analysis. They are NOT in the BSR CSV.

## 8. Stage Analysis Logic

```python
def stage_breakdown(rows: list[dict], low: float, high: float) -> dict:
    """Split price range [low, high] into 3 zones:
      early  = [low, low + 0.25 × (high - low)]
      mid    = [low + 0.25 × range, low + 0.75 × range]
      late   = [low + 0.75 × range, high]
    For each zone, aggregate buy/sell per broker. Return:
      {early: [(broker, net), ...], mid: [...], late: [...]}
    sorted by absolute net within each zone."""
```

The 25%/50%/25% split is a heuristic — typical morning panic at low, mid-day discovery in middle, end-of-day discovery at high. Override-able later if user wants different splits.

## 9. Tool Output Cell Format

The "Top 10 大單 cells" output annotates each cell with a direction tag:

- `⬇ 早盤搶低` if price ≤ low + 25% of range (zone-1) AND buy > 0
- `⬆ 高檔倒貨` if price ≥ low + 75% of range (zone-3) AND sell > 0
- `↗ 盤中追進` if mid zone AND buy > 0
- `↘ 盤中出脫` if mid zone AND sell > 0
- `△ 低檔賣壓` if zone-1 AND sell > 0 (unusual)
- `▽ 高檔追進` if zone-3 AND buy > 0 (FOMO)

## 10. TPEx Support

The TPEx scraper (`tpex_scraper.py` via Playwright) returns the same CSV format but via different URL. If per-price CSV is available, same parser works. If not, `fetch_bsr_with_prices` falls back to aggregate-only and tags `"per_price_available": false` in the output dict; the analyzer falls back to "可比 chip skill but no stage" mode.

## 11. Skill Wiring

`~/.claude/skills/chip-price/SKILL.md` triggers on:
- `籌碼價格 / 籌碼價量 / 分點價格` keywords with a 4-digit stock code
- Slash form `/chip-price XXXX`

The skill instructs the agent to run:
```bash
FINMIND_TOKEN=... /usr/bin/python3 ~/project/tw_stock_tools/tw_chip_price.py <code>
```

And forward the report to Telegram via the existing reply infrastructure.

## 12. Acceptance Criteria

1. Running `tw_chip_price.py 2313` on a trading day returns within 30 seconds (BSR fetch + parse + analysis)
2. Output includes:
   - OHLC + total volume
   - Top 10 大單 cells with direction tags
   - 3-stage breakdown (early/mid/late) with top 3 buyers/sellers per stage
   - Top 5 buyer + Top 5 seller fingerprints
3. Per-price cache saved at `bsr_cache/{code}_{date}_prices.json` (new format, doesn't conflict with existing aggregate cache)
4. Skill triggers on all 3 phrase variants and slash form
5. TPEx stock (e.g., 3491 昇達科) at minimum returns aggregate-mode output with a warning if per-price not available

## 13. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| TWSE rate-limit / CAPTCHA fail | Existing scraper retries up to 10× with new CAPTCHAs; tool prints warning and retries |
| TPEx CSV doesn't expose price | Detect during parse; fall back to aggregate output with note |
| Per-price cache file grows large | Each is ~50-200 KB; gitignore `bsr_cache/*_prices.json` (already covered by `bsr_cache/`) |
| Cell direction tagging misleads (price ≠ time perfectly) | Document in tooltip / report header that price is a proxy, not a true timestamp |
| Yahoo/FinMind for OHLC fails | Falls back to using max/min of all price levels in BSR CSV |

## 14. Implementation Phases

1. Modify `bsr_scraper.py` — add `_parse_bsr_csv_with_prices` + `fetch_bsr_with_prices` (TDD)
2. Create `tw_chip_price.py` — fetcher + analyzer + formatter (TDD on analyzer)
3. CLI args + telegram push + JSON output
4. TPEx fallback handling
5. Create `~/.claude/skills/chip-price/SKILL.md`
6. End-to-end test on 2313 (TWSE) and 3491 (TPEx fallback)
7. README + memory updates

Estimated 9-11 tasks, same magnitude as `chip` skill creation earlier.
