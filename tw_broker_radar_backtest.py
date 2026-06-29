#!/usr/bin/env python3
"""主力雷達 回測 (事件研究)。

主力雷達靠分點 BSR，BSR 無歷史 API → 不能重算歷史訊號。
改用 cron 每天存下的『實際訊號輸出』broker_radar_history/YYYYMMDD.json
做事件研究：每個被點名的 (股票,日)，量它之後 H 日報酬 vs 大盤 vs
同期隨機股票日基準(edge)。

⚠ 訊號於 18:00(收盤後)產生 → 真實進場是隔天；本測以『訊號日收盤』為
進場基準(理想化)，並另算『隔天收盤進場』供對照。

用法：
  tw_broker_radar_backtest.py
  tw_broker_radar_backtest.py --entry next --json-out out.json
"""
import argparse
import glob
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tw_intraday_sim as sim  # noqa: E402

HIST = os.path.join(HERE, "concept_momentum", "cache", "broker_radar_history")
PRICE_ALL = os.path.join(HERE, "concept_momentum", "cache", "backtest_prices_all.json")


def load_events() -> list[tuple]:
    """回 [(date YYYYMMDD, code)] 去重(同股同日只一次)。"""
    ev = []
    for f in sorted(glob.glob(os.path.join(HIST, "2026*.json"))):
        d = json.load(open(f))
        date = os.path.basename(f)[:8]
        for s in d.get("stocks", []):
            ev.append((date, str(s["code"])))
    return ev


def fetch_closes(codes: set, token: str) -> dict:
    """{code: {date: close}}，新抓 FinMind 確保涵蓋最近。"""
    out = {}
    for c in sorted(codes):
        rows = sim.fetch_daily(c, "2026-03-01", token)
        if rows:
            out[c] = ({r["date"]: r["close"] for r in rows},
                      [r["date"] for r in rows])
    return out


def baseline_fwd(allp: dict, taiex: dict, tdates: list, horizons: list) -> dict:
    """全市場隨機股票日的平均前向超額(vs大盤) per H。"""
    import random
    rng = random.Random(7)
    res = {h: [] for h in horizons}
    codes = list(allp.keys())
    for _ in range(8000):
        c = rng.choice(codes)
        rows = allp[c]["rows"]
        if len(rows) < 25:
            continue
        i = rng.randrange(0, len(rows) - max(horizons) - 1)
        d0 = rows[i]["date"]; c0 = rows[i]["close"]
        if c0 <= 0 or d0 not in taiex:
            continue
        ti = tdates.index(d0) if d0 in tdates else None
        if ti is None:
            continue
        for h in horizons:
            if i + h < len(rows) and ti + h < len(tdates):
                sr = (rows[i + h]["close"] / c0 - 1) * 100
                tr = (taiex[tdates[ti + h]] / taiex[d0] - 1) * 100
                res[h].append(sr - tr)
    return {h: (statistics.mean(v) if v else 0.0) for h, v in res.items()}


def run(entry="signal", horizons=(5, 10, 20)):
    token = sim._token()
    ev = load_events()
    codes = {c for _, c in ev}
    closes = fetch_closes(codes, token)
    # TAIEX
    tx_rows = sim.fetch_daily("TAIEX", "2026-03-01", token)
    taiex = {r["date"]: r["close"] for r in tx_rows}
    tdates = [r["date"] for r in tx_rows]
    # baseline universe
    allp = json.load(open(PRICE_ALL))["stocks"]
    base = baseline_fwd(allp, taiex, tdates, list(horizons))

    res = {h: {"exc": [], "abs": [], "dates": []} for h in horizons}
    last_seen = {}   # episode 去重: 同股 H 日內只算一次
    used = 0
    for date, code in sorted(ev):
        if code not in closes:
            continue
        c2c, cdates = closes[code]
        if date not in cdates:
            continue
        ei = cdates.index(date)
        if entry == "next":
            ei += 1            # 隔天進場
        if ei >= len(cdates):
            continue
        edate = cdates[ei]
        # 去重
        prev = last_seen.get(code)
        if prev is not None and (ei - prev) <= max(horizons):
            continue
        last_seen[code] = ei
        if edate not in taiex:
            continue
        ti = tdates.index(edate) if edate in tdates else None
        if ti is None:
            continue
        used += 1
        for h in horizons:
            if ei + h < len(cdates) and ti + h < len(tdates):
                sr = (c2c[cdates[ei + h]] / c2c[edate] - 1) * 100
                tr = (taiex[tdates[ti + h]] / taiex[edate] - 1) * 100
                res[h]["abs"].append(sr)
                res[h]["exc"].append(sr - tr)
                res[h]["dates"].append(edate)
    out = {"n_events_raw": len(ev), "n_episodes": used, "entry": entry,
           "horizons": {}}
    for h in horizons:
        R = res[h]
        if not R["exc"]:
            continue
        exc = statistics.mean(R["exc"])
        out["horizons"][h] = {
            "n": len(R["exc"]),
            "abs_mean": round(statistics.mean(R["abs"]), 2),
            "exc_mean": round(exc, 2), "exc_med": round(statistics.median(R["exc"]), 2),
            "win": round(sum(1 for x in R["abs"] if x > 0) / len(R["abs"]) * 100, 0),
            "beat": round(sum(1 for x in R["exc"] if x > 0) / len(R["exc"]) * 100, 0),
            "baseline": round(base[h], 2),
            "edge": round(exc - base[h], 2),
        }
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", default="signal", choices=["signal", "next"])
    ap.add_argument("--json-out")
    args = ap.parse_args()
    r = run(args.entry)
    print(f"\n主力雷達 事件研究  進場={args.entry}  "
          f"原始事件 {r['n_events_raw']} → 去重 {r['n_episodes']}")
    for h, v in r["horizons"].items():
        print(f"\n【持有 {h} 日】 樣本 {v['n']}")
        print(f"  絕對報酬 {v['abs_mean']:+.2f}% (賺錢率 {v['win']:.0f}%)")
        print(f"  超額vs大盤 {v['exc_mean']:+.2f}% (中位 {v['exc_med']:+.2f}%, 贏大盤率 {v['beat']:.0f}%)")
        print(f"  基準 {v['baseline']:+.2f}% → ⭐edge {v['edge']:+.2f}%")
    if args.json_out:
        from datetime import datetime
        r_next = run("next") if args.entry == "signal" else run("signal")
        json.dump({"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "result": r if args.entry == "signal" else r_next,
                   "result_next": r if args.entry == "next" else r_next},
                  open(args.json_out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"\n[json] 寫入 {args.json_out}", file=sys.stderr)
