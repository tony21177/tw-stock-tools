# Market Breadth Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 13-column × 60-day "大盤+市場寬度" data table as a new top tab in the existing concept_momentum dashboard.

**Architecture:** Two new files (`market_breadth.py`, `market_breadth_renderer.py`) own data fetch/compute and HTML rendering separately. Two-tier disk cache: `cache/market_universe/{YYYYMMDD}.json` (~1,700 stocks/day) and `cache/market_breadth/{YYYYMMDD}.json` (computed metrics). Existing `concept_charts.generate_html()` and `run_daily.py` get minimal additive hooks. Lazy 200-day backfill on first run; daily incremental thereafter.

**Tech Stack:** Python 3 (stdlib only — `urllib`, `json`, `os`, `statistics`, `unittest`), FinMind REST (free tier), TWSE OpenAPI, Yahoo Finance (already cached). No new pip dependencies.

**Spec:** `docs/superpowers/specs/2026-05-10-market-breadth-dashboard-design.md`

---

## File Structure

**Create:**
- `concept_momentum/market_breadth.py` — fetcher + metric computer (single module, ~400 lines)
- `concept_momentum/market_breadth_renderer.py` — HTML table renderer (~150 lines)
- `concept_momentum/tests/test_market_breadth.py` — unit tests for compute/render
- `concept_momentum/tests/__init__.py` — empty marker

**Modify:**
- `concept_momentum/concept_charts.py` — `generate_html()` accepts new `breadth_table_html` param, injects new tab
- `concept_momentum/run_daily.py` — calls `market_breadth.run_today()` after concept analysis
- `concept_momentum/.gitignore` updated (or top-level `.gitignore`) — add new cache dirs
- `README.md` § 11 — document new tab
- `concept_momentum/README.md` — document breadth metrics
- `~/.claude/projects/-home-kun/memory/MEMORY.md` + new memory file — record dashboard tab

**Run-time data dirs (gitignored, created at runtime):**
- `concept_momentum/cache/market_universe/`
- `concept_momentum/cache/market_breadth/`

---

## Testing Approach

The codebase has no existing pytest setup. This plan uses Python's stdlib `unittest` so tests run without new dependencies:

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Tests focus on **pure functions** (compute_breadth, format_cell, etc.) where mocking is cheap. I/O-heavy fetchers are smoke-tested via real-data integration in Task 9 instead of unit tests with elaborate mocks.

---

### Task 1: Tests scaffold + cache dirs declared

**Files:**
- Create: `concept_momentum/tests/__init__.py`
- Create: `concept_momentum/tests/test_market_breadth.py` (placeholder)
- Modify: `.gitignore` (top-level)

- [ ] **Step 1: Create empty test package marker**

```bash
mkdir -p ~/project/tw_stock_tools/concept_momentum/tests
touch ~/project/tw_stock_tools/concept_momentum/tests/__init__.py
```

- [ ] **Step 2: Create placeholder test file**

Create `concept_momentum/tests/test_market_breadth.py`:

```python
import unittest


class TestMarketBreadthScaffold(unittest.TestCase):
    def test_placeholder(self):
        """Confirms unittest discovery works; replaced in later tasks."""
        self.assertEqual(1 + 1, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run placeholder test to confirm scaffold**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Expected: `Ran 1 test in 0.000s\nOK`

- [ ] **Step 4: Add cache dirs to .gitignore**

Edit `.gitignore` — add after the `concept_momentum/cache/news/` line:

```
concept_momentum/cache/market_universe/
concept_momentum/cache/market_breadth/
```

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/tests .gitignore
git commit -m "market_breadth: scaffold tests + gitignore cache dirs"
```

---

### Task 2: `compute_breadth_for_day()` — pure function, full TDD

**Files:**
- Create: `concept_momentum/market_breadth.py`
- Modify: `concept_momentum/tests/test_market_breadth.py`

- [ ] **Step 1: Write the failing test**

Replace contents of `concept_momentum/tests/test_market_breadth.py`:

```python
import unittest
from concept_momentum.market_breadth import compute_breadth_for_day


def _make_history(closes_per_day: list[list[float]]) -> dict:
    """Build {code: [close_t-N, ..., close_t]} from per-day rows.

    closes_per_day[i] = list of stock closes on day i (oldest first).
    All days must have same number of stocks.
    """
    n_stocks = len(closes_per_day[0])
    return {
        f"{1000 + i:04d}": [day[i] for day in closes_per_day]
        for i in range(n_stocks)
    }


class TestComputeBreadth(unittest.TestCase):
    def test_simple_uptrend_breadth(self):
        # 3 stocks, 21 days history. All rising linearly → all above 20MA.
        closes_per_day = [[10.0 + i, 20.0 + i, 30.0 + i] for i in range(21)]
        history = _make_history(closes_per_day)
        result = compute_breadth_for_day(history)

        # All 3 stocks above 20-day MA on day 21 (the last)
        self.assertAlmostEqual(result["pct_above_20ma"], 100.0, places=1)

    def test_mixed_breadth(self):
        # Stock A: rising; Stock B: flat; Stock C: falling
        # On day 21:
        #   A close=30, mean=20 → above ✓
        #   B close=20, mean=20 → not above (>=, not strict)
        #   C close=10, mean=20 → below ✗
        closes_per_day = []
        for i in range(21):
            closes_per_day.append([10.0 + i, 20.0, 30.0 - i])
        history = _make_history(closes_per_day)
        result = compute_breadth_for_day(history)

        # 1 of 3 strictly above 20MA = 33.33%
        self.assertAlmostEqual(result["pct_above_20ma"], 33.33, places=1)

    def test_excludes_stocks_with_short_history(self):
        # Stock A: 21 days; Stock B: only 5 days (too short for 20MA)
        history = {
            "1000": [10.0 + i for i in range(21)],
            "1001": [50.0, 51.0, 52.0, 53.0, 54.0],
        }
        result = compute_breadth_for_day(history)

        # Only Stock A counted in 20MA; it's above → 100%
        self.assertAlmostEqual(result["pct_above_20ma"], 100.0, places=1)
        # 200MA pool is empty (no stock has 200 days)
        self.assertIsNone(result["pct_above_200ma"])

    def test_new_high_count(self):
        # Stock A: hits new 200-day high today; Stock B: doesn't
        # Need 201 days: prior 200 + today
        a_history = [50.0] * 200 + [60.0]   # today's 60 > prior max 50 → new high
        b_history = [70.0] * 200 + [65.0]   # today's 65 < prior max 70 → no
        history = {"1000": a_history, "1001": b_history}
        result = compute_breadth_for_day(history)

        self.assertEqual(result["new_high_200d"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Expected: `ImportError` or `ModuleNotFoundError: No module named 'concept_momentum.market_breadth'`

- [ ] **Step 3: Write minimal implementation**

Create `concept_momentum/market_breadth.py`:

```python
"""Market breadth computation for the concept_momentum dashboard.

Pure-function compute layer (this file) + I/O layer (added in later tasks).
"""

from __future__ import annotations
from statistics import mean


def compute_breadth_for_day(history: dict[str, list[float]]) -> dict:
    """Given {code: [close_oldest, ..., close_today]}, compute breadth metrics.

    Returns dict with keys:
      pct_above_20ma, pct_above_50ma, pct_above_200ma  (float% or None if pool empty)
      new_high_200d  (int — count of stocks where today's close > max(prior 200))

    Stocks with fewer than N+1 days of history are excluded from the >NMA% pool
    (need N days for the rolling mean + 1 today's close).
    For new_high_200d, stocks need 201 days (200 prior + today).
    """
    pcts = {}
    for ma_n in (20, 50, 200):
        eligible = [closes for closes in history.values() if len(closes) >= ma_n + 1]
        if not eligible:
            pcts[f"pct_above_{ma_n}ma"] = None
            continue
        above = 0
        for closes in eligible:
            today = closes[-1]
            ma = mean(closes[-(ma_n + 1):-1])  # last N closes, excluding today
            if today > ma:
                above += 1
        pcts[f"pct_above_{ma_n}ma"] = round(100.0 * above / len(eligible), 2)

    # 200-day new high
    new_high = 0
    for closes in history.values():
        if len(closes) < 201:
            continue
        prior_max = max(closes[-201:-1])  # past 200 days, excluding today
        if closes[-1] > prior_max:
            new_high += 1
    return {**pcts, "new_high_200d": new_high}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Expected: `Ran 4 tests in <1s\nOK`

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py concept_momentum/tests/test_market_breadth.py
git commit -m "market_breadth: compute_breadth_for_day pure function (TDD)"
```

---

### Task 3: Universe price cache I/O (load + iterate)

**Files:**
- Modify: `concept_momentum/market_breadth.py`
- Modify: `concept_momentum/tests/test_market_breadth.py`

- [ ] **Step 1: Write the failing test**

Append to `concept_momentum/tests/test_market_breadth.py`:

```python
import os
import json
import tempfile


class TestUniverseCache(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_load_universe_history_aggregates(self):
        """Reads multiple {date}.json files, returns {code: [close_oldest_first]}."""
        from concept_momentum.market_breadth import load_universe_history

        # Day 1: 2 stocks
        with open(os.path.join(self.tmpdir, "20260101.json"), "w") as f:
            json.dump({"date": "20260101",
                       "stocks": [{"code": "1000", "close": 10.0},
                                  {"code": "1001", "close": 20.0}]}, f)
        # Day 2: same 2 stocks
        with open(os.path.join(self.tmpdir, "20260102.json"), "w") as f:
            json.dump({"date": "20260102",
                       "stocks": [{"code": "1000", "close": 11.0},
                                  {"code": "1001", "close": 19.0}]}, f)

        history = load_universe_history(self.tmpdir, end_date="20260102", days=2)

        self.assertEqual(history["1000"], [10.0, 11.0])
        self.assertEqual(history["1001"], [20.0, 19.0])

    def test_load_universe_history_skips_missing_codes(self):
        """A stock missing on day N is skipped for that day."""
        from concept_momentum.market_breadth import load_universe_history

        with open(os.path.join(self.tmpdir, "20260101.json"), "w") as f:
            json.dump({"date": "20260101",
                       "stocks": [{"code": "1000", "close": 10.0}]}, f)
        with open(os.path.join(self.tmpdir, "20260102.json"), "w") as f:
            json.dump({"date": "20260102",
                       "stocks": [{"code": "1000", "close": 11.0},
                                  {"code": "1001", "close": 5.0}]}, f)

        history = load_universe_history(self.tmpdir, end_date="20260102", days=2)

        # 1000 has both days; 1001 only has day 2
        self.assertEqual(history["1000"], [10.0, 11.0])
        self.assertEqual(history["1001"], [5.0])
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth.TestUniverseCache -v
```

Expected: `ImportError: cannot import name 'load_universe_history'`

- [ ] **Step 3: Implement load_universe_history**

Append to `concept_momentum/market_breadth.py`:

```python
import json
import os


def load_universe_history(cache_dir: str, end_date: str, days: int) -> dict[str, list[float]]:
    """Load up to `days` days of {YYYYMMDD}.json files ending at end_date.

    Returns {code: [close_oldest, ..., close_at_end_date]}. A stock missing on
    a particular day simply has no entry for that day in the list (not None).

    end_date inclusive. Files newer than end_date are ignored.
    """
    if not os.path.isdir(cache_dir):
        return {}
    files = sorted(f for f in os.listdir(cache_dir)
                   if f.endswith(".json") and f[:8] <= end_date)
    files = files[-days:]

    history: dict[str, list[float]] = {}
    for fname in files:
        with open(os.path.join(cache_dir, fname)) as f:
            data = json.load(f)
        for s in data.get("stocks", []):
            history.setdefault(s["code"], []).append(s["close"])
    return history
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Expected: All tests PASS (placeholder + 4 compute + 2 cache = 7 total).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py concept_momentum/tests/test_market_breadth.py
git commit -m "market_breadth: load_universe_history reader"
```

---

### Task 4: FinMind universe fetch (1 day, real network call)

**Files:**
- Modify: `concept_momentum/market_breadth.py`

This task uses real network because mocking `urllib` is heavier than just running it. Smoke-test only.

- [ ] **Step 1: Add fetch function**

Append to `concept_momentum/market_breadth.py`:

```python
import urllib.request
import urllib.parse
import time

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def fetch_universe_one_day(date: str, finmind_token: str) -> list[dict]:
    """Fetch all stocks' close prices for a single trading day from FinMind.

    `date` in YYYY-MM-DD format. Returns list of
        [{code, market, close, volume}]
    Filtered to 4-digit numeric codes (excludes ETF/REITs/warrants).

    Raises RuntimeError on API error (4xx/5xx or status != 200 in payload).
    """
    import re
    params = {
        "dataset": "TaiwanStockPrice",
        "date": date,
        "token": finmind_token,
    }
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind error for {date}: {payload.get('msg', '')}")

    out = []
    for row in payload.get("data", []):
        code = str(row.get("stock_id", ""))
        if not re.fullmatch(r"\d{4}", code):
            continue
        close = row.get("close")
        if close is None or close <= 0:
            continue
        out.append({
            "code": code,
            "close": float(close),
            "volume": int(row.get("Trading_Volume", 0)),
        })
    return out


def save_universe_day(cache_dir: str, date_yyyymmdd: str, stocks: list[dict]) -> str:
    """Write {date}.json. Returns path."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{date_yyyymmdd}.json")
    with open(path, "w") as f:
        json.dump({"date": date_yyyymmdd, "stocks": stocks}, f, ensure_ascii=False)
    return path
```

- [ ] **Step 2: Smoke test against real FinMind**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import fetch_universe_one_day
import os
stocks = fetch_universe_one_day('2026-05-08', os.environ['TOKEN'])
print(f'fetched {len(stocks)} stocks for 2026-05-08')
print('first 3:', stocks[:3])
" TOKEN=$TOKEN
```

Expected: Prints ~1,500-1,800 stock count and 3 sample rows. If 0 stocks → wrong dataset/token.

- [ ] **Step 3: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py
git commit -m "market_breadth: fetch_universe_one_day via FinMind"
```

---

### Task 5: Backfill helper (lazy fill missing days)

**Files:**
- Modify: `concept_momentum/market_breadth.py`

- [ ] **Step 1: Add backfill function**

Append to `concept_momentum/market_breadth.py`:

```python
from datetime import datetime, timedelta


def _twii_trading_dates(end_date: str, days: int) -> list[str]:
    """Return up to `days` trading dates ending at end_date by reading
    cache/taiex.json. Falls back to weekday-only generation if cache missing."""
    here = os.path.dirname(os.path.abspath(__file__))
    taiex_path = os.path.join(here, "cache", "taiex.json")
    if os.path.exists(taiex_path):
        with open(taiex_path) as f:
            taiex = json.load(f)
        dates = [r["date"] for r in taiex.get("rows", []) if r["date"] <= end_date]
        return dates[-days:]
    # Fallback: just weekdays
    out = []
    end = datetime.strptime(end_date, "%Y%m%d")
    cur = end
    while len(out) < days:
        if cur.weekday() < 5:  # Mon-Fri
            out.append(cur.strftime("%Y%m%d"))
        cur -= timedelta(days=1)
    return list(reversed(out))


def backfill_universe(cache_dir: str, finmind_token: str,
                      end_date: str, days: int = 200,
                      delay_seconds: float = 0.5,
                      verbose: bool = True) -> int:
    """Fetch missing daily snapshots for the last `days` trading dates ending
    at end_date. Returns number of new files written.

    Uses cache/taiex.json's date list as the trading-day source of truth.
    Sleeps `delay_seconds` between FinMind calls to respect free-tier limits.
    On HTTP 429, sleeps 60s and retries once; on second failure, logs and skips.
    """
    dates = _twii_trading_dates(end_date, days)
    written = 0
    for d in dates:
        path = os.path.join(cache_dir, f"{d}.json")
        if os.path.exists(path):
            continue
        api_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        try:
            stocks = fetch_universe_one_day(api_date, finmind_token)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower():
                if verbose:
                    print(f"[backfill] rate-limited at {d}, sleeping 60s", flush=True)
                time.sleep(60)
                try:
                    stocks = fetch_universe_one_day(api_date, finmind_token)
                except Exception as e2:
                    if verbose:
                        print(f"[backfill] still failing at {d}: {e2}", flush=True)
                    continue
            else:
                if verbose:
                    print(f"[backfill] error at {d}: {e}", flush=True)
                continue
        if not stocks:
            if verbose:
                print(f"[backfill] no data for {d} (holiday?)", flush=True)
            continue
        save_universe_day(cache_dir, d, stocks)
        written += 1
        if verbose and written % 10 == 0:
            print(f"[backfill] wrote {written} days so far", flush=True)
        time.sleep(delay_seconds)
    if verbose:
        print(f"[backfill] complete: {written} new files", flush=True)
    return written
```

- [ ] **Step 2: Smoke test backfill (just 5 days for speed)**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import backfill_universe
import os
n = backfill_universe(
    cache_dir='/tmp/market_universe_test',
    finmind_token=os.environ['TOKEN'],
    end_date='20260508',
    days=5,
)
print(f'wrote {n} files')
import os
for f in sorted(os.listdir('/tmp/market_universe_test')):
    sz = os.path.getsize('/tmp/market_universe_test/' + f)
    print(f'  {f} ({sz} bytes)')
" TOKEN=$TOKEN
```

Expected: Writes 4-5 files (skips weekends), each 50-100 KB.

Cleanup:
```bash
rm -rf /tmp/market_universe_test
```

- [ ] **Step 3: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py
git commit -m "market_breadth: backfill_universe with rate-limit handling"
```

---

### Task 6: Institutional + margin aggregate fetchers

**Files:**
- Modify: `concept_momentum/market_breadth.py`

- [ ] **Step 1: Add institutional + margin functions**

Append to `concept_momentum/market_breadth.py`:

```python
def fetch_institutional_one_day(date: str, finmind_token: str) -> dict:
    """Fetch 三大法人 buy-sell aggregate for one day.

    Returns {foreign_yi, trust_yi, dealer_yi, total_yi}  (yi = 億 NTD; +買超/-賣超)
    Raises RuntimeError on API error.
    """
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "date": date,
        "token": finmind_token,
    }
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind 法人 error for {date}: {payload.get('msg', '')}")

    # FinMind returns per-stock per-investor rows. Aggregate net (buy-sell) by
    # investor type into NTD total, then convert to 億.
    foreign = trust = dealer = 0.0
    for row in payload.get("data", []):
        name = row.get("name", "")
        net = float(row.get("buy", 0) - row.get("sell", 0))  # NTD
        # FinMind's name field varies by market — match common substrings
        if "Foreign" in name or "外資" in name:
            foreign += net
        elif "Trust" in name or "投信" in name:
            trust += net
        elif "Dealer" in name or "自營" in name:
            dealer += net
    yi = 1e8
    total = foreign + trust + dealer
    return {
        "foreign_yi": round(foreign / yi, 2),
        "trust_yi": round(trust / yi, 2),
        "dealer_yi": round(dealer / yi, 2),
        "total_yi": round(total / yi, 2),
    }


def fetch_margin_aggregate_one_day(date: str, finmind_token: str) -> dict:
    """Fetch market-wide margin balance aggregate for one day.

    Returns {margin_balance_yi}  (億 NTD — total outstanding margin loan amount)
    """
    params = {
        "dataset": "TaiwanStockTotalMarginPurchaseShortSale",
        "date": date,
        "token": finmind_token,
    }
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind 融資 error for {date}: {payload.get('msg', '')}")

    rows = payload.get("data", [])
    if not rows:
        return {"margin_balance_yi": None}
    # Sum across markets (上市 + 上櫃) for that date
    total_amt = 0.0
    for r in rows:
        # FinMind returns amount in NTD (千元) typically — verify with smoke test
        # Field name may be "MarginPurchaseBalanceAmount" or similar
        for k in ("MarginPurchaseBalanceAmount", "MarginPurchaseTodayBalance",
                 "MarginBalance"):
            if k in r and r[k] is not None:
                total_amt += float(r[k])
                break
    # FinMind 融資金額 typically already in 千元; convert: 千元 → 億 = / 1e5
    # Verify in smoke test; adjust scale if needed.
    return {"margin_balance_yi": round(total_amt / 1e5, 2)}
```

- [ ] **Step 2: Smoke test**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import fetch_institutional_one_day, fetch_margin_aggregate_one_day
import os
inst = fetch_institutional_one_day('2026-05-08', os.environ['TOKEN'])
print('institutional:', inst)
margin = fetch_margin_aggregate_one_day('2026-05-08', os.environ['TOKEN'])
print('margin:', margin)
" TOKEN=$TOKEN
```

Expected: institutional dict with `foreign_yi`, `trust_yi`, `dealer_yi`, `total_yi` all reasonable (e.g., -200 to +200 億). Margin around 2,500-3,500 億 (台股目前水準).

If margin scale is way off (e.g., 10x or 100x wrong), adjust the divisor in `fetch_margin_aggregate_one_day` and re-test.

- [ ] **Step 3: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py
git commit -m "market_breadth: institutional + margin aggregate fetchers"
```

---

### Task 7: `run_today()` orchestrator + index/change

**Files:**
- Modify: `concept_momentum/market_breadth.py`

- [ ] **Step 1: Add orchestrator**

Append to `concept_momentum/market_breadth.py`:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_DIR = os.path.join(HERE, "cache", "market_universe")
BREADTH_DIR = os.path.join(HERE, "cache", "market_breadth")


def _load_taiex() -> list[dict]:
    """Load cached ^TWII rows. Returns [] if missing."""
    path = os.path.join(HERE, "cache", "taiex.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f).get("rows", [])


def _index_change_pct(taiex_rows: list[dict], date: str) -> tuple[float | None, float | None]:
    """Return (close_today, pct_change_vs_prev_trading_day)."""
    rows = sorted(taiex_rows, key=lambda r: r["date"])
    today_idx = next((i for i, r in enumerate(rows) if r["date"] == date), None)
    if today_idx is None or today_idx == 0:
        return None, None
    today = rows[today_idx]["close"]
    prev = rows[today_idx - 1]["close"]
    if prev <= 0:
        return today, None
    return today, round((today - prev) / prev * 100, 2)


def run_today(today_yyyymmdd: str, finmind_token: str,
              backfill_days: int = 200, history_days: int = 60,
              verbose: bool = True) -> dict:
    """Top-level: ensure backfill, compute today's breadth row, save.

    Returns the breadth row dict for today.
    """
    os.makedirs(UNIVERSE_DIR, exist_ok=True)
    os.makedirs(BREADTH_DIR, exist_ok=True)

    # 1. Ensure universe backfill
    if verbose:
        print(f"[market_breadth] checking universe cache up to {today_yyyymmdd}", flush=True)
    backfill_universe(UNIVERSE_DIR, finmind_token, today_yyyymmdd,
                      days=backfill_days, verbose=verbose)

    # 2. Compute today's breadth
    history = load_universe_history(UNIVERSE_DIR, today_yyyymmdd, days=210)
    breadth = compute_breadth_for_day(history)

    # 3. Index level + change
    taiex_rows = _load_taiex()
    close, change_pct = _index_change_pct(taiex_rows, today_yyyymmdd)

    # 4. Institutional + margin (today only — no per-day backfill needed for these
    #    because rendering only shows the last 60 days from the per-day cache)
    api_date = f"{today_yyyymmdd[:4]}-{today_yyyymmdd[4:6]}-{today_yyyymmdd[6:8]}"
    try:
        inst = fetch_institutional_one_day(api_date, finmind_token)
    except Exception as e:
        if verbose: print(f"[market_breadth] inst error: {e}", flush=True)
        inst = {"foreign_yi": None, "trust_yi": None, "dealer_yi": None, "total_yi": None}
    try:
        margin = fetch_margin_aggregate_one_day(api_date, finmind_token)
    except Exception as e:
        if verbose: print(f"[market_breadth] margin error: {e}", flush=True)
        margin = {"margin_balance_yi": None}

    # 5. Compute margin delta vs yesterday
    margin_delta = None
    if margin["margin_balance_yi"] is not None:
        prev_files = sorted(f for f in os.listdir(BREADTH_DIR)
                            if f.endswith(".json") and f[:8] < today_yyyymmdd)
        if prev_files:
            with open(os.path.join(BREADTH_DIR, prev_files[-1])) as f:
                prev = json.load(f)
            prev_balance = prev.get("margin_balance_yi")
            if prev_balance is not None:
                margin_delta = round(margin["margin_balance_yi"] - prev_balance, 2)

    row = {
        "date": today_yyyymmdd,
        "twii_close": close,
        "twii_change_pct": change_pct,
        **breadth,
        **inst,
        **margin,
        "margin_delta_yi": margin_delta,
    }

    # 6. Save
    out_path = os.path.join(BREADTH_DIR, f"{today_yyyymmdd}.json")
    with open(out_path, "w") as f:
        json.dump(row, f, ensure_ascii=False)
    if verbose:
        print(f"[market_breadth] wrote {out_path}", flush=True)

    return row
```

- [ ] **Step 2: Smoke test orchestrator (limit backfill to 30 days for speed)**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import run_today
import os
row = run_today('20260508', os.environ['TOKEN'], backfill_days=30)
import json
print(json.dumps(row, indent=2, ensure_ascii=False))
" TOKEN=$TOKEN
```

Expected: A single row dict printed. `pct_above_20ma` populated; `pct_above_200ma` likely None (only 30 days of universe history). 法人 + 融資 fields populated unless market closed.

- [ ] **Step 3: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth.py
git commit -m "market_breadth: run_today orchestrator with backfill + delta"
```

---

### Task 8: HTML renderer (TDD)

**Files:**
- Create: `concept_momentum/market_breadth_renderer.py`
- Modify: `concept_momentum/tests/test_market_breadth.py`

- [ ] **Step 1: Write failing test**

Append to `concept_momentum/tests/test_market_breadth.py`:

```python
class TestRenderTable(unittest.TestCase):
    def test_render_basic_row(self):
        from concept_momentum.market_breadth_renderer import render_table
        rows = [{
            "date": "20260508",
            "twii_close": 31840.5,
            "twii_change_pct": 1.23,
            "pct_above_20ma": 67.5, "pct_above_50ma": 54.2, "pct_above_200ma": 71.0,
            "new_high_200d": 32,
            "foreign_yi": 45.20, "trust_yi": -3.50, "dealer_yi": 8.10, "total_yi": 49.80,
            "margin_balance_yi": 2894, "margin_delta_yi": 12.30,
        }]
        html = render_table(rows)
        # Date format: 2026/05/08
        self.assertIn("2026/05/08", html)
        # Index with comma
        self.assertIn("31,840", html)
        # Pos color on +1.23%
        self.assertIn('class="pos">+1.23%', html)
        # Neg color on -3.50
        self.assertIn('class="neg">-3.50', html)

    def test_render_missing_cells_show_dash(self):
        from concept_momentum.market_breadth_renderer import render_table
        rows = [{
            "date": "20260508",
            "twii_close": None, "twii_change_pct": None,
            "pct_above_20ma": None, "pct_above_50ma": None, "pct_above_200ma": None,
            "new_high_200d": None,
            "foreign_yi": None, "trust_yi": None, "dealer_yi": None, "total_yi": None,
            "margin_balance_yi": None, "margin_delta_yi": None,
        }]
        html = render_table(rows)
        self.assertIn("—", html)  # em-dash

    def test_render_empty_shows_message(self):
        from concept_momentum.market_breadth_renderer import render_table
        html = render_table([])
        self.assertIn("目前尚無數據", html)
        self.assertNotIn("<table", html)  # no broken table

    def test_render_descending_order(self):
        from concept_momentum.market_breadth_renderer import render_table
        rows = [
            {"date": "20260506", "twii_close": 100, "twii_change_pct": 0,
             "pct_above_20ma": 0, "pct_above_50ma": 0, "pct_above_200ma": 0,
             "new_high_200d": 0, "foreign_yi": 0, "trust_yi": 0, "dealer_yi": 0,
             "total_yi": 0, "margin_balance_yi": 0, "margin_delta_yi": 0},
            {"date": "20260508", "twii_close": 200, "twii_change_pct": 0,
             "pct_above_20ma": 0, "pct_above_50ma": 0, "pct_above_200ma": 0,
             "new_high_200d": 0, "foreign_yi": 0, "trust_yi": 0, "dealer_yi": 0,
             "total_yi": 0, "margin_balance_yi": 0, "margin_delta_yi": 0},
        ]
        html = render_table(rows)
        # 5/8 should appear before 5/6 in HTML (descending)
        self.assertLess(html.index("2026/05/08"), html.index("2026/05/06"))
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth.TestRenderTable -v
```

Expected: `ImportError: cannot import name 'render_table'`.

- [ ] **Step 3: Implement renderer**

Create `concept_momentum/market_breadth_renderer.py`:

```python
"""HTML table renderer for the market breadth tab.

Pure function: takes list-of-dict rows, returns HTML string. No I/O.
"""

DASH = "—"  # em-dash for missing cells


def _fmt_int(v) -> str:
    if v is None:
        return DASH
    return f"{int(round(v)):,}"


def _fmt_pct(v, sign: bool = False) -> str:
    if v is None:
        return DASH
    if sign:
        return f"{v:+.2f}%"
    return f"{v:.1f}%"


def _fmt_yi(v, sign: bool = True) -> str:
    if v is None:
        return DASH
    if sign:
        return f"{v:+.2f}"
    return f"{v:,.0f}"


def _color_class(v) -> str:
    """Return 'pos' if v>0, 'neg' if v<0, '' otherwise."""
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def render_table(rows: list[dict]) -> str:
    """Render rows (any order) as descending-by-date HTML table.

    rows = [{date, twii_close, twii_change_pct, pct_above_20ma, ..., margin_delta_yi}]

    Per AC: empty list returns friendly message, no <table> element.
    """
    if not rows:
        return ('<p class="empty-state" style="text-align:center; padding: 40px; '
                'color: #888;">目前尚無數據，請稍後再試</p>')

    sorted_rows = sorted(rows, key=lambda r: r["date"], reverse=True)

    parts = ['<div class="table-scroll" style="overflow-x:auto;">']
    parts.append('<table class="market-breadth">')
    parts.append('<thead><tr>'
                 '<th>日期</th><th>加權指數</th><th>漲跌幅%</th>'
                 '<th>&gt;20MA%</th><th>&gt;50MA%</th><th>&gt;200MA%</th>'
                 '<th>200日新高</th>'
                 '<th>外資(億)</th><th>投信(億)</th><th>自營(億)</th><th>法人合計(億)</th>'
                 '<th>融資(億)</th><th>融資增減(億)</th>'
                 '</tr></thead>')
    parts.append('<tbody>')

    for r in sorted_rows:
        chg_cls = _color_class(r["twii_change_pct"])
        f_cls = _color_class(r["foreign_yi"])
        t_cls = _color_class(r["trust_yi"])
        d_cls = _color_class(r["dealer_yi"])
        tot_cls = _color_class(r["total_yi"])
        md_cls = _color_class(r["margin_delta_yi"])

        parts.append(
            '<tr>'
            f'<td>{_fmt_date(r["date"])}</td>'
            f'<td>{_fmt_int(r["twii_close"])}</td>'
            f'<td class="{chg_cls}">{_fmt_pct(r["twii_change_pct"], sign=True)}</td>'
            f'<td>{_fmt_pct(r["pct_above_20ma"])}</td>'
            f'<td>{_fmt_pct(r["pct_above_50ma"])}</td>'
            f'<td>{_fmt_pct(r["pct_above_200ma"])}</td>'
            f'<td>{_fmt_int(r["new_high_200d"])}</td>'
            f'<td class="{f_cls}">{_fmt_yi(r["foreign_yi"])}</td>'
            f'<td class="{t_cls}">{_fmt_yi(r["trust_yi"])}</td>'
            f'<td class="{d_cls}">{_fmt_yi(r["dealer_yi"])}</td>'
            f'<td class="{tot_cls}">{_fmt_yi(r["total_yi"])}</td>'
            f'<td>{_fmt_yi(r["margin_balance_yi"], sign=False)}</td>'
            f'<td class="{md_cls}">{_fmt_yi(r["margin_delta_yi"])}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_market_breadth -v
```

Expected: All tests PASS (placeholder + 4 compute + 2 cache + 4 render = 11 total).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/market_breadth_renderer.py concept_momentum/tests/test_market_breadth.py
git commit -m "market_breadth: HTML table renderer (TDD)"
```

---

### Task 9: Inject new tab into dashboard.html via concept_charts.py

**Files:**
- Modify: `concept_momentum/concept_charts.py:188-330` (around `generate_html`)

- [ ] **Step 1: Find the tab list in dashboard.html template**

```bash
grep -n 'class="tab"' /home/kun/project/tw_stock_tools/concept_momentum/concept_charts.py | head -10
```

Expected: Lines defining the tab buttons inside generate_html.

- [ ] **Step 2: Modify generate_html signature and tab injection**

Open `concept_momentum/concept_charts.py`. Find the `generate_html` function (`def generate_html(results, taiex_rows, target_date)`). Modify in 3 places:

(a) **Add new parameter** with default for backwards compat:

Replace:
```python
def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str) -> str:
```

With:
```python
def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str,
                  breadth_table_html: str = "") -> str:
```

(b) **Inject tab button** at the start of the tabs list. Search for the line that starts the tabs section (e.g., `<div class="tabs">`). Add a new tab button as the FIRST tab and shift `.active` class to it:

Find a block like (the exact strings depend on existing code — adapt):
```python
tabs_html = '''
<div class="tabs">
  <div class="tab active" onclick="showTab('snapshot')">📊 今日快照</div>
  ...
'''
```

Change to:
```python
tabs_html = '''
<div class="tabs">
  <div class="tab active" onclick="showTab('breadth')">📊 大盤寬度</div>
  <div class="tab" onclick="showTab('snapshot')">🔥 概念熱力</div>
  ...
'''
```

Also remove `active` from whichever tab previously had it (so only breadth is default-active).

(c) **Inject tab content** at the start of tab-content sections:

Add after the `<div class="tabs">` block, before the existing `<div class="tab-content active" id="snapshot">`:

```python
breadth_section = f'''
<div class="tab-content active" id="breadth">
  <h2>📊 大盤寬度（最近 60 個交易日）</h2>
  <p class="meta">寬度池 = 上市+上櫃 普通股 4 位代號 (~1,700 檔) | 紅 = 漲/買超 / 綠 = 跌/賣超 / 缺值 = —</p>
  {breadth_table_html}
</div>
'''
```

And remove `active` class from the previously-first tab content. Insert `breadth_section` into the page body before the existing tab-contents.

> **Implementation tip:** Read the full `generate_html` first to identify the exact strings. Use search-and-replace for the `active` class moves to ensure exactly one tab/content is active.

- [ ] **Step 3: Smoke test the modified function**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -c "
import json
from concept_momentum.concept_charts import generate_html
from concept_momentum.market_breadth_renderer import render_table

# Mock data — 1 row for sanity
sample = [{
    'date': '20260508', 'twii_close': 31840, 'twii_change_pct': 1.23,
    'pct_above_20ma': 67.5, 'pct_above_50ma': 54.2, 'pct_above_200ma': 71.0,
    'new_high_200d': 32,
    'foreign_yi': 45.20, 'trust_yi': -3.50, 'dealer_yi': 8.10, 'total_yi': 49.80,
    'margin_balance_yi': 2894, 'margin_delta_yi': 12.30,
}]
breadth_html = render_table(sample)

# Need real concept results + taiex for generate_html
import os
HERE = '/home/kun/project/tw_stock_tools/concept_momentum'
with open(os.path.join(HERE, 'cache', 'results', sorted(os.listdir(os.path.join(HERE, 'cache', 'results')))[-1])) as f:
    results = json.load(f)
with open(os.path.join(HERE, 'cache', 'taiex.json')) as f:
    taiex = json.load(f)['rows']

html_path = generate_html(results, taiex, '2026-05-10', breadth_table_html=breadth_html)
print(f'wrote: {html_path}')
print(f'size: {os.path.getsize(html_path)} bytes')

# Quick check that breadth content made it in
with open(html_path) as f:
    body = f.read()
assert '大盤寬度' in body, 'breadth title missing'
assert '31,840' in body, 'breadth row missing'
print('OK: breadth tab rendered')
"
```

Expected: Prints written path, OK message. If "breadth title missing" → tab injection failed; revisit Step 2.

- [ ] **Step 4: Visual eyeball check**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 concept_momentum/app.py --port 5001 &
sleep 2
curl -s http://localhost:5001/ | head -100
kill %1 2>/dev/null
```

Expected: HTML output containing the breadth table at top, and the original concept tabs still listed.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/concept_charts.py
git commit -m "concept_charts: inject 大盤寬度 tab as first/default-active in dashboard"
```

---

### Task 10: Hook market_breadth.run_today() into run_daily.py

**Files:**
- Modify: `concept_momentum/run_daily.py`

- [ ] **Step 1: Add imports + call**

Open `concept_momentum/run_daily.py`. Find existing imports:

```python
from rerating_detector import compute_rerating, format_rerating_report
from business_drift_detector import detect_drift, format_drift_report
```

Add after them:

```python
from market_breadth import run_today as run_market_breadth, load_universe_history
from market_breadth import BREADTH_DIR
from market_breadth_renderer import render_table
```

Find the line:
```python
html_path = generate_html(results, taiex, target_date)
```

Replace with:
```python
# Market breadth — fetch + compute + render
target_yyyymmdd = datetime.now().strftime("%Y%m%d")
finmind_token = os.environ.get("FINMIND_TOKEN", "")
breadth_html = ""
if finmind_token:
    print("計算大盤寬度...", file=sys.stderr)
    try:
        run_market_breadth(target_yyyymmdd, finmind_token, verbose=True)
    except Exception as e:
        print(f"[WARN] market_breadth: {e}", file=sys.stderr)
    # Load last 60 breadth rows for table
    if os.path.isdir(BREADTH_DIR):
        import json
        files = sorted(f for f in os.listdir(BREADTH_DIR) if f.endswith(".json"))[-60:]
        rows = []
        for fname in files:
            with open(os.path.join(BREADTH_DIR, fname)) as f:
                rows.append(json.load(f))
        breadth_html = render_table(rows)

html_path = generate_html(results, taiex, target_date, breadth_table_html=breadth_html)
```

- [ ] **Step 2: Smoke test full flow with --skip-fetch**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 concept_momentum/run_daily.py --skip-fetch 2>&1 | tail -30
```

Expected: Sees `計算大盤寬度...` message and existing concept output. dashboard.html written.

- [ ] **Step 3: Verify dashboard renders**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 concept_momentum/app.py --port 5002 &
sleep 2
curl -s http://localhost:5002/ | grep -E "大盤寬度|breadth" | head -5
kill %1 2>/dev/null
```

Expected: Sees breadth-related HTML lines.

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/run_daily.py
git commit -m "run_daily: integrate market_breadth into daily 17:00 run"
```

---

### Task 11: Initial 200-day backfill (one-time)

**Files:** none (data only)

- [ ] **Step 1: Run backfill in background**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import backfill_universe, UNIVERSE_DIR
import os
n = backfill_universe(UNIVERSE_DIR, os.environ['TOKEN'], '20260510', days=200, verbose=True)
print(f'Total written: {n}')
" TOKEN=$TOKEN 2>&1 | tee /tmp/backfill.log
```

Expected: Prints progress every 10 days. Final count ~140-180 (200 calendar - weekends - holidays). Total time ~3-5 min.

- [ ] **Step 2: Verify cache size & file count**

```bash
ls /home/kun/project/tw_stock_tools/concept_momentum/cache/market_universe/ | wc -l
du -sh /home/kun/project/tw_stock_tools/concept_momentum/cache/market_universe/
```

Expected: ~140-180 files, total ~10-20 MB.

- [ ] **Step 3: Recompute breadth for last 60 days using full history**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  /usr/bin/python3 -c "
from concept_momentum.market_breadth import run_today, _twii_trading_dates
import os
# Recompute last 60 trading days now that backfill is complete
dates = _twii_trading_dates('20260510', 60)
for d in dates:
    print(f'computing {d}...')
    try:
        run_today(d, os.environ['TOKEN'], backfill_days=200, verbose=False)
    except Exception as e:
        print(f'  error: {e}')
print('done')
" TOKEN=$TOKEN
```

Expected: Iterates through 60 dates, each adding/refreshing `cache/market_breadth/{d}.json`. Takes ~3-5 min (4 FinMind calls/day × 60 days).

- [ ] **Step 4: Sanity check breadth values**

```bash
ls /home/kun/project/tw_stock_tools/concept_momentum/cache/market_breadth/ | wc -l
/usr/bin/python3 -c "
import json, os
d = '/home/kun/project/tw_stock_tools/concept_momentum/cache/market_breadth'
files = sorted(os.listdir(d))[-3:]
for f in files:
    with open(os.path.join(d, f)) as fh:
        print(json.dumps(json.load(fh), ensure_ascii=False))
"
```

Expected: 60 breadth files. Last 3 rows show all fields populated with reasonable values (>20MA% in 30-90 range, 法人 in -200 to +200 億).

- [ ] **Step 5: Regenerate dashboard with full history**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 concept_momentum/run_daily.py --skip-fetch 2>&1 | tail -5
```

- [ ] **Step 6: Open dashboard and verify**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 concept_momentum/app.py --port 5003 &
sleep 2
curl -s http://localhost:5003/ -o /tmp/dashboard.html
kill %1 2>/dev/null
grep -c "<tr>" /tmp/dashboard.html
```

Expected: `<tr>` count >= 60 (one row per day) plus a few thead/concept rows.

- [ ] **Step 7: Visual confirmation via Telegram**

Notify user that dashboard is ready at `http://<wsl-ip>:5000/` (his existing concept_momentum URL) and to check the new tab. No commit needed (data only).

---

### Task 12: Documentation + memory update

**Files:**
- Modify: `README.md` § 11
- Modify: `concept_momentum/README.md`
- Create: `~/.claude/projects/-home-kun/memory/reference_market_breadth_dashboard.md`
- Modify: `~/.claude/projects/-home-kun/memory/MEMORY.md`

- [ ] **Step 1: Update top-level README § 11**

In `README.md`, find the section that starts `## 11. concept_momentum/ — 族群熱力 (Theme Heatmap)`. Add after the line about Snapshot PNG/Trend PNG/4 messages:

```markdown
- **大盤寬度 (Market Breadth)**：dashboard.html 最上方分頁，13 欄 × 60 個交易日。寬度池 = 上市+上櫃 普通股 4 位代號 (~1,700 檔)。包含加權指數 / 漲跌幅 / 股價>20-50-200MA% / 200日新高 / 三大法人 (拆 4 欄) / 融資餘額 + 增減
- **快取**：`concept_momentum/cache/market_universe/{date}.json` (全市場日 OHLC) + `concept_momentum/cache/market_breadth/{date}.json` (計算結果)，皆 gitignored
```

- [ ] **Step 2: Update concept_momentum/README.md**

Find a logical place (likely near the dashboard.html description) in `concept_momentum/README.md` and add a section:

```markdown
## 大盤寬度看板 (Market Breadth)

每日 17:00 cron 完成概念分析後，自動跑 `market_breadth.run_today()`，產生 13 欄資料：

| 欄位 | 說明 | 來源 |
|------|------|------|
| 日期 | 交易日 | TWSE/TPEx |
| 加權指數 | ^TWII 收盤 | Yahoo (cached) |
| 漲跌幅% | 大盤日漲跌 | 計算 |
| 股價>20MA% | 收盤站上月線比例 | FinMind 全市場 |
| 股價>50MA% | 站上季線 | 同上 |
| 股價>200MA% | 站上年線 | 同上 |
| 200日新高數 | 創 200 日新高個股數 | 同上 |
| 外資 / 投信 / 自營 (億) | 三大法人各別淨買賣超 | FinMind 法人 |
| 法人合計 (億) | 三者加總 | 計算 |
| 融資 (億) | 大盤融資使用金額 | FinMind |
| 融資增減 (億) | 日比變化 | 計算 |

**寬度池**: 上市+上櫃 4 位數代號 (~1,700 檔)，排除 ETF/REITs/權證。
**首次部署需 backfill 200 天**: `backfill_universe()` 會自動執行 (~3-5 分鐘)。
```

- [ ] **Step 3: Create memory file**

Write `~/.claude/projects/-home-kun/memory/reference_market_breadth_dashboard.md`:

```markdown
---
name: 大盤寬度看板 (Market Breadth)
description: concept_momentum dashboard 最上方新分頁，13 欄 × 60 天的大盤+市場寬度數據表，含 ^TWII / >NMA% / 200新高 / 三大法人(4欄) / 融資餘額+增減
type: reference
---

dashboard.html 最上方第一個分頁「📊 大盤寬度」於 2026-05-10 加入，每日 17:00 cron 自動更新。

**13 欄定義**:
1. 日期、2. 加權指數、3. 漲跌幅%
4-6. 股價>20MA% / >50MA% / >200MA%
7. 200日新高數 (收盤價)
8-11. 外資 / 投信 / 自營 / 法人合計 (億)
12-13. 融資 (億) / 融資增減 (億)

**寬度池**: 上市+上櫃 普通股 4 位代號 (~1,700 檔)，排除 ETF/REITs/權證。

**檔案**:
- 計算: `concept_momentum/market_breadth.py`
- 渲染: `concept_momentum/market_breadth_renderer.py`
- 注入點: `concept_momentum/concept_charts.py:generate_html()` 的 `breadth_table_html` 參數

**Cache** (gitignored):
- `concept_momentum/cache/market_universe/{YYYYMMDD}.json` — 全市場當日收盤
- `concept_momentum/cache/market_breadth/{YYYYMMDD}.json` — 計算結果 (1 行 = 1 天)

**設計文件**: `docs/superpowers/specs/2026-05-10-market-breadth-dashboard-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-10-market-breadth-dashboard.md`

**判讀提示**:
- >20MA% < 30 = 過度悲觀（可能反彈）
- >20MA% > 80 = 過度樂觀（可能修正）
- 200新高數 < 20 + 法人合計 連續負 = 弱市
- 融資增減連 5 日正 + >50MA% < 50 = 散戶逆勢加碼，警戒
```

- [ ] **Step 4: Update MEMORY.md index**

Append to `~/.claude/projects/-home-kun/memory/MEMORY.md`:

```
- [大盤寬度看板](reference_market_breadth_dashboard.md) — concept_momentum dashboard 最上方分頁，13 欄 × 60 天大盤+市場寬度數據；自製功能於 2026-05-10 加入
```

- [ ] **Step 5: Commit + push**

```bash
cd ~/project/tw_stock_tools && git add README.md concept_momentum/README.md
git commit -m "README: document 大盤寬度 (market breadth) dashboard tab"
git push
```

(Memory files are not in the git repo — they live in ~/.claude/.)

---

## Self-Review

**Spec coverage:**
- §3 columns → Tasks 7 (orchestrator builds row), 8 (renderer formats columns)
- §3.1 formulas → Task 2 (compute_breadth_for_day matches formulas exactly)
- §4 sources → Tasks 4 (universe), 6 (institutional + margin), 7 (index from cached taiex)
- §5 architecture → Task layout matches file map (market_breadth.py + market_breadth_renderer.py + injection)
- §6 data flow → Task 10 wires `run_daily.py` → `run_today` → `render_table` → `generate_html`
- §7 caching → Tasks 4 (universe save), 5 (backfill), 7 (breadth save), 11 (initial backfill)
- §8 UI → Task 9 (tab injection), Task 8 (table HTML)
- §9 edge cases → Task 8 tests cover empty + missing cells; Task 5 covers 429 retry
- §10 testing → Tasks 2/3/8 are TDD with explicit AC1/2/3 coverage
- §11 perf → Task 11 runs full backfill; <30s daily target verified by Task 7 smoke test
- §12 docs → Task 12
- §13 rollout → Task ordering matches steps 1-9 in spec

**No placeholders found** in plan text. All code blocks contain concrete implementations.

**Type consistency:**
- `compute_breadth_for_day` returns `pct_above_20ma`, `pct_above_50ma`, `pct_above_200ma`, `new_high_200d` — same field names used in Task 7 (`run_today` row) and Task 8 (renderer).
- `fetch_institutional_one_day` returns `foreign_yi`, `trust_yi`, `dealer_yi`, `total_yi` — matched in Task 7 spread + Task 8 renderer.
- `fetch_margin_aggregate_one_day` returns `margin_balance_yi` — matched in Task 7 + 8.
- `margin_delta_yi` computed in Task 7, consumed in Task 8.

**Edge cases preserved:** all None handling propagates from compute → renderer (renderer prints `—`).

---

Plan complete and saved to `docs/superpowers/plans/2026-05-10-market-breadth-dashboard.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
