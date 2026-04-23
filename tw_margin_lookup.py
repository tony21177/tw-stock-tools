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


def lookup(code: str, target_date: str | None = None, finmind_token: str = "") -> str:
    today = target_date or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(today, "%Y%m%d")
    start_dt = end_dt - timedelta(days=95)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    # Fetch history and prices
    history = fetch_finmind_history(code, start_date, end_date, finmind_token)
    if not history:
        return f"{code}: 無法取得融資歷史（可能非可融資標的或 API 限流）"

    price_data = fetch_yahoo_history(code)
    if not price_data:
        return f"{code}: 無法取得股價資料"

    # FIFO compute
    avg_cost, remaining = compute_fifo_cost(history, price_data["prices"])
    if remaining == 0 or avg_cost == 0:
        return f"{code} {price_data['name']}: 目前無融資餘額"

    market = price_data["market"]
    ratio = TPEX_MARGIN_RATIO if market == "上櫃" else TWSE_MARGIN_RATIO
    current = price_data["current_price"]
    maintenance = (current / (avg_cost * ratio)) * 100
    trigger_call = avg_cost * ratio * 1.30  # 130% call
    trigger_warn = avg_cost * ratio * 1.40  # 140% warning

    # Get current balance from last history entry
    current_balance = history[-1]["balance"] if history else remaining

    # Find most recent buying day
    recent_buys = [h for h in history[-20:] if h["buy"] > 0]

    sign = "+" if price_data["change_pct"] >= 0 else ""
    status = "🔴 危險（<140%）" if maintenance < 140 else \
             "🟡 警戒（140-150%）" if maintenance < 150 else \
             "🟢 尚可（150-170%）" if maintenance < 170 else \
             "✅ 安全（>170%）"

    # Distance to call
    pct_to_call = ((current - trigger_call) / current) * 100

    lines = [
        f"{code} {price_data['name']} [{market}]",
        f"現價: ${current:,.2f}  {sign}{price_data['change_pct']:.2f}%",
        "",
        f"【融資維持率估算】",
        f"加權成本: ${avg_cost:,.2f} (FIFO 過去 3 個月)",
        f"融資餘額: {current_balance:,} 張",
        f"融資成數: {ratio*100:.0f}%",
        f"估算維持率: {maintenance:.1f}%  {status}",
        "",
        f"【關鍵價位】",
        f"140% 警戒價: ${trigger_warn:,.2f}  (再跌 {((current-trigger_warn)/current*100):.2f}%)",
        f"130% 追繳價: ${trigger_call:,.2f}  (再跌 {pct_to_call:.2f}%)",
    ]

    if recent_buys:
        lines.append("")
        lines.append("【近期融資買進（最近 5 筆）】")
        for h in recent_buys[-5:]:
            date_fmt = datetime.strptime(h["date"], "%Y%m%d").strftime("%m/%d")
            price = price_data["prices"].get(h["date"], 0)
            lines.append(f"  {date_fmt}: 買 {h['buy']:,} 張 @ ${price:,.2f}")

    lines.append("")
    lines.append("註：這是市場整體的 FIFO 加權估算，不等於個別投資人的實際維持率。")
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
