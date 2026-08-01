#!/usr/bin/env python3
"""
借券賣出大增/回補 事件研究 (tw_sbl_surge_study)

問題(用戶 2026-08-01):上市櫃股票「借券賣出餘額大增」後股價怎麼走?
大量賣出後「陸續回補」又怎麼走?

事件定義(全市場 4 位數普通股,近一年逐日借券賣出餘額):
  A 大增:10 交易日內餘額增 ≥ +50% 且 增量 ≥ 1,000 張 且 10日前餘額 ≥ 500 張
         (有規模的突然放空,排除低基期噪音)
  B 回補:近 60 日餘額峰值 ≥ 3,000 張,餘額首次跌破峰值的 70%(=回補 30%+)
  同一檔冷卻 40 交易日(避免重疊視窗重複計數)。

報酬:事件日還原收盤起算 H5/H10/H20/H60 絕對報酬 + 超額(減同期加權指數)。
資料:FinMind TaiwanDailyShortSaleBalances(逐日全市場,重用 tw_margin_scan._sbl_day
  快取 cache/sbl_day/)+ 還原收盤(重用 tw_extremes year_prices 快取)。
⚠ 借券賣出≠融券;回補=還券(可能是召回/自主,動機不唯一)。觀察統計、非訊號。

用法:
  FINMIND_TOKEN=xxx python3 tw_sbl_surge_study.py --backfill   # 補逐日快取
  FINMIND_TOKEN=xxx python3 tw_sbl_surge_study.py              # 跑研究
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
import tw_extremes as ex                     # noqa: E402
import tw_margin_scan as ms                  # noqa: E402

CACHE = os.path.join(HERE, "concept_momentum", "cache")
SBL_DIR = os.path.join(CACHE, "sbl_day")

# 事件參數
SURGE_WIN = 10        # A:回看視窗(交易日)
SURGE_PCT = 0.50      # A:餘額增幅門檻(+50%)
SURGE_MIN_ADD = 1000  # A:增量張數門檻
SURGE_MIN_BASE = 500  # A:基期餘額下限(排除低基期)
COVER_PEAK_WIN = 60   # B:峰值回看視窗
COVER_PEAK_MIN = 3000 # B:峰值餘額下限(張)
COVER_DROP = 0.30     # B:自峰值回補比例門檻
COOLDOWN = 40         # 同檔事件冷卻(交易日)
HORIZONS = [5, 10, 20, 60]


def backfill(token: str) -> int:
    dates = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    done = 0
    for i, d in enumerate(dates):
        p = os.path.join(SBL_DIR, f"{d.replace('-', '')}.json")
        if os.path.exists(p):
            continue
        if ms._sbl_day(d, token):
            done += 1
        if done and done % 40 == 0:
            print(f"  sbl backfill {d} ({done} new, {i+1}/{len(dates)})", flush=True)
        time.sleep(0.3)
    return done


def _is_common(c: str) -> bool:
    return len(c) == 4 and c.isdigit() and not c.startswith("00")


def load_series(token: str):
    """回傳 dates(YYYYMMDD 升冪), bal{code:{dk:張}}, close{code:{dk:還原收}}, taiex{dk:close}"""
    dates_iso = ex._trading_dates(datetime.now().strftime("%Y-%m-%d"), token)
    dks = []
    bal: dict = {}
    close: dict = {}
    for d in dates_iso:
        dk = d.replace("-", "")
        sp = os.path.join(SBL_DIR, f"{dk}.json")
        if not os.path.exists(sp):
            continue
        try:
            with open(sp, encoding="utf-8") as f:
                sd = json.load(f)
        except Exception:
            continue
        pd_ = ex._day_prices(d, token)
        if not pd_:
            continue
        dks.append(dk)
        for c, v in sd.items():
            if _is_common(c):
                bal.setdefault(c, {})[dk] = v[0]
        for c, v in pd_.items():
            if _is_common(c):
                close.setdefault(c, {})[dk] = v[2]
    # TAIEX
    rows = ex._fm("TaiwanStockPrice",
                  {"data_id": "TAIEX", "start_date": dates_iso[0]}, token)
    taiex = {r["date"].replace("-", ""): r["close"] for r in rows if r.get("close")}
    return dks, bal, close, taiex


def detect_events(dks, bal):
    """回傳 events = [{code, dk, i, kind:'surge'|'cover', b0, b1, peak}]"""
    idx = {d: i for i, d in enumerate(dks)}
    events = []
    for code, series in bal.items():
        sd = [series.get(d) for d in dks]
        last_ev = {"surge": -10**9, "cover": -10**9}
        peak = 0.0
        for i in range(len(dks)):
            b = sd[i]
            if b is None:
                continue
            # A 大增
            if i >= SURGE_WIN and sd[i - SURGE_WIN] is not None:
                b0 = sd[i - SURGE_WIN]
                if (b0 >= SURGE_MIN_BASE and b >= b0 * (1 + SURGE_PCT)
                        and b - b0 >= SURGE_MIN_ADD
                        and i - last_ev["surge"] >= COOLDOWN):
                    events.append({"code": code, "dk": dks[i], "i": i,
                                   "kind": "surge", "b0": b0, "b1": b})
                    last_ev["surge"] = i
            # B 回補:近 COVER_PEAK_WIN 峰值
            lo = max(0, i - COVER_PEAK_WIN)
            win = [x for x in sd[lo:i + 1] if x is not None]
            if not win:
                continue
            pk = max(win)
            prev_b = sd[i - 1] if i > 0 else None
            if (pk >= COVER_PEAK_MIN and b <= pk * (1 - COVER_DROP)
                    and prev_b is not None and prev_b > pk * (1 - COVER_DROP)
                    and i - last_ev["cover"] >= COOLDOWN):
                events.append({"code": code, "dk": dks[i], "i": i,
                               "kind": "cover", "b0": pk, "b1": b})
                last_ev["cover"] = i
    return events


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


def study(token: str) -> dict:
    dks, bal, close, taiex = load_series(token)
    print(f"資料 {dks[0]}~{dks[-1]} 共 {len(dks)} 交易日,"
          f"{len(bal)} 檔有借券餘額", file=sys.stderr)
    events = detect_events(dks, bal)
    out = {"window": f"{dks[0]}~{dks[-1]}", "n_days": len(dks), "params": {
        "surge": f"{SURGE_WIN}日增≥{SURGE_PCT:.0%} 且 +≥{SURGE_MIN_ADD}張 且 基期≥{SURGE_MIN_BASE}張",
        "cover": f"{COVER_PEAK_WIN}日峰值≥{COVER_PEAK_MIN}張 回補跨過 {COVER_DROP:.0%}",
    }}
    for kind in ("surge", "cover"):
        evs = [e for e in events if e["kind"] == kind]
        res = {"n_events": len(evs), "H": {}}
        # 事件前 20 日報酬(context:大增時股價通常已在跌?)
        pre = []
        for e in evs:
            c, i = e["code"], e["i"]
            if i >= 20:
                p0, p1 = close.get(c, {}).get(dks[i - 20]), close.get(c, {}).get(e["dk"])
                if p0 and p1:
                    pre.append((p1 / p0 - 1) * 100)
        res["pre20"] = _stats(pre)
        for h in HORIZONS:
            abs_r, exc_r = [], []
            for e in evs:
                c, i = e["code"], e["i"]
                if i + h >= len(dks):
                    continue
                p0 = close.get(c, {}).get(e["dk"])
                p1 = close.get(c, {}).get(dks[i + h])
                t0, t1 = taiex.get(e["dk"]), taiex.get(dks[i + h])
                if not (p0 and p1 and t0 and t1):
                    continue
                r = (p1 / p0 - 1) * 100
                abs_r.append(r)
                exc_r.append(r - (t1 / t0 - 1) * 100)
            res["H"][h] = {"abs": _stats(abs_r), "excess": _stats(exc_r)}
        out[kind] = res
    # 對照組:全部 stock-days 的 H 報酬(抽樣每 5 日以省時)
    base = {h: {"abs": [], "excess": []} for h in HORIZONS}
    for c, cs in close.items():
        for i in range(0, len(dks) - max(HORIZONS), 5):
            p0 = cs.get(dks[i])
            if not p0:
                continue
            for h in HORIZONS:
                p1 = cs.get(dks[i + h])
                t0, t1 = taiex.get(dks[i]), taiex.get(dks[i + h])
                if p1 and t0 and t1:
                    r = (p1 / p0 - 1) * 100
                    base[h]["abs"].append(r)
                    base[h]["excess"].append(r - (t1 / t0 - 1) * 100)
    out["baseline"] = {h: {"abs": _stats(base[h]["abs"]),
                           "excess": _stats(base[h]["excess"])} for h in HORIZONS}
    return out


def fmt_report(o: dict) -> str:
    L = [f"借券賣出 大增/回補 事件研究  {o['window']}({o['n_days']} 交易日)",
         f"  A 大增定義:{o['params']['surge']}",
         f"  B 回補定義:{o['params']['cover']}", ""]
    for kind, name in (("surge", "A 借券賣出大增"), ("cover", "B 大量後回補")):
        r = o[kind]
        L.append(f"═══ {name}(事件 {r['n_events']} 次)═══")
        p = r["pre20"]
        if p["n"]:
            L.append(f"  事件前20日股價: 平均{p['mean']:+.1f}% 中位{p['med']:+.1f}%(context)")
        for h in HORIZONS:
            s = r["H"][h]
            a, e = s["abs"], s["excess"]
            b = o["baseline"][h]
            if not a.get("n"):
                continue
            L.append(f"  H{h:<3}: 絕對 勝率{a['win']:5.1f}% 均{a['mean']:+6.2f}% 中位{a['med']:+6.2f}%"
                     f" | 超額 均{e['mean']:+6.2f}% 中位{e['med']:+6.2f}% t={e['t']:+.1f}"
                     f"  (對照超額均 {b['excess']['mean']:+.2f}%)")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("需要 FINMIND_TOKEN"); sys.exit(1)
    if args.backfill:
        n = backfill(token)
        print(f"sbl_day 新增 {n} 天")
        return
    o = study(token)
    print(fmt_report(o))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False)
        print(f"寫入 {args.json_out}")


if __name__ == "__main__":
    main()
