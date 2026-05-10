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
