"""TSM (台積電 ADR) vs 2330 (台股) 折溢價計算。

換股比例 1 : 5 (1 股 TSM = 5 股 2330)。
  理論價格(TWD) = TSM(USD) × USD/TWD / 5
  折溢價率(%)   = (理論價格 / 2330實際價 - 1) × 100
  > 0 溢價 (美股投資人願出更高價) / < 0 折價

資料源：Yahoo Finance chart API (concept_momentum/data_fetcher.fetch_yahoo)
  TSM      美股 ADR 日線收盤 (USD)
  2330.TW  台股日線收盤 (TWD)
  TWD=X    USD/TWD 日匯率

時間差 caveat：TSM 當日收盤 (美東盤後) 比 2330 同日收盤 (台北 13:30) 晚約
14.5 小時，所以同日配對的溢價反映「美股盤後對 2330 的看法」，常被當作隔日
2330 開盤跳空的前瞻指標。除權息日附近因台美除息日不同步會有假性折溢價。
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

ADR_RATIO = 5  # 1 TSM = 5 × 2330
DEFAULT_CHAT_ID = "-5229750819"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API.format(token=bot_token)
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("ok", False)
    except Exception as e:
        print(f"[ERROR] Telegram: {e}", file=sys.stderr)
        return False


def _range_str(years: int) -> str:
    if years <= 1:
        return "1y"
    if years <= 2:
        return "2y"
    if years <= 5:
        return "5y"
    return "10y"


def _nearest_prior(date_map: dict, dates_sorted: list, target: str):
    """Value on `target` date, else most-recent prior date (FX/holiday gaps)."""
    if target in date_map:
        return date_map[target]
    import bisect
    i = bisect.bisect_right(dates_sorted, target) - 1
    if i >= 0:
        return date_map[dates_sorted[i]]
    return None


def fetch_premium_series(years: int = 5) -> dict:
    """Return ADR premium/discount daily series + summary.

    {
      "series": [{"date":"YYYY-MM-DD", "tsm": float, "fx": float,
                  "theoretical": float, "tw": float, "premium": float}, ...],
      "summary": {"current", "mean", "min", "max", "min_date", "max_date",
                  "pctile" (current's percentile in window), "n"},
      "error": str (only on failure),
    }
    """
    import data_fetcher as df
    rng = _range_str(years)
    tsm = df.fetch_yahoo("TSM", rng)
    tw = df.fetch_yahoo("2330.TW", rng)
    fx = df.fetch_yahoo("TWD=X", rng)
    if not tsm or not tw or not fx:
        missing = [n for n, r in (("TSM", tsm), ("2330.TW", tw),
                                  ("TWD=X", fx)) if not r]
        return {"error": f"Yahoo 抓不到: {', '.join(missing)}",
                "series": [], "summary": {}}

    def _fmt(d):  # 20260604 -> 2026-06-04
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"

    tsm_map = {r["date"]: r["close"] for r in tsm if r.get("close")}
    tw_map = {r["date"]: r["close"] for r in tw if r.get("close")}
    fx_map = {r["date"]: r["close"] for r in fx if r.get("close")}
    fx_dates = sorted(fx_map.keys())

    # window cutoff (trim the standard yahoo range to exactly `years`)
    cutoff = (datetime.now() - timedelta(days=int(years * 365.25))
              ).strftime("%Y%m%d")

    series = []
    for d in sorted(set(tsm_map) & set(tw_map)):
        if d < cutoff:
            continue
        rate = _nearest_prior(fx_map, fx_dates, d)
        if not rate:
            continue
        theo = tsm_map[d] * rate / ADR_RATIO
        twp = tw_map[d]
        if twp <= 0:
            continue
        prem = (theo / twp - 1) * 100
        series.append({"date": _fmt(d), "tsm": round(tsm_map[d], 2),
                       "fx": round(rate, 3), "theoretical": round(theo, 1),
                       "tw": round(twp, 1), "premium": round(prem, 2)})

    if not series:
        return {"error": "無重疊交易日資料", "series": [], "summary": {}}

    prems = [s["premium"] for s in series]
    cur = prems[-1]
    lo, hi = min(prems), max(prems)
    lo_s = series[prems.index(lo)]
    hi_s = series[prems.index(hi)]
    below = sum(1 for p in prems if p <= cur)
    summary = {
        "current": cur, "mean": round(sum(prems) / len(prems), 2),
        "min": lo, "min_date": lo_s["date"], "max": hi, "max_date": hi_s["date"],
        "pctile": round(below / len(prems) * 100, 1), "n": len(series),
        "current_date": series[-1]["date"],
        "current_tsm": series[-1]["tsm"], "current_fx": series[-1]["fx"],
        "current_theo": series[-1]["theoretical"], "current_tw": series[-1]["tw"],
    }
    return {"series": series, "summary": summary}


def _pctile(series: list, window: int, cur: float) -> tuple[float, int]:
    """Percentile of `cur` within the last `window` rows of series."""
    recent = [s["premium"] for s in series[-window:]]
    below = sum(1 for p in recent if p <= cur)
    return round(below / len(recent) * 100, 1), len(recent)


def build_alert(high: float, low: float) -> tuple[str | None, dict]:
    """Return (telegram_message_or_None, summary). Message is non-None only
    when the current premium crosses a threshold or hits a 1-year extreme."""
    r = fetch_premium_series(5)
    if r.get("error"):
        return None, {"error": r["error"]}
    s, ser = r["summary"], r["series"]
    cur = s["current"]
    p1, n1 = _pctile(ser, 252, cur)   # 1-year percentile (shown as context)
    # Trigger ONLY on absolute thresholds — keeps the daily cron quiet, firing
    # only at genuine extremes (high premium / discount), not 1y drift.
    if not (cur >= high or cur <= low):
        return None, s

    if cur >= high:
        tag = f"🔴 溢價偏高 (≥{high:g}%)"
        read = ("溢價接近歷史高檔，美股對 2330 明顯樂觀 → 隔日 2330 易開高，"
                "但高溢價也有均值回歸風險。")
    else:
        tag = (f"🟢 翻折價 (≤{low:g}%)" if low <= 0
               else f"🟢 折價/低溢價 (≤{low:g}%)")
        read = ("溢價收斂甚至折價，美股對 2330 轉保守 → 隔日 2330 易開低 / "
                "ADR 套利買盤可能進場。")

    msg = (
        f"🇺🇸 TSM ADR 折溢價警示 ({s['current_date']})\n\n"
        f"當前折溢價: {cur:+.2f}%  {tag}\n"
        f"  TSM ${s['current_tsm']} × {s['current_fx']} / 5 = "
        f"理論 {s['current_theo']:.0f} vs 2330 實際 {s['current_tw']:.0f}\n\n"
        f"近 1 年: 當前位於 {p1:.0f} 百分位 ({n1} 交易日)\n"
        f"近 5 年: 均值 {s['mean']:+.2f}% | 區間 {s['min']:+.2f}% "
        f"({s['min_date']}) ~ {s['max']:+.2f}% ({s['max_date']})\n\n"
        f"⚠ {read}\n"
        f"註：TSM 收盤晚 2330 約 14.5h，此為隔日 2330 開盤跳空前瞻指標；"
        f"除權息日附近數字僅供參考。"
    )
    return msg, s


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="TSM ADR vs 2330 折溢價")
    ap.add_argument("years", nargs="?", type=int, default=5,
                    help="回看年數 (1-10, 預設 5)")
    ap.add_argument("--alert", action="store_true",
                    help="警示模式: 折溢價達門檻才輸出 / 推 Telegram")
    ap.add_argument("--high", type=float, default=25.0, help="高溢價門檻 %% (預設 25)")
    ap.add_argument("--low", type=float, default=0.0, help="低溢價門檻 %% (預設 0=翻折價)")
    ap.add_argument("--telegram", action="store_true", help="推送 Telegram")
    ap.add_argument("--bot-token", help="或設 TG_BOT_TOKEN 環境變數")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    args = ap.parse_args()

    if args.alert:
        msg, s = build_alert(args.high, args.low)
        if s.get("error"):
            print("ERROR:", s["error"], file=sys.stderr)
            sys.exit(1)
        if not msg:
            print(f"[OK] 折溢價 {s['current']:+.2f}% 在正常區間 "
                  f"({args.low:g}%~{args.high:g}%)，不警示。")
            sys.exit(0)
        print(msg)
        if args.telegram:
            token = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")
            if not token:
                print("[ERROR] 需要 TG_BOT_TOKEN", file=sys.stderr)
                sys.exit(1)
            send_telegram(msg, token, args.chat_id)
        sys.exit(0)

    yrs = max(1, min(args.years, 10))
    r = fetch_premium_series(yrs)
    if r.get("error"):
        print("ERROR:", r["error"])
        sys.exit(1)
    s = r["summary"]
    print(f"TSM vs 2330 折溢價 (近 {yrs} 年, {s['n']} 個交易日)")
    print(f"  當前 ({s['current_date']}): {s['current']:+.2f}%  "
          f"[TSM ${s['current_tsm']} × {s['current_fx']} / 5 = "
          f"理論 {s['current_theo']} vs 實際 {s['current_tw']}]")
    print(f"  區間均值: {s['mean']:+.2f}% | 最低 {s['min']:+.2f}% ({s['min_date']})"
          f" | 最高 {s['max']:+.2f}% ({s['max_date']})")
    print(f"  當前位於區間 {s['pctile']:.0f} 百分位")
    print("  近 5 日:")
    for row in r["series"][-5:]:
        print(f"    {row['date']}  溢價 {row['premium']:+.2f}%  "
              f"(TSM ${row['tsm']} fx {row['fx']} 理論 {row['theoretical']} "
              f"vs {row['tw']})")
