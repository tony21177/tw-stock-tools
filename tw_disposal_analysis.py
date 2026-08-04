#!/usr/bin/env python3
"""
處置股兩項回測:
  A. 解禁行情 — 解除處置日(處置期末日 E)收盤進場,H5/10/20 報酬 vs date-matched 基準
  B. 整數關卡跨越 — 千金股「原始收盤價」首次站上 1000/2000/3000… 後的動能
     (圓整數效應 proxy;新制鋸齒紅利只適用施行後,回測驗證的是關卡心理效應)

價格:cache/year_prices/{date}.json(還原收盤,報酬計算正確口徑)。
關卡跨越的「事件偵測」用 FinMind TaiwanStockPrice 原始收盤(關卡是名目價格概念,
還原價會平移歷史關卡位置);報酬仍用還原價。

輸出:concept_momentum/cache/disposal_backtest.json
      concept_momentum/cache/tier_cross_backtest.json

CLI:
  python3 tw_disposal_analysis.py --release      # A 解禁回測
  python3 tw_disposal_analysis.py --tier-cross   # B 關卡回測(需 FINMIND_TOKEN)
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
sys.path.insert(0, CM)
import tw_disposal_data as dd  # noqa: E402

HORIZONS = [5, 10, 20]
BASELINE_N = 100


# ── 價格面板(還原收盤) ─────────────────────────────────────────
def load_panel():
    """回傳 (dates[list], closes{code: {date: close}})。"""
    files = sorted(glob.glob(os.path.join(CM, "cache", "year_prices", "*.json")))
    dates, closes = [], {}
    for f in files:
        d = os.path.basename(f).replace(".json", "")
        dates.append(d)
        for code, v in json.load(open(f)).items():
            c = v[2] if isinstance(v, list) and len(v) >= 3 else None
            if c:
                closes.setdefault(code, {})[d] = c
    return dates, closes


def ret_h(closes, code, dates, di, h):
    """dates[di] 收盤 → dates[di+h] 收盤報酬。缺值回 None。"""
    if di + h >= len(dates):
        return None
    c0 = closes.get(code, {}).get(dates[di])
    c1 = closes.get(code, {}).get(dates[di + h])
    if not c0 or not c1:
        return None
    return (c1 - c0) / c0 * 100


def baseline_h(closes, all_codes, dates, di, h, seed):
    rnd = random.Random(seed)
    pool = rnd.sample(all_codes, min(BASELINE_N * 3, len(all_codes)))
    rets = []
    for c in pool:
        r = ret_h(closes, c, dates, di, h)
        if r is not None:
            rets.append(r)
        if len(rets) >= BASELINE_N:
            break
    return statistics.mean(rets) if len(rets) >= 30 else None


def _stats(pairs):
    """pairs = [(絕對報酬, 超額)] → 統計 dict。"""
    if not pairs:
        return None
    a = [p[0] for p in pairs]
    e = [p[1] for p in pairs if p[1] is not None]
    out = {"n": len(a), "mean": round(statistics.mean(a), 2),
           "median": round(statistics.median(a), 2),
           "win": round(sum(1 for x in a if x > 0) / len(a) * 100, 1)}
    if e:
        out["excess_mean"] = round(statistics.mean(e), 2)
        out["excess_median"] = round(statistics.median(e), 2)
        n = len(e)
        if n >= 5 and statistics.pstdev(e) > 0:
            out["t"] = round(statistics.mean(e) /
                             (statistics.stdev(e) / n ** 0.5), 1)
    return out


# ── A. 解禁回測 ────────────────────────────────────────────────
def backtest_release():
    dates, closes = load_panel()
    didx = {d: i for i, d in enumerate(dates)}
    all_codes = [c for c in closes if len(c) == 4 and c.isdigit()]
    punish = dd.load_all("punish")
    events, seen = [], set()
    for r in punish:
        code, st, en = r["code"], r.get("start"), r.get("end")
        if not (code and len(code) == 4 and code.isdigit() and st and en):
            continue
        k = (code, st, en)
        if k in seen:
            continue
        seen.add(k)
        # 解除日 E = 處置期末日;非交易日往前找
        e_idx = didx.get(en)
        if e_idx is None:
            cand = [d for d in dates if d <= en]
            if not cand or cand[-1] < st:
                continue
            e_idx = didx[cand[-1]]
        cum = str(r.get("cum", "")).strip()
        try:
            cum_n = int(float(cum))
        except ValueError:
            cum_n = 1
        events.append({"code": code, "name": r["name"], "market": r["market"],
                       "start": st, "end": en, "e_idx": e_idx, "cum": cum_n,
                       "daytrade": ("當沖" in (r.get("condition") or ""))})

    per_h = {h: [] for h in HORIZONS}
    splits = {"first": {h: [] for h in HORIZONS},
              "second_plus": {h: [] for h in HORIZONS},
              "twse": {h: [] for h in HORIZONS},
              "tpex": {h: [] for h in HORIZONS}}
    in_period = []
    used = []
    for ev in events:
        di = ev["e_idx"]
        # 處置期間報酬(進處置前一日收盤 → 解除日收盤)
        s_idx = didx.get(ev["start"])
        if s_idx and s_idx > 0:
            c0 = closes.get(ev["code"], {}).get(dates[s_idx - 1])
            c1 = closes.get(ev["code"], {}).get(dates[di])
            if c0 and c1:
                in_period.append((c1 - c0) / c0 * 100)
        ok = False
        for h in HORIZONS:
            r = ret_h(closes, ev["code"], dates, di, h)
            if r is None:
                continue
            b = baseline_h(closes, all_codes, dates, di, h,
                           seed=hash((dates[di], h)) & 0xffff)
            ex = r - b if b is not None else None
            per_h[h].append((r, ex))
            key = "first" if ev["cum"] <= 1 else "second_plus"
            splits[key][h].append((r, ex))
            splits[ev["market"]][h].append((r, ex))
            ok = True
        if ok:
            used.append(ev)

    out = {
        "built_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_events": len(used),
        "sample_range": [min(e["end"] for e in used), max(e["end"] for e in used)]
        if used else None,
        "horizons": {str(h): _stats(per_h[h]) for h in HORIZONS},
        "splits": {k: {str(h): _stats(v[h]) for h in HORIZONS}
                   for k, v in splits.items()},
        "in_period_ret": (round(statistics.mean(in_period), 2)
                          if in_period else None),
        "in_period_n": len(in_period),
        "recent": [{"code": e["code"], "name": e["name"], "end": e["end"],
                    "cum": e["cum"]} for e in sorted(used, key=lambda x: x["end"])[-10:]],
    }
    path = os.path.join(CM, "cache", "disposal_backtest.json")
    json.dump(out, open(path, "w"), ensure_ascii=False)
    print(json.dumps(out["horizons"], ensure_ascii=False, indent=1))
    print(f"n={out['n_events']} 處置期間均報酬={out['in_period_ret']}% → {path}")


# ── B. 關卡跨越回測 ────────────────────────────────────────────
def _finmind_raw_closes(code, token, start="2024-07-01"):
    q = urllib.parse.urlencode({"dataset": "TaiwanStockPrice", "data_id": code,
                                "start_date": start, "token": token})
    try:
        with urllib.request.urlopen(
                f"https://api.finmindtrade.com/api/v4/data?{q}", timeout=30) as r:
            d = json.loads(r.read())
        return {row["date"].replace("-", ""): row["close"]
                for row in d.get("data", []) if row.get("close")}
    except Exception:
        return {}


def backtest_tier_cross():
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        print("需要 FINMIND_TOKEN")
        sys.exit(1)
    dates, closes = load_panel()
    didx = {d: i for i, d in enumerate(dates)}
    # 候選:還原收盤曾 >800 的 4 碼個股(關卡股 superset)
    cands = [c for c, m in closes.items()
             if len(c) == 4 and c.isdigit() and max(m.values()) > 800]
    print(f"候選 {len(cands)} 檔,抓原始收盤偵測關卡跨越…", flush=True)
    tiers = [1000, 2000, 3000, 4000, 5000, 6000]
    events = []
    cache_p = os.path.join(CM, "cache", "raw_closes_high.json")
    raw_cache = json.load(open(cache_p)) if os.path.exists(cache_p) else {}
    for i, code in enumerate(cands):
        raw = raw_cache.get(code)
        if raw is None:
            raw = _finmind_raw_closes(code, token)
            raw_cache[code] = raw
            time.sleep(0.4)
        if (i + 1) % 20 == 0:
            print(f"  …{i+1}/{len(cands)}", flush=True)
            json.dump(raw_cache, open(cache_p, "w"))
        rdates = sorted(d for d in raw if d in didx)
        for j in range(1, len(rdates)):
            c_prev, c_now = raw[rdates[j - 1]], raw[rdates[j]]
            for B in tiers:
                if c_prev < B <= c_now:
                    # 60 交易日內首次跨越才算(排除關卡附近震盪重複計)
                    lookback = rdates[max(0, j - 60):j]
                    if any(raw[d] >= B for d in lookback):
                        continue
                    events.append({"code": code, "date": rdates[j], "tier": B})
    json.dump(raw_cache, open(cache_p, "w"))
    print(f"跨關卡事件 {len(events)} 次", flush=True)

    # 對照組:同日其他高價股(原始收盤 800 以上、且當日未跨關卡)
    per_h = {h: [] for h in HORIZONS}
    ctrl_h = {h: [] for h in HORIZONS}
    ev_dates = {e["date"] for e in events}
    for ev in events:
        di = didx[ev["date"]]
        for h in HORIZONS:
            r = ret_h(closes, ev["code"], dates, di, h)
            if r is None:
                continue
            per_h[h].append((r, None))
    # 對照:每個事件日抽同日高價股
    for d in sorted(ev_dates):
        di = didx[d]
        highs = [c for c in cands
                 if closes.get(c, {}).get(d, 0) > 800
                 and not any(e["code"] == c and e["date"] == d for e in events)]
        rnd = random.Random(hash(d) & 0xffff)
        for c in rnd.sample(highs, min(20, len(highs))):
            for h in HORIZONS:
                r = ret_h(closes, c, dates, di, h)
                if r is not None:
                    ctrl_h[h].append((r, None))

    out = {
        "built_at": time.strftime("%Y-%m-%d %H:%M"),
        "n_events": len(events),
        "horizons": {str(h): _stats(per_h[h]) for h in HORIZONS},
        "control": {str(h): _stats(ctrl_h[h]) for h in HORIZONS},
        "by_tier": {},
        "recent": sorted(events, key=lambda e: e["date"])[-12:],
    }
    for B in tiers:
        evB = [e for e in events if e["tier"] == B]
        if not evB:
            continue
        ph = {h: [] for h in HORIZONS}
        for e in evB:
            di = didx[e["date"]]
            for h in HORIZONS:
                r = ret_h(closes, e["code"], dates, di, h)
                if r is not None:
                    ph[h].append((r, None))
        out["by_tier"][str(B)] = {str(h): _stats(ph[h]) for h in HORIZONS}
    path = os.path.join(CM, "cache", "tier_cross_backtest.json")
    json.dump(out, open(path, "w"), ensure_ascii=False)
    print(json.dumps(out["horizons"], ensure_ascii=False, indent=1))
    print("對照:", json.dumps(out["control"], ensure_ascii=False))
    print(f"→ {path}")


# ── 每日訊號:今日跨關卡 + 逼近關卡 watch ─────────────────────
TIERS = [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000,
         12000, 15000, 20000]
RAW_CACHE = os.path.join(CM, "cache", "raw_closes_high.json")


def update_raw_closes(token: str) -> dict:
    """增量更新高價股原始收盤快取。候選=還原收盤近 60 日曾 >900 的 4 碼個股
    (新進榜者抓近 120 日)。回傳快取 dict {code: {date: close}}。"""
    dates, closes = load_panel()
    recent = dates[-60:]
    cands = {c for c, m in closes.items()
             if len(c) == 4 and c.isdigit()
             and max((m.get(d, 0) for d in recent), default=0) > 900}
    cache = json.load(open(RAW_CACHE)) if os.path.exists(RAW_CACHE) else {}
    from datetime import datetime, timedelta
    for code in sorted(cands | set(cache)):
        cur = cache.get(code, {})
        if cur:
            last = max(cur)
            start = (datetime.strptime(last, "%Y%m%d")
                     + timedelta(days=1)).strftime("%Y-%m-%d")
            if last >= dates[-1]:
                continue
        else:
            start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        new = _finmind_raw_closes(code, token, start=start)
        if new:
            cur.update(new)
            cache[code] = cur
        time.sleep(0.3)
    json.dump(cache, open(RAW_CACHE, "w"))
    return cache


def _first_cross(raw: dict, rdates: list, j: int, B: int) -> bool:
    """rdates[j] 收盤跨上 B 且前 60 交易日未曾 ≥B。"""
    if j == 0:
        return False
    if not (raw[rdates[j - 1]] < B <= raw[rdates[j]]):
        return False
    return not any(raw[d] >= B for d in rdates[max(0, j - 60):j])


def recent_tier_events(days: int = 5) -> list[dict]:
    """近 N 交易日的跨關卡事件(讀快取,不打 API)。"""
    if not os.path.exists(RAW_CACHE):
        return []
    cache = json.load(open(RAW_CACHE))
    out = []
    for code, raw in cache.items():
        rdates = sorted(raw)
        if len(rdates) < 61:
            continue
        for j in range(max(1, len(rdates) - days), len(rdates)):
            for B in TIERS:
                if _first_cross(raw, rdates, j, B):
                    out.append({"code": code, "date": rdates[j], "tier": B,
                                "close": raw[rdates[j]]})
    out.sort(key=lambda e: (-int(e["date"]), -e["tier"]))
    return out


def near_tier_watch(max_gap_pct: float = 5.0) -> list[dict]:
    """逼近關卡 watch:最新收盤距上方「60 日未觸及」關卡 ≤max_gap_pct%。"""
    if not os.path.exists(RAW_CACHE):
        return []
    cache = json.load(open(RAW_CACHE))
    out = []
    for code, raw in cache.items():
        rdates = sorted(raw)
        if len(rdates) < 61:
            continue
        c = raw[rdates[-1]]
        nxt = next((B for B in TIERS if B > c), None)
        if not nxt:
            continue
        gap = (nxt - c) / c * 100
        if gap > max_gap_pct:
            continue
        if any(raw[d] >= nxt for d in rdates[-61:-1]):
            continue                      # 近 60 日碰過 → 非首次跨越 setup
        out.append({"code": code, "close": c, "tier": nxt,
                    "gap_pct": round(gap, 1), "date": rdates[-1]})
    out.sort(key=lambda e: e["gap_pct"])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--tier-cross", action="store_true")
    a = ap.parse_args()
    if a.release:
        backtest_release()
    if a.tier_cross:
        backtest_tier_cross()
    if not (a.release or a.tier_cross):
        ap.print_help()
