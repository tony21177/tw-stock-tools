#!/usr/bin/env python3
"""權證每日資料層 — 抓 TWSE 六類權證、按標的現股彙總、寫日檔.

⚠ 訊號門檻為先驗假設、未經回測。權證量主要由券商造市/避險驅動，
單看絕對量無意義（見設計文件 2026-07-21-warrant-signal-design.md）。
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FLOW_DIR = os.path.join(HERE, "cache", "warrant_flow")
MI_INDEX = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            "?type={type}&response=json&date={date}")
UA = "Mozilla/5.0"

# type code → 方向（偏多 bull / 偏空 bear）
WARRANT_TYPES = {
    "0999": "bull",    # 認購權證(不含牛證)
    "0999C": "bull",   # 牛證
    "0999X": "bull",   # 可展延牛證
    "0999P": "bear",   # 認售權證(不含熊證)
    "0999B": "bear",   # 熊證
    "0999Y": "bear",   # 可展延熊證
}

# 權證名稱 = [標的簡稱][券商][流水][購/售][序]，券商名擷取用
_ISSUERS = ("凱基", "元大", "統一", "富邦", "永豐", "群益", "國泰", "兆豐",
            "中信", "元富", "第一金", "康和", "日盛", "台新", "華南", "宏遠",
            "麥格理", "花旗", "高盛", "摩根", "國票")


def parse_issuer(name: str, underlying_name: str = "") -> str:
    """從權證名稱擷取券商。標的簡稱可能本身含券商字樣（如「元大金」含
    「元大」、「國泰金」含「國泰」、「富邦金」含「富邦」），故須先剝除
    標的簡稱前綴，只在剩餘部分比對券商，避免誤判為標的自身。
    """
    rest = name
    if underlying_name and name.startswith(underlying_name):
        rest = name[len(underlying_name):]
    for iss in _ISSUERS:
        if iss in rest:
            return iss
    return ""


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(",", ""))
        return v
    except (TypeError, ValueError):
        return None


def _parse_warrant_table(payload: dict) -> list[dict]:
    tables = [t for t in payload.get("tables", []) if t.get("title")]
    rows = []
    for t in tables:
        for d in t.get("data", []):
            if len(d) < 20:
                continue
            turnover = _num(d[5])
            volume = _num(d[3])
            if turnover is None or volume is None:
                continue    # 壞/空值列跳過
            rows.append({
                "code": str(d[1]), "name": str(d[2]),
                "volume": int(volume), "trades": int(_num(d[4]) or 0),
                "turnover": turnover,
                "underlying": str(d[17]), "underlying_name": str(d[18]),
            })
    return rows


def _fetch_json(url: str, retries: int, delay: float) -> dict | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 2))
                continue
            print(f"[WARN] {e}: {url[:90]}", file=sys.stderr)
    return None


def fetch_warrant_day(date_yyyymmdd: str, delay: float = 3.0,
                      retries: int = 3) -> list[dict]:
    out = []
    for i, (ty, side) in enumerate(WARRANT_TYPES.items()):
        if i:
            time.sleep(delay)
        payload = _fetch_json(
            MI_INDEX.format(type=ty, date=date_yyyymmdd), retries, delay)
        if not payload or payload.get("stat") != "OK":
            continue
        for r in _parse_warrant_table(payload):
            r["side"] = side
            out.append(r)
    return out


def aggregate_by_underlying(rows: list[dict]) -> dict:
    agg: dict[str, dict] = {}
    for r in rows:
        code = r["underlying"]
        if not re.fullmatch(r"\d{4}", code):
            continue    # 只留 4 位數普通股標的（排除指數 IX...）
        u = agg.setdefault(code, {
            "bull_turnover": 0.0, "bear_turnover": 0.0,
            "bull_vol": 0, "bear_vol": 0, "n_warrants": 0,
            "issuers": {}, "_all": []})
        side = r["side"]
        u[f"{side}_turnover"] += r["turnover"]
        u[f"{side}_vol"] += r["volume"]
        u["n_warrants"] += 1
        iss = parse_issuer(r["name"], r.get("underlying_name", ""))
        if iss:
            u["issuers"][iss] = u["issuers"].get(iss, 0.0) + r["turnover"]
        u["_all"].append({"code": r["code"], "name": r["name"],
                          "issuer": iss, "side": side,
                          "turnover": r["turnover"]})
    for u in agg.values():
        u["top_warrants"] = sorted(u.pop("_all"),
                                   key=lambda w: -w["turnover"])[:5]
    return agg


def run_day(date_yyyymmdd: str, rows: list[dict] | None = None) -> dict:
    """彙總日資料 + 原子寫日檔。

    若 rows 為即時抓取（呼叫端未傳入，走 fetch_warrant_day）且彙總結果
    零標的，視為抓取失敗/遭限流（正常交易日一定有權證資料），不寫日檔，
    避免污染日檔快取；直接傳入 rows 的路徑（測試用）維持照寫不誤。
    """
    live_fetch = rows is None
    if rows is None:
        rows = fetch_warrant_day(date_yyyymmdd)
    day = {"date": date_yyyymmdd,
           "underlyings": aggregate_by_underlying(rows)}
    if live_fetch and not day["underlyings"]:
        print(f"[WARN] {date_yyyymmdd} 即時抓取零標的資料，"
              f"可能抓取失敗或遭限流（正常交易日必有權證資料），"
              f"不寫入日檔", file=sys.stderr)
        return day
    os.makedirs(FLOW_DIR, exist_ok=True)
    path = os.path.join(FLOW_DIR, f"{date_yyyymmdd}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False)
    os.replace(tmp, path)
    return day


def load_day(date_yyyymmdd: str) -> dict | None:
    """載入日檔，不存在回傳 None。"""
    path = os.path.join(FLOW_DIR, f"{date_yyyymmdd}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _main():
    import argparse
    from datetime import datetime
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", type=int)
    ap.add_argument("--delay", type=float, default=3.0)
    args = ap.parse_args()
    if args.backfill:
        sys.path.insert(0, HERE)
        import market_breadth
        today = datetime.now().strftime("%Y%m%d")
        dates = market_breadth._twii_trading_dates(today, args.backfill)
        for d in dates:
            if load_day(d):
                continue
            print(f"[warrant] {d} …", file=sys.stderr)
            run_day(d)
            time.sleep(args.delay)
    else:
        d = args.date or datetime.now().strftime("%Y%m%d")
        run_day(d)
        print(f"[warrant] wrote {d}", file=sys.stderr)


if __name__ == "__main__":
    _main()
