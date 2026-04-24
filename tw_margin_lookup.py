#!/usr/bin/env python3
"""
台股單檔融資維持率估算查詢

維持率 = 現價 / (FIFO 加權成本 × 融資成數) × 100%
  融資成數：上市 60%、上櫃 50%
  警戒線：140%  追繳線：130%

資料：FinMind (3 個月融資買/賣/償還) + Yahoo Finance (股價)
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta

# Reuse functions from tw_margin_monitor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tw_margin_monitor import (
    fetch_finmind_history,
    fetch_yahoo_history,
    compute_fifo_cost,
    TWSE_MARGIN_RATIO,
    TPEX_MARGIN_RATIO,
)


def compute_cohort_distribution(history: list[dict], daily_prices: dict,
                                 current_price: float, current_balance: int,
                                 margin_ratio: float,
                                 sig_threshold_pct: float = 0.05) -> dict:
    """
    Cohort analysis via BALANCE-CHANGE method:
    - Each day the balance INCREASED = new cohort at that day's price for the delta
    - Each day the balance DECREASED = FIFO reduce oldest cohorts
    - This is more realistic than tracking raw buy/sell because it only
      creates cohorts when net balance actually grew.

    Any residual balance not explained by tracked changes (e.g. pre-window
    positions) is shown as "unknown/legacy" holdings.
    """
    from collections import deque

    # Build daily balance series from history (sorted ascending)
    sorted_hist = sorted(history, key=lambda x: x["date"])
    if not sorted_hist:
        return {"cohorts": [], "buckets": {}, "tracked": 0, "legacy": current_balance}

    # Starting balance = prev day balance of first entry (not available)
    # Use first entry's balance as seed (this represents "legacy holders" before window)
    first_balance = sorted_hist[0]["balance"]
    # Legacy holders = earliest known balance; their cost unknown
    legacy_at_start = first_balance

    lots = deque()  # [date, volume, price]
    prev_balance = first_balance
    for entry in sorted_hist:
        date = entry["date"]
        price = daily_prices.get(date)
        today_balance = entry["balance"]
        delta = today_balance - prev_balance

        if delta > 0 and price is not None:
            # Net new position → new cohort
            lots.append([date, delta, price])
        elif delta < 0:
            # Net reduction → FIFO remove oldest (from known cohorts only)
            reduce = -delta
            while reduce > 0 and lots:
                oldest = lots[0]
                if oldest[1] <= reduce:
                    reduce -= oldest[1]
                    lots.popleft()
                else:
                    oldest[1] -= reduce
                    reduce = 0
            # If still reduction remains, legacy holders decreased
            if reduce > 0:
                legacy_at_start -= reduce
                legacy_at_start = max(0, legacy_at_start)

        prev_balance = today_balance

    # Aggregate lots by date (same-day positions merged)
    date_map = {}
    for d, v, p in lots:
        if d not in date_map:
            date_map[d] = {"date": d, "volume": 0, "price": p}
        date_map[d]["volume"] += v

    all_cohorts = sorted(date_map.values(), key=lambda x: x["date"])
    tracked_vol = sum(c["volume"] for c in all_cohorts)

    # Reconcile with actual current balance
    # actual = legacy_at_start + tracked_vol (ideally)
    # but if mismatch, scale or show discrepancy
    legacy_vol = max(0, current_balance - tracked_vol)

    # Filter significant cohorts (by % of actual current balance, not just tracked)
    threshold = current_balance * sig_threshold_pct
    significant = [c for c in all_cohorts if c["volume"] >= threshold]

    for c in significant:
        c["maintenance_ratio"] = (current_price / (c["price"] * margin_ratio)) * 100
        c["trigger_call"] = c["price"] * margin_ratio * 1.30
        c["trigger_warn"] = c["price"] * margin_ratio * 1.40

    # Bucket distribution for all tracked cohorts
    buckets = {"<130": 0, "130-140": 0, "140-150": 0, "150-170": 0, "170+": 0}
    for c in all_cohorts:
        ratio = (current_price / (c["price"] * margin_ratio)) * 100
        if ratio < 130:
            buckets["<130"] += c["volume"]
        elif ratio < 140:
            buckets["130-140"] += c["volume"]
        elif ratio < 150:
            buckets["140-150"] += c["volume"]
        elif ratio < 170:
            buckets["150-170"] += c["volume"]
        else:
            buckets["170+"] += c["volume"]

    minor_vol = sum(c["volume"] for c in all_cohorts if c["volume"] < threshold)

    return {
        "cohorts": significant,
        "buckets": buckets,
        "tracked_vol": tracked_vol,
        "legacy_vol": legacy_vol,
        "current_balance": current_balance,
        "minor_volume": minor_vol,
        "minor_pct": minor_vol / tracked_vol * 100 if tracked_vol else 0,
    }


def lookup(code: str, target_date: str | None = None, finmind_token: str = "") -> str:
    today = target_date or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(today, "%Y%m%d")
    start_dt = end_dt - timedelta(days=95)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    history = fetch_finmind_history(code, start_date, end_date, finmind_token)
    if not history:
        return f"{code}: 無法取得融資歷史（可能非可融資標的或 API 限流）"

    price_data = fetch_yahoo_history(code)
    if not price_data:
        return f"{code}: 無法取得股價資料"

    avg_cost, remaining = compute_fifo_cost(history, price_data["prices"])
    if remaining == 0 or avg_cost == 0:
        return f"{code} {price_data['name']}: 目前無融資餘額"

    market = price_data["market"]
    ratio = TPEX_MARGIN_RATIO if market == "上櫃" else TWSE_MARGIN_RATIO
    current = price_data["current_price"]
    maintenance = (current / (avg_cost * ratio)) * 100
    trigger_call = avg_cost * ratio * 1.30
    trigger_warn = avg_cost * ratio * 1.40

    current_balance = history[-1]["balance"] if history else remaining

    # Cohort analysis (skip small days as noise)
    cohort_data = compute_cohort_distribution(
        history, price_data["prices"], current, current_balance, ratio, sig_threshold_pct=0.05
    )

    sign = "+" if price_data["change_pct"] >= 0 else ""
    status = "🔴 危險（<140%）" if maintenance < 140 else \
             "🟡 警戒（140-150%）" if maintenance < 150 else \
             "🟢 尚可（150-170%）" if maintenance < 170 else \
             "✅ 安全（>170%）"

    pct_to_call = ((current - trigger_call) / current) * 100

    lines = [
        f"{code} {price_data['name']} [{market}]",
        f"現價: ${current:,.2f}  {sign}{price_data['change_pct']:.2f}%",
        "",
        f"【整體維持率（FIFO 加權）】",
        f"加權成本: ${avg_cost:,.2f} | 融資餘額: {current_balance:,} 張 | 成數: {ratio*100:.0f}%",
        f"估算維持率: {maintenance:.1f}%  {status}",
        f"140% 警戒價: ${trigger_warn:,.2f} (再跌 {((current-trigger_warn)/current*100):.2f}%)",
        f"130% 追繳價: ${trigger_call:,.2f} (再跌 {pct_to_call:.2f}%)",
        "",
        f"【批次分布（顯示佔比 ≥5% 的大量進場日）】",
    ]

    tracked = cohort_data["tracked_vol"]
    legacy = cohort_data["legacy_vol"]
    balance = cohort_data["current_balance"]
    lines.append(f"目前融資餘額 {balance:,} 張 = "
                  f"可追蹤批次 {tracked:,} 張 + 舊部位 {legacy:,} 張")
    lines.append(f"（舊部位 = 3 個月區間以前就存在的部位，成本無從得知）")
    lines.append("")
    lines.append(f"可追蹤批次的維持率分布：")
    buckets = cohort_data["buckets"]
    bucket_labels = [
        ("<130", "🔴 追繳區"),
        ("130-140", "🟠 危險區"),
        ("140-150", "🟡 警戒區"),
        ("150-170", "🟢 尚可區"),
        ("170+", "✅ 安全區"),
    ]
    for key, label in bucket_labels:
        vol = buckets.get(key, 0)
        pct = vol / tracked * 100 if tracked else 0
        bar = "█" * int(pct / 5)
        lines.append(f"  {label} ({key}%)：{vol:>6,}張 ({pct:>5.1f}%) {bar}")

    lines.append("")
    lines.append(f"【主要批次明細（佔總餘額 ≥5% 才列出）】")
    cohorts = cohort_data["cohorts"]
    if not cohorts:
        lines.append("  (本期無顯著大量進場日；多為零散散買)")
    else:
        cohorts_sorted = sorted(cohorts, key=lambda x: x["volume"], reverse=True)
        for c in cohorts_sorted:
            date_fmt = datetime.strptime(c["date"], "%Y%m%d").strftime("%m/%d")
            r = c["maintenance_ratio"]
            emoji = "🔴" if r < 130 else "🟠" if r < 140 else "🟡" if r < 150 else "🟢" if r < 170 else "✅"
            lines.append(
                f"  {date_fmt} 淨進 {c['volume']:,}張 @ ${c['price']:.2f}  "
                f"→ 維持率 {r:.1f}% {emoji}  追繳 ${c['trigger_call']:.2f}"
            )
    if cohort_data.get("minor_volume", 0) > 0:
        lines.append(f"  (另有 {cohort_data['minor_volume']:,}張 為小量散進，共 {cohort_data['minor_pct']:.1f}%，已略過)")

    lines.append("")
    lines.append("註：整體維持率是加權平均；批次分布是 FIFO 推估每日進場至今尚未平倉的部位。")
    lines.append("  實際投資人成本因個別擔保品組合而異，以上僅為市場整體估算。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="台股單檔融資維持率查詢")
    parser.add_argument("code", help="股票代號，例如 2330")
    parser.add_argument("--date", help="指定日期 YYYYMMDD（預設今天）")
    parser.add_argument("--finmind-token")
    args = parser.parse_args()

    token = args.finmind_token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[ERROR] 需要 FinMind token (--finmind-token 或 FINMIND_TOKEN)", file=sys.stderr)
        sys.exit(1)

    print(lookup(args.code, args.date, token))


if __name__ == "__main__":
    main()
