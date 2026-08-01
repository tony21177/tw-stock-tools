#!/usr/bin/env python3
"""
外資成本線 110-140% 策略回測 (tw_foreign_cost_backtest)

檢驗:「現價/外資成本 ∈ [110%,140%]」的股票之後是否表現較好?
方法(walk-forward、point-in-time):
  每 5 交易日取樣一次(自第 100 日起,留 60 日前瞻窗)。取樣日 t 的
  成本線只用 day0..t 的資料算(種子=day0 收盤);持股 H_t 由今日官方
  持股以 t 之後的買賣超往回反推(全程單一資料源)。
  過濾(與 live 工具同):持股/發行 ≥5%、現價 ≥10、收斂度(累積買進/H_t) ≥0.3。
  依 現價/成本% 分五桶:<100(外資被套)/100-110/110-140(策略區)/140-180/>180(過熱)
  前瞻 H5/H20/H60 絕對與超額(減加權)報酬,桶間互比。
⚠ 取樣重疊(每5日)+單一年度 regime;持股反推忽略盤後鉅額/增減資,誤差已由
  反推負持股剔除機制部分吸收。
用法:FINMIND_TOKEN=xxx python3 tw_foreign_cost_backtest.py [--json-out F]
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
import tw_extremes as ex                     # noqa: E402
from tw_foreign_cost import (_is_common, _holdings, INST_DIR,   # noqa: E402
                             MIN_HOLD_PCT, MIN_PRICE, MIN_CONV)

CACHE = os.path.join(HERE, "concept_momentum", "cache")
BUCKETS = [("<100", 0, 100), ("100-110", 100, 110), ("110-140", 110, 140),
           ("140-180", 140, 180), (">180", 180, 10**9)]
HORIZONS = [5, 20, 60]
SAMPLE_EVERY = 5
WARMUP = 100


def _stats(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if not n:
        return {"n": 0}
    mean = sum(vals) / n
    med = sorted(vals)[n // 2]
    win = sum(1 for v in vals if v > 0) / n * 100
    return {"n": n, "mean": round(mean, 2), "med": round(med, 2),
            "win": round(win, 1)}


def run(token: str) -> dict:
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    hold = _holdings(token)
    dks, net, close = [], {}, {}
    for d in dates:
        dk = d.replace("-", "")
        ip = os.path.join(INST_DIR, f"{dk}.json")
        if not os.path.exists(ip):
            continue
        try:
            idd = json.load(open(ip, encoding="utf-8"))
        except Exception:
            continue
        pdd = ex._day_prices(d, token)
        if not pdd:
            continue
        dks.append(dk)
        for c, (b, s_) in idd.items():
            net.setdefault(c, {})[dk] = (b - s_, b)
        for c, v in pdd.items():
            if _is_common(c):
                close.setdefault(c, {})[dk] = v[2]
    trows = ex._fm("TaiwanStockPrice",
                   {"data_id": "TAIEX", "start_date": dates[0]}, token)
    taiex = {r["date"].replace("-", ""): r["close"] for r in trows if r.get("close")}
    n_days = len(dks)
    samples = list(range(WARMUP, n_days - max(HORIZONS) - 1, SAMPLE_EVERY))

    res = {b[0]: {h: {"abs": [], "exc": []} for h in HORIZONS} for b in BUCKETS}
    counts = {b[0]: 0 for b in BUCKETS}
    for c, hv in hold.items():
        h_end, issued = hv
        if h_end <= 0 or issued <= 0:
            continue
        cs = close.get(c)
        nn = net.get(c, {})
        if not cs:
            continue
        # 持股反推
        H = [0.0] * n_days
        H[-1] = float(h_end)
        ok = True
        for i in range(n_days - 1, 0, -1):
            H[i - 1] = H[i] - nn.get(dks[i], (0, 0))[0]
            if H[i - 1] < 0:
                ok = False
                break
        if not ok:
            continue
        # 前向:遞迴成本 + 累積買進,取樣
        cost = None
        gross = 0.0
        si = 0
        sample_set = set(samples)
        for i, dk in enumerate(dks):
            p = cs.get(dk)
            nb, gb = nn.get(dk, (0.0, 0.0))
            gross += gb
            if p is not None and H[i] > 0:
                if cost is None:
                    cost = p
                elif nb > 0:
                    held = max(H[i] - nb, 0.0)
                    cost = (cost * held + p * nb) / (held + nb)
            if i not in sample_set:
                continue
            if (p is None or cost is None or cost <= 0 or H[i] <= 0
                    or p < MIN_PRICE
                    or H[i] / issued * 100 < MIN_HOLD_PCT
                    or gross / H[i] < MIN_CONV):
                continue
            ratio = p / cost * 100
            t0 = taiex.get(dk)
            for bname, lo, hi in BUCKETS:
                if lo <= ratio < hi:
                    counts[bname] += 1
                    for h in HORIZONS:
                        p1 = cs.get(dks[i + h])
                        t1 = taiex.get(dks[i + h])
                        if p1 and t0 and t1:
                            r = (p1 / p - 1) * 100
                            res[bname][h]["abs"].append(r)
                            res[bname][h]["exc"].append(r - (t1 / t0 - 1) * 100)
                    break
    out = {"window": f"{dks[0]}~{dks[-1]}", "n_days": n_days,
           "n_samples_dates": len(samples), "buckets": {}}
    for bname, _, _ in BUCKETS:
        out["buckets"][bname] = {
            "n": counts[bname],
            **{f"H{h}": {"abs": _stats(res[bname][h]["abs"]),
                         "exc": _stats(res[bname][h]["exc"])} for h in HORIZONS}}
    return out


def fmt(o: dict) -> str:
    L = [f"外資成本線 桶別回測  {o['window']}({o['n_days']} 交易日,"
         f"{o['n_samples_dates']} 個取樣日,每 {SAMPLE_EVERY} 日取樣)",
         f"過濾:持股≥{MIN_HOLD_PCT:.0f}%、現價≥{MIN_PRICE:.0f}、收斂≥{MIN_CONV:.0%}(與 live 同)",
         "", "現價/外資成本 桶別 → 後續超額報酬(減加權):", ""]
    for bname, _, _ in BUCKETS:
        b = o["buckets"][bname]
        tag = " ★策略區" if bname == "110-140" else ""
        L.append(f"═ {bname:8}(樣本 {b['n']:5}){tag}")
        for h in HORIZONS:
            s = b[f"H{h}"]
            a, e = s["abs"], s["exc"]
            if not a.get("n"):
                continue
            L.append(f"   H{h:<3}: 絕對 勝率{a['win']:5.1f}% 均{a['mean']:+6.2f}%"
                     f" | 超額 均{e['mean']:+6.2f}% 中位{e['med']:+6.2f}%")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("需要 FINMIND_TOKEN"); sys.exit(1)
    o = run(token)
    print(fmt(o))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False)
        print(f"寫入 {args.json_out}")


if __name__ == "__main__":
    main()
