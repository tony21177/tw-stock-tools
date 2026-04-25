#!/usr/bin/env python3
"""
單檔分點+融資連動分析

抓近 N 天的 BSR 分點資料 + 融資餘額變化，
找出「連續多天買超 + 融資也淨增加 + 買超與融資增量正相關」的分點。
這類分點疑似用融資做短線。

注意：BSR 只有當日資料，因此本工具依賴 ~/project/tw_stock_tools/bsr_cache/
中累積的歷史資料（每天需跑一次 tw_broker_monitor.py 累積）。
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

from bsr_scraper import load_history as load_bsr_history, fetch_and_cache as fetch_bsr_today
from tw_margin_monitor import fetch_finmind_history
try:
    from stock_names import get_name as _zh_name
except ImportError:
    def _zh_name(c, fb=""):
        return fb or c


def correlation(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation. Returns 0 if undefined."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)


def analyze(stock_code: str, days: int, finmind_token: str,
            min_active_days: int = 3, min_pct_of_volume: float = 0.05,
            min_correlation: float = 0.5, top_n: int = 10) -> dict:
    """Cross-analyze BSR + margin for one stock."""
    # 1. Load BSR history (cached). If no today, fetch.
    bsr_today_file = os.path.join(HERE, "bsr_cache",
                                   f"{stock_code}_{datetime.now().strftime('%Y%m%d')}.json")
    if not os.path.exists(bsr_today_file):
        # Try to fetch today
        fetch_bsr_today(stock_code)

    history = load_bsr_history(stock_code, days=days)
    if len(history) < 2:
        return {"error": f"BSR 歷史不足（只有 {len(history)} 天，至少需要 2 天才能分析）",
                "days_available": len(history)}

    bsr_dates = [h["date"] for h in history]

    # 2. Load FinMind margin history
    end_date = bsr_dates[-1]
    start_dt = datetime.strptime(bsr_dates[0], "%Y%m%d")
    finmind_start = start_dt.strftime("%Y-%m-%d")
    finmind_end = (datetime.strptime(end_date, "%Y%m%d")).strftime("%Y-%m-%d")
    margin_history = fetch_finmind_history(stock_code, finmind_start, finmind_end, finmind_token)
    margin_by_date = {m["date"]: m for m in margin_history}

    # 3. For each broker that appears, build daily series
    all_brokers = {}
    for h in history:
        for bid, info in h.get("brokers", {}).items():
            if bid not in all_brokers:
                all_brokers[bid] = {"name": info["name"], "daily": {}}
            all_brokers[bid]["daily"][h["date"]] = {
                "buy": info["buy"],
                "sell": info["sell"],
                "net": info["buy"] - info["sell"],
            }

    # 4. For each broker compute metrics
    candidates = []
    for bid, info in all_brokers.items():
        # Compute per-day net + each-day-as-pct-of-stock-volume
        active_days = 0  # days where broker net buy > min_pct_of_volume of total volume
        net_series = []
        margin_series = []

        for date in bsr_dates:
            day_data = info["daily"].get(date)
            day_total = next((h["total_buy"] + h["total_sell"]
                              for h in history if h["date"] == date), 0)
            if day_data and day_total > 0:
                broker_net = day_data["net"]
                pct = abs(broker_net) / (day_total / 2) if day_total else 0  # buy or sell side
                if broker_net > 0 and pct >= min_pct_of_volume:
                    active_days += 1
                # For correlation: include all days
                net_series.append(broker_net)
            else:
                net_series.append(0)

            margin = margin_by_date.get(date, {})
            margin_net = (margin.get("buy", 0) - margin.get("sell", 0)
                          - margin.get("repay", 0))
            margin_series.append(margin_net)

        # Skip if not enough buying days
        if active_days < min_active_days:
            continue

        total_buy = sum(d["buy"] for d in info["daily"].values())
        total_sell = sum(d["sell"] for d in info["daily"].values())
        total_net = total_buy - total_sell
        if total_net <= 0:
            continue

        corr = correlation(net_series, margin_series)
        if corr < min_correlation:
            continue

        candidates.append({
            "broker_id": bid,
            "broker_name": info["name"],
            "active_days": active_days,
            "total_buy": total_buy,
            "total_sell": total_sell,
            "total_net": total_net,
            "correlation": corr,
            "buy_dates": [d for d in bsr_dates
                          if info["daily"].get(d, {}).get("net", 0) > 0],
        })

    # 5. Sort by correlation desc
    candidates.sort(key=lambda x: -x["correlation"])

    # 6. Margin summary
    sorted_margin = sorted(margin_history, key=lambda x: x["date"])
    margin_first = sorted_margin[0] if sorted_margin else None
    margin_last = sorted_margin[-1] if sorted_margin else None
    margin_total_increase = (margin_last["balance"] - margin_first["balance"]) if margin_first and margin_last else 0

    return {
        "stock_code": stock_code,
        "days_analyzed": len(bsr_dates),
        "bsr_dates": bsr_dates,
        "current_balance": margin_last["balance"] if margin_last else 0,
        "margin_total_increase": margin_total_increase,
        "candidates": candidates[:top_n],
    }


def format_report(result: dict, stock_code: str) -> str:
    if "error" in result:
        return f"{stock_code} {_zh_name(stock_code)}: {result['error']}\n→ 提示：BSR 從第一天爬起需累積 ≥3 天才能做相關分析"

    name = _zh_name(stock_code)
    lines = [f"{stock_code} {name} - 分點+融資連動分析"]
    lines.append(f"分析區間: {result['bsr_dates'][0]} ~ {result['bsr_dates'][-1]} ({result['days_analyzed']} 個交易日)")
    lines.append(f"目前融資餘額: {result['current_balance']:,} 張")
    lines.append(f"區間融資累計變化: {result['margin_total_increase']:+,} 張")

    if result["margin_total_increase"] <= 0:
        lines.append("⚠️ 區間融資並未淨增加，連動分析意義有限")

    lines.append("")
    lines.append(f"【疑似用融資做短線的分點 (Top {len(result['candidates'])})】")
    if not result["candidates"]:
        lines.append("  無符合條件的分點（需 ≥3 天買超且與融資正相關 ≥0.5）")
    else:
        for i, c in enumerate(result["candidates"], 1):
            buy_days_str = ", ".join(f"{d[4:6]}/{d[6:8]}" for d in c["buy_dates"])
            lines.append(
                f"{i}. {c['broker_id']} {c['broker_name']}\n"
                f"   買超天數: {c['active_days']}/{result['days_analyzed']} ({buy_days_str})\n"
                f"   累計買 {c['total_buy']/1000:,.0f}張 / 賣 {c['total_sell']/1000:,.0f}張 / 淨 +{c['total_net']/1000:,.0f}張\n"
                f"   與融資餘額相關係數: {c['correlation']:.2f}"
            )

    lines.append("")
    lines.append("註：相關係數 = 該分點當日淨買 vs 當日融資淨增量的 Pearson 相關")
    lines.append("    高相關不代表因果，僅顯示時間上的同步性")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="台股單檔分點+融資連動分析")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--days", type=int, default=5, help="回看天數（預設 5）")
    parser.add_argument("--min-days", type=int, default=3, help="最少買超天數（預設 3）")
    parser.add_argument("--min-pct", type=float, default=0.05, help="買超佔當日量門檻（預設 0.05）")
    parser.add_argument("--min-corr", type=float, default=0.5, help="相關係數門檻（預設 0.5）")
    parser.add_argument("--top-n", type=int, default=10, help="顯示前 N 名分點")
    parser.add_argument("--finmind-token")
    args = parser.parse_args()

    token = args.finmind_token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[ERROR] 需要 FinMind token", file=sys.stderr)
        sys.exit(1)

    result = analyze(args.code, args.days, token,
                     min_active_days=args.min_days,
                     min_pct_of_volume=args.min_pct,
                     min_correlation=args.min_corr,
                     top_n=args.top_n)
    print(format_report(result, args.code))


if __name__ == "__main__":
    main()
