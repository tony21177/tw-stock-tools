#!/usr/bin/env python3
"""
「自營收 put」訊號回測 (tw_option_flow_backtest)

檢驗社群口徑:TXO 自營商 put 淨收權利金異常放大(≥1億 且 ≥近60日P90)
→ 隔日/後續加權指數是否偏多?

方法(walk-forward,與 tw_option_flow.detect_signal 同參數):
  每日 t 以「前 60 交易日」的自營 put 淨收分布算 P90/P10(不含當日),
  訊號於 t 收盤後可知 → 報酬從 t 收盤起算:
    gap  = open(t+1)/close(t) − 1
    H1   = close(t+1)/close(t) − 1
    H3/H5/H10 同理
  對照組 = 同期間所有可判定日。另做自營 put 淨收五分位 vs 隔日報酬。

資料:FinMind TaiwanOptionInstitutionalInvestors TXO(2020 起)+ TAIEX 日線。
用法:FINMIND_TOKEN=xxx python3 tw_option_flow_backtest.py [--start 2020-01-01]
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tw_option_flow import _pctl, PCTL_WIN, ABS_FLOOR, YI   # noqa: E402

FINMIND = "https://api.finmindtrade.com/api/v4/data"
CACHE = os.path.join(HERE, "concept_momentum", "cache")


def _fm(dataset: str, params: dict, token: str) -> list[dict]:
    p = {"dataset": dataset, "token": token, **params}
    req = urllib.request.Request(FINMIND + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        payload = json.load(r)
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset}: {payload.get('msg')}")
    return payload.get("data", [])


def load_series(token: str, start: str):
    """回傳 dates(升冪), dp{date:自營put淨收億}, taiex{date:(open,close)}。"""
    rows = _fm("TaiwanOptionInstitutionalInvestors",
               {"data_id": "TXO", "start_date": start}, token)
    dp = {}
    for r in rows:
        if (r.get("institutional_investors") == "自營商"
                and r.get("call_put") == "賣權"):
            dp[r["date"]] = (r.get("short_deal_amount", 0)
                             - r.get("long_deal_amount", 0)) / YI
    trows = _fm("TaiwanStockPrice", {"data_id": "TAIEX", "start_date": start}, token)
    taiex = {r["date"]: (r["open"], r["close"]) for r in trows
             if r.get("open") and r.get("close")}
    dates = sorted(set(dp) & set(taiex))
    return dates, dp, taiex


def stats(vals: list[float]) -> dict:
    n = len(vals)
    if n == 0:
        return {"n": 0}
    mean = sum(vals) / n
    med = sorted(vals)[n // 2]
    win = sum(1 for v in vals if v > 0) / n * 100
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / n) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean": mean, "med": med, "win": win, "sd": sd, "t": t}


def fmt(s: dict) -> str:
    if s["n"] == 0:
        return "n=0"
    return (f"n={s['n']:4d}  勝率{s['win']:5.1f}%  平均{s['mean']*100:+6.2f}%  "
            f"中位{s['med']*100:+6.2f}%  t={s['t']:+.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("需要 FINMIND_TOKEN"); sys.exit(1)

    dates, dp, taiex = load_series(token, args.start)
    print(f"資料 {dates[0]} ~ {dates[-1]},共 {len(dates)} 交易日\n")

    horizons = [("gap", 1), ("H1", 1), ("H3", 3), ("H5", 5), ("H10", 10)]
    bull, bear, base = {h: [] for h, _ in horizons}, {h: [] for h, _ in horizons}, {h: [] for h, _ in horizons}
    bull_days, bear_days = [], []
    dp_next = []                                     # (dp_t, H1 報酬) 五分位用

    for i in range(PCTL_WIN, len(dates) - 10):
        t = dates[i]
        hist = [dp[d] for d in dates[i - PCTL_WIN:i]]
        p90, p10 = _pctl(hist, 0.90), _pctl(hist, 0.10)
        v = dp[t]
        c0 = taiex[t][1]
        rets = {}
        ok = True
        for h, k in horizons:
            if i + k >= len(dates):
                ok = False; break
            if h == "gap":
                rets[h] = taiex[dates[i + 1]][0] / c0 - 1
            else:
                rets[h] = taiex[dates[i + k]][1] / c0 - 1
        if not ok:
            continue
        for h, _ in horizons:
            base[h].append(rets[h])
        dp_next.append((v, rets["H1"]))
        if v >= ABS_FLOOR and v >= p90:
            bull_days.append((t, v, rets["H1"]))
            for h, _ in horizons:
                bull[h].append(rets[h])
        elif v <= -ABS_FLOOR and v <= p10:
            bear_days.append((t, v, rets["H1"]))
            for h, _ in horizons:
                bear[h].append(rets[h])

    print("═══ 🟢 轉多訊號(自營put淨收 ≥1億 且 ≥P90)後續加權報酬 ═══")
    for h, _ in horizons:
        print(f"  {h:4}: {fmt(stats(bull[h]))}")
    print("═══ 🔴 偏空訊號(淨買 ≤−1億 且 ≤P10)═══")
    for h, _ in horizons:
        print(f"  {h:4}: {fmt(stats(bear[h]))}")
    print("═══ 對照組(全部日)═══")
    for h, _ in horizons:
        print(f"  {h:4}: {fmt(stats(base[h]))}")

    # 五分位:自營 put 淨收大小 vs 隔日報酬(連續預測力)
    print("\n═══ 自營put淨收 五分位 vs 隔日(H1)報酬 ═══")
    dp_sorted = sorted(dp_next, key=lambda x: x[0])
    qn = len(dp_sorted) // 5
    quints = []
    for q in range(5):
        seg = dp_sorted[q * qn:(q + 1) * qn] if q < 4 else dp_sorted[4 * qn:]
        vals = [r for _, r in seg]
        lo, hi = seg[0][0], seg[-1][0]
        s = stats(vals)
        quints.append({"q": q + 1, "lo": lo, "hi": hi, **{k: s[k] for k in ("n", "mean", "win")}})
        print(f"  Q{q+1} [{lo:+6.2f}~{hi:+6.2f}億]: {fmt(s)}")

    print("\n═══ 🟢 訊號日明細(近 15 筆)═══")
    for t, v, r in bull_days[-15:]:
        print(f"  {t}  淨收{v:+.2f}億 → 隔日 {r*100:+.2f}%")

    if args.json_out:
        out = {
            "window": f"{dates[0]}~{dates[-1]}",
            "bull": {h: stats(bull[h]) for h, _ in horizons},
            "bear": {h: stats(bear[h]) for h, _ in horizons},
            "base": {h: stats(base[h]) for h, _ in horizons},
            "quintiles": quints,
            "n_bull": len(bull_days), "n_bear": len(bear_days),
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        print(f"\n寫入 {args.json_out}")


if __name__ == "__main__":
    main()
