# 權證量能訊號策略 — 實作計畫（Phase 1-2：資料層 + 核心回測）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立權證每日資料層（抓取+按標的彙總+日檔），並用歷史資料回測「爆量×失衡」訊號對現股短期漲跌有無 edge，決定是否進上線層。

**Architecture:** 三個模組（比照 concept_money_flow 模式，放 `concept_momentum/`）：`warrant_flow.py` 抓 TWSE 六類權證 + 按標的彙總 + 寫日檔 `cache/warrant_flow/{date}.json`；`warrant_signal.py` 由日檔算爆量倍數 + 認購佔比 Δ + 方向標記；`warrant_signal_backtest.py` 事件研究驗證分方向 edge。純資料 + 回測，**不含網頁/推播**（Phase 3 gated on 本回測結果，另立計畫）。

**Tech Stack:** Python 3（unittest，非 pytest）；TWSE `MI_INDEX` REST（urllib，仿 tw_margin_monitor `_http_get_json`）；FinMind `TaiwanStockPrice`（現股收盤，仿 finmind_client）；無新第三方套件。

## Global Constraints

- **測試框架 unittest**（repo 無 pytest）；測試放 `tests/`，開頭 `sys.path.insert` repo root + concept_momentum。
- **從 repo root 跑測試**：`cd ~/project/tw_stock_tools && python3 -m unittest tests.<name>`。
- **權證六類 type code**（TWSE `MI_INDEX?type=<T>&response=json&date=YYYYMMDD`）：`0999`=認購、`0999C`=牛證、`0999X`=可展延牛證（以上偏多）；`0999P`=認售、`0999B`=熊證、`0999Y`=可展延熊證（以上偏空）。回應 `tables` 中唯一有 `title` 的表為權證表，欄位順序固定見 Task 1。
- **TWSE 限流**：連續請求會被擋 → 每次 fetch 間 `time.sleep(delay)`（預設 ≥3s），失敗 retry。
- **金額單位**：權證「成交金額」欄位單位為元；「成交股數」為股。彙總金額以元存、顯示除 1e8 為億（顯示層 Phase 3 處理，本計畫存元）。
- **NEVER `git add -A` / `git add .`**：只 stage 明確路徑。
- **commit trailer**：每個 commit 末尾加
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 與
  `Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR`。
- **先驗未回測**：訊號門檻皆為先驗假設，正是本回測要驗證的；程式註解與輸出不得宣稱已驗證。

---

## 檔案結構

- Create `concept_momentum/warrant_flow.py` — 抓取 + 彙總 + 日檔 + backfill CLI
- Create `concept_momentum/warrant_signal.py` — 由日檔算訊號 rows
- Create `concept_momentum/warrant_signal_backtest.py` — 事件研究回測 + 參數掃描 + JSON
- Create `tests/test_warrant_flow.py`
- Create `tests/test_warrant_signal.py`
- Create `tests/test_warrant_signal_backtest.py`
- 日檔目錄 `concept_momentum/cache/warrant_flow/`（程式自建）

---

### Task 1: 權證類型登錄 + 名稱解析 + 單日抓取

**Files:**
- Create: `concept_momentum/warrant_flow.py`
- Test: `tests/test_warrant_flow.py`

**Interfaces:**
- Produces:
  - `WARRANT_TYPES: dict[str, str]` — type code → `"bull"`/`"bear"`（偏多/偏空方向）
  - `parse_issuer(name: str) -> str` — 權證名稱 → 發行券商（無法解析回 `""`）
  - `_parse_warrant_table(payload: dict) -> list[dict]` — TWSE JSON → rows，每 row `{code, name, underlying, underlying_name, turnover, volume, trades}`（金額元、量股，非數字/空值跳過）
  - `fetch_warrant_day(date_yyyymmdd, delay=3.0, retries=3) -> list[dict]` — 抓六類合併，每 row 另含 `side`（bull/bear，來自 WARRANT_TYPES）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_flow.py
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_flow as wf


class TestTypesAndIssuer(unittest.TestCase):
    def test_type_direction(self):
        self.assertEqual(wf.WARRANT_TYPES["0999"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999C"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999X"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999P"], "bear")
        self.assertEqual(wf.WARRANT_TYPES["0999B"], "bear")
        self.assertEqual(wf.WARRANT_TYPES["0999Y"], "bear")

    def test_parse_issuer(self):
        self.assertEqual(wf.parse_issuer("AES凱基57購02"), "凱基")
        self.assertEqual(wf.parse_issuer("台積電元大99購01"), "元大")
        self.assertEqual(wf.parse_issuer("鴻海統一88售03"), "統一")

    def test_parse_issuer_unknown(self):
        self.assertEqual(wf.parse_issuer("XYZ"), "")


class TestParseTable(unittest.TestCase):
    PAYLOAD = {"stat": "OK", "tables": [
        {"title": "115年07月20日 每日收盤行情(認購權證(不含牛證))",
         "fields": ["暫停交易", "證券代號", "證券名稱", "成交股數", "成交筆數",
                    "成交金額", "開盤價", "最高價", "最低價", "收盤價",
                    "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量",
                    "最後揭示賣價", "最後揭示賣量", "本益比", "標的代號",
                    "標的名稱", "標的收盤價/指數"],
         "data": [
            ["", "030012", "AES凱基57購02", "36,000", "36", "3,600",
             "0.01", "0.02", "0.01", "0.01", "-", "0.00", "0.01", "100",
             "0.02", "50", "-", "2308", "台達電", "1,250.00"],
            ["", "030099", "壞資料", "-", "-", "-", "-", "-", "-", "-",
             "-", "-", "-", "-", "-", "-", "-", "2330", "台積電", "-"],
         ]}]}

    def test_parse_ok_row(self):
        rows = wf._parse_warrant_table(self.PAYLOAD)
        self.assertEqual(len(rows), 1)   # 壞資料列跳過
        r = rows[0]
        self.assertEqual(r["code"], "030012")
        self.assertEqual(r["underlying"], "2308")
        self.assertEqual(r["turnover"], 3600.0)
        self.assertEqual(r["volume"], 36000)

    def test_parse_no_title_table(self):
        self.assertEqual(wf._parse_warrant_table({"tables": [{}]}), [])
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow -v`
Expected: FAIL（`No module named 'warrant_flow'`）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_flow.py
#!/usr/bin/env python3
"""權證每日資料層 — 抓 TWSE 六類權證、按標的現股彙總、寫日檔.

⚠ 訊號門檻為先驗假設、未經回測。權證量主要由券商造市/避險驅動，
單看絕對量無意義（見設計文件 2026-07-21-warrant-signal-design.md）。
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_DIR = os.path.join(HERE, "cache", "warrant_flow")
MI_INDEX = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            "?type={type}&response=json&date={date}")
UA = "Mozilla/5.0"

# type code → 方向（偏多 bull / 偏空 bear）
WARRANT_TYPES = {
    "0999": "bull",    # 認購權證(不含牛證)
    "0999C": "bull",   # 牛證
    "0999X": "bull",   # 可展延牛證
    "0999P": "bear",   # 認售權證(不含熊證)
    "0999B": "bear",   # 熊證
    "0999Y": "bear",   # 可展延熊證
}

# 權證名稱 = [標的簡稱][券商][流水][購/售][序]，券商名擷取用
_ISSUERS = ("凱基", "元大", "統一", "富邦", "永豐", "群益", "國泰", "兆豐",
            "中信", "元富", "第一金", "康和", "日盛", "台新", "華南", "宏遠",
            "麥格理", "花旗", "高盛", "摩根")


def parse_issuer(name: str) -> str:
    for iss in _ISSUERS:
        if iss in name:
            return iss
    return ""


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(",", ""))
        return v
    except (TypeError, ValueError):
        return None


def _parse_warrant_table(payload: dict) -> list[dict]:
    tables = [t for t in payload.get("tables", []) if t.get("title")]
    rows = []
    for t in tables:
        for d in t.get("data", []):
            if len(d) < 20:
                continue
            turnover = _num(d[5])
            volume = _num(d[3])
            if turnover is None or volume is None:
                continue    # 壞/空值列跳過
            rows.append({
                "code": str(d[1]), "name": str(d[2]),
                "volume": int(volume), "trades": int(_num(d[4]) or 0),
                "turnover": turnover,
                "underlying": str(d[17]), "underlying_name": str(d[18]),
            })
    return rows


def _fetch_json(url: str, retries: int, delay: float) -> dict | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 2))
                continue
            print(f"[WARN] {e}: {url[:90]}", file=sys.stderr)
    return None


def fetch_warrant_day(date_yyyymmdd: str, delay: float = 3.0,
                      retries: int = 3) -> list[dict]:
    out = []
    for i, (ty, side) in enumerate(WARRANT_TYPES.items()):
        if i:
            time.sleep(delay)
        payload = _fetch_json(
            MI_INDEX.format(type=ty, date=date_yyyymmdd), retries, delay)
        if not payload or payload.get("stat") != "OK":
            continue
        for r in _parse_warrant_table(payload):
            r["side"] = side
            out.append(r)
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow -v`
Expected: PASS（5 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_flow.py tests/test_warrant_flow.py
git commit -m "$(cat <<'EOF'
warrant-flow: type registry + issuer parse + day fetch/parse

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

### Task 2: 按標的現股彙總

**Files:**
- Modify: `concept_momentum/warrant_flow.py`
- Test: `tests/test_warrant_flow.py`（加 class）

**Interfaces:**
- Consumes: `fetch_warrant_day` rows（含 `side`, `underlying`, `turnover`, `volume`, `name`）
- Produces:
  - `aggregate_by_underlying(rows: list[dict]) -> dict` — key=標的代號，value=
    `{bull_turnover, bear_turnover, bull_vol, bear_vol, n_warrants, issuers: {issuer: turnover}, top_warrants: [{code,name,issuer,side,turnover} ×≤5]}`
    （只計標的為 4 位數普通股，排除指數型標的如 `IX0001`）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_flow.py 追加
class TestAggregate(unittest.TestCase):
    ROWS = [
        {"code": "030001", "name": "台達電凱基購01", "side": "bull",
         "underlying": "2308", "turnover": 1000.0, "volume": 10000},
        {"code": "030002", "name": "台達電元大購02", "side": "bull",
         "underlying": "2308", "turnover": 3000.0, "volume": 20000},
        {"code": "070001", "name": "台達電凱基售01", "side": "bear",
         "underlying": "2308", "turnover": 500.0, "volume": 5000},
        {"code": "030999", "name": "台指凱基購", "side": "bull",
         "underlying": "IX0001", "turnover": 9999.0, "volume": 100},
    ]

    def test_aggregate_call_put(self):
        agg = wf.aggregate_by_underlying(self.ROWS)
        self.assertIn("2308", agg)
        self.assertNotIn("IX0001", agg)   # 指數標的排除
        u = agg["2308"]
        self.assertEqual(u["bull_turnover"], 4000.0)
        self.assertEqual(u["bear_turnover"], 500.0)
        self.assertEqual(u["n_warrants"], 3)

    def test_issuer_distribution(self):
        u = wf.aggregate_by_underlying(self.ROWS)["2308"]
        self.assertEqual(u["issuers"]["凱基"], 1500.0)  # 1000 + 500
        self.assertEqual(u["issuers"]["元大"], 3000.0)

    def test_top_warrants_sorted(self):
        u = wf.aggregate_by_underlying(self.ROWS)["2308"]
        self.assertEqual(u["top_warrants"][0]["code"], "030002")  # 最大額
        self.assertLessEqual(len(u["top_warrants"]), 5)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow.TestAggregate -v`
Expected: FAIL（`aggregate_by_underlying` 不存在）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_flow.py 追加
def aggregate_by_underlying(rows: list[dict]) -> dict:
    agg: dict[str, dict] = {}
    for r in rows:
        code = r["underlying"]
        if not re.fullmatch(r"\d{4}", code):
            continue    # 只留 4 位數普通股標的（排除指數 IX...）
        u = agg.setdefault(code, {
            "bull_turnover": 0.0, "bear_turnover": 0.0,
            "bull_vol": 0, "bear_vol": 0, "n_warrants": 0,
            "issuers": {}, "_all": []})
        side = r["side"]
        u[f"{side}_turnover"] += r["turnover"]
        u[f"{side}_vol"] += r["volume"]
        u["n_warrants"] += 1
        iss = parse_issuer(r["name"])
        if iss:
            u["issuers"][iss] = u["issuers"].get(iss, 0.0) + r["turnover"]
        u["_all"].append({"code": r["code"], "name": r["name"],
                          "issuer": iss, "side": side,
                          "turnover": r["turnover"]})
    for u in agg.values():
        u["top_warrants"] = sorted(u.pop("_all"),
                                   key=lambda w: -w["turnover"])[:5]
    return agg
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow -v`
Expected: PASS（8 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_flow.py tests/test_warrant_flow.py
git commit -m "$(cat <<'EOF'
warrant-flow: aggregate by underlying (call/put/issuer/top)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

### Task 3: run_day 日檔寫入 + backfill CLI

**Files:**
- Modify: `concept_momentum/warrant_flow.py`
- Test: `tests/test_warrant_flow.py`

**Interfaces:**
- Consumes: `fetch_warrant_day`, `aggregate_by_underlying`
- Produces:
  - `run_day(date_yyyymmdd, rows=None) -> dict` — 彙總 + 原子寫 `FLOW_DIR/{date}.json`（schema `{date, underlyings: {code: {...}}}`）；`rows` 給定時不抓（測試用），回寫入的 dict
  - `load_day(date_yyyymmdd) -> dict | None`
  - CLI：`--date YYYYMMDD`（單日）/`--backfill N`（近 N 交易日，交易日取自 `market_breadth._twii_trading_dates`，仿 concept_money_flow）/`--delay`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_flow.py 追加
import tempfile, json as _json
class TestRunDay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = wf.FLOW_DIR
        wf.FLOW_DIR = self.tmp.name

    def tearDown(self):
        wf.FLOW_DIR = self._orig
        self.tmp.cleanup()

    def test_run_day_writes_file(self):
        rows = [{"code": "030001", "name": "台達電凱基購01", "side": "bull",
                 "underlying": "2308", "turnover": 1000.0, "volume": 10000}]
        out = wf.run_day("20260720", rows=rows)
        self.assertEqual(out["date"], "20260720")
        self.assertIn("2308", out["underlyings"])
        path = os.path.join(self.tmp.name, "20260720.json")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(wf.load_day("20260720")["date"], "20260720")

    def test_load_missing(self):
        self.assertIsNone(wf.load_day("20250101"))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow.TestRunDay -v`
Expected: FAIL（`run_day` 不存在）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_flow.py 追加
def run_day(date_yyyymmdd: str, rows: list[dict] | None = None) -> dict:
    if rows is None:
        rows = fetch_warrant_day(date_yyyymmdd)
    day = {"date": date_yyyymmdd,
           "underlyings": aggregate_by_underlying(rows)}
    os.makedirs(FLOW_DIR, exist_ok=True)
    path = os.path.join(FLOW_DIR, f"{date_yyyymmdd}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False)
    os.replace(tmp, path)
    return day


def load_day(date_yyyymmdd: str) -> dict | None:
    path = os.path.join(FLOW_DIR, f"{date_yyyymmdd}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", type=int)
    ap.add_argument("--delay", type=float, default=3.0)
    args = ap.parse_args()
    if args.backfill:
        sys.path.insert(0, HERE)
        import market_breadth
        dates = market_breadth._twii_trading_dates()[-args.backfill:]
        for d in dates:
            dd = d.replace("-", "")
            if load_day(dd):
                continue
            print(f"[warrant] {dd} …", file=sys.stderr)
            run_day(dd)
            time.sleep(args.delay)
    else:
        d = args.date or __import__("datetime").datetime.now().strftime("%Y%m%d")
        run_day(d)
        print(f"[warrant] wrote {d}", file=sys.stderr)


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_flow -v`
Expected: PASS（10 tests）

- [ ] **Step 5: 真實單日 smoke（非測試，人工驗證）**

Run: `cd ~/project/tw_stock_tools && python3 concept_momentum/warrant_flow.py --date 20260720 && python3 -c "import sys; sys.path.insert(0,'concept_momentum'); import warrant_flow as wf; d=wf.load_day('20260720'); print('標的數', len(d['underlyings'])); print('2330' in d['underlyings'])"`
Expected: 標的數 數百、含權值股；印出範例確認 bull/bear turnover 合理

- [ ] **Step 6: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_flow.py tests/test_warrant_flow.py
git commit -m "$(cat <<'EOF'
warrant-flow: run_day day-file + backfill CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

### Task 4: 訊號計算（爆量 × 失衡 × 方向）

**Files:**
- Create: `concept_momentum/warrant_signal.py`
- Test: `tests/test_warrant_signal.py`

**Interfaces:**
- Consumes: 日檔 list（由舊到新），每個 `{date, underlyings: {code: {bull_turnover, bear_turnover, ...}}}`
- Produces:
  - `SURGE_MIN = 2.0`、`SHARE_DELTA_MIN = 0.10`（先驗門檻常數）
  - `build_signal_rows(day_files, surge_min=SURGE_MIN, delta_min=SHARE_DELTA_MIN) -> list[dict]` — 最新一日每檔標的：
    `{code, warrant_turnover, surge_ratio, bull_share, bull_share_20d, bull_share_delta, direction}`
    - `surge_ratio` = 今日權證總成交金額 ÷ 前 20 日均（不足用現有天數）
    - `bull_share` = bull_turnover / (bull+bear)
    - `bull_share_delta` = 今日 bull_share − 前 20 日 bull_share 均
    - `direction`：surge≥surge_min 且 |delta|≥delta_min → `"bull"`（delta>0）/`"bear"`（delta<0）；surge≥surge_min 但 |delta|<delta_min → `"neutral"`；surge<surge_min → `""`（不入選）
    - 依 surge_ratio 降冪排序，只回 surge≥surge_min 的

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_signal.py
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_signal as ws


def _day(date, bull, bear):
    return {"date": date, "underlyings": {
        "2308": {"bull_turnover": bull, "bear_turnover": bear,
                 "bull_vol": 0, "bear_vol": 0, "n_warrants": 1,
                 "issuers": {}, "top_warrants": []}}}


class TestSignal(unittest.TestCase):
    def test_surge_and_bull_direction(self):
        # 前 20 日總量 100（bull80/bear20，bull_share 0.8），今日爆量到 400、
        # bull_share 升到 0.95 → delta +0.15 → bull
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 380, 20))
        rows = ws.build_signal_rows(days)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertAlmostEqual(r["surge_ratio"], 4.0, places=1)
        self.assertGreater(r["bull_share_delta"], 0.10)
        self.assertEqual(r["direction"], "bull")

    def test_bear_direction(self):
        # 今日認售/熊證放量 → bull_share 大降 → bear
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 100, 300))  # 總量 400 爆量, bull_share 0.25
        rows = ws.build_signal_rows(days)
        self.assertEqual(rows[0]["direction"], "bear")

    def test_neutral_when_balanced(self):
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 320, 80))  # 爆量但 bull_share 仍 0.8, delta 0
        rows = ws.build_signal_rows(days)
        self.assertEqual(rows[0]["direction"], "neutral")

    def test_no_surge_excluded(self):
        days = [_day(f"202606{i:02d}", 80, 20) for i in range(1, 21)]
        days.append(_day("20260701", 90, 20))  # 沒爆量
        self.assertEqual(ws.build_signal_rows(days), [])
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal -v`
Expected: FAIL（`No module named 'warrant_signal'`）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_signal.py
#!/usr/bin/env python3
"""權證訊號 — 由 warrant_flow 日檔算爆量×失衡×方向.

⚠ 門檻先驗、未回測（見 warrant_signal_backtest.py）。
"""
SURGE_MIN = 2.0
SHARE_DELTA_MIN = 0.10


def _total(u: dict) -> float:
    return (u.get("bull_turnover", 0.0) or 0.0) + (u.get("bear_turnover", 0.0) or 0.0)


def build_signal_rows(day_files: list[dict], surge_min: float = SURGE_MIN,
                      delta_min: float = SHARE_DELTA_MIN) -> list[dict]:
    if not day_files:
        return []
    latest = day_files[-1]
    rows = []
    for code, cur in latest.get("underlyings", {}).items():
        tot = _total(cur)
        if tot <= 0:
            continue
        # 前 N 日（不含今日）總量與 bull_share 序列
        prior_tot, prior_share = [], []
        for df in day_files[:-1]:
            u = df.get("underlyings", {}).get(code)
            if not u:
                continue
            t = _total(u)
            if t > 0:
                prior_tot.append(t)
                prior_share.append((u.get("bull_turnover", 0.0) or 0.0) / t)
        prior_tot = prior_tot[-20:]
        prior_share = prior_share[-20:]
        if not prior_tot:
            continue
        surge = tot / (sum(prior_tot) / len(prior_tot))
        if surge < surge_min:
            continue
        bull_share = (cur.get("bull_turnover", 0.0) or 0.0) / tot
        base_share = sum(prior_share) / len(prior_share) if prior_share else bull_share
        delta = bull_share - base_share
        if abs(delta) >= delta_min:
            direction = "bull" if delta > 0 else "bear"
        else:
            direction = "neutral"
        rows.append({
            "code": code, "warrant_turnover": tot,
            "surge_ratio": round(surge, 2),
            "bull_share": round(bull_share, 3),
            "bull_share_20d": round(base_share, 3),
            "bull_share_delta": round(delta, 3),
            "direction": direction,
        })
    rows.sort(key=lambda r: -r["surge_ratio"])
    return rows
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal -v`
Expected: PASS（4 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_signal.py tests/test_warrant_signal.py
git commit -m "$(cat <<'EOF'
warrant-signal: surge x imbalance direction tagging

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

### Task 5: 回測 — 前瞻報酬 + 分方向統計

**Files:**
- Create: `concept_momentum/warrant_signal_backtest.py`
- Test: `tests/test_warrant_signal_backtest.py`

**Interfaces:**
- Consumes: `warrant_signal.build_signal_rows`；現股收盤 `{code: {date: close}}`（測試注入、正式從 FinMind）
- Produces:
  - `forward_return(closes, code, signal_date, horizon) -> float | None` — 訊號日收盤 → +horizon 交易日收盤報酬（%）；資料不足回 None
  - `evaluate(day_files, closes, horizon=5, surge_min=2.0, delta_min=0.10) -> dict` — 對每一日產生訊號、算前瞻報酬，分 bull/bear 彙總：
    `{"bull": {n, win_rate, median, mean}, "bear": {...}, "baseline": {n, median, mean}}`
    - bull 勝率 = 前瞻報酬 > 0 比例；bear 勝率 = 前瞻報酬 < 0 比例
    - baseline = 全標的全日的前瞻報酬分布（同 horizon）

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_signal_backtest.py
import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_signal_backtest as bt


class TestForwardReturn(unittest.TestCase):
    CLOSES = {"2308": {"20260701": 100.0, "20260702": 102.0,
                       "20260703": 105.0, "20260704": 108.0,
                       "20260705": 110.0, "20260708": 121.0}}

    def test_forward_return(self):
        # 20260701 收 100 → +3 交易日(20260704) 收 108 → +8%
        r = bt.forward_return(self.CLOSES, "2308", "20260701", 3)
        self.assertAlmostEqual(r, 8.0, places=1)

    def test_insufficient(self):
        self.assertIsNone(bt.forward_return(self.CLOSES, "2308",
                                            "20260708", 5))


class TestEvaluate(unittest.TestCase):
    def _days(self, bull, bear):
        base = [{"date": f"202606{i:02d}", "underlyings":
                 {"2308": {"bull_turnover": 80, "bear_turnover": 20}}}
                for i in range(1, 21)]
        base.append({"date": "20260701", "underlyings":
                     {"2308": {"bull_turnover": bull, "bear_turnover": bear}}})
        return base

    def test_bull_signal_counts_win(self):
        days = self._days(380, 20)   # bull 訊號 on 20260701
        closes = {"2308": {"20260701": 100.0, "20260702": 103.0,
                           "20260703": 106.0, "20260704": 109.0,
                           "20260705": 112.0, "20260708": 115.0}}
        # 每個 signal_date 需要 day_files 前綴 → evaluate 內部逐日切
        res = bt.evaluate(days, closes, horizon=3, surge_min=2.0)
        self.assertEqual(res["bull"]["n"], 1)
        self.assertEqual(res["bull"]["win_rate"], 1.0)  # +9% > 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal_backtest -v`
Expected: FAIL（模組不存在）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_signal_backtest.py
#!/usr/bin/env python3
"""權證訊號回測 — 事件研究，分方向驗證 edge.

⚠ 結果誠實呈現有無 edge；無 edge 則不上線（見設計文件）。
"""
import os
import sys
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warrant_signal as ws


def forward_return(closes: dict, code: str, signal_date: str,
                   horizon: int) -> float | None:
    series = closes.get(code, {})
    dates = sorted(series)
    if signal_date not in dates:
        return None
    i = dates.index(signal_date)
    if i + horizon >= len(dates):
        return None
    p0, p1 = series[signal_date], series[dates[i + horizon]]
    if not p0:
        return None
    return (p1 / p0 - 1) * 100


def _stats(vals: list[float], win_cmp) -> dict:
    if not vals:
        return {"n": 0, "win_rate": None, "median": None, "mean": None}
    wins = sum(1 for v in vals if win_cmp(v))
    return {"n": len(vals), "win_rate": round(wins / len(vals), 3),
            "median": round(statistics.median(vals), 2),
            "mean": round(statistics.mean(vals), 2)}


def evaluate(day_files: list[dict], closes: dict, horizon: int = 5,
             surge_min: float = 2.0, delta_min: float = 0.10) -> dict:
    bull_ret, bear_ret, base_ret = [], [], []
    # 逐日：用該日(含)之前的 day_files 產生訊號，算前瞻報酬
    for end in range(21, len(day_files) + 1):
        window = day_files[:end]
        sig_date = window[-1]["date"]
        rows = ws.build_signal_rows(window, surge_min=surge_min,
                                    delta_min=delta_min)
        for r in rows:
            fr = forward_return(closes, r["code"], sig_date, horizon)
            if fr is None:
                continue
            if r["direction"] == "bull":
                bull_ret.append(fr)
            elif r["direction"] == "bear":
                bear_ret.append(fr)
        # baseline：該日所有標的（不論訊號）
        for code in window[-1].get("underlyings", {}):
            fr = forward_return(closes, code, sig_date, horizon)
            if fr is not None:
                base_ret.append(fr)
    return {
        "horizon": horizon,
        "bull": _stats(bull_ret, lambda v: v > 0),
        "bear": _stats(bear_ret, lambda v: v < 0),
        "baseline": _stats(base_ret, lambda v: v > 0),
    }
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal_backtest -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_signal_backtest.py tests/test_warrant_signal_backtest.py
git commit -m "$(cat <<'EOF'
warrant-backtest: forward-return event study by direction

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

### Task 6: 參數掃描 + CLI（讀日檔 + FinMind 收盤 → JSON 報告）

**Files:**
- Modify: `concept_momentum/warrant_signal_backtest.py`
- Test: `tests/test_warrant_signal_backtest.py`

**Interfaces:**
- Consumes: `evaluate`；`warrant_flow.load_day`；FinMind `finmind_client.fetch_stock_price`
- Produces:
  - `sweep(day_files, closes, horizons, surge_grid, delta_grid) -> list[dict]` — 每組參數一列結果（含 bull/bear/baseline stats）
  - CLI：`--backfill-days N`（讀 `warrant_flow/*.json` 近 N 日 + 抓對應現股收盤）、`--json-out PATH`（寫掃描結果）；印摘要表

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_warrant_signal_backtest.py 追加
class TestSweep(unittest.TestCase):
    def test_sweep_grid(self):
        days = [{"date": f"202606{i:02d}", "underlyings":
                 {"2308": {"bull_turnover": 80, "bear_turnover": 20}}}
                for i in range(1, 21)]
        days.append({"date": "20260701", "underlyings":
                     {"2308": {"bull_turnover": 380, "bear_turnover": 20}}})
        closes = {"2308": {d["date"]: 100.0 + i for i, d in enumerate(days)}}
        grid = bt.sweep(days, closes, horizons=[1, 3],
                        surge_grid=[2.0, 3.0], delta_grid=[0.10])
        # 2 horizons × 2 surge × 1 delta = 4 組
        self.assertEqual(len(grid), 4)
        self.assertTrue(all("bull" in g and "horizon" in g for g in grid))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal_backtest.TestSweep -v`
Expected: FAIL（`sweep` 不存在）

- [ ] **Step 3: 寫最小實作**

```python
# concept_momentum/warrant_signal_backtest.py 追加
def sweep(day_files, closes, horizons, surge_grid, delta_grid) -> list[dict]:
    out = []
    for h in horizons:
        for sg in surge_grid:
            for dg in delta_grid:
                res = evaluate(day_files, closes, horizon=h,
                               surge_min=sg, delta_min=dg)
                out.append({"horizon": h, "surge_min": sg, "delta_min": dg,
                            "bull": res["bull"], "bear": res["bear"],
                            "baseline": res["baseline"]})
    return out


def _main():
    import argparse, glob, json
    import warrant_flow as wf
    sys.path.insert(0, os.path.dirname(HERE))  # repo root for finmind_client
    import finmind_client
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-days", type=int, default=120)
    ap.add_argument("--json-out")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(wf.FLOW_DIR, "*.json")))[-args.backfill_days:]
    day_files = [json.load(open(f, encoding="utf-8")) for f in files]
    if not day_files:
        print("[backtest] 無 warrant_flow 日檔，先 backfill", file=sys.stderr)
        return
    codes = set()
    for df in day_files:
        codes.update(df.get("underlyings", {}))
    start = day_files[0]["date"]
    end = day_files[-1]["date"]
    tok = os.environ.get("FINMIND_TOKEN", "")
    s_iso = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e_iso = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    closes = {}
    for c in codes:
        try:
            rows = finmind_client.fetch_stock_price(c, s_iso, e_iso, tok)
            closes[c] = {r["date"].replace("-", ""): r["close"]
                         for r in rows if r.get("close")}
        except Exception:
            continue
    grid = sweep(day_files, closes, horizons=[1, 3, 5, 10],
                 surge_grid=[2.0, 3.0, 5.0], delta_grid=[0.10, 0.15])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"start": start, "end": end, "grid": grid}, f,
                      ensure_ascii=False, indent=1)
    for g in grid:
        b, be, ba = g["bull"], g["bear"], g["baseline"]
        print(f"h{g['horizon']} surge{g['surge_min']} d{g['delta_min']}: "
              f"多 n{b['n']} 勝{b['win_rate']} 中{b['median']} | "
              f"空 n{be['n']} 勝{be['win_rate']} 中{be['median']} | "
              f"基準 中{ba['median']}")


if __name__ == "__main__":
    _main()
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd ~/project/tw_stock_tools && python3 -m unittest tests.test_warrant_signal_backtest -v`
Expected: PASS（4 tests）

- [ ] **Step 5: 真實回測（人工，決定 gate）**

Run:
```bash
cd ~/project/tw_stock_tools
FINMIND_TOKEN=$(crontab -l | grep -oE 'FINMIND_TOKEN=[^ ]+' | head -1 | cut -d= -f2) \
  python3 concept_momentum/warrant_flow.py --backfill 120 --delay 3
FINMIND_TOKEN=$(crontab -l | grep -oE 'FINMIND_TOKEN=[^ ]+' | head -1 | cut -d= -f2) \
  python3 concept_momentum/warrant_signal_backtest.py --backfill-days 120 \
  --json-out concept_momentum/cache/warrant_backtest.json
```
Expected: 印出各參數的 多/空/基準 勝率與中位數 → **人工判讀有無 edge**（多方勝率與中位數是否顯著高於基準；空方樣本是否足夠）。此為 gate：有 edge 才寫 Phase 3 上線計畫。

- [ ] **Step 6: Commit**

```bash
cd ~/project/tw_stock_tools
git add concept_momentum/warrant_signal_backtest.py tests/test_warrant_signal_backtest.py
git commit -m "$(cat <<'EOF'
warrant-backtest: parameter sweep + FinMind CLI + JSON report

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014mBeNtDPXKPZzALRyMn8SR
EOF
)"
```

---

## 完成後（Gate 決策）

跑完 Task 6 的真實回測，看多/空方相對基準有無統計顯著 edge：
- **有 edge** → 寫 Phase 3 計畫（每日掃描 cron + JSON 歷史 + `/warrant-signal` 網頁分頁 + LINE/TG 推播 + 履約價/到期日條款 cache + 近到期過濾），更新 README + memory。
- **無 edge / 僅單方向有** → 記錄回測結論於設計文件，只保留有效部分或停止；不硬上無效訊號（誠實原則）。

## Self-Review 對照 spec

- 資料層（六類抓取+標的彙總+日檔）→ Task 1-3 ✓
- 發行券商（名稱解析）→ Task 1-2 ✓
- 爆量×失衡×方向（相對自身基準）→ Task 4 ✓
- 回測分方向 edge + 參數掃描 → Task 5-6 ✓
- 履約價/到期日/近到期過濾 + 網頁/推播 → **Phase 3（gated，另立計畫）**，spec 已載明依回測結果
- caveat（造市陷阱、認售稀薄、先驗未回測）→ 模組 docstring + gate 決策 ✓
