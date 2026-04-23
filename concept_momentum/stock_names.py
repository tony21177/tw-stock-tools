#!/usr/bin/env python3
"""
取得台股代號 → 中文名對照。
資料來源：TWSE ISIN 公開資料（上市 strMode=2, 上櫃 strMode=4）
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "cache", "stock_names.json")
CACHE_TTL_DAYS = 7

TWSE_ISIN_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"


def _fetch_isin(mode: int) -> dict:
    """Fetch ISIN data for a market. mode=2 for 上市, mode=4 for 上櫃.
    Returns {code: name}."""
    url = TWSE_ISIN_URL.format(mode=mode)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
        # Use cp950 (superset of big5) to handle chars like 碁
        try:
            text = raw.decode("cp950", errors="replace")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[WARN] ISIN fetch failed (mode={mode}): {e}")
        return {}

    # Each row has "代號　名稱" (full-width space separator) in a td
    # Example: <td bgcolor=#FAFAD2>1101　台泥</td>
    # Filter: 4-6 char codes (digits, sometimes trailing letter for ETF)
    result = {}
    for m in re.finditer(r"<td[^>]*>([A-Z0-9]{3,8})[　\s]+([^\s<][^<]*?)</td>", text):
        code = m.group(1).strip()
        name = m.group(2).strip()
        # Keep 4-digit stocks + 5/6-char ETFs (00xxx), skip warrants (7+ chars usually)
        if not (4 <= len(code) <= 6):
            continue
        if code and name and not name.startswith("<"):
            result[code] = name
    return result


def load_names(force_refresh: bool = False) -> dict:
    """Load code→name map. Cached for CACHE_TTL_DAYS days."""
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached.get("updated_at", "2000-01-01"))
            if datetime.now() - updated < timedelta(days=CACHE_TTL_DAYS):
                return cached.get("names", {})
        except Exception:
            pass

    print("抓取 TWSE ISIN 股票中文名對照表...")
    listed = _fetch_isin(2)
    otc = _fetch_isin(4)
    names = {**otc, **listed}  # listed overrides OTC if duplicate
    print(f"  上市: {len(listed)} 檔, 上櫃: {len(otc)} 檔, 合計: {len(names)} 檔")

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now().isoformat(),
            "names": names,
        }, f, ensure_ascii=False, indent=2)
    return names


_NAME_CACHE = None


def get_name(code: str, fallback: str = "") -> str:
    """Get Chinese name for a stock code. Falls back to given fallback string."""
    global _NAME_CACHE
    if _NAME_CACHE is None:
        _NAME_CACHE = load_names()
    return _NAME_CACHE.get(code, fallback or code)


if __name__ == "__main__":
    names = load_names(force_refresh=True)
    print(f"\n總共 {len(names)} 檔股票中文名")
    # Sample
    for code in ["2330", "2317", "3491", "6862", "6285", "3324", "3035"]:
        print(f"  {code}: {names.get(code, '(未找到)')}")
