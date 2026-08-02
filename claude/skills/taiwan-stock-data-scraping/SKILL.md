---
name: taiwan-stock-data-scraping
description: Use when fetching Taiwan stock data — margin/lending balances, broker-branch flows, daily prices, concept stock lists. Covers TWSE/TPEx/FinMind/Yahoo APIs, CAPTCHA workarounds, encoding gotchas, rate limits.
---

# Taiwan Stock Data Scraping

## Overview

Taiwan stock data is split across several authorities and providers, each with quirks:
- **TWSE** (上市): some endpoints rate-limited, some have CAPTCHA, OpenAPI is the safe bet
- **TPEx** (上櫃): newer pages use Cloudflare Turnstile (need real browser)
- **FinMind**: clean REST API but tiered (some datasets free, some sponsor-only)
- **Yahoo Finance**: convenient daily OHLCV, but rate-limits and lacks Chinese names

**Use the right source for the right data.** Don't guess endpoints — this skill maps known-working ones.

## Quick Reference: Where To Find What

| Data | Source | Endpoint / Dataset | Notes |
|------|--------|-------------------|-------|
| Today's 融資/融券餘額 (per stock) | TWSE OpenAPI | `https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN` | No CAPTCHA, no rate limit, today only |
| Today's 上櫃 融資餘額 | TPEx OpenAPI | `https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance` | No CAPTCHA, today only |
| Historical 融資/融券 (per stock, 3mo) | FinMind | `dataset=TaiwanStockMarginPurchaseShortSale&data_id={code}` | Free tier OK, ~600 req/hr |
| 借券議借交易明細 | TWSE SBL | `https://www.twse.com.tw/SBL/t13sa710?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo={code}&response=json` | Includes 上市+上櫃, returns 議借/競價/定價 |
| 借券還券明細 (含原借入日) | TWSE SBL | `https://www.twse.com.tw/SBL/t13sa870?startDate=YYYYMMDD&endDate=YYYYMMDD&stockNo={code}&response=json` | Includes 借券天數 |
| 借券賣出餘額 (per stock) | TWSE | `https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=YYYYMMDD&response=json` | 上市only; values in 股 (÷1000 = 張) |
| 借券賣出餘額 (上櫃) | TPEx | `https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=YYYY/MM/DD&response=json` | Note slash format in date |
| Daily OHLCV per stock (3mo) | Yahoo Finance | `https://query1.finance.yahoo.com/v8/finance/chart/{code}.TW?interval=1d&range=3mo` | Use `.TW` for 上市, `.TWO` for 上櫃 |
| 加權指數 (TAIEX) | Yahoo Finance | `^TWII` symbol | Same chart endpoint |
| 分點 BSR (上市, today) | TWSE BSR | `https://bsr.twse.com.tw/bshtm/bsMenu.aspx` | CAPTCHA — see ddddocr section |
| 分點 (上櫃, today) | TPEx | `https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html` | Cloudflare Turnstile — see Playwright section |
| 分點歷史 (paid) | FinMind sponsor | `dataset=TaiwanStockTradingDailyReport` | Sponsor tier required |
| 股票代號 → 中文名 | TWSE ISIN | `https://isin.twse.com.tw/isin/C_public.jsp?strMode=2` (上市) or `strMode=4` (上櫃) | HTML page, decode with **cp950** not big5 |
| 股票代號 → 中文名 + 產業 (per stock) | FinMind | `dataset=TaiwanStockInfo&data_id={code}` | JSON, easier than ISIN for single lookups |
| 概念股名單 (CPO/AI伺服器/etc) | None public | Manually curate JSON | Goodinfo/cnyes/Statementdog all blocked or paid |

## Critical Pitfalls

### `www.twse.com.tw` rate-limits aggressively
Repeated requests get HTTP 307 with body "FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED". This is an IP ban, not a header issue. **Use `openapi.twse.com.tw` for snapshot data instead** — same data, no blocking.

The block lasts hours and affects multiple `www.twse.com.tw` paths simultaneously. Recovery: wait or switch endpoints.

### 借券賣出餘額 unit is 股, not 張
TWT93U returns values in shares (股). Divide by 1000 for 張. Do NOT do this for 議借交易 (`t13sa710`) which already reports in 張 ("交易單位").

### Chinese encoding: use cp950, NOT big5
TWSE/TPEx legacy pages serve Big5-encoded HTML. Python's built-in `big5` codec misses chars like `碁` (in `啟碁`/`啟碁`). Always use `cp950` (a Big5 superset) instead:
```python
text = response.content.decode("cp950", errors="replace")
```

### FinMind tier gates specific datasets
Free tier: `TaiwanStockMarginPurchaseShortSale`, `TaiwanStockPrice`, `TaiwanStockInstitutionalInvestorsBuySell`, etc.
Sponsor-only (returns 400 "Your level is register"): `TaiwanStockTradingDailyReport`, `TaiwanStockSecuritiesLending`, `TaiwanTotalExchangeMarginMaintenance`.
Free tier rate limit: ~600 req/hr per token. Beyond that, 403.

### Yahoo Finance "chartPreviousClose" is misleading
`meta.regularMarketPrice` is current price, but `meta.chartPreviousClose` is the close BEFORE the chart range starts (e.g., for 5d range, that's 6 days ago). For today's % change, use the second-to-last close from `indicators.quote[0].close`:
```python
closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
yesterday = closes[-2]  # NOT meta.chartPreviousClose
change_pct = (current - yesterday) / yesterday * 100
```

### TPEx OpenAPI uses ROC dates and PascalCase fields
Field names are English PascalCase (`MarginPurchaseBalance`, `SecuritiesBorrowingBalanceOfTheMarketDay`), not Chinese. Date format is ROC integer (`1150421` = 2026-04-21). Different from TWSE OpenAPI which uses Chinese field names.

### 概念股 name lists are not publicly available
There is NO free programmatic source for theme/concept stock lists (CPO, AI伺服器, 矽光子, etc.). Goodinfo blocks scrapers, Statementdog uses non-enumerable tag IDs, FinMind doesn't carry this dataset. Maintain a manual JSON; update quarterly. Don't waste effort scraping.

## CAPTCHA and Anti-Bot Bypass

Two distinct challenges in Taiwan financial sites — handle differently:

### 1. Simple image CAPTCHA (TWSE BSR)
5-character alphanumeric image. Use `ddddocr` (Python, ~95% accuracy on this style):

```python
import ddddocr, requests, re

ocr = ddddocr.DdddOcr(show_ad=False)
session = requests.Session()
r = session.get("https://bsr.twse.com.tw/bshtm/bsMenu.aspx")
viewstate = re.search(r'name="__VIEWSTATE".+?value="([^"]+)"', r.text).group(1)
generator = re.search(r'name="__VIEWSTATEGENERATOR".+?value="([^"]+)"', r.text).group(1)
validation = re.search(r'name="__EVENTVALIDATION".+?value="([^"]+)"', r.text).group(1)
captcha_url = "https://bsr.twse.com.tw/bshtm/" + re.search(r"src='(CaptchaImage[^']+)'", r.text).group(1)

img = session.get(captcha_url).content
solved = ocr.classification(img)  # 5-char string

# Validate before submitting
if len(solved) != 5: continue  # retry with new page

session.post("https://bsr.twse.com.tw/bshtm/bsMenu.aspx", data={
    "__VIEWSTATE": viewstate,
    "__VIEWSTATEGENERATOR": generator,
    "__EVENTVALIDATION": validation,
    "RadioButton_Normal": "RadioButton_Normal",
    "TextBox_Stkno": stock_code,
    "CaptchaControl1": solved,
    "btnOK": "查詢",
})
# Response contains "HyperLink_DownloadCSV" link if successful, "查無資料" if no data
```

Important: ALL three hidden fields (`__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`) are required. Missing any → 307 redirect to error page.

Failed CAPTCHA shows in response: `驗證碼錯誤` (retry) or `查無資料` (give up — stock truly has no BSR data today).

### 2. Cloudflare Turnstile (TPEx new pages)
Pure headless mode (`headless=True`) does NOT solve Turnstile — Cloudflare detects it. Two requirements:

1. Use `patchright` (drop-in playwright fork with anti-detection patches), NOT plain `playwright`
2. Run in `headless=False` mode under `Xvfb` virtual display

```bash
pip install patchright
python3 -m patchright install chromium
sudo apt install xvfb libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
                 libcups2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
                 libgbm1 libxkbcommon0 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0
```

```python
import os, subprocess, time
from patchright.sync_api import sync_playwright

# Start Xvfb on :99 and override DISPLAY
proc = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1920x1080x24"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.environ["DISPLAY"] = ":99"
time.sleep(1)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()  # Default context — do NOT customize viewport/locale/UA, they trip detection
    page.goto(url, wait_until="domcontentloaded")

    # Wait for Turnstile to auto-solve (~3s)
    for _ in range(20):
        time.sleep(1)
        token = page.evaluate("() => document.querySelector('input[name=\"cf-turnstile-response\"]')?.value || ''")
        if token:
            break

    # Submit form, then capture downloaded CSV
    page.fill('#tables-form input[name="code"]', stock_code)
    with page.expect_download(timeout=30000) as dl:
        page.click('button[data-format="csv"]')
    with open(dl.value.path(), "rb") as f:
        csv = f.read().decode("cp950", errors="replace")

    browser.close()
proc.terminate()
```

Key gotchas:
- Default `browser.new_page()` works; custom `new_context(viewport=..., locale=..., user_agent=...)` triggers detection
- DON'T set `DISPLAY=:0` if WSL has a real display — Cloudflare still detects something. Use fresh `:99` Xvfb.
- Headless `True` always fails. No way around this without paid 2captcha service.

## Common Workflow Patterns

### Snapshot today + history per stock
1. Hit OpenAPI once for full-market snapshot (bulk)
2. Filter to your stock list
3. For each stock, FinMind history API (per-stock, retry on 403 with backoff)
4. Yahoo Finance for prices in parallel

### Resolving Chinese stock names
Don't translate from Yahoo's `shortName` (English mangled) — fetch TWSE ISIN once, cache 7 days:
```python
import urllib.request, re
def fetch_isin(mode):  # mode=2 listed, 4 OTC
    url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
    raw = urllib.request.urlopen(url, timeout=30).read()
    text = raw.decode("cp950", errors="replace")
    return dict(re.findall(r"<td[^>]*>([A-Z0-9]{3,6})[　\s]+([^<\s][^<]*?)</td>", text))
```

### Daily cron pipeline
For accumulating today-only data (BSR, TPEx broker), run cron `Mon-Fri 18:00` (BSR publishes ~17:30). For 借券賣出餘額, schedule `21:30` (TWT93U publishes after 21:00). 議借交易 (`t13sa710`) is available immediately after market close (~14:00).

## Output Format Conventions

When showing financial data to users (especially Telegram messages):
- 餘額 in 張, not 股. Divide TWT93U values by 1000.
- Use Chinese stock names from ISIN, not Yahoo English
- Currency: NTD with `$` prefix
- Date: `YYYY-MM-DD` for display, `YYYYMMDD` for filenames/queries
- Stock code first, name second: `2330 台積電`
- Market tag: `[上市]` or `[上櫃]` after name

## When NOT to Use This Skill

- For non-Taiwan markets — different ecosystem
- For options/futures data — separate set of endpoints not covered here
- For order book / Level 2 data — only 真券商 APIs have this, not public
- For real-time intraday — these endpoints are end-of-day or with delay; use a broker API for tick data
