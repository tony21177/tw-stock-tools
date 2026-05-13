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
import finmind_client
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


def max_consecutive_run(flags: list[bool]) -> int:
    """Longest run of consecutive True values in `flags`. Returns 0 if all False."""
    best = 0
    cur = 0
    for f in flags:
        if f:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def analyze(stock_code: str, days: int, finmind_token: str,
            min_active_days: int = 3, min_pct_of_volume: float = 0.05,
            min_correlation: float = 0.5,
            min_return_correlation: float = 0.3,
            min_top10_buyer_days: int = 3,
            min_consecutive_top10: int = 2,
            top_n: int = 10,
            skip_fetch_if_missing: bool = False) -> dict:
    """Cross-analyze BSR + margin + price-return for one stock.

    Targets 大戶用融資連續大量買進推高股價 — a broker is a candidate if:
      - 累計 ≥ min_top10_buyer_days 個交易日是該檔當日 net-buyer top 10
      - 至少有一段 ≥ min_consecutive_top10 個交易日連續在 top 10 (允許後續斷層)
      - 與融資餘額同步增加 (corr(broker_net, margin_net) ≥ min_correlation)
      - 與當日股價漲幅同步 (corr(broker_net, daily_return) ≥ min_return_correlation)

    Why split top10_buyer_days vs consecutive_top10: BSR top-10 rotation is
    fast for many stocks. Requiring strictly consecutive ≥3 over-filters; a
    broker who is top 10 on 4 of 7 days with a 2-day streak somewhere is
    plausibly a recurring buyer.

    skip_fetch_if_missing=True: 若今日 BSR cache 不存在直接 skip，不嘗試 Playwright fetch。
    用於批量 analyze-only 模式避免 ~1500 個失敗 fetch 各拖 3 秒。"""
    # 1. Load BSR history (cached). If no today, fetch (除非 skip_fetch_if_missing).
    bsr_today_file = os.path.join(HERE, "bsr_cache",
                                   f"{stock_code}_{datetime.now().strftime('%Y%m%d')}.json")
    if not os.path.exists(bsr_today_file):
        if skip_fetch_if_missing:
            return {"error": "今日 BSR cache 不存在 (skip_fetch_if_missing=True)"}
        # Try to fetch today
        fetch_bsr_today(stock_code)

    history = load_bsr_history(stock_code, days=days)
    if len(history) < 2:
        return {"error": f"BSR 歷史不足（只有 {len(history)} 天，至少需要 2 天才能分析）",
                "days_available": len(history)}

    bsr_dates = [h["date"] for h in history]

    # 2. Load FinMind margin history + OHLC for daily-return series
    end_date = bsr_dates[-1]
    start_dt = datetime.strptime(bsr_dates[0], "%Y%m%d")
    finmind_start = start_dt.strftime("%Y-%m-%d")
    finmind_end = (datetime.strptime(end_date, "%Y%m%d")).strftime("%Y-%m-%d")
    margin_history = fetch_finmind_history(stock_code, finmind_start, finmind_end, finmind_token)
    margin_by_date = {m["date"]: m for m in margin_history}

    # OHLC for daily return computation. Pull one extra trading day before
    # bsr_dates[0] so we can compute return on the first BSR day.
    ohlc_start = (start_dt - timedelta(days=10)).strftime("%Y-%m-%d")
    try:
        ohlc_rows = finmind_client.fetch_stock_price(
            stock_code, ohlc_start, finmind_end, finmind_token
        )
    except Exception:
        ohlc_rows = []
    close_by_date = {
        r["date"].replace("-", ""): float(r.get("close", 0)) for r in ohlc_rows
    }
    # daily_return[i] = (close[bsr_dates[i]] - close[prev_trading_day]) / close[prev]
    ohlc_sorted_dates = sorted(close_by_date.keys())
    return_by_date = {}
    for d in bsr_dates:
        # find latest ohlc date strictly before d
        prev = None
        for od in ohlc_sorted_dates:
            if od < d:
                prev = od
            else:
                break
        cur_close = close_by_date.get(d, 0)
        if prev and close_by_date[prev] > 0 and cur_close > 0:
            return_by_date[d] = (cur_close - close_by_date[prev]) / close_by_date[prev]
        else:
            return_by_date[d] = 0.0

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

    # 3b. Per-day top-10 net-buyer set (for consecutive-streak check)
    top10_buyers_per_day = {}
    for h in history:
        nets = [
            (bid, info["buy"] - info["sell"])
            for bid, info in h.get("brokers", {}).items()
            if info["buy"] - info["sell"] > 0
        ]
        nets.sort(key=lambda x: -x[1])
        top10_buyers_per_day[h["date"]] = {bid for bid, _ in nets[:10]}

    # 4. For each broker compute metrics
    candidates = []
    for bid, info in all_brokers.items():
        # Compute per-day net + each-day-as-pct-of-stock-volume
        active_days = 0  # days where broker net buy > min_pct_of_volume of total volume
        net_series = []
        margin_series = []
        return_series = []
        top10_flags = []

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

            return_series.append(return_by_date.get(date, 0.0))
            top10_flags.append(bid in top10_buyers_per_day.get(date, set()))

        consecutive_top10 = max_consecutive_run(top10_flags)
        top10_buyer_days = sum(top10_flags)

        # Skip if not enough buying days (cumulative)
        if active_days < min_active_days:
            continue
        # Skip if not enough cumulative top-10 days
        if top10_buyer_days < min_top10_buyer_days:
            continue
        # Skip if no minimum-length streak
        if consecutive_top10 < min_consecutive_top10:
            continue

        total_buy = sum(d["buy"] for d in info["daily"].values())
        total_sell = sum(d["sell"] for d in info["daily"].values())
        total_net = total_buy - total_sell
        if total_net <= 0:
            continue

        margin_corr = correlation(net_series, margin_series)
        if margin_corr < min_correlation:
            continue
        return_corr = correlation(net_series, return_series)
        if return_corr < min_return_correlation:
            continue

        # Composite score = geometric mean of two correlations × streak ratio
        # (all in [0,1] after normalization). Lets us rank "stronger main
        # players" above merely above-threshold ones.
        streak_ratio = consecutive_top10 / len(bsr_dates) if bsr_dates else 0
        score = ((margin_corr * return_corr) ** 0.5 if margin_corr > 0 and return_corr > 0 else 0) * streak_ratio

        candidates.append({
            "broker_id": bid,
            "broker_name": info["name"],
            "active_days": active_days,
            "top10_buyer_days": top10_buyer_days,
            "consecutive_top10": consecutive_top10,
            "total_buy": total_buy,
            "total_sell": total_sell,
            "total_net": total_net,
            "correlation": margin_corr,          # legacy alias = margin corr
            "margin_correlation": margin_corr,
            "return_correlation": return_corr,
            "score": score,
            "buy_dates": [d for d in bsr_dates
                          if info["daily"].get(d, {}).get("net", 0) > 0],
        })

    # 5. Sort by composite score desc (strongest 推升 signal first)
    candidates.sort(key=lambda x: -x["score"])

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
    lines.append(f"【疑似大戶用融資推升的分點 (Top {len(result['candidates'])})】")
    if not result["candidates"]:
        lines.append("  無符合條件的分點（需連續 ≥3 日 top 10 買 + 融資相關 ≥0.5 + 漲幅相關 ≥0.3）")
    else:
        for i, c in enumerate(result["candidates"], 1):
            buy_days_str = ", ".join(f"{d[4:6]}/{d[6:8]}" for d in c["buy_dates"])
            mc = c.get("margin_correlation", c["correlation"])
            rc = c.get("return_correlation", 0.0)
            top10_days = c.get("top10_buyer_days", 0)
            streak = c.get("consecutive_top10", 0)
            score = c.get("score", 0)
            lines.append(
                f"{i}. {c['broker_id']} {c['broker_name']} (score {score:.2f})\n"
                f"   Top 10 買超: 累計 {top10_days}/{result['days_analyzed']} 日，最長連續 {streak} 日\n"
                f"   買超日: {buy_days_str}\n"
                f"   累計買 {c['total_buy']/1000:,.0f}張 / 賣 {c['total_sell']/1000:,.0f}張 / 淨 +{c['total_net']/1000:,.0f}張\n"
                f"   ➤ 與融資 corr: {mc:+.2f}  與漲幅 corr: {rc:+.2f}"
            )

    lines.append("")
    lines.append("註：score = √(融資corr × 漲幅corr) × (連續日數/總日數)")
    lines.append("    融資 corr = 該分點當日淨買 vs 當日融資淨增的 Pearson")
    lines.append("    漲幅 corr = 該分點當日淨買 vs 當日股價漲幅的 Pearson")
    lines.append("    連續 top 10 = 連續幾日在當日 net 買超榜 top 10 內")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="台股單檔分點+融資連動分析")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--days", type=int, default=5, help="回看天數（預設 5）")
    parser.add_argument("--min-days", type=int, default=3, help="最少買超天數（預設 3）")
    parser.add_argument("--min-pct", type=float, default=0.05, help="買超佔當日量門檻（預設 0.05）")
    parser.add_argument("--min-corr", type=float, default=0.5, help="融資相關係數門檻（預設 0.5）")
    parser.add_argument("--min-return-corr", type=float, default=0.3,
                        help="漲幅相關係數門檻（預設 0.3，較融資寬鬆因漲幅雜訊大）")
    parser.add_argument("--min-top10-days", type=int, default=3,
                        help="累計 top 10 買超天數門檻（預設 3）")
    parser.add_argument("--min-streak", type=int, default=2,
                        help="連續 top 10 買超天數最少門檻（預設 2）")
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
                     min_return_correlation=args.min_return_corr,
                     min_top10_buyer_days=args.min_top10_days,
                     min_consecutive_top10=args.min_streak,
                     top_n=args.top_n)
    print(format_report(result, args.code))


if __name__ == "__main__":
    main()
