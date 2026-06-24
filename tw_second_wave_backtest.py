#!/usr/bin/env python3
"""強勢股第二波 回測 — 事件研究法 (event study)。

第二波是『每檔股票』的型態訊號（強漲→急殺15-25%→反彈啟動），不是排名，
所以用事件研究：每當某股某日觸發訊號，量它之後 H 日的報酬，跟
(a) 大盤、(b) 同universe隨機股票日 的基準比，看訊號有沒有 edge。

手法：直接 import 正式程式的 detect_second_wave（測真訊號），對每檔股票
逐日 point-in-time 跑（只用 ≤t 資料）。同一波連續觸發只取『首次』(episode 去重)。

資料：重用 concept_momentum/cache/backtest_prices.json (192 檔 date/close/volume)。
※ universe = 概念股 192 檔（正式 cron 掃全市場，這裡是子集，偏液性大票）。

用法：
  tw_second_wave_backtest.py
  tw_second_wave_backtest.py --horizon 5 10 20 --cost 0.4 --json-out path.json
"""
import argparse
import json
import os
import statistics
import sys
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tw_second_wave import detect_second_wave  # noqa: E402

PRICE_CACHE = os.path.join(HERE, "concept_momentum", "cache", "backtest_prices.json")

# 與 tw_second_wave.py add_argument 預設一致
DEFAULT_ARGS = Namespace(
    rally_min_gain=0.30, peak_lookback=60, drop_min=0.15, drop_max=0.25,
    min_drop_days=5, max_drop_days=15, min_recovery_days=1, max_recovery_days=10,
    recovery_min_gain=0.05, recovery_vol_ratio=0.7, max_today_vs_peak=0.98,
)
MIN_HISTORY = 135   # detect 需 rally_lookback(130)+ 緩衝


def load_prices():
    with open(PRICE_CACHE) as f:
        d = json.load(f)
    return d["stocks"], d["taiex"]


def fwd_ret(rows_close: dict, dates: list, i: int, h: int) -> float | None:
    if i + h >= len(dates):
        return None
    c0 = rows_close.get(dates[i]); c1 = rows_close.get(dates[i + h])
    if not c0 or not c1 or c0 <= 0:
        return None
    return (c1 / c0 - 1) * 100


def run(horizons, cost, dedup=True):
    stocks, taiex = load_prices()
    tx_close = {r["date"]: r["close"] for r in taiex}
    tx_dates = sorted(tx_close)

    def tx_fwd(date, h):
        if date not in tx_close:
            return None
        i = tx_dates.index(date) if date in tx_dates else None
        if i is None or i + h >= len(tx_dates):
            return None
        c0, c1 = tx_close[tx_dates[i]], tx_close[tx_dates[i + h]]
        return (c1 / c0 - 1) * 100 if c0 > 0 else None

    sig = {h: {"exc": [], "abs": [], "dates": []} for h in horizons}
    base = {h: [] for h in horizons}   # baseline: 所有可跑訊號的股票日
    n_signal_days = 0
    n_episodes = 0
    max_h = max(horizons)

    for code, s in stocks.items():
        rows = s["rows"]
        if len(rows) < MIN_HISTORY + max_h:
            continue
        dates = [r["date"] for r in rows]
        close = {r["date"]: r["close"] for r in rows}
        prev_fire = False
        for i in range(MIN_HISTORY, len(rows) - max_h):
            # baseline: 每個可評估股票日的前向超額 (vs 大盤)
            for h in horizons:
                fr = fwd_ret(close, dates, i, h)
                tf = tx_fwd(dates[i], h)
                if fr is not None and tf is not None:
                    base[h].append(fr - tf)
            # 訊號：只用 ≤i 的資料 point-in-time
            res = detect_second_wave(rows[:i + 1], DEFAULT_ARGS)
            fire = res is not None
            if fire:
                n_signal_days += 1
                is_entry = (not prev_fire) if dedup else True
                if is_entry:
                    n_episodes += 1
                    for h in horizons:
                        fr = fwd_ret(close, dates, i, h)
                        tf = tx_fwd(dates[i], h)
                        if fr is not None and tf is not None:
                            sig[h]["abs"].append(fr)
                            sig[h]["exc"].append(fr - tf)
                            sig[h]["dates"].append(dates[i])
            prev_fire = fire

    # 輸出
    summary = {"n_signal_days": n_signal_days, "n_episodes": n_episodes,
               "start": tx_dates[0], "end": tx_dates[-1], "cost": cost,
               "universe": len(stocks), "horizons": {}}
    print(f"\n{'='*60}\n強勢股第二波 回測（事件研究）"
          f"\n universe {len(stocks)} 檔・{tx_dates[0]}~{tx_dates[-1]}"
          f"\n 訊號觸發 {n_signal_days} 股票日 → 去重後 {n_episodes} 個進場 episode"
          f"\n{'='*60}")
    for h in horizons:
        S = sig[h]
        if not S["exc"]:
            print(f"\n[H={h}d] 無樣本"); continue
        exc = statistics.mean(S["exc"])
        net = exc - cost
        med = statistics.median(S["exc"])
        win = sum(1 for x in S["abs"] if x > 0) / len(S["abs"]) * 100   # 絕對賺錢
        beat = sum(1 for x in S["exc"] if x > 0) / len(S["exc"]) * 100  # 贏大盤
        b = statistics.mean(base[h]) if base[h] else 0.0               # 基準超額
        edge = net - b
        # 權益曲線 (非複利累加淨超額，按日期排序)
        order = sorted(range(len(S["dates"])), key=lambda k: S["dates"][k])
        eq, cum = [], 0.0
        for k in order:
            cum += S["exc"][k] - cost
            eq.append({"date": S["dates"][k], "cum": round(cum, 2)})
        summary["horizons"][h] = {
            "n": len(S["exc"]), "abs_mean": round(statistics.mean(S["abs"]), 2),
            "exc_mean": round(exc, 2), "net": round(net, 2), "exc_med": round(med, 2),
            "win": round(win, 0), "beat": round(beat, 0),
            "baseline": round(b, 2), "edge": round(edge, 2), "equity": eq}
        print(f"\n【持有 {h} 交易日】 進場 {len(S['exc'])} 次")
        print(f"  絕對報酬(均)      : {statistics.mean(S['abs']):+.2f}%  (賺錢率 {win:.0f}%)")
        print(f"  超額 vs 大盤(均)   : {exc:+.2f}%  (中位 {med:+.2f}%, 贏大盤率 {beat:.0f}%)")
        print(f"  扣 {cost}% 成本後淨超額: {net:+.2f}%")
        print(f"  基準(隨機股票日超額): {b:+.2f}%")
        print(f"  ⭐訊號 edge(淨−基準) : {edge:+.2f}%  ← 正=訊號真有用")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--cost", type=float, default=0.4)
    ap.add_argument("--no-dedup", action="store_true",
                    help="不做 episode 去重 (每個觸發日都算進場)")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    s = run(args.horizon, args.cost, dedup=not args.no_dedup)
    if args.json_out:
        from datetime import datetime
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "params": {"horizons": args.horizon, "cost": args.cost},
                       "result": s}, f, ensure_ascii=False)
        print(f"\n[json] 寫入 {args.json_out}", file=sys.stderr)
