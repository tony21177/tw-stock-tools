#!/usr/bin/env python3
"""全站統一導航列 (site_nav)

每個工具頁的 render_html 都 import 這裡的 nav_html(),取代各自手寫的
<nav>(舊況:每頁連結子集不同、futures-basis/adr-premium 甚至沒 nav)。
新增工具頁時只要改 NAV_LINKS 一處,全站同步。

用法:
    from site_nav import nav_html
    nav = nav_html("/margin-scan")   # 當前頁會顯示為粗體、不可點
"""

# (href, 顯示名) — 順序即顯示順序;分組用 None 當分隔點(顯示 ·)
NAV_LINKS = [
    ("/", "🏠 首頁"),
    ("/market-tomorrow", "🌏 明天大盤"),
    ("/ftd", "🚀 FTD"),
    ("/option-flow", "📊 選擇權法人"),
    ("/margin-scan", "💥 融資斷頭潮"),
    ("/extremes", "📊 一年高低"),
    ("/seasonality", "📅 月份季節性"),
    ("/stock-futures", "🔥 個股期"),
    ("/lin-matrix", "📐 林則行"),
    ("/futures-basis", "📐 期貨基差"),
    ("/adr-premium", "🇺🇸 ADR"),
    ("/warrant-signal", "🎫 權證"),
    ("/money-flow", "💰 資金流"),
    ("/chip-price", "🧬 籌碼價量"),
    ("/intraday-sim", "📉 盤中模擬"),
]

_CSS = (
    '<style>nav.site{font-size:.82em;line-height:2;margin-bottom:6px}'
    'nav.site a{margin-right:10px;color:#0066cc;text-decoration:none;'
    'white-space:nowrap}nav.site a:hover{text-decoration:underline}'
    'nav.site b{margin-right:10px;color:#222;white-space:nowrap}</style>'
)


# 對外網址(推播訊息用;localhost 在手機上點不開)。ngrok 靜態域名,
# 可用 env PUBLIC_BASE_URL 覆蓋。
import os as _os

PUBLIC_BASE = _os.environ.get(
    "PUBLIC_BASE_URL", "https://shudder-attention-musky.ngrok-free.dev")


def public_url(path: str = "/") -> str:
    """推播訊息用的公開網址(手機可開)。"""
    return PUBLIC_BASE.rstrip("/") + path


def nav_html(current: str | None = None) -> str:
    """統一導航列。current=當前頁 href(顯示粗體不可點)。"""
    parts = []
    for href, label in NAV_LINKS:
        if href == current:
            parts.append(f"<b>{label}</b>")
        else:
            parts.append(f'<a href="{href}">{label}</a>')
    return _CSS + '<nav class="site">' + " ".join(parts) + "</nav>"
