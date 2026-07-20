#!/usr/bin/env python3
"""
台股單檔融資維持率估算查詢

主指標 (2026-07-20 改版)：XQ/三竹口徑「遞迴融資成本線」(全歷史)
  今日成本 = (昨日成本×(餘額−買進) + 收盤×買進) ÷ 餘額
  維持率 = 現價 ÷ (成本線 × 融資成數) × 100%
  成數同時給 五成(券商實務常見, 尤其上櫃/高價股) 與 六成(法規上限)
  兩個口徑 — 實際成數依券商與個股而異。警戒 140% / 追繳 130%。

第二段：FIFO 批次分析 (近 3 個月視窗) — 看「誰套在哪個價位」，
  這是資料商沒有的差異化視角。

資料：FinMind (全歷史融資買/賣/償還 + 日收盤) + 交易所 MIS 即時價
  (盤中即時、修 Yahoo fallback stale 問題)，Yahoo 為備援。
"""

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta

# Reuse functions from tw_margin_monitor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "concept_momentum"))
from tw_margin_monitor import (
    fetch_finmind_history,
    fetch_yahoo_history,
    fetch_mis_price,
    compute_fifo_cost,
    compute_recursive_cost,
    TWSE_MARGIN_RATIO,
    TPEX_MARGIN_RATIO,
)
try:
    from stock_names import get_name as _get_zh_name
except ImportError:
    def _get_zh_name(code, fallback=""):
        return fallback or code


def compute_cohort_distribution(history: list[dict], daily_prices: dict,
                                 current_price: float, current_balance: int,
                                 margin_ratio: float,
                                 sig_threshold_pct: float = 0.05,
                                 method: str = "fifo") -> dict:
    """
    Cohort analysis via BALANCE-CHANGE method:
    - Each day balance INCREASED = new cohort at that day's price for the delta
    - Each day balance DECREASED = reduce existing cohorts using one of:
      - "fifo" (default): oldest cohorts exit first
      - "lifo": newest cohorts exit first
      - "proportional": all cohorts reduce proportionally

    Any residual balance not explained by tracked changes (e.g. pre-window
    positions) is shown as "unknown/legacy" holdings.
    """
    from collections import deque

    sorted_hist = sorted(history, key=lambda x: x["date"])
    if not sorted_hist:
        return {"cohorts": [], "buckets": {}, "tracked": 0, "legacy": current_balance}

    first_balance = sorted_hist[0]["balance"]
    legacy_at_start = first_balance

    lots = deque()  # [date, volume, price]
    prev_balance = first_balance
    for entry in sorted_hist:
        date = entry["date"]
        price = daily_prices.get(date)
        today_balance = entry["balance"]
        delta = today_balance - prev_balance

        if delta > 0 and price is not None:
            lots.append([date, delta, price])
        elif delta < 0:
            reduce = -delta
            if method == "lifo":
                # Newest first (pop from right)
                while reduce > 0 and lots:
                    newest = lots[-1]
                    if newest[1] <= reduce:
                        reduce -= newest[1]
                        lots.pop()
                    else:
                        newest[1] -= reduce
                        reduce = 0
                if reduce > 0:
                    legacy_at_start = max(0, legacy_at_start - reduce)
            elif method == "proportional":
                # Reduce all lots + legacy proportionally to total
                total_vol = sum(l[1] for l in lots) + legacy_at_start
                if total_vol > 0:
                    factor = max(0.0, 1.0 - reduce / total_vol)
                    new_lots = deque()
                    for d, v, p in lots:
                        nv = v * factor
                        if nv >= 1:  # drop very small remainders
                            new_lots.append([d, nv, p])
                    lots = new_lots
                    legacy_at_start = legacy_at_start * factor
            else:  # fifo
                while reduce > 0 and lots:
                    oldest = lots[0]
                    if oldest[1] <= reduce:
                        reduce -= oldest[1]
                        lots.popleft()
                    else:
                        oldest[1] -= reduce
                        reduce = 0
                if reduce > 0:
                    legacy_at_start = max(0, legacy_at_start - reduce)

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


def _fetch_full_closes(code: str, start_iso: str, end_iso: str,
                       token: str) -> dict:
    """FinMind 全歷史日收盤 {YYYYMMDD: close}（遞迴成本線用）。"""
    try:
        import finmind_client
        rows = finmind_client.fetch_stock_price(code, start_iso, end_iso,
                                                token)
    except Exception:
        return {}
    return {str(r["date"]).replace("-", ""): r["close"]
            for r in rows or [] if r.get("close")}


def lookup(code: str, target_date: str | None = None, finmind_token: str = "",
           method: str = "fifo") -> str:
    today = target_date or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(today, "%Y%m%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    full_start = "2018-01-01"                       # 遞迴成本線需全歷史
    win_start = (end_dt - timedelta(days=95)).strftime("%Y%m%d")

    history = fetch_finmind_history(code, full_start, end_date, finmind_token)
    if not history:
        return f"{code}: 無法取得融資歷史（可能非可融資標的或 API 限流）"
    # FIFO 批次分析維持原本的 3 個月視窗
    history_win = [h for h in history if h["date"] >= win_start]

    closes = _fetch_full_closes(code, full_start, end_date, finmind_token)
    price_data = fetch_yahoo_history(code)   # 備援：名稱/市場/現價
    mis = fetch_mis_price(code)              # 即時價（修 stale）

    if not price_data and not (mis and closes):
        return f"{code}: 無法取得股價資料"
    if not price_data:
        price_data = {"prices": {}, "current_price": 0.0,
                      "market": mis.get("market", "上市"),
                      "name": mis.get("name", code), "change_pct": 0.0}

    # 現價解析順序：MIS 即時 → Yahoo → FinMind 最後收盤
    price_src = "Yahoo"
    current = price_data.get("current_price") or 0.0
    if mis.get("price"):
        current = mis["price"]
        price_src = "交易所即時"
        if mis.get("prev_close"):
            price_data["change_pct"] = ((current - mis["prev_close"])
                                        / mis["prev_close"] * 100)
    elif not current and closes:
        current = closes[max(closes)]
        price_src = "FinMind 收盤"
    daily_prices = {**closes, **price_data.get("prices", {})}

    avg_cost, remaining = compute_fifo_cost(history_win, daily_prices)
    rec_cost = compute_recursive_cost(history, daily_prices)
    current_balance = history[-1]["balance"] if history else 0

    if current_balance == 0:
        return f"{code} {price_data['name']}: 目前無融資餘額"

    market = mis.get("market") or price_data["market"]
    ratio = TPEX_MARGIN_RATIO if market == "上櫃" else TWSE_MARGIN_RATIO

    if remaining > 0 and avg_cost > 0:
        maintenance = (current / (avg_cost * ratio)) * 100
    else:
        maintenance = None  # all legacy, no tracked cohorts

    # Cohort analysis (skip small days as noise)
    cohort_data = compute_cohort_distribution(
        history_win, daily_prices, current, current_balance, ratio,
        sig_threshold_pct=0.05, method=method
    )

    sign = "+" if price_data["change_pct"] >= 0 else ""

    def _status(m):
        return ("🔴 危險（<140%）" if m < 140 else
                "🟡 警戒（140-150%）" if m < 150 else
                "🟢 尚可（150-170%）" if m < 170 else
                "✅ 安全（>170%）")

    zh_name = _get_zh_name(code, price_data["name"])
    lines = [
        f"{code} {zh_name} [{market}]",
        f"現價: ${current:,.2f}  {sign}{price_data['change_pct']:.2f}%"
        f"  ({price_src})",
        "",
    ]

    # ── 主指標：XQ/三竹口徑遞迴成本線（全歷史，無舊部位黑洞）──
    if rec_cost:
        m50 = current / (rec_cost * 0.5) * 100
        m60 = current / (rec_cost * 0.6) * 100
        call50, call60 = rec_cost * 0.5 * 1.30, rec_cost * 0.6 * 1.30
        lines.extend([
            "【整體維持率（XQ/三竹口徑：遞迴成本線，全歷史）】",
            f"遞迴成本線: ${rec_cost:,.2f} | 融資餘額: {current_balance:,} 張",
            f"維持率(五成/券商實務): {m50:.1f}%  {_status(m50)}",
            f"維持率(六成/法規上限): {m60:.1f}%  {_status(m60)}",
            f"130% 追繳價: 五成 ${call50:,.2f} / 六成 ${call60:,.2f}",
            "⚠ 實際成數依券商與個股而異（上櫃/高價/處置股常降成數），"
            "真實維持率落在兩口徑之間",
            "",
        ])

    # ── 第二段：FIFO 3 個月視窗（僅涵蓋可追蹤批次，非整體）──
    if maintenance is not None:
        lines.extend([
            f"【FIFO 視窗成本（近 3 個月可追蹤批次，成數 {ratio*100:.0f}%）】",
            f"視窗批次成本: ${avg_cost:,.2f} → 該批維持率 {maintenance:.1f}%"
            f"  {_status(maintenance)}",
            "",
        ])
    else:
        lines.extend([
            f"【FIFO 視窗（近 3 個月）】無可追蹤批次"
            f"（餘額全為 3 個月前舊部位 → 看上方遞迴成本線）",
            "",
        ])

    method_label = {"fifo": "FIFO 老批先扣", "lifo": "LIFO 新批先扣", "proportional": "比例扣減"}[method]
    lines.append(f"【批次分布（規則：{method_label}，顯示佔比 ≥5%）】")

    tracked = round(cohort_data["tracked_vol"])
    legacy = round(cohort_data["legacy_vol"])
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
        vol = round(buckets.get(key, 0))
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
            vol = round(c["volume"])
            lines.append(
                f"  {date_fmt} 淨進 {vol:,}張 @ ${c['price']:.2f}  "
                f"→ 維持率 {r:.1f}% {emoji}  追繳 ${c['trigger_call']:.2f}"
            )
    if cohort_data.get("minor_volume", 0) > 0:
        minor_v = round(cohort_data['minor_volume'])
        lines.append(f"  (另有 {minor_v:,}張 為小量散進，共 {cohort_data['minor_pct']:.1f}%，已略過)")

    lines.append("")
    lines.append(f"註：批次分布規則 = {method_label}；不同規則對「誰先離場」假設不同，數字會有差異。")
    lines.append("  實際投資人成本因個別擔保品組合而異，以上僅為市場整體估算。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="台股單檔融資維持率查詢")
    parser.add_argument("code", help="股票代號，例如 2330")
    parser.add_argument("--date", help="指定日期 YYYYMMDD（預設今天）")
    parser.add_argument("--method", choices=["fifo", "lifo", "proportional"], default="fifo",
                        help="餘額減少時的批次扣減規則：fifo=老批先扣（預設）、lifo=新批先扣、proportional=全部按比例")
    parser.add_argument("--finmind-token")
    args = parser.parse_args()

    token = args.finmind_token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("[ERROR] 需要 FinMind token (--finmind-token 或 FINMIND_TOKEN)", file=sys.stderr)
        sys.exit(1)

    print(lookup(args.code, args.date, token, method=args.method))


if __name__ == "__main__":
    main()
