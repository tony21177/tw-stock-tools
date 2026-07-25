#!/usr/bin/env python3
"""tw_lin_matrix_backtest — 林則行矩陣「爆量突破」事件研究回測。

用 v2 回測價格面板 (backtest_prices_v2.json，1895 檔・2025-01~2026-07)驗證:
矩陣突破訊號(低量箱型 ≤15% → 收盤破天花板 + 量 2-10 倍)進場後,持有
H 日的還原報酬能否顯著贏過大盤 / 同日隨機基準。

  - 進場：訊號隔日還原開盤價 (--entry next_open)，避免看未來。
  - 報酬：還原價 (aopen/aclose)，跨除息不失真；超額 = 個股 − TAIEX。
  - edge：每事件超額 − 同日 k 檔隨機股平均超額(控當日大盤/風格)。
  - 去重：同股觸發後 cooldown 根內不再進場 (預設 = max horizon)。

⚠ 資料落差(重要,寫入結論):v2 面板只有 open/close/volume,無 high/low。
  live 篩選器用 high/low 定天花板與幅度;此回測改用 **收盤價** 定箱型邊界
  (high=low=close 餵同一套 detect_matrix/classify)。故為「收盤價口徑」的
  矩陣突破,與線上盤中口徑略有差異(收盤口徑濾掉上下影線雜訊,較保守)。

用法:
  python3 tw_lin_matrix_backtest.py                       # H=5/10/20 全期
  python3 tw_lin_matrix_backtest.py --json-out bt.json    # 存結果
  python3 tw_lin_matrix_backtest.py --is-end 20251231     # IS/OOS 切窗
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                       # noqa: E402
from backtest_prices import load_panel          # noqa: E402
from lin_matrix import (MIN_BOX_DAYS, detect_matrix, classify)  # noqa: E402

MIN_HISTORY = MIN_BOX_DAYS + 1     # 需 ≥60 日箱 + 今日；再加盤整前量能基準更佳


def _in_universe(code: str) -> bool:
    """與 live 篩選器同口徑:4 位數個股、排除 00 開頭 ETF。"""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


def _as_hlc(rows):
    """v2 面板列(無 high/low)→ 餵 detect_matrix 的序列:high=low=close。"""
    return [{"date": r["date"], "high": r["close"], "low": r["close"],
             "close": r["close"], "volume": r["volume"]} for r in rows]


def _rolling_high_flags(closes, look=MIN_BOX_DAYS):
    """flags[i]=True 若 close[i] > 前 look 日最高收(嚴格 60 日新高)。
    突破⟹創箱頂新高⟹創 ≥60 日新高,故此為必要條件,可安全預篩加速。"""
    n = len(closes)
    flags = [False] * n
    for i in range(look, n):
        if closes[i] > max(closes[i - look:i]):
            flags[i] = True
    return flags


def find_breakouts(rows):
    """回該股所有矩陣突破日的 index(收盤口徑)。"""
    series = _as_hlc(rows)
    closes = [r["close"] for r in rows]
    hi_flags = _rolling_high_flags(closes)
    fires = []
    for i in range(MIN_HISTORY, len(rows)):
        if not hi_flags[i]:            # 非 60 日新高 → 不可能突破,跳過(加速)
            continue
        sub = series[:i + 1]
        m = detect_matrix(sub, as_of_idx=len(sub) - 2)   # 今日之前的箱
        if not m:
            continue
        if classify(sub, m)["breakout"]:
            fires.append((i, m))
    return fires


def _summarize_window(panel, events, h, cost, entry, baseline_k):
    absr, excr, edges, dates = [], [], [], []
    by_year = {}
    for code, date, _i in events:
        r = panel.fwd(code, date, h, entry)
        if r is None:
            continue
        sr, tr = r
        b = panel.matched_baseline(date, h, k=baseline_k, entry=entry)
        if b is not None:
            edges.append((sr - tr) - b)
        absr.append(sr)
        excr.append(sr - tr)
        dates.append(date)
        by_year.setdefault(date[:4], []).append(sr - tr)
    s = bl.summarize_events(absr, excr, cost, edge_samples=edges)
    return s, {"dates": dates, "excr": excr, "by_year": by_year}


def run(horizons, cost, entry="next_open", dedup_days=None,
        start="2025-01-01", baseline_k=100, windows=None):
    panel = load_panel(start)
    max_h = max(horizons)
    cooldown = dedup_days if dedup_days is not None else max_h
    events = []
    n_signal_days = 0
    n_skipped_div = 0

    n_universe = 0
    for code, s in panel.stocks.items():
        if not _in_universe(code):
            continue
        n_universe += 1
        rows = s["rows"]
        if len(rows) < MIN_HISTORY + max_h:
            continue
        fires_i = []
        for i, m in find_breakouts(rows):
            if i >= len(rows) - max_h:       # 出場窗超出面板 → 無法衡量
                continue
            n_signal_days += 1
            # 除權息 guard:箱型期間有除權息 → 未還原收盤被人為調降,箱頂失真
            if panel.has_ex_dividend(code, m["start"], rows[i]["date"]):
                n_skipped_div += 1
                continue
            fires_i.append(i)
        for i in bl.dedup_cooldown(fires_i, cooldown):
            events.append((code, rows[i]["date"], i))

    summary = {"strategy": "lin_matrix_breakout", "entry": entry, "cost": cost,
               "n_signal_days": n_signal_days, "n_skipped_div": n_skipped_div,
               "n_episodes": len(events), "start": panel.tx_dates[0],
               "end": panel.tx_dates[-1], "universe": n_universe,
               "price_basis": "close (面板無 high/low)", "horizons": {}}
    print(f"\n{'='*62}\n林則行矩陣突破 回測  entry={entry}  cost={cost}%"
          f"\n universe {n_universe} 檔個股・{panel.tx_dates[0]}~{panel.tx_dates[-1]}"
          f"  (收盤價口徑)"
          f"\n 訊號 {n_signal_days} 股票日 → 除息剔除 {n_skipped_div} → "
          f"episodes {len(events)}\n{'='*62}")

    for h in horizons:
        s, extra = _summarize_window(panel, events, h, cost, entry, baseline_k)
        by_year = extra["by_year"]
        s["per_year"] = {y: {"n": len(v), "exc_mean": round(sum(v) / len(v), 2),
                             "exc_ci": [round(x, 2) for x in bl.bootstrap_ci(v)]}
                         for y, v in sorted(by_year.items())}
        summary["horizons"][h] = s
        if s["n"]:
            print(f"\n【H={h}d】n={s['n']}  絕對 {s['abs_mean']:+.2f}% "
                  f"(勝率 {s['win']:.0f}%,贏大盤 {s['beat']:.0f}%)")
            print(f"  超額均 {s['exc_mean']:+.2f}%  中位 {s['exc_med']:+.2f}%  "
                  f"95%CI [{s['exc_ci'][0]:+.2f}, {s['exc_ci'][1]:+.2f}]  t={s['t']:.2f}")
            print(f"  扣成本淨超額 {s['net']:+.2f}%  "
                  f"⭐edge {s.get('edge_mean', 0):+.2f}% CI {s.get('edge_ci')}")
            for y, v in s["per_year"].items():
                print(f"    {y}: n={v['n']} 超額 {v['exc_mean']:+.2f}% CI {v['exc_ci']}")

    if windows:
        win_events = bl.split_by_window(events, windows)
        summary["windows"] = {}
        print(f"\n{'='*62}\n IS/OOS 切窗彙總  {windows}\n{'='*62}")
        for label, subset in win_events.items():
            summary["windows"][label] = {}
            print(f" [{label}] n_episodes={len(subset)}")
            for h in horizons:
                s_w, _ = _summarize_window(panel, subset, h, cost, entry, baseline_k)
                summary["windows"][label][h] = s_w
                if s_w["n"]:
                    print(f"   H={h}d n={s_w['n']} 超額 {s_w['exc_mean']:+.2f}% "
                          f"CI {s_w['exc_ci']} t={s_w['t']} 淨 {s_w['net']:+.2f}%")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=bl.cost_roundtrip_pct())
    ap.add_argument("--entry", default="next_open",
                    choices=["next_open", "signal_close"])
    ap.add_argument("--dedup-days", type=int, default=None)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--baseline-k", type=int, default=100)
    ap.add_argument("--is-end", default=None,
                    help="IS 結束日 YYYYMMDD;設了就切 IS/OOS")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    windows = None
    if args.is_end:
        windows = {"IS": (args.start.replace("-", ""), args.is_end),
                   "OOS": (str(int(args.is_end) + 1), "20301231")}
    s = run(args.horizon, args.cost, entry=args.entry,
            dedup_days=args.dedup_days, start=args.start,
            baseline_k=args.baseline_k, windows=windows)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        print(f"\n→ 已存 {args.json_out}")
