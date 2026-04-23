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

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "prices")
TAIEX_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "taiex.json")

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


def fetch_stock(code: str) -> dict:
    """Fetch stock with .TW first, fallback .TWO. Returns {name, market, rows}."""
    for suffix in [".TW", ".TWO"]:
        symbol = code + suffix
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10)
                return fetch_stock(code)
            continue
        except Exception:
            continue

        try:
            result = data["chart"]["result"][0]
            meta = result["meta"]
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
                rows.append({
                    "date": datetime.fromtimestamp(ts).strftime("%Y%m%d"),
                    "open": opens[i] if i < len(opens) else c,
                    "high": highs[i] if i < len(highs) else c,
                    "low": lows[i] if i < len(lows) else c,
                    "close": c,
                    "volume": volumes[i] if i < len(volumes) else 0,
                })
            if not rows:
                continue
            return {
                "code": code,
                "name": meta.get("shortName", code),
                "market": "上櫃" if suffix == ".TWO" else "上市",
                "current_price": meta.get("regularMarketPrice"),
                "rows": rows,
            }
        except (KeyError, IndexError, TypeError):
            continue
    return {}


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
    """Fetch TAIEX (weighted index) for benchmark comparison."""
    today = datetime.now().strftime("%Y%m%d")
    if os.path.exists(TAIEX_CACHE) and not force:
        with open(TAIEX_CACHE) as f:
            cached = json.load(f)
        if cached.get("updated_at") == today:
            return cached.get("rows", [])

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
