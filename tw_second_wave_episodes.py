#!/usr/bin/env python3
"""第二波 episode 收集器 — 對 v2 面板重播偵測，輸出每個 episode 的
特徵 + 前向超額，供子群/regime/出場規則等分析使用。

輸出欄位：code/date/year/score/vol20_zhang/turn20_m(百萬)/
rally_gain/drop_pct/drop_days/bounce_pct/vol_ratio/today_vs_peak/
days_since_trough/peak_date/trough_date/exc5/exc10/exc20

用法：
  python3 tw_second_wave_episodes.py                       # 預設 2025 面板
  python3 tw_second_wave_episodes.py --start 2022-01-01    # 2022 長面板
  → 寫 bt_cache/sw_episodes_{start}.json
"""
import argparse
import json
import os
import sys
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                        # noqa: E402
from backtest_prices import load_panel, BT_CACHE                 # noqa: E402
from tw_second_wave import detect_second_wave, FILTER_DEFAULTS   # noqa: E402

MIN_HISTORY = 135
MAXH = 20


def collect(start: str = "2025-01-01", params_override: dict | None = None) -> list[dict]:
    args = Namespace(**{**FILTER_DEFAULTS, **(params_override or {})})
    panel = load_panel(start)
    episodes = []
    for n, (code, s) in enumerate(sorted(panel.stocks.items())):
        rows = s["rows"]
        if len(rows) < MIN_HISTORY + MAXH:
            continue
        fires, sigs = [], {}
        for i in range(MIN_HISTORY, len(rows) - MAXH):
            res = detect_second_wave(rows[:i + 1], args)
            if res is None:
                continue
            if panel.has_ex_dividend(code, res["peak_date"], rows[i]["date"]):
                continue
            fires.append(i)
            sigs[i] = res
        for i in bl.dedup_cooldown(fires, MAXH):
            d = rows[i]["date"]
            res = sigs[i]
            fwd = {}
            for h in (5, 10, 20):
                r = panel.fwd(code, d, h, "next_open")
                if r:
                    fwd[h] = round(r[0] - r[1], 3)
            if 20 not in fwd:
                continue
            vol20 = sum(x["volume"] for x in rows[max(0, i - 19):i + 1]) / min(20, i + 1) / 1000
            turn20_m = vol20 * rows[i]["close"] / 1000
            score = (res["rally_gain"] * res["drop_pct"] * res["bounce_pct"]
                     * min(res["vol_ratio"], 3) * (res["today_vs_peak"] - 0.7))
            ep = {"code": code, "date": d, "year": d[:4], "i": i,
                  "score": round(score, 5), "vol20_zhang": round(vol20, 1),
                  "turn20_m": round(turn20_m, 1),
                  "peak_date": res["peak_date"], "trough_date": res["trough_date"],
                  "trough_close": res["trough_close"]}
            for k in ("rally_gain", "drop_pct", "drop_days", "bounce_pct",
                      "vol_ratio", "today_vs_peak", "days_since_trough"):
                ep[k] = round(res[k], 4)
            for h in (5, 10, 20):
                ep[f"exc{h}"] = fwd.get(h)
            episodes.append(ep)
        if (n + 1) % 300 == 0:
            print(f"  {n+1}/{len(panel.stocks)} episodes={len(episodes)}", file=sys.stderr)
    return episodes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    args = ap.parse_args()
    eps = collect(args.start)
    out = os.path.join(BT_CACHE, f"sw_episodes_{args.start.replace('-', '')}.json")
    json.dump(eps, open(out, "w"))
    print(f"完成 → {out}  n={len(eps)}")
