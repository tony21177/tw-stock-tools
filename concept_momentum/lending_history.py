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
            "ratio_5d": (None if latest.get("ratio_5d") is None
                          else float(latest.get("ratio_5d"))),
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
