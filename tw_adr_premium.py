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
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

ADR_RATIO = 5  # 1 TSM = 5 × 2330


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


if __name__ == "__main__":
    yrs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
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
