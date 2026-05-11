#!/usr/bin/env python3
"""
概念股資料抓取：Yahoo Finance OHLCV + TAIEX benchmark
每檔股票抓 3 個月日線，增量更新快取
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

HERE_FETCHER = os.path.dirname(os.path.abspath(__file__))
TOP_DIR = os.path.dirname(HERE_FETCHER)  # tw_stock_tools root (for finmind_client)
CACHE_DIR = os.path.join(HERE_FETCHER, "cache", "prices")
TAIEX_CACHE = os.path.join(HERE_FETCHER, "cache", "taiex.json")

sys.path.insert(0, HERE_FETCHER)
if TOP_DIR not in sys.path:
    sys.path.insert(0, TOP_DIR)
try:
    from stock_names import get_name as _get_zh_name
except ImportError:
    def _get_zh_name(code, fallback=""):
        return fallback or code

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def ensure_dirs():
    os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_yahoo(symbol: str, range_str: str = "3mo") -> list[dict]:
    """Fetch daily OHLCV. Returns [{date, open, high, low, close, volume}, ...]"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={range_str}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(10)
            return fetch_yahoo(symbol, range_str)
        return []
    except Exception:
        return []

    try:
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        quotes = result.get("indicators", {}).get("quote", [{}])[0]
        opens = quotes.get("open", [])
        highs = quotes.get("high", [])
        lows = quotes.get("low", [])
        closes = quotes.get("close", [])
        volumes = quotes.get("volume", [])

        rows = []
        for i, ts in enumerate(timestamps):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            date_str = datetime.fromtimestamp(ts).strftime("%Y%m%d")
            rows.append({
                "date": date_str,
                "open": opens[i] if i < len(opens) else c,
                "high": highs[i] if i < len(highs) else c,
                "low": lows[i] if i < len(lows) else c,
                "close": c,
                "volume": volumes[i] if i < len(volumes) else 0,
            })
        return rows
    except (KeyError, IndexError, TypeError):
        return []


def _infer_market(code: str) -> str:
    """Infer market (上市/上櫃) from the stock_names ISIN cache.

    The ISIN cache is built by stock_names.py from TWSE public data:
    mode=2 → 上市, mode=4 → 上櫃. We peek at the raw JSON cache file
    to avoid a live HTTP call just for market classification.

    Falls back to "" if cache is unavailable or code not found.
    """
    isin_cache = os.path.join(HERE_FETCHER, "cache", "stock_names_market.json")
    if os.path.exists(isin_cache):
        try:
            with open(isin_cache) as f:
                mkt_map = json.load(f)
            return mkt_map.get(code, "")
        except Exception:
            pass

    # Build + cache a code→market map from the TWSE ISIN pages (once per week)
    import urllib.request as _ur
    import re
    mkt_map: dict = {}
    try:
        for mode, label in [(2, "上市"), (4, "上櫃")]:
            url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            req = _ur.Request(url, headers={"User-Agent": UA})
            with _ur.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            try:
                text = raw.decode("cp950", errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")
            for m in re.finditer(r"<td[^>]*>([A-Z0-9]{3,8})[　\s]+([^\s<][^<]*?)</td>", text):
                c = m.group(1).strip()
                if 4 <= len(c) <= 6:
                    mkt_map[c] = label
        with open(isin_cache, "w") as f:
            json.dump(mkt_map, f, ensure_ascii=False)
    except Exception:
        pass
    return mkt_map.get(code, "")


def fetch_stock(code: str) -> dict:
    """Fetch 3-month daily OHLCV for one concept member via FinMind.

    Migrated 2026-05-11 from Yahoo to FinMind (TaiwanStockPrice dataset).
    Cache layout preserved so downstream analyze_all() works unchanged.

    Returns {code, name, name_en, market, current_price, rows}.
    Per-row shape: {date (YYYYMMDD), open, high, low, close, volume}.
    """
    import finmind_client  # available via TOP_DIR inserted into sys.path at module load

    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {}

    end = datetime.now()
    start = end - timedelta(days=100)  # covers 3+ trading months

    try:
        fm_rows = finmind_client.fetch_stock_price(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as ex:
        print(f"[WARN] FinMind {code}: {ex}", file=sys.stderr)
        return {}

    rows = []
    for r in fm_rows:
        c = r.get("close")
        if c is None or float(c) <= 0:
            continue
        rows.append({
            "date": r["date"].replace("-", ""),          # "2026-05-09" → "20260509"
            "open": float(r.get("open", c)),
            "high": float(r.get("max", c)),              # FinMind uses "max"/"min"
            "low": float(r.get("min", c)),
            "close": float(c),
            "volume": int(r.get("Trading_Volume", 0)),
        })

    if not rows:
        return {}

    zh_name = _get_zh_name(code, code)
    return {
        "code": code,
        "name": zh_name,
        "name_en": "",                                   # FinMind has no English name
        "market": _infer_market(code),                   # 上市/上櫃 from ISIN cache
        "current_price": rows[-1]["close"],
        "rows": rows,
    }


def fetch_and_cache(code: str, force: bool = False) -> dict:
    """Fetch stock data, cache to disk (per-day cache key)."""
    ensure_dirs()
    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CACHE_DIR, f"{code}_{today}.json")
    if os.path.exists(cache_file) and not force:
        with open(cache_file) as f:
            return json.load(f)

    data = fetch_stock(code)
    if data:
        with open(cache_file, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


def fetch_taiex(force: bool = False) -> list[dict]:
    """Fetch TAIEX (weighted index) for benchmark comparison.

    Cache invalidation rule: only treat cache as fresh-for-today if the
    cached rows actually contain today's date (or today is a weekend/holiday
    where no new row should exist). This prevents the bug where an earlier
    intraday fetch returns stale rows but stamps cache with today, locking
    subsequent fetches from getting the real close.
    """
    today = datetime.now().strftime("%Y%m%d")
    is_weekend = datetime.now().weekday() >= 5  # Sat/Sun
    if os.path.exists(TAIEX_CACHE) and not force:
        with open(TAIEX_CACHE) as f:
            cached = json.load(f)
        cached_rows = cached.get("rows", [])
        last_date = cached_rows[-1].get("date") if cached_rows else ""
        # Trust cache only when: stamped today AND either
        #   (a) cached rows include today's date, OR
        #   (b) today is a non-trading day (weekend)
        if cached.get("updated_at") == today and (last_date == today or is_weekend):
            return cached_rows

    rows = fetch_yahoo("^TWII", "3mo")
    if rows:
        with open(TAIEX_CACHE, "w") as f:
            json.dump({"updated_at": today, "rows": rows}, f, ensure_ascii=False)
    return rows


def fetch_all_concepts(concepts: dict, delay: float = 0.6) -> dict:
    """Fetch price data for all stocks in all concepts. Returns {code: data_dict}."""
    ensure_dirs()
    all_codes = set()
    for theme in concepts.get("themes", {}).values():
        for code in theme.get("stocks", []):
            all_codes.add(code)

    print(f"抓取 {len(all_codes)} 檔股票的 3 個月日線...", file=sys.stderr)
    result = {}
    for i, code in enumerate(sorted(all_codes)):
        data = fetch_and_cache(code)
        if data:
            result[code] = data
        time.sleep(delay)
        if (i + 1) % 50 == 0:
            print(f"  進度: {i+1}/{len(all_codes)}", file=sys.stderr)

    print(f"完成，取得 {len(result)} 檔有效資料", file=sys.stderr)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", help="測試單檔抓取")
    parser.add_argument("--all", action="store_true", help="抓所有概念股")
    args = parser.parse_args()

    if args.code:
        data = fetch_and_cache(args.code, force=True)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:500])
    elif args.all:
        with open(os.path.join(os.path.dirname(__file__), "cache", "concepts.json")) as f:
            concepts = json.load(f)
        fetch_all_concepts(concepts)
        fetch_taiex(force=True)
