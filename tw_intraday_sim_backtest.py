#!/usr/bin/env python3
"""盤中走勢模擬 — 收盤層級校準回測 (walk-forward, 市場技術池)。

驗證核心問題：「技術型態相似的歷史日，能不能預測隔天開盤→收盤的方向/幅度？」
只看收盤結果(隔天日線 vs 前收)，不抓分鐘 K → 大樣本、零新抓取(全用快取)。

走前測 (walk-forward)：對每個測試 (股票,日 t)，相似日只能取 <t 的過去日，
量它隔天實際收盤報酬，跟相似日「隔天收盤報酬」的預測分布比。

指標：
  方向命中率   — 預測中位數方向 vs 實際；對照「總是猜漲」base rate
  信心帶校準   — 實際落在 25-75% 帶(目標50%)、10-90%帶(目標80%)的比例
  技巧 skill   — 相似日中位數的 MAE，vs「猜0%」「猜無條件均值」的 MAE
                 (有降誤差才代表相似日帶資訊)
  分位校準曲線 — 預測中位數分十組，看實際平均是否單調遞增

用法：
  tw_intraday_sim_backtest.py                       # 預設抽 800 點
  tw_intraday_sim_backtest.py --n 1500 --k 40 --json-out out.json
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
MKT_MATRIX = os.path.join(CACHE, "intraday_mkt_matrix.json")
PRICE_ALL = os.path.join(CACHE, "backtest_prices_all.json")


def load():
    with open(MKT_MATRIX) as f:
        mat = json.load(f)
    with open(PRICE_ALL) as f:
        allp = json.load(f)["stocks"]
    return mat, allp


def build_arrays(mat, allp):
    """回 Z(N,6) float32, codes, dates(int), nxt_ret(N) %、有效遮罩。"""
    rows = mat["rows"]
    n = len(rows)
    Z = np.empty((n, 6), dtype=np.float32)
    dates = np.empty(n, dtype=np.int64)
    codes = []
    # 每股 date→close 與 next-close
    nxt = np.full(n, np.nan, dtype=np.float32)
    close_by = {}
    for code, s in allp.items():
        d2c = {r["date"]: r["close"] for r in s["rows"]}
        ds = [r["date"] for r in s["rows"]]
        nextret = {}
        for i in range(len(ds) - 1):
            c0 = d2c[ds[i]]
            if c0 > 0:
                nextret[ds[i]] = (d2c[ds[i + 1]] / c0 - 1) * 100
        close_by[code] = nextret
    for j, r in enumerate(rows):
        codes.append(r[0])
        dates[j] = int(r[1])
        Z[j] = r[2:8]
        nr = close_by.get(r[0], {}).get(r[1])
        if nr is not None:
            nxt[j] = nr
    return Z, np.array(codes), dates, nxt


def run(n_test=800, k=40, cutoff=20260101, seed=42):
    mat, allp = load()
    Z, codes, dates, nxt = build_arrays(mat, allp)
    valid = ~np.isnan(nxt)
    uncond_mean = float(np.nanmean(nxt[valid]))
    # 測試池：date>=cutoff 且有隔天結果
    test_idx = np.where(valid & (dates >= cutoff))[0]
    rng = random.Random(seed)
    if len(test_idx) > n_test:
        test_idx = np.array(rng.sample(list(test_idx), n_test))
    print(f"矩陣 {len(dates):,} 列；測試點 {len(test_idx)} (date>={cutoff})", file=sys.stderr)

    recs = []   # (pred_median, actual, in2575, in1090, dir_hit, ae_a, ae_0, ae_u, p10,p25,p75,p90)
    for cnt, ti in enumerate(test_idx):
        td = dates[ti]; tc = codes[ti]
        tz = Z[ti]
        # 候選：過去日 (date<td) + 有隔天結果 + 排除同股±3日
        cand = valid & (dates < td)
        # 排除同股鄰近(避免重疊/同型態洩漏)
        same = (codes == tc) & (np.abs(dates - td) <= 5)
        cand &= ~same
        ci = np.where(cand)[0]
        if len(ci) < k * 2:
            continue
        d = np.sum((Z[ci] - tz) ** 2, axis=1)
        nn = ci[np.argpartition(d, k)[:k]]
        outs = nxt[nn]
        med = float(np.median(outs))
        p10, p25, p75, p90 = [float(np.percentile(outs, q)) for q in (10, 25, 75, 90)]
        act = float(nxt[ti])
        recs.append((med, act,
                     1 if p25 <= act <= p75 else 0,
                     1 if p10 <= act <= p90 else 0,
                     1 if (med > 0) == (act > 0) else 0,
                     abs(act - med), abs(act), abs(act - uncond_mean)))
        if (cnt + 1) % 200 == 0:
            print(f"  {cnt+1}/{len(test_idx)}", file=sys.stderr)

    if not recs:
        return {"error": "無有效測試點"}
    return _summarize(recs, uncond_mean, k, cutoff, "市場技術池")


def _summarize(recs, uncond_mean, k, cutoff, pool_label):
    A = np.array(recs, dtype=np.float64)
    med, act = A[:, 0], A[:, 1]
    base_up = float(np.mean(act > 0)) * 100
    dir_hit = float(np.mean(A[:, 4])) * 100
    conf = np.abs(med) > np.median(np.abs(med))
    dir_hit_conf = float(np.mean(A[conf, 4])) * 100 if conf.any() else None
    in2575 = float(np.mean(A[:, 2])) * 100
    in1090 = float(np.mean(A[:, 3])) * 100
    mae_a = float(np.mean(A[:, 5])); mae_0 = float(np.mean(A[:, 6])); mae_u = float(np.mean(A[:, 7]))
    order = np.argsort(med)
    nb = 8
    curve = []
    for b in range(nb):
        seg = order[b * len(order) // nb:(b + 1) * len(order) // nb]
        if len(seg):
            curve.append({"pred": round(float(np.mean(med[seg])), 3),
                          "actual": round(float(np.mean(act[seg])), 3), "n": len(seg)})
    return {
        "pool": pool_label, "n": len(recs), "k": k, "cutoff": cutoff,
        "uncond_mean": round(uncond_mean, 3),
        "base_up_pct": round(base_up, 1), "dir_hit_pct": round(dir_hit, 1),
        "dir_hit_conf_pct": round(dir_hit_conf, 1) if dir_hit_conf else None,
        "cover_2575_pct": round(in2575, 1), "cover_1090_pct": round(in1090, 1),
        "mae_analog": round(mae_a, 3), "mae_zero": round(mae_0, 3), "mae_uncond": round(mae_u, 3),
        "skill_vs_zero": round((mae_0 - mae_a) / mae_0 * 100, 1),
        "calib_curve": curve,
    }


# ── 個股自己池回測 (完整 14 特徵, 含籌碼) ──────────────
def run_self(k=40, cutoff=20260101, max_stocks=160, per_stock=40,
             start="2024-06-01", seed=42):
    """對概念股 universe，每檔用自己歷史(含借券/融資/法人)做 walk-forward。"""
    sys.path.insert(0, HERE)
    import tw_intraday_sim as sim
    cpath = os.path.join(CACHE, "concepts.json")
    themes = json.load(open(cpath))["themes"]
    codes = sorted({c for v in themes.values() for c in v.get("stocks", [])})
    rng = random.Random(seed)
    if len(codes) > max_stocks:
        codes = rng.sample(codes, max_stocks)
    tok = sim._token()
    recs = []
    all_act = []
    done = 0
    for ci, code in enumerate(codes):
        try:
            rows = sim.fetch_daily(code, start, tok)
            if len(rows) < 150:
                continue
            chip = sim.build_chip_history(code, start, tok)
            mat = sim.build_matrix(rows, chip)           # [{i,date,feat}]
            if len(mat) < k * 3:
                continue
            st = sim._stats(mat)
            Z = np.array([sim._zvec(m["feat"], st) for m in mat], dtype=np.float32)
            idates = np.array([int(m["date"]) for m in mat])
            irow = np.array([m["i"] for m in mat])
            closes = np.array([r["close"] for r in rows])
            # 測試點：date>=cutoff 且 隔天存在
            tcand = [p for p in range(len(mat))
                     if idates[p] >= cutoff and irow[p] + 1 < len(rows)]
            if len(tcand) > per_stock:
                tcand = rng.sample(tcand, per_stock)
            for p in tcand:
                td = idates[p]
                cmask = (idates < td) & (np.abs(irow - irow[p]) > 3)
                cand = np.where(cmask)[0]
                if len(cand) < k * 2:
                    continue
                d = np.sum((Z[cand] - Z[p]) ** 2, axis=1)
                nn = cand[np.argpartition(d, k)[:k]]
                outs = []
                for a in nn:
                    ia = irow[a]
                    if ia + 1 < len(rows) and closes[ia] > 0:
                        outs.append((closes[ia + 1] / closes[ia] - 1) * 100)
                if len(outs) < k // 2:
                    continue
                outs = np.array(outs)
                med = float(np.median(outs))
                p10, p25, p75, p90 = [float(np.percentile(outs, q)) for q in (10, 25, 75, 90)]
                ip = irow[p]
                act = (closes[ip + 1] / closes[ip] - 1) * 100
                all_act.append(act)
                recs.append((med, act, 1 if p25 <= act <= p75 else 0,
                             1 if p10 <= act <= p90 else 0,
                             1 if (med > 0) == (act > 0) else 0,
                             abs(act - med), abs(act), 0.0))
            done += 1
        except Exception as e:
            print(f"  跳過 {code}: {e}", file=sys.stderr)
        if (ci + 1) % 20 == 0:
            print(f"  {ci+1}/{len(codes)} 檔 (有效 {done}, 樣本 {len(recs)})", file=sys.stderr)
        time.sleep(0.05)
    if not recs:
        return {"error": "無有效測試點"}
    um = float(np.mean(all_act))
    # 補 ae_uncond
    recs = [(m, a, i1, i2, dh, aea, ae0, abs(a - um)) for (m, a, i1, i2, dh, aea, ae0, _z) in recs]
    return _summarize(recs, um, k, cutoff, f"個股自己池(含籌碼, {done}檔)")


def _print(r):
    print(f"\n【{r['pool']}】 測試 {r['n']} 點")
    print(f"  base rate(實際上漲) : {r['base_up_pct']}%  | 方向命中率 {r['dir_hit_pct']}% (信心子集 {r['dir_hit_conf_pct']}%)")
    print(f"  信心帶 25-75% {r['cover_2575_pct']}% (目標50) / 10-90% {r['cover_1090_pct']}% (目標80)")
    print(f"  MAE 相似日 {r['mae_analog']} vs 猜0% {r['mae_zero']} → skill {r['skill_vs_zero']}%")
    for c in r["calib_curve"]:
        print(f"    pred {c['pred']:+.2f}% → actual {c['actual']:+.2f}% (n={c['n']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="both", choices=["market", "self", "both"])
    ap.add_argument("--n", type=int, default=800)
    ap.add_argument("--k", type=int, default=40)
    ap.add_argument("--cutoff", type=int, default=20260101)
    ap.add_argument("--max-stocks", type=int, default=160)
    ap.add_argument("--json-out")
    args = ap.parse_args()
    out = {"generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}
    if args.pool in ("market", "both"):
        rm = run(args.n, args.k, args.cutoff)
        if not rm.get("error"):
            out["result"] = rm; _print(rm)
    if args.pool in ("self", "both"):
        rs = run_self(args.k, args.cutoff, max_stocks=args.max_stocks)
        if not rs.get("error"):
            out["result_self"] = rs; _print(rs)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        print(f"[json] 寫入 {args.json_out}", file=sys.stderr)
