#!/usr/bin/env python3
"""權證訊號回測 — 事件研究，分方向驗證 edge.

⚠ 結果誠實呈現有無 edge；無 edge 則不上線（見設計文件）。
"""
import os
import sys
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import warrant_signal as ws


def forward_return(closes: dict, code: str, signal_date: str,
                   horizon: int) -> float | None:
    series = closes.get(code, {})
    dates = sorted(series)
    if signal_date not in dates:
        return None
    i = dates.index(signal_date)
    if i + horizon >= len(dates):
        return None
    p0, p1 = series[signal_date], series[dates[i + horizon]]
    if not p0:
        return None
    return (p1 / p0 - 1) * 100


def _stats(vals: list[float], win_cmp) -> dict:
    if not vals:
        return {"n": 0, "win_rate": None, "median": None, "mean": None}
    wins = sum(1 for v in vals if win_cmp(v))
    return {"n": len(vals), "win_rate": round(wins / len(vals), 3),
            "median": round(statistics.median(vals), 2),
            "mean": round(statistics.mean(vals), 2)}


def evaluate(day_files: list[dict], closes: dict, horizon: int = 5,
             surge_min: float = 2.0, delta_min: float = 0.10) -> dict:
    bull_ret, bear_ret, base_ret = [], [], []
    # 逐日：用該日(含)之前的 day_files 產生訊號，算前瞻報酬
    for end in range(21, len(day_files) + 1):
        window = day_files[:end]
        sig_date = window[-1]["date"]
        rows = ws.build_signal_rows(window, surge_min=surge_min,
                                    delta_min=delta_min)
        for r in rows:
            fr = forward_return(closes, r["code"], sig_date, horizon)
            if fr is None:
                continue
            if r["direction"] == "bull":
                bull_ret.append(fr)
            elif r["direction"] == "bear":
                bear_ret.append(fr)
        # baseline：該日所有標的（不論訊號）
        for code in window[-1].get("underlyings", {}):
            fr = forward_return(closes, code, sig_date, horizon)
            if fr is not None:
                base_ret.append(fr)
    return {
        "horizon": horizon,
        "bull": _stats(bull_ret, lambda v: v > 0),
        "bear": _stats(bear_ret, lambda v: v < 0),
        "baseline": _stats(base_ret, lambda v: v > 0),
    }
