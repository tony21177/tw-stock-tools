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


# ---------------------------------------------------------------- I/O 層


def load_themes() -> dict:
    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        return json.load(f)["themes"]


def day_path(yyyymmdd: str) -> str:
    return os.path.join(FLOW_DIR, f"{yyyymmdd}.json")


def _fetch_finmind(dataset: str, date_iso: str, token: str) -> list[dict]:
    """單日全市場查詢（sponsor tier）。API/quota 錯誤 raise RuntimeError。"""
    params = {"dataset": dataset, "start_date": date_iso,
              "end_date": date_iso, "token": token}
    url = f"{FINMIND_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"FinMind HTTP {e.code} {dataset} {date_iso}: {body[:200]}")
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind error {dataset} {date_iso}: {payload.get('msg', '')}")
    return payload.get("data", [])


def run_day(date_yyyymmdd: str, token: str, themes: dict | None = None,
            verbose: bool = True, force: bool = False) -> dict | None:
    """抓當日全市場兩個 dataset → aggregate → 寫日檔。

    已存在（且非 force）→ 跳過並回快取內容。
    法人未發布/非交易日（inst 空）或成交額為 0 → 不寫檔、回 None（fail-open，
    絕不寫空檔）。API 錯誤（402 quota / 斷線）→ raise，由呼叫端決定。
    """
    os.makedirs(FLOW_DIR, exist_ok=True)
    path = day_path(date_yyyymmdd)
    if os.path.exists(path) and not force:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 已存在，跳過", flush=True)
        with open(path) as f:
            return json.load(f)
    if themes is None:
        themes = load_themes()
    date_iso = _to_iso(date_yyyymmdd)
    inst_rows = [r for r in
                 _fetch_finmind("TaiwanStockInstitutionalInvestorsBuySell",
                                date_iso, token)
                 if r.get("date") == date_iso]
    if not inst_rows:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 法人資料尚未發布或非交易日 — 不寫檔",
                  flush=True)
        return None
    price_rows = _fetch_finmind("TaiwanStockPrice", date_iso, token)
    day = aggregate_day(date_yyyymmdd, inst_rows, price_rows, themes)
    if day["market_turnover_ntd"] <= 0:
        if verbose:
            print(f"[money_flow] {date_yyyymmdd} 無成交金額資料 — 不寫檔", flush=True)
        return None
    with open(path, "w") as f:
        json.dump(day, f, ensure_ascii=False)
    if verbose:
        print(f"[money_flow] wrote {path}", flush=True)
    return day


def load_flow_days(end_yyyymmdd: str, days: int = 60) -> list[dict]:
    """讀 <= end_date 的最近 `days` 個日檔，由舊到新。壞檔跳過。"""
    if not os.path.isdir(FLOW_DIR):
        return []
    files = sorted(f for f in os.listdir(FLOW_DIR)
                   if f.endswith(".json") and f[:8] <= end_yyyymmdd)[-days:]
    out = []
    for fname in files:
        try:
            with open(os.path.join(FLOW_DIR, fname)) as f:
                out.append(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def backfill(token: str, end_yyyymmdd: str, days: int = 60,
             delay_seconds: float = 1.0, verbose: bool = True) -> int:
    """回補最近 `days` 個交易日（交易日來源 = taiex.json，比照 market_breadth）。

    已存在跳過（resumable，中斷重跑安全）。單日失敗記 log 續跑。
    """
    from market_breadth import _twii_trading_dates
    dates = _twii_trading_dates(end_yyyymmdd, days)
    themes = load_themes()
    written = 0
    for d in dates:
        if os.path.exists(day_path(d)):
            continue
        try:
            day = run_day(d, token, themes=themes, verbose=verbose)
        except Exception as e:
            print(f"[money_flow] {d} 失敗: {e}", file=sys.stderr, flush=True)
            time.sleep(delay_seconds)
            continue
        if day:
            written += 1
        time.sleep(delay_seconds)
    if verbose:
        print(f"[money_flow] 回補完成，新寫 {written} 日", flush=True)
    return written


def main():
    from datetime import datetime
    p = argparse.ArgumentParser(description="族群資金流 日檔快取（抓取+回補）")
    p.add_argument("--date", help="單日 YYYYMMDD（預設今天）")
    p.add_argument("--backfill", type=int, metavar="N", help="回補最近 N 個交易日")
    p.add_argument("--force", action="store_true", help="已存在也重抓")
    args = p.parse_args()
    token = os.environ.get("FINMIND_TOKEN", "")
    if not token:
        print("需要 FINMIND_TOKEN 環境變數", file=sys.stderr)
        sys.exit(1)
    if args.backfill:
        backfill(token, datetime.now().strftime("%Y%m%d"), days=args.backfill)
    else:
        d = args.date or datetime.now().strftime("%Y%m%d")
        run_day(d, token, force=args.force)


if __name__ == "__main__":
    main()
