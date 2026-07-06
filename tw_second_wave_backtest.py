#!/usr/bin/env python3
"""強勢股第二波 回測 v2 — 事件研究。

v2 相對 v1 的差異：
  - 進場：預設『訊號隔日還原開盤價』(--entry next_open)。訊號 07:40 盤前產生，
    隔日開盤是最早可實現的成交價；v1 的訊號日收盤進場把隔夜跳空算進去（不可實現）。
  - 報酬：還原價 (aopen/aclose)，跨除息的持有期不再低估。
  - 訊號除污：偵測窗 (peak→signal) 內有除權息交易日的 episode 剔除
    （未還原收盤的除權缺口會偽造 F3 急跌）— 剔除數記在 n_skipped_div。
  - 統計：bootstrap 95% CI + t-stat + 中位數 + 分年 (2025/2026)。
  - 基準：與事件同日期的隨機股票日 (date-matched)。
偵測邏輯不變：import 正式 detect_second_wave point-in-time 跑。
"""
import argparse
import json
import os
import sys
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                                  # noqa: E402
from backtest_prices import load_panel                     # noqa: E402
from tw_second_wave import detect_second_wave, FILTER_DEFAULTS  # noqa: E402

DEFAULT_ARGS = Namespace(**FILTER_DEFAULTS)
MIN_HISTORY = 135


def run(horizons, cost, entry="next_open", dedup_days=None, start="2025-01-01",
        baseline_k=100):
    panel = load_panel(start)
    max_h = max(horizons)
    cooldown = dedup_days if dedup_days is not None else max_h
    events = []          # (code, date, i)
    n_signal_days = 0
    n_skipped_div = 0

    for code, s in panel.stocks.items():
        rows = s["rows"]
        if len(rows) < MIN_HISTORY + max_h:
            continue
        fires = []
        for i in range(MIN_HISTORY, len(rows) - max_h):
            res = detect_second_wave(rows[:i + 1], DEFAULT_ARGS)
            if res is None:
                continue
            n_signal_days += 1
            # 除權息 guard：偵測窗 (peak_date, signal_date] 有除權息 → 假急跌
            if panel.has_ex_dividend(code, res["peak_date"], rows[i]["date"]):
                n_skipped_div += 1
                continue
            fires.append(i)
        for i in bl.dedup_cooldown(fires, cooldown):
            events.append((code, rows[i]["date"], i))

    summary = {"n_signal_days": n_signal_days, "n_episodes": len(events),
               "n_skipped_div": n_skipped_div, "entry": entry, "cost": cost,
               "start": panel.tx_dates[0], "end": panel.tx_dates[-1],
               "universe": len(panel.stocks), "universe_label": "全市場",
               "horizons": {}}
    print(f"\n{'='*60}\n第二波 回測 v2  entry={entry}  cost={cost}%"
          f"\n universe {len(panel.stocks)} 檔・{panel.tx_dates[0]}~{panel.tx_dates[-1]}"
          f"\n 訊號 {n_signal_days} 股票日 → 除權息剔除 {n_skipped_div} → "
          f"episodes {len(events)}\n{'='*60}")

    for h in horizons:
        absr, excr, edges, dates = [], [], [], []
        by_year = {}
        for code, date, _i in events:
            r = panel.fwd(code, date, h, entry)
            if r is None:
                continue
            sr, tr = r
            b = panel.matched_baseline(date, h, k=baseline_k, entry=entry)
            absr.append(sr); excr.append(sr - tr); dates.append(date)
            if b is not None:
                edges.append(sr - tr - b)
            by_year.setdefault(date[:4], []).append(sr - tr)
        s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
        s["per_year"] = {y: {"n": len(v),
                             "exc_mean": round(sum(v) / len(v), 2),
                             "exc_ci": [round(x, 2) for x in bl.bootstrap_ci(v)]}
                         for y, v in sorted(by_year.items())}
        # 權益曲線（沿用 v1 呈現：非複利累加淨超額）
        order = sorted(range(len(dates)), key=lambda k: dates[k])
        eq, cum = [], 0.0
        for k in order:
            cum += excr[k] - cost
            eq.append({"date": dates[k], "cum": round(cum, 2)})
        s["equity"] = eq
        summary["horizons"][h] = s
        if s["n"]:
            print(f"\n【H={h}d】n={s['n']}  絕對 {s['abs_mean']:+.2f}% (勝率 {s['win']:.0f}%)")
            print(f"  超額均 {s['exc_mean']:+.2f}%  中位 {s['exc_med']:+.2f}%  "
                  f"95%CI [{s['exc_ci'][0]:+.2f}, {s['exc_ci'][1]:+.2f}]  t={s['t']:.2f}")
            print(f"  扣成本淨超額 {s['net']:+.2f}%  "
                  f"⭐edge {s.get('edge_mean', 0):+.2f}% CI {s.get('edge_ci')}")
            for y, v in s["per_year"].items():
                print(f"    {y}: n={v['n']} 超額 {v['exc_mean']:+.2f}% CI {v['exc_ci']}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--entry", default="next_open",
                    choices=["next_open", "signal_close"])
    ap.add_argument("--slippage-bp", type=float, default=0.0)
    ap.add_argument("--dedup-days", type=int, default=None,
                    help="episode cooldown 交易日數 (預設 = max horizon)")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    cost = (bl.cost_roundtrip_pct(slippage_bp=args.slippage_bp)
            if args.cost == bl.cost_roundtrip_pct() else args.cost)
    s = run(args.horizon, cost, entry=args.entry, dedup_days=args.dedup_days,
            start=args.start)
    if args.json_out:
        from datetime import datetime
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "params": {"horizons": args.horizon, "cost": cost,
                                  "entry": args.entry, "universe": "all"},
                       "result": s}, f, ensure_ascii=False)
        print(f"\n[json] 寫入 {args.json_out}", file=sys.stderr)
