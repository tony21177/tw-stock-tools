#!/usr/bin/env python3
"""backtest_prices — v2 回測價格面板。

v1 (concept_momentum/cache/backtest_prices_all.json) 只有 close/volume，
無法做「隔日開盤進場」也無法算還原報酬。v2 每檔存：
  open/close   — TaiwanStockPrice（未還原；訊號偵測用，與正式篩選器同口徑）
  aopen/aclose — TaiwanStockPriceAdj（還原；報酬衡量用）
  ex_dates     — TaiwanStockDividend 除權息交易日（訊號除污用）
TAIEX 只有 open/close（指數無還原問題）。

用法：
  python3 backtest_prices.py --start 2025-01-01          # build/refresh
  python3 backtest_prices.py --start 2025-01-01 --force  # 強制重抓
"""
import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tw_second_wave import load_universe  # noqa: E402

BT_CACHE = os.path.join(HERE, "bt_cache")
os.makedirs(BT_CACHE, exist_ok=True)
PANEL_PATH = os.path.join(BT_CACHE, "backtest_prices_v2.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    import subprocess
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    return ""


def _fm(dataset: str, data_id: str, start: str, token: str) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": dataset, "data_id": data_id,
                                "start_date": start, "token": token})
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{FINMIND}?{q}", timeout=30) as r:
                return json.loads(r.read().decode()).get("data", [])
        except Exception:
            time.sleep(2)
    return []


def _fetch_one(code: str, name: str, start: str, token: str):
    raw = _fm("TaiwanStockPrice", code, start, token)
    adj = _fm("TaiwanStockPriceAdj", code, start, token)
    div = _fm("TaiwanStockDividend", code, "2024-01-01", token)
    adj_by = {r["date"]: r for r in adj}
    rows = []
    for r in raw:
        c = r.get("close")
        if not c or float(c) <= 0:
            continue
        a = adj_by.get(r["date"], {})
        rows.append({
            "date": r["date"].replace("-", ""),
            "open": float(r.get("open") or 0),
            "close": float(c),
            "volume": float(r.get("Trading_Volume") or 0),
            "aopen": float(a.get("open") or 0),
            "aclose": float(a.get("close") or 0),
        })
    rows.sort(key=lambda x: x["date"])
    ex = set()
    for d in div:
        for k in ("CashExDividendTradingDate", "StockExDividendTradingDate"):
            v = (d.get(k) or "").strip()
            if v:
                ex.add(v.replace("-", ""))
    return rows, sorted(ex)


def _panel_path(start: str) -> str:
    """預設起日用原路徑（向後相容既有面板）；其他起日各自一檔，互不覆蓋。"""
    if start == "2025-01-01":
        return PANEL_PATH
    return os.path.join(BT_CACHE, f"backtest_prices_v2_{start.replace('-', '')}.json")


def build_cache_v2(start: str = "2025-01-01", workers: int = 4, force: bool = False) -> dict:
    path = _panel_path(start)
    if not force and os.path.exists(path):
        with open(path) as f:
            c = json.load(f)
        if c.get("start") == start and c.get("schema") == 2:
            print(f"[cache] v2 面板 {len(c['stocks'])} 檔（--force 可重抓）", file=sys.stderr)
            return c
    token = _token()
    uni = load_universe("all")
    print(f"[fetch] v2 面板：{len(uni)} 檔 × 3 datasets（約 30-60 分鐘）…", file=sys.stderr)
    stocks, ex_dates = {}, {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_fetch_one, code, name, start, token): (code, name)
                for code, name in uni}
        for fut in as_completed(futs):
            code, name = futs[fut]
            done += 1
            try:
                rows, ex = fut.result()
            except Exception as e:
                print(f"  [ERR] {code}: {e}", file=sys.stderr)
                continue
            if len(rows) >= 60:
                stocks[code] = {"code": code, "name": name, "rows": rows}
                ex_dates[code] = ex
            if done % 100 == 0:
                print(f"  {done}/{len(uni)} (有效 {len(stocks)})", file=sys.stderr)
    tx = _fm("TaiwanStockPrice", "TAIEX", start, token)
    taiex = [{"date": r["date"].replace("-", ""),
              "open": float(r.get("open") or r.get("close") or 0),
              "close": float(r.get("close") or 0)}
             for r in tx if r.get("close")]
    if not taiex:
        raise RuntimeError("TAIEX 抓取失敗 (可能 rate limit)，不寫入快取 — 稍後重跑 build")
    c = {"schema": 2, "start": start, "stocks": stocks,
         "ex_dates": ex_dates, "taiex": taiex}
    with open(path, "w") as f:
        json.dump(c, f)
    print(f"[fetch] 完成 {len(stocks)} 檔 → {path}", file=sys.stderr)
    return c


class PricePanel:
    def __init__(self, cache: dict):
        self.stocks = cache["stocks"]
        self.ex_dates = {k: set(v) for k, v in cache.get("ex_dates", {}).items()}
        self.taiex = {r["date"]: r for r in cache["taiex"]}
        self.tx_dates = sorted(self.taiex)
        self.tx_idx = {d: i for i, d in enumerate(self.tx_dates)}
        self._by_code = {}
        self._codes_on = {}
        for code, s in self.stocks.items():
            didx = {r["date"]: i for i, r in enumerate(s["rows"])}
            self._by_code[code] = (s["rows"], didx)
            for d, i in didx.items():
                self._codes_on.setdefault(d, []).append((code, i))

    def fwd(self, code, date, h, entry="next_open"):
        if h < 1:
            return None
        rows, didx = self._by_code.get(code, (None, None))
        if rows is None or date not in didx or date not in self.tx_idx:
            return None
        ti = self.tx_idx[date]
        if ti + h >= len(self.tx_dates):
            return None
        exit_date = self.tx_dates[ti + h]
        j = didx.get(exit_date)
        if j is None:
            return None  # 個股在出場日停牌 → 窗口不對齊，剔除該事件
        x = rows[j].get("aclose") or 0
        tx1 = self.taiex[exit_date]["close"]
        if entry == "next_open":
            entry_date = self.tx_dates[ti + 1]
            j0 = didx.get(entry_date)
            if j0 is None:
                return None
            e = rows[j0].get("aopen") or 0
            tx_e = self.taiex[entry_date]
            tx0 = tx_e.get("open") or tx_e["close"]
        else:  # signal_close
            e = rows[didx[date]].get("aclose") or 0
            tx0 = self.taiex[date]["close"]
        if e <= 0 or x <= 0 or tx0 <= 0 or tx1 <= 0:
            return None
        return ((x / e - 1) * 100, (tx1 / tx0 - 1) * 100)

    def matched_baseline(self, date, h, k=100, entry="next_open", seed=7):
        pool = self._codes_on.get(date, [])
        if not pool:
            return None
        rng = random.Random(f"{seed}:{date}:{h}:{entry}")
        vals = []
        for code, _ in rng.sample(pool, min(k, len(pool))):
            r = self.fwd(code, date, h, entry)
            if r is not None:
                vals.append(r[0] - r[1])
        return statistics.mean(vals) if vals else None

    def has_ex_dividend(self, code, d_from, d_to) -> bool:
        """[d_from, d_to] (YYYYMMDD, 含) 內有無除權息交易日。"""
        return any(d_from <= d <= d_to for d in self.ex_dates.get(code, ()))


def load_panel(start: str = "2025-01-01") -> PricePanel:
    return PricePanel(build_cache_v2(start))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    build_cache_v2(args.start, workers=args.workers, force=args.force)
