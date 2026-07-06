#!/usr/bin/env python3
"""主力雷達 回測 (事件研究) v2。

主力雷達靠分點 BSR，BSR 無歷史 API → 不能重算歷史訊號。
改用 cron 每天存下的『實際訊號輸出』broker_radar_history/YYYYMMDD.json
做事件研究：每個被點名的 (股票,日)，量它之後 H 日報酬 vs 大盤 vs
同期隨機股票日基準(edge)。

⚠ 訊號於 18:00(收盤後)產生 → 真實進場是隔日開盤；v2 預設 --entry next
  (隔日開盤)。--entry signal 改用訊號日收盤（理想化，供對照）。
  date-matched 基準 + bootstrap 95% CI。

用法：
  tw_broker_radar_backtest.py
  tw_broker_radar_backtest.py --entry next --json-out out.json
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backtest_lib as bl                   # noqa: E402
from backtest_prices import load_panel      # noqa: E402

HIST = os.path.join(HERE, "concept_momentum", "cache", "broker_radar_history")


def load_events() -> list[tuple]:
    """回 [(date YYYYMMDD, code)] 去重(同股同日只一次)。"""
    ev = []
    seen: set[tuple] = set()
    for f in sorted(glob.glob(os.path.join(HIST, "2026*.json"))):
        d = json.load(open(f))
        date = os.path.basename(f)[:8]
        for s in d.get("stocks", []):
            key = (date, str(s["code"]))
            if key not in seen:
                seen.add(key)
                ev.append(key)
    return ev


def run(entry: str = "next", horizons: tuple = (5, 10, 20), cost: float | None = None):
    """事件研究主流程。entry: 'next' = 隔日開盤(預設), 'signal' = 訊號日收盤。"""
    if cost is None:
        cost = bl.cost_roundtrip_pct()
    entry_mode = "next_open" if entry == "next" else "signal_close"
    panel = load_panel()
    max_h = max(horizons)

    ev_raw = load_events()
    n_events_raw = len(ev_raw)

    # Group by code for per-code dedup
    by_code: dict[str, list[str]] = {}
    for date, code in ev_raw:
        by_code.setdefault(code, []).append(date)

    # Dedup per code using signal-date row indices (entry-shift NOT applied here)
    n_skipped_no_data = 0
    events: list[tuple[str, str]] = []   # (date YYYYMMDD, code)
    for code in sorted(by_code):
        dates = by_code[code]
        if code not in panel._by_code:
            n_skipped_no_data += len(dates)
            continue
        _, didx = panel._by_code[code]
        idx_to_date: dict[int, str] = {}
        for date in dates:
            if date not in didx:
                n_skipped_no_data += 1
                continue
            i = didx[date]
            idx_to_date[i] = date   # same idx = same signal date → keep one
        for i in bl.dedup_cooldown(sorted(idx_to_date), max_h):
            events.append((idx_to_date[i], code))

    n_episodes = len(events)

    per_h: dict[int, dict] = {h: {"abs": [], "exc": [], "edges": []} for h in horizons}
    for date, code in events:
        for h in horizons:
            r = panel.fwd(code, date, h, entry_mode)
            if r is None:
                continue
            sr, tr = r
            b = panel.matched_baseline(date, h, entry=entry_mode)
            per_h[h]["abs"].append(sr)
            per_h[h]["exc"].append(sr - tr)
            if b is not None:
                per_h[h]["edges"].append(sr - tr - b)

    print(f"\n主力雷達 事件研究  進場={entry}({entry_mode})"
          f"  原始事件 {n_events_raw} → 去重 {n_episodes}"
          f"  無資料跳過 {n_skipped_no_data}")

    out: dict = {"n_events_raw": n_events_raw, "n_episodes": n_episodes,
                 "n_skipped_no_data": n_skipped_no_data, "entry": entry,
                 "horizons": {}}

    for h in horizons:
        R = per_h[h]
        if not R["exc"]:
            continue
        s = bl.summarize_events(R["abs"], R["exc"], cost,
                                edge_samples=R["edges"] or None)
        out["horizons"][h] = s
        print(f"\n【持有 {h} 日】 樣本 {s['n']}")
        if s["n"] < 30:
            print("  ⚠ 樣本 <30，CI 很寬，結論僅供參考")
        print(f"  絕對報酬 {s['abs_mean']:+.2f}% (賺錢率 {s['win']:.0f}%)")
        print(f"  超額vs大盤 {s['exc_mean']:+.2f}% (中位 {s['exc_med']:+.2f}%,"
              f" 贏大盤率 {s['beat']:.0f}%,"
              f" 95%CI [{s['exc_ci'][0]:+.2f},{s['exc_ci'][1]:+.2f}],"
              f" t={s['t']:.2f})")
        if "edge_mean" in s:
            print(f"  ⭐edge {s['edge_mean']:+.2f}% CI {s.get('edge_ci')}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="next", choices=["signal", "next"])
    ap.add_argument("--cost", type=float, default=None)
    ap.add_argument("--json-out")
    args = ap.parse_args()
    cost = args.cost if args.cost is not None else bl.cost_roundtrip_pct()
    r = run(args.entry, cost=cost)
    if args.json_out:
        from datetime import datetime
        other = "signal" if args.entry == "next" else "next"
        r_other = run(other, cost=cost)
        r_signal = r if args.entry == "signal" else r_other
        r_next   = r if args.entry == "next"   else r_other
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "result": r_signal,
                   "result_next": r_next},
                  open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n[json] 寫入 {args.json_out}", file=sys.stderr)
