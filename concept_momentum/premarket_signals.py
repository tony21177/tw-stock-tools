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
