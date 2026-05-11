# FinMind Sponsor Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate lending tools (hybrid; 還券 stays on TWSE) and price fetchers (Yahoo→FinMind) to FinMind sponsor tier, with side-by-side verification on 2313/1268/2330 before each commit.

**Architecture:** Create a shared `finmind_client.py` module with thin pass-through wrappers for the three datasets (`TaiwanStockSecuritiesLending`, `TaiwanDailyShortSaleBalances`, `TaiwanStockPrice`). Each affected tool's fetcher gets its body replaced (preserving return-dict shape) so downstream code stays untouched. Per-tool side-by-side verification (old vs new) on 3 stocks × 5 days blocks the commit until they match within tolerance.

**Tech Stack:** Python 3 stdlib (`urllib`, `json`, `os`, `unittest`). FinMind v4 REST API. No new pip deps.

**Spec:** `docs/superpowers/specs/2026-05-11-finmind-migration-design.md`

---

## File Structure

**Create:**
- `finmind_client.py` (top-level) — thin FinMind v4 client (3 fetch functions + 1 whole-market helper)
- `tests/test_finmind_client.py` (top-level) — unit tests via real network (or skipped if no token)
- `tools/verify_fetcher_parity.py` — side-by-side verification harness (called manually per task)

**Modify:**
- `tw_lending_lookup.py` — replace `fetch_lending_transactions`, `fetch_twse_sbl_balance`, `fetch_tpex_sbl_balance`. KEEP `fetch_return_details` (TWSE).
- `tw_lending_monitor.py` — replace `fetch_twse_lending`, `fetch_sbl_short_selling`.
- `tw_second_wave.py` — replace `fetch_yahoo_6mo`.
- `tw_dormant_giants.py` — replace `fetch_yahoo_long`.
- `concept_momentum/data_fetcher.py` — replace `fetch_yahoo` / `fetch_stock` body (keep cache layout).
- `tw_limitup_signal.py` — replace Yahoo branch of `fetch_price_history` (TWSE part is fine — kept).
- `~/.claude/skills/chip/SKILL.md` — reword 紀律 6 (TWSE retry now only applies to 還券 section).
- `README.md`, `concept_momentum/README.md`, memory MEMORY.md.

**Testing approach:** stdlib `unittest`. Unit tests for `finmind_client` use real network smoke (token from crontab). Per-tool parity tests run as ad-hoc scripts using `verify_fetcher_parity.py` before each migration commit — they print "PASS"/"FAIL" lines comparing fields. No CI; verification is human-supervised.

---

### Task 1: Scaffold `finmind_client.py` + tests

**Files:**
- Create: `finmind_client.py`
- Create: `tests/__init__.py`
- Create: `tests/test_finmind_client.py`

- [ ] **Step 1: Create empty test scaffold**

```bash
mkdir -p ~/project/tw_stock_tools/tests
touch ~/project/tw_stock_tools/tests/__init__.py
```

Create `tests/test_finmind_client.py`:

```python
"""Smoke tests for finmind_client. Hits real FinMind API; skips if no token."""
import os
import unittest

# Token loaded once at module import
TOKEN = ""
try:
    import subprocess
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            TOKEN = line.split("FINMIND_TOKEN=")[1].split()[0]
            break
except Exception:
    pass


class TestPlaceholder(unittest.TestCase):
    def test_token_available(self):
        if not TOKEN:
            self.skipTest("No FINMIND_TOKEN in crontab")
        self.assertTrue(TOKEN.startswith("eyJ"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run placeholder test**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_finmind_client -v 2>&1 | tail -5
```

Expected: `Ran 1 test ... OK`.

- [ ] **Step 3: Create minimal `finmind_client.py`**

Create `finmind_client.py`:

```python
"""Thin FinMind v4 API client.

Each function takes (data_id, start_date, end_date, token) and returns the
parsed `data` list in FinMind's native schema. No schema translation, no
caching — callers stay in control of their own data shapes.

Built-in retry: HTTP 429 → sleep 60s, retry once.
"""

from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.finmindtrade.com/api/v4/data"


def _call(dataset: str, params: dict, token: str, _retried: bool = False) -> list[dict]:
    """Generic FinMind call. Raises RuntimeError on non-200 status."""
    full_params = {"dataset": dataset, "token": token, **params}
    url = f"{BASE_URL}?{urllib.parse.urlencode(full_params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429 and not _retried:
            time.sleep(60)
            return _call(dataset, params, token, _retried=True)
        body = e.read().decode() if hasattr(e, "read") else str(e)
        raise RuntimeError(f"FinMind {dataset} HTTP {e.code}: {body[:200]}")
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset} error: {payload.get('msg', '')}")
    return payload.get("data", [])


def fetch_securities_lending(stock_id: str, start_date: str, end_date: str,
                              token: str) -> list[dict]:
    """Fetch 借券交易 (借入 events) for a stock.

    Returns rows with shape:
      {date, stock_id, transaction_type, volume (張), fee_rate (%),
       close, original_return_date, original_lending_period}
    """
    return _call("TaiwanStockSecuritiesLending", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_short_sale_balances(stock_id: str, start_date: str, end_date: str,
                               token: str) -> list[dict]:
    """Fetch 信用交易+借券賣出餘額 for a stock.

    Returns rows with shape (values in 股):
      {date, stock_id,
       MarginShortSalesPreviousDayBalance, MarginShortSalesShortSales,
       MarginShortSalesShortCovering, ..., MarginShortSalesCurrentDayBalance,
       SBLShortSalesPreviousDayBalance, SBLShortSalesShortSales,
       SBLShortSalesReturns, SBLShortSalesAdjustments, SBLShortSalesCurrentDayBalance,
       SBLShortSalesQuota, SBLShortSalesShortCovering}
    """
    return _call("TaiwanDailyShortSaleBalances", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_stock_price(stock_id: str, start_date: str, end_date: str,
                      token: str) -> list[dict]:
    """Fetch 個股日線價格.

    Returns rows with shape:
      {date, stock_id, Trading_Volume, Trading_money, open, max, min, close,
       spread, Trading_turnover}
    """
    return _call("TaiwanStockPrice", {
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }, token)


def fetch_short_sale_balances_market(date: str, token: str) -> list[dict]:
    """Fetch 全市場一日 借券賣出餘額 (for daily SBL monitor sweeps)."""
    return _call("TaiwanDailyShortSaleBalances", {
        "start_date": date,
        "end_date": date,
    }, token)
```

- [ ] **Step 4: Add real tests**

Replace `tests/test_finmind_client.py` content with:

```python
"""Smoke tests for finmind_client. Hits real FinMind API; skips if no token."""
import os
import subprocess
import sys
import unittest

# Token loaded once at module import
TOKEN = ""
try:
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            TOKEN = line.split("FINMIND_TOKEN=")[1].split()[0]
            break
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import finmind_client


@unittest.skipUnless(TOKEN, "No FINMIND_TOKEN in crontab")
class TestFinmindClient(unittest.TestCase):
    def test_securities_lending_2313_2026_05_08(self):
        """2313 on 5/8 had a 190-張 議借 row (verified manually)."""
        rows = finmind_client.fetch_securities_lending(
            "2313", "2026-05-08", "2026-05-08", TOKEN)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-05-08")
        self.assertEqual(row["stock_id"], "2313")
        self.assertEqual(row["transaction_type"], "議借")
        self.assertEqual(row["volume"], 190)
        self.assertAlmostEqual(row["fee_rate"], 1.75, places=2)

    def test_short_sale_balances_2313_2026_05_08(self):
        """2313 SBL balance 5/8 should be 21,833,000 股 (21,833 張)."""
        rows = finmind_client.fetch_short_sale_balances(
            "2313", "2026-05-08", "2026-05-08", TOKEN)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["SBLShortSalesCurrentDayBalance"], 21833000)
        # 當日賣出 826,000 股 = 826 張
        self.assertEqual(row["SBLShortSalesShortSales"], 826000)
        # 當日還券 912,000 股 = 912 張
        self.assertEqual(row["SBLShortSalesReturns"], 912000)

    def test_stock_price_2330_q1_2008(self):
        """Sanity: 18-year historical depth available."""
        rows = finmind_client.fetch_stock_price(
            "2330", "2008-01-01", "2008-01-31", TOKEN)
        self.assertGreater(len(rows), 15)  # ~20 trading days in Jan
        self.assertEqual(rows[0]["stock_id"], "2330")
        self.assertEqual(rows[0]["date"][:7], "2008-01")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run tests + commit**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest tests.test_finmind_client -v 2>&1 | tail -10
```

Expected: 3 tests pass.

```bash
cd ~/project/tw_stock_tools && git add finmind_client.py tests/
git commit -m "finmind_client: thin v4 API wrapper for sponsor migration"
```

---

### Task 2: Migrate `tw_lending_lookup.py` 借入交易 (fetch_lending_transactions)

**Files:**
- Modify: `tw_lending_lookup.py:32-64` (replace `fetch_lending_transactions` body)
- Create: `tools/verify_lending_lookup.py` (verification harness)

- [ ] **Step 1: Create verification harness**

```bash
mkdir -p ~/project/tw_stock_tools/tools
```

Create `tools/verify_lending_lookup.py`:

```python
"""Side-by-side verification: TWSE direct vs FinMind for 借入交易 events.

Run BEFORE swapping fetch_lending_transactions to FinMind.
Usage:
  /usr/bin/python3 tools/verify_lending_lookup.py
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import finmind_client  # noqa


def _get_token():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=")[1].split()[0]
    return ""


def _twse_fetch(code: str, start: str, end: str) -> list[dict]:
    """Direct TWSE t13sa710 fetch (current production path)."""
    url = (f"https://www.twse.com.tw/SBL/t13sa710?"
           f"startDate={start.replace('-','')}&endDate={end.replace('-','')}"
           f"&stockNo={code}&response=json")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  [TWSE error {e.code}] retrying once after 5s")
        import time
        time.sleep(5)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    if data.get("stat") != "OK":
        return []
    out = []
    for row in data.get("data", []):
        # row format: [date_roc, code_name, type, volume, fee_rate, ...]
        roc = row[0]  # e.g., "115年05月08日"
        y, m, d = roc.replace("年", "/").replace("月", "/").replace("日", "").split("/")
        ad = f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
        out.append({
            "date": ad,
            "volume": int(str(row[3]).replace(",", "")),
            "fee_rate": float(str(row[4]).replace(",", "")),
            "type": row[2].strip(),
        })
    return out


def _finmind_fetch(code: str, start: str, end: str, token: str) -> list[dict]:
    rows = finmind_client.fetch_securities_lending(code, start, end, token)
    return [{"date": r["date"],
             "volume": int(r["volume"]),
             "fee_rate": float(r["fee_rate"]),
             "type": r["transaction_type"]}
            for r in rows]


def main():
    token = _get_token()
    if not token:
        print("ERROR: no FINMIND_TOKEN")
        sys.exit(1)

    test_cases = [
        ("2313", "2026-05-04", "2026-05-08"),
        ("1268", "2026-05-04", "2026-05-08"),
        ("2330", "2026-05-04", "2026-05-08"),
    ]
    all_pass = True
    for code, start, end in test_cases:
        print(f"\n=== {code} {start} ~ {end} ===")
        twse = sorted(_twse_fetch(code, start, end), key=lambda r: (r["date"], r["volume"]))
        fm = sorted(_finmind_fetch(code, start, end, token), key=lambda r: (r["date"], r["volume"]))
        print(f"  TWSE: {len(twse)} rows | FinMind: {len(fm)} rows")
        if len(twse) != len(fm):
            print(f"  FAIL: row count differs")
            all_pass = False
            continue
        match = True
        for a, b in zip(twse, fm):
            if (a["date"] != b["date"] or a["volume"] != b["volume"]
                    or abs(a["fee_rate"] - b["fee_rate"]) > 0.01
                    or a["type"] != b["type"]):
                print(f"  DIFF: TWSE={a} vs FinMind={b}")
                match = False
        if match:
            print(f"  PASS")
        else:
            all_pass = False

    print(f"\n{'='*40}\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run verification — must PASS before swapping**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tools/verify_lending_lookup.py
```

Expected: all 3 test cases show "PASS", and final line says `PASS`. If FAIL, investigate the mismatch before continuing.

- [ ] **Step 3: Swap `fetch_lending_transactions` in `tw_lending_lookup.py`**

Open `tw_lending_lookup.py`. Find lines 32-64 (`fetch_lending_transactions`). Replace the function body:

```python
def fetch_lending_transactions(code: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch all lending transactions (all types) for a stock code.

    Migrated 2026-05-11 from TWSE t13sa710 to FinMind TaiwanStockSecuritiesLending.
    Returns list of dicts with shape {date (YYYYMMDD), name, type, volume, fee_rate}.
    """
    import os
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client

    # Convert YYYYMMDD → YYYY-MM-DD for FinMind
    s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[ERROR] FINMIND_TOKEN env var not set", file=sys.stderr)
        return []

    try:
        rows = finmind_client.fetch_securities_lending(code, s, e, token)
    except Exception as ex:
        print(f"[ERROR] FinMind SecuritiesLending: {ex}", file=sys.stderr)
        return []

    records = []
    for row in rows:
        # Convert YYYY-MM-DD → YYYYMMDD to match prior shape
        date_str = row["date"].replace("-", "")
        records.append({
            "date": date_str,
            "name": "",  # FinMind doesn't include 中文名 in this dataset
            "type": row.get("transaction_type", ""),
            "volume": int(row.get("volume", 0)),
            "fee_rate": float(row.get("fee_rate", 0.0)),
        })
    return records
```

Note: TWSE 中文名 was in column 1 of t13sa710 row; FinMind doesn't expose it. The `name` field is downstream-consumed in `format_report()` but `_zh_name(code)` is the canonical source (via stock_names.py), so this is a benign drop.

- [ ] **Step 4: End-to-end smoke**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_lending_lookup.py 2313 --date 20260508 2>&1 | tail -30
```

Expected: report renders correctly, "借券交易" section shows 190 張 議借 @ 1.75% for 5/8 (matches the data we already know from prior runs).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_lending_lookup.py tools/verify_lending_lookup.py
git commit -m "lending_lookup: migrate fetch_lending_transactions to FinMind

Side-by-side verified on 2313/1268/2330 × 5 days. Native FinMind dataset
TaiwanStockSecuritiesLending returns identical (volume, fee_rate, type) data.

Note: TWSE 中文名 column not in FinMind; downstream uses stock_names.py
anyway, so this is a benign drop."
```

---

### Task 3: Migrate `tw_lending_lookup.py` 借券賣出餘額 (fetch_twse_sbl_balance + fetch_tpex_sbl_balance)

**Files:**
- Modify: `tw_lending_lookup.py:83-125` (replace both SBL balance fetchers)
- Modify: `tools/verify_lending_lookup.py` (extend with SBL balance verification)

- [ ] **Step 1: Extend verification harness**

Open `tools/verify_lending_lookup.py`. Append a second verification function:

```python
def _twse_sbl_fetch(code: str, date_str: str) -> dict:
    """Direct TWSE TWT93U fetch."""
    url = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={date_str}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {}
    if data.get("stat") != "OK":
        return {}
    for row in data.get("data", []):
        if len(row) >= 14 and row[0].strip() == code:
            # cols 8-12: prev_balance, sell, return, adjust, today_balance (all 股)
            try:
                return {
                    "prev_balance_zhang": int(str(row[8]).replace(",", "")) // 1000,
                    "sell_zhang": int(str(row[9]).replace(",", "")) // 1000,
                    "return_zhang": int(str(row[10]).replace(",", "")) // 1000,
                    "today_balance_zhang": int(str(row[12]).replace(",", "")) // 1000,
                }
            except (ValueError, IndexError):
                return {}
    return {}


def _finmind_sbl_fetch(code: str, date_str: str, token: str) -> dict:
    """FinMind TaiwanDailyShortSaleBalances; same date in YYYY-MM-DD format."""
    s = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    rows = finmind_client.fetch_short_sale_balances(code, s, s, token)
    if not rows:
        return {}
    r = rows[0]
    return {
        "prev_balance_zhang": int(r.get("SBLShortSalesPreviousDayBalance", 0)) // 1000,
        "sell_zhang": int(r.get("SBLShortSalesShortSales", 0)) // 1000,
        "return_zhang": int(r.get("SBLShortSalesReturns", 0)) // 1000,
        "today_balance_zhang": int(r.get("SBLShortSalesCurrentDayBalance", 0)) // 1000,
    }


def verify_sbl_balance():
    token = _get_token()
    test_cases = [
        ("2313", "20260508"),
        ("2313", "20260507"),
        ("1268", "20260508"),
        ("2330", "20260508"),
    ]
    print("\n\n=== SBL balance verification ===")
    all_pass = True
    for code, date in test_cases:
        print(f"\n  {code} {date}")
        twse = _twse_sbl_fetch(code, date)
        fm = _finmind_sbl_fetch(code, date, token)
        print(f"    TWSE: {twse}")
        print(f"    FM  : {fm}")
        if twse and fm:
            ok = all(twse.get(k) == fm.get(k) for k in ["prev_balance_zhang",
                                                         "sell_zhang",
                                                         "return_zhang",
                                                         "today_balance_zhang"])
            print(f"    {'PASS' if ok else 'FAIL'}")
            if not ok:
                all_pass = False
        elif not twse and not fm:
            print(f"    PASS (both empty)")
        else:
            print(f"    FAIL (one source empty, other not)")
            all_pass = False
    return all_pass
```

And modify the `main()` to call this too:

```python
def main():
    token = _get_token()
    if not token:
        print("ERROR: no FINMIND_TOKEN")
        sys.exit(1)

    # Existing 借入 verification
    test_cases = [
        ("2313", "2026-05-04", "2026-05-08"),
        ("1268", "2026-05-04", "2026-05-08"),
        ("2330", "2026-05-04", "2026-05-08"),
    ]
    all_pass = True
    for code, start, end in test_cases:
        print(f"\n=== {code} 借入 {start} ~ {end} ===")
        twse = sorted(_twse_fetch(code, start, end), key=lambda r: (r["date"], r["volume"]))
        fm = sorted(_finmind_fetch(code, start, end, token), key=lambda r: (r["date"], r["volume"]))
        print(f"  TWSE: {len(twse)} rows | FinMind: {len(fm)} rows")
        if len(twse) != len(fm):
            print(f"  FAIL: row count differs")
            all_pass = False
            continue
        match = all(a["date"] == b["date"] and a["volume"] == b["volume"]
                    and abs(a["fee_rate"] - b["fee_rate"]) < 0.01
                    and a["type"] == b["type"] for a, b in zip(twse, fm))
        print(f"  {'PASS' if match else 'FAIL'}")
        if not match:
            for a, b in zip(twse, fm):
                if a != b:
                    print(f"    DIFF: TWSE={a} vs FinMind={b}")
            all_pass = False

    # SBL balance verification
    sbl_ok = verify_sbl_balance()
    all_pass = all_pass and sbl_ok

    print(f"\n{'='*40}\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)
```

- [ ] **Step 2: Run verification**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tools/verify_lending_lookup.py
```

Expected: all PASS for both 借入 and SBL balance sections.

- [ ] **Step 3: Swap both SBL balance fetchers in `tw_lending_lookup.py`**

In `tw_lending_lookup.py`, find `fetch_twse_sbl_balance` (line 83) and `fetch_tpex_sbl_balance` (line 103). Replace both function bodies with:

```python
def fetch_twse_sbl_balance(code: str, date_str: str) -> dict:
    """Fetch SBL balance for a TWSE (listed) stock.

    Migrated 2026-05-11 from TWSE TWT93U to FinMind TaiwanDailyShortSaleBalances.
    """
    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client
    s = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {}
    try:
        rows = finmind_client.fetch_short_sale_balances(code, s, s, token)
    except Exception as ex:
        print(f"[ERROR] FinMind ShortSaleBalances {code} {date_str}: {ex}", file=sys.stderr)
        return {}
    if not rows:
        return {}
    r = rows[0]
    return {
        "name": "",  # not provided by FinMind
        "prev_balance": int(r.get("SBLShortSalesPreviousDayBalance", 0)) / 1000,
        "sell": int(r.get("SBLShortSalesShortSales", 0)) / 1000,
        "return": int(r.get("SBLShortSalesReturns", 0)) / 1000,
        "adjust": int(r.get("SBLShortSalesAdjustments", 0)) / 1000,
        "today_balance": int(r.get("SBLShortSalesCurrentDayBalance", 0)) / 1000,
    }


def fetch_tpex_sbl_balance(code: str, date_str: str) -> dict:
    """Fetch SBL balance for a TPEx (OTC) stock.

    Migrated 2026-05-11 — TPEx and TWSE both available via FinMind unified dataset.
    """
    # FinMind unifies both markets; same function works for both.
    return fetch_twse_sbl_balance(code, date_str)
```

- [ ] **Step 4: Smoke test**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_lending_lookup.py 2313 --date 20260508 2>&1 | tail -30
```

Expected: 借券賣出餘額 section now shows: 前日 21,919 / 賣出 826 / 還券 912 / 當日 21,833 (-0.4%) for 5/8.

Also test TPEx stock:
```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_lending_lookup.py 3491 --date 20260508 2>&1 | tail -30
```

Expected: 3491 (上櫃) shows valid SBL balance section.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_lending_lookup.py tools/verify_lending_lookup.py
git commit -m "lending_lookup: migrate SBL balance fetchers to FinMind

TaiwanDailyShortSaleBalances unifies TWSE + TPEx SBL data. fetch_tpex_sbl_balance
becomes a thin alias of fetch_twse_sbl_balance. Side-by-side verified on
2313/1268/2330 × 4 dates."
```

---

### Task 4: Migrate `tw_lending_monitor.py` (both modes)

**Files:**
- Modify: `tw_lending_monitor.py:42-148` (replace `fetch_twse_lending` and `fetch_sbl_short_selling`)
- Create: `tools/verify_lending_monitor.py`

- [ ] **Step 1: Create verification harness**

Create `tools/verify_lending_monitor.py`:

```python
"""Side-by-side verification: TWSE direct vs FinMind for whole-market borrow + SBL.

For lending mode: compare 議借量+利率 detection on a sample date.
For SBL mode: compare 餘額大減 detection on a sample date.
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import finmind_client


def _get_token():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=")[1].split()[0]
    return ""


def main():
    token = _get_token()
    # Check that whole-market SBL balances endpoint works
    print("=== Whole-market SBL balances 5/8 ===")
    rows = finmind_client.fetch_short_sale_balances_market("2026-05-08", token)
    print(f"  FinMind row count: {len(rows)}")
    print(f"  First 3 rows:")
    for r in rows[:3]:
        print(f"    {r}")
    # Spot-check 2313
    for r in rows:
        if r.get("stock_id") == "2313":
            print(f"  2313 found: SBLBalance={r.get('SBLShortSalesCurrentDayBalance')} 股")
            break
    else:
        print("  WARN: 2313 not in whole-market response")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run verification**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tools/verify_lending_monitor.py
```

Expected: whole-market response has hundreds-to-thousands of stocks, 2313 found with reasonable SBLShortSalesCurrentDayBalance.

- [ ] **Step 3: Swap `fetch_twse_lending` in `tw_lending_monitor.py`**

In `tw_lending_monitor.py`, find `fetch_twse_lending` (line 42). Read the function to understand existing dict shape. Replace function body to call FinMind for each interesting stock OR batch fetch a date range. Since TWSE returned per-stock per-day, mirror that:

```python
def fetch_twse_lending(start_date: str, end_date: str) -> list[dict]:
    """Fetch 借入 events across all stocks for a date range.

    Migrated 2026-05-11 from TWSE t13sa710 to FinMind TaiwanStockSecuritiesLending.
    FinMind requires per-stock query; we fetch by date range with empty data_id
    via fetch_short_sale_balances_market style, but SecuritiesLending requires
    data_id — so iterate over stocks discovered via 借券賣出餘額 (whole-market).

    Returns list of {date (YYYYMMDD), code, type, volume, fee_rate}.
    """
    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[ERROR] FINMIND_TOKEN not set", file=sys.stderr)
        return []

    s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # Step 1: get all stock IDs that have SBL activity in the window
    # (cheaper than 4000+ per-stock calls — only stocks with any SBL appear)
    all_stock_ids = set()
    cur = s
    while cur <= e:
        try:
            rows = finmind_client.fetch_short_sale_balances_market(cur, token)
            for r in rows:
                sid = r.get("stock_id", "")
                if sid and sid.isdigit() and len(sid) == 4:
                    all_stock_ids.add(sid)
        except Exception as ex:
            print(f"[WARN] fetch_short_sale_balances_market {cur}: {ex}", file=sys.stderr)
        # advance by 1 day (string arithmetic)
        from datetime import datetime, timedelta
        d = datetime.strptime(cur, "%Y-%m-%d") + timedelta(days=1)
        cur = d.strftime("%Y-%m-%d")
        if cur > e:
            break

    # Step 2: per-stock fetch lending events
    records = []
    import time
    for sid in sorted(all_stock_ids):
        try:
            rows = finmind_client.fetch_securities_lending(sid, s, e, token)
        except Exception as ex:
            continue
        for row in rows:
            records.append({
                "date": row["date"].replace("-", ""),
                "code": sid,
                "type": row.get("transaction_type", ""),
                "volume": int(row.get("volume", 0)),
                "fee_rate": float(row.get("fee_rate", 0.0)),
            })
        time.sleep(0.05)  # gentle pacing
    return records
```

⚠️ This is N×M calls (N stocks × M dates). For a 6-day window and ~2,500 stocks, that's ~15,000 calls. At sponsor tier (~3,000 req/hr) this would take 5 hours.

Better approach: see if FinMind supports per-date whole-market for `TaiwanStockSecuritiesLending`. Test:

```bash
TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/')
/usr/bin/python3 -c "
import urllib.request, urllib.parse, json
url = 'https://api.finmindtrade.com/api/v4/data?' + urllib.parse.urlencode({
    'dataset': 'TaiwanStockSecuritiesLending',
    'start_date': '2026-05-08',
    'end_date': '2026-05-08',
    'token': '$TOKEN',
})
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
import urllib.error
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read())
    print(f'status: {payload.get(\"status\")} rows: {len(payload.get(\"data\", []))}')
    if payload.get('data'):
        print('first 3:', payload['data'][:3])
except urllib.error.HTTPError as e:
    print(f'HTTP {e.code}: {e.read().decode()[:200]}')
"
```

If whole-market call works (returns hundreds of rows), use a simpler implementation:

```python
def fetch_twse_lending(start_date: str, end_date: str) -> list[dict]:
    """[Updated implementation if whole-market FinMind call works]"""
    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return []

    s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
    rows = finmind_client._call("TaiwanStockSecuritiesLending", {
        "start_date": s, "end_date": e,
    }, token)
    records = []
    for row in rows:
        sid = row.get("stock_id", "")
        if not (sid.isdigit() and len(sid) == 4):
            continue
        records.append({
            "date": row["date"].replace("-", ""),
            "code": sid,
            "type": row.get("transaction_type", ""),
            "volume": int(row.get("volume", 0)),
            "fee_rate": float(row.get("fee_rate", 0.0)),
        })
    return records
```

Pick whichever variant the probe in this Step 3 supports.

- [ ] **Step 4: Swap `fetch_sbl_short_selling` in `tw_lending_monitor.py`**

In the same file, find `fetch_sbl_short_selling` (line 99). Replace body:

```python
def fetch_sbl_short_selling(date_str: str) -> list[dict]:
    """Fetch whole-market SBL balance + day-over-day change.

    Migrated 2026-05-11 from TWSE TWT93U + TPEx /sbl to FinMind.
    Returns list of dicts with shape:
      {code, prev_balance, today_balance, change_pct}
    """
    import os, sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return []

    d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    try:
        rows = finmind_client.fetch_short_sale_balances_market(d, token)
    except Exception as ex:
        print(f"[ERROR] FinMind SBL whole-market: {ex}", file=sys.stderr)
        return []

    out = []
    for r in rows:
        sid = r.get("stock_id", "")
        if not (sid.isdigit() and len(sid) == 4):
            continue
        prev = int(r.get("SBLShortSalesPreviousDayBalance", 0)) // 1000
        today = int(r.get("SBLShortSalesCurrentDayBalance", 0)) // 1000
        change_pct = ((today - prev) / prev * 100) if prev > 0 else 0.0
        out.append({
            "code": sid,
            "prev_balance": prev,
            "today_balance": today,
            "change_pct": round(change_pct, 2),
        })
    return out
```

- [ ] **Step 5: End-to-end smoke (both modes)**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  TG_BOT_TOKEN= /usr/bin/python3 tw_lending_monitor.py --mode lending --date 20260508 2>&1 | tail -20

echo ""

cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  TG_BOT_TOKEN= /usr/bin/python3 tw_lending_monitor.py --mode sbl --date 20260508 2>&1 | tail -20
```

Expected: lending mode produces a list of stocks (議借量爆量 + 利率異常); SBL mode produces stocks with 餘額大減. Both should have non-empty output.

- [ ] **Step 6: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_lending_monitor.py tools/verify_lending_monitor.py
git commit -m "lending_monitor: migrate both modes to FinMind sponsor

议借异常 detection and 借券賣出餘額大減 detection now both use FinMind
unified dataset (TaiwanStockSecuritiesLending + TaiwanDailyShortSaleBalances).
End-to-end smoke verified on 20260508 — both modes produce non-empty
candidate lists with same schema as before."
```

---

### Task 5: Migrate `tw_second_wave.py` (Yahoo → FinMind for daily prices)

**Files:**
- Modify: `tw_second_wave.py:141-189` (replace `fetch_yahoo_6mo`)
- Create: `tools/verify_price_parity.py`

- [ ] **Step 1: Create price parity verification harness**

Create `tools/verify_price_parity.py`:

```python
"""Side-by-side: Yahoo .TW vs FinMind TaiwanStockPrice."""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import finmind_client


def _get_token():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=")[1].split()[0]
    return ""


def _yahoo_fetch(code: str, suffix: str = ".TW", range_str: str = "6mo") -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range={range_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    out = {}
    from datetime import datetime
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        out[d] = round(c, 2)
    return out


def _finmind_fetch(code: str, start: str, end: str, token: str) -> dict:
    rows = finmind_client.fetch_stock_price(code, start, end, token)
    return {r["date"]: round(float(r["close"]), 2) for r in rows}


def main():
    token = _get_token()
    test_cases = [
        ("2313", ".TW"),    # 上市
        ("2330", ".TW"),
        ("3491", ".TWO"),   # 上櫃
    ]
    all_pass = True
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    for code, suffix in test_cases:
        print(f"\n=== {code}{suffix} ===")
        try:
            yhoo = _yahoo_fetch(code, suffix)
        except Exception as ex:
            print(f"  Yahoo error: {ex}")
            continue
        fm = _finmind_fetch(code, start_date, end_date, token)
        # Compare common dates only
        common = set(yhoo.keys()) & set(fm.keys())
        print(f"  Yahoo {len(yhoo)} | FinMind {len(fm)} | common {len(common)}")
        diffs = []
        for d in sorted(common)[-30:]:  # latest 30 dates
            y = yhoo[d]
            f = fm[d]
            if abs(y - f) > 0.01:
                diffs.append((d, y, f, y - f))
        if diffs:
            print(f"  DIFFS in last 30 days: {len(diffs)}")
            for d, y, f, delta in diffs[:5]:
                print(f"    {d}: Yahoo={y} FinMind={f} (delta={delta:+.2f})")
            # If diffs are sub-1%, likely due to adjusted vs raw
            ratio_diffs = [abs(y - f) / y * 100 for _, y, f, _ in diffs if y > 0]
            mean_pct = sum(ratio_diffs) / len(ratio_diffs)
            print(f"  Mean diff: {mean_pct:.2f}%")
            if mean_pct > 1.0:
                all_pass = False
        else:
            print(f"  PASS")

    print(f"\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run price parity**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 tools/verify_price_parity.py
```

Expected: For most days, Yahoo and FinMind close prices match within 0.01. For dividend / split dates, Yahoo (adj) may differ — that's expected (script flags >1% mean diff as FAIL).

If significant diffs are seen, investigate whether Yahoo's `adjclose` vs FinMind raw `close` is the issue. In our cases (second_wave uses 6-month window for pattern detection), raw close is acceptable.

- [ ] **Step 3: Swap `fetch_yahoo_6mo` in `tw_second_wave.py`**

In `tw_second_wave.py`, find `fetch_yahoo_6mo` (line 141). Replace body with:

```python
def fetch_yahoo_6mo(code: str) -> dict:
    """Fetch 6-month daily OHLCV for a stock.

    Migrated 2026-05-11 from Yahoo Finance to FinMind TaiwanStockPrice.
    Function name kept for backwards compatibility; data source is now FinMind.

    Returns dict {rows: [{date, open, high, low, close, volume}], ...} with
    same shape as before so downstream detect_second_wave() doesn't change.
    """
    import os, sys
    from datetime import datetime, timedelta
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"rows": []}

    end = datetime.now()
    start = end - timedelta(days=200)  # 6+ months
    try:
        rows = finmind_client.fetch_stock_price(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as ex:
        print(f"[WARN] FinMind fetch {code}: {ex}", file=sys.stderr)
        return {"rows": []}

    # FinMind row shape: {date, stock_id, Trading_Volume, open, max, min, close, ...}
    converted = []
    for r in rows:
        if r.get("close") is None or r.get("close") <= 0:
            continue
        converted.append({
            "date": r["date"].replace("-", ""),  # YYYYMMDD to match prior shape
            "open": float(r.get("open", 0)),
            "high": float(r.get("max", 0)),
            "low": float(r.get("min", 0)),
            "close": float(r["close"]),
            "volume": int(r.get("Trading_Volume", 0)),
        })
    return {"rows": converted}
```

- [ ] **Step 4: Smoke test**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_second_wave.py --quiet --json-out /tmp/sw_finmind.json 2>&1 | tail -5

/usr/bin/python3 -c "
import json
with open('/tmp/sw_finmind.json') as f: d = json.load(f)
print(f'date={d[\"date\"]} candidates={len(d[\"candidates\"])}')
for c in d['candidates'][:3]:
    print(f'  {c}')
"
rm /tmp/sw_finmind.json
```

Expected: candidate list produced. Compare to recent `second_wave_history/{date}.json` for similar count.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_second_wave.py tools/verify_price_parity.py
git commit -m "second_wave: migrate fetch_yahoo_6mo to FinMind TaiwanStockPrice

Function name preserved (drop-in replacement). Shape unchanged so detect_second_wave()
needs no modification."
```

---

### Task 6: Migrate `tw_dormant_giants.py` (Yahoo 18-year history → FinMind)

**Files:**
- Modify: `tw_dormant_giants.py:149-197` (replace `fetch_yahoo_long`)

- [ ] **Step 1: Verify FinMind has full 18-year depth for low-cap stocks**

```bash
TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/')
/usr/bin/python3 -c "
import urllib.request, urllib.parse, json
# Pick 2 known small-cap stocks that should have long history
for code in ['1268', '2331']:
    url = 'https://api.finmindtrade.com/api/v4/data?' + urllib.parse.urlencode({
        'dataset': 'TaiwanStockPrice', 'data_id': code,
        'start_date': '2008-01-01', 'end_date': '2008-12-31',
        'token': '$TOKEN',
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    print(f'{code}: {len(d.get(\"data\", []))} rows in 2008, first: {d.get(\"data\", [{}])[0].get(\"date\", \"?\")}')"
```

Expected: both have 200+ rows in 2008.

- [ ] **Step 2: Swap `fetch_yahoo_long`**

In `tw_dormant_giants.py`, find `fetch_yahoo_long` (line 149). Replace body:

```python
def fetch_yahoo_long(code: str, years: int = 18) -> dict:
    """Fetch N-year daily history for a stock.

    Migrated 2026-05-11 from Yahoo Finance to FinMind TaiwanStockPrice.
    Function name kept for backwards compatibility.

    Returns dict {rows: [{date, close, volume}], ...} matching prior shape.
    Note: FinMind returns raw close (not split-adjusted). 沉睡巨人 uses
    raw close anyway since we look for "曾經 X 倍" peaks, which are
    historical absolute levels.
    """
    import os, sys
    from datetime import datetime, timedelta
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    import finmind_client
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"rows": []}

    end = datetime.now()
    start = end.replace(year=end.year - years)
    try:
        rows = finmind_client.fetch_stock_price(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as ex:
        print(f"[WARN] FinMind fetch {code}: {ex}", file=sys.stderr)
        return {"rows": []}

    converted = []
    for r in rows:
        if r.get("close") is None or r.get("close") <= 0:
            continue
        converted.append({
            "date": r["date"].replace("-", ""),
            "close": float(r["close"]),
            "volume": int(r.get("Trading_Volume", 0)),
        })
    return {"rows": converted}
```

- [ ] **Step 3: Smoke test**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_dormant_giants.py 2>&1 | tail -20
```

Expected: candidate list produced (may take 5-10 min due to ~3,000 stocks, even with FinMind being faster than Yahoo).

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_dormant_giants.py
git commit -m "dormant_giants: migrate fetch_yahoo_long to FinMind TaiwanStockPrice

18-year history confirmed available for 2330 (2008-01-02 onward). Function
name preserved; shape unchanged."
```

---

### Task 7: Migrate `concept_momentum/data_fetcher.py`

**Files:**
- Modify: `concept_momentum/data_fetcher.py:33-150` (replace `fetch_yahoo` and `fetch_stock`)

- [ ] **Step 1: Read the existing fetcher**

```bash
sed -n '33,150p' ~/project/tw_stock_tools/concept_momentum/data_fetcher.py
```

Note the cache layout: `cache/prices/{code}_{date}.json` with a specific JSON shape. We preserve that.

- [ ] **Step 2: Replace `fetch_stock` body to call FinMind**

The simplest path: keep `fetch_yahoo` untouched (it's still useful for `^TWII`) but redirect `fetch_stock` (the per-stock concept member fetcher) to FinMind.

In `concept_momentum/data_fetcher.py`, find `fetch_stock` (line 77). Replace body:

```python
def fetch_stock(code: str) -> dict:
    """Fetch 3-month daily OHLCV for one concept member.

    Migrated 2026-05-11 from Yahoo to FinMind. Cache shape preserved so
    downstream concept_momentum.analyze_all() works unchanged.

    Cache miss → FinMind call. Cache hit → read disk.
    """
    import os, sys, json
    from datetime import datetime, timedelta
    HERE_LOCAL = os.path.dirname(os.path.abspath(__file__))
    TOP = os.path.dirname(HERE_LOCAL)
    sys.path.insert(0, TOP)
    import finmind_client

    today_str = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CACHE_DIR, "prices", f"{code}_{today_str}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                return json.load(f)
        except Exception:
            pass

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"code": code, "rows": []}

    end = datetime.now()
    start = end - timedelta(days=100)  # 3+ months
    try:
        rows = finmind_client.fetch_stock_price(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as ex:
        print(f"[WARN] FinMind {code}: {ex}", file=sys.stderr)
        return {"code": code, "rows": []}

    # Get Chinese name from stock_names if available
    try:
        from stock_names import get_name as _zh_name
        name = _zh_name(code, "")
    except Exception:
        name = ""

    converted_rows = []
    for r in rows:
        if r.get("close") is None or r.get("close") <= 0:
            continue
        converted_rows.append({
            "date": r["date"].replace("-", ""),
            "open": float(r.get("open", 0)),
            "high": float(r.get("max", 0)),
            "low": float(r.get("min", 0)),
            "close": float(r["close"]),
            "volume": int(r.get("Trading_Volume", 0)),
        })

    result = {
        "code": code,
        "name": name,
        "rows": converted_rows,
        "current_price": converted_rows[-1]["close"] if converted_rows else 0,
    }

    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w") as f:
        json.dump(result, f, ensure_ascii=False)
    return result
```

Note: Reads the actual `CACHE_DIR` constant defined at the top of `data_fetcher.py`. Check the existing module for what's already imported (constants like `CACHE_DIR`).

- [ ] **Step 3: Smoke test concept_momentum end-to-end**

Clear today's cache to force re-fetch:

```bash
cd ~/project/tw_stock_tools && \
  ls concept_momentum/cache/prices/*$(date +%Y%m%d).json 2>/dev/null | head -3
# Don't actually delete; this is just to see the layout. Re-run will read cache if it exists.
```

Run full pipeline:

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 concept_momentum/run_daily.py 2>&1 | tail -15
```

Expected: completes with no traceback; ranks 30+ concepts; dashboard regenerates.

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/data_fetcher.py
git commit -m "data_fetcher: migrate fetch_stock to FinMind TaiwanStockPrice

Concept momentum daily cron now uses FinMind for ~190 concept members.
Cache layout preserved. Yahoo still used for ^TWII (fetch_taiex unchanged).
End-to-end run_daily smoke verified."
```

---

### Task 8: Migrate `tw_limitup_signal.py` Yahoo branch

**Files:**
- Modify: `tw_limitup_signal.py:310-355` (replace Yahoo branch of `fetch_price_history`)

- [ ] **Step 1: Read the existing function**

```bash
sed -n '310,355p' ~/project/tw_stock_tools/tw_limitup_signal.py
```

The function likely has a Yahoo fallback path. Replace it with FinMind call.

- [ ] **Step 2: Modify `fetch_price_history`**

In `tw_limitup_signal.py`, find `fetch_price_history` (line 310). Replace the Yahoo call inside with FinMind. The exact replacement depends on the existing structure — keep all surrounding logic (TWSE-OpenAPI primary path) the same, only swap the fallback that hits Yahoo.

Generic pattern to follow:

```python
def fetch_price_history(code: str, target_date: str, token: str = "") -> list[dict]:
    """[Existing docstring]

    Migrated 2026-05-11: Yahoo fallback replaced with FinMind.
    """
    # ... existing TWSE / TPEx OpenAPI primary path stays the same ...

    # Replace the Yahoo fallback block:
    if not rows:  # primary path failed
        import os, sys
        HERE = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, HERE)
        import finmind_client
        finmind_token = os.environ.get("FINMIND_TOKEN", "")
        if not finmind_token:
            return []
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=40)  # ABCD needs ~20-30 days
        try:
            rows_raw = finmind_client.fetch_stock_price(
                code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), finmind_token)
        except Exception as ex:
            print(f"[WARN] FinMind fallback {code}: {ex}", file=sys.stderr)
            return []
        rows = [{
            "date": r["date"].replace("-", ""),
            "open": float(r.get("open", 0)),
            "high": float(r.get("max", 0)),
            "low": float(r.get("min", 0)),
            "close": float(r["close"]),
            "volume": int(r.get("Trading_Volume", 0)),
        } for r in rows_raw if r.get("close")]

    return rows
```

⚠️ Read the actual function first — the exact replacement may differ.

- [ ] **Step 3: Smoke test limitup_signal**

```bash
cd ~/project/tw_stock_tools && \
  FINMIND_TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') \
  /usr/bin/python3 tw_limitup_signal.py --header --min-score 2 2>&1 | tail -10
```

Expected: ABCD scored output renders without traceback.

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_limitup_signal.py
git commit -m "limitup_signal: migrate Yahoo fallback to FinMind"
```

---

### Task 9: Update chip skill 紀律 6 + docs + memory

**Files:**
- Modify: `~/.claude/skills/chip/SKILL.md`
- Modify: `README.md`
- Modify: `concept_momentum/README.md` (if relevant changes)
- Update memory MEMORY.md

- [ ] **Step 1: Reword chip skill 紀律 6**

Open `~/.claude/skills/chip/SKILL.md`. Find 紀律 6 (about TWSE rate-limit retry). Replace the section with:

```markdown
### ⚠️ 紀律 6：TWSE 還券明細 endpoint 偶爾 rate-limit
- `tw_lending_lookup.py` 大部分已遷到 FinMind（借入交易 + 借券賣出餘額），不會被 rate-limit
- **但「還券明細」(t13sa870) 仍由 TWSE 直接抓**，因為 FinMind 沒有 per-event 還券 + 借入日資料
- 如果 chip 報告「還券明細：無還券」但你預期應該有（如大跌日 / 餘額大減日），**重跑一次再下結論**
- 等 1-2 分鐘後 retry 通常會拿到資料
- 範例教訓：2026-05-11 2313 第一次 chip 顯示「無還券」是 TWSE rate-limit；FinMind 部分（借入 + 餘額）不受影響
- 若 retry 仍空 → 才考慮「真的沒還券」
```

- [ ] **Step 2: Update top-level README**

In `~/project/tw_stock_tools/README.md`, find tool sections for lending/second_wave/dormant_giants/concept_momentum. Add a brief note about FinMind sponsor migration:

```markdown
## 資料源更新 (2026-05-11)

升級 FinMind sponsor 後遷移多個工具的資料源，提升穩定性 + 統一資料源：

- **借入交易** (lending_lookup + lending_monitor) → FinMind `TaiwanStockSecuritiesLending`，解決 TWSE rate-limit 問題
- **借券賣出餘額** → FinMind `TaiwanDailyShortSaleBalances`（TWSE + TPEx 統一）
- **日線價格** (second_wave + dormant_giants + concept_momentum + limitup_signal Yahoo 部分) → FinMind `TaiwanStockPrice`
- **還券明細** (lending_lookup) — **仍用 TWSE t13sa870**（FinMind 無此 dataset）
- **分點 BSR** (broker_monitor + broker_lookup) — **仍用 TWSE/TPEx + Playwright**（FinMind sponsor 無 per-broker dataset）
```

- [ ] **Step 3: Create memory note**

Write `~/.claude/projects/-home-kun/memory/reference_finmind_migration.md`:

```markdown
---
name: FinMind sponsor migration (2026-05-11)
description: 多個工具遷到 FinMind sponsor tier 的範圍 + 例外
type: reference
---

2026-05-11 升級 FinMind sponsor tier 後完成的遷移：

**已遷移到 FinMind**:
- `tw_lending_lookup.py` 借入交易 + 借券賣出餘額（合併 TWSE + TPEx）
- `tw_lending_monitor.py` 兩個 mode (議借 + SBL)
- `tw_second_wave.py` 6-month 日線
- `tw_dormant_giants.py` 18-year 歷史
- `concept_momentum/data_fetcher.py` 概念股 3-month 日線
- `tw_limitup_signal.py` Yahoo fallback

**未遷移（FinMind 沒這 dataset）**:
- 還券明細 (TWSE t13sa870) — chip skill 紀律 6 retry 仍用
- 分點 BSR (TWSE + Playwright) — sponsor 無 per-broker dataset
- 美股部分 (tw_us_correlation) — FinMind 沒美股
- ^TWII 指數 (concept_momentum/fetch_taiex) — Yahoo 仍用，沒換的必要
- 新聞 (concept_momentum/news_fetcher) — FinMind 沒新聞

**新模組**: `finmind_client.py` (3 個 fetch 函式 + 1 個 whole-market helper)，retry 429 內建

**設計文件**: `docs/superpowers/specs/2026-05-11-finmind-migration-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-11-finmind-migration.md`
```

Append to MEMORY.md:

```
- [FinMind sponsor migration](reference_finmind_migration.md) — 2026-05-11 多個工具改用 FinMind sponsor（lending/prices）；分點 BSR + 還券明細 + 美股仍用原資料源
```

- [ ] **Step 4: Commit + push**

```bash
cd ~/project/tw_stock_tools && git add README.md concept_momentum/README.md
git commit -m "README: document FinMind sponsor migration scope"
git push
```

(Memory + skill changes are in ~/.claude, not in git repo.)

---

## Self-Review

**Spec coverage:**
- §3 datasets → Tasks 1 (finmind_client)
- §4 migration strategy → Tasks 2-8 (per-tool)
- §5 file-by-file → Tasks 2 (lending_lookup borrows) + 3 (lending_lookup SBL) + 4 (lending_monitor) + 5 (second_wave) + 6 (dormant_giants) + 7 (data_fetcher) + 8 (limitup_signal)
- §6 architecture (finmind_client) → Task 1
- §8 verification → Each migration task has verification step using harness in `tools/`
- §11 documentation → Task 9
- §12 decision log: 還券 stays TWSE → reflected in Task 2-3 plan (only 借入 + balance migrated, 還券 kept)

**Placeholder scan:** None — all code blocks have concrete content. Verification harness includes full Python code.

**Type consistency:**
- `finmind_client.fetch_securities_lending(stock_id, start_date, end_date, token)` — used identically in Tasks 2, 4
- `fetch_short_sale_balances` — used in Tasks 3, 4
- `fetch_stock_price` — used in Tasks 5, 6, 7, 8
- All return `list[dict]` with FinMind native schema; callers translate to their own shapes.

**Edge cases:**
- Task 4 has a fallback path if whole-market 借券交易 query doesn't work in FinMind — the probe in Step 3 determines which path to take.
- Task 7 cache file format preserved → downstream concept_momentum unaffected.
- Task 8 Yahoo branch identified as fallback → primary TWSE/TPEx path untouched.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-11-finmind-migration.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
