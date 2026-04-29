#!/usr/bin/env python3
"""
台股概念 vs 美股 peer 相關性查詢

對指定的台股概念，計算其成員與對應美股 peer 的近 N 天 β 調整後相關係數。
找出真的跟著美股 narrative 跑的標的，與只是名字像但實際走自己路的。

公式：
  TPE 股票報酬 = 對 ^TWII 做 β 調整後的 excess returns
  US 股票報酬  = 對 ^GSPC 做 β 調整後的 excess returns
  correlation = Pearson(TPE_excess, US_excess)，以 TPE 日期為基準
                並對齊到「TPE D 配對 US D-1 之最近交易日」（TPE 對美股的反應有 1 天時差）

correlation 解讀：
  > 0.6  強相關（跟著美股動）
  0.3-0.6 中等
  < 0.3  弱相關（自己走自己的路）
  < 0    反向（少見，多半是雜訊）

Usage:
  python3 tw_us_correlation.py ASIC自研晶片
  python3 tw_us_correlation.py AI伺服器_ODM --window 90
  python3 tw_us_correlation.py NVIDIA供應鏈 --peer NVDA
  python3 tw_us_correlation.py --list   # 列出所有概念與預設 peer
"""

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
from data_fetcher import fetch_stock, fetch_yahoo  # noqa: E402

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


def daily_returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes)) if closes[i - 1] > 0]


def correlation(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 5:
        return 0.0
    xs, ys = xs[-n:], ys[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx > 0 and dy > 0 else 0.0


def linear_beta(stock: list[float], market: list[float]) -> float:
    n = min(len(stock), len(market))
    if n < 10:
        return 1.0
    xs = market[-n:]
    ys = stock[-n:]
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    varx = sum((x - mx) ** 2 for x in xs)
    return cov / varx if varx > 0 else 1.0


def excess_returns(stock: list[float], market: list[float]) -> list[float]:
    if len(stock) != len(market) or len(stock) < 10:
        return stock
    b = linear_beta(stock, market)
    return [s - b * m for s, m in zip(stock, market)]


def fetch_excess_series(ticker: str, market_ticker: str | None,
                         range_str: str = "6mo"):
    """Fetch ticker's returns. If market_ticker given, β-adjust to excess returns.
    Returns dict {date_yyyymmdd: return}."""
    rows = fetch_yahoo(ticker, range_str)
    if not rows:
        return {}
    closes = [r["close"] for r in rows if r.get("close")]
    if len(closes) < 30:
        return {}
    rets = daily_returns(closes)
    dates = [r["date"] for r in rows if r.get("close")][1:]
    if market_ticker is None:
        return dict(zip(dates, rets))

    market_rows = fetch_yahoo(market_ticker, range_str)
    if not market_rows:
        return dict(zip(dates, rets))
    m_closes = [r["close"] for r in market_rows if r.get("close")]
    m_rets = daily_returns(m_closes)
    m_dates = [r["date"] for r in market_rows if r.get("close")][1:]
    m_map = dict(zip(m_dates, m_rets))

    paired = [(rets[i], m_map[d]) for i, d in enumerate(dates) if d in m_map]
    if len(paired) < 10:
        return dict(zip(dates, rets))
    rs = [p[0] for p in paired]
    ms = [p[1] for p in paired]
    ex = excess_returns(rs, ms)
    ds = [d for d in dates if d in m_map]
    return dict(zip(ds, ex))


def fetch_tw_excess(code: str, raw: bool = False, range_str: str = "6mo"):
    """Fetch TPE stock's returns. β-adjust vs ^TWII unless raw=True.
    Returns ({date: return}, name)."""
    rows = []
    name = code
    for suffix in [".TW", ".TWO"]:
        rows = fetch_yahoo(code + suffix, range_str)
        if rows:
            # We need the company name; fetch_stock returns it. Run once for name.
            info = fetch_stock(code)
            if info:
                name = info.get("name", code)
            break
    if not rows or len(rows) < 30:
        return {}, name
    closes = [r["close"] for r in rows if r.get("close")]
    rets = daily_returns(closes)
    dates = [r["date"] for r in rows if r.get("close")][1:]
    if raw:
        return dict(zip(dates, rets)), name

    twi_rows = fetch_yahoo("^TWII", range_str)
    twi_closes = [r["close"] for r in twi_rows if r.get("close")]
    twi_rets = daily_returns(twi_closes)
    twi_dates = [r["date"] for r in twi_rows if r.get("close")][1:]
    twi_raw = dict(zip(twi_dates, twi_rets))

    paired = [(rets[i], twi_raw[d]) for i, d in enumerate(dates) if d in twi_raw]
    if len(paired) < 10:
        return dict(zip(dates, rets)), name
    rs = [p[0] for p in paired]
    ms = [p[1] for p in paired]
    ex = excess_returns(rs, ms)
    ds = [d for d in dates if d in twi_raw]
    return dict(zip(ds, ex)), name


def lagged_pairs(tw_map: dict, us_map: dict) -> list[tuple[float, float]]:
    """Pair TPE date D with the latest US date STRICTLY LESS THAN D
    (TPE D session reacts to US D-1 close, never US D since US session
    for D hasn't happened yet during TPE D's session)."""
    us_dates_sorted = sorted(us_map.keys())
    pairs = []
    for d in sorted(tw_map.keys()):
        # binary-search-ish: find largest us date < d
        prior = [ud for ud in us_dates_sorted if ud < d]
        if not prior:
            continue
        ud = prior[-1]
        pairs.append((tw_map[d], us_map[ud]))
    return pairs


def main():
    parser = argparse.ArgumentParser(
        description="台股概念 vs 美股 peer 相關性查詢",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("concept", nargs="?",
                        help="台股概念 key（例：ASIC自研晶片）。省略+--peer 即進入掃描全市場模式。")
    parser.add_argument("--window", type=int, default=60,
                        help="相關係數計算視窗天數（預設 60）")
    parser.add_argument("--peer", help="美股 peer ticker（覆蓋預設或啟用全掃模式）")
    parser.add_argument("--top", type=int, default=20, help="顯示前 N 檔")
    parser.add_argument("--raw", action="store_true",
                        help="使用原始報酬（不做 β 調整）— 直觀的「NVDA 漲台股也漲」"
                             "視角；預設 β 調整則只看「扣除大盤後仍同步」的部分")
    parser.add_argument("--scan", action="store_true",
                        help="掃描全部 34 個概念裡的所有股票，跟指定 --peer 算相關性。"
                             "需搭配 --peer。省略 concept 直接 --peer X 也會自動進入掃全模式。")
    parser.add_argument("--list", action="store_true", help="列出所有概念與預設 peer")
    args = parser.parse_args()

    # Load concepts.json
    concepts_path = os.path.join(HERE, "concept_momentum", "cache", "concepts.json")
    with open(concepts_path) as f:
        concepts = json.load(f)

    if args.list:
        print("可用概念與對應美股 peer：\n")
        for k, v in concepts["themes"].items():
            peers = US_PEERS.get(k, ["(no mapping)"])
            print(f"  {k:24s} ({len(v['stocks'])}檔) → {','.join(peers)}")
        return

    # Decide mode: scan-all vs concept-scoped
    scan_mode = args.scan or (not args.concept and args.peer)
    if scan_mode and not args.peer:
        print("--scan 必須搭配 --peer 指定一個美股 ticker")
        sys.exit(1)

    if scan_mode:
        # Build deduplicated stock list across all concepts, plus a code→concepts map
        code_to_concepts: dict[str, list[str]] = {}
        for k, v in concepts["themes"].items():
            for s in v.get("stocks", []):
                code_to_concepts.setdefault(s, []).append(k)
        stocks = list(code_to_concepts.keys())
        us_peers = [args.peer]
        title = f"全市場 ({len(stocks)} 檔)"
    else:
        if not args.concept:
            parser.print_help()
            sys.exit(1)
        if args.concept not in concepts["themes"]:
            print(f"概念 '{args.concept}' 不存在")
            print("用 --list 看所有可用概念")
            sys.exit(1)
        theme = concepts["themes"][args.concept]
        stocks = theme["stocks"]
        code_to_concepts = None
        if args.peer:
            us_peers = [args.peer]
        else:
            us_peers = US_PEERS.get(args.concept, [])
            if not us_peers:
                print(f"概念 '{args.concept}' 沒有預設美股 peer。用 --peer 指定")
                sys.exit(1)
        title = theme["name_zh"]

    mode = "原始報酬（不扣大盤 β）" if args.raw else "β 調整：TPE 對 ^TWII / US 對 ^GSPC"
    print(f"=== {title} vs {','.join(us_peers)} ===")
    print(f"視窗：{args.window} 個 TPE 交易日 | {mode} | 配對：TPE D ↔ US D-1\n")

    # Auto-extend Yahoo range to cover the requested window (default 6mo ≈ 130 td)
    yahoo_range = "1y" if args.window > 100 else "6mo"

    market_us = None if args.raw else "^GSPC"
    us_excess = {}
    for p in us_peers:
        ex = fetch_excess_series(p, market_us, yahoo_range)
        if ex:
            us_excess[p] = ex
        else:
            print(f"  ⚠ 抓不到 {p} 資料")

    if not us_excess:
        print("沒有任何美股 peer 資料可用")
        sys.exit(1)

    # Fetch each TPE stock, compute lagged correlation per peer
    rows_out = []
    for code in stocks:
        tw_map, name = fetch_tw_excess(code, raw=args.raw, range_str=yahoo_range)
        if not tw_map:
            continue
        # Take last `window` days
        recent_dates = sorted(tw_map.keys())[-args.window:]
        tw_recent = {d: tw_map[d] for d in recent_dates}
        corrs = {}
        for p in us_peers:
            us_recent_dates = sorted(us_excess[p].keys())[-(args.window + 5):]
            us_recent = {d: us_excess[p][d] for d in us_recent_dates}
            pairs = lagged_pairs(tw_recent, us_recent)
            if len(pairs) < 10:
                corrs[p] = None
                continue
            xs = [pp[0] for pp in pairs]
            ys = [pp[1] for pp in pairs]
            corrs[p] = correlation(xs, ys)
        rows_out.append((code, name, corrs))

    if not rows_out:
        print("無可用資料")
        return

    # Sort by max correlation across peers
    def max_corr(row):
        cs = [c for c in row[2].values() if c is not None]
        return max(cs) if cs else -2

    rows_out.sort(key=max_corr, reverse=True)

    # Print table
    name_w = 12
    col_w = 9
    header = f"{'代號':<8}{'名稱':<{name_w}}"
    for p in us_peers:
        header += f"{p:<{col_w}}"
    header += "max"
    if scan_mode:
        header += "  概念"
    print(header)
    print("-" * (8 + name_w + col_w * len(us_peers) + 6 + (20 if scan_mode else 0)))

    for code, name, corrs in rows_out[:args.top]:
        line = f"{code:<8}{name[:name_w-1]:<{name_w}}"
        cs_vals = []
        for p in us_peers:
            c = corrs.get(p)
            if c is None:
                line += f"{'--':<{col_w}}"
            else:
                line += f"{c:+.2f}    "[:col_w]
                cs_vals.append(c)
        if cs_vals:
            mc = max(cs_vals)
            tag = "🟢" if mc >= 0.6 else "🟡" if mc >= 0.3 else "⚪"
            line += f" {tag}{mc:+.2f}"
        if scan_mode and code_to_concepts:
            cc = code_to_concepts.get(code, [])
            cc_short = "/".join([k.split("_")[0] for k in cc[:2]])
            line += f"  {cc_short}"
        print(line)

    print(f"\n🟢 ≥0.6 強相關 / 🟡 0.3–0.6 中等 / ⚪ <0.3 弱相關")


if __name__ == "__main__":
    main()
