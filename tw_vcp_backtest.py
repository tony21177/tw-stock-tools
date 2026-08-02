#!/usr/bin/env python3
"""
VCP 突破回測 (tw_vcp_backtest) — walk-forward, point-in-time

檢驗:VCP 突破 pivot(帶量)後的報酬,是否優於「僅通過趨勢模板」的股票?
(關鍵對照:VCP 在動能/趨勢過濾之上,還有沒有增量 edge —— 林則行箱型
 的教訓是型態本身可能無效,必須跟 regime-matched 對照比。)

方法:
  逐日 t(需 ≥200 日收盤 + ≥50 日量 + 130 日基底,前瞻 60 日):
    1. 趨勢模板@t:價>MA50>MA150>MA200、MA200 走揚、距一年高<25%、
       距一年低>+30%、年RS@t ≥70(全市場當日百分位)
    2. VCP@t(tw_vcp_screen._detect_vcp,只用 ≤t 資料)
    3. 突破事件:收盤_t > pivot(t-15..t-1 高)且 vol_t ≥ 1.5×vol50_t
       → 進場 = t 收盤(另報 t+1 收盤進場的 H20 檢查執行敏感度)
    同檔冷卻 20 交易日。
  報酬:H5/10/20/60 絕對 + 超額(減加權);突破失敗率 = 10 日內收盤跌回 pivot 下。
  對照組:(a) 全部股票日 (b) 通過趨勢模板+RS 但當日非 VCP 突破(每 5 日抽樣)。
資料:year_prices / vol_day(已回補至 2024-07,約 500 交易日)。
用法:FINMIND_TOKEN=xxx python3 tw_vcp_backtest.py [--json-out F]
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
import tw_extremes as ex                      # noqa: E402
from tw_vcp_screen import (_detect_vcp, RS_MIN, BRK_VOL)   # noqa: E402
import tw_utility_screen as us                # noqa: E402

CACHE = os.path.join(HERE, "concept_momentum", "cache")
HORIZONS = [5, 10, 20, 60]
COOLDOWN = 20
FAIL_WIN = 10          # 突破失敗:N 日內收盤跌回 pivot 之下
MIN_VOL50 = 100        # 50日均量 ≥100 張(排殭屍股/停牌補值假象)
BASE_SAMPLE = 5        # 對照組抽樣頻率(日)


def _load_calendar(token):
    rows = ex._fm("TaiwanStockPrice", {"data_id": "2330",
                                       "start_date": "2024-07-01"}, token)
    return sorted({r["date"] for r in rows if r.get("close")})


def load_panel(token):
    """全市場對齊面板:dates, H/L/C/V dict[code]->list(缺日 carry-forward,vol=0)"""
    dates = _load_calendar(token)
    H, L, C, V = {}, {}, {}, {}
    for di, d in enumerate(dates):
        dk = d.replace("-", "")
        pp = os.path.join(CACHE, "year_prices", f"{dk}.json")
        vp = os.path.join(CACHE, "vol_day", f"{dk}.json")
        if not os.path.exists(pp):
            continue
        try:
            pd_ = json.load(open(pp, encoding="utf-8"))
            vd = json.load(open(vp, encoding="utf-8")) if os.path.exists(vp) else {}
        except Exception:
            continue
        for c, v in pd_.items():
            if not (len(c) == 4 and c.isdigit() and not c.startswith("00")):
                continue
            if c not in C:
                H[c] = [None] * di
                L[c] = [None] * di
                C[c] = [None] * di
                V[c] = [0.0] * di
            H[c].append(v[0]); L[c].append(v[1]); C[c].append(v[2])
            V[c].append(float(vd.get(c, 0)))
        # 補齊本日缺席股票(carry-forward)
        for c in C:
            if len(C[c]) <= di:
                pc = C[c][-1] if C[c] and C[c][-1] is not None else None
                H[c].append(pc); L[c].append(pc); C[c].append(pc); V[c].append(0.0)
    # TAIEX
    trows = ex._fm("TaiwanStockPrice", {"data_id": "TAIEX",
                                        "start_date": "2024-07-01"}, token)
    tx = {r["date"]: r["close"] for r in trows if r.get("close")}
    taiex = [tx.get(d) for d in dates]
    return dates, H, L, C, V, taiex


def _stats(vals):
    vals = [v for v in vals if v is not None]
    n = len(vals)
    if not n:
        return {"n": 0}
    mean = sum(vals) / n
    med = sorted(vals)[n // 2]
    win = sum(1 for v in vals if v > 0) / n * 100
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / n) if n > 1 else 0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0
    return {"n": n, "mean": round(mean, 2), "med": round(med, 2),
            "win": round(win, 1), "t": round(t, 2)}


def run(token):
    dates, H, L, C, V, taiex = load_panel(token)
    n_dates = len(dates)
    print(f"面板 {dates[0]}~{dates[-1]} {n_dates} 日 {len(C)} 檔", file=sys.stderr)
    t_start = 210
    t_end = n_dates - max(HORIZONS) - 1
    # 預計算年RS原始分矩陣(逐日)→ 當日百分位
    # score@t 需 closes[:t+1];為省時逐 t 現算(O(1)/檔)
    codes = [c for c in C if len(C[c]) == n_dates]
    events = []
    base_all = {h: {"abs": [], "exc": []} for h in HORIZONS}
    base_tmpl = {h: {"abs": [], "exc": []} for h in HORIZONS}
    last_ev = {}
    prefix_v = {}          # 滾動 vol50 以 prefix sum 加速
    for c in codes:
        pv = [0.0]
        for x in V[c]:
            pv.append(pv[-1] + x)
        prefix_v[c] = pv

    for t in range(t_start, t_end):
        # 當日全市場年RS分數 → 百分位
        scores = {}
        for c in codes:
            cs = C[c]
            if cs[t] is None or cs[t - 200] is None:
                continue
            s = us._rs_score([x for x in cs[:t + 1] if x is not None][-251:], 250)
            if s is not None:
                scores[c] = s
        if len(scores) < 300:
            continue
        ranked = sorted(scores, key=lambda x: scores[x])
        pct = {c: (i + 1) / len(ranked) * 99 for i, c in enumerate(ranked)}
        t0 = taiex[t]
        for c, rs in pct.items():
            cs, hs, ls, vs = C[c], H[c], L[c], V[c]
            cur = cs[t]
            if cur is None or rs < RS_MIN:
                continue
            vol50 = (prefix_v[c][t + 1] - prefix_v[c][t + 1 - 50]) / 50
            if vol50 < MIN_VOL50:
                continue
            # 趨勢模板(只用 ≤t)
            w50 = [x for x in cs[t - 49:t + 1] if x is not None]
            w150 = [x for x in cs[t - 149:t + 1] if x is not None]
            w200 = [x for x in cs[t - 199:t + 1] if x is not None]
            w200p = [x for x in cs[t - 219:t - 19] if x is not None]
            if len(w200) < 180:
                continue
            ma50 = sum(w50) / len(w50)
            ma150 = sum(w150) / len(w150)
            ma200 = sum(w200) / len(w200)
            ma200p = sum(w200p) / len(w200p)
            hi52 = max(x for x in hs[max(0, t - 249):t + 1] if x is not None)
            lo52 = min(x for x in ls[max(0, t - 249):t + 1] if x is not None)
            if not (cur > ma50 > ma150 > ma200 and ma200 > ma200p
                    and cur >= hi52 * 0.75 and cur >= lo52 * 1.30):
                continue
            # regime 對照組(通過模板+RS,每5日抽樣)
            if t % BASE_SAMPLE == 0 and t1_ok(t, n_dates):
                _acc(base_tmpl, cs, taiex, t, t0)
            # VCP + 突破
            if t - last_ev.get(c, -10**9) < COOLDOWN:
                continue
            hseg = [x for x in hs[:t + 1] if x is not None]
            lseg = [x for x in ls[:t + 1] if x is not None]
            det = _detect_vcp(hseg, lseg, None)
            if not det:
                continue
            pivot_prev = max(x for x in hs[t - 15:t] if x is not None)
            if cur > pivot_prev and vs[t] >= vol50 * BRK_VOL:
                last_ev[c] = t
                ev = {"code": c, "date": dates[t], "rs": round(rs, 1),
                      "depths": det["depths"], "vol_x": round(vs[t] / vol50, 1)}
                # 失敗:10 日內收盤跌回 pivot 下
                ev["failed"] = any(
                    cs[j] is not None and cs[j] < pivot_prev
                    for j in range(t + 1, min(t + 1 + FAIL_WIN, n_dates)))
                for h in HORIZONS:
                    p1, tx1 = cs[t + h], taiex[t + h]
                    if p1 and t0 and tx1:
                        r = (p1 / cur - 1) * 100
                        ev[f"h{h}"] = round(r, 2)
                        ev[f"e{h}"] = round(r - (tx1 / t0 - 1) * 100, 2)
                # t+1 收盤進場的 H20(執行敏感度)
                if cs[t + 1] and cs[t + 21]:
                    ev["h20_d1"] = round((cs[t + 21] / cs[t + 1] - 1) * 100, 2)
                events.append(ev)
        # 全市場對照
        if t % BASE_SAMPLE == 0:
            for c in codes[::7]:                      # 稀疏抽樣夠用
                cs = C[c]
                if cs[t] is None:
                    continue
                _acc(base_all, cs, taiex, t, t0)

    out = {"window": f"{dates[t_start]}~{dates[t_end]}",
           "n_events": len(events),
           "fail_rate": (round(sum(1 for e in events if e["failed"])
                               / len(events) * 100, 1) if events else None),
           "H": {}, "base_all": {}, "base_tmpl": {}}
    for h in HORIZONS:
        out["H"][h] = {"abs": _stats([e.get(f"h{h}") for e in events]),
                       "exc": _stats([e.get(f"e{h}") for e in events])}
        out["base_all"][h] = {"abs": _stats(base_all[h]["abs"]),
                              "exc": _stats(base_all[h]["exc"])}
        out["base_tmpl"][h] = {"abs": _stats(base_tmpl[h]["abs"]),
                               "exc": _stats(base_tmpl[h]["exc"])}
    out["h20_d1"] = _stats([e.get("h20_d1") for e in events])
    out["events"] = events
    return out


def t1_ok(t, n):
    return t + max(HORIZONS) < n


def _acc(bucket, cs, taiex, t, t0):
    for h in HORIZONS:
        p1, tx1 = cs[t + h], taiex[t + h]
        if cs[t] and p1 and t0 and tx1:
            r = (p1 / cs[t] - 1) * 100
            bucket[h]["abs"].append(r)
            bucket[h]["exc"].append(r - (tx1 / t0 - 1) * 100)


def fmt(o):
    L = [f"VCP 突破回測  {o['window']}",
         f"事件 {o['n_events']} 次;突破失敗率(10日內收回 pivot 下):{o['fail_rate']}%",
         ""]
    for h in HORIZONS:
        e = o["H"][h]["exc"]
        a = o["H"][h]["abs"]
        bt = o["base_tmpl"][h]["exc"]
        ba = o["base_all"][h]["exc"]
        if not a.get("n"):
            continue
        L.append(f"H{h:<3}: 絕對 勝率{a['win']:5.1f}% 均{a['mean']:+6.2f}% | "
                 f"超額 均{e['mean']:+6.2f}% 中位{e['med']:+6.2f}% t={e['t']:+.1f} | "
                 f"模板對照 {bt['mean']:+.2f}% | 全市場 {ba['mean']:+.2f}%")
    d1 = o["h20_d1"]
    if d1.get("n"):
        L.append(f"執行敏感度:t+1 收盤進場 H20 均 {d1['mean']:+.2f}%(vs 當日收盤進場)")
    L.append("")
    L.append("近 10 筆事件:")
    for e in o["events"][-10:]:
        L.append(f"  {e['date']} {e['code']} RS{e['rs']:.0f} "
                 f"收縮{'→'.join(str(x)+'%' for x in e['depths'])} 量{e['vol_x']}x "
                 f"{'✗破' if e['failed'] else '✓'} H20={e.get('h20')}")
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
        slim = {k: v for k, v in o.items() if k != "events"}
        slim["events_tail"] = o["events"][-20:]
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False)
        print(f"寫入 {args.json_out}")


if __name__ == "__main__":
    main()
