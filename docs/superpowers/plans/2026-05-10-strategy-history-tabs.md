# Strategy History Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three new dashboard tabs (主力雷達歷史榜 / 盤前訊號 / 借券動向) by accumulating strategy outputs into per-day JSON caches, building loaders + renderers per tab, and injecting into the existing concept_momentum dashboard.

**Architecture:** Each strategy gains a `--json-out PATH` flag so its cron run dumps a structured snapshot. Three tab modules (loader + renderer pair each) read multiple days of those snapshots, compute consecutive-appearance counts and tab-specific scores, and return HTML strings. `concept_charts.generate_html()` accepts three new optional params; `run_daily.py` orchestrates loading + rendering + injection. Pattern mirrors the existing market_breadth tab.

**Tech Stack:** Python 3 stdlib only (`json`, `os`, `math`, `glob`, `unittest`). No new pip dependencies. Test framework: stdlib `unittest`.

**Spec:** `docs/superpowers/specs/2026-05-10-strategy-history-tabs-design.md`

---

## File Structure

**Create:**
- `concept_momentum/broker_radar_history.py` — load broker JSONs, compute consecutive count + composite score
- `concept_momentum/broker_radar_renderer.py` — render 主力雷達歷史榜 HTML table
- `concept_momentum/premarket_signals.py` — load TR + 2W JSONs, compute consecutive counts
- `concept_momentum/premarket_signals_renderer.py` — render two stacked tables
- `concept_momentum/lending_history.py` — load lending + sbl JSONs, compute consecutive counts
- `concept_momentum/lending_history_renderer.py` — render two stacked tables
- `concept_momentum/tests/test_broker_radar_history.py`
- `concept_momentum/tests/test_premarket_signals.py`
- `concept_momentum/tests/test_lending_history.py`

**Modify:**
- `tw_broker_monitor.py` — add `--json-out PATH` flag + JSON write
- `tw_lending_monitor.py` — add `--json-out PATH` flag + per-mode JSON writes
- `tw_second_wave.py` — add `--json-out PATH` flag (already has `--quiet` so cron-friendly)
- `tw_daily_screen.py` — already has `--json-out` for full pipeline; verify Layer 2 result is captured
- `concept_momentum/concept_charts.py` — `generate_html()` accepts 3 new `*_html` params, injects 3 new tabs
- `concept_momentum/run_daily.py` — load 3 histories + render + pass to generate_html
- `crontab` — append `--json-out PATH` to relevant cron lines
- `.gitignore` — add 5 new cache dirs
- `README.md` § 11
- `concept_momentum/README.md`

---

## Testing Approach

Same as market_breadth: stdlib `unittest`, no pytest. All new tests run via:

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest discover -s concept_momentum/tests -v
```

Pure-function loaders + renderers get TDD with mock data via `tempfile.mkdtemp()`. Strategy `--json-out` additions are smoke-tested by running the strategy and inspecting the file.

---

### Task 1: Scaffold tests + gitignore cache dirs

**Files:**
- Create: `concept_momentum/tests/test_broker_radar_history.py` (placeholder)
- Create: `concept_momentum/tests/test_premarket_signals.py` (placeholder)
- Create: `concept_momentum/tests/test_lending_history.py` (placeholder)
- Modify: `.gitignore`

- [ ] **Step 1: Create the three placeholder test files**

Each file should contain only:

```python
import unittest


class TestPlaceholder(unittest.TestCase):
    def test_placeholder(self):
        """Replaced in later tasks."""
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
```

Create at `concept_momentum/tests/test_broker_radar_history.py`, `test_premarket_signals.py`, and `test_lending_history.py`.

- [ ] **Step 2: Verify all tests run**

Run:
```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest discover -s concept_momentum/tests -v 2>&1 | tail -5
```

Expected: All existing market_breadth tests + 3 new placeholders all pass.

- [ ] **Step 3: Add cache dirs to .gitignore**

Edit `.gitignore`. Find the existing `concept_momentum/cache/market_breadth/` line and add 5 lines after it:

```
concept_momentum/cache/broker_radar_history/
concept_momentum/cache/turnaround_relay_history/
concept_momentum/cache/second_wave_history/
concept_momentum/cache/lending_radar_history/
concept_momentum/cache/short_retreat_history/
```

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/tests .gitignore
git commit -m "history-tabs: scaffold tests + gitignore 5 new cache dirs"
```

---

### Task 2: Add `--json-out` to `tw_broker_monitor.py`

**Files:**
- Modify: `tw_broker_monitor.py`

- [ ] **Step 1: Add the CLI flag**

Open `/home/kun/project/tw_stock_tools/tw_broker_monitor.py`. Find the argparse block (search for `parser.add_argument("--allow-margin-decrease"`). Add this line right after it:

```python
    parser.add_argument("--json-out", help="將今日結果寫到指定 JSON 檔案路徑（dashboard 歷史榜用）")
```

- [ ] **Step 2: Find where `results` (the analyzed list) is finalized and add JSON write**

Find the line near the end of `main()` that reads `summary = format_summary(results, target_date, args.days)`. Right BEFORE that line, add:

```python
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump({
                "date": datetime.now().strftime("%Y%m%d"),
                "stocks": [
                    {
                        "code": r["code"],
                        "name": r["name"],
                        "current_balance": r["current_balance"],
                        "margin_increase_zhang": r["margin_increase"],
                        "candidates": [
                            {
                                "broker_id": c["broker_id"],
                                "broker_name": c["broker_name"],
                                "active_days": c["active_days"],
                                "total_net_zhang": c["total_net"] // 1000,
                                "correlation": round(c["correlation"], 3),
                            } for c in r["candidates"][:5]
                        ],
                    } for r in results
                ],
            }, f, ensure_ascii=False, indent=2)
        print(f"[broker_monitor] wrote {args.json_out}", file=sys.stderr)
```

Note: `total_net` is in 股 (shares); divide by 1000 → 張. `r` already has `code`, `name`, `current_balance`, `margin_increase`, `candidates`. The `// 1000` integer-divide handles `total_net` correctly (it's always an int multiple of 1000).

- [ ] **Step 3: Smoke test (analyze-only mode skips Playwright, uses cache)**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 tw_broker_monitor.py \
    --top-n 50 --analyze-only --json-out /tmp/broker_test.json 2>&1 | tail -10
echo ""
ls -la /tmp/broker_test.json
/usr/bin/python3 -c "
import json
with open('/tmp/broker_test.json') as f: d = json.load(f)
print(f'date={d[\"date\"]}, stocks={len(d[\"stocks\"])}')
if d['stocks']:
    print('sample:', json.dumps(d['stocks'][0], ensure_ascii=False, indent=2))
"
rm /tmp/broker_test.json
```

Expected: file written, `date` matches today, `stocks` is a list (may be 0 or more depending on cache), each stock has `code/name/current_balance/margin_increase_zhang/candidates` with the new schema.

- [ ] **Step 4: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_broker_monitor.py
git commit -m "broker_monitor: add --json-out for dashboard history tab"
```

---

### Task 3: Add `--json-out` to `tw_lending_monitor.py` (both modes)

**Files:**
- Modify: `tw_lending_monitor.py`

This task is more involved than Task 2 because lending_monitor has TWO modes (`lending` and `sbl`); each writes to a separate JSON file path.

- [ ] **Step 1: Read existing structure**

```bash
grep -n "def main\|format_lending\|format_sbl\|args.mode" ~/project/tw_stock_tools/tw_lending_monitor.py | head
```

Note the function names producing each mode's output (likely `format_lending_alerts` and `format_sbl_alerts` or similar). The actual data list/dict that feeds these formatters is what we serialize.

- [ ] **Step 2: Add the CLI flag**

In the argparse block of `tw_lending_monitor.py`, after the existing args, add:

```python
    parser.add_argument("--json-out-lending",
                        help="議借異常結果寫到 JSON 路徑（dashboard 用）")
    parser.add_argument("--json-out-sbl",
                        help="借券賣出減少結果寫到 JSON 路徑（dashboard 用）")
```

- [ ] **Step 3: Add JSON writes in main()**

After the existing lending alert computation (the variable holding the list of alerts; let's call it `lending_alerts` — read the actual code to confirm the variable name), add:

```python
    if args.mode in ("lending", "both") and args.json_out_lending:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out_lending)) or ".", exist_ok=True)
        with open(args.json_out_lending, "w") as f:
            json.dump({
                "date": (args.date or datetime.now().strftime("%Y%m%d")),
                "stocks": [
                    {
                        "code": a.get("code", ""),
                        "name": a.get("name", a.get("code", "")),
                        "lending_zhang": a.get("today_lending", 0),
                        "ratio_5d": round(a.get("ratio", 0.0), 2),
                        "rate_pct": round(a.get("rate", 0.0), 2),
                    } for a in lending_alerts
                ],
            }, f, ensure_ascii=False, indent=2)
        print(f"[lending_monitor] wrote {args.json_out_lending}", file=sys.stderr)
```

And after the sbl alert computation (variable `sbl_alerts` — confirm by reading code):

```python
    if args.mode in ("sbl", "both") and args.json_out_sbl:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out_sbl)) or ".", exist_ok=True)
        with open(args.json_out_sbl, "w") as f:
            json.dump({
                "date": (args.date or datetime.now().strftime("%Y%m%d")),
                "stocks": [
                    {
                        "code": s.get("code", ""),
                        "name": s.get("name", s.get("code", "")),
                        "balance_change_pct": round(s.get("change_pct", 0.0), 2),
                        "today_change_pct": round(s.get("today_pct", 0.0), 2),
                    } for s in sbl_alerts
                ],
            }, f, ensure_ascii=False, indent=2)
        print(f"[lending_monitor] wrote {args.json_out_sbl}", file=sys.stderr)
```

If actual key names in the alert dicts differ (e.g., `code` vs `stock_code`, `change_pct` vs `balance_diff`), adjust the `.get()` keys to match. Use `.get()` with defaults to be tolerant.

- [ ] **Step 4: Smoke test both modes**

```bash
cd ~/project/tw_stock_tools && \
  TG_BOT_TOKEN= /usr/bin/python3 tw_lending_monitor.py \
    --mode both \
    --json-out-lending /tmp/lend_test.json \
    --json-out-sbl /tmp/sbl_test.json 2>&1 | tail -10
echo ""
ls -la /tmp/lend_test.json /tmp/sbl_test.json
/usr/bin/python3 -c "
import json
for p in ['/tmp/lend_test.json', '/tmp/sbl_test.json']:
    with open(p) as f: d = json.load(f)
    print(f'{p}: date={d[\"date\"]} count={len(d[\"stocks\"])}')
    if d['stocks']:
        print(f'  sample: {d[\"stocks\"][0]}')
"
rm /tmp/lend_test.json /tmp/sbl_test.json
```

Expected: both files exist with `date` matching today and `stocks` lists (may be empty if no alerts today; that's OK).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_lending_monitor.py
git commit -m "lending_monitor: add --json-out-lending / --json-out-sbl"
```

---

### Task 4: Add `--json-out` to `tw_second_wave.py`

**Files:**
- Modify: `tw_second_wave.py`

- [ ] **Step 1: Inspect existing JSON write**

```bash
grep -n "json.dump\|json_out\|--json" ~/project/tw_stock_tools/tw_second_wave.py | head
```

The script already has `json.dump(out, f)` at line ~118 (writing internal cache). We need a separate user-facing `--json-out` that writes the candidate list in our spec's schema.

- [ ] **Step 2: Add the CLI flag**

In argparse, after `--telegram` line, add:

```python
    p.add_argument("--json-out", help="將今日候選寫到 JSON 路徑（dashboard 用）")
```

- [ ] **Step 3: Add JSON write at end of main()**

Find where `candidates` (the final filtered list) is built. Right after that list is finalized but before any quiet-check or telegram push, add:

```python
    if args.json_out:
        import os as _os
        _os.makedirs(_os.path.dirname(_os.path.abspath(args.json_out)) or ".", exist_ok=True)
        from datetime import datetime as _dt
        with open(args.json_out, "w") as _f:
            json.dump({
                "date": _dt.now().strftime("%Y%m%d"),
                "candidates": [
                    {
                        "code": c.get("code", ""),
                        "name": c.get("name", c.get("code", "")),
                        "second_wave_score": round(c.get("score", 0.0), 2),
                        "drop_pct": round(c.get("drop_pct", 0.0), 2),
                        "volume_ratio": round(c.get("vol_ratio", 0.0), 2),
                    } for c in candidates
                ],
            }, _f, ensure_ascii=False, indent=2)
        print(f"[second_wave] wrote {args.json_out}", file=sys.stderr)
```

If candidate dict keys differ from `code/name/score/drop_pct/vol_ratio`, read tw_second_wave.py to verify and adjust `.get()` keys.

- [ ] **Step 4: Smoke test**

```bash
cd ~/project/tw_stock_tools && \
  /usr/bin/python3 tw_second_wave.py --quiet --json-out /tmp/sw_test.json 2>&1 | tail -5
ls -la /tmp/sw_test.json
/usr/bin/python3 -c "
import json
with open('/tmp/sw_test.json') as f: d = json.load(f)
print(f'date={d[\"date\"]} candidates={len(d[\"candidates\"])}')
if d['candidates']:
    print('sample:', d['candidates'][0])
"
rm /tmp/sw_test.json
```

Expected: file written; `candidates` may be empty (no second-wave hits today) or non-empty with the schema fields.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add tw_second_wave.py
git commit -m "second_wave: add --json-out for dashboard tab"
```

---

### Task 5: 主力雷達歷史榜 — loader + composite score (TDD)

**Files:**
- Create: `concept_momentum/broker_radar_history.py`
- Modify: `concept_momentum/tests/test_broker_radar_history.py`

- [ ] **Step 1: Write the failing test**

Replace contents of `concept_momentum/tests/test_broker_radar_history.py`:

```python
import os
import json
import math
import tempfile
import unittest
from concept_momentum.broker_radar_history import (
    composite_score,
    load_broker_radar_rows,
)


class TestCompositeScore(unittest.TestCase):
    def test_score_basic(self):
        # consecutive_days=5, top_broker_net=3000 張, margin_inc=500 張
        # top_factor = log(3001) ≈ 8.006
        # margin_factor = sqrt(500) ≈ 22.36
        # score = 5 * (8.006 + 22.36) / 2 ≈ 75.92
        s = composite_score(consecutive_days=5, top_broker_net_zhang=3000, margin_increase_zhang=500)
        self.assertAlmostEqual(s, 75.9, places=0)

    def test_score_negative_clipped_to_zero(self):
        # negative top_broker / negative margin → factors clipped to 0
        s = composite_score(consecutive_days=3, top_broker_net_zhang=-100, margin_increase_zhang=-200)
        self.assertEqual(s, 0.0)

    def test_score_zero_consecutive(self):
        s = composite_score(consecutive_days=0, top_broker_net_zhang=10000, margin_increase_zhang=10000)
        self.assertEqual(s, 0.0)


class TestLoader(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_day(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def _stock(self, code, name, top_net, margin_inc):
        return {
            "code": code,
            "name": name,
            "current_balance": 100000,
            "margin_increase_zhang": margin_inc,
            "candidates": [
                {"broker_id": "9268", "broker_name": "凱基台北",
                 "active_days": 3, "total_net_zhang": top_net, "correlation": 0.8}
            ],
        }

    def test_consecutive_count_two_days(self):
        self._write_day("20260506", [self._stock("2330", "台積電", 1000, 200)])
        self._write_day("20260507", [self._stock("2330", "台積電", 1500, 250)])
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260507", lookback_days=10)

        # 2330 appears in both days → consecutive 2
        match = [r for r in rows if r["code"] == "2330"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["consecutive_days"], 2)
        self.assertEqual(match[0]["latest_date"], "20260507")
        # uses the LATEST day's margin/top values
        self.assertEqual(match[0]["margin_increase_zhang"], 250)
        self.assertEqual(match[0]["top_broker_net_zhang"], 1500)

    def test_consecutive_breaks_with_gap(self):
        # 2330 appears 5/06, missing 5/07, appears 5/08 → consecutive count = 1 (only most recent run)
        self._write_day("20260506", [self._stock("2330", "台積電", 1000, 200)])
        self._write_day("20260507", [self._stock("2317", "鴻海", 500, 100)])
        self._write_day("20260508", [self._stock("2330", "台積電", 1500, 250)])
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        match = [r for r in rows if r["code"] == "2330"]
        self.assertEqual(match[0]["consecutive_days"], 1)

    def test_sorted_by_score_desc(self):
        # 2330: 5 days * (1500張, 250張) = high
        # 2317: 1 day * (10000張, 1000張) = lower because consecutive_days=1
        for d in ["20260504", "20260505", "20260506", "20260507", "20260508"]:
            self._write_day(d, [self._stock("2330", "台積電", 1500, 250)])
        # 2317 only on the last day
        with open(os.path.join(self.tmpdir, "20260508.json")) as f:
            existing = json.load(f)
        existing["stocks"].append(self._stock("2317", "鴻海", 10000, 1000))
        with open(os.path.join(self.tmpdir, "20260508.json"), "w") as f:
            json.dump(existing, f)

        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        # First row should be 2330 (5-day persistence beats 2317's 1 day with bigger numbers)
        self.assertEqual(rows[0]["code"], "2330")

    def test_empty_dir(self):
        rows = load_broker_radar_rows(self.tmpdir, end_date="20260508", lookback_days=10)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to confirm fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_broker_radar_history -v 2>&1 | tail -10
```

Expected: ImportError or ModuleNotFoundError for `concept_momentum.broker_radar_history`.

- [ ] **Step 3: Implement loader + score**

Create `concept_momentum/broker_radar_history.py`:

```python
"""Broker radar history — load daily JSON snapshots, compute consecutive-day
counts and composite scores, return sorted rows for the dashboard tab.

Pure-function loader. No I/O outside of reading the cache directory.
"""

from __future__ import annotations
import json
import math
import os


def composite_score(consecutive_days: int,
                    top_broker_net_zhang: int,
                    margin_increase_zhang: int) -> float:
    """Composite score: consecutive_days × (log(top_net+1) + sqrt(margin_inc)) / 2.

    Negative inputs clipped to 0 (defensively avoids math errors).
    Zero consecutive_days → 0 (stock not on radar today).
    """
    if consecutive_days <= 0:
        return 0.0
    top = max(top_broker_net_zhang, 0)
    margin = max(margin_increase_zhang, 0)
    top_factor = math.log(top + 1)
    margin_factor = math.sqrt(margin)
    return round(consecutive_days * (top_factor + margin_factor) / 2, 2)


def _load_day(path: str) -> dict:
    """Read one {date}.json. Returns parsed dict or empty dict on error."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def load_broker_radar_rows(cache_dir: str,
                           end_date: str,
                           lookback_days: int = 10) -> list[dict]:
    """Load broker history JSONs, return sorted list of stock rows.

    Each row:
        {code, name, consecutive_days, latest_date,
         top_broker_id, top_broker_name, top_broker_net_zhang,
         margin_increase_zhang, score}

    Sort: score desc, consecutive_days desc, top_broker_net_zhang desc.
    Stocks not present in any of the most recent N consecutive days have
    consecutive_days = 0 and are excluded from the result.
    """
    if not os.path.isdir(cache_dir):
        return []
    files = sorted(f for f in os.listdir(cache_dir)
                   if f.endswith(".json") and f[:8] <= end_date)
    files = files[-lookback_days:]
    if not files:
        return []

    # Build per-day stock-set for consecutive-count, plus latest snapshot
    per_day: list[tuple[str, dict[str, dict]]] = []  # [(date, {code: stock_dict})]
    for fname in files:
        d = _load_day(os.path.join(cache_dir, fname))
        date = d.get("date") or fname[:8]
        by_code = {s["code"]: s for s in d.get("stocks", []) if s.get("code")}
        per_day.append((date, by_code))

    # Compute consecutive_days = N where stock appears in last N days unbroken
    # (counted from the most recent day backwards)
    if not per_day:
        return []
    latest_date = per_day[-1][0]
    rows = []
    seen_codes = set(per_day[-1][1].keys())  # only stocks on latest day
    for code in seen_codes:
        # walk backwards from latest, count unbroken streak
        streak = 0
        latest_stock = None
        for date, by_code in reversed(per_day):
            if code in by_code:
                streak += 1
                if latest_stock is None:
                    latest_stock = by_code[code]
            else:
                break
        if streak == 0:
            continue
        # extract top broker (largest total_net_zhang in candidates list)
        candidates = latest_stock.get("candidates", [])
        if candidates:
            top_c = max(candidates, key=lambda c: c.get("total_net_zhang", 0))
            top_id = top_c.get("broker_id", "")
            top_name = top_c.get("broker_name", "")
            top_net = int(top_c.get("total_net_zhang", 0))
        else:
            top_id, top_name, top_net = "", "", 0
        margin_inc = int(latest_stock.get("margin_increase_zhang", 0))
        score = composite_score(streak, top_net, margin_inc)
        rows.append({
            "code": code,
            "name": latest_stock.get("name", code),
            "consecutive_days": streak,
            "latest_date": latest_date,
            "top_broker_id": top_id,
            "top_broker_name": top_name,
            "top_broker_net_zhang": top_net,
            "margin_increase_zhang": margin_inc,
            "score": score,
        })

    rows.sort(key=lambda r: (-r["score"], -r["consecutive_days"],
                              -r["top_broker_net_zhang"]))
    return rows
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_broker_radar_history -v 2>&1 | tail -10
```

Expected: All 6 tests (3 score + 3 loader + 1 empty) pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/broker_radar_history.py concept_momentum/tests/test_broker_radar_history.py
git commit -m "broker_radar_history: loader + composite score (TDD)"
```

---

### Task 6: 主力雷達歷史榜 — renderer (TDD)

**Files:**
- Create: `concept_momentum/broker_radar_renderer.py`
- Modify: `concept_momentum/tests/test_broker_radar_history.py`

- [ ] **Step 1: Append render tests**

Append to `concept_momentum/tests/test_broker_radar_history.py`:

```python
class TestBrokerRadarRenderer(unittest.TestCase):
    def test_render_basic_row(self):
        from concept_momentum.broker_radar_renderer import render_table
        rows = [{
            "code": "2330", "name": "台積電",
            "consecutive_days": 5, "latest_date": "20260508",
            "top_broker_id": "9268", "top_broker_name": "凱基台北",
            "top_broker_net_zhang": 3000, "margin_increase_zhang": 500,
            "score": 75.9,
        }]
        html = render_table(rows)
        self.assertIn("2330", html)
        self.assertIn("台積電", html)
        self.assertIn("5", html)  # consecutive
        self.assertIn("2026/05/08", html)
        self.assertIn("9268 凱基台北", html)
        self.assertIn("3,000", html)  # net with comma
        self.assertIn("75.9", html)
        self.assertIn("<table", html)

    def test_render_empty_shows_message(self):
        from concept_momentum.broker_radar_renderer import render_table
        html = render_table([])
        self.assertIn("今日無主力雷達訊號", html)
        self.assertNotIn("<table", html)

    def test_render_top_30_only(self):
        from concept_momentum.broker_radar_renderer import render_table
        rows = [{
            "code": f"{1000+i:04d}", "name": f"S{i}",
            "consecutive_days": 1, "latest_date": "20260508",
            "top_broker_id": "9268", "top_broker_name": "凱基",
            "top_broker_net_zhang": 100, "margin_increase_zhang": 100,
            "score": float(50 - i),  # descending so #1 has score 50, #50 has 0
        } for i in range(50)]
        html = render_table(rows)
        # row #1 (S0) present, row #31 (S30) NOT present
        self.assertIn("S0", html)
        self.assertNotIn("<td>S30<", html)
```

- [ ] **Step 2: Run tests to confirm fail**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_broker_radar_history.TestBrokerRadarRenderer -v 2>&1 | tail -10
```

Expected: ImportError for `broker_radar_renderer`.

- [ ] **Step 3: Implement renderer**

Create `concept_momentum/broker_radar_renderer.py`:

```python
"""Render 主力雷達歷史榜 HTML table from sorted rows.

Pure function: list of dicts → HTML string.
"""

EMPTY_MSG = ('<p class="empty-state" style="text-align:center; padding: 40px; '
             'color: #888;">今日無主力雷達訊號</p>')


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def render_table(rows: list[dict], top_n: int = 30) -> str:
    """Render top N rows as HTML table.

    Empty list → friendly message, no <table>.
    """
    if not rows:
        return EMPTY_MSG

    parts = ['<div class="table-scroll" style="overflow-x:auto;">']
    parts.append('<table class="market-breadth">')
    parts.append('<thead><tr>'
                 '<th>排名</th><th>代號</th><th>名稱</th>'
                 '<th>連續天數</th><th>最新入榜</th>'
                 '<th>Top 分點</th><th>區間 Top 分點淨買 (張)</th>'
                 '<th>融資增量 (張)</th><th>綜合分數</th>'
                 '</tr></thead><tbody>')

    for i, r in enumerate(rows[:top_n], start=1):
        broker_label = (f"{r['top_broker_id']} {r['top_broker_name']}"
                        if r.get('top_broker_id') else "—")
        parts.append(
            '<tr>'
            f'<td>{i}</td>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{r["consecutive_days"]}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{broker_label}</td>'
            f'<td>{_fmt_int(r.get("top_broker_net_zhang"))}</td>'
            f'<td>{_fmt_int(r.get("margin_increase_zhang"))}</td>'
            f'<td>{r.get("score", 0):.1f}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_broker_radar_history -v 2>&1 | tail -10
```

Expected: All tests in TestBrokerRadarRenderer pass (3 new + previous passing tests).

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/broker_radar_renderer.py concept_momentum/tests/test_broker_radar_history.py
git commit -m "broker_radar_renderer: HTML table (TDD)"
```

---

### Task 7: 盤前訊號 — loader (TDD)

**Files:**
- Create: `concept_momentum/premarket_signals.py`
- Modify: `concept_momentum/tests/test_premarket_signals.py`

- [ ] **Step 1: Write failing test**

Replace contents of `concept_momentum/tests/test_premarket_signals.py`:

```python
import os
import json
import tempfile
import unittest
from concept_momentum.premarket_signals import (
    load_turnaround_relay_rows,
    load_second_wave_rows,
)


class TestTurnaroundRelay(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, candidates):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "candidates": candidates}, f)

    def test_consecutive_count(self):
        self._write("20260506", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 3}])
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 4}])
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260507",
                                          lookback_days=10)
        match = [r for r in rows if r["code"] == "2313"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["consecutive_days"], 2)
        self.assertEqual(match[0]["abcd_score"], 4)  # latest day's score
        self.assertEqual(match[0]["latest_date"], "20260507")
        self.assertTrue(match[0]["layer1_passed"])

    def test_empty(self):
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260508",
                                          lookback_days=10)
        self.assertEqual(rows, [])

    def test_sort_latest_date_then_consecutive(self):
        # 2313 appears 5/6+5/7 (latest=5/7, streak=2)
        # 2330 appears only 5/8 (latest=5/8, streak=1)
        self._write("20260506", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 3}])
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "layer1_passed": True, "abcd_score": 4}])
        self._write("20260508", [{"code": "2330", "name": "台積電",
                                   "layer1_passed": True, "abcd_score": 2}])
        rows = load_turnaround_relay_rows(self.tmpdir, end_date="20260508",
                                          lookback_days=10)
        # 2330 should come first (later date)
        self.assertEqual(rows[0]["code"], "2330")
        self.assertEqual(rows[1]["code"], "2313")


class TestSecondWave(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, candidates):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "candidates": candidates}, f)

    def test_basic(self):
        self._write("20260507", [{"code": "2313", "name": "華通",
                                   "second_wave_score": 8.5,
                                   "drop_pct": -22.0, "volume_ratio": 5.16}])
        rows = load_second_wave_rows(self.tmpdir, end_date="20260507",
                                     lookback_days=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "2313")
        self.assertEqual(rows[0]["second_wave_score"], 8.5)
        self.assertEqual(rows[0]["consecutive_days"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to confirm fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_premarket_signals -v 2>&1 | tail -10
```

Expected: ImportError for premarket_signals module.

- [ ] **Step 3: Implement loader**

Create `concept_momentum/premarket_signals.py`:

```python
"""Pre-market signals — load 轉機接力 + 強勢股第二波 daily JSONs and compute
consecutive-day counts. Pure-function loaders.
"""

from __future__ import annotations
import json
import os


def _load_day(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _consecutive_streak_to_latest(per_day: list[tuple[str, dict[str, dict]]],
                                   code: str) -> int:
    """Count unbroken streak of `code` appearances ending at the latest day."""
    streak = 0
    for _, by_code in reversed(per_day):
        if code in by_code:
            streak += 1
        else:
            break
    return streak


def _load_per_day(cache_dir: str, end_date: str, lookback_days: int,
                  list_field: str) -> list[tuple[str, dict[str, dict]]]:
    """Read last `lookback_days` JSONs, return [(date, {code: candidate_dict})]."""
    if not os.path.isdir(cache_dir):
        return []
    files = sorted(f for f in os.listdir(cache_dir)
                   if f.endswith(".json") and f[:8] <= end_date)
    files = files[-lookback_days:]
    out = []
    for fname in files:
        d = _load_day(os.path.join(cache_dir, fname))
        date = d.get("date") or fname[:8]
        by_code = {c["code"]: c for c in d.get(list_field, []) if c.get("code")}
        out.append((date, by_code))
    return out


def load_turnaround_relay_rows(cache_dir: str, end_date: str,
                                lookback_days: int = 10) -> list[dict]:
    """Return list of {code, name, latest_date, layer1_passed, abcd_score,
    consecutive_days}, sorted by latest_date desc, consecutive desc, score desc."""
    per_day = _load_per_day(cache_dir, end_date, lookback_days, "candidates")
    if not per_day:
        return []
    # Union of all codes seen across the window
    all_codes = set()
    for _, by_code in per_day:
        all_codes.update(by_code.keys())

    rows = []
    for code in all_codes:
        # find most recent appearance
        latest_appearance = None
        latest_data = None
        for date, by_code in reversed(per_day):
            if code in by_code:
                latest_appearance = date
                latest_data = by_code[code]
                break
        if latest_data is None:
            continue
        streak = _consecutive_streak_to_latest(per_day, code)
        rows.append({
            "code": code,
            "name": latest_data.get("name", code),
            "latest_date": latest_appearance,
            "layer1_passed": bool(latest_data.get("layer1_passed", False)),
            "abcd_score": int(latest_data.get("abcd_score", 0)),
            "consecutive_days": streak,
        })
    rows.sort(key=lambda r: (r["latest_date"], r["consecutive_days"],
                              r["abcd_score"]), reverse=True)
    return rows


def load_second_wave_rows(cache_dir: str, end_date: str,
                           lookback_days: int = 10) -> list[dict]:
    """Return list of {code, name, latest_date, second_wave_score, drop_pct,
    volume_ratio, consecutive_days}, sorted by latest_date desc, consecutive desc,
    score desc."""
    per_day = _load_per_day(cache_dir, end_date, lookback_days, "candidates")
    if not per_day:
        return []
    all_codes = set()
    for _, by_code in per_day:
        all_codes.update(by_code.keys())

    rows = []
    for code in all_codes:
        latest_appearance = None
        latest_data = None
        for date, by_code in reversed(per_day):
            if code in by_code:
                latest_appearance = date
                latest_data = by_code[code]
                break
        if latest_data is None:
            continue
        streak = _consecutive_streak_to_latest(per_day, code)
        rows.append({
            "code": code,
            "name": latest_data.get("name", code),
            "latest_date": latest_appearance,
            "second_wave_score": float(latest_data.get("second_wave_score", 0.0)),
            "drop_pct": float(latest_data.get("drop_pct", 0.0)),
            "volume_ratio": float(latest_data.get("volume_ratio", 0.0)),
            "consecutive_days": streak,
        })
    rows.sort(key=lambda r: (r["latest_date"], r["consecutive_days"],
                              r["second_wave_score"]), reverse=True)
    return rows
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_premarket_signals -v 2>&1 | tail -10
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/premarket_signals.py concept_momentum/tests/test_premarket_signals.py
git commit -m "premarket_signals: loader for TR + second-wave (TDD)"
```

---

### Task 8: 盤前訊號 — renderer (TDD)

**Files:**
- Create: `concept_momentum/premarket_signals_renderer.py`
- Modify: `concept_momentum/tests/test_premarket_signals.py`

- [ ] **Step 1: Append render tests**

Append to `concept_momentum/tests/test_premarket_signals.py`:

```python
class TestPremarketRenderer(unittest.TestCase):
    def test_render_with_data(self):
        from concept_momentum.premarket_signals_renderer import render_table
        tr_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "layer1_passed": True, "abcd_score": 4, "consecutive_days": 3}]
        sw_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "second_wave_score": 8.5, "drop_pct": -22.0,
                    "volume_ratio": 5.16, "consecutive_days": 2}]
        html = render_table(tr_rows, sw_rows)
        # both stocks shown
        self.assertIn("轉機接力", html)
        self.assertIn("強勢股第二波", html)
        self.assertIn("2313", html)
        self.assertIn("4", html)
        self.assertIn("8.5", html)
        self.assertIn("-22.0", html)
        self.assertIn("5.16", html)

    def test_render_both_empty(self):
        from concept_momentum.premarket_signals_renderer import render_table
        html = render_table([], [])
        self.assertIn("近 10 個交易日無候選", html)

    def test_render_one_section_empty(self):
        from concept_momentum.premarket_signals_renderer import render_table
        tr_rows = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "layer1_passed": True, "abcd_score": 4, "consecutive_days": 3}]
        html = render_table(tr_rows, [])
        # TR section has data; 2W section shows empty msg
        self.assertIn("2313", html)
        # Empty msg appears for 2W only
        self.assertEqual(html.count("近 10 個交易日無候選"), 1)
```

- [ ] **Step 2: Run to confirm fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_premarket_signals.TestPremarketRenderer -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement renderer**

Create `concept_momentum/premarket_signals_renderer.py`:

```python
"""Render 盤前訊號 (TR + 強勢股第二波) HTML — two stacked sub-tables."""


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _empty_msg() -> str:
    return ('<p class="empty-state" style="text-align:center; padding: 20px; '
            'color: #888;">近 10 個交易日無候選</p>')


def _render_tr(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>L1 通過</th><th>ABCD 分數</th><th>連續天數</th>'
             '</tr></thead><tbody>']
    for r in rows:
        l1 = '✓' if r.get('layer1_passed') else '—'
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{l1}</td>'
            f'<td>{r.get("abcd_score", 0)}</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_sw(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>第二波分數</th><th>急跌%</th><th>量比</th><th>連續天數</th>'
             '</tr></thead><tbody>']
    for r in rows:
        drop = r.get('drop_pct', 0.0)
        drop_cls = 'pos' if drop > 0 else 'neg' if drop < 0 else ''
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{r.get("second_wave_score", 0):.2f}</td>'
            f'<td class="{drop_cls}">{drop:+.1f}%</td>'
            f'<td>{r.get("volume_ratio", 0):.2f}x</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def render_table(tr_rows: list[dict], sw_rows: list[dict]) -> str:
    """Render two stacked sub-tables. Each section either shows table or
    empty message."""
    return (
        '<h3 style="margin-top: 16px;">🌅 轉機接力 (TR Layer 2 ABCD)</h3>'
        + _render_tr(tr_rows)
        + '<h3 style="margin-top: 24px;">🌅 強勢股第二波</h3>'
        + _render_sw(sw_rows)
    )
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_premarket_signals -v 2>&1 | tail -10
```

Expected: All 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/premarket_signals_renderer.py concept_momentum/tests/test_premarket_signals.py
git commit -m "premarket_signals_renderer: two stacked sub-tables (TDD)"
```

---

### Task 9: 借券動向 — loader (TDD)

**Files:**
- Create: `concept_momentum/lending_history.py`
- Modify: `concept_momentum/tests/test_lending_history.py`

- [ ] **Step 1: Write failing tests**

Replace `concept_momentum/tests/test_lending_history.py`:

```python
import os
import json
import tempfile
import unittest
from concept_momentum.lending_history import (
    load_lending_radar_rows,
    load_short_retreat_rows,
)


class TestLendingRadar(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def test_consecutive_count(self):
        self._write("20260507", [{"code": "3491", "name": "昇達科",
                                    "lending_zhang": 1280, "ratio_5d": 4.2,
                                    "rate_pct": 8.5}])
        self._write("20260508", [{"code": "3491", "name": "昇達科",
                                    "lending_zhang": 800, "ratio_5d": 3.5,
                                    "rate_pct": 7.0}])
        rows = load_lending_radar_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["code"], "3491")
        self.assertEqual(rows[0]["consecutive_days"], 2)
        self.assertEqual(rows[0]["lending_zhang"], 800)  # latest

    def test_empty(self):
        rows = load_lending_radar_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        self.assertEqual(rows, [])


class TestShortRetreat(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write(self, date, stocks):
        with open(os.path.join(self.tmpdir, f"{date}.json"), "w") as f:
            json.dump({"date": date, "stocks": stocks}, f)

    def test_sort_by_balance_change_asc(self):
        # Most negative first (biggest空頭撤退)
        self._write("20260508", [
            {"code": "2313", "name": "華通",
             "balance_change_pct": -11.9, "today_change_pct": 1.6},
            {"code": "3491", "name": "昇達科",
             "balance_change_pct": -14.7, "today_change_pct": 0.0},
        ])
        rows = load_short_retreat_rows(self.tmpdir, end_date="20260508",
                                        lookback_days=5)
        # 3491 should come first (more negative balance_change)
        self.assertEqual(rows[0]["code"], "3491")
        self.assertEqual(rows[1]["code"], "2313")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to confirm fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_lending_history -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement loader**

Create `concept_momentum/lending_history.py`:

```python
"""借券動向 history loaders — 借券雷達 (議借爆量) and 空頭撤退 (餘額大減).

Pure-function loaders.
"""

from __future__ import annotations
import json
import os


def _load_day(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _consecutive_streak(per_day: list[tuple[str, dict[str, dict]]],
                        code: str) -> int:
    streak = 0
    for _, by_code in reversed(per_day):
        if code in by_code:
            streak += 1
        else:
            break
    return streak


def _load_per_day(cache_dir: str, end_date: str,
                  lookback_days: int) -> list[tuple[str, dict[str, dict]]]:
    if not os.path.isdir(cache_dir):
        return []
    files = sorted(f for f in os.listdir(cache_dir)
                   if f.endswith(".json") and f[:8] <= end_date)
    files = files[-lookback_days:]
    out = []
    for fname in files:
        d = _load_day(os.path.join(cache_dir, fname))
        date = d.get("date") or fname[:8]
        by_code = {s["code"]: s for s in d.get("stocks", []) if s.get("code")}
        out.append((date, by_code))
    return out


def load_lending_radar_rows(cache_dir: str, end_date: str,
                             lookback_days: int = 5) -> list[dict]:
    """Return list of {code, name, latest_date, lending_zhang, ratio_5d,
    rate_pct, consecutive_days}, sorted by latest_date desc, consecutive desc,
    lending_zhang desc."""
    per_day = _load_per_day(cache_dir, end_date, lookback_days)
    if not per_day:
        return []
    all_codes = set()
    for _, by_code in per_day:
        all_codes.update(by_code.keys())

    rows = []
    for code in all_codes:
        latest_date = None
        latest = None
        for date, by_code in reversed(per_day):
            if code in by_code:
                latest_date = date
                latest = by_code[code]
                break
        if latest is None:
            continue
        streak = _consecutive_streak(per_day, code)
        rows.append({
            "code": code,
            "name": latest.get("name", code),
            "latest_date": latest_date,
            "lending_zhang": int(latest.get("lending_zhang", 0)),
            "ratio_5d": float(latest.get("ratio_5d", 0.0)),
            "rate_pct": float(latest.get("rate_pct", 0.0)),
            "consecutive_days": streak,
        })
    rows.sort(key=lambda r: (r["latest_date"], r["consecutive_days"],
                              r["lending_zhang"]), reverse=True)
    return rows


def load_short_retreat_rows(cache_dir: str, end_date: str,
                             lookback_days: int = 5) -> list[dict]:
    """Return list of {code, name, latest_date, balance_change_pct,
    today_change_pct, consecutive_days}, sorted by balance_change_pct asc
    (most negative first = biggest空方撤退)."""
    per_day = _load_per_day(cache_dir, end_date, lookback_days)
    if not per_day:
        return []
    all_codes = set()
    for _, by_code in per_day:
        all_codes.update(by_code.keys())

    rows = []
    for code in all_codes:
        latest_date = None
        latest = None
        for date, by_code in reversed(per_day):
            if code in by_code:
                latest_date = date
                latest = by_code[code]
                break
        if latest is None:
            continue
        streak = _consecutive_streak(per_day, code)
        rows.append({
            "code": code,
            "name": latest.get("name", code),
            "latest_date": latest_date,
            "balance_change_pct": float(latest.get("balance_change_pct", 0.0)),
            "today_change_pct": float(latest.get("today_change_pct", 0.0)),
            "consecutive_days": streak,
        })
    rows.sort(key=lambda r: r["balance_change_pct"])  # asc = most negative first
    return rows
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_lending_history -v 2>&1 | tail -10
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/lending_history.py concept_momentum/tests/test_lending_history.py
git commit -m "lending_history: loaders for 借券雷達 + 空頭撤退 (TDD)"
```

---

### Task 10: 借券動向 — renderer (TDD)

**Files:**
- Create: `concept_momentum/lending_history_renderer.py`
- Modify: `concept_momentum/tests/test_lending_history.py`

- [ ] **Step 1: Append render tests**

Append to `concept_momentum/tests/test_lending_history.py`:

```python
class TestLendingRenderer(unittest.TestCase):
    def test_render_lending_radar(self):
        from concept_momentum.lending_history_renderer import render_table
        radar = [{"code": "3491", "name": "昇達科", "latest_date": "20260508",
                  "lending_zhang": 1280, "ratio_5d": 4.2, "rate_pct": 8.5,
                  "consecutive_days": 2}]
        retreat = []
        html = render_table(radar, retreat)
        self.assertIn("借券雷達", html)
        self.assertIn("空頭撤退", html)
        self.assertIn("3491", html)
        self.assertIn("1,280", html)
        self.assertIn("4.20x", html)
        # rate >7% should get pos class
        self.assertIn('class="pos">8.50%', html)

    def test_render_short_retreat_color(self):
        from concept_momentum.lending_history_renderer import render_table
        retreat = [{"code": "2313", "name": "華通", "latest_date": "20260508",
                    "balance_change_pct": -11.9, "today_change_pct": 1.6,
                    "consecutive_days": 1}]
        html = render_table([], retreat)
        # balance_change negative → neg color
        self.assertIn('class="neg">-11.90%', html)
        # today_change positive → pos color
        self.assertIn('class="pos">+1.60%', html)

    def test_render_both_empty(self):
        from concept_momentum.lending_history_renderer import render_table
        html = render_table([], [])
        self.assertEqual(html.count("近 5 個交易日無候選"), 2)
```

- [ ] **Step 2: Run to confirm fails**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_lending_history.TestLendingRenderer -v 2>&1 | tail -10
```

Expected: ImportError.

- [ ] **Step 3: Implement renderer**

Create `concept_momentum/lending_history_renderer.py`:

```python
"""Render 借券動向 (借券雷達 + 空頭撤退) — two stacked sub-tables."""


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _empty_msg() -> str:
    return ('<p class="empty-state" style="text-align:center; padding: 20px; '
            'color: #888;">近 5 個交易日無候選</p>')


def _rate_class(rate: float) -> str:
    """Rate > 7% = pos (red, 高成本做空), < 1% = neg (green, 套利可能), else ''."""
    if rate is None:
        return ""
    if rate > 7:
        return "pos"
    if rate < 1:
        return "neg"
    return ""


def _signed_class(v: float) -> str:
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _render_radar(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>議借量 (張)</th><th>5日均量倍數</th><th>利率%</th>'
             '<th>連續天數</th></tr></thead><tbody>']
    for r in rows:
        rate = r.get("rate_pct", 0.0)
        rate_cls = _rate_class(rate)
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{int(r.get("lending_zhang", 0)):,}</td>'
            f'<td>{r.get("ratio_5d", 0):.2f}x</td>'
            f'<td class="{rate_cls}">{rate:.2f}%</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_retreat(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>餘額變化%</th><th>今日漲跌%</th>'
             '<th>連續天數</th></tr></thead><tbody>']
    for r in rows:
        bc = r.get("balance_change_pct", 0.0)
        tc = r.get("today_change_pct", 0.0)
        bc_cls = _signed_class(bc)
        tc_cls = _signed_class(tc)
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td class="{bc_cls}">{bc:+.2f}%</td>'
            f'<td class="{tc_cls}">{tc:+.2f}%</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def render_table(radar_rows: list[dict], retreat_rows: list[dict]) -> str:
    return (
        '<h3 style="margin-top: 16px;">🌙 借券雷達 (議借爆量)</h3>'
        + _render_radar(radar_rows)
        + '<h3 style="margin-top: 24px;">🌙 空頭撤退 (借券賣餘大減)</h3>'
        + _render_retreat(retreat_rows)
    )
```

- [ ] **Step 4: Run tests**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -m unittest concept_momentum.tests.test_lending_history -v 2>&1 | tail -10
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/lending_history_renderer.py concept_momentum/tests/test_lending_history.py
git commit -m "lending_history_renderer: two stacked sub-tables (TDD)"
```

---

### Task 11: Inject 3 new tabs into concept_charts.py

**Files:**
- Modify: `concept_momentum/concept_charts.py:188-330` (the `generate_html` function)

- [ ] **Step 1: Update function signature**

Find:
```python
def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str,
                  breadth_table_html: str = "") -> str:
```

Replace with:
```python
def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str,
                  breadth_table_html: str = "",
                  broker_radar_html: str = "",
                  premarket_signals_html: str = "",
                  lending_history_html: str = "") -> str:
```

- [ ] **Step 2: Inject 3 new tab buttons**

In the f-string template, find this block:
```html
<div class="tabs">
  <div class="tab active" onclick="showTab('breadth')">📊 大盤寬度</div>
  <div class="tab" onclick="showTab('snap')">🔥 今日快照</div>
```

Replace with (insert 3 new tab buttons between `breadth` and `snap`):
```html
<div class="tabs">
  <div class="tab active" onclick="showTab('breadth')">📊 大盤寬度</div>
  <div class="tab" onclick="showTab('broker')">🎯 主力雷達</div>
  <div class="tab" onclick="showTab('premarket')">🌅 盤前訊號</div>
  <div class="tab" onclick="showTab('lending')">🌙 借券動向</div>
  <div class="tab" onclick="showTab('snap')">🔥 今日快照</div>
```

- [ ] **Step 3: Inject 3 new tab content divs**

Find this block in the template:
```html
<div id="tab-breadth" class="tab-content active chart-wrap">
  <h2>📊 大盤寬度（最近 60 個交易日）</h2>
  <p class="meta">寬度池 = 上市+上櫃 普通股 4 位代號 (~2,300 檔) | 紅 = 漲/買超 / 綠 = 跌/賣超 / 缺值 = —</p>
  {breadth_table_html}
</div>
<div id="tab-snap" class="tab-content chart-wrap">{snapshot_html}</div>
```

Replace with:
```html
<div id="tab-breadth" class="tab-content active chart-wrap">
  <h2>📊 大盤寬度（最近 60 個交易日）</h2>
  <p class="meta">寬度池 = 上市+上櫃 普通股 4 位代號 (~2,300 檔) | 紅 = 漲/買超 / 綠 = 跌/賣超 / 缺值 = —</p>
  {breadth_table_html}
</div>
<div id="tab-broker" class="tab-content chart-wrap">
  <h2>🎯 主力雷達歷史榜（10 日視窗）</h2>
  <p class="meta">綜合分數 = 連續天數 × (log(Top 分點累計淨買 + 1) + sqrt(融資增量)) / 2 | Top 30</p>
  {broker_radar_html}
</div>
<div id="tab-premarket" class="tab-content chart-wrap">
  <h2>🌅 盤前訊號（10 日視窗）</h2>
  <p class="meta">盤前 07:30 / 07:40 cron 跑出的兩層篩選結果</p>
  {premarket_signals_html}
</div>
<div id="tab-lending" class="tab-content chart-wrap">
  <h2>🌙 借券動向（5 日視窗）</h2>
  <p class="meta">盤後 16:00 / 21:30 cron 跑出的議借爆量 + 借券賣餘大減</p>
  {lending_history_html}
</div>
<div id="tab-snap" class="tab-content chart-wrap">{snapshot_html}</div>
```

- [ ] **Step 4: Smoke test with mock data**

```bash
cd ~/project/tw_stock_tools && /usr/bin/python3 -c "
import json, os
from concept_momentum.concept_charts import generate_html
from concept_momentum.broker_radar_renderer import render_table as render_broker
from concept_momentum.premarket_signals_renderer import render_table as render_premarket
from concept_momentum.lending_history_renderer import render_table as render_lending

# Mock data
broker_html = render_broker([{
    'code': '2330', 'name': '台積電',
    'consecutive_days': 5, 'latest_date': '20260508',
    'top_broker_id': '9268', 'top_broker_name': '凱基台北',
    'top_broker_net_zhang': 3000, 'margin_increase_zhang': 500,
    'score': 75.9,
}])
premarket_html = render_premarket(
    [{'code': '2313', 'name': '華通', 'latest_date': '20260508',
      'layer1_passed': True, 'abcd_score': 4, 'consecutive_days': 3}],
    [{'code': '2313', 'name': '華通', 'latest_date': '20260508',
      'second_wave_score': 8.5, 'drop_pct': -22.0,
      'volume_ratio': 5.16, 'consecutive_days': 2}],
)
lending_html = render_lending(
    [{'code': '3491', 'name': '昇達科', 'latest_date': '20260508',
      'lending_zhang': 1280, 'ratio_5d': 4.2, 'rate_pct': 8.5,
      'consecutive_days': 2}],
    [{'code': '2313', 'name': '華通', 'latest_date': '20260508',
      'balance_change_pct': -11.9, 'today_change_pct': 1.6,
      'consecutive_days': 1}],
)

# Need real concept results + taiex
HERE = '/home/kun/project/tw_stock_tools/concept_momentum'
results_files = sorted(os.listdir(os.path.join(HERE, 'cache', 'results')))
with open(os.path.join(HERE, 'cache', 'results', results_files[-1])) as f:
    results = json.load(f)
with open(os.path.join(HERE, 'cache', 'taiex.json')) as f:
    taiex = json.load(f)['rows']

html_path = generate_html(results, taiex, '2026-05-10',
                          breadth_table_html='<p>breadth</p>',
                          broker_radar_html=broker_html,
                          premarket_signals_html=premarket_html,
                          lending_history_html=lending_html)
print(f'wrote: {html_path}')
print(f'size: {os.path.getsize(html_path)} bytes')

# Quick checks
with open(html_path) as f:
    body = f.read()
assert 'tab-broker' in body, 'broker tab id missing'
assert 'tab-premarket' in body, 'premarket tab id missing'
assert 'tab-lending' in body, 'lending tab id missing'
assert '主力雷達歷史榜' in body
assert '盤前訊號' in body
assert '借券動向' in body
assert '台積電' in body
assert '昇達科' in body
print('OK: 3 new tabs rendered with mock data')
"
```

Expected: prints OK with all assertions passing.

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/concept_charts.py
git commit -m "concept_charts: inject 主力雷達 / 盤前訊號 / 借券動向 tabs"
```

---

### Task 12: Hook 3 loaders into run_daily.py

**Files:**
- Modify: `concept_momentum/run_daily.py`

- [ ] **Step 1: Add imports**

Find existing imports near top of `concept_momentum/run_daily.py`:
```python
from market_breadth import run_today as run_market_breadth, BREADTH_DIR
from market_breadth_renderer import render_table
```

Add right after them:
```python
from broker_radar_history import load_broker_radar_rows
from broker_radar_renderer import render_table as render_broker_table
from premarket_signals import load_turnaround_relay_rows, load_second_wave_rows
from premarket_signals_renderer import render_table as render_premarket_table
from lending_history import load_lending_radar_rows, load_short_retreat_rows
from lending_history_renderer import render_table as render_lending_table
```

- [ ] **Step 2: Add cache dir constants near the top of main() or as module-level**

After the existing `HERE` definition (line ~14) add:

```python
BROKER_HISTORY_DIR = os.path.join(HERE, "cache", "broker_radar_history")
TR_HISTORY_DIR = os.path.join(HERE, "cache", "turnaround_relay_history")
SW_HISTORY_DIR = os.path.join(HERE, "cache", "second_wave_history")
LENDING_HISTORY_DIR = os.path.join(HERE, "cache", "lending_radar_history")
RETREAT_HISTORY_DIR = os.path.join(HERE, "cache", "short_retreat_history")
```

- [ ] **Step 3: Build the 3 history HTMLs before generate_html call**

Find the existing block in run_daily.py main():
```python
    # Market breadth — fetch + compute + render
    target_yyyymmdd = datetime.now().strftime("%Y%m%d")
    finmind_token = os.environ.get("FINMIND_TOKEN", "")
    breadth_html = ""
    if finmind_token:
        ...
        breadth_html = render_table(rows)

    html_path = generate_html(results, taiex, target_date, breadth_table_html=breadth_html)
```

Replace `html_path = generate_html(...)` line with:

```python
    # Strategy history tabs
    print("載入策略歷史榜...", file=sys.stderr)
    broker_rows = load_broker_radar_rows(BROKER_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    broker_html = render_broker_table(broker_rows)

    tr_rows = load_turnaround_relay_rows(TR_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    sw_rows = load_second_wave_rows(SW_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    premarket_html = render_premarket_table(tr_rows, sw_rows)

    lending_rows = load_lending_radar_rows(LENDING_HISTORY_DIR, target_yyyymmdd, lookback_days=5)
    retreat_rows = load_short_retreat_rows(RETREAT_HISTORY_DIR, target_yyyymmdd, lookback_days=5)
    lending_html = render_lending_table(lending_rows, retreat_rows)

    html_path = generate_html(
        results, taiex, target_date,
        breadth_table_html=breadth_html,
        broker_radar_html=broker_html,
        premarket_signals_html=premarket_html,
        lending_history_html=lending_html,
    )
```

- [ ] **Step 4: Smoke test full run with --skip-fetch**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 concept_momentum/run_daily.py --skip-fetch 2>&1 | tail -10
```

Expected: prints `載入策略歷史榜...` plus existing concept lines, no traceback.

- [ ] **Step 5: Verify dashboard**

```bash
/usr/bin/python3 -c "
with open('/home/kun/project/tw_stock_tools/concept_momentum/templates/dashboard.html') as f:
    body = f.read()
print('tab-broker:', body.count('tab-broker'))
print('tab-premarket:', body.count('tab-premarket'))
print('tab-lending:', body.count('tab-lending'))
# Empty cache dirs → should show empty-state messages
print('empty broker msg:', '今日無主力雷達訊號' in body)
print('empty 10-day msg:', '近 10 個交易日無候選' in body)
print('empty 5-day msg:', '近 5 個交易日無候選' in body)
"
```

Expected: each tab id appears at least once, all 3 empty-state messages present (because cache dirs are still empty before cron writes).

- [ ] **Step 6: Commit**

```bash
cd ~/project/tw_stock_tools && git add concept_momentum/run_daily.py
git commit -m "run_daily: load + render 主力雷達 / 盤前訊號 / 借券動向 history tabs"
```

---

### Task 13: Update crontab + smoke test

**Files:**
- Modify: `crontab` (system-level via `crontab -e`)

- [ ] **Step 1: Backup current crontab**

```bash
crontab -l > /tmp/crontab.bak.$(date +%Y%m%d_%H%M%S)
echo "Backup created"
```

- [ ] **Step 2: Update crontab entries with `--json-out` paths**

Use `crontab -l | sed | crontab -` style replacements. Run these one at a time and verify with `crontab -l | grep <pattern>` after each:

```bash
# tw_broker_monitor — append --json-out
crontab -l | sed 's|tw_broker_monitor.py --top-n 200 --telegram|tw_broker_monitor.py --top-n 200 --telegram --json-out /home/kun/project/tw_stock_tools/concept_momentum/cache/broker_radar_history/$(date +\\%Y\\%m\\%d).json|' | crontab -
crontab -l | grep tw_broker_monitor

# tw_lending_monitor (lending mode 16:00)
crontab -l | sed 's|tw_lending_monitor.py --mode lending --telegram|tw_lending_monitor.py --mode lending --telegram --json-out-lending /home/kun/project/tw_stock_tools/concept_momentum/cache/lending_radar_history/$(date +\\%Y\\%m\\%d).json|' | crontab -
crontab -l | grep "mode lending"

# tw_lending_monitor (sbl mode 21:30)
crontab -l | sed 's|tw_lending_monitor.py --mode sbl --telegram|tw_lending_monitor.py --mode sbl --telegram --json-out-sbl /home/kun/project/tw_stock_tools/concept_momentum/cache/short_retreat_history/$(date +\\%Y\\%m\\%d).json|' | crontab -
crontab -l | grep "mode sbl"

# tw_second_wave (07:40)
crontab -l | sed 's|tw_second_wave.py --quiet --telegram|tw_second_wave.py --quiet --telegram --json-out /home/kun/project/tw_stock_tools/concept_momentum/cache/second_wave_history/$(date +\\%Y\\%m\\%d).json|' | crontab -
crontab -l | grep tw_second_wave

# tw_daily_screen (07:30) — already supports --json-out, but verify destination is right
# This one already writes to /tmp; update to write to history dir
crontab -l | sed 's|tw_daily_screen.py|tw_daily_screen.py --json-out /home/kun/project/tw_stock_tools/concept_momentum/cache/turnaround_relay_history/$(date +\\%Y\\%m\\%d).json|' | crontab -
crontab -l | grep tw_daily_screen
```

⚠️ **Verify the sed replacements actually changed each line**. The pattern needs to match the EXISTING crontab line exactly. If a sed call doesn't match, you'll see no change and the next `crontab -l | grep` will show the line unchanged. In that case, fix the pattern (e.g., the cron may have different `--top-n N` value or other flags) and try again.

- [ ] **Step 3: Manual smoke test broker_monitor json output**

```bash
mkdir -p /home/kun/project/tw_stock_tools/concept_momentum/cache/broker_radar_history
TODAY=$(date +%Y%m%d)
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 tw_broker_monitor.py \
    --top-n 50 --analyze-only \
    --json-out concept_momentum/cache/broker_radar_history/${TODAY}.json 2>&1 | tail -5

ls -la concept_momentum/cache/broker_radar_history/
/usr/bin/python3 -c "
import json
with open('concept_momentum/cache/broker_radar_history/$TODAY.json') as f:
    d = json.load(f)
print(f'wrote {len(d[\"stocks\"])} stocks for {d[\"date\"]}')
"
```

Expected: file created with stocks list (may be 0+ depending on cache).

- [ ] **Step 4: Re-run dashboard to confirm broker tab now has data**

```bash
cd ~/project/tw_stock_tools && \
  TOKEN=$(crontab -l | grep FINMIND_TOKEN | head -1 | sed 's/.*FINMIND_TOKEN=\([^ ]*\).*/\1/') && \
  TG_BOT_TOKEN= FINMIND_TOKEN=$TOKEN /usr/bin/python3 concept_momentum/run_daily.py --skip-fetch 2>&1 | tail -5

/usr/bin/python3 -c "
with open('/home/kun/project/tw_stock_tools/concept_momentum/templates/dashboard.html') as f:
    body = f.read()
# If broker_radar_history cache has data, the empty-state msg should NOT appear
print('broker tab still empty?:', '今日無主力雷達訊號' in body)
"
```

If broker_radar_history JSON has stocks, the dashboard should show the broker table (not empty-state). If empty, that's fine — the `--analyze-only` smoke test may have written 0 stocks.

- [ ] **Step 5: No commit needed (crontab is system-state, not git)**

The crontab changes happen on this machine only and aren't tracked in git. Move on to Task 14.

---

### Task 14: Documentation + memory update

**Files:**
- Modify: `README.md` § 11
- Modify: `concept_momentum/README.md`
- Create: `~/.claude/projects/-home-kun/memory/reference_strategy_history_tabs.md`
- Modify: `~/.claude/projects/-home-kun/memory/MEMORY.md`

- [ ] **Step 1: Update top-level README § 11**

In `/home/kun/project/tw_stock_tools/README.md`, find the existing line `- **大盤寬度 (Market Breadth)**：dashboard.html 最上方分頁...`. After all the existing 大盤寬度 bullets (the block ending around `quiet rate-limit`), add three new bullets:

```markdown
- **🎯 主力雷達歷史榜**：dashboard 第二分頁，10 日視窗。每日 18:00 cron 跑出的主力分點+融資連動結果累積，依「綜合分數 = 連續天數 × (log(Top 分點淨買+1) + sqrt(融資增量)) / 2」排序，Top 30
- **🌅 盤前訊號**：dashboard 第三分頁，10 日視窗。上下兩段顯示轉機接力 (TR ABCD) 與強勢股第二波，含連續入榜天數
- **🌙 借券動向**：dashboard 第四分頁，5 日視窗。上下兩段顯示借券雷達 (議借爆量) 與空頭撤退 (借券賣餘大減)，依時間/變化幅度排序
- **快取**：5 個新 dir — `concept_momentum/cache/{broker_radar_history,turnaround_relay_history,second_wave_history,lending_radar_history,short_retreat_history}/{date}.json`，皆 gitignored；歷史由 cron 累積，無 backfill
```

- [ ] **Step 2: Add section to concept_momentum/README.md**

Append a new section to `/home/kun/project/tw_stock_tools/concept_momentum/README.md`:

```markdown
## 策略歷史榜三分頁 (Strategy History Tabs)

dashboard 自第二分頁起，依 cron 執行時間順序：

### 主力雷達歷史榜 (broker_radar_history)
- 資料源：`tw_broker_monitor.py` 18:00 cron + `--json-out`
- 視窗：10 個交易日
- 排序：綜合分數降冪
- 公式：`score = 連續天數 × (log(Top 分點累計淨買 張 + 1) + sqrt(融資增量 張)) / 2`

### 盤前訊號 (premarket_signals)
- 資料源：`tw_daily_screen.py` (TR Layer 2) 07:30 + `tw_second_wave.py` 07:40 + `--json-out`
- 視窗：10 個交易日
- 排版：上下兩段（轉機接力 / 第二波）
- 排序：最新入榜日期降冪 → 連續天數降冪 → 分數降冪

### 借券動向 (lending_history)
- 資料源：`tw_lending_monitor.py` 16:00 (lending) + 21:30 (sbl) + `--json-out-*`
- 視窗：5 個交易日
- 排版：上下兩段（議借爆量 / 空頭撤退）
- 排序議借：日期降冪；排序撤退：餘額變化%升冪 (最負先排)

**首次部署無歷史**：cron 動態運算，第一次部署當天起累積，連續天數要等幾天後才有意義。
```

- [ ] **Step 3: Create memory file**

Write `/home/kun/.claude/projects/-home-kun/memory/reference_strategy_history_tabs.md`:

```markdown
---
name: 策略歷史榜三分頁
description: concept_momentum dashboard 第 2-4 分頁，分別對應主力雷達歷史榜（10 日）、盤前訊號（TR + 2W，10 日）、借券動向（議借 + 撤退，5 日），自製功能於 2026-05-10 加入
type: reference
---

dashboard 自上而下分頁順序：
1. 📊 大盤寬度 (active)
2. 🎯 主力雷達 ← NEW (10 日)
3. 🌅 盤前訊號 ← NEW (10 日)
4. 🌙 借券動向 ← NEW (5 日)
5. 🔥 今日快照
6. 📈 3 個月趨勢
7. 強勢族群領漲股
8. 完整排行

**檔案**:
- 主力雷達: `concept_momentum/broker_radar_history.py` + `_renderer.py`
- 盤前訊號: `concept_momentum/premarket_signals.py` + `_renderer.py`
- 借券動向: `concept_momentum/lending_history.py` + `_renderer.py`

**Cache** (gitignored, cron 累積，無 backfill):
- `cache/broker_radar_history/{date}.json` (cron 18:00)
- `cache/turnaround_relay_history/{date}.json` (cron 07:30)
- `cache/second_wave_history/{date}.json` (cron 07:40)
- `cache/lending_radar_history/{date}.json` (cron 16:00)
- `cache/short_retreat_history/{date}.json` (cron 21:30)

**主力雷達綜合分數**:
`score = consecutive_days × (log(top_broker_net_zhang + 1) + sqrt(margin_increase_zhang)) / 2`
負值 clip to 0；連續天數 = 0 → score = 0。

**設計文件**: `docs/superpowers/specs/2026-05-10-strategy-history-tabs-design.md`
**實作計畫**: `docs/superpowers/plans/2026-05-10-strategy-history-tabs.md`
```

- [ ] **Step 4: Update MEMORY.md index**

Append to `/home/kun/.claude/projects/-home-kun/memory/MEMORY.md`:

```
- [策略歷史榜三分頁](reference_strategy_history_tabs.md) — concept_momentum dashboard 第 2-4 分頁：主力雷達歷史榜 / 盤前訊號 / 借券動向；2026-05-10 加入
```

- [ ] **Step 5: Commit + push**

```bash
cd ~/project/tw_stock_tools && git add README.md concept_momentum/README.md
git commit -m "README: document 主力雷達 / 盤前訊號 / 借券動向 history tabs"
git push
```

---

## Self-Review

**1. Spec coverage:**
- §3.1 主力雷達歷史榜 → Tasks 5 (loader+score) + 6 (renderer) + 11 (inject) + 12 (orchestrate)
- §3.2 盤前訊號 → Tasks 7 (loader) + 8 (renderer) + 11 + 12
- §3.3 借券動向 → Tasks 9 (loader) + 10 (renderer) + 11 + 12
- §4 Data flow → Tasks 2-4 (--json-out adds), 13 (cron updates), 12 (orchestration)
- §5 Architecture → File structure section
- §6 Cache layout → Task 1 (.gitignore) + Task 13 (cron writes)
- §7 JSON schema → Tasks 2-4 (schema enforced in --json-out writers)
- §8 UI integration → Task 11 (tab order, default-active stays on breadth)
- §9 Edge cases → Renderers handle empty cases (Tasks 6, 8, 10); loaders return [] on missing dir
- §10 Testing → 3 test classes per loader/renderer; integration via --skip-fetch smoke (Task 12)
- §11 Implementation order → Tasks ordered: --json-out adds → loaders → renderers → injection → run_daily → cron → docs
- §12 Decision Log → Reflected in renderer + composite score formula

**2. Placeholder scan:**
- All code blocks have actual content
- No TBD/TODO
- "Add appropriate error handling" not used; error handling shown explicitly (try/except in `_load_day` helpers, `os.makedirs(..., exist_ok=True)`)

**3. Type consistency:**
- `consecutive_days` (int), `latest_date` (str YYYYMMDD), `score` (float) — consistent across broker_radar_history loader, renderer, and integration test mock
- `total_net_zhang` field name in JSON schema (Task 2) matches what loader reads (Task 5) and renderer formats (Task 6) — verified
- `balance_change_pct` and `today_change_pct` (Task 3) match loader (Task 9) and renderer (Task 10)
- `second_wave_score` / `drop_pct` / `volume_ratio` field names consistent across Task 4 (writer), Task 7 (loader), Task 8 (renderer)

---

Plan complete and saved to `docs/superpowers/plans/2026-05-10-strategy-history-tabs.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
