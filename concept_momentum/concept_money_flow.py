#!/usr/bin/env python3
"""族群資金流入流出 — 每日快取 + 計算 + CLI 回補

資料源（FinMind sponsor tier，單日全市場各一次呼叫）：
  TaiwanStockInstitutionalInvestorsBuySell — 三大法人買賣超（單位：股數）
  TaiwanStockPrice — 收盤價 + 成交金額 (Trading_money)

法人金額 = 淨股數 × 當日收盤價（近似值；實際成交價分布在盤中）。
日檔 cache/money_flow/{yyyymmdd}.json；衍生欄位（占比vs20日均、連續天數、
標記、5日累計）由讀取端從日檔序列現算、不落地 — 回補順序不影響快取正確性。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_DIR = os.path.join(HERE, "cache", "money_flow")
FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

YI = 1e8  # 億 NTD

# 四象限交叉判讀門檻 — 先驗設定、未經回測驗證（上線累積數據後可校準）
FLOW_SHARE_PP = 0.15   # |占比 vs 20日均| >= 0.15pp 才算熱度升/降
FLOW_INST_NTD = 0.5    # |法人淨流| >= 0.5 億才算法人買/賣

# FinMind name 欄位 → 法人身分（Foreign_Dealer_Self 依 TWSE 慣例併外資）
_FOREIGN = {"Foreign_Investor", "Foreign_Dealer_Self"}
_TRUST = {"Investment_Trust"}
_DEALER = {"Dealer_self", "Dealer_Hedging"}


def classify_flow_tag(share_vs_20d: float | None, inst_net_ntd: float | None) -> str:
    """占比變化 × 法人淨流 四象限。缺值或未達門檻 → '—'（fail-open）。"""
    if share_vs_20d is None or inst_net_ntd is None:
        return "—"
    if abs(share_vs_20d) < FLOW_SHARE_PP or abs(inst_net_ntd) < FLOW_INST_NTD:
        return "—"
    if share_vs_20d > 0:
        return "🔥" if inst_net_ntd > 0 else "⚠"
    return "🧲" if inst_net_ntd > 0 else "❄"


def _to_iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def aggregate_day(date_yyyymmdd: str, inst_rows: list[dict],
                  price_rows: list[dict], themes: dict) -> dict:
    """單日全市場原始列 → 族群加總日檔 dict。

    inst_rows 單位是股數；金額 = 淨股數 × 收盤價（近似）。
    全市場成交額只計 4 位數字代號（排除 ETF/權證）。
    FinMind start=end 查詢會夾帶次日列 — 這裡按 date 過濾。
    """
    date_iso = _to_iso(date_yyyymmdd)

    net: dict[str, dict] = {}  # code -> {"f","t","d"} 淨股數
    for row in inst_rows:
        if row.get("date") != date_iso:
            continue
        code = str(row.get("stock_id", ""))
        name = row.get("name", "")
        n = float(row.get("buy", 0) or 0) - float(row.get("sell", 0) or 0)
        slot = net.setdefault(code, {"f": 0.0, "t": 0.0, "d": 0.0})
        if name in _FOREIGN:
            slot["f"] += n
        elif name in _TRUST:
            slot["t"] += n
        elif name in _DEALER:
            slot["d"] += n

    close: dict[str, float] = {}
    money: dict[str, float] = {}
    market_turnover = 0.0
    for row in price_rows:
        if row.get("date") != date_iso:
            continue
        code = str(row.get("stock_id", ""))
        if not re.fullmatch(r"\d{4}", code):
            continue
        m = float(row.get("Trading_money", 0) or 0)
        money[code] = m
        market_turnover += m
        c = row.get("close")
        if c and c > 0:
            close[code] = float(c)

    out_themes = {}
    for tkey, tval in themes.items():
        f_ntd = t_ntd = d_ntd = 0.0
        turnover = 0.0
        missing = []
        for code in tval.get("stocks", []):
            code = str(code)
            turnover += money.get(code, 0.0)
            px = close.get(code)
            if px is None:
                missing.append(code)  # 無收盤價 → 金額跳過（占比不受影響）
                continue
            slot = net.get(code)
            if slot:
                f_ntd += slot["f"] * px
                t_ntd += slot["t"] * px
                d_ntd += slot["d"] * px
        inst = f_ntd + t_ntd + d_ntd
        out_themes[tkey] = {
            "inst_net_ntd": round(inst / YI, 2),
            "foreign_net_ntd": round(f_ntd / YI, 2),
            "trust_net_ntd": round(t_ntd / YI, 2),
            "turnover_ntd": turnover,
            "mkt_share_pct": (round(turnover / market_turnover * 100, 3)
                               if market_turnover > 0 else None),
            "missing": missing,
        }
    return {"date": date_yyyymmdd, "market_turnover_ntd": market_turnover,
            "themes": out_themes}


def inst_streak(nets: list[float]) -> int:
    """尾端起算的連續淨流入天數；連續流出為負；0 中斷、空序列回 0。"""
    if not nets or nets[-1] == 0:
        return 0
    sign = 1 if nets[-1] > 0 else -1
    n = 0
    for v in reversed(nets):
        if v != 0 and (v > 0) == (sign > 0):
            n += 1
        else:
            break
    return n * sign


def rolling_5d_cum(nets: list[float]) -> list[float]:
    """5 日滾動累計（前 4 天不足就用現有天數）— sparkline 用。"""
    return [round(sum(nets[max(0, i - 4):i + 1]), 2) for i in range(len(nets))]


def build_view_rows(day_files: list[dict], themes: dict) -> list[dict]:
    """由舊到新的日檔 list → 最新一日的 view rows（依法人淨流降冪）。

    衍生欄位在此現算：share_vs_20d（今日占比 − 前 20 日均，樣本不足用現有
    天數並回報 share_samples）、streak、net_5d、spark（5日滾動累計，最多 60 點）。
    """
    if not day_files:
        return []
    latest = day_files[-1]
    rows = []
    for tkey, tval in themes.items():
        series_net: list[float] = []
        series_share: list[float | None] = []
        for df in day_files:
            td = df.get("themes", {}).get(tkey)
            if td is None:
                continue
            series_net.append(td.get("inst_net_ntd") or 0.0)
            series_share.append(td.get("mkt_share_pct"))
        cur = latest.get("themes", {}).get(tkey)
        if cur is None or not series_net:
            continue
        prior_shares = [s for s in series_share[:-1] if s is not None][-20:]
        share_vs_20d = None
        if series_share[-1] is not None and prior_shares:
            share_vs_20d = round(series_share[-1] - sum(prior_shares) / len(prior_shares), 3)
        row = {
            "theme_key": tkey,
            "name_zh": tval.get("name_zh", tkey),
            "inst_net_ntd": cur["inst_net_ntd"],
            "foreign_net_ntd": cur["foreign_net_ntd"],
            "trust_net_ntd": cur["trust_net_ntd"],
            "net_5d": round(sum(series_net[-5:]), 2),
            "streak": inst_streak(series_net),
            "mkt_share_pct": cur.get("mkt_share_pct"),
            "share_vs_20d": share_vs_20d,
            "share_samples": len(prior_shares),
            "spark": rolling_5d_cum(series_net)[-60:],
            "missing": cur.get("missing", []),
        }
        row["tag"] = classify_flow_tag(share_vs_20d, row["inst_net_ntd"])
        rows.append(row)
    rows.sort(key=lambda r: -(r["inst_net_ntd"] or 0))
    return rows
