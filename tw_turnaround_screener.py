#!/usr/bin/env python3
"""
台股 turnaround 篩選器：毛利率改善 + 量能放大 + 借券回補

過濾條件（v1，數值可調整）：
  A. 毛利率：近 4 季 GM_Q-0 - GM_Q-3 ≥ +1.5pp 且至少 2 次 QoQ 增長
  B. 量能：近 20 td 平均量 ≥ 近 60 td 平均量 × 1.3
  C. 借券賣出餘額回補：近 10 td 借券賣出餘額均值 ≤ 前 30 td 平均 × 0.95
     （融券餘額僅作參考顯示，不納入過濾條件）
  D. 季線多頭排列：收盤 ≥ 60 日均線 且 60 日均線（vs 10 td 前）上揚

預設掃描 concepts.json 裡 ~190 檔（避免太慢；可改 --universe all 全市場）。

資料來源：
  毛利率：FinMind TaiwanStockFinancialStatements（free tier 可用）
  量能：Yahoo Finance（同 concept_momentum/data_fetcher.py）
  借券賣出餘額：FinMind TaiwanDailyShortSaleBalances 的 SBLShortSalesCurrentDayBalance 欄
                融券餘額（MarginShortSalesCurrentDayBalance）也一併抓但只顯示不過濾
                借券餘額（gross outstanding，TWSE 不公開逐日）改用 借券交易量
                作為 proxy（FinMind TaiwanStockSecuritiesLending）

Usage:
  python3 tw_turnaround_screener.py
  python3 tw_turnaround_screener.py --gm-pp 2.0 --vol-ratio 1.5 --sbl-decline 0.90
  python3 tw_turnaround_screener.py --quiet           # 只列通過的，不秀掃描進度
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
from data_fetcher import fetch_stock, fetch_yahoo  # noqa: E402


def fetch_stock_6mo(code: str) -> dict:
    """Fetch 6 months of TW stock data (vs fetch_stock's 3mo).
    Returns {name, market, rows} or empty dict."""
    for suffix, market in [(".TW", "上市"), (".TWO", "上櫃")]:
        rows = fetch_yahoo(code + suffix, "6mo")
        if rows and len(rows) >= 60:
            # Get name from fetch_stock (does the 3mo lookup but returns metadata)
            info = fetch_stock(code)
            name = info.get("name", code) if info else code
            return {"name": name, "market": market, "rows": rows}
    return {}

CACHE_DIR = os.path.join(HERE, "screener_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def http_json(url: str, retries: int = 2):
    """Simple GET → JSON with retry on rate limit."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(5)
                continue
            return None
        except Exception:
            return None
    return None


# ============================================================
# Filter A: Quarterly gross margin trend
# ============================================================

def fetch_quarterly_margins(code: str, token: str = "") -> list[dict]:
    """Fetch last ~6 quarters of gross margin from FinMind. Cached 30 days.
    Returns [{date: 'YYYY-MM-DD', gross_margin: pct}, ...] sorted ascending."""
    cache_path = os.path.join(CACHE_DIR, f"margin_{code}.json")
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < 30 * 86400:
            with open(cache_path) as f:
                return json.load(f)

    end = datetime.now().strftime("%Y-%m-%d")
    # 18 months covers 6 quarters
    start = (datetime.now() - timedelta(days=540)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "dataset": "TaiwanStockFinancialStatements",
        "data_id": code,
        "start_date": start,
        "end_date": end,
    })
    url = f"https://api.finmindtrade.com/api/v4/data?{params}"
    if token:
        url += f"&token={token}"
    data = http_json(url)
    if not data or data.get("msg") != "success":
        return []

    by_quarter: dict[str, dict] = {}
    for r in data.get("data", []):
        d = r.get("date")
        t = r.get("type")
        v = r.get("value")
        if not (d and t and v is not None):
            continue
        by_quarter.setdefault(d, {})[t] = v

    margins = []
    for d in sorted(by_quarter.keys()):
        q = by_quarter[d]
        rev = q.get("Revenue")
        gp = q.get("GrossProfit")
        if rev and gp and rev > 0:
            margins.append({"date": d, "gross_margin": gp / rev * 100})

    margins = margins[-6:]
    with open(cache_path, "w") as f:
        json.dump(margins, f)
    return margins


def margin_passes(margins: list[dict], min_delta_pp: float, min_qoq_inc: int):
    """Check 4-quarter trend. Returns (bool, dict_of_metrics)."""
    if len(margins) < 4:
        return False, {"reason": "資料不足"}
    last4 = margins[-4:]
    gms = [m["gross_margin"] for m in last4]
    delta = gms[-1] - gms[0]
    qoq_inc = sum(1 for i in range(1, 4) if gms[i] > gms[i - 1])
    metrics = {
        "gms": gms,
        "delta_pp": delta,
        "qoq_inc": qoq_inc,
        "dates": [m["date"] for m in last4],
    }
    return (delta >= min_delta_pp and qoq_inc >= min_qoq_inc), metrics


# ============================================================
# Filter B: Volume surge
# ============================================================

def volume_passes(rows: list[dict], min_ratio: float):
    """rows = Yahoo daily bars. Compare 20d avg vs 60d avg (in 張 = shares/1000)."""
    if len(rows) < 60:
        return False, {"reason": "資料不足"}
    vols = [r.get("volume", 0) for r in rows[-60:]]
    if len(vols) < 60 or sum(vols) == 0:
        return False, {"reason": "成交量缺漏"}
    v20 = sum(vols[-20:]) / 20 / 1000  # 張
    v60 = sum(vols) / 60 / 1000
    ratio = v20 / v60 if v60 > 0 else 0
    return (ratio >= min_ratio), {"v20": v20, "v60": v60, "ratio": ratio}


def ma60_passes(rows: list[dict], accel_days: int = 5):
    """季線多頭排列 + 曲率向上：
    - 收盤 ≥ MA60（季線之上）
    - MA60 斜率為正（rising）
    - MA60 曲率為正：近期斜率 > 較早斜率（accelerating up，2 階導數 > 0）

    用 3 個時點的 MA60 算斜率變化：
      slope_recent  = MA60(today) - MA60(today - accel_days)
      slope_earlier = MA60(today - accel_days) - MA60(today - 2*accel_days)
    曲率向上 = slope_recent > slope_earlier。
    """
    needed = 60 + 2 * accel_days
    if len(rows) < needed:
        return False, {"reason": "資料不足"}
    closes = [r.get("close") for r in rows if r.get("close")]
    if len(closes) < needed:
        return False, {"reason": "資料不足"}

    def ma60_at(offset: int) -> float:
        return sum(closes[-60 - offset: len(closes) - offset if offset > 0 else len(closes)]) / 60

    ma60_today = ma60_at(0)
    ma60_mid = ma60_at(accel_days)
    ma60_old = ma60_at(2 * accel_days)

    slope_recent = ma60_today - ma60_mid
    slope_earlier = ma60_mid - ma60_old

    last_close = closes[-1]
    above_ma = last_close >= ma60_today
    rising = slope_recent > 0
    curving_up = slope_recent > slope_earlier

    return (above_ma and rising and curving_up), {
        "close": last_close,
        "ma60": ma60_today,
        "ma60_mid": ma60_mid,
        "ma60_old": ma60_old,
        "slope_recent": slope_recent,
        "slope_earlier": slope_earlier,
        "above_ma": above_ma,
        "rising": rising,
        "curving_up": curving_up,
        "pct_above": (last_close / ma60_today - 1) * 100 if ma60_today > 0 else 0,
        "pct_slope_recent": (slope_recent / ma60_mid * 100) if ma60_mid > 0 else 0,
        "pct_slope_earlier": (slope_earlier / ma60_old * 100) if ma60_old > 0 else 0,
    }


# ============================================================
# Filter C: SBL outstanding balance decline
# ============================================================

def fetch_lending_flow(code: str, token: str = "") -> dict:
    """Fetch 借券交易（borrow transactions）flow from FinMind. Used as a proxy
    for 借券餘額 (gross outstanding) trend, since TWSE doesn't publicly expose
    per-stock gross outstanding daily.

    Returns {avg10, avg_prior30} (張) — last 10 td vs prior 30 td borrow volume.
    Higher recent = more new borrows being booked (potential future shorts).
    Lower recent = borrowing slowing down."""
    cache_path = os.path.join(CACHE_DIR, f"lend_{code}_{datetime.now().strftime('%Y%m%d')}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=80)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "dataset": "TaiwanStockSecuritiesLending",
        "data_id": code,
        "start_date": start,
        "end_date": end,
    })
    url = f"https://api.finmindtrade.com/api/v4/data?{params}"
    if token:
        url += f"&token={token}"
    data = http_json(url)
    result = {"avg10": 0, "avg_prior30": 0}
    if not data or data.get("msg") != "success":
        with open(cache_path, "w") as f:
            json.dump(result, f)
        return result
    # Aggregate per date
    by_date: dict[str, int] = {}
    for r in data.get("data", []):
        d = r.get("date")
        v = r.get("volume", 0) or 0
        if d:
            by_date[d] = by_date.get(d, 0) + v  # already in 張 (lots)
    if not by_date:
        with open(cache_path, "w") as f:
            json.dump(result, f)
        return result
    sorted_dates = sorted(by_date.keys())
    last10 = sorted_dates[-10:]
    prior30 = sorted_dates[-40:-10] if len(sorted_dates) >= 40 else sorted_dates[:-10]
    if last10:
        result["avg10"] = sum(by_date[d] for d in last10) / len(last10)
    if prior30:
        result["avg_prior30"] = sum(by_date[d] for d in prior30) / len(prior30)
    with open(cache_path, "w") as f:
        json.dump(result, f)
    return result


def fetch_short_balance(code: str, token: str = "") -> list[dict]:
    """Fetch ~80 days of 借券賣出餘額 (SBLShortSalesCurrentDayBalance) from FinMind.
    Also captures 融券 (margin short) for informational display only.
    Cached 1 day. Returns [{date, balance, sbl, margin}, ...] sorted ascending.
    All values in 張. `balance` = sbl (the filter target)."""
    cache_path = os.path.join(CACHE_DIR, f"short_{code}_{datetime.now().strftime('%Y%m%d')}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=80)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "dataset": "TaiwanDailyShortSaleBalances",
        "data_id": code,
        "start_date": start,
        "end_date": end,
    })
    url = f"https://api.finmindtrade.com/api/v4/data?{params}"
    if token:
        url += f"&token={token}"
    data = http_json(url)
    if not data or data.get("msg") != "success":
        return []
    rows = []
    for r in data.get("data", []):
        d = r.get("date")
        sbl = r.get("SBLShortSalesCurrentDayBalance") or 0
        mgn = r.get("MarginShortSalesCurrentDayBalance") or 0
        if d:
            # FinMind values in shares; ÷1000 → 張
            # balance == sbl only (filter target is 借券賣出餘額 specifically)
            rows.append({
                "date": d,
                "balance": sbl / 1000,
                "sbl": sbl / 1000,
                "margin": mgn / 1000,
            })
    rows.sort(key=lambda x: x["date"])
    with open(cache_path, "w") as f:
        json.dump(rows, f)
    return rows


def short_passes(rows: list[dict], decline_ratio: float):
    """Check 借券賣出餘額 declining (only SBL — 融券 excluded by design):
    last 10 td avg / prior 30 td avg <= decline_ratio."""
    if len(rows) < 30:
        return False, {"reason": "資料不足"}
    bals = [r["balance"] for r in rows]
    last10 = bals[-10:]
    prior30 = bals[-40:-10] if len(bals) >= 40 else bals[:-10]
    if not prior30 or sum(prior30) == 0:
        return False, {"reason": "前期資料不足"}
    avg10 = sum(last10) / len(last10)
    avg_prior = sum(prior30) / len(prior30)
    ratio = avg10 / avg_prior if avg_prior > 0 else 1.0
    # Also break down sbl vs margin contribution
    sbl_last = sum(r["sbl"] for r in rows[-10:]) / 10
    sbl_prior = sum(r["sbl"] for r in rows[-40:-10] if "sbl" in r) / max(len(rows[-40:-10]), 1)
    mgn_last = sum(r["margin"] for r in rows[-10:]) / 10
    mgn_prior = sum(r["margin"] for r in rows[-40:-10] if "margin" in r) / max(len(rows[-40:-10]), 1)
    return (ratio <= decline_ratio), {
        "avg10": avg10,
        "avg_prior": avg_prior,
        "ratio": ratio,
        "sbl_last": sbl_last, "sbl_prior": sbl_prior,
        "margin_last": mgn_last, "margin_prior": mgn_prior,
    }


# ============================================================
# Main scan
# ============================================================

def load_universe(universe_arg: str) -> list[tuple[str, str]]:
    """Returns list of (code, name) tuples to scan."""
    if universe_arg == "concepts":
        path = os.path.join(HERE, "concept_momentum", "cache", "concepts.json")
        with open(path) as f:
            c = json.load(f)
        codes = set()
        for v in c["themes"].values():
            codes.update(v.get("stocks", []))
        # Names will be filled when we fetch yahoo
        return [(c, c) for c in sorted(codes)]
    elif universe_arg == "all":
        # TODO: full TWSE/TPEx; for v1 just concepts
        print("--universe all 尚未實作，改用 concepts", file=sys.stderr)
        return load_universe("concepts")
    else:
        # Comma-separated codes
        codes = [c.strip() for c in universe_arg.split(",") if c.strip()]
        return [(c, c) for c in codes]


def main():
    ap = argparse.ArgumentParser(
        description="台股 turnaround 篩選：毛利率改善 + 量能放大 + 借券回補",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--gm-pp", type=float, default=1.5,
                    help="毛利率 4Q 累積增幅門檻（pp，預設 1.5）")
    ap.add_argument("--gm-qoq", type=int, default=2,
                    help="4Q 中至少幾次 QoQ 增長（預設 2/3）")
    ap.add_argument("--vol-ratio", type=float, default=1.3,
                    help="20d/60d 成交量比門檻（預設 1.3）")
    ap.add_argument("--sbl-decline", type=float, default=0.95,
                    help="借券賣出餘額 10d/30d-prior 比門檻（預設 0.95，需 ≤ 此值）")
    ap.add_argument("--ma-accel-days", type=int, default=5,
                    help="季線（MA60）曲率比較窗口（預設 5td：比較近 5 天斜率 vs 前 5 天斜率）")
    ap.add_argument("--universe", default="concepts",
                    help="掃描範圍：concepts(預設) / all / 逗號分隔代號")
    ap.add_argument("--token", default=os.environ.get("FINMIND_TOKEN", ""),
                    help="FinMind token（free tier 也可，但有 rate limit）")
    ap.add_argument("--quiet", action="store_true", help="不顯示掃描進度")
    args = ap.parse_args()

    universe = load_universe(args.universe)
    if not args.quiet:
        print(f"掃描範圍：{len(universe)} 檔", file=sys.stderr)
        print(f"門檻：GM Δ≥{args.gm_pp}pp / QoQ≥{args.gm_qoq} / "
              f"Vol 20d/60d≥{args.vol_ratio} / 借券賣出 10d/prior≤{args.sbl_decline} / "
              f"收盤≥MA60 且 MA60 曲率向上 (近{args.ma_accel_days}td 斜率 > 前{args.ma_accel_days}td 斜率)",
              file=sys.stderr)

    survivors = []
    counts = {"start": len(universe), "A": 0, "AB": 0, "ABC": 0, "ABCD": 0}

    for i, (code, _) in enumerate(universe):
        if not args.quiet and i % 20 == 0:
            print(f"  [{i}/{len(universe)}] 掃描中 ({code})...", file=sys.stderr)

        # Filter A: gross margin
        margins = fetch_quarterly_margins(code, args.token)
        ok_a, m_a = margin_passes(margins, args.gm_pp, args.gm_qoq)
        if not ok_a:
            continue
        counts["A"] += 1

        # Filter B: volume (also need name from Yahoo)
        info = fetch_stock_6mo(code)
        if not info or not info.get("rows"):
            continue
        name = info.get("name", code)
        ok_b, m_b = volume_passes(info["rows"], args.vol_ratio)
        if not ok_b:
            continue
        counts["AB"] += 1

        # Filter C: 借券賣出餘額 (SBL only)
        shorts = fetch_short_balance(code, args.token)
        ok_c, m_c = short_passes(shorts, args.sbl_decline)
        if not ok_c:
            continue
        counts["ABC"] += 1

        # Filter D: 季線多頭排列 + 曲率向上 (close ≥ MA60, slope > 0, curvature > 0)
        ok_d, m_d = ma60_passes(info["rows"], accel_days=args.ma_accel_days)
        if not ok_d:
            continue
        counts["ABCD"] += 1

        # Reference: 借券交易量 trend (proxy for gross 借券餘額)
        lending_flow = fetch_lending_flow(code, args.token)

        survivors.append({
            "code": code, "name": name,
            "margin": m_a, "volume": m_b, "short": m_c, "ma": m_d,
            "lending_flow": lending_flow,
            "market": info.get("market", ""),
        })

    print(f"\n掃描結果：總 {counts['start']} → A:{counts['A']} → A+B:{counts['AB']}"
          f" → A+B+C:{counts['ABC']} → A+B+C+D: {counts['ABCD']} 檔")
    print()
    if not survivors:
        print("無候選 — 可調寬門檻（--gm-pp 1.0 / --vol-ratio 1.2 / --sbl-decline 0.98）")
        return

    # Sort by composite score: margin delta * vol ratio * (1 / short ratio)
    def score(s):
        return (s["margin"]["delta_pp"] * s["volume"]["ratio"]
                / max(s["short"]["ratio"], 0.5))
    survivors.sort(key=score, reverse=True)

    print(f"{'代號':<6}{'名稱':<10}{'GM Δ':<10}{'QoQ':<6}"
          f"{'Vol 20/60':<11}{'借券賣出':<11}{'季線':<10}{'最新 GM':<8}")
    print("-" * 65)
    for s in survivors:
        m = s["margin"]; v = s["volume"]; b = s["short"]; ma = s["ma"]
        latest_gm = m["gms"][-1]
        print(f"{s['code']:<6}{s['name'][:8]:<10}"
              f"+{m['delta_pp']:>4.1f}pp  "
              f"{m['qoq_inc']}/3  "
              f"{v['ratio']:>4.2f}x      "
              f"{b['ratio']:>4.2f}      "
              f"{ma['pct_above']:>+4.1f}%  "
              f"{latest_gm:>5.1f}%")

    # Detail
    print()
    print("【詳細】（filter 只看借券賣出餘額；融券僅顯示參考）")
    for s in survivors:
        m = s["margin"]; v = s["volume"]; b = s["short"]; ma = s["ma"]
        gms_str = " → ".join(f"{g:.1f}%" for g in m["gms"])
        print(f"\n{s['code']} {s['name']} [{s['market']}]")
        print(f"  毛利率 4Q: {gms_str}  (Δ +{m['delta_pp']:.1f}pp, {m['qoq_inc']}/3 QoQ ↑)")
        print(f"  量能：20d {v['v20']:.0f} 張 vs 60d {v['v60']:.0f} 張  →  "
              f"{v['ratio']:.2f}x")
        print(f"  借券賣出：近 10d 均 {b['avg10']:.0f} 張 vs 前 30d 均 {b['avg_prior']:.0f} 張"
              f"  →  {b['ratio']:.2f}x ({(b['ratio']-1)*100:+.1f}%)")
        print(f"  季線：收盤 {ma['close']:.2f} vs MA60 {ma['ma60']:.2f}"
              f" ({ma['pct_above']:+.1f}%)")
        print(f"     ├ 近 {args.ma_accel_days}td 斜率: {ma['pct_slope_recent']:+.2f}%"
              f"  vs 前 {args.ma_accel_days}td 斜率: {ma['pct_slope_earlier']:+.2f}%"
              f"  → 曲率 {'+' if ma['curving_up'] else '−'}")
        # margin (融券) display only
        mgn_change = ((b['margin_last'] / b['margin_prior'] - 1) * 100
                      if b['margin_prior'] > 0 else 0)
        print(f"  （參考）融券：近 10d 均 {b['margin_last']:.0f} 張 vs 前 30d 均 "
              f"{b['margin_prior']:.0f} 張  →  {mgn_change:+.1f}%")
        # 借券交易量 (proxy for gross 借券餘額 trend)
        lf = s.get("lending_flow", {"avg10": 0, "avg_prior30": 0})
        if lf["avg_prior30"] > 0:
            lf_change = (lf["avg10"] / lf["avg_prior30"] - 1) * 100
            print(f"  （參考）借券交易量：近 10d 均 {lf['avg10']:.0f} 張 vs 前 30d 均 "
                  f"{lf['avg_prior30']:.0f} 張  →  {lf_change:+.1f}%")
        else:
            print(f"  （參考）借券交易量：資料不足（近 10d 均 {lf['avg10']:.0f} 張）")


if __name__ == "__main__":
    main()
