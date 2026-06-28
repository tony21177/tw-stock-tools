#!/usr/bin/env python3
"""股價盤中走勢模擬系統 (tw_intraday_sim)

給股票代號 → 根據籌碼/型態/量價狀態，模擬「下一交易日」09:00-13:30 走勢。
三種呈現：
  A 情境劇本   — 相似日隔天路徑分群 (具名劇本 + 機率)
  B 信心帶     — 相似日逐分鐘中位數 + 25/75 百分位帶
  C 蒙地卡羅   — 純波動度隨機模擬 (沒有資訊優勢的對照基準)

核心 = A2 相似日法：FinMind 日線特徵找「籌碼/型態最像今天」的歷史日，
抓那些日子隔天的 TaiwanStockKBar 分鐘路徑 (rebase 距前收%)。

設計見 docs/superpowers/specs/2026-06-28-intraday-price-simulation-design.md
用法：
  tw_intraday_sim.py 6451                       # 個股自己池
  tw_intraday_sim.py 6451 --json-out out.json
"""
from __future__ import annotations
import json
import math
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
KBAR_CACHE = os.path.join(CACHE, "kbar")
FINMIND = "https://api.finmindtrade.com/api/v4/data"

# 盤中分鐘格 09:00 ~ 13:30（含），共 271 格
MINUTE_GRID = [f"{9 + (m // 60):02d}:{m % 60:02d}" for m in range(0, 271)]
# 09:00..13:30 → minutes-from-open 0..270


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    import subprocess
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    return ""


def _fm(dataset: str, data_id: str, start: str, token: str,
        end: str | None = None) -> list[dict]:
    p = {"dataset": dataset, "data_id": data_id, "start_date": start, "token": token}
    if end:
        p["end_date"] = end
    q = urllib.parse.urlencode(p)
    for _ in range(3):
        try:
            with urllib.request.urlopen(f"{FINMIND}?{q}", timeout=30) as r:
                return json.loads(r.read().decode()).get("data", [])
        except Exception:
            time.sleep(2)
    return []


# ── 資料層 ──────────────────────────────────────────────
def fetch_daily(code: str, start: str, token: str) -> list[dict]:
    """日線 OHLCV，date 轉 YYYYMMDD，排序。"""
    out = []
    for x in _fm("TaiwanStockPrice", code, start, token):
        c = x.get("close")
        if not c or c <= 0:
            continue
        out.append({"date": x["date"].replace("-", ""),
                    "open": float(x.get("open") or c), "high": float(x.get("max") or c),
                    "low": float(x.get("min") or c), "close": float(c),
                    "volume": float(x.get("Trading_Volume") or 0)})
    out.sort(key=lambda r: r["date"])
    return out


def fetch_kbar(code: str, date_yyyymmdd: str, token: str) -> list[dict] | None:
    """某日分鐘 K（含快取）。回 [{minute 'HH:MM', close, volume}] 或 None。"""
    os.makedirs(KBAR_CACHE, exist_ok=True)
    cp = os.path.join(KBAR_CACHE, f"{code}_{date_yyyymmdd}.json")
    if os.path.exists(cp):
        try:
            with open(cp) as f:
                d = json.load(f)
            return d if d else None
        except Exception:
            pass
    iso = f"{date_yyyymmdd[:4]}-{date_yyyymmdd[4:6]}-{date_yyyymmdd[6:]}"
    raw = _fm("TaiwanStockKBar", code, iso, token, end=iso)
    bars = []
    for x in raw:
        mn = str(x.get("minute", ""))[:5]   # 'HH:MM'
        c = x.get("close")
        if mn and c:
            bars.append({"minute": mn, "close": float(c),
                         "volume": float(x.get("volume") or 0)})
    bars.sort(key=lambda b: b["minute"])
    with open(cp, "w") as f:
        json.dump(bars, f)
    return bars or None


# ── 特徵抽取 ────────────────────────────────────────────
def _ma(rows: list[dict], i: int, n: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(r["close"] for r in rows[i + 1 - n:i + 1]) / n


def extract_features(rows: list[dict], i: int, chip: dict | None = None) -> dict | None:
    """rows[i] 當天的特徵。chip = {date→{borrow_chg5,margin_chg5,inst_ratio}} 可選。
    回 dict 或 None（資料不足）。"""
    if i < 60:
        return None
    r = rows[i]
    c = r["close"]
    feat = {}
    # 型態：距均線
    for n in (5, 20, 60):
        ma = _ma(rows, i, n)
        if ma is None or ma <= 0:
            return None
        feat[f"dist_ma{n}"] = (c / ma - 1) * 100
    # 報酬
    feat["ret5"] = (c / rows[i - 5]["close"] - 1) * 100
    feat["ret20"] = (c / rows[i - 20]["close"] - 1) * 100
    # 距 20 日高低位置 0~100
    win = rows[i - 19:i + 1]
    hi = max(x["high"] for x in win); lo = min(x["low"] for x in win)
    feat["pos20"] = (c - lo) / (hi - lo) * 100 if hi > lo else 50.0
    # 今日 K 棒
    o = r["open"]; h = r["high"]; lw = r["low"]
    rng = h - lw if h > lw else 1e-9
    feat["body"] = (c - o) / o * 100                       # 收紅(+)/黑(-)%
    feat["upsh"] = (h - max(o, c)) / rng * 100             # 上影線比
    feat["dnsh"] = (min(o, c) - lw) / rng * 100            # 下影線比
    feat["gap"] = (o / rows[i - 1]["close"] - 1) * 100     # 開盤跳空%
    # 量價
    vols = [x["volume"] for x in rows[i - 19:i + 1]]
    vma = statistics.mean(vols) if vols else 0
    feat["volratio"] = (r["volume"] / vma) if vma > 0 else 1.0
    # 籌碼（可選；缺則中位數補在標準化階段處理）
    if chip:
        ch = chip.get(r["date"], {})
        feat["borrow5"] = ch.get("borrow_chg5")
        feat["margin5"] = ch.get("margin_chg5")
        feat["inst"] = ch.get("inst_ratio")
    return feat


FEATURE_KEYS = ["dist_ma5", "dist_ma20", "dist_ma60", "ret5", "ret20", "pos20",
                "body", "upsh", "dnsh", "gap", "volratio",
                "borrow5", "margin5", "inst"]


# ── 籌碼歷史（個股自己池用）────────────────────────────
def build_chip_history(code: str, start: str, token: str) -> dict:
    """回 {date YYYYMMDD → {borrow_chg5, margin_chg5, inst_ratio}}。"""
    out: dict[str, dict] = {}
    # 借券賣出餘額
    bal = {}
    for x in _fm("TaiwanDailyShortSaleBalances", code, start, token):
        d = x["date"].replace("-", "")
        v = x.get("ShortSaleBalance") or x.get("TodayBalance")
        if v is not None:
            bal[d] = float(v)
    # 融資餘額
    mar = {}
    for x in _fm("TaiwanStockMarginPurchaseShortSale", code, start, token):
        d = x["date"].replace("-", "")
        v = x.get("MarginPurchaseTodayBalance")
        if v is not None:
            mar[d] = float(v)
    # 三大法人合計 + 量（淨買超/量需要量，這裡存淨額，比對時用相對值）
    inst = {}
    for x in _fm("TaiwanStockInstitutionalInvestorsBuySell", code, start, token):
        d = x["date"].replace("-", "")
        net = (x.get("buy") or 0) - (x.get("sell") or 0)
        inst[d] = inst.get(d, 0) + net
    def chg5(series: dict, d: str, dates: list) -> float | None:
        if d not in series:
            return None
        idx = dates.index(d) if d in dates else None
        if idx is None or idx < 5:
            return None
        prev = series.get(dates[idx - 5])
        if prev is None or prev == 0:
            return None
        return (series[d] / prev - 1) * 100
    bdates = sorted(bal); mdates = sorted(mar)
    alld = sorted(set(bal) | set(mar) | set(inst))
    for d in alld:
        out[d] = {
            "borrow_chg5": chg5(bal, d, bdates),
            "margin_chg5": chg5(mar, d, mdates),
            "inst_ratio": inst.get(d),     # 原始淨額；標準化時轉 z
        }
    return out


# ── 標準化 + 相似日搜尋 ────────────────────────────────
def build_matrix(rows: list[dict], chip: dict) -> list[dict]:
    """回 [{i, date, feat}] 所有可算特徵的日子（型態/量價必備，缺則跳過）。"""
    out = []
    for i in range(len(rows)):
        f = extract_features(rows, i, chip)
        if f is None:
            continue
        # 型態/量價核心缺值 → 跳過 (extract_features 已保證非 None)
        out.append({"i": i, "date": rows[i]["date"], "feat": f})
    return out


def _stats(matrix: list[dict]) -> dict:
    """每特徵的 mean/std/median（None 忽略）。"""
    st = {}
    for k in FEATURE_KEYS:
        vals = [m["feat"].get(k) for m in matrix]
        vals = [v for v in vals if v is not None]
        if not vals:
            st[k] = (0.0, 1.0, 0.0); continue
        mu = statistics.mean(vals)
        sd = statistics.pstdev(vals) or 1.0
        st[k] = (mu, sd, statistics.median(vals))
    return st


def _zvec(feat: dict, st: dict) -> list[float]:
    """標準化向量；None 以中位數補（z=0 即 median 補後標準化）。"""
    out = []
    for k in FEATURE_KEYS:
        mu, sd, med = st[k]
        v = feat.get(k)
        if v is None:
            v = med
        out.append((v - mu) / sd)
    return out


def find_analogs(today_feat: dict, matrix: list[dict], st: dict, k: int,
                 exclude_last_i: int, min_gap_days: int = 3) -> list[dict]:
    """回最像今天的 k 天 [{i,date,dist}]，排除最後幾天(避免重疊/未來)。"""
    tz = _zvec(today_feat, st)
    scored = []
    for m in matrix:
        if m["i"] >= exclude_last_i - min_gap_days:
            continue
        mz = _zvec(m["feat"], st)
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(tz, mz)))
        scored.append({"i": m["i"], "date": m["date"], "dist": d})
    scored.sort(key=lambda x: x["dist"])
    return scored[:k]


# ── 相似日隔天路徑 ────────────────────────────────────
def rebase_path(kbar: list[dict], prev_close: float) -> list[float] | None:
    """分鐘 K → 271 格「距 prev_close %」，前向填補。"""
    if not kbar or prev_close <= 0:
        return None
    by_min = {b["minute"]: b["close"] for b in kbar}
    out = []
    last = None
    for mn in MINUTE_GRID:
        if mn in by_min:
            last = (by_min[mn] / prev_close - 1) * 100
        out.append(last)
    # 前導 None 用第一個有值補
    first = next((v for v in out if v is not None), 0.0)
    return [v if v is not None else first for v in out]


def gather_next_day_paths(code: str, rows: list[dict], analogs: list[dict],
                          token: str) -> list[list[float]]:
    """每個相似日 → 抓它隔天分鐘 K → rebase 成 271 格 %。"""
    paths = []
    for a in analogs:
        j = a["i"]
        if j + 1 >= len(rows):
            continue
        nxt = rows[j + 1]["date"]
        kb = fetch_kbar(code, nxt, token)
        if not kb:
            continue
        p = rebase_path(kb, rows[j]["close"])
        if p:
            paths.append(p)
    return paths


# ── A 分群劇本 ────────────────────────────────────────
def _bucket(p: list[float]) -> str:
    gap = p[0]
    move = p[-1] - p[0]
    g = "高" if gap > 0.5 else ("低" if gap < -0.5 else "平")
    m = "走高" if move > 0.5 else ("走低" if move < -0.5 else "盤整")
    names = {
        ("高", "走低"): "開高走低", ("低", "走高"): "開低走高",
        ("平", "走高"): "開平走高", ("平", "走低"): "開平走低",
        ("高", "走高"): "開高走高(強)", ("低", "走低"): "開低走低(弱)",
        ("高", "盤整"): "高開盤整", ("低", "盤整"): "低開盤整",
        ("平", "盤整"): "平盤整理",
    }
    return names[(g, m)]


def _median_path(paths: list[list[float]]) -> list[float]:
    return [statistics.median(col) for col in zip(*paths)]


def cluster_scenarios(paths: list[list[float]]) -> list[dict]:
    from collections import defaultdict
    buckets = defaultdict(list)
    for p in paths:
        buckets[_bucket(p)].append(p)
    n = len(paths)
    scen = [{"name": k, "prob": round(len(v) / n * 100, 0), "count": len(v),
             "path": _median_path(v)} for k, v in buckets.items()]
    # 併小桶 (<8%) 入最大桶
    big = [s for s in scen if s["count"] / n >= 0.08]
    small = [s for s in scen if s["count"] / n < 0.08]
    if small and big:
        big.sort(key=lambda s: -s["count"])
        # 小桶併入「其他」名義保留資訊：標成備註，不重畫路徑
        merged_n = sum(s["count"] for s in small)
        big_total = sum(s["count"] for s in big)
        for s in big:                       # 重新正規化機率到大桶
            s["prob"] = round(s["count"] / big_total * 100, 0)
        scen = big
        scen.append({"name": f"其他零星 ({len(small)}型)", "prob": 0,
                     "count": merged_n, "path": None})
    scen.sort(key=lambda s: -s["count"])
    return scen


# ── B 信心帶 ──────────────────────────────────────────
def _pct_band(paths: list[list[float]]) -> dict:
    def pct(col, q):
        s = sorted(col); idx = min(len(s) - 1, max(0, int(q * (len(s) - 1))))
        return s[idx]
    cols = list(zip(*paths))
    return {
        "median": [statistics.median(c) for c in cols],
        "p25": [pct(c, 0.25) for c in cols], "p75": [pct(c, 0.75) for c in cols],
        "p10": [pct(c, 0.10) for c in cols], "p90": [pct(c, 0.90) for c in cols],
    }


# ── C 蒙地卡羅 ────────────────────────────────────────
def monte_carlo(rows: list[dict], n_sims: int = 500) -> dict:
    """純統計：用歷史開盤跳空分布 + 日內波動度，做 N 條布朗運動路徑。
    用固定 seed 的常態隨機（可重現），變異數隨時間擴散（扇形展開）。"""
    import random
    rng = random.Random(20260628)
    rets = [(rows[i]["close"] / rows[i - 1]["close"] - 1)
            for i in range(1, len(rows))]
    daily_sd = statistics.pstdev(rets) if len(rets) > 2 else 0.02
    gaps = [(rows[i]["open"] / rows[i - 1]["close"] - 1) for i in range(1, len(rows))]
    gap_mu = statistics.mean(gaps) if gaps else 0.0
    gap_sd = statistics.pstdev(gaps) if len(gaps) > 2 else daily_sd
    steps = len(MINUTE_GRID)
    # 盤中(開盤後到收盤)總波動 ≈ daily_sd；每分鐘 sd = daily_sd / sqrt(steps)
    per_min_sd = daily_sd / math.sqrt(steps)
    sims = []
    for _ in range(n_sims):
        gap = rng.gauss(gap_mu, gap_sd)          # 開盤跳空
        cum = gap
        path = [cum * 100]
        for _t in range(1, steps):
            cum += rng.gauss(0, per_min_sd)      # 每分鐘隨機步進 → 累積擴散
            path.append(cum * 100)
        sims.append(path)
    return _pct_band(sims)


# ── 全市場池（技術+量價子集，無歷史籌碼）────────────
PRICE_ALL = os.path.join(CACHE, "backtest_prices_all.json")
MKT_MATRIX = os.path.join(CACHE, "intraday_mkt_matrix.json")
MKT_KEYS = ["dist_ma5", "dist_ma20", "dist_ma60", "ret5", "ret20", "volratio"]


def _tech_feat_from_close(closes: list[float], vols: list[float], i: int) -> list[float] | None:
    """只用 close+volume 的技術子集 (市場池)。回 6 維向量或 None。"""
    if i < 60:
        return None
    c = closes[i]
    out = []
    for n in (5, 20, 60):
        ma = sum(closes[i + 1 - n:i + 1]) / n
        if ma <= 0:
            return None
        out.append((c / ma - 1) * 100)
    out.append((c / closes[i - 5] - 1) * 100)
    out.append((c / closes[i - 20] - 1) * 100)
    vma = statistics.mean(vols[i - 19:i + 1]) if i >= 19 else 0
    out.append((vols[i] / vma) if vma > 0 else 1.0)
    return out


_MKT_CACHE = None       # 記憶體快取矩陣
_PRICE_ALL_CACHE = None


def _load_price_all() -> dict:
    global _PRICE_ALL_CACHE
    if _PRICE_ALL_CACHE is None:
        with open(PRICE_ALL) as f:
            _PRICE_ALL_CACHE = json.load(f)["stocks"]
    return _PRICE_ALL_CACHE


def build_market_matrix(rebuild: bool = False) -> dict:
    """從 backtest_prices_all.json 算全市場技術特徵矩陣，快取(檔案+記憶體)。
    回 {keys, mu, sd, rows:[[code, date, z1..z6]]} (已標準化)。"""
    global _MKT_CACHE
    if _MKT_CACHE is not None and not rebuild:
        return _MKT_CACHE
    if os.path.exists(MKT_MATRIX) and not rebuild:
        with open(MKT_MATRIX) as f:
            _MKT_CACHE = json.load(f)
        return _MKT_CACHE
    allp = _load_price_all()
    raw = []   # [code, date, vec(6)]
    for code, s in allp.items():
        rows = s["rows"]
        closes = [r["close"] for r in rows]
        vols = [r["volume"] for r in rows]
        for i in range(60, len(rows)):
            v = _tech_feat_from_close(closes, vols, i)
            if v:
                raw.append([code, rows[i]["date"], v])
    # 標準化
    cols = list(zip(*[r[2] for r in raw]))
    mu = [statistics.mean(c) for c in cols]
    sd = [statistics.pstdev(c) or 1.0 for c in cols]
    rows_z = [[r[0], r[1]] + [(r[2][j] - mu[j]) / sd[j] for j in range(6)] for r in raw]
    out = {"keys": MKT_KEYS, "mu": mu, "sd": sd, "rows": rows_z,
           "n_stocks": len(allp)}
    with open(MKT_MATRIX, "w") as f:
        json.dump(out, f)
    _MKT_CACHE = out
    return out


def run_market_pool(today_tech: list[float], k: int, token: str) -> dict:
    """市場池：今天的技術向量 → 全市場相似日 → 隔天路徑 → A/B/C。"""
    mat = build_market_matrix()
    mu, sd = mat["mu"], mat["sd"]
    tz = [(today_tech[j] - mu[j]) / sd[j] for j in range(6)]
    scored = []
    for r in mat["rows"]:
        z = r[2:]
        d = sum((tz[j] - z[j]) ** 2 for j in range(6))
        scored.append((d, r[0], r[1]))
    scored.sort(key=lambda x: x[0])
    # 取最像的 k 檔股票日 (不同股票，避免同股連續日洗版：每股最多 2 筆)
    picks = []
    per_stock: dict[str, int] = {}
    for d, code, date in scored:
        if per_stock.get(code, 0) >= 2:
            continue
        per_stock[code] = per_stock.get(code, 0) + 1
        picks.append((code, date, math.sqrt(d)))
        if len(picks) >= k:
            break
    # 抓每個相似日「隔天」路徑
    allp = _load_price_all()
    paths = []
    for code, date, dist in picks:
        rows = allp[code]["rows"]
        idx = next((ii for ii, rr in enumerate(rows) if rr["date"] == date), None)
        if idx is None or idx + 1 >= len(rows):
            continue
        nxt = rows[idx + 1]["date"]
        kb = fetch_kbar(code, nxt, token)
        if not kb:
            continue
        p = rebase_path(kb, rows[idx]["close"])
        if p:
            paths.append(p)
    out = {"n_analog": len(paths),
           "avg_dist": round(statistics.mean([p[2] for p in picks]), 2) if picks else None}
    if paths:
        out["scenarios"] = cluster_scenarios(paths)
        out["band"] = _pct_band(paths)
    return out


def run(code: str, k: int = 40, start: str = "2024-01-01", pool: str = "self") -> dict:
    tok = _token()
    rows = fetch_daily(code, start, tok)
    if len(rows) < 80:
        return {"error": f"日線資料不足 ({len(rows)} 根)"}
    chip = build_chip_history(code, start, tok)
    today_i = len(rows) - 1
    today_feat = extract_features(rows, today_i, chip)
    if not today_feat:
        return {"error": "今日特徵無法計算"}
    matrix = build_matrix(rows, chip)
    st = _stats(matrix)
    analogs = find_analogs(today_feat, matrix, st, k, exclude_last_i=today_i)
    paths = gather_next_day_paths(code, rows, analogs, tok)
    out = {
        "code": code, "as_of": rows[today_i]["date"],
        "prev_close": rows[today_i]["close"],
        "grid": MINUTE_GRID, "n_analog": len(paths),
        "analog_dates": [a["date"] for a in analogs[:len(paths)]],
        "avg_dist": round(statistics.mean([a["dist"] for a in analogs]), 2) if analogs else None,
        "monte_carlo": monte_carlo(rows),
    }
    if paths:
        out["scenarios"] = cluster_scenarios(paths)
        out["band"] = _pct_band(paths)
    # 全市場池（技術子集）
    if pool in ("market", "both") and os.path.exists(PRICE_ALL):
        closes = [r["close"] for r in rows]; vols = [r["volume"] for r in rows]
        today_tech = _tech_feat_from_close(closes, vols, today_i)
        if today_tech:
            try:
                out["market"] = run_market_pool(today_tech, k, tok)
            except Exception as e:
                out["market"] = {"error": f"{type(e).__name__}: {e}"}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("-k", type=int, default=40)
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    res = run(args.code, args.k, args.start)
    if res.get("error"):
        print("ERROR:", res["error"]); sys.exit(1)
    print(f"{res['code']} as_of {res['as_of']} 前收 {res['prev_close']}")
    print(f"相似日樣本 {res['n_analog']} / 平均距離 {res['avg_dist']}")
    if res.get("scenarios"):
        print("情境劇本:")
        for s in res["scenarios"]:
            end = f"收{s['path'][-1]:+.1f}%" if s["path"] else ""
            print(f"  {s['name']:<14} {s['prob']:.0f}% (n={s['count']}) {end}")
    b = res.get("band")
    if b:
        print(f"信心帶 收盤分布: p25 {b['p25'][-1]:+.1f}% / 中位 {b['median'][-1]:+.1f}% / p75 {b['p75'][-1]:+.1f}%")
    mc = res["monte_carlo"]
    print(f"蒙地卡羅 收盤: p10 {mc['p10'][-1]:+.1f}% / 中位 {mc['median'][-1]:+.1f}% / p90 {mc['p90'][-1]:+.1f}%")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        print(f"[json] 寫入 {args.json_out}")
