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


import urllib.request
import urllib.parse
import time

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def fetch_universe_one_day(date: str, finmind_token: str) -> list[dict]:
    """Fetch all stocks' close prices for a single trading day from FinMind.

    `date` in YYYY-MM-DD format. Returns list of
        [{code, close, volume}]
    Filtered to 4-digit numeric codes (excludes ETF/REITs/warrants/sector indices).

    Raises RuntimeError on API error (4xx/5xx or status != 200 in payload).

    Note: FinMind's TaiwanStockPrice requires start_date+end_date (not just `date`).
    Sponsor-tier account required for the all-stocks variant.
    """
    import re
    params = {
        "dataset": "TaiwanStockPrice",
        "start_date": date,
        "end_date": date,
        "token": finmind_token,
    }
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"FinMind HTTP {e.code} for {date}: {body[:200]}")
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
