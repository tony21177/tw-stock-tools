#!/usr/bin/env python3
"""台股加權指數「結算前剩餘除息點數」精算 — 修正期貨基差的除息拖累.

台指期結算 vs 加權指數(價格指數，除息當天機械蒸發點數)：期貨合理價
≈ 現貨 − 結算前未發放股利現值。除權息旺季(6-9月)會出現數百點「結構性
逆價差」，純粹待除息、非看空。此模組算出剩餘除息點數 D，讓
  調整後基差 = 原始基差(期-現) + D
把待除息加回，真正的方向訊號才浮得出來。

精算公式：某股除息蒸發指數點數 = 指數 × (該股市值/全市場市值)
                                      × (每股現金股利/股價)
資料 FinMind：TaiwanStockMarketValue(全市場市值，權重)、TaiwanStockPrice
(股價)、TaiwanStockDividend(逐檔除息日+現金股利)。

⚠ 資料限制：FinMind 全市場股利查詢不完整、逐檔查上千檔不現實 → 只對
**前 N 大權值股**逐檔查(指數極度集中頭部，前 30-50 大約佔 75-85% 權重)。
輸出標明覆蓋率(top-N 權重和)，非 100% 全市場精算。
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache",
                     "index_div_points.json")


def third_wednesday(year: int, month: int) -> date:
    """該月第三個週三 = 台指期近月結算日。"""
    d = date(year, month, 1)
    # 第一個週三
    first_wed = d + timedelta(days=(2 - d.weekday()) % 7)
    return first_wed + timedelta(days=14)


def front_settlement(asof: date, front_contract_yyyymm: str | None = None
                     ) -> date:
    """近月合約結算日。給合約月(YYYYMM)用它；否則由 asof 推：
    未過本月第三週三 → 本月結算，否則次月。"""
    if front_contract_yyyymm and len(front_contract_yyyymm) == 6:
        y, m = int(front_contract_yyyymm[:4]), int(front_contract_yyyymm[4:6])
        return third_wednesday(y, m)
    tw = third_wednesday(asof.year, asof.month)
    if asof <= tw:
        return tw
    nm = asof.replace(day=1) + timedelta(days=32)
    return third_wednesday(nm.year, nm.month)


def _load_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, CACHE)


def compute_points(index_value: float, total_mktcap: float,
                   top_stocks: list[dict], settle_iso: str,
                   asof_iso: str, div_fetch, price_map: dict) -> dict:
    """純計算(可注入 div_fetch / price_map 供測試)。

    top_stocks: [{stock_id, market_value}] 前 N 大(依市值)。
    div_fetch(stock_id) -> [{ex_date 'YYYY-MM-DD', cash}] 該股除息事件。
    price_map: {stock_id: close}。
    回 {points, coverage_pct, n_stocks, n_div, detail:[{code,pts}]}。
    """
    covered_mv = sum(s["market_value"] for s in top_stocks)
    coverage = covered_mv / total_mktcap * 100 if total_mktcap else 0.0
    pts = 0.0
    detail = []
    n_div = 0
    for s in top_stocks:
        sid = s["stock_id"]
        price = price_map.get(sid)
        if not price or not s["market_value"]:
            continue
        weight = s["market_value"] / total_mktcap
        for ev in div_fetch(sid) or []:
            ex = ev.get("ex_date", "")
            cash = ev.get("cash") or 0
            # 除息日落在 (今天, 結算日] 才算(今天以後、含結算日)
            if not (asof_iso < ex <= settle_iso) or cash <= 0:
                continue
            p = index_value * weight * (cash / price)
            pts += p
            n_div += 1
            if p >= 0.5:
                detail.append({"code": sid, "pts": round(p, 1)})
    detail.sort(key=lambda x: -x["pts"])
    return {"points": round(pts, 1), "coverage_pct": round(coverage, 1),
            "n_stocks": len(top_stocks), "n_div": n_div,
            "detail": detail[:10]}


def remaining_dividend_points(asof_iso: str, settle_iso: str, token: str,
                              index_value: float, top_n: int = 50,
                              use_cache: bool = True) -> dict | None:
    """抓資料 + 精算。以 (asof, settle, top_n) 快取一天。None=資料不足。"""
    key = f"{asof_iso}_{settle_iso}_{top_n}"
    if use_cache:
        c = _load_cache()
        if key in c:
            return c[key]
    sys.path.insert(0, HERE)
    try:
        import finmind_client as fc
    except Exception:
        return None
    # 全市場市值(取 <= asof 最近一日)
    mv_rows = fc._call("TaiwanStockMarketValue",
                       {"start_date": asof_iso, "end_date": asof_iso}, token)
    if not mv_rows:
        # 往前退幾天找最近有市值的交易日
        d = datetime.strptime(asof_iso, "%Y-%m-%d")
        for back in range(1, 6):
            dd = (d - timedelta(days=back)).strftime("%Y-%m-%d")
            mv_rows = fc._call("TaiwanStockMarketValue",
                               {"start_date": dd, "end_date": dd}, token)
            if mv_rows:
                break
    mv_rows = [r for r in (mv_rows or []) if r.get("market_value")
               and str(r.get("stock_id", "")).isdigit()
               and len(str(r["stock_id"])) == 4]
    if not mv_rows:
        return None
    total = sum(r["market_value"] for r in mv_rows)
    top = sorted(mv_rows, key=lambda r: -r["market_value"])[:top_n]
    codes = [r["stock_id"] for r in top]
    # 股價(全市場一次查)
    px = fc._call("TaiwanStockPrice",
                  {"start_date": asof_iso, "end_date": asof_iso}, token)
    if not px:
        d = datetime.strptime(asof_iso, "%Y-%m-%d")
        for back in range(1, 6):
            dd = (d - timedelta(days=back)).strftime("%Y-%m-%d")
            px = fc._call("TaiwanStockPrice",
                          {"start_date": dd, "end_date": dd}, token)
            if px:
                break
    price_map = {r["stock_id"]: r["close"] for r in (px or [])
                 if r.get("close")}

    def _div_fetch(sid: str):
        try:
            rows = fc._call("TaiwanStockDividend",
                            {"data_id": sid, "start_date": "2025-06-01",
                             "end_date": settle_iso}, token)
        except Exception:
            return []
        return [{"ex_date": r.get("CashExDividendTradingDate", ""),
                 "cash": r.get("CashEarningsDistribution") or 0}
                for r in rows]

    out = compute_points(index_value, total,
                         [{"stock_id": r["stock_id"],
                           "market_value": r["market_value"]} for r in top],
                         settle_iso, asof_iso, _div_fetch, price_map)
    out["asof"] = asof_iso
    out["settle"] = settle_iso
    if use_cache:
        c = _load_cache()
        c[key] = out
        # 只留最近 30 筆
        if len(c) > 30:
            for k in sorted(c)[:-30]:
                del c[k]
        _save_cache(c)
    return out
