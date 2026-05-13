# Chip Price Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New CLI tool `tw_chip_price.py` + `/chip-price` skill that fetches a single stock's TWSE BSR (買賣日報表) preserving per-price detail, then produces a Top 10 cell + 3-stage + per-broker fingerprint Telegram-friendly report.

**Architecture:** Add a parallel `_parse_bsr_csv_with_prices()` parser + `fetch_bsr_with_prices()` fetcher in `bsr_scraper.py` (existing aggregate path stays). New `tw_chip_price.py` orchestrates fetch → analyze → format → optional Telegram push. Skill at `~/.claude/skills/chip-price/SKILL.md` triggers on multiple phrase variants and the slash form.

**Tech Stack:** Python 3 stdlib only (`json`, `argparse`, `urllib`, `unittest`). Existing `requests` + `ddddocr` for BSR CAPTCHA already in repo. No new pip deps.

**Spec:** `docs/superpowers/specs/2026-05-13-chip-price-analysis-design.md`

---

## File Structure

**Create:**
- `tw_chip_price.py` — CLI entry: fetch + analyze + format + telegram
- `~/.claude/skills/chip-price/SKILL.md` — skill definition (triggers + run instructions)
- `tests/test_chip_price.py` — unit tests for pure functions (parser + stage + fingerprint)

**Modify:**
- `bsr_scraper.py` — add `_parse_bsr_csv_with_prices()` (preserves price column) + `fetch_bsr_with_prices()` (parallel to existing `fetch_bsr`)
- `bsr_cache/.gitignore` (implicit via existing `bsr_cache/`) — already covered; per-price files use `*_prices.json` suffix
- `README.md` — note new tool in tool list
- `~/.claude/projects/-home-kun/memory/MEMORY.md` — add reference for the new skill
- Create memory: `reference_chip_price_skill.md`

**Run-time data:**
- `bsr_cache/{code}_{date}_prices.json` — per-price BSR cache (gitignored by existing `bsr_cache/`)

---

## Testing Approach

Use stdlib `unittest`. Tests live in top-level `tests/` (same as `tests/test_finmind_client.py`). Pure-function tests:
- CSV parser (mock CSV string in → list of price rows out)
- Stage breakdown (mock rows + price range → 3 zone aggregates)
- Per-broker fingerprint (mock rows → top brokers + price summary)

Network-dependent tests (real TWSE scrape) are smoke tests, not unit tests. Run end-to-end against 2313 once after implementation.

Run all unit tests:
```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest discover -s tests -v
```

---

### Task 1: Scaffold tests + price-row parser (TDD)

**Files:**
- Modify: `bsr_scraper.py` — add `_parse_bsr_csv_with_prices()`
- Create: `tests/test_chip_price.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chip_price.py`:

```python
"""Unit tests for chip-price analysis (parser, stage, fingerprint)."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from bsr_scraper import _parse_bsr_csv_with_prices


# Realistic CSV slice — left/right two-record pairs, broker like "1020合　　庫"
SAMPLE_CSV = """\
證券代號 ,2313,證券名稱 ,華通
99/05/12,日期
序,證券商,成交單價,買進股數,賣出股數,,序,證券商,成交單價,買進股數,賣出股數
1,1020合　　庫,249.00,5000,0,,2,1020合　　庫,251.00,0,1000
3,1020合　　庫,251.50,0,1000,,4,8888國泰敦南,264.00,0,3100
"""


class TestParseBsrCsvWithPrices(unittest.TestCase):
    def test_basic_two_pair_row(self):
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        # 4 records expected from 2 lines × 2 pairs
        self.assertEqual(len(rows), 4)

    def test_first_row_shape(self):
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        r = rows[0]
        self.assertEqual(r["broker_id"], "1020")
        self.assertEqual(r["broker_name"], "合 庫")  # double-width space collapsed
        self.assertEqual(r["price"], 249.0)
        self.assertEqual(r["buy"], 5000)
        self.assertEqual(r["sell"], 0)

    def test_skips_blank_broker(self):
        # Add a row with empty broker column — should be dropped
        csv = SAMPLE_CSV + "5,,255.00,1000,0,,6,1020合　　庫,256.00,2000,0\n"
        rows = _parse_bsr_csv_with_prices(csv)
        # Blank pair skipped, only the right side of last line counted
        broker_ids = [r["broker_id"] for r in rows]
        self.assertNotIn("", broker_ids)

    def test_broker_id_extraction(self):
        # broker like "8888國泰敦南" — id is first 4 chars
        rows = _parse_bsr_csv_with_prices(SAMPLE_CSV)
        last = [r for r in rows if r["broker_id"] == "8888"]
        self.assertEqual(len(last), 1)
        self.assertEqual(last[0]["broker_name"], "國泰敦南")
        self.assertEqual(last[0]["price"], 264.0)
        self.assertEqual(last[0]["sell"], 3100)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name '_parse_bsr_csv_with_prices'`

- [ ] **Step 3: Implement `_parse_bsr_csv_with_prices` in `bsr_scraper.py`**

Open `/home/kun/project/tw_stock_tools/bsr_scraper.py`. After the existing `_parse_bsr_csv` function (ends around line 109), add:

```python
def _parse_bsr_csv_with_prices(text: str) -> list[dict]:
    """Parse the BSR CSV into per-(broker, price) rows.

    Returns list of {broker_id, broker_name, price (float),
                     buy (int shares), sell (int shares)}.
    Companion to _parse_bsr_csv which aggregates over price; this one preserves
    every (broker, price) cell for intraday price-vs-broker analysis.
    """
    out = []
    lines = text.split("\n")
    # Header is lines 0-2 (title, stock code/name, columns)
    for line in lines[3:]:
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        # CSV layout: seq, broker, price, buy, sell, ,, seq, broker, price, buy, sell
        for offset in (0, 6):
            if len(parts) < offset + 5:
                continue
            broker = parts[offset + 1]
            if not broker:
                continue
            try:
                price = float(parts[offset + 2])
                buy = int(parts[offset + 3])
                sell = int(parts[offset + 4])
            except (ValueError, IndexError):
                continue
            broker = broker.replace("　", " ").strip()
            # broker like "1020合 庫" — first 4-6 alphanumeric chars are id, rest is name
            m = re.match(r"^([A-Z0-9]{4,6})\s*(.+)$", broker)
            if m:
                broker_id = m.group(1)
                broker_name = m.group(2).strip()
            else:
                broker_id = broker[:4]
                broker_name = broker[4:].strip()
            out.append({
                "broker_id": broker_id,
                "broker_name": broker_name,
                "price": price,
                "buy": buy,
                "sell": sell,
            })
    return out
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: `Ran 4 tests in <1s\nOK`

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add bsr_scraper.py tests/test_chip_price.py
git commit -m "bsr_scraper: add _parse_bsr_csv_with_prices for per-price detail"
```

---

### Task 2: `fetch_bsr_with_prices` wrapper (network smoke test)

**Files:**
- Modify: `bsr_scraper.py` — add `fetch_bsr_with_prices()` wrapper

- [ ] **Step 1: Add the fetch wrapper**

Open `bsr_scraper.py`. After the existing `fetch_bsr()` function (ends around line 205), add:

```python
def fetch_bsr_with_prices(stock_code: str, max_attempts: int = 10,
                          session=None) -> dict:
    """Fetch and parse BSR data preserving per-(broker, price) rows.

    Same overall flow as fetch_bsr() but uses _parse_bsr_csv_with_prices()
    so callers get the price-level detail. Returns dict with:
      {date, stock_code, rows: [...per-price rows...],
       total_buy_shares, total_sell_shares}
    Returns {} on failure after max_attempts.
    """
    import requests
    if session is None:
        session = requests.Session()
    headers = {"User-Agent": UA}
    ocr = _get_ocr()

    for attempt in range(max_attempts):
        try:
            r = session.get(BSR_URL, headers=headers, timeout=30)
            form = _parse_form(r.text)
            if not form.get("__VIEWSTATE"):
                time.sleep(1)
                continue

            img_r = session.get(form["_captcha_url"], headers=headers, timeout=15)
            if img_r.status_code != 200 or not _is_valid_image(img_r.content):
                time.sleep(0.5)
                continue

            try:
                solved = ocr.classification(img_r.content)
            except Exception:
                time.sleep(0.5)
                continue
            if not solved or len(solved) != 5:
                time.sleep(0.3)
                continue

            data = {
                "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
                "__VIEWSTATE": form["__VIEWSTATE"],
                "__VIEWSTATEGENERATOR": form["__VIEWSTATEGENERATOR"],
                "__EVENTVALIDATION": form["__EVENTVALIDATION"],
                "RadioButton_Normal": "RadioButton_Normal",
                "TextBox_Stkno": stock_code,
                "CaptchaControl1": solved,
                "btnOK": "查詢",
            }
            r2 = session.post(BSR_URL, data=data, headers=headers, timeout=30,
                              allow_redirects=True)
            if "查無資料" in r2.text:
                return {"date": datetime.now().strftime("%Y%m%d"),
                        "stock_code": stock_code, "rows": [],
                        "total_buy_shares": 0, "total_sell_shares": 0,
                        "no_data": True, "captcha_attempts": attempt + 1}
            if "HyperLink_DownloadCSV" not in r2.text:
                time.sleep(0.3)
                continue
            link_match = re.search(r'href="(bsContent\.aspx\?StkNo=[^"]+)"', r2.text)
            if not link_match:
                continue
            csv_url = BSR_BASE + link_match.group(1).replace("&amp;", "&")
            csv_r = session.get(csv_url, headers=headers, timeout=30)
            if csv_r.status_code != 200:
                continue
            text = csv_r.content.decode("cp950", errors="replace")
            rows = _parse_bsr_csv_with_prices(text)
            if not rows:
                return {}
            total_buy = sum(r["buy"] for r in rows)
            total_sell = sum(r["sell"] for r in rows)
            return {
                "date": datetime.now().strftime("%Y%m%d"),
                "stock_code": stock_code,
                "rows": rows,
                "total_buy_shares": total_buy,
                "total_sell_shares": total_sell,
                "captcha_attempts": attempt + 1,
            }
        except Exception:
            time.sleep(1)
    return {}
```

- [ ] **Step 2: Smoke test against real TWSE**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -c "
from bsr_scraper import fetch_bsr_with_prices
result = fetch_bsr_with_prices('2330')
import json
print('Keys:', list(result.keys()))
print(f'Stock: {result.get(\"stock_code\")} Date: {result.get(\"date\")}')
print(f'Rows: {len(result.get(\"rows\", []))}')
print(f'Total buy/sell: {result.get(\"total_buy_shares\")}/{result.get(\"total_sell_shares\")}')
if result.get('rows'):
    print('First 3 rows:')
    for r in result['rows'][:3]:
        print(f'  {r}')
"
```

Expected: After 1-5 CAPTCHA attempts (each 1-2 sec), returns rows list with hundreds of entries. Sample row like `{'broker_id': '1020', 'broker_name': '合 庫', 'price': 1234.5, 'buy': 5000, 'sell': 0}`. If TWSE returns 查無資料 (e.g., weekend), `rows` is empty and `no_data` is True.

- [ ] **Step 3: Commit**

```bash
cd ~/project/tw_stock_tools && git add bsr_scraper.py
git commit -m "bsr_scraper: add fetch_bsr_with_prices wrapper"
```

---

### Task 3: OHLC fetcher for stage analysis (TDD)

**Files:**
- Create: `tw_chip_price.py` (just the OHLC helper for now)
- Modify: `tests/test_chip_price.py` — append OHLC test

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_price.py`:

```python
class TestOhlcFromFinmind(unittest.TestCase):
    def test_returns_dict_with_required_keys(self):
        from tw_chip_price import get_ohlc
        result = get_ohlc("2330")
        # Real network — skip if no token or bad day
        if not result:
            self.skipTest("No FINMIND_TOKEN or no recent OHLC data")
        for k in ("open", "high", "low", "close"):
            self.assertIn(k, result)
            self.assertGreater(result[k], 0)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price.TestOhlcFromFinmind -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'get_ohlc' from 'tw_chip_price'`

- [ ] **Step 3: Create `tw_chip_price.py` with OHLC helper**

Create `/home/kun/project/tw_stock_tools/tw_chip_price.py`:

```python
#!/usr/bin/env python3
"""Chip-price analysis: per-stock daily BSR with (broker × price) detail.

Usage:
  tw_chip_price.py <code>                # today, force re-fetch BSR
  tw_chip_price.py <code> --date YYYYMMDD  # use cached per-price file
  tw_chip_price.py <code> --telegram     # also push report to TG
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

DEFAULT_CHAT_ID = "-5229750819"


def _get_token() -> str:
    """Read FINMIND_TOKEN from env or crontab."""
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=")[1].split()[0]
    except Exception:
        pass
    return ""


def get_ohlc(stock_code: str, date: str | None = None) -> dict:
    """Fetch OHLC for stage analysis. Uses FinMind TaiwanStockPrice.

    Returns {open, high, low, close} for the most recent trading day at or
    before `date`. Returns {} on failure or no data.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return {}
    target = date or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(target, "%Y%m%d")
    start_dt = end_dt - timedelta(days=10)
    try:
        rows = finmind_client.fetch_stock_price(
            stock_code,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
            token,
        )
    except Exception:
        return {}
    if not rows:
        return {}
    # Pick the row whose date is the target, or the latest available row ≤ target
    target_dash = f"{target[:4]}-{target[4:6]}-{target[6:8]}"
    match = [r for r in rows if r["date"] == target_dash]
    chosen = match[0] if match else rows[-1]
    return {
        "open": float(chosen.get("open", 0)),
        "high": float(chosen.get("max", 0)),
        "low": float(chosen.get("min", 0)),
        "close": float(chosen.get("close", 0)),
    }


if __name__ == "__main__":
    # Placeholder main — full implementation in later task
    parser = argparse.ArgumentParser()
    parser.add_argument("code")
    args = parser.parse_args()
    print(get_ohlc(args.code))
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: 4 parser + 1 OHLC = 5 tests pass (OHLC test may skip if no token).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py tests/test_chip_price.py
git commit -m "chip_price: OHLC helper for stage analysis"
```

---

### Task 4: Stage breakdown pure function (TDD)

**Files:**
- Modify: `tw_chip_price.py` — add `stage_breakdown()` + zone constants
- Modify: `tests/test_chip_price.py` — append stage tests

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_price.py`:

```python
class TestStageBreakdown(unittest.TestCase):
    SAMPLE_ROWS = [
        # Early zone (low quartile): $100-105
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 101.0, "buy": 5000, "sell": 0},
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 102.0, "buy": 0, "sell": 200},
        # Mid zone: $105-115
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 110.0, "buy": 1000, "sell": 0},
        {"broker_id": "C001", "broker_name": "外資C",
         "price": 112.0, "buy": 800, "sell": 0},
        # Late zone (high quartile): $115-120
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 118.0, "buy": 0, "sell": 1500},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 119.0, "buy": 300, "sell": 0},
    ]

    def test_three_zones_partition(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        # Zones: early [100, 105], mid (105, 115], late (115, 120]
        self.assertIn("early", result)
        self.assertIn("mid", result)
        self.assertIn("late", result)

    def test_early_zone_top_buyer(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        early = result["early"]
        # A001 bought 5000 in early; B001 sold 200
        a = [r for r in early if r["broker_id"] == "A001"][0]
        self.assertEqual(a["buy_shares"], 5000)
        self.assertEqual(a["sell_shares"], 0)
        b = [r for r in early if r["broker_id"] == "B001"][0]
        self.assertEqual(b["sell_shares"], 200)

    def test_late_zone_top_seller(self):
        from tw_chip_price import stage_breakdown
        result = stage_breakdown(self.SAMPLE_ROWS, low=100.0, high=120.0)
        late = result["late"]
        # B001 sold 1500 in late; A001 bought 300
        b = [r for r in late if r["broker_id"] == "B001"][0]
        self.assertEqual(b["sell_shares"], 1500)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price.TestStageBreakdown -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'stage_breakdown' from 'tw_chip_price'`

- [ ] **Step 3: Implement `stage_breakdown`**

In `tw_chip_price.py`, before the `if __name__ == "__main__"` block, add:

```python
ZONE_LOW_FRACTION = 0.25
ZONE_HIGH_FRACTION = 0.75


def stage_breakdown(rows: list[dict], low: float, high: float) -> dict:
    """Split rows into 3 price zones and aggregate buy/sell per broker per zone.

    Zones:
      early = [low, low + 0.25 × (high − low)]
      mid   = (low + 0.25 × range, low + 0.75 × range]
      late  = (low + 0.75 × range, high]

    Returns:
      {"early": [{broker_id, broker_name, buy_shares, sell_shares, net_shares}, ...],
       "mid":   [...],
       "late":  [...]}
    Each list sorted by abs(net_shares) descending.
    """
    rng = high - low
    if rng <= 0:
        # Flat price day — everything in mid
        zones = {"early": [], "mid": rows, "late": []}
    else:
        early_max = low + ZONE_LOW_FRACTION * rng
        late_min = low + ZONE_HIGH_FRACTION * rng
        zone_rows = {"early": [], "mid": [], "late": []}
        for r in rows:
            p = r["price"]
            if p <= early_max:
                zone_rows["early"].append(r)
            elif p <= late_min:
                zone_rows["mid"].append(r)
            else:
                zone_rows["late"].append(r)
        zones = zone_rows

    result = {}
    for zone, zrows in zones.items():
        per_broker = {}
        for r in zrows:
            bid = r["broker_id"]
            agg = per_broker.setdefault(bid, {
                "broker_id": bid,
                "broker_name": r["broker_name"],
                "buy_shares": 0,
                "sell_shares": 0,
            })
            agg["buy_shares"] += r["buy"]
            agg["sell_shares"] += r["sell"]
        for a in per_broker.values():
            a["net_shares"] = a["buy_shares"] - a["sell_shares"]
        sorted_list = sorted(per_broker.values(),
                              key=lambda x: -abs(x["net_shares"]))
        result[zone] = sorted_list
    return result
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: parser + OHLC + 3 stage tests = 8 tests total, all pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py tests/test_chip_price.py
git commit -m "chip_price: stage_breakdown 3-zone aggregator (TDD)"
```

---

### Task 5: Per-broker fingerprint (TDD)

**Files:**
- Modify: `tw_chip_price.py` — add `broker_fingerprint()`
- Modify: `tests/test_chip_price.py` — append fingerprint tests

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_price.py`:

```python
class TestBrokerFingerprint(unittest.TestCase):
    ROWS = [
        # 外資A — 累積買在 $100 / $110，少量在 $119
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 100.0, "buy": 5000, "sell": 0},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 110.0, "buy": 3000, "sell": 0},
        {"broker_id": "A001", "broker_name": "外資A",
         "price": 119.0, "buy": 500, "sell": 0},
        # 散戶B — 賣出集中 $118-120
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 118.0, "buy": 0, "sell": 1500},
        {"broker_id": "B001", "broker_name": "散戶B",
         "price": 120.0, "buy": 0, "sell": 800},
    ]

    def test_returns_top_n_brokers(self):
        from tw_chip_price import broker_fingerprint
        result = broker_fingerprint(self.ROWS, top_n=2)
        self.assertEqual(len(result["top_buyers"]), 1)  # only A001 net+
        self.assertEqual(result["top_buyers"][0]["broker_id"], "A001")
        self.assertEqual(len(result["top_sellers"]), 1)  # only B001 net-
        self.assertEqual(result["top_sellers"][0]["broker_id"], "B001")

    def test_top_buyer_price_summary(self):
        from tw_chip_price import broker_fingerprint
        result = broker_fingerprint(self.ROWS, top_n=2)
        a = result["top_buyers"][0]
        # A001: total +8500張, avg cost ≈ (5000×100 + 3000×110 + 500×119) / 8500
        self.assertEqual(a["net_shares"], 8500)
        # Avg cost: (500000 + 330000 + 59500) / 8500 = 105.82
        self.assertAlmostEqual(a["avg_price"], 105.82, places=1)
        self.assertEqual(a["price_range"], (100.0, 119.0))
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price.TestBrokerFingerprint -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `broker_fingerprint`**

In `tw_chip_price.py`, after `stage_breakdown`, add:

```python
def broker_fingerprint(rows: list[dict], top_n: int = 5) -> dict:
    """Per-broker summary: total buy/sell, average price, price range.

    Returns:
      {"top_buyers": [{broker_id, broker_name, buy_shares, sell_shares,
                       net_shares, avg_price, price_range (lo, hi),
                       cells: [...sorted by abs(net) per price...]}, ...],
       "top_sellers": [...same shape, net_shares < 0...]}
    Sorted by abs(net_shares) descending.
    """
    per_broker = {}
    for r in rows:
        bid = r["broker_id"]
        agg = per_broker.setdefault(bid, {
            "broker_id": bid,
            "broker_name": r["broker_name"],
            "buy_shares": 0,
            "sell_shares": 0,
            "cells": [],
            "_buy_value": 0.0,
            "_sell_value": 0.0,
            "_min_price": float("inf"),
            "_max_price": 0.0,
        })
        agg["buy_shares"] += r["buy"]
        agg["sell_shares"] += r["sell"]
        agg["cells"].append({"price": r["price"], "buy": r["buy"], "sell": r["sell"]})
        agg["_buy_value"] += r["price"] * r["buy"]
        agg["_sell_value"] += r["price"] * r["sell"]
        if r["buy"] > 0 or r["sell"] > 0:
            agg["_min_price"] = min(agg["_min_price"], r["price"])
            agg["_max_price"] = max(agg["_max_price"], r["price"])

    for a in per_broker.values():
        a["net_shares"] = a["buy_shares"] - a["sell_shares"]
        total_shares = a["buy_shares"] + a["sell_shares"]
        weighted = a["_buy_value"] + a["_sell_value"]
        a["avg_price"] = round(weighted / total_shares, 2) if total_shares else 0
        a["price_range"] = (
            a["_min_price"] if a["_min_price"] != float("inf") else 0.0,
            a["_max_price"],
        )
        a["cells"].sort(key=lambda c: -(c["buy"] + c["sell"]))
        # drop internal accumulators
        del a["_buy_value"]
        del a["_sell_value"]
        del a["_min_price"]
        del a["_max_price"]

    buyers = [b for b in per_broker.values() if b["net_shares"] > 0]
    sellers = [b for b in per_broker.values() if b["net_shares"] < 0]
    buyers.sort(key=lambda x: -x["net_shares"])
    sellers.sort(key=lambda x: x["net_shares"])
    return {
        "top_buyers": buyers[:top_n],
        "top_sellers": sellers[:top_n],
    }
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: 10 tests total pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py tests/test_chip_price.py
git commit -m "chip_price: broker_fingerprint per-broker price summary (TDD)"
```

---

### Task 6: Top 10 cells helper (TDD)

**Files:**
- Modify: `tw_chip_price.py` — add `top_cells()` + direction-tag helper
- Modify: `tests/test_chip_price.py` — append top-cell tests

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_price.py`:

```python
class TestTopCells(unittest.TestCase):
    ROWS = [
        # Big buy cells at low prices (early)
        {"broker_id": "G", "broker_name": "高盛", "price": 100.0, "buy": 10000, "sell": 0},
        {"broker_id": "G", "broker_name": "高盛", "price": 119.0, "buy": 2000, "sell": 0},
        # Big sell cells at high prices (late)
        {"broker_id": "K", "broker_name": "國泰", "price": 120.0, "buy": 0, "sell": 8000},
        # Small noise
        {"broker_id": "X", "broker_name": "X", "price": 110.0, "buy": 100, "sell": 50},
    ]

    def test_top_cells_sorted_by_abs_volume(self):
        from tw_chip_price import top_cells
        result = top_cells(self.ROWS, top_n=3)
        # Largest cell is 高盛 @100 buy 10000
        self.assertEqual(result[0]["broker_id"], "G")
        self.assertEqual(result[0]["price"], 100.0)
        self.assertEqual(result[0]["volume"], 10000)
        self.assertEqual(result[0]["side"], "buy")

    def test_direction_tag(self):
        from tw_chip_price import top_cells
        # 高盛 buy at $100 (low 25% of [100,120]) → 早盤搶低
        result = top_cells(self.ROWS, top_n=4, low=100.0, high=120.0)
        early_buy = [r for r in result
                     if r["broker_id"] == "G" and r["price"] == 100.0][0]
        self.assertEqual(early_buy["zone"], "early")
        self.assertIn("早盤搶低", early_buy["tag"])
        late_sell = [r for r in result
                     if r["broker_id"] == "K" and r["price"] == 120.0][0]
        self.assertEqual(late_sell["zone"], "late")
        self.assertIn("高檔倒貨", late_sell["tag"])
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price.TestTopCells -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `top_cells`**

In `tw_chip_price.py`, after `broker_fingerprint`, add:

```python
def _zone_and_tag(price: float, side: str, low: float, high: float) -> tuple[str, str]:
    """Return (zone, tag) for a (price, side) cell.

    Zones: early (≤ 25%), mid (25-75%), late (> 75%).
    Tags:
      buy@early → '⬇ 早盤搶低'
      buy@mid   → '↗ 盤中追進'
      buy@late  → '▽ 高檔追進'
      sell@early → '△ 低檔賣壓'
      sell@mid   → '↘ 盤中出脫'
      sell@late  → '⬆ 高檔倒貨'
    Flat day (rng ≤ 0): everything 'mid', tag without zone descriptor.
    """
    rng = high - low
    if rng <= 0:
        zone = "mid"
    else:
        f = (price - low) / rng
        if f <= ZONE_LOW_FRACTION:
            zone = "early"
        elif f <= ZONE_HIGH_FRACTION:
            zone = "mid"
        else:
            zone = "late"
    tags = {
        ("buy", "early"):  "⬇ 早盤搶低",
        ("buy", "mid"):    "↗ 盤中追進",
        ("buy", "late"):   "▽ 高檔追進",
        ("sell", "early"): "△ 低檔賣壓",
        ("sell", "mid"):   "↘ 盤中出脫",
        ("sell", "late"):  "⬆ 高檔倒貨",
    }
    return zone, tags.get((side, zone), "")


def top_cells(rows: list[dict], top_n: int = 10,
               low: float = 0.0, high: float = 0.0) -> list[dict]:
    """Top N (broker, price, side) cells by volume.

    Each row contributes up to 2 cells (one buy, one sell, if both > 0).
    Returns list sorted by volume descending:
      [{broker_id, broker_name, price, side ('buy'|'sell'), volume,
        zone, tag}, ...]
    """
    cells = []
    for r in rows:
        if r["buy"] > 0:
            zone, tag = _zone_and_tag(r["price"], "buy", low, high)
            cells.append({
                "broker_id": r["broker_id"],
                "broker_name": r["broker_name"],
                "price": r["price"],
                "side": "buy",
                "volume": r["buy"],
                "zone": zone,
                "tag": tag,
            })
        if r["sell"] > 0:
            zone, tag = _zone_and_tag(r["price"], "sell", low, high)
            cells.append({
                "broker_id": r["broker_id"],
                "broker_name": r["broker_name"],
                "price": r["price"],
                "side": "sell",
                "volume": r["sell"],
                "zone": zone,
                "tag": tag,
            })
    cells.sort(key=lambda c: -c["volume"])
    return cells[:top_n]
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: 12 tests total pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py tests/test_chip_price.py
git commit -m "chip_price: top_cells + direction tag (TDD)"
```

---

### Task 7: Report formatter (TDD)

**Files:**
- Modify: `tw_chip_price.py` — add `format_report()`
- Modify: `tests/test_chip_price.py` — append format tests

- [ ] **Step 1: Write the failing test**

Append to `tests/test_chip_price.py`:

```python
class TestFormatReport(unittest.TestCase):
    def test_report_includes_header_and_sections(self):
        from tw_chip_price import format_report
        data = {
            "stock_code": "2313",
            "name": "華通",
            "date": "20260512",
            "ohlc": {"open": 246.0, "high": 264.5, "low": 246.0, "close": 260.0},
            "total_buy_shares": 93922000,
            "total_sell_shares": 93922000,
            "top_cells": [
                {"broker_id": "1480", "broker_name": "美商高盛",
                 "price": 246.5, "side": "buy", "volume": 8200000,
                 "zone": "early", "tag": "⬇ 早盤搶低"},
            ],
            "stage": {"early": [], "mid": [], "late": []},
            "fingerprint": {"top_buyers": [], "top_sellers": []},
        }
        report = format_report(data)
        # Header
        self.assertIn("2313", report)
        self.assertIn("華通", report)
        self.assertIn("246.00", report)
        self.assertIn("260.00", report)
        # Top cells section
        self.assertIn("Top", report)
        self.assertIn("8,200", report)  # 8200000 shares / 1000 = 8200 張
        self.assertIn("早盤搶低", report)
        # Section headers
        self.assertIn("三階段", report)
        self.assertIn("價格指紋", report)
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price.TestFormatReport -v 2>&1 | tail -10
```

Expected: `ImportError`.

- [ ] **Step 3: Implement `format_report`**

In `tw_chip_price.py`, after `top_cells`, add:

```python
def _fmt_zhang(shares: int) -> str:
    """股 → 張 with thousands separator (e.g., 8200000 → '8,200')."""
    return f"{shares // 1000:,}"


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def format_report(data: dict) -> str:
    """Render the analysis result as Telegram-friendly text.

    data = {stock_code, name, date, ohlc, total_buy_shares, total_sell_shares,
            top_cells, stage, fingerprint, [optional] notes}
    """
    code = data["stock_code"]
    name = data.get("name", "")
    date = data["date"]
    ohlc = data["ohlc"]
    change_pct = ((ohlc["close"] - ohlc["open"]) / ohlc["open"] * 100
                  if ohlc["open"] > 0 else 0)

    lines = []
    lines.append(f"{code} {name} 籌碼價格分析 ({_fmt_date(date)})")
    lines.append(f"開盤 ${ohlc['open']:.2f} / 收盤 ${ohlc['close']:.2f} / "
                  f"高 ${ohlc['high']:.2f} / 低 ${ohlc['low']:.2f} "
                  f"({change_pct:+.2f}%)")
    lines.append(f"總量 {_fmt_zhang(data['total_buy_shares'])} 張")
    lines.append("")

    # Top cells
    lines.append("【🔥 Top 10 大單 cells (broker × price)】")
    if not data["top_cells"]:
        lines.append("  (無資料)")
    else:
        for i, c in enumerate(data["top_cells"], 1):
            side_label = "買" if c["side"] == "buy" else "賣"
            lines.append(
                f"{i}. {c['broker_id']} {c['broker_name']} @${c['price']:.2f} "
                f"{side_label} {_fmt_zhang(c['volume'])} 張 {c['tag']}"
            )
    lines.append("")

    # Stage analysis
    lines.append("【⏰ 三階段分析】")
    rng = ohlc["high"] - ohlc["low"]
    if rng > 0:
        lines.append(f"早盤 (低 25%: ${ohlc['low']:.2f} ~ "
                      f"${ohlc['low'] + 0.25 * rng:.2f}):")
    else:
        lines.append("早盤:")
    _emit_zone(lines, data["stage"]["early"])
    lines.append("")
    if rng > 0:
        lines.append(f"盤中 (中 50%: ${ohlc['low'] + 0.25 * rng:.2f} ~ "
                      f"${ohlc['low'] + 0.75 * rng:.2f}):")
    else:
        lines.append("盤中:")
    _emit_zone(lines, data["stage"]["mid"])
    lines.append("")
    if rng > 0:
        lines.append(f"尾盤 (高 25%: ${ohlc['low'] + 0.75 * rng:.2f} ~ "
                      f"${ohlc['high']:.2f}):")
    else:
        lines.append("尾盤:")
    _emit_zone(lines, data["stage"]["late"])
    lines.append("")

    # Fingerprint
    lines.append("【🎯 Top 5 買超分點價格指紋】")
    if not data["fingerprint"]["top_buyers"]:
        lines.append("  (無)")
    else:
        for b in data["fingerprint"]["top_buyers"]:
            pr_lo, pr_hi = b["price_range"]
            lines.append(
                f"  {b['broker_id']} {b['broker_name']} "
                f"+{_fmt_zhang(b['net_shares'])} 張 — "
                f"avg ${b['avg_price']:.2f}, 範圍 ${pr_lo:.2f}~${pr_hi:.2f}"
            )
    lines.append("")
    lines.append("【🎯 Top 5 賣超分點價格指紋】")
    if not data["fingerprint"]["top_sellers"]:
        lines.append("  (無)")
    else:
        for b in data["fingerprint"]["top_sellers"]:
            pr_lo, pr_hi = b["price_range"]
            lines.append(
                f"  {b['broker_id']} {b['broker_name']} "
                f"{_fmt_zhang(b['net_shares'])} 張 — "
                f"avg ${b['avg_price']:.2f}, 範圍 ${pr_lo:.2f}~${pr_hi:.2f}"
            )
    return "\n".join(lines)


def _emit_zone(lines: list[str], zone_rows: list[dict]) -> None:
    """Helper: append top 3 buyers + top 3 sellers from a zone's sorted rows."""
    buyers = [r for r in zone_rows if r["net_shares"] > 0][:3]
    sellers = [r for r in zone_rows if r["net_shares"] < 0][:3]
    if buyers:
        labels = " / ".join(
            f"{r['broker_name']} +{_fmt_zhang(r['net_shares'])} 張"
            for r in buyers
        )
        lines.append(f"  🟢 買方主力: {labels}")
    if sellers:
        labels = " / ".join(
            f"{r['broker_name']} {_fmt_zhang(r['net_shares'])} 張"
            for r in sellers
        )
        lines.append(f"  🔴 賣方主力: {labels}")
    if not buyers and not sellers:
        lines.append("  (本區無大量交易)")
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_chip_price -v 2>&1 | tail -10
```

Expected: 13 tests total pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py tests/test_chip_price.py
git commit -m "chip_price: format_report Telegram-friendly text output"
```

---

### Task 8: CLI entry point + analyze pipeline

**Files:**
- Modify: `tw_chip_price.py` — replace placeholder `__main__` with full pipeline + telegram push

- [ ] **Step 1: Replace `__main__` block**

In `tw_chip_price.py`, replace the existing `if __name__ == "__main__":` block (placeholder at the bottom) with:

```python
def analyze(stock_code: str, date: str | None = None,
            no_fetch: bool = False) -> dict:
    """Run the full pipeline: BSR fetch → OHLC → top cells / stage / fingerprint.

    Returns a dict ready for format_report() (or empty dict on failure).
    """
    import bsr_scraper

    # 1. BSR fetch (or load cached per-price file)
    target = date or datetime.now().strftime("%Y%m%d")
    cache_path = os.path.join(HERE, "bsr_cache", f"{stock_code}_{target}_prices.json")
    bsr = {}
    if no_fetch:
        if not os.path.exists(cache_path):
            print(f"[ERROR] --no-fetch but cache missing: {cache_path}", file=sys.stderr)
            return {}
        with open(cache_path) as f:
            bsr = json.load(f)
    else:
        bsr = bsr_scraper.fetch_bsr_with_prices(stock_code)
        if not bsr or not bsr.get("rows"):
            print(f"[ERROR] BSR fetch returned empty for {stock_code}", file=sys.stderr)
            return {}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(bsr, f, ensure_ascii=False)

    # 2. OHLC for stage range
    ohlc = get_ohlc(stock_code, target)
    if not ohlc:
        # Fallback: derive range from BSR rows themselves
        prices = [r["price"] for r in bsr["rows"]]
        ohlc = {"open": min(prices), "high": max(prices),
                "low": min(prices), "close": max(prices)}

    # 3. Top cells + stage + fingerprint
    cells = top_cells(bsr["rows"], top_n=10,
                       low=ohlc["low"], high=ohlc["high"])
    stage = stage_breakdown(bsr["rows"], ohlc["low"], ohlc["high"])
    fingerprint = broker_fingerprint(bsr["rows"], top_n=5)

    # 4. Resolve Chinese name
    try:
        from stock_names import get_name
        name = get_name(stock_code, "")
    except Exception:
        name = ""

    return {
        "stock_code": stock_code,
        "name": name,
        "date": bsr.get("date", target),
        "ohlc": ohlc,
        "total_buy_shares": bsr.get("total_buy_shares", 0),
        "total_sell_shares": bsr.get("total_sell_shares", 0),
        "top_cells": cells,
        "stage": stage,
        "fingerprint": fingerprint,
    }


def _send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    """Push report to Telegram chat. Chunks if > 4000 chars."""
    api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_len = 4000
    chunks = [text] if len(text) <= max_len else []
    if not chunks:
        cur, lines = "", text.split("\n")
        for ln in lines:
            if len(cur) + len(ln) + 1 > max_len:
                chunks.append(cur)
                cur = ln
            else:
                cur = cur + "\n" + ln if cur else ln
        if cur:
            chunks.append(cur)
    ok = True
    for c in chunks:
        body = json.dumps({"chat_id": chat_id, "text": c}).encode()
        req = urllib.request.Request(
            api, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if not json.loads(resp.read().decode()).get("ok"):
                    ok = False
        except Exception as e:
            print(f"[TG error] {e}", file=sys.stderr)
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description="台股單檔籌碼價格分析")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--date", help="日期 YYYYMMDD (預設今天)")
    parser.add_argument("--telegram", action="store_true",
                        help="推送報告到 Telegram")
    parser.add_argument("--bot-token",
                        default=os.environ.get("TG_BOT_TOKEN", ""))
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--json-out", help="同時寫結構化 JSON 到此路徑")
    parser.add_argument("--no-fetch", action="store_true",
                        help="只讀 cache，不打 TWSE")
    args = parser.parse_args()

    data = analyze(args.code, date=args.date, no_fetch=args.no_fetch)
    if not data:
        sys.exit(1)
    report = format_report(data)
    print(report)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".",
                    exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] --telegram requires TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = _send_telegram(report, args.bot_token, args.chat_id)
        print(f"[TG] {'sent' if ok else 'partial/fail'}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test (end-to-end against 2330)**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tw_chip_price.py 2330 2>&1 | head -30
```

Expected: prints "2330 台積電 籌碼價格分析" + OHLC + top cells + stage + fingerprint. CAPTCHA may need 1-5 tries. Total time 5-15 seconds.

- [ ] **Step 3: Verify cache file written**

```bash
ls -la ~/project/tw_stock_tools/bsr_cache/2330_*_prices.json
/usr/bin/python3 -c "
import json
import os, glob
files = sorted(glob.glob('/home/kun/project/tw_stock_tools/bsr_cache/2330_*_prices.json'))
with open(files[-1]) as f: d = json.load(f)
print(f'date={d[\"date\"]} rows={len(d[\"rows\"])} buy={d[\"total_buy_shares\"]} sell={d[\"total_sell_shares\"]}')
"
```

Expected: cache file exists, contains rows list + totals.

- [ ] **Step 4: Re-run with --no-fetch (should use cache)**

```bash
TODAY=$(date +%Y%m%d)
cd ~/project/tw_stock_tools && /usr/bin/python3 tw_chip_price.py 2330 --date $TODAY --no-fetch 2>&1 | head -5
```

Expected: same report, no CAPTCHA hit (instant return).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py
git commit -m "chip_price: CLI entry + analyze pipeline + telegram push"
```

---

### Task 9: Create `/chip-price` skill

**Files:**
- Create: `~/.claude/skills/chip-price/SKILL.md`

- [ ] **Step 1: Create skill directory**

```bash
mkdir -p ~/.claude/skills/chip-price
```

- [ ] **Step 2: Write SKILL.md**

Create `/home/kun/.claude/skills/chip-price/SKILL.md`:

```markdown
---
name: chip-price
description: 台股單檔日內籌碼 × 價格分析 — 取得當日 TWSE BSR (買賣日報表) 含每個分點在每個成交價的買賣量，列出 Top 10 大單 cells、三階段 (早盤/盤中/尾盤) 各方主力、Top 5 買賣超分點價格指紋。當使用者說 "/chip-price XXXX"、"XXXX 籌碼價格"、"XXXX 籌碼價量"、"XXXX 分點價格" 時觸發。
---

# Chip-Price — 台股單檔日內籌碼價格分析

## 觸發時機

- 使用者明確要 `/chip-price XXXX` 或「XXXX 籌碼價格 / 籌碼價量 / 分點價格」
- 使用者在 chip 分析後追問「價格分布」/「誰在哪個價位買」/「時間點大買賣」
- ⚠️ 不要跟 `/chip` (籌碼總覽) 混用 — `/chip` 是三線整合 (借券+分點+融資)，`/chip-price` 是當日 BSR 價格深度

## 執行流程

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_chip_price.py <code>
```

工具會自動：
1. 重抓 TWSE BSR (含 CAPTCHA, 5-15 秒)
2. 從 FinMind 抓 OHLC 取得當日價格區間
3. 計算 Top 10 cells、三階段、分點指紋
4. 輸出 Telegram 友善文字
5. 同步寫 cache 到 `bsr_cache/{code}_{date}_prices.json`

## 輸出格式（範例）

```
2313 華通 籌碼價格分析 (2026/05/12)
開盤 $246.00 / 收盤 $260.00 / 高 $264.50 / 低 $246.00 (+5.69%)
總量 93,922 張

【🔥 Top 10 大單 cells (broker × price)】
1. 1480 美商高盛 @$246.50 買 8,200 張 ⬇ 早盤搶低
2. ...

【⏰ 三階段分析】
早盤 (低 25%: $246.00 ~ $250.63):
  🟢 買方主力: 高盛 +8,500張 / ...
  🔴 賣方主力: 國泰 -600張 / ...
盤中 (中 50%): ...
尾盤 (高 25%): ...

【🎯 Top 5 買超分點價格指紋】
...

【🎯 Top 5 賣超分點價格指紋】
...
```

## 判讀紀律

### ⚠️ 紀律 1：價格 ≠ 時間

BSR 沒有真正的時間戳。價格只是「時間的 proxy」：
- 開盤近低點 → 早盤
- 收盤近高點 → 尾盤
- 但若整日 V 型反轉，順序就會錯亂

→ 判讀時用「**$246-250 區買進**」這種**價位描述**，不要直接說「**早盤買進**」(可能誤)。

### ⚠️ 紀律 2：上市/上櫃覆蓋

- TWSE (上市) 100% 支援 per-price detail
- TPEx (上櫃) 若 CSV 格式同樣可解析則同樣支援；若不可解析則 fall back 到 aggregate-only (工具會 print 警告)

### ⚠️ 紀律 3：CAPTCHA 失敗

TWSE BSR 用 CAPTCHA 阻擋自動爬蟲。我們用 ddddocr 解，成功率 ~80%。如果 fetch 失敗：
- 工具會自動重試 10 次（換 CAPTCHA 圖）
- 若全部失敗，回傳 empty rows
- 重跑一次通常會成功

### ⚠️ 紀律 4：跟 /chip 的分工

- `/chip` = 三線整合（借券+分點 aggregate+融資）— 看「**今天是誰在主導**」
- `/chip-price` = 當日 BSR 價格深度 — 看「**主導者在哪個價位下手**」

兩個一起跑能拿到完整圖像。
```

- [ ] **Step 3: Verify skill registers (within current session)**

```bash
ls -la ~/.claude/skills/chip-price/SKILL.md
head -3 ~/.claude/skills/chip-price/SKILL.md
```

Expected: file exists with the frontmatter present.

- [ ] **Step 4: No git commit needed for skill** (user-level skill outside repo)

---

### Task 10: TPEx fallback + documentation + memory

**Files:**
- Modify: `tw_chip_price.py` — TPEx detection + warning
- Modify: `README.md`
- Create: `~/.claude/projects/-home-kun/memory/reference_chip_price_skill.md`
- Modify: `~/.claude/projects/-home-kun/memory/MEMORY.md`

- [ ] **Step 1: Add TPEx fallback note in `analyze()`**

In `tw_chip_price.py`, find the `analyze()` function. After the BSR fetch block, add a market-detection step. If BSR returns 0 rows AND `no_fetch` is False, try checking if the stock is TPEx (上櫃) — for now this is a warning only (the existing `bsr_scraper.fetch_and_cache()` has TPEx via Playwright path, but `fetch_bsr_with_prices` is TWSE only as of v1):

Insert after `bsr = bsr_scraper.fetch_bsr_with_prices(stock_code)`:

```python
        # TPEx (上櫃) detection — fetch_bsr_with_prices is currently TWSE-only.
        # If we got 0 rows or a no_data flag, the stock may be 上櫃; tell user.
        if not bsr or not bsr.get("rows") or bsr.get("no_data"):
            print(f"[WARN] No TWSE BSR for {stock_code}. If 上櫃 (TPEx) stock, "
                  f"per-price detail is not yet supported. Use /chip (aggregate) "
                  f"instead.", file=sys.stderr)
            return {}
```

(The earlier "if not bsr or not bsr.get('rows')" block becomes the above; remove the duplicate `return {}` below it if present.)

- [ ] **Step 2: Smoke test with TPEx stock 3491**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tw_chip_price.py 3491 2>&1 | head -5
```

Expected: prints WARN message about TPEx not supported, exits non-zero (or empty output).

- [ ] **Step 3: Update top-level README**

In `~/project/tw_stock_tools/README.md`, find a logical spot (after the existing tool listing). Add:

```markdown
## tw_chip_price.py — 單檔日內籌碼 × 價格分析 (CLI / Skill)

跟 `/chip` 不同 — `/chip-price` 專看當日 TWSE BSR 的「分點 × 價格」二維分布，
推斷誰在哪個價位買進/出脫。輸出包括：
- Top 10 大單 cells (broker × price × side) 含 ⬇ 早盤搶低 / ⬆ 高檔倒貨 等 direction tag
- 三階段 (早盤低 25% / 盤中 50% / 尾盤高 25%) 各方主力
- Top 5 買賣超分點價格指紋 (avg cost + 價格範圍)

### 使用
```bash
FINMIND_TOKEN=... python3 tw_chip_price.py 2313
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --telegram   # 推 TG
FINMIND_TOKEN=... python3 tw_chip_price.py 2313 --json-out out.json
```

### Skill 觸發
- `/chip-price 2313`
- "2313 籌碼價格" / "2313 分點價格" / "2313 籌碼價量"

### 限制
- 僅支援 TWSE (上市)。TPEx (上櫃) 暫不支援 per-price detail (fall back 到 `/chip`)
- 價格是時間的 proxy，不是真正的時間戳
- CAPTCHA 解析靠 ddddocr，成功率 ~80% (失敗自動重試)
```

- [ ] **Step 4: Create memory reference**

Create `/home/kun/.claude/projects/-home-kun/memory/reference_chip_price_skill.md`:

```markdown
---
name: /chip-price skill — 日內籌碼價格分析
description: 自製 user-level skill 在 ~/.claude/skills/chip-price/SKILL.md，台股單檔當日 TWSE BSR 的 broker × price 二維分析，含 Top 10 大單/三階段/分點指紋。觸發詞 + 4 條判讀紀律。
type: reference
---

`/chip-price XXXX` skill 在 `~/.claude/skills/chip-price/SKILL.md`，於 2026-05-13 建立。

**觸發條件：**
- `/chip-price XXXX`
- 「XXXX 籌碼價格」/「XXXX 籌碼價量」/「XXXX 分點價格」

**跟 /chip 的分工：**
- `/chip` = 三線整合（借券+分點 aggregate+融資）— 看誰在主導
- `/chip-price` = 當日 BSR 價格深度 — 看主導者在哪個價位下手

**底層工具：** `tw_chip_price.py`
1. fetch_bsr_with_prices() — 解 CAPTCHA + parse per-(broker, price) rows
2. get_ohlc() — FinMind 拿當日 OHLC 用作 stage 切分
3. top_cells / stage_breakdown / broker_fingerprint — 三段分析
4. format_report — Telegram 友善文字

**判讀紀律：**
1. 價格 ≠ 時間（只是 proxy；V 型反轉日順序會錯亂）
2. 上市/上櫃 — 目前只支援 TWSE，TPEx 暫無 per-price detail
3. CAPTCHA 失敗時工具自動重試 10 次
4. /chip 跟 /chip-price 互補，不要當成同一個工具

**Cache:** `bsr_cache/{code}_{date}_prices.json` (新格式，跟舊 aggregate cache 並存)

**設計文件:** `docs/superpowers/specs/2026-05-13-chip-price-analysis-design.md`
**實作計畫:** `docs/superpowers/plans/2026-05-13-chip-price-analysis.md`
```

- [ ] **Step 5: Update MEMORY.md index**

Append to `/home/kun/.claude/projects/-home-kun/memory/MEMORY.md`:

```
- [/chip-price skill](reference_chip_price_skill.md) — 自製 skill 做台股單檔當日 BSR broker × price 二維分析；2026-05-13 加入
```

- [ ] **Step 6: Commit + push**

```bash
cd ~/project/tw_stock_tools && git add tw_chip_price.py README.md
git commit -m "chip_price: TPEx fallback warning + README"
git push 2>&1 | tail -3
```

(Memory and skill files in ~/.claude, not git.)

---

## Self-Review

**Spec coverage:**
- §1 Goal → Tasks 1-8 cover fetch + analysis + format
- §3 Decision Log → Trigger phrases in Task 9 SKILL.md (all variants); force re-fetch is default in Task 8; full output in Task 7; TPEx fallback in Task 10
- §4 Architecture → File map matches plan
- §5 Data Structure → JSON schema written by Task 8 (analyze() → cache file); CLI output produced by Task 7 format_report
- §6 CLI Interface → Task 8 main()
- §7 Scraper Modification → Tasks 1 + 2
- §8 Stage Analysis Logic → Task 4
- §9 Tool Output Cell Format / direction tags → Task 6
- §10 TPEx Support → Task 10
- §11 Skill Wiring → Task 9
- §12 Acceptance Criteria → smoke tests in Tasks 2, 8

**Placeholder scan:** No TBD/TODO/placeholder code. Every step has concrete code or commands.

**Type consistency:**
- `_parse_bsr_csv_with_prices()` returns `list[dict]` with `broker_id`, `broker_name`, `price`, `buy`, `sell` — referenced consistently in Tasks 4, 5, 6
- `fetch_bsr_with_prices()` returns `{date, stock_code, rows, total_buy_shares, total_sell_shares}` — Task 8 reads these keys
- `stage_breakdown()` returns `{early: [...], mid: [...], late: [...]}` with per-row `{broker_id, broker_name, buy_shares, sell_shares, net_shares}` — Task 7 format_report consumes this exact shape via `_emit_zone()`
- `broker_fingerprint()` returns `{top_buyers, top_sellers}` with per-row `{net_shares, avg_price, price_range, ...}` — Task 7 consumes via fingerprint section
- `top_cells()` returns list of `{broker_id, broker_name, price, side, volume, zone, tag}` — Task 7 reads side/zone/tag/volume

All types align.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-13-chip-price-analysis.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
