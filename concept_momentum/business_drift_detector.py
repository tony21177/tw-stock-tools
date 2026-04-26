#!/usr/bin/env python3
"""
業務轉型偵測器（基本面新聞訊號）

差異點 vs rerating_detector.py：
  rerating_detector 看「股價走勢」，抓的是市場已開始重新定價的訊號
  business_drift_detector 看「公司新聞」，抓的是業務確實轉型但市場還沒反應的訊號

核心流程：
  1. 對 concepts.json 中每檔股票，抓 Yahoo TW 新聞標題
  2. 用 theme_keywords 字典統計每個概念的提及次數
  3. 判斷「新聞主導概念」與「分類概念」是否一致
  4. 若不一致且差異顯著 → 業務轉型候選

關鍵字匹配是輕量近似法，無 LLM、無 API key 需求。
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from news_fetcher import fetch_news_for_stock
from theme_keywords import THEME_KEYWORDS, count_theme_mentions


def detect_drift(concepts: dict, stocks_data: dict | None = None,
                 min_news: int = 5, drift_ratio: float = 1.5,
                 min_top_count: int = 3) -> list[dict]:
    """For each stock in concepts, fetch news, classify themes, find drift.

    Args:
      concepts: concepts.json
      stocks_data: optional {code: {market}} for OTC routing
      min_news: minimum news titles required to analyze
      drift_ratio: top news theme must be at least this much higher
                   than assigned concept's count to flag as drift

    Returns:
      List of {code, name, assigned, news_top, drift_ratio, mention_counts}
      sorted by drift severity desc.
    """
    # Build code → assigned concepts
    code_to_concepts = defaultdict(list)
    for theme_key, theme in concepts.get("themes", {}).items():
        for code in theme.get("stocks", []):
            code_to_concepts[code].append(theme_key)

    # Try to load stock_names for Chinese names + market detection
    try:
        from stock_names import get_name
    except ImportError:
        def get_name(c, fb=""):
            return fb or c

    results = []
    all_codes = list(code_to_concepts.keys())
    print(f"分析 {len(all_codes)} 檔股票的新聞...", file=sys.stderr)

    for i, code in enumerate(all_codes):
        name = get_name(code, code)
        market = "上市"
        if stocks_data and code in stocks_data:
            market = stocks_data[code].get("market", "上市")

        try:
            titles = fetch_news_for_stock(code, name, market)
        except Exception:
            titles = []

        if len(titles) < min_news:
            continue

        # Filter: keep only titles that contain stock name or code (relevance check)
        relevant = [t for t in titles if name in t or code in t]
        if len(relevant) < min_news:
            # Fallback: use all titles (Yahoo TW page is already stock-specific)
            relevant = titles

        counts = count_theme_mentions(relevant)
        # Skip if no theme mentioned
        total_mentions = sum(counts.values())
        if total_mentions == 0:
            continue

        # Top news-implied theme
        sorted_themes = sorted(counts.items(), key=lambda x: -x[1])
        top_theme, top_count = sorted_themes[0]
        if top_count < min_top_count:
            continue  # Not enough mentions to be meaningful signal

        assigned = code_to_concepts[code]
        own_max_count = max((counts.get(k, 0) for k in assigned), default=0)

        # Drift: top theme is NOT in assigned and significantly higher than own max
        if top_theme in assigned:
            continue  # already correctly classified

        if own_max_count == 0:
            ratio = float("inf")
        else:
            ratio = top_count / own_max_count

        if ratio < drift_ratio:
            continue

        results.append({
            "code": code,
            "name": name,
            "market": market,
            "assigned": assigned,
            "news_top_theme": top_theme,
            "news_top_count": top_count,
            "own_max_count": own_max_count,
            "drift_ratio": ratio,
            "all_counts": dict(sorted_themes[:5]),
            "news_count": len(relevant),
        })

        if (i + 1) % 30 == 0:
            print(f"  進度 {i+1}/{len(all_codes)}, 目前發現 {len(results)} 個轉型候選",
                   file=sys.stderr)
        time.sleep(0.2)  # Yahoo rate limit

    # Sort: highest drift_ratio (capped for display)
    results.sort(key=lambda x: -min(x["drift_ratio"], 99))
    return results


def format_drift_report(drifts: list[dict], concepts: dict, top_n: int = 20) -> str:
    """Format drift candidates as text."""
    theme_names = {k: v["name_zh"] for k, v in concepts["themes"].items()}

    lines = ["【業務轉型候選 — 基於新聞主題分析】"]
    lines.append("（新聞中主導主題 ≠ 目前分類概念，且差異 ≥1.5 倍）")
    lines.append("")

    if not drifts:
        lines.append("（過去 30 天內無顯著的業務轉型訊號）")
        return "\n".join(lines)

    for r in drifts[:top_n]:
        own_names = " / ".join(theme_names.get(k, k) for k in r["assigned"][:3])
        new_name = theme_names.get(r["news_top_theme"], r["news_top_theme"])
        ratio = r["drift_ratio"]
        ratio_str = f"{ratio:.1f}×" if ratio != float("inf") else "原概念零提及"
        lines.append(
            f"{r['code']} {r['name']} [{r['market']}]\n"
            f"  原屬：{own_names}\n"
            f"  →新聞主題：{new_name} ({r['news_top_count']} 次提及)\n"
            f"  原概念新聞提及次數：{r['own_max_count']} 次\n"
            f"  轉型比率：{ratio_str} | 共分析 {r['news_count']} 則新聞"
        )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        concepts = json.load(f)

    drifts = detect_drift(concepts)
    print(format_drift_report(drifts, concepts, top_n=20))
