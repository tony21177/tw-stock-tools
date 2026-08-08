#!/usr/bin/env python3
"""
集保千張大戶跳增偵測 + 回測 —— 事件交易務實版旗艦。

理念:元太/台虹驗證顯示歷史分點(最強前兆)是 FinMind 付費層拿不到,
但集保大戶週報免費有歷史。大戶(千張,≥1000張=≥100萬股)持股比例週增 ≥N pp
= 主力/策略買家吸貨的可觀測痕跡。初步回測(120檔樣本,≥3pp):
  H5 超額 +1.6% / H10 +4.0% / H20 +7.4%,中位皆正 —— 有 edge。

資料:FinMind TaiwanStockHoldingSharesPer(週頻,免費有歷史)。
  級距 'more than 1,000,001' = 千張大戶。
快取:cache/bigholder/{code}.json = {date: 千張大戶%}(週更新)。
還原價面板:cache/year_prices(算 forward return / 現價)。

CLI:
  python3 tw_bigholder.py --backtest [--universe N]   # 回測
  python3 tw_bigholder.py --scan                       # 掃最近跳增(建快取)
"""

import argparse
import glob
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CM = os.path.join(HERE, "concept_momentum")
CACHE = os.path.join(CM, "cache", "bigholder")
RESULT = os.path.join(CM, "cache", "bigholder_backtest.json")
SCAN_OUT = os.path.join(CM, "cache", "bigholder_scan.json")
BIG_TIER = "more than 1,000,001"
JUMP_PP = 3.0        # 週增門檻(百分點)
HORIZONS = [5, 10, 20]


def _panel():
    files = sorted(glob.glob(os.path.join(CM, "cache", "year_prices", "*.json")))
    dates = [os.path.basename(f)[:8] for f in files]
    closes = {}
    for f in files:
        d = os.path.basename(f)[:8]
        for c, v in json.load(open(f)).items():
            if isinstance(v, list) and len(v) >= 3 and v[2]:
                closes.setdefault(c, {})[d] = v[2]
    return dates, closes, {d: i for i, d in enumerate(dates)}


def fetch_holder(code, token, start="2024-07-01", force=False) -> dict:
    """千張大戶% 週序列 {yyyymmdd: pct}。快取,force 重抓。"""
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, f"{code}.json")
    if os.path.exists(fp) and not force:
        return json.load(open(fp))
    q = urllib.parse.urlencode({"dataset": "TaiwanStockHoldingSharesPer",
                                "data_id": code, "start_date": start, "token": token})
    try:
        rows = json.loads(urllib.request.urlopen(
            f"https://api.finmindtrade.com/api/v4/data?{q}", timeout=25).read()).get("data", [])
    except Exception:
        return {}
    out = {r["date"].replace("-", ""): (r.get("percent") or 0)
           for r in rows if r["HoldingSharesLevel"] == BIG_TIER}
    json.dump(out, open(fp, "w"))
    return out


def _fwd(closes, didx, dates, code, d0, h):
    i = didx.get(d0)
    if i is None:
        cand = [x for x in dates if x >= d0]
        if not cand:
            return None
        i = didx[cand[0]]
    if i + h >= len(dates):
        return None
    c0 = closes.get(code, {}).get(dates[i])
    c1 = closes.get(code, {}).get(dates[i + h])
    if not c0 or not c1:
        return None
    return (c1 - c0) / c0 * 100


def detect_jumps(hist: dict, thresh=JUMP_PP):
    """回傳 [(date, 前值, 後值, 增幅pp)]。"""
    wks = sorted(hist)
    out = []
    for j in range(1, len(wks)):
        d = hist[wks[j]] - hist[wks[j - 1]]
        if d >= thresh:
            out.append((wks[j], hist[wks[j - 1]], hist[wks[j]], round(d, 2)))
    return out


def backtest(token, universe_n=250, thresh=JUMP_PP):
    dates, closes, didx = _panel()
    univ = [c for c in closes if len(c) == 4 and c.isdigit()
            and max(closes[c].values()) > 20]
    rnd = random.Random(42)
    sample = rnd.sample(univ, min(universe_n, len(univ)))
    ev = {h: [] for h in HORIZONS}
    base = {h: [] for h in HORIZONS}
    n_ev = 0
    for k, code in enumerate(sample):
        hist = fetch_holder(code, token)
        if not os.path.exists(os.path.join(CACHE, f"{code}.json")):
            time.sleep(0.3)
        for (d, _p0, _p1, _dp) in detect_jumps(hist, thresh):
            n_ev += 1
            for h in HORIZONS:
                r = _fwd(closes, didx, dates, code, d, h)
                if r is not None:
                    ev[h].append(r)
        if (k + 1) % 50 == 0:
            print(f"  ..{k+1}/{len(sample)} 事件{n_ev}", flush=True)
    for code in sample:
        for d in rnd.sample(dates[:-25], 3):
            for h in HORIZONS:
                r = _fwd(closes, didx, dates, code, d, h)
                if r is not None:
                    base[h].append(r)

    def st(a):
        return {"n": len(a), "mean": round(statistics.mean(a), 2),
                "median": round(statistics.median(a), 2),
                "win": round(sum(1 for x in a if x > 0) / len(a) * 100, 1)} if a else None
    out = {"built_at": time.strftime("%Y-%m-%d %H:%M"), "thresh": thresh,
           "universe": len(sample), "n_events": n_ev,
           "horizons": {str(h): st(ev[h]) for h in HORIZONS},
           "baseline": {str(h): st(base[h]) for h in HORIZONS}}
    json.dump(out, open(RESULT, "w"), ensure_ascii=False)
    for h in HORIZONS:
        e, b = out["horizons"][str(h)], out["baseline"][str(h)]
        if e and b:
            print(f"H{h:2d}: 事件均{e['mean']:+.2f}% 中位{e['median']:+.2f}% "
                  f"勝率{e['win']:.0f}%(n={e['n']}) | 對照{b['mean']:+.2f}% | "
                  f"超額{e['mean']-b['mean']:+.2f}%")
    print(f"n_events={n_ev} → {RESULT}")


def scan(token, universe_codes=None, weeks=4, thresh=JUMP_PP):
    """掃最近 weeks 週內有大戶跳增的個股(建 scan 快取)。"""
    dates, closes, didx = _panel()
    if universe_codes is None:
        universe_codes = [c for c in closes if len(c) == 4 and c.isdigit()
                          and max(closes[c].values()) > 20]
    hits = []
    cutoff = dates[-weeks * 5] if len(dates) > weeks * 5 else dates[0]
    for k, code in enumerate(universe_codes):
        hist = fetch_holder(code, token, force=True)   # scan 需最新
        if not hist:
            continue
        time.sleep(0.25)
        js = [j for j in detect_jumps(hist, thresh) if j[0] >= cutoff]
        if js:
            last = js[-1]
            cur = closes.get(code, {}).get(dates[-1])
            hits.append({"code": code, "date": last[0], "from": round(last[1], 1),
                         "to": round(last[2], 1), "jump": last[3], "close": cur})
        if (k + 1) % 100 == 0:
            print(f"  ..{k+1}/{len(universe_codes)} hits {len(hits)}", flush=True)
    hits.sort(key=lambda x: (-int(x["date"]), -x["jump"]))
    json.dump({"built_at": time.strftime("%Y-%m-%d %H:%M"), "weeks": weeks,
               "thresh": thresh, "hits": hits}, open(SCAN_OUT, "w"), ensure_ascii=False)
    print(f"掃出 {len(hits)} 檔近{weeks}週大戶跳增 → {SCAN_OUT}")


def load_backtest():
    return json.load(open(RESULT)) if os.path.exists(RESULT) else None


def load_scan():
    return json.load(open(SCAN_OUT)) if os.path.exists(SCAN_OUT) else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--universe", type=int, default=250)
    ap.add_argument("--thresh", type=float, default=JUMP_PP)
    a = ap.parse_args()
    tok = os.environ.get("FINMIND_TOKEN")
    if not tok:
        print("需 FINMIND_TOKEN")
        sys.exit(1)
    if a.backtest:
        backtest(tok, a.universe, a.thresh)
    if a.scan:
        scan(tok, thresh=a.thresh)
    if not (a.backtest or a.scan):
        ap.print_help()
