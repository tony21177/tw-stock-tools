#!/usr/bin/env python3
"""
Rerating 偵測器

對每檔股票計算它與「自己被分到的概念」vs「其他所有概念」的相關係數。
如果一檔股票跟其他概念的相關性 > 跟原概念的相關性，可能該股票正在 rerate。

公式：
  daily_return(stock, t) = (close[t] - close[t-1]) / close[t-1]
  相關係數(stock, concept) = Pearson(stock daily returns, concept index daily returns)
  rerating_score = max_other_corr - own_corr
  rerating_score > 0.1 → 顯示為「疑似 rerating」
"""

import math
from collections import defaultdict


def daily_returns(prices: list[float]) -> list[float]:
    """Compute daily returns from a list of closes."""
    return [(prices[i] - prices[i-1]) / prices[i-1]
            for i in range(1, len(prices)) if prices[i-1] > 0]


def correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation."""
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)


def linear_beta(stock_rets: list[float], market_rets: list[float]) -> float:
    """Compute β (regression slope) of stock returns vs market returns."""
    n = min(len(stock_rets), len(market_rets))
    if n < 10:
        return 1.0
    xs = market_rets[-n:]
    ys = stock_rets[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    varx = sum((x - mx) ** 2 for x in xs)
    return cov / varx if varx > 0 else 1.0


def excess_returns(stock_rets: list[float], market_rets: list[float]) -> list[float]:
    """Return market-beta-adjusted excess returns: stock_ret - β × market_ret.
    Both lists must be same length and aligned by date."""
    if len(stock_rets) != len(market_rets) or len(stock_rets) < 10:
        return stock_rets
    beta = linear_beta(stock_rets, market_rets)
    return [s - beta * m for s, m in zip(stock_rets, market_rets)]


def compute_rerating(concepts: dict, results: list[dict], stocks_data: dict,
                     taiex_rows: list[dict] | None = None,
                     window_days: int = 60,
                     mega_cap_taiex_corr_threshold: float = 0.85) -> list[dict]:
    """For each stock, compute correlation between BETA-ADJUSTED excess returns
    of stock vs each concept index. Skip "broad-market" stocks (high TAIEX corr).
    Use recent N days for rerating signal (default 20 = ~1 month).

    Improvements over naive version:
    - β-adjusted excess returns (removes broad-market co-movement)
    - Filter mega-caps with corr(stock, TAIEX) > threshold (萬有引力 effect)
    - Recent window (rerating is a phase change, not long-term correlation)
    """
    # Build code → list of assigned concepts
    code_to_concepts = defaultdict(list)
    for theme_key, theme in concepts.get("themes", {}).items():
        for code in theme.get("stocks", []):
            code_to_concepts[code].append(theme_key)

    # TAIEX returns (for β adjustment)
    taiex_rets = []
    taiex_dates = []
    if taiex_rows:
        taiex_closes = [r["close"] for r in taiex_rows if r.get("close")]
        taiex_dates = [r["date"] for r in taiex_rows if r.get("close")][1:]
        taiex_rets = daily_returns(taiex_closes)

    # Build concept index returns (also β-adjusted vs TAIEX)
    concept_excess_rets = {}
    concept_dates = {}
    for r in results:
        # Prefer equal-weighted index for correlation (stable across filter/weighting changes)
        ci = r.get("concept_index_equal") or r.get("concept_index", [])
        if not ci or len(ci) < 6:
            continue
        values = [p["value"] for p in ci]
        rets = daily_returns(values)
        dates = [p["date"] for p in ci][1:]

        # Align with TAIEX and compute excess
        taiex_map = dict(zip(taiex_dates, taiex_rets))
        paired = [(rets[i], taiex_map[d]) for i, d in enumerate(dates) if d in taiex_map]
        if len(paired) >= 10:
            c_rets = [p[0] for p in paired]
            t_rets = [p[1] for p in paired]
            paired_dates = [d for d in dates if d in taiex_map]
            excess = excess_returns(c_rets, t_rets)
            concept_excess_rets[r["theme_key"]] = (paired_dates, excess)
        else:
            concept_excess_rets[r["theme_key"]] = (dates, rets)

    # Limit to recent window
    def tail_window(dates: list[str], values: list[float]) -> tuple[list[str], list[float]]:
        if len(dates) <= window_days:
            return dates, values
        return dates[-window_days:], values[-window_days:]

    results_list = []
    for code, info in stocks_data.items():
        rows = info.get("rows", [])
        # Need at least 30 days; will use whatever's available up to window_days
        if len(rows) < 30:
            continue
        closes = [r["close"] for r in rows if r.get("close")]
        stock_rets = daily_returns(closes)
        stock_dates = [r["date"] for r in rows if r.get("close")][1:]

        # Filter: skip mega-caps that move with TAIEX
        if taiex_rets:
            taiex_map = dict(zip(taiex_dates, taiex_rets))
            paired_t = [(stock_rets[i], taiex_map[d])
                         for i, d in enumerate(stock_dates) if d in taiex_map]
            if len(paired_t) < 10:
                continue
            sx = [p[0] for p in paired_t]
            tx = [p[1] for p in paired_t]
            taiex_corr = correlation(sx, tx)
            if taiex_corr > mega_cap_taiex_corr_threshold:
                continue  # broad-market mover, skip
            # Compute excess returns
            stock_excess = excess_returns(sx, tx)
            stock_dates_aligned = [d for d in stock_dates if d in taiex_map]
        else:
            taiex_corr = 0.0
            stock_excess = stock_rets
            stock_dates_aligned = stock_dates

        # Limit to recent window
        stock_dates_aligned, stock_excess = tail_window(stock_dates_aligned, stock_excess)

        # Compute correlation between stock_excess and each concept's excess returns
        corr_by_concept = {}
        for theme_key, (c_dates, c_excess) in concept_excess_rets.items():
            c_dates_w, c_excess_w = tail_window(c_dates, c_excess)
            stock_map = dict(zip(stock_dates_aligned, stock_excess))
            paired = [(stock_map[d], c_excess_w[i])
                       for i, d in enumerate(c_dates_w) if d in stock_map]
            if len(paired) < 10:
                continue
            sx = [p[0] for p in paired]
            sy = [p[1] for p in paired]
            corr_by_concept[theme_key] = correlation(sx, sy)

        if not corr_by_concept:
            continue

        own = code_to_concepts.get(code, [])
        own_corrs = [corr_by_concept[k] for k in own if k in corr_by_concept]
        own_max = max(own_corrs) if own_corrs else 0.0

        other = {k: v for k, v in corr_by_concept.items() if k not in own}
        if not other:
            continue
        top_other_key = max(other, key=other.get)
        top_other_corr = other[top_other_key]

        rerating_score = top_other_corr - own_max if own else top_other_corr

        results_list.append({
            "code": code,
            "name": info.get("name", code),
            "market": info.get("market", ""),
            "taiex_corr": taiex_corr,
            "assigned_concepts": own,
            "own_max_corr": own_max,
            "top_other_concept": top_other_key,
            "top_other_corr": top_other_corr,
            "rerating_score": rerating_score,
            "all_correlations": corr_by_concept,
        })

    results_list.sort(key=lambda x: -x["rerating_score"])
    return results_list


def format_rerating_report(rerating: list[dict], concepts: dict, top_n: int = 30) -> str:
    """Format top N rerating candidates as text."""
    lines = ["【可能 Rerating 標的】"]
    lines.append("（與其他概念相關性 > 與原所屬概念相關性 0.1 以上）")
    lines.append("")

    theme_names = {k: v["name_zh"] for k, v in concepts["themes"].items()}

    # Higher threshold (0.15) since excess returns have lower magnitudes than raw
    candidates = [r for r in rerating if r["rerating_score"] >= 0.15
                   and r["assigned_concepts"]][:top_n]

    if not candidates:
        lines.append("（過濾大盤 β 後無顯著 rerating 訊號）")
        return "\n".join(lines)

    lines.append("（已扣除大盤 β、近 60 個交易日視窗，過濾 TAIEX 相關 >0.85 的萬有引力股）")
    lines.append("")

    for r in candidates:
        own_names = " / ".join(theme_names.get(k, k) for k in r["assigned_concepts"][:3])
        new_name = theme_names.get(r["top_other_concept"], r["top_other_concept"])
        lines.append(
            f"{r['code']} {r['name']} [{r['market']}]\n"
            f"  原屬：{own_names} (excess corr {r['own_max_corr']:+.2f})\n"
            f"  →更接近：{new_name} (excess corr {r['top_other_corr']:+.2f})\n"
            f"  Rerating 分數：+{r['rerating_score']:.2f}  (TAIEX β corr {r['taiex_corr']:.2f})"
        )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from data_fetcher import fetch_all_concepts, fetch_taiex
    from concept_momentum import analyze_all

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "cache", "concepts.json")) as f:
        concepts = json.load(f)

    stocks = fetch_all_concepts(concepts)
    taiex = fetch_taiex()
    results = analyze_all(concepts, stocks, taiex)
    rerating = compute_rerating(concepts, results, stocks, taiex_rows=taiex)

    print(format_rerating_report(rerating, concepts, top_n=30))
