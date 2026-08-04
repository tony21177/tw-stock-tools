#!/usr/bin/env python3
"""
注意/處置公告抓取與快取(上市 TWSE + 上櫃 TPEx)。

資料源(官方,免 token):
  TWSE 注意: https://www.twse.com.tw/announcement/notice?response=json&startDate=&endDate=
  TWSE 處置: https://www.twse.com.tw/announcement/punish?response=json&startDate=&endDate=
  TPEx 注意: https://www.tpex.org.tw/www/zh-tw/bulletin/attention?startDate=YYYY/MM/DD&endDate=&response=json
  TPEx 處置: https://www.tpex.org.tw/www/zh-tw/bulletin/disposal?startDate=YYYY/MM/DD&endDate=&response=json

快取:concept_momentum/cache/disposal/{notice|punish}_{YYYYMM}.json(月檔)。
歷史月檔存在即跳過;當月每次重抓(增量安全)。這份快取同時是
「新制施行後處置股行為研究」的數據累積基礎。

統一 schema:
  notice: {date, code, name, market(twse/tpex), cum, info, close}
  punish: {ann_date, code, name, market, cum, condition, start, end, measure}
  (日期一律 YYYYMMDD;TPEx 民國年自動轉換)

CLI:
  python3 tw_disposal_data.py --backfill 2024-07   # 回補至指定年月
  python3 tw_disposal_data.py                      # 更新當月
"""

import argparse
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "concept_momentum", "cache", "disposal")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def _get_json(url: str, retries: int = 2) -> dict | list | None:
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            if i < retries:
                time.sleep(3)
    return None


def _roc_to_ymd(s: str) -> str | None:
    """'114/01/03'、'115.08.04' 或 '2025/01/03' → YYYYMMDD。"""
    s = str(s).strip()
    m = re.match(r"(\d{2,4})[./](\d{1,2})[./](\d{1,2})", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1000:
        y += 1911
    return f"{y:04d}{mo:02d}{d:02d}"


def _parse_period(s: str) -> tuple[str | None, str | None]:
    """'114/01/03~114/01/16' → (start, end)。分隔符容錯 ~ ～ -。"""
    parts = re.split(r"[~～]|(?<=\d)-(?=\d{2,4}/)", s.strip(), maxsplit=1)
    if len(parts) == 2:
        return _roc_to_ymd(parts[0]), _roc_to_ymd(parts[1])
    return _roc_to_ymd(s), None


def _month_range(yyyymm: str) -> tuple[str, str]:
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    import calendar
    return f"{y:04d}{m:02d}01", f"{y:04d}{m:02d}{calendar.monthrange(y, m)[1]:02d}"


def fetch_twse_month(kind: str, yyyymm: str) -> list[dict]:
    """kind: notice | punish。"""
    s, e = _month_range(yyyymm)
    url = (f"https://www.twse.com.tw/announcement/{kind}"
           f"?response=json&startDate={s}&endDate={e}")
    d = _get_json(url)
    if not d or d.get("stat") not in ("OK", "ok"):
        return []
    fields = d.get("fields", [])
    out = []
    for row in d.get("data", []):
        r = dict(zip(fields, row))
        if kind == "notice":
            date = _roc_to_ymd(r.get("日期", "")) or ""
            out.append({"date": date, "code": r.get("證券代號", "").strip(),
                        "name": r.get("證券名稱", "").strip(), "market": "twse",
                        "cum": r.get("累計次數", ""), "info": r.get("注意交易資訊", ""),
                        "close": r.get("收盤價", "")})
        else:
            st, en = _parse_period(r.get("處置起迄時間", ""))
            out.append({"ann_date": _roc_to_ymd(r.get("公布日期", "")) or "",
                        "code": r.get("證券代號", "").strip(),
                        "name": r.get("證券名稱", "").strip(), "market": "twse",
                        "cum": r.get("累計", ""), "condition": r.get("處置條件", ""),
                        "start": st, "end": en, "measure": r.get("處置措施", "")})
    return out


def fetch_tpex_month(kind: str, yyyymm: str) -> list[dict]:
    """kind: attention | disposal。"""
    s, e = _month_range(yyyymm)
    s_f = f"{s[:4]}/{s[4:6]}/{s[6:]}"
    e_f = f"{e[:4]}/{e[4:6]}/{e[6:]}"
    url = (f"https://www.tpex.org.tw/www/zh-tw/bulletin/{kind}"
           f"?startDate={s_f}&endDate={e_f}&response=json")
    d = _get_json(url)
    if not d:
        return []
    tables = d.get("tables") or [d]
    out = []
    for t in tables:
        fields = t.get("fields", [])
        for row in t.get("data", []):
            r = dict(zip(fields, row))
            if kind == "attention":
                date = _roc_to_ymd(r.get("公告日期", "")) or ""
                out.append({"date": date, "code": r.get("證券代號", "").strip(),
                            "name": r.get("證券名稱", "").strip(), "market": "tpex",
                            "cum": r.get("累計", ""), "info": r.get("注意交易資訊", ""),
                            "close": r.get("收盤價", "")})
            else:
                st, en = _parse_period(r.get("處置起訖時間", "") or r.get("處置起迄時間", ""))
                out.append({"ann_date": _roc_to_ymd(r.get("公布日期", "")) or "",
                            "code": r.get("證券代號", "").strip(),
                            "name": r.get("證券名稱", "").strip(), "market": "tpex",
                            "cum": r.get("累計", ""), "condition": r.get("處置原因", ""),
                            "start": st, "end": en, "measure": r.get("處置內容", "")})
    return out


def update_month(yyyymm: str, force: bool = False) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    stats = {}
    for label, fn in [("notice", lambda: fetch_twse_month("notice", yyyymm)
                       + fetch_tpex_month("attention", yyyymm)),
                      ("punish", lambda: fetch_twse_month("punish", yyyymm)
                       + fetch_tpex_month("disposal", yyyymm))]:
        path = os.path.join(CACHE_DIR, f"{label}_{yyyymm}.json")
        if os.path.exists(path) and not force:
            stats[label] = f"skip({len(json.load(open(path)))})"
            continue
        rows = fn()
        time.sleep(1.5)
        with open(path, "w") as f:
            json.dump(rows, f, ensure_ascii=False)
        stats[label] = len(rows)
    return stats


def load_all(kind: str) -> list[dict]:
    """kind: notice | punish。讀全部月檔合併(去重)。"""
    out, seen = [], set()
    for p in sorted(__import__("glob").glob(os.path.join(CACHE_DIR, f"{kind}_*.json"))):
        for r in json.load(open(p)):
            k = (r.get("date") or r.get("ann_date"), r.get("code"),
                 r.get("market"), r.get("info") or r.get("start"))
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
    return out


def main():
    from datetime import datetime
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", help="回補至 YYYY-MM(含),逐月抓")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    now = datetime.now()
    months = []
    if args.backfill:
        y, m = map(int, args.backfill.split("-"))
        while (y, m) <= (now.year, now.month):
            months.append(f"{y:04d}{m:02d}")
            m += 1
            if m > 12:
                y, m = y + 1, 1
    else:
        months = [now.strftime("%Y%m")]
    for mm in months:
        force = args.force or (mm == now.strftime("%Y%m"))   # 當月一律重抓
        print(mm, update_month(mm, force=force), flush=True)


if __name__ == "__main__":
    main()
