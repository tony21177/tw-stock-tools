#!/usr/bin/env python3
"""權證訊號回測 — 事件研究，分方向驗證 edge.

⚠ 結果誠實呈現有無 edge；無 edge 則不上線（見設計文件）。
"""
import os
import sys
import statistics
import json
import glob

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


def sweep(day_files: list[dict], closes: dict, horizons: list[int],
          surge_grid: list[float], delta_grid: list[float]) -> list[dict]:
    """參數掃描：遍歷 (horizons × surge_grid × delta_grid)，回傳各組結果。

    Args:
        day_files: 日檔列表
        closes: 標的收盤價字典 {code: {date: price}}
        horizons: 回報期間列表
        surge_grid: 爆量閾值列表
        delta_grid: 失衡幅度列表

    Returns:
        list[dict]: 每組參數一筆，含 horizon/surge_min/delta_min/bull/bear/baseline
    """
    out = []
    for h in horizons:
        for sg in surge_grid:
            for dg in delta_grid:
                res = evaluate(day_files, closes, horizon=h,
                               surge_min=sg, delta_min=dg)
                out.append({"horizon": h, "surge_min": sg, "delta_min": dg,
                            "bull": res["bull"], "bear": res["bear"],
                            "baseline": res["baseline"]})
    return out


def _main():
    """CLI：讀 warrant_flow 日檔 + FinMind 收盤 → 參數掃描 + 印摘要表。"""
    import argparse
    import warrant_flow as wf
    sys.path.insert(0, os.path.dirname(HERE))  # repo root for finmind_client
    import finmind_client

    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-days", type=int, default=120)
    ap.add_argument("--json-out")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(wf.FLOW_DIR, "*.json")))[-args.backfill_days:]
    day_files = [json.load(open(f, encoding="utf-8")) for f in files]
    if not day_files:
        print("[backtest] 無 warrant_flow 日檔，先 backfill", file=sys.stderr)
        return
    codes = set()
    for df in day_files:
        codes.update(df.get("underlyings", {}))
    start = day_files[0]["date"]
    end = day_files[-1]["date"]
    tok = os.environ.get("FINMIND_TOKEN", "")
    s_iso = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e_iso = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    closes = {}
    for c in codes:
        try:
            rows = finmind_client.fetch_stock_price(c, s_iso, e_iso, tok)
            closes[c] = {r["date"].replace("-", ""): r["close"]
                         for r in rows if r.get("close")}
        except Exception:
            continue
    grid = sweep(day_files, closes, horizons=[1, 3, 5, 10],
                 surge_grid=[2.0, 3.0, 5.0], delta_grid=[0.10, 0.15])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"start": start, "end": end, "grid": grid}, f,
                      ensure_ascii=False, indent=1)
    for g in grid:
        b, be, ba = g["bull"], g["bear"], g["baseline"]
        print(f"h{g['horizon']} surge{g['surge_min']} d{g['delta_min']}: "
              f"多 n{b['n']} 勝{b['win_rate']} 中{b['median']} | "
              f"空 n{be['n']} 勝{be['win_rate']} 中{be['median']} | "
              f"基準 中{ba['median']}")


if __name__ == "__main__":
    _main()
