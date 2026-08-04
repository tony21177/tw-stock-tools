#!/usr/bin/env python3
"""
台股概念 vs 美股 peer 相關性查詢(v2 演算法,2026-08-04)

對指定的台股概念(或全市場),計算成員與美股 peer 的 β 調整後相關係數。
找出真的跟著美股 narrative 跑的標的,與只是名字像但實際走自己路的。

v2 演算法(詳細說明見 docs/tools/us-correlation.md):
  1. 還原價:報酬一律用 Yahoo adjclose(除權息還原),消除除息日假報酬
  2. 缺值防護:相鄰兩筆收盤相隔 >5 個日曆日(停牌)的報酬捨棄
  3. β 同視窗:β 只用「相關係數視窗內」的資料估,不用全抓取範圍(regime 對齊)
  4. 美股雙因子:excess = r − b1·SPX − b2·NDXresid(NDX 對 SPX 迴歸的殘差,
     正交化科技因子;非科技股 b2≈0 自動退化為單因子)。台股仍對 ^TWII 單因子
     (櫃買指數 ^TWOII Yahoo 資料落後數週,不可用,上櫃股照用 ^TWII)
  5. Winsorize:相關係數計算前,兩序列各自截尾在 mean±3σ,防單日暴漲暴跌
     (財報日/漲跌停共現)綁架 Pearson
  6. 顯著性+穩定性:輸出配對數 n、Fisher 95% CI、前半/後半視窗分算 r;
     |前半−後半| > 0.20 或正負相反標 ⚠(相關可能由短期巧合貢獻)
  7. 時差配對:TPE D ↔ 嚴格小於 D 的最近美股交易日(台股反應美股前一晚)

correlation 解讀:
  > 0.6  強相關(跟著美股動)  0.3-0.6 中等  < 0.3 弱  < 0 反向(多為雜訊)
  ⚠ = 前後半視窗不一致,短期巧合風險;n < 100 時 CI 很寬,r < 0.3 基本不顯著

Usage:
  python3 tw_us_correlation.py ASIC自研晶片
  python3 tw_us_correlation.py AI伺服器_ODM --window 90
  python3 tw_us_correlation.py NVIDIA供應鏈 --peer NVDA
  python3 tw_us_correlation.py --peer NVDA          # 全市場掃描
  python3 tw_us_correlation.py --list
"""

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
import data_fetcher  # noqa: E402

# Concept → US peer tickers. Curated to match the dominant US narrative driver
# for each TW concept. Edit / add as themes evolve.
US_PEERS = {
    "ASIC自研晶片":      ["AVGO", "MRVL", "ALAB"],
    "矽智財_IP":         ["ARM", "SNPS", "CDNS"],
    "AI伺服器_ODM":      ["DELL", "HPE", "SMCI"],
    "AI伺服器_電源":      ["VRT", "ETN", "GEV"],
    "AI伺服器_線材連接":   ["APH", "TEL"],
    "NVIDIA供應鏈":      ["NVDA"],
    "HBM記憶體":         ["MU"],
    "先進封裝_CoWoS":     ["AMKR", "TSM"],
    "液冷散熱":           ["VRT"],
    "CPO_矽光子":        ["ANET", "CIEN", "COHR"],
    "半導體設備":         ["AMAT", "LRCX", "KLAC", "ASML"],
    "量子運算":           ["IBM", "IONQ", "RGTI"],
    "軍工":              ["LMT", "RTX", "NOC"],
    "電動車_EV":         ["TSLA", "RIVN"],
    "SiC功率元件":        ["ON", "WOLF"],
    "重電_電網":          ["ETN", "GEV", "HUBB"],
    "晶圓代工":           ["TSM"],
    "ADAS_智駕":         ["MBLY"],
    "車用電子":           ["MBLY", "APH"],
    "Edge_AI":          ["AMD", "QCOM"],
    "蘋果概念":           ["AAPL"],
    "鋰電池_儲能":        ["TSLA", "ENPH"],
    "低軌衛星":           ["IRDM", "GSAT"],
    "綠能_太陽能":        ["FSLR", "ENPH"],
    "無人機":             ["AVAV", "KTOS"],
    "機器人_人形":        ["TSLA"],   # Optimus narrative
    "機器人_工業自動化":   ["ROK", "EMR"],
    "PCB_ABF":          ["AVGO"],
    "玻璃基板_TGV":       ["INTC", "AVGO"],
    "被動元件":           ["VSH"],
    "CXO_生技代工":       ["LLY"],
    "光學鏡頭":           ["GLW"],
    "折疊螢幕":           ["AAPL"],
}


# ── 當日記憶化 fetch(^TWII/^GSPC/^NDX 只抓一次;掃描時省一半請求) ──
_memo: dict = {}


def fetch_yahoo(symbol: str, range_str: str = "3mo") -> list[dict]:
    k = (symbol, range_str)
    if k not in _memo:
        _memo[k] = data_fetcher.fetch_yahoo(symbol, range_str)
    return _memo[k]


_names_cache: dict = {}


def stock_name(code: str) -> str:
    """本地名稱快取(TWSE ISIN + FinMind TaiwanStockInfo),不打 Yahoo。"""
    if not _names_cache:
        try:
            from stock_names import get_name as _gn
            _names_cache["_gn"] = _gn
        except Exception:
            _names_cache["_gn"] = None
        try:
            fm = json.load(open(os.path.join(
                HERE, "concept_momentum", "cache", "finmind_names.json")))
            _names_cache["_fm"] = fm.get("names", fm) if isinstance(fm, dict) else {}
        except Exception:
            _names_cache["_fm"] = {}
    gn = _names_cache["_gn"]
    if gn:
        n = gn(code)
        if n and n != code:
            return n
    return _names_cache["_fm"].get(code, code)


# ── 報酬與統計基元 ─────────────────────────────────────────────
def dated_returns(rows: list[dict]) -> dict:
    """{date: return}。用還原價 adj;相鄰兩筆相隔 >5 日曆日(停牌)捨棄該筆報酬。"""
    from datetime import datetime as _dt
    out = {}
    prev_c, prev_d = None, None
    for r in rows:
        c = r.get("adj") or r.get("close")
        d = r.get("date")
        if not c or not d:
            continue
        if prev_c and prev_c > 0:
            gap = (_dt.strptime(d, "%Y%m%d") - _dt.strptime(prev_d, "%Y%m%d")).days
            if gap <= 5:
                out[d] = (c - prev_c) / prev_c
        prev_c, prev_d = c, d
    return out


def winsorize(xs: list[float], k: float = 3.0) -> list[float]:
    n = len(xs)
    if n < 5:
        return xs
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / n)
    if sd == 0:
        return xs
    lo, hi = m - k * sd, m + k * sd
    return [min(max(x, lo), hi) for x in xs]


def pearson(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


# 向後相容別名(app.py 舊呼叫)
correlation = pearson


def corr_stats(xs: list[float], ys: list[float]) -> dict | None:
    """winsorize 後的 Pearson + n + Fisher 95% CI + 前/後半視窗 r + 穩定旗標。"""
    n = min(len(xs), len(ys))
    if n < 10:
        return None
    xs, ys = winsorize(xs[-n:]), winsorize(ys[-n:])
    r = pearson(xs, ys)
    half = n // 2
    r1 = pearson(xs[:half], ys[:half]) if half >= 10 else None
    r2 = pearson(xs[half:], ys[half:]) if half >= 10 else None
    ci_lo = ci_hi = None
    if n > 3 and abs(r) < 1:
        z = 0.5 * math.log((1 + r) / (1 - r))
        se = 1 / math.sqrt(n - 3)
        ci_lo = math.tanh(z - 1.96 * se)
        ci_hi = math.tanh(z + 1.96 * se)
    unstable = (r1 is not None and r2 is not None
                and (abs(r1 - r2) > 0.20 or (r1 * r2 < 0 and max(abs(r1), abs(r2)) > 0.1)))
    return {"r": r, "n": n, "r_front": r1, "r_back": r2,
            "ci_lo": ci_lo, "ci_hi": ci_hi, "unstable": bool(unstable)}


def beta_residual(stock: dict, factors: list[dict], window: int) -> dict:
    """多因子 OLS 殘差(逐因子 Gram-Schmidt 已由呼叫端保證正交或近正交)。
    只用日期交集的最近 window 筆估 β。回傳 {date: residual}。"""
    dates = sorted(set(stock) & set.intersection(*[set(f) for f in factors]))         if factors else sorted(stock)
    dates = dates[-window:]
    if len(dates) < 30 or not factors:
        return {d: stock[d] for d in sorted(stock)[-window:]}
    ys = [stock[d] for d in dates]
    betas = []
    resid = ys[:]
    for f in factors:
        fs = [f[d] for d in dates]
        mf = sum(fs) / len(fs)
        mr = sum(resid) / len(resid)
        var = sum((x - mf) ** 2 for x in fs)
        cov = sum((x - mf) * (y - mr) for x, y in zip(fs, resid))
        b = cov / var if var > 0 else 0.0
        betas.append(b)
        resid = [y - b * x for y, x in zip(resid, fs)]
    return dict(zip(dates, resid))


# ── 因子序列 ──────────────────────────────────────────────────
def us_factors(range_str: str, window: int) -> list[dict]:
    """[SPX 報酬, NDX 正交殘差]。NDX 抓不到時退化為單因子。"""
    spx = dated_returns(fetch_yahoo("^GSPC", range_str))
    if not spx:
        return []
    ndx = dated_returns(fetch_yahoo("^NDX", range_str))
    if not ndx:
        return [spx]
    ndx_resid = beta_residual(ndx, [spx], window + 60)
    return [spx, ndx_resid]


def fetch_us_excess(ticker: str, range_str: str, window: int,
                    raw: bool = False) -> dict:
    rows = fetch_yahoo(ticker, range_str)
    rets = dated_returns(rows)
    if not rets or len(rets) < 30:
        return {}
    if raw:
        return rets
    factors = us_factors(range_str, window)
    if not factors:
        return rets
    return beta_residual(rets, factors, window)


def fetch_tw_excess(code: str, raw: bool = False, range_str: str = "6mo",
                    window: int = 240):
    """回傳 ({date: excess_return}, 名稱)。β 對 ^TWII 同視窗估。"""
    rows = []
    for suffix in [".TW", ".TWO"]:
        rows = fetch_yahoo(code + suffix, range_str)
        if rows:
            break
    name = stock_name(code)
    rets = dated_returns(rows)
    if not rets or len(rets) < 30:
        return {}, name
    if raw:
        return rets, name
    twii = dated_returns(fetch_yahoo("^TWII", range_str))
    if not twii:
        return rets, name
    return beta_residual(rets, [twii], window), name


def lagged_pairs(tw_map: dict, us_map: dict) -> list[tuple[float, float]]:
    """TPE D 配對「嚴格小於 D 的最近美股交易日」(台股反應美股前一晚)。"""
    us_sorted = sorted(us_map.keys())
    pairs = []
    import bisect
    for d in sorted(tw_map.keys()):
        i = bisect.bisect_left(us_sorted, d)
        if i == 0:
            continue
        pairs.append((tw_map[d], us_map[us_sorted[i - 1]]))
    return pairs


# ── 共用計算入口(CLI 與網頁共用) ─────────────────────────────
def yahoo_range_for(window: int) -> str:
    return "2y" if window > 200 else ("1y" if window > 100 else "6mo")


def compute_correlations(peers: list[str], stocks: list[str], window: int,
                         raw: bool = False,
                         code_to_concepts: dict | None = None,
                         progress=None) -> list[dict]:
    """回傳 [{code,name,concepts,corrs:{peer:{r,n,ci_lo,ci_hi,r_front,r_back,unstable}}}]
    依 max r 降冪。"""
    range_str = yahoo_range_for(window)
    us_excess = {}
    for p in peers:
        ex = fetch_us_excess(p, range_str, window, raw=raw)
        if ex:
            us_excess[p] = ex
    if not us_excess:
        raise RuntimeError("抓不到任何美股 peer 資料(代號打錯?)")
    rows = []
    for i, code in enumerate(stocks):
        tw_map, name = fetch_tw_excess(code, raw=raw, range_str=range_str,
                                       window=window)
        if not tw_map:
            continue
        recent = sorted(tw_map.keys())[-window:]
        twr = {d: tw_map[d] for d in recent}
        corrs = {}
        for p in peers:
            if p not in us_excess:
                corrs[p] = None
                continue
            usd = sorted(us_excess[p].keys())[-(window + 5):]
            pairs = lagged_pairs(twr, {d: us_excess[p][d] for d in usd})
            corrs[p] = corr_stats([x for x, _ in pairs], [y for _, y in pairs])
        rows.append({"code": code, "name": name, "corrs": corrs,
                     "concepts": (code_to_concepts or {}).get(code, [])})
        if progress and (i + 1) % 25 == 0:
            progress(i + 1, len(stocks))

    def max_r(row):
        rs = [c["r"] for c in row["corrs"].values() if c]
        return max(rs) if rs else -2
    rows.sort(key=max_r, reverse=True)
    return rows


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("concept", nargs="?",
                        help="台股概念 key(例:ASIC自研晶片)。省略+--peer 即全掃。")
    parser.add_argument("--window", type=int, default=240,
                        help="相關係數視窗天數(預設 240 ≈ 1 年)")
    parser.add_argument("--peer", help="美股 peer ticker(覆蓋預設或啟用全掃)")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--raw", action="store_true",
                        help="原始報酬(不做 β 調整)")
    parser.add_argument("--scan", action="store_true",
                        help="全市場掃描,需搭配 --peer(省略 concept 亦自動全掃)")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    concepts_path = os.path.join(HERE, "concept_momentum", "cache", "concepts.json")
    with open(concepts_path) as f:
        concepts = json.load(f)

    if args.list:
        print("可用概念與對應美股 peer:\n")
        for k, v in concepts["themes"].items():
            peers = US_PEERS.get(k, ["(no mapping)"])
            print(f"  {k:24s} ({len(v['stocks'])}檔) → {','.join(peers)}")
        return

    scan_mode = args.scan or (not args.concept and args.peer)
    if scan_mode and not args.peer:
        print("--scan 必須搭配 --peer")
        sys.exit(1)

    if scan_mode:
        code_to_concepts: dict = {}
        for k, v in concepts["themes"].items():
            for s in v.get("stocks", []):
                code_to_concepts.setdefault(s, []).append(k)
        stocks = list(code_to_concepts.keys())
        us_peers = [p for p in args.peer.upper().split(",") if p]
        title = f"全市場 ({len(stocks)} 檔)"
    else:
        if not args.concept:
            parser.print_help()
            sys.exit(1)
        if args.concept not in concepts["themes"]:
            print(f"概念 '{args.concept}' 不存在(--list 看全部)")
            sys.exit(1)
        theme = concepts["themes"][args.concept]
        stocks = theme["stocks"]
        code_to_concepts = None
        us_peers = ([p for p in args.peer.upper().split(",") if p]
                    if args.peer else US_PEERS.get(args.concept, []))
        if not us_peers:
            print(f"概念 '{args.concept}' 沒有預設 peer,用 --peer 指定")
            sys.exit(1)
        title = theme["name_zh"]

    mode = "原始報酬(不扣大盤)" if args.raw else \
        "β 調整:TPE−^TWII / US−(^GSPC+^NDX殘差) 同視窗估;winsorize ±3σ"
    print(f"=== {title} vs {','.join(us_peers)} ===")
    print(f"視窗:{args.window} TPE 交易日 | {mode} | 配對:TPE D ↔ US D-1\n")

    rows = compute_correlations(us_peers, stocks, args.window, raw=args.raw,
                                code_to_concepts=code_to_concepts,
                                progress=lambda i, n: print(f"  …{i}/{n}", flush=True)
                                if scan_mode else None)
    if not rows:
        print("無可用資料")
        return

    name_w, col_w = 12, 10
    header = f"{'代號':<8}{'名稱':<{name_w}}"
    for p in us_peers:
        header += f"{p:<{col_w}}"
    header += "max     [95% CI]        前/後半   n"
    if scan_mode:
        header += "   概念"
    print(header)
    print("-" * (8 + name_w + col_w * len(us_peers) + 42 + (20 if scan_mode else 0)))
    for row in rows[:args.top]:
        line = f"{row['code']:<8}{row['name'][:name_w-1]:<{name_w}}"
        best = None
        for p in us_peers:
            c = row["corrs"].get(p)
            if c is None:
                line += f"{'--':<{col_w}}"
                continue
            flag = "⚠" if c["unstable"] else " "
            line += f"{c['r']:+.2f}{flag}    "[:col_w]
            if best is None or c["r"] > best["r"]:
                best = c
        if best:
            mc = best["r"]
            tag = "🟢" if mc >= 0.6 else "🟡" if mc >= 0.3 else "⚪"
            ci = (f"[{best['ci_lo']:+.2f},{best['ci_hi']:+.2f}]"
                  if best["ci_lo"] is not None else "")
            fb = (f"{best['r_front']:+.2f}/{best['r_back']:+.2f}"
                  if best["r_front"] is not None else "—")
            line += f" {tag}{mc:+.2f} {ci:<15} {fb:<9} {best['n']}"
        if scan_mode and code_to_concepts:
            cc = code_to_concepts.get(row["code"], [])
            line += "  " + "/".join(k.split("_")[0] for k in cc[:2])
        print(line)

    print("\n🟢 ≥0.6 強 / 🟡 0.3-0.6 中 / ⚪ <0.3 弱 | "
          "⚠ 前/後半視窗不一致(短期巧合風險) | CI 含 0 = 統計上不顯著")


if __name__ == "__main__":
    main()
