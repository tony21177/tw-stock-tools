"""訊號成效追蹤 — 把 5 個推播歷史 dir 的每筆訊號配上 T+h 實際報酬 (後照鏡自動化)。

date 語意 (實測，勿信直覺)：
  turnaround_relay / broker_radar / lending_radar / short_retreat: date=資料日 → entry=下一交易日
  second_wave: date=執行日 (盤前) → entry=≥date 第一個交易日
entry 價 = entry_date 還原開盤；成效 = T+h 還原收盤報酬 − TAIEX 同窗。
"""
from __future__ import annotations
import bisect
import json
import os

STRATS = {
    "turnaround_relay": ("turnaround_relay_history", "candidates", "after"),
    "second_wave": ("second_wave_history", "candidates", "on_or_after"),
    "broker_radar": ("broker_radar_history", "stocks", "after"),
    "lending_radar": ("lending_radar_history", "stocks", "after"),
    "short_retreat": ("short_retreat_history", "stocks", "after"),
}


def _entry_date(date: str, rule: str, trading_dates: list[str]) -> str | None:
    if rule == "after":
        i = bisect.bisect_right(trading_dates, date)
    else:  # on_or_after
        i = bisect.bisect_left(trading_dates, date)
    return trading_dates[i] if i < len(trading_dates) else None


def load_signals(cache_root: str, trading_dates: list[str]) -> list[dict]:
    out, seen = [], set()
    for strat, (dirname, field, rule) in STRATS.items():
        d = os.path.join(cache_root, dirname)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(d, fn)))
            except (OSError, json.JSONDecodeError):
                continue
            date = str(data.get("date") or fn[:8])
            for item in data.get(field, []):
                code = str(item.get("code") or "")
                if not code:
                    continue
                key = (strat, date, code)
                if key in seen:      # 同訊號同日只算一次
                    continue
                seen.add(key)
                entry = _entry_date(date, rule, trading_dates)
                if entry is None:
                    continue
                meta = {k: v for k, v in item.items() if k not in ("code", "name")}
                meta["name"] = item.get("name", code)
                out.append({"strategy": strat, "signal_date": date,
                            "entry_date": entry, "code": code, "meta": meta})
    return out


def compute_outcomes(signals: list[dict], px_fetch, taiex: dict,
                     trading_dates: list[str], horizons=(1, 5, 10, 20)) -> dict:
    """px_fetch(code) -> {dateYYYYMMDD: {"aopen","aclose"}}；taiex[date] -> {"open","close"}。"""
    tx_idx = {d: i for i, d in enumerate(trading_dates)}
    recs = []
    for s in signals:
        px = px_fetch(s["code"])
        e = s["entry_date"]
        if e not in px or e not in tx_idx:
            continue
        e_px = px[e].get("aopen") or 0
        tx0 = taiex.get(e, {}).get("open") or taiex.get(e, {}).get("close") or 0
        if e_px <= 0 or tx0 <= 0:
            continue
        ei = tx_idx[e]
        ret = {}
        for h in horizons:
            if ei + h - 1 >= len(trading_dates):
                continue
            xd = trading_dates[ei + h - 1]          # T+h = entry 起第 h 個交易日收盤
            x = px.get(xd, {}).get("aclose") or 0
            tx1 = taiex.get(xd, {}).get("close") or 0
            if x <= 0 or tx1 <= 0:
                continue
            sr = (x / e_px - 1) * 100
            tr = (tx1 / tx0 - 1) * 100
            ret[str(h)] = {"abs": round(sr, 2), "exc": round(sr - tr, 2)}
        if ret:
            recs.append({**s, "ret": ret})
    # 彙總 per strategy × horizon
    agg = {}
    for r in recs:
        a = agg.setdefault(r["strategy"], {str(h): {"abs": [], "exc": []}
                                           for h in horizons})
        for h, v in r["ret"].items():
            a[h]["abs"].append(v["abs"])
            a[h]["exc"].append(v["exc"])
    summary = {}
    for strat, hs in agg.items():
        summary[strat] = {}
        for h, v in hs.items():
            n = len(v["exc"])
            if not n:
                continue
            summary[strat][h] = {
                "n": n,
                "abs_mean": round(sum(v["abs"]) / n, 2),
                "exc_mean": round(sum(v["exc"]) / n, 2),
                "exc_med": round(sorted(v["exc"])[n // 2], 2),
                "win": round(sum(1 for x in v["abs"] if x > 0) / n * 100, 0),
                "beat": round(sum(1 for x in v["exc"] if x > 0) / n * 100, 0),
            }
    return {"signals": recs, "summary": summary}
