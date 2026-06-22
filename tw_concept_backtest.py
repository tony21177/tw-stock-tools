#!/usr/bin/env python3
"""族群資金流向策略 回測 — 驗證 sustainability_score 是否預測前向超額報酬。

策略 (concept_momentum.py)：每族群每日算
  score = 0.40×廣度 + 0.20×量能 + 0.20×RS + 0.20×續航
高分 = 資金流入。選股 = 熱門族群的 leaders。

回測手法：用 FinMind 歷史價格 point-in-time 重建 score（直接 import 正式
程式的 compute_score_for_date，測的是真訊號），再量前向報酬。

Layer 1 (族群層)：每 R 日 rebalance，排名 34 族群，量未來 H 日各族群相對
  大盤超額報酬 → IC(Spearman) + 高分組vs低分組價差 + 命中率 + horizon。
Layer 2 (選股層)：買前 K 名族群的 Top5 leaders 等權、持有 H 日、扣成本，
  畫權益曲線 + 勝率 + 最大回撤。
對照基準：純 ret_20d 排序 (證明廣度/量能/續航有沒有加值)。

用法：
  tw_concept_backtest.py                      # 預設 2025-01-01 起
  tw_concept_backtest.py --start 2024-06-01 --rebalance 5 --horizon 5 10 20
  tw_concept_backtest.py --topk 3 --cost 0.4
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CM = os.path.join(HERE, "concept_momentum")
sys.path.insert(0, HERE)
sys.path.insert(0, CM)

from concept_momentum import compute_score_for_date, extract_leaders, _truncate_rows  # noqa: E402

CONCEPTS = os.path.join(CM, "cache", "concepts.json")
PRICE_CACHE = os.path.join(CM, "cache", "backtest_prices.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"


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


def _fm_price(data_id: str, start: str, token: str) -> list[dict]:
    q = urllib.parse.urlencode({"dataset": "TaiwanStockPrice", "data_id": data_id,
                                "start_date": start, "token": token})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{FINMIND}?{q}", timeout=30) as r:
                return json.loads(r.read().decode()).get("data", [])
        except Exception:
            time.sleep(2)
    return []


def _to_rows(fm_data: list[dict]) -> list[dict]:
    """FinMind → [{date:YYYYMMDD, close, volume}] 排序。"""
    out = []
    for x in fm_data:
        c = x.get("close")
        if c is None or c <= 0:
            continue
        out.append({"date": x["date"].replace("-", ""), "close": float(c),
                    "volume": float(x.get("Trading_Volume") or 0)})
    out.sort(key=lambda r: r["date"])
    return out


def load_data(start: str, token: str, names: dict) -> tuple[dict, list[dict]]:
    """回 (stocks_data, taiex_rows)。有快取且涵蓋 start 就用快取。"""
    if os.path.exists(PRICE_CACHE):
        with open(PRICE_CACHE) as f:
            cache = json.load(f)
        if cache.get("start") == start:
            print(f"[cache] 用既有價格快取 ({len(cache['stocks'])} 檔)", file=sys.stderr)
            return cache["stocks"], cache["taiex"]

    codes = sorted({c for v in names.values() for c in v["stocks"]})
    print(f"[fetch] 抓 {len(codes)} 檔 + TAIEX，自 {start} …", file=sys.stderr)
    stocks = {}
    for i, code in enumerate(codes):
        rows = _to_rows(_fm_price(code, start, token))
        if rows:
            stocks[code] = {"code": code, "name": code, "market": "",
                            "rows": rows, "current_price": rows[-1]["close"]}
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(codes)}", file=sys.stderr)
        time.sleep(0.08)
    taiex = _to_rows(_fm_price("TAIEX", start, token))
    with open(PRICE_CACHE, "w") as f:
        json.dump({"start": start, "stocks": stocks, "taiex": taiex}, f)
    print(f"[fetch] 完成，快取寫入 {PRICE_CACHE}", file=sys.stderr)
    return stocks, taiex


def trading_dates(stocks: dict) -> list[str]:
    s = set()
    for v in stocks.values():
        for r in v["rows"]:
            s.add(r["date"])
    return sorted(s)


def theme_fwd_return(theme_info: dict, stocks: dict, t: str, fwd: str) -> float | None:
    """族群等權成員 t→fwd 報酬 (%)。"""
    rets = []
    for c in theme_info.get("stocks", []):
        s = stocks.get(c)
        if not s:
            continue
        px = {r["date"]: r["close"] for r in s["rows"]}
        if t in px and fwd in px and px[t] > 0:
            rets.append((px[fwd] / px[t] - 1) * 100)
    return statistics.mean(rets) if rets else None


def stock_fwd_return(code: str, stocks: dict, t: str, fwd: str) -> float | None:
    s = stocks.get(code)
    if not s:
        return None
    px = {r["date"]: r["close"] for r in s["rows"]}
    if t in px and fwd in px and px[t] > 0:
        return (px[fwd] / px[t] - 1) * 100
    return None


def taiex_fwd_return(taiex: list[dict], t: str, fwd: str) -> float | None:
    px = {r["date"]: r["close"] for r in taiex}
    if t in px and fwd in px and px[t] > 0:
        return (px[fwd] / px[t] - 1) * 100
    return None


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation."""
    n = len(xs)
    if n < 3:
        return 0.0
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def ret_20d_score(theme_info: dict, stocks: dict, t: str) -> float:
    """對照基準：純 20 日報酬 (等權成員)。"""
    rets = []
    for c in theme_info.get("stocks", []):
        s = stocks.get(c)
        if not s:
            continue
        rows = _truncate_rows(s["rows"], t)
        if len(rows) > 20 and rows[-21]["close"] > 0:
            rets.append((rows[-1]["close"] / rows[-21]["close"] - 1) * 100)
    return statistics.mean(rets) if rets else 0.0


def run_backtest(start, rebalance, horizons, topk, cost, which, label):
    token = _token()
    if not token:
        print("[ERROR] 需要 FINMIND_TOKEN", file=sys.stderr)
        sys.exit(1)
    themes = json.load(open(CONCEPTS))["themes"]
    stocks, taiex = load_data(start, token, themes)
    dates = trading_dates(stocks)
    if len(dates) < 60:
        print(f"[ERROR] 交易日太少 ({len(dates)})", file=sys.stderr)
        sys.exit(1)

    def _valid(info, t):
        n = sum(1 for c in info.get("stocks", []) if c in stocks
                and len(_truncate_rows(stocks[c]["rows"], t)) >= 21)
        return n >= 3

    # score function: 策略真訊號 vs 純動能對照
    if which == "strategy":
        def score_fn(info, t):
            return compute_score_for_date(info, stocks, taiex, t) if _valid(info, t) else None
    else:                                          # benchmark: 純 ret_20d
        def score_fn(info, t):
            return ret_20d_score(info, stocks, t) if _valid(info, t) else None

    # rebalance 日：留 warmup 20 + 最大 horizon 在尾端
    max_h = max(horizons)
    idxs = list(range(20, len(dates) - max_h, rebalance))
    print(f"\n{'='*60}\n回測：{label}  ({dates[idxs[0]]} ~ {dates[idxs[-1]]}, "
          f"{len(idxs)} 個 rebalance 點)\n{'='*60}")

    results = {h: {"ic": [], "top_rs": [], "bot_rs": [], "hit": [],
                   "l2_ret": []} for h in horizons}

    for t_i in idxs:
        t = dates[t_i]
        scored = []
        for tk, info in themes.items():
            sc = score_fn(info, t)
            if sc is not None:
                scored.append((tk, info, sc))
        if len(scored) < 6:
            continue
        scored.sort(key=lambda x: x[2], reverse=True)
        n = len(scored)
        tercile = max(1, n // 3)

        for h in horizons:
            fwd = dates[t_i + h]
            tw = taiex_fwd_return(taiex, t, fwd)
            if tw is None:
                continue
            sc_list, rs_list = [], []
            for tk, info, sc in scored:
                tr = theme_fwd_return(info, stocks, t, fwd)
                if tr is None:
                    continue
                sc_list.append(sc)
                rs_list.append(tr - tw)        # 超額 vs 大盤
            if len(sc_list) < 6:
                continue
            results[h]["ic"].append(spearman(sc_list, rs_list))
            # 高分前 1/3 vs 低分後 1/3 (rs_list 已按 score 排序)
            top = rs_list[:tercile]
            bot = rs_list[-tercile:]
            results[h]["top_rs"].append(statistics.mean(top))
            results[h]["bot_rs"].append(statistics.mean(bot))
            results[h]["hit"].append(1 if statistics.mean(top) > 0 else 0)

            # Layer 2：前 K 名族群的 leaders
            leg = []
            for tk, info, sc in scored[:topk]:
                codes = info.get("stocks", [])
                cstocks = [{**stocks[c], "rows": _truncate_rows(stocks[c]["rows"], t)}
                           for c in codes if c in stocks
                           and len(_truncate_rows(stocks[c]["rows"], t)) >= 20]
                for ld in extract_leaders(cstocks, top_n=5):
                    r = stock_fwd_return(ld["code"], stocks, t, fwd)
                    if r is not None:
                        leg.append(r)
            if leg:
                results[h]["l2_ret"].append(statistics.mean(leg) - tw - cost)

    # 輸出
    for h in horizons:
        R = results[h]
        if not R["ic"]:
            print(f"\n[H={h}d] 無足夠樣本")
            continue
        ic = statistics.mean(R["ic"])
        ic_pos = sum(1 for x in R["ic"] if x > 0) / len(R["ic"]) * 100
        top = statistics.mean(R["top_rs"])
        bot = statistics.mean(R["bot_rs"])
        hit = statistics.mean(R["hit"]) * 100
        l2 = statistics.mean(R["l2_ret"]) if R["l2_ret"] else float("nan")
        l2_win = (sum(1 for x in R["l2_ret"] if x > 0) / len(R["l2_ret"]) * 100
                  if R["l2_ret"] else float("nan"))
        print(f"\n【持有 {h} 交易日】 樣本 {len(R['ic'])} 期")
        print(f"  IC (Spearman)     : {ic:+.3f}   (>0 比例 {ic_pos:.0f}%)")
        print(f"  高分前1/3 超額報酬 : {top:+.2f}%")
        print(f"  低分後1/3 超額報酬 : {bot:+.2f}%")
        print(f"  多空價差 (高−低)   : {top-bot:+.2f}%")
        print(f"  高分組贏大盤命中率 : {hit:.0f}%")
        print(f"  Layer2 選股淨超額  : {l2:+.2f}% (扣{cost}%成本, 勝率{l2_win:.0f}%)")
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--rebalance", type=int, default=5)
    ap.add_argument("--horizon", type=int, nargs="+", default=[5, 10, 20])
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--cost", type=float, default=0.4)
    ap.add_argument("--benchmark", action="store_true",
                    help="也跑純 ret_20d 對照基準")
    args = ap.parse_args()

    run_backtest(args.start, args.rebalance, args.horizon, args.topk, args.cost,
                 "strategy", "sustainability_score (策略真訊號)")
    if args.benchmark:
        run_backtest(args.start, args.rebalance, args.horizon, args.topk, args.cost,
                     "benchmark", "純 ret_20d 動能 (對照基準)")
