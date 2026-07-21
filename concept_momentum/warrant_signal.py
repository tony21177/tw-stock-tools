#!/usr/bin/env python3
"""權證訊號 — 由 warrant_flow 日檔算爆量×失衡×方向.

⚠ 門檻先驗、未回測（見 warrant_signal_backtest.py）。
"""
SURGE_MIN = 2.0
SHARE_DELTA_MIN = 0.10


def _total(u: dict) -> float:
    return (u.get("bull_turnover", 0.0) or 0.0) + (u.get("bear_turnover", 0.0) or 0.0)


def build_signal_rows(day_files: list[dict], surge_min: float = SURGE_MIN,
                      delta_min: float = SHARE_DELTA_MIN) -> list[dict]:
    if not day_files:
        return []
    latest = day_files[-1]
    rows = []
    for code, cur in latest.get("underlyings", {}).items():
        tot = _total(cur)
        if tot <= 0:
            continue
        # 前 N 日（不含今日）總量與 bull_share 序列
        prior_tot, prior_share = [], []
        for df in day_files[:-1]:
            u = df.get("underlyings", {}).get(code)
            if not u:
                continue
            t = _total(u)
            if t > 0:
                prior_tot.append(t)
                prior_share.append((u.get("bull_turnover", 0.0) or 0.0) / t)
        prior_tot = prior_tot[-20:]
        prior_share = prior_share[-20:]
        if not prior_tot:
            continue
        surge = tot / (sum(prior_tot) / len(prior_tot))
        if surge < surge_min:
            continue
        bull_share = (cur.get("bull_turnover", 0.0) or 0.0) / tot
        base_share = sum(prior_share) / len(prior_share) if prior_share else bull_share
        delta = bull_share - base_share
        if abs(delta) >= delta_min:
            direction = "bull" if delta > 0 else "bear"
        else:
            direction = "neutral"
        rows.append({
            "code": code, "warrant_turnover": tot,
            "surge_ratio": round(surge, 2),
            "bull_share": round(bull_share, 3),
            "bull_share_20d": round(base_share, 3),
            "bull_share_delta": round(delta, 3),
            "direction": direction,
        })
    rows.sort(key=lambda r: -r["surge_ratio"])
    return rows
