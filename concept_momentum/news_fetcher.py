#!/usr/bin/env python3
"""
台股個股新聞抓取（從 Yahoo TW 股市新聞頁）

Yahoo TW 的 /quote/{code}.TW/news 頁面有股票相關新聞，h3 tag 解析即可。
"""

import json
import os
import re
import urllib.request
from datetime import datetime

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "news")


def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def fetch_yahoo_news(code: str, market: str = "上市") -> list[str]:
    """Fetch news titles for a stock from Yahoo TW stock news page.
    Returns list of news title strings (most recent first)."""
    suffix = ".TWO" if market == "上櫃" else ".TW"
    url = f"https://tw.stock.yahoo.com/quote/{code}{suffix}/news"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        # Try OTC suffix as fallback
        if market != "上櫃":
            return fetch_yahoo_news(code, "上櫃")
        return []

    titles = []
    for h3 in re.findall(r"<h3[^>]*>(.+?)</h3>", html, flags=re.DOTALL):
        text = _strip_html(h3)
        if 10 <= len(text) <= 200:
            titles.append(text)
    return titles


def fetch_news_for_stock(code: str, name_zh: str = "", market: str = "上市",
                         force: bool = False) -> list[str]:
    """Fetch news titles, cache for today. Returns list of titles."""
    _ensure_cache()
    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CACHE_DIR, f"{code}_{today}.json")
    if os.path.exists(cache_file) and not force:
        with open(cache_file) as f:
            return json.load(f)

    titles = fetch_yahoo_news(code, market)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False)
    return titles


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "3665"
    market = sys.argv[2] if len(sys.argv) > 2 else "上市"
    titles = fetch_news_for_stock(code, "", market, force=True)
    print(f"{code} ({market}) - {len(titles)} news titles:")
    for t in titles[:15]:
        print(f"  {t}")
