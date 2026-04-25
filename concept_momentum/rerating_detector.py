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


def compute_rerating(concepts: dict, results: list[dict], stocks_data: dict) -> list[dict]:
    """For each stock that appears in any concept, compute correlation with
    its assigned concept(s) and all other concepts. Flag potential rerating.

    Args:
      concepts: concepts.json dict
      results: list of analyze_concept results, each with concept_index
      stocks_data: {code: {rows: [...]}} from data_fetcher

    Returns:
      List of {code, name, assigned_concepts, top_concept, top_corr,
               own_corr, rerating_score} sorted by rerating_score desc.
    """
    # Build code → list of assigned concepts
    code_to_concepts = defaultdict(list)
    for theme_key, theme in concepts.get("themes", {}).items():
        for code in theme.get("stocks", []):
            code_to_concepts[code].append(theme_key)

    # Build concept_key → daily returns of concept index
    concept_returns = {}
    concept_dates = {}
    for r in results:
        ci = r.get("concept_index", [])
        if not ci or len(ci) < 6:
            continue
        values = [p["value"] for p in ci]
        rets = daily_returns(values)
        concept_returns[r["theme_key"]] = rets
        concept_dates[r["theme_key"]] = [p["date"] for p in ci]

    # For each stock with prices, compute returns
    results_list = []
    for code, info in stocks_data.items():
        rows = info.get("rows", [])
        if len(rows) < 10:
            continue
        closes = [r["close"] for r in rows if r.get("close")]
        stock_rets = daily_returns(closes)
        stock_dates = [r["date"] for r in rows if r.get("close")][1:]

        # Compute correlation with EVERY concept (align by date)
        corr_by_concept = {}
        for theme_key, c_rets in concept_returns.items():
            c_dates = concept_dates[theme_key][1:]  # skip first since returns are diff
            # Align: only days both have data
            stock_map = dict(zip(stock_dates, stock_rets))
            paired = [(stock_map[d], c_rets[i])
                       for i, d in enumerate(c_dates)
                       if d in stock_map]
            if len(paired) < 10:
                continue
            sx = [p[0] for p in paired]
            sy = [p[1] for p in paired]
            corr_by_concept[theme_key] = correlation(sx, sy)

        if not corr_by_concept:
            continue

        # Find own concepts (assigned) and others
        own = code_to_concepts.get(code, [])
        own_corrs = [corr_by_concept[k] for k in own if k in corr_by_concept]
        own_avg = sum(own_corrs) / len(own_corrs) if own_corrs else 0.0
        own_max = max(own_corrs) if own_corrs else 0.0

        # Top non-own concept
        other_concepts = {k: v for k, v in corr_by_concept.items() if k not in own}
        if not other_concepts:
            continue
        top_other_key = max(other_concepts, key=other_concepts.get)
        top_other_corr = other_concepts[top_other_key]

        rerating_score = top_other_corr - own_max if own else top_other_corr

        results_list.append({
            "code": code,
            "name": info.get("name", code),
            "market": info.get("market", ""),
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

    candidates = [r for r in rerating if r["rerating_score"] >= 0.1
                   and r["assigned_concepts"]][:top_n]

    if not candidates:
        lines.append("（無顯著 rerating 訊號）")
        return "\n".join(lines)

    for r in candidates:
        own_names = " / ".join(theme_names.get(k, k) for k in r["assigned_concepts"][:3])
        new_name = theme_names.get(r["top_other_concept"], r["top_other_concept"])
        lines.append(
            f"{r['code']} {r['name']} [{r['market']}]\n"
            f"  原屬：{own_names} (相關 {r['own_max_corr']:.2f})\n"
            f"  →更接近：{new_name} (相關 {r['top_other_corr']:.2f})\n"
            f"  Rerating 分數：+{r['rerating_score']:.2f}"
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
    rerating = compute_rerating(concepts, results, stocks)

    print(format_rerating_report(rerating, concepts, top_n=30))
