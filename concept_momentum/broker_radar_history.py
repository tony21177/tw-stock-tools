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
