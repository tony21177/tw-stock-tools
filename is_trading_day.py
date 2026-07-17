#!/usr/bin/env python3
"""台股交易日守門 — 給 cron 用。今天(或指定日)是 TWSE 交易日 → exit 0；
否則(週末/國定假日) → exit 1。

用法 (cron 前綴)：
    is_trading_day.py && <實際指令>      # 非交易日就不跑

資料來源：FinMind TaiwanStockTradingDate（含未來日期、已排除國定假日），
本地快取 cache/trading_calendar.json 以免每次 cron 都打 API。

Fail-safe：拿不到日曆又沒快取時，退回「週一~週五 = 交易日」判斷
（寧可在平日多跑一次產生空推，也不要誤判而漏掉真正交易日的累積資料）。
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_CACHE = os.path.join(HERE, "concept_momentum", "cache", "trading_calendar.json")
FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    except Exception:
        pass
    return ""


def _fetch_calendar(token: str) -> list[str]:
    """抓 TaiwanStockTradingDate (今年~明年)。回 ['YYYY-MM-DD', ...]。"""
    today = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                           text=True).stdout.strip()
    year = today[:4]
    end = f"{int(year) + 1}-12-31"
    q = urllib.parse.urlencode({
        "dataset": "TaiwanStockTradingDate",
        "start_date": f"{year}-01-01", "end_date": end, "token": token})
    req = urllib.request.Request(f"{FINMIND_API}?{q}")
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    return sorted(x["date"] for x in d.get("data", []))


def _load_cache() -> list[str]:
    if not os.path.exists(CAL_CACHE):
        return []
    try:
        with open(CAL_CACHE, encoding="utf-8") as f:
            return json.load(f).get("dates", [])
    except Exception:
        return []


def _save_cache(dates: list[str]) -> None:
    os.makedirs(os.path.dirname(CAL_CACHE), exist_ok=True)
    with open(CAL_CACHE, "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f, ensure_ascii=False)


def _verify_traded(date_iso: str, token: str) -> bool | None:
    """臨時休市驗證 — 日曆說是交易日後，查 2330 該日有無實際成交。

    FinMind 的 TaiwanStockTradingDate 是預排日曆，**不含臨時停市**
    (2026-07-10 颱風假事件：實際休市但日曆列為交易日 → 所有盤後 cron
    誤跑，TWSE BSR 回傳前一日資料被錯標)。收盤資料 FinMind ~14:00 後
    可得，所以只對「過去日期」或「今天且已過 15:00」做此驗證。

    True=有成交, False=臨時休市, None=查不到(fail-open 照日曆)。
    """
    q = urllib.parse.urlencode({
        "dataset": "TaiwanStockPrice", "data_id": "2330",
        "start_date": date_iso, "end_date": date_iso, "token": token})
    try:
        req = urllib.request.Request(f"{FINMIND_API}?{q}")
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if str(d.get("msg", "")).lower() != "success":
        return None   # token 額度/API 異常 → 不可信，fail-open
    return any(x.get("date") == date_iso for x in d.get("data", []))


def is_trading_day(date_iso: str) -> bool | None:
    """True=交易日, False=休市, None=無法判定(讓呼叫端 fail-safe)。"""
    cal = _load_cache()
    # 快取沒涵蓋到要查的日期 → 刷新
    if not cal or date_iso > cal[-1] or date_iso < cal[0]:
        tok = _token()
        if tok:
            try:
                cal = _fetch_calendar(tok)
                _save_cache(cal)
            except Exception:
                pass
    if not cal:
        return None
    if cal[0] <= date_iso <= cal[-1]:
        return date_iso in set(cal)
    return None  # 超出日曆範圍，無法判定


if __name__ == "__main__":
    if len(sys.argv) > 1:                       # 接受 YYYYMMDD 或 YYYY-MM-DD
        a = sys.argv[1]
        date_iso = a if "-" in a else f"{a[:4]}-{a[4:6]}-{a[6:]}"
    else:
        date_iso = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                  text=True).stdout.strip()
    res = is_trading_day(date_iso)
    if res is None:                              # fail-safe：退回週一~週五
        wd = subprocess.run(["date", "-d", date_iso, "+%u"],
                            capture_output=True, text=True).stdout.strip()
        res = wd in ("1", "2", "3", "4", "5")
        sys.stderr.write(f"[is_trading_day] {date_iso} 無日曆，fallback 週間判斷={res}\n")
    if res:
        # 第二層：臨時休市驗證 (颱風假等日曆沒有的停市)。
        # 只在收盤資料應已存在時查：過去日期、或今天且已過 15:00。
        today_iso = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                   text=True).stdout.strip()
        hour = int(subprocess.run(["date", "+%H"], capture_output=True,
                                  text=True).stdout.strip())
        if date_iso < today_iso or (date_iso == today_iso and hour >= 15):
            v = _verify_traded(date_iso, _token())
            if v is False:
                sys.stderr.write(f"[is_trading_day] {date_iso} 日曆列交易日"
                                 f"但無成交資料 (臨時休市?)，跳過\n")
                sys.exit(1)
        sys.exit(0)                             # 交易日 → 跑
    sys.stderr.write(f"[is_trading_day] {date_iso} 非交易日，跳過\n")
    sys.exit(1)                                 # 休市 → 不跑
