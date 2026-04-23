#!/usr/bin/env python3
"""
概念股動能分析
計算每個概念的：廣度、持續性、量能、相對強度、綜合評分

評分公式：
  Score = 0.40 * Breadth + 0.20 * Volume + 0.20 * RS + 0.20 * Duration
  各項先標準化到 0-100
"""

import json
import os
import sys
from datetime import datetime


def pct_change(prices: list[float], days: int) -> float:
    """Return pct change over last N trading days."""
    if len(prices) < days + 1:
        return 0.0
    return (prices[-1] - prices[-days - 1]) / prices[-days - 1] * 100


def sma(values: list[float], window: int) -> float:
    """Simple moving average."""
    if len(values) < window:
        return 0.0
    return sum(values[-window:]) / window


def compute_breadth(stocks_data: list[dict], days: int) -> float:
    """Breadth = % of stocks with positive return over N days."""
    if not stocks_data:
        return 0.0
    up = 0
    total = 0
    for s in stocks_data:
        rows = s.get("rows", [])
        if len(rows) < days + 1:
            continue
        closes = [r["close"] for r in rows]
        change = pct_change(closes, days)
        total += 1
        if change > 0:
            up += 1
    return (up / total * 100) if total > 0 else 0.0


def compute_duration(concept_index: list[float]) -> int:
    """Count consecutive days the concept index is above 5-day MA (most recent streak)."""
    if len(concept_index) < 6:
        return 0
    streak = 0
    for i in range(len(concept_index) - 1, 4, -1):
        # 5MA at day i = avg of last 5 including i
        ma = sum(concept_index[i - 4:i + 1]) / 5
        if concept_index[i] > ma:
            streak += 1
        else:
            break
    return streak


def compute_volume_ratio(stocks_data: list[dict]) -> float:
    """Return (5d avg volume / 20d avg volume) for equal-weighted concept volume."""
    if not stocks_data:
        return 0.0
    # Build daily total volume across all stocks
    date_vol = {}
    for s in stocks_data:
        for r in s.get("rows", []):
            date_vol[r["date"]] = date_vol.get(r["date"], 0) + r.get("volume", 0)
    sorted_dates = sorted(date_vol.keys())
    if len(sorted_dates) < 20:
        return 1.0
    last5 = [date_vol[d] for d in sorted_dates[-5:]]
    last20 = [date_vol[d] for d in sorted_dates[-20:]]
    avg5 = sum(last5) / 5
    avg20 = sum(last20) / 20
    return avg5 / avg20 if avg20 > 0 else 1.0


def build_concept_index(stocks_data: list[dict]) -> list[dict]:
    """Equal-weighted concept index. Returns list of {date, value} sorted ascending.
    Value is normalized to 100 at start."""
    if not stocks_data:
        return []

    # Build per-stock normalized series
    all_dates = set()
    stock_series = []
    for s in stocks_data:
        rows = s.get("rows", [])
        if len(rows) < 5:
            continue
        closes = {r["date"]: r["close"] for r in rows}
        first_close = rows[0]["close"]
        if first_close <= 0:
            continue
        normalized = {d: c / first_close * 100 for d, c in closes.items()}
        stock_series.append(normalized)
        all_dates.update(closes.keys())

    if not stock_series:
        return []

    sorted_dates = sorted(all_dates)
    index = []
    for date in sorted_dates:
        values = [s[date] for s in stock_series if date in s]
        if values:
            index.append({"date": date, "value": sum(values) / len(values)})
    return index


def compute_rs(concept_index: list[dict], taiex_rows: list[dict], days: int = 20) -> float:
    """Relative strength: concept return - TAIEX return over last N days."""
    if len(concept_index) < days + 1 or len(taiex_rows) < days + 1:
        return 0.0
    concept_ret = (concept_index[-1]["value"] - concept_index[-days - 1]["value"]) / concept_index[-days - 1]["value"] * 100
    taiex_closes = [r["close"] for r in taiex_rows]
    taiex_ret = pct_change(taiex_closes, days)
    return concept_ret - taiex_ret


def normalize(value: float, min_v: float, max_v: float) -> float:
    """Clip to 0-100 scale."""
    if max_v == min_v:
        return 0.0
    return max(0.0, min(100.0, (value - min_v) / (max_v - min_v) * 100))


def extract_leaders(concept_stocks: list[dict], top_n: int = 5) -> list[dict]:
    """Identify top N leader stocks: sort by 20d return desc, filter 5d return > 0."""
    candidates = []
    for s in concept_stocks:
        rows = s.get("rows", [])
        if len(rows) < 21:
            continue
        closes = [r["close"] for r in rows]
        volumes = [r["volume"] for r in rows]
        ret_5d = pct_change(closes, 5)
        ret_20d = pct_change(closes, 20)
        # volume ratio: last 5d avg / last 20d avg
        vol5 = sum(volumes[-5:]) / 5 if volumes else 0
        vol20 = sum(volumes[-20:]) / 20 if volumes else 0
        vol_ratio = vol5 / vol20 if vol20 > 0 else 1.0
        candidates.append({
            "code": s["code"],
            "name": s.get("name", s["code"]),
            "market": s.get("market", ""),
            "current_price": s.get("current_price", closes[-1]),
            "ret_5d": ret_5d,
            "ret_20d": ret_20d,
            "vol_ratio": vol_ratio,
        })

    # Filter: 5d > 0 (still up short-term), sort by 20d desc
    filtered = [c for c in candidates if c["ret_5d"] > 0]
    if len(filtered) < top_n:
        # Fallback: no 5d filter
        filtered = candidates
    filtered.sort(key=lambda x: x["ret_20d"], reverse=True)
    return filtered[:top_n]


def analyze_concept(theme_key: str, theme_info: dict, stocks_data: dict, taiex_rows: list[dict]) -> dict:
    """Compute all metrics for one concept."""
    codes = theme_info.get("stocks", [])
    concept_stocks = [stocks_data[c] for c in codes if c in stocks_data]

    if len(concept_stocks) < 3:
        return None  # too few stocks

    # Breadth (5d, 20d)
    breadth_5d = compute_breadth(concept_stocks, 5)
    breadth_20d = compute_breadth(concept_stocks, 20)
    breadth_avg = (breadth_5d + breadth_20d) / 2

    # Concept index + duration
    concept_index = build_concept_index(concept_stocks)
    index_values = [p["value"] for p in concept_index]
    duration = compute_duration(index_values) if index_values else 0

    # Volume ratio
    vol_ratio = compute_volume_ratio(concept_stocks)

    # Relative strength vs TAIEX
    rs_20d = compute_rs(concept_index, taiex_rows, 20)
    rs_5d = compute_rs(concept_index, taiex_rows, 5)

    # Concept-level returns
    ret_5d = pct_change(index_values, 5) if len(index_values) > 5 else 0
    ret_20d = pct_change(index_values, 20) if len(index_values) > 20 else 0

    # Normalized scores (each 0-100)
    #   Breadth: 50% → 0, 80% → 100
    breadth_score = normalize(breadth_avg, 50, 80)
    #   Volume: 1.0 → 0, 2.0 → 100
    volume_score = normalize(vol_ratio, 1.0, 2.0)
    #   RS 20d: -5% → 0, +15% → 100
    rs_score = normalize(rs_20d, -5, 15)
    #   Duration: 0 days → 0, 10 days → 100
    duration_score = normalize(duration, 0, 10)

    # Composite
    sustainability_score = (
        0.40 * breadth_score +
        0.20 * volume_score +
        0.20 * rs_score +
        0.20 * duration_score
    )

    # Top 5 leader stocks
    leaders = extract_leaders(concept_stocks, top_n=5)

    return {
        "theme_key": theme_key,
        "name_zh": theme_info.get("name_zh", theme_key),
        "name_en": theme_info.get("name_en", ""),
        "stock_count": len(concept_stocks),
        "codes_available": [s["code"] for s in concept_stocks],
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "breadth_5d": breadth_5d,
        "breadth_20d": breadth_20d,
        "duration": duration,
        "volume_ratio": vol_ratio,
        "rs_5d": rs_5d,
        "rs_20d": rs_20d,
        "breadth_score": breadth_score,
        "volume_score": volume_score,
        "rs_score": rs_score,
        "duration_score": duration_score,
        "sustainability_score": sustainability_score,
        "concept_index": concept_index,
        "leaders": leaders,
    }


# ============================================================
# Historical score time series (3-month trend)
# ============================================================

def _truncate_rows(rows: list[dict], end_date: str) -> list[dict]:
    """Keep only rows with date <= end_date."""
    return [r for r in rows if r["date"] <= end_date]


def compute_score_for_date(theme_info: dict, stocks_data: dict, taiex_rows: list[dict], as_of: str) -> float:
    """Compute sustainability score as if 'as_of' were the current date.
    Uses data up to and including as_of."""
    codes = theme_info.get("stocks", [])
    concept_stocks_full = [stocks_data[c] for c in codes if c in stocks_data]

    # Truncate to as_of
    truncated = []
    for s in concept_stocks_full:
        truncated_rows = _truncate_rows(s.get("rows", []), as_of)
        if len(truncated_rows) >= 20:
            truncated.append({**s, "rows": truncated_rows})

    if len(truncated) < 3:
        return 0.0

    breadth_5d = compute_breadth(truncated, 5)
    breadth_20d = compute_breadth(truncated, 20)
    breadth_avg = (breadth_5d + breadth_20d) / 2

    concept_index = build_concept_index(truncated)
    index_values = [p["value"] for p in concept_index]
    duration = compute_duration(index_values) if index_values else 0

    vol_ratio = compute_volume_ratio(truncated)

    taiex_truncated = _truncate_rows(taiex_rows, as_of)
    rs_20d = compute_rs(concept_index, taiex_truncated, 20)

    breadth_score = normalize(breadth_avg, 50, 80)
    volume_score = normalize(vol_ratio, 1.0, 2.0)
    rs_score = normalize(rs_20d, -5, 15)
    duration_score = normalize(duration, 0, 10)

    return 0.40 * breadth_score + 0.20 * volume_score + 0.20 * rs_score + 0.20 * duration_score


def compute_score_history(theme_info: dict, stocks_data: dict, taiex_rows: list[dict], sample_every: int = 2) -> list[dict]:
    """Compute score for each sampled trading day in the available data range.
    Returns list of {date, score}."""
    # Find all unique trading dates
    all_dates = set()
    for code in theme_info.get("stocks", []):
        if code in stocks_data:
            for r in stocks_data[code].get("rows", []):
                all_dates.add(r["date"])
    sorted_dates = sorted(all_dates)

    # Need at least 20 days of history for score
    if len(sorted_dates) < 21:
        return []

    start_idx = 20
    series = []
    for i in range(start_idx, len(sorted_dates), sample_every):
        date = sorted_dates[i]
        score = compute_score_for_date(theme_info, stocks_data, taiex_rows, date)
        series.append({"date": date, "score": score})
    # Always include last date if not in sample
    if sorted_dates[-1] != series[-1]["date"]:
        score = compute_score_for_date(theme_info, stocks_data, taiex_rows, sorted_dates[-1])
        series.append({"date": sorted_dates[-1], "score": score})
    return series


def add_score_history(concepts: dict, results: list[dict], stocks_data: dict, taiex_rows: list[dict]) -> None:
    """Mutate results in-place: add 'score_history' to each entry."""
    for r in results:
        theme_info = concepts["themes"].get(r["theme_key"])
        if theme_info:
            r["score_history"] = compute_score_history(theme_info, stocks_data, taiex_rows)


def analyze_all(concepts: dict, stocks_data: dict, taiex_rows: list[dict]) -> list[dict]:
    """Analyze all themes. Returns sorted list by sustainability score."""
    results = []
    for key, theme in concepts.get("themes", {}).items():
        result = analyze_concept(key, theme, stocks_data, taiex_rows)
        if result:
            results.append(result)
    results.sort(key=lambda x: x["sustainability_score"], reverse=True)
    return results


if __name__ == "__main__":
    from data_fetcher import fetch_all_concepts, fetch_taiex
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "cache", "concepts.json")) as f:
        concepts = json.load(f)

    stocks = fetch_all_concepts(concepts)
    taiex = fetch_taiex()
    results = analyze_all(concepts, stocks, taiex)

    print(f"{'Rank':<5}{'概念':<22}{'成分':<6}{'5d%':<8}{'20d%':<8}{'廣度':<8}{'持續':<6}{'量比':<8}{'RS20':<8}{'評分':<6}")
    print("-" * 90)
    for i, r in enumerate(results, 1):
        print(f"{i:<5}{r['name_zh'][:20]:<22}{r['stock_count']:<6}"
              f"{r['ret_5d']:>6.2f}  {r['ret_20d']:>6.2f}  "
              f"{r['breadth_20d']:>6.1f}  {r['duration']:>4}  "
              f"{r['volume_ratio']:>6.2f}  {r['rs_20d']:>6.2f}  "
              f"{r['sustainability_score']:>5.1f}")

    # Save
    results_file = os.path.join(here, "cache", "results", f"analysis_{datetime.now().strftime('%Y%m%d')}.json")
    os.makedirs(os.path.dirname(results_file), exist_ok=True)
    # Strip concept_index for JSON (too big)
    for r in results:
        r["concept_index_size"] = len(r.pop("concept_index", []))
    with open(results_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n已存 {results_file}")
