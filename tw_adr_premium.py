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


# period key -> (yahoo range to fetch, cutoff in days, 中文 label).
# Fetch the smallest standard yahoo range that covers the period, then trim.
PERIODS = {
    "1w":  ("1mo", 7,    "1 週"),
    "2w":  ("1mo", 14,   "2 週"),
    "1mo": ("3mo", 31,   "1 個月"),
    "3mo": ("6mo", 93,   "3 個月"),
    "6mo": ("1y",  186,  "6 個月"),
    "1y":  ("1y",  366,  "1 年"),
    "2y":  ("2y",  731,  "2 年"),
    "3y":  ("5y",  1096, "3 年"),
    "5y":  ("5y",  1827, "5 年"),
    "10y": ("10y", 3653, "10 年"),
}
PERIOD_ORDER = ["1w", "2w", "1mo", "3mo", "6mo", "1y", "2y", "3y", "5y", "10y"]


def _resolve_period(period) -> tuple[str, int, str]:
    """Accept a period key ('6mo') or a legacy int years -> (range, days, label)."""
    if isinstance(period, int):
        period = f"{max(1, min(period, 10))}y"
    return PERIODS.get(period, PERIODS["6mo"])


def _nearest_prior(date_map: dict, dates_sorted: list, target: str):
    """Value on `target` date, else most-recent prior date (FX/holiday gaps)."""
    if target in date_map:
        return date_map[target]
    import bisect
    i = bisect.bisect_right(dates_sorted, target) - 1
    if i >= 0:
        return date_map[dates_sorted[i]]
    return None


def fetch_premium_series(period="6mo") -> dict:
    """Return ADR premium/discount daily series + summary.

    `period` is a key from PERIODS ('1w','1mo','6mo','5y'…) or a legacy int
    (years). {
      "series": [{"date","tsm","fx","theoretical","tw","premium","twii"}, ...],
      "summary": {"current","mean","min","max","min_date","max_date","pctile",
                  "n","period_label", ...},
      "error": str (only on failure),
    }
    """
    import data_fetcher as df
    rng, cutoff_days, period_label = _resolve_period(period)
    tsm = df.fetch_yahoo("TSM", rng)
    tw = df.fetch_yahoo("2330.TW", rng)
    fx = df.fetch_yahoo("TWD=X", rng)
    twii = df.fetch_yahoo("^TWII", rng)  # 加權指數 (for chart overlay)
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
    twii_map = {r["date"]: r["close"] for r in (twii or []) if r.get("close")}
    fx_dates = sorted(fx_map.keys())
    twii_dates = sorted(twii_map.keys())

    # window cutoff (trim the fetched yahoo range to exactly the period)
    cutoff = (datetime.now() - timedelta(days=cutoff_days)).strftime("%Y%m%d")

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
        twii_v = _nearest_prior(twii_map, twii_dates, d) if twii_map else None
        series.append({"date": _fmt(d), "tsm": round(tsm_map[d], 2),
                       "fx": round(rate, 3), "theoretical": round(theo, 1),
                       "tw": round(twp, 1), "premium": round(prem, 2),
                       "twii": round(twii_v, 1) if twii_v else None})

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
        "period_label": period_label,
        "current_date": series[-1]["date"],
        "current_tsm": series[-1]["tsm"], "current_fx": series[-1]["fx"],
        "current_theo": series[-1]["theoretical"], "current_tw": series[-1]["tw"],
    }
    return {"series": series, "summary": summary}


def latest_mixed_premium() -> dict:
    """Real-time premium pairing each market's LATEST available close, even if
    on different dates. 2330 closes 13:30 TWT; TSM's same-day session only
    closes ~next-day 04:00 TWT, so on a TW afternoon the freshest TSM is the
    prior US session. This gives a 'current' read (2330 today vs ADR overnight)
    that the same-date series can't show until tomorrow morning.

    Returns {tsm_date, tsm, tw_date, tw, fx_date, fx, theoretical, premium,
    aligned (bool: same date both sides)} or {"error": ...}.
    """
    import data_fetcher as df
    tsm = df.fetch_yahoo("TSM", "5d")
    tw = df.fetch_yahoo("2330.TW", "5d")
    fx = df.fetch_yahoo("TWD=X", "5d")
    if not tsm or not tw or not fx:
        return {"error": "Yahoo 抓不到最新報價"}

    def _fmt(d):
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    t, w, f = tsm[-1], tw[-1], fx[-1]
    theo = t["close"] * f["close"] / ADR_RATIO
    prem = (theo / w["close"] - 1) * 100 if w["close"] else None
    return {
        "tsm_date": _fmt(t["date"]), "tsm": round(t["close"], 2),
        "tw_date": _fmt(w["date"]), "tw": round(w["close"], 1),
        "fx_date": _fmt(f["date"]), "fx": round(f["close"], 3),
        "theoretical": round(theo, 1),
        "premium": round(prem, 2) if prem is not None else None,
        "aligned": t["date"] == w["date"],
    }


def _pctile(series: list, window: int, cur: float) -> tuple[float, int]:
    """Percentile of `cur` within the last `window` rows of series."""
    recent = [s["premium"] for s in series[-window:]]
    below = sum(1 for p in recent if p <= cur)
    return round(below / len(recent) * 100, 1), len(recent)


def compute_slope(series: list, win: int) -> list:
    """Rolling least-squares slope of premium (pp/day), aligned to series
    (None for the first win-1 points)."""
    pv = [r["premium"] for r in series]
    n = len(pv)
    out = [None] * n
    if n < win:
        return out
    xm = (win - 1) / 2.0
    den = sum((j - xm) ** 2 for j in range(win))
    for i in range(win - 1, n):
        ys = pv[i - win + 1:i + 1]
        ym = sum(ys) / win
        num = sum((j - xm) * (ys[j] - ym) for j in range(win))
        out[i] = round(num / den, 3) if den else None
    return out


def slope_signals(series: list, win: int = 5) -> dict:
    """Detect slope-turn events + backtest next-day 2330 reaction.

    A turn-positive at i = slope[i-1] <= 0 < slope[i]; turn-negative the
    reverse. Next-day reaction uses the series' own consecutive 2330 closes
    (series[i+1].tw / series[i].tw). Returns slope list, marker index lists,
    and hit-rate / mean-return stats vs the all-day baseline.
    """
    slope = compute_slope(series, win)
    n = len(series)

    def nxt_ret(i):
        if i + 1 >= n:
            return None
        a, b = series[i].get("tw"), series[i + 1].get("tw")
        return (b / a - 1) * 100 if a and b else None

    base = [r for r in (nxt_ret(i) for i in range(n)) if r is not None]
    base_up = round(sum(1 for r in base if r > 0) / len(base) * 100, 1) if base else 0

    pos_idx, neg_idx = [], []
    pos_ret, neg_ret = [], []
    for i in range(1, n):
        p, c = slope[i - 1], slope[i]
        if p is None or c is None:
            continue
        if p <= 0 < c:
            pos_idx.append(i)
            r = nxt_ret(i)
            if r is not None:
                pos_ret.append(r)
        elif p >= 0 > c:
            neg_idx.append(i)
            r = nxt_ret(i)
            if r is not None:
                neg_ret.append(r)

    def st(rs, direction):
        if not rs:
            return None
        if direction > 0:
            hit = sum(1 for r in rs if r > 0)
        else:
            hit = sum(1 for r in rs if r < 0)
        return {"n": len(rs), "hit": round(hit / len(rs) * 100, 1),
                "mean": round(sum(rs) / len(rs), 3)}

    return {"slope": slope, "win": win,
            "pos_idx": pos_idx, "neg_idx": neg_idx,
            "stats": {"base_up": base_up, "base_n": len(base),
                      "pos": st(pos_ret, +1), "neg": st(neg_ret, -1)}}


def build_alert(high: float, low: float, slope_win: int = 5,
                check_slope: bool = True) -> tuple[str | None, dict]:
    """Return (telegram_message_or_None, summary). Fires when EITHER the
    premium crosses an absolute threshold (high/low) OR the slope just turned
    (positive/negative) on the most recent day."""
    r = fetch_premium_series("5y")
    if r.get("error"):
        return None, {"error": r["error"]}
    s, ser = r["summary"], r["series"]
    cur = s["current"]
    p1, n1 = _pctile(ser, 252, cur)
    n = len(ser)
    sections = []

    # ── A. 折溢價絕對門檻 ───────────────────────────────────────────
    if cur >= high:
        sections.append(
            f"🔴 溢價偏高 (≥{high:g}%)：{cur:+.2f}%\n"
            f"  溢價接近歷史高檔，美股對 2330 明顯樂觀 → 隔日易開高，"
            f"但高溢價有均值回歸風險。")
    elif cur <= low:
        tag = "翻折價" if low <= 0 else "折價/低溢價"
        sections.append(
            f"🟢 {tag} (≤{low:g}%)：{cur:+.2f}%\n"
            f"  溢價收斂/折價，美股對 2330 轉保守 → 隔日易開低 / 套利買盤進場。")

    # ── B. 斜率剛轉折 (最新一天) ────────────────────────────────────
    if check_slope and n >= slope_win + 1:
        sig = slope_signals(ser, win=slope_win)
        last = n - 1
        st = sig["stats"]
        if last in set(sig["pos_idx"]):
            hit = st["pos"]["hit"] if st["pos"] else 0
            sections.append(
                f"🟢▲ 斜率剛轉正 (動能翻多)\n"
                f"  折溢價斜率 {slope_win} 日由負轉正 → 隔日 2330 偏多"
                f"（歷史此訊號隔日收紅 {hit:.0f}%）。")
        elif last in set(sig["neg_idx"]):
            hit = st["neg"]["hit"] if st["neg"] else 0
            sections.append(
                f"🔴▼ 斜率剛轉負 (動能翻空)\n"
                f"  折溢價斜率 {slope_win} 日由正轉負 → 隔日 2330 偏空"
                f"（歷史此訊號隔日收黑 {hit:.0f}%）。")

    if not sections:
        return None, s

    msg = (
        f"🇺🇸 TSM ADR 折溢價警示 ({s['current_date']})\n\n"
        + "\n\n".join(sections) +
        f"\n\n當前折溢價 {cur:+.2f}% (近 1 年 {p1:.0f} 百分位)\n"
        f"  TSM ${s['current_tsm']} × {s['current_fx']} / 5 = "
        f"理論 {s['current_theo']:.0f} vs 2330 實際 {s['current_tw']:.0f}\n"
        f"註：TSM 收盤晚 2330 約 14.5h，為隔日開盤跳空前瞻指標（漲跌多在開盤反映）；"
        f"除權息日附近僅供參考。"
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
    ap.add_argument("--no-slope", action="store_true",
                    help="不檢查斜率轉折 (只看溢價門檻)")
    ap.add_argument("--telegram", action="store_true", help="推送 Telegram")
    ap.add_argument("--bot-token", help="或設 TG_BOT_TOKEN 環境變數")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    args = ap.parse_args()

    if args.alert:
        msg, s = build_alert(args.high, args.low,
                             check_slope=not args.no_slope)
        if s.get("error"):
            print("ERROR:", s["error"], file=sys.stderr)
            sys.exit(1)
        if not msg:
            print(f"[OK] 折溢價 {s['current']:+.2f}% 正常 + 斜率無轉折，不警示。")
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
