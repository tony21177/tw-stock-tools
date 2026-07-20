#!/usr/bin/env python3
"""單檔「兩波下殺」籌碼對比 — 價格 + 借券賣出餘額(SBL) + 外資累計淨額 + 融資餘額.

給定股票代號與兩段時期，各拆「下跌段 / 築底(反彈)段」，比對四線動向。
資料來源 FinMind（皆有長歷史）：
  - 價格 TaiwanStockPrice（close）
  - 借券 TaiwanDailyShortSaleBalances（SBLShortSalesCurrentDayBalance，單位股 → /1000 張）
  - 法人 TaiwanStockInstitutionalInvestorsBuySell（外資 buy/sell，單位股 → /1000 張）
  - 融資 TaiwanStockMarginPurchaseShortSale（MarginPurchaseTodayBalance，**已是張、勿 /1000**）

⚠ 單位教訓（2026-07-20）：融資 balance 已是「張」，借券/法人是「股」。
⚠ 分點（券商分點）限制：TWSE/TPEx 只提供當日、無歷史 API，本頁不含分點。
"""
import json
import os
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CACHE_DIR = os.path.join(HERE, "cache", "chip_episode")
_FOREIGN_NAMES = ("Foreign_Investor", "Foreign_Dealer_Self")


def _token() -> str:
    import sys
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        import subprocess
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    except Exception:
        pass
    return ""


def fetch_series(code: str, start: str, end: str, token: str) -> dict:
    """回 {price:{d:close}, sbl:{d:張}, fnet:{d:張}, margin:{d:張}}（日, YYYY-MM-DD）。

    以 (code, start, end) 快取 1 天，避免每次開頁都打 FinMind。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    cache = os.path.join(CACHE_DIR, f"{code}_{start}_{end}_{today}.json")
    if os.path.exists(cache):
        try:
            with open(cache) as f:
                return json.load(f)
        except Exception:
            pass

    import sys
    sys.path.insert(0, REPO)
    import finmind_client as fc

    price = {r["date"]: r["close"]
             for r in fc.fetch_stock_price(code, start, end, token)
             if r.get("close")}
    sbl_rows = fc._call("TaiwanDailyShortSaleBalances",
                        {"data_id": code, "start_date": start,
                         "end_date": end}, token)
    sbl = {r["date"]: (r.get("SBLShortSalesCurrentDayBalance") or 0) / 1000
           for r in sbl_rows}
    inst = fc._call("TaiwanStockInstitutionalInvestorsBuySell",
                    {"data_id": code, "start_date": start,
                     "end_date": end}, token)
    fnet: dict[str, float] = defaultdict(float)
    for r in inst:
        if r.get("name") in _FOREIGN_NAMES:
            fnet[r["date"]] += ((r.get("buy", 0) or 0)
                                - (r.get("sell", 0) or 0)) / 1000
    mgn = fc._call("TaiwanStockMarginPurchaseShortSale",
                   {"data_id": code, "start_date": start,
                    "end_date": end}, token)
    # ⚠ 融資 balance 已是「張」— 不除 1000
    margin = {r["date"]: (r.get("MarginPurchaseTodayBalance") or 0)
              for r in mgn}

    out = {"price": price, "sbl": sbl, "fnet": dict(fnet), "margin": margin}
    try:
        with open(cache, "w") as f:
            json.dump(out, f)
    except Exception:
        pass
    return out


def _trough(price: dict, a: str, b: str) -> tuple[str, float]:
    ds = [d for d in sorted(price) if a <= d <= b]
    if not ds:
        return "", 0.0
    lo = min(ds, key=lambda d: price[d])
    return lo, price[lo]


def _seg_stats(s: dict, a: str, b: str) -> dict:
    """一個時間區段 [a,b] 的四線統計。"""
    price, sbl, fnet, margin = (s["price"], s["sbl"], s["fnet"], s["margin"])
    ds = [d for d in sorted(price) if a <= d <= b]
    if not ds:
        return {}
    d0, d1 = ds[0], ds[-1]

    def _bal(series, d):
        # 取 ≤ d 的最後一筆（該線可能缺當日）
        keys = [k for k in series if k <= d]
        return series[max(keys)] if keys else None

    sbl0, sbl1 = _bal(sbl, d0), _bal(sbl, d1)
    mgn0, mgn1 = _bal(margin, d0), _bal(margin, d1)
    sbl_win = {k: v for k, v in sbl.items() if a <= k <= b}
    mgn_win = {k: v for k, v in margin.items() if a <= k <= b}
    return {
        "start": d0, "end": d1,
        "px0": price[d0], "px1": price[d1],
        "px_chg_pct": round((price[d1] / price[d0] - 1) * 100, 1),
        "f_cum": round(sum(v for k, v in fnet.items() if a <= k <= b), 0),
        "sbl0": round(sbl0, 0) if sbl0 is not None else None,
        "sbl1": round(sbl1, 0) if sbl1 is not None else None,
        "sbl_peak": round(max(sbl_win.values()), 0) if sbl_win else None,
        "mgn0": mgn0, "mgn1": mgn1,
        "mgn_peak": max(mgn_win.values()) if mgn_win else None,
        "mgn_low": min(mgn_win.values()) if mgn_win else None,
    }


def build_episode(code: str, ep_start: str, ep_end: str,
                  s: dict) -> dict:
    """一波：自動找區段內低點 → 拆下跌段 / 築底反彈段。"""
    peak_d, peak_px = "", 0.0
    ds = [d for d in sorted(s["price"]) if ep_start <= d <= ep_end]
    if ds:
        peak_d = max(ds, key=lambda d: s["price"][d])
        peak_px = s["price"][peak_d]
    lo_d, lo_px = _trough(s["price"], peak_d or ep_start, ep_end)
    fall = _seg_stats(s, peak_d or ep_start, lo_d or ep_end)
    base = _seg_stats(s, lo_d or ep_end, ep_end) if lo_d and lo_d < ep_end else {}
    return {
        "ep_start": ep_start, "ep_end": ep_end,
        "peak_date": peak_d, "peak_px": peak_px,
        "low_date": lo_d, "low_px": lo_px,
        "fall": fall, "base": base,
    }


def build_compare(code: str, episodes: list[tuple[str, str]],
                  token: str | None = None) -> dict:
    """兩（多）波對比 + 連續時間序列（給圖）。"""
    token = token or _token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    lo = min(e[0] for e in episodes)
    s = fetch_series(code, lo, datetime.now().strftime("%Y-%m-%d"), token)
    if not s.get("price"):
        return {"error": f"{code} 無價格資料"}
    eps = [build_episode(code, a, b, s) for a, b in episodes]
    # 連續序列（給 SVG）：日期排序後的 price / sbl（張）
    dates = sorted(s["price"])
    series = [{"d": d, "px": s["price"][d],
               "sbl": s["sbl"].get(d),
               "mgn": s["margin"].get(d)}
              for d in dates]
    return {"code": code, "episodes": eps, "series": series,
            "asof": dates[-1] if dates else ""}


if __name__ == "__main__":
    import sys
    _code = sys.argv[1] if len(sys.argv) > 1 else "3491"
    data = build_compare(_code, [("2025-03-21", "2025-08-31"),
                                 ("2026-05-29",
                                  datetime.now().strftime("%Y-%m-%d"))])
    print(json.dumps({k: v for k, v in data.items() if k != "series"},
                     ensure_ascii=False, indent=1))
    print("series points:", len(data.get("series", [])))
