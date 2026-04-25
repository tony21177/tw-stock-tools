#!/usr/bin/env python3
"""
TWSE BSR (券商買賣日報) 爬蟲 - 用 ddddocr 解 CAPTCHA。
BSR 只有當日資料，需每天跑一次累積歷史。

CSV 解析：
  欄位：序號, 券商, 價格, 買進股數, 賣出股數
  券商欄位格式：「1020合　　庫」(代碼+全形空格+名稱)，左邊 4 碼是券商分點代碼

每筆 CSV 約 6,000+ 行（每股票每日），按價格逐筆紀錄。
我們將其彙總成「每分點當日總買進、總賣出」。
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests

try:
    import ddddocr
except ImportError:
    print("[ERROR] need: pip install ddddocr", file=sys.stderr)
    raise

BSR_URL = "https://bsr.twse.com.tw/bshtm/bsMenu.aspx"
BSR_BASE = "https://bsr.twse.com.tw/bshtm/"

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bsr_cache")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

_ocr = None


def _get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr


def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _parse_form(html: str) -> dict:
    """Extract VIEWSTATE etc. from BSR form page."""
    fields = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        m = re.search(rf'name="{name}"\s+id="{name}"\s+value="([^"]+)"', html)
        if m:
            fields[name] = m.group(1)
    m = re.search(r"src='(CaptchaImage\.aspx\?guid=[a-f0-9-]+)'", html)
    if m:
        fields["_captcha_url"] = BSR_BASE + m.group(1)
    return fields


def _parse_bsr_csv(text: str) -> dict:
    """Parse the BSR CSV into per-broker buy/sell aggregates.
    Returns: {broker_branch_id: {name, buy, sell}}
    Volume is in shares (股), needs /1000 if you want 張."""
    aggregates = {}
    # Skip header lines
    lines = text.split("\n")
    # Header is lines 0-2 (title, stock code, columns)
    for line in lines[3:]:
        line = line.strip()
        if not line:
            continue
        # Each row may have two records (left + right pair)
        # CSV format: seq, broker, price, buy, sell, , seq, broker, price, buy, sell
        parts = [p.strip() for p in line.split(",")]
        # Process in two halves
        for offset in (0, 6):
            if len(parts) < offset + 5:
                continue
            seq = parts[offset]
            broker = parts[offset + 1]
            try:
                buy = int(parts[offset + 3])
                sell = int(parts[offset + 4])
            except (ValueError, IndexError):
                continue
            if not broker:
                continue
            # broker like "1020合　　庫" — first 4 chars are id, rest is name
            broker = broker.replace("　", " ").strip()
            broker_id_match = re.match(r"^([A-Z0-9]{4,6})\s+(.+)$", broker)
            if broker_id_match:
                broker_id = broker_id_match.group(1)
                broker_name = broker_id_match.group(2).strip()
            else:
                broker_id = broker[:4]
                broker_name = broker[4:].strip()

            agg = aggregates.setdefault(broker_id, {"name": broker_name, "buy": 0, "sell": 0})
            agg["buy"] += buy
            agg["sell"] += sell
    return aggregates


def fetch_bsr(stock_code: str, max_attempts: int = 5,
              session: requests.Session | None = None) -> dict:
    """Fetch and parse BSR data for one stock (today only).
    Returns dict {date, stock_code, brokers: {id: {name, buy, sell}}, total_buy, total_sell}.
    Returns empty dict on failure after max_attempts."""
    if session is None:
        session = requests.Session()
    headers = {"User-Agent": UA}
    ocr = _get_ocr()

    for attempt in range(max_attempts):
        try:
            r = session.get(BSR_URL, headers=headers, timeout=30)
            form = _parse_form(r.text)
            if not form.get("__VIEWSTATE"):
                time.sleep(1)
                continue

            img_r = session.get(form["_captcha_url"], headers=headers, timeout=15)
            solved = ocr.classification(img_r.content)

            data = {
                "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
                "__VIEWSTATE": form["__VIEWSTATE"],
                "__VIEWSTATEGENERATOR": form["__VIEWSTATEGENERATOR"],
                "__EVENTVALIDATION": form["__EVENTVALIDATION"],
                "RadioButton_Normal": "RadioButton_Normal",
                "TextBox_Stkno": stock_code,
                "CaptchaControl1": solved,
                "btnOK": "查詢",
            }
            r2 = session.post(BSR_URL, data=data, headers=headers, timeout=30, allow_redirects=True)

            if "HyperLink_DownloadCSV" not in r2.text:
                # CAPTCHA or query failed; retry
                time.sleep(0.5)
                continue

            # Find CSV link
            link_match = re.search(r'href="(bsContent\.aspx\?StkNo=[^"]+)"', r2.text)
            if not link_match:
                continue
            csv_url = BSR_BASE + link_match.group(1).replace("&amp;", "&")

            csv_r = session.get(csv_url, headers=headers, timeout=30)
            if csv_r.status_code != 200:
                continue

            text = csv_r.content.decode("cp950", errors="replace")
            brokers = _parse_bsr_csv(text)
            total_buy = sum(b["buy"] for b in brokers.values())
            total_sell = sum(b["sell"] for b in brokers.values())
            return {
                "date": datetime.now().strftime("%Y%m%d"),
                "stock_code": stock_code,
                "brokers": brokers,
                "total_buy": total_buy,
                "total_sell": total_sell,
                "captcha_attempts": attempt + 1,
            }
        except Exception as e:
            print(f"[WARN] BSR {stock_code} attempt {attempt+1}: {e}", file=sys.stderr)
            time.sleep(1)

    return {}


def fetch_and_cache(stock_code: str, force: bool = False) -> dict:
    """Fetch BSR for stock, cache to disk. Returns parsed data."""
    _ensure_cache()
    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CACHE_DIR, f"{stock_code}_{today}.json")
    if os.path.exists(cache_file) and not force:
        with open(cache_file) as f:
            return json.load(f)

    data = fetch_bsr(stock_code)
    if data:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


def load_history(stock_code: str, days: int = 5) -> list[dict]:
    """Load past N days of BSR cache for a stock. Returns list ordered by date asc."""
    _ensure_cache()
    files = []
    pattern = re.compile(rf"^{re.escape(stock_code)}_(\d{{8}})\.json$")
    for fname in os.listdir(CACHE_DIR):
        m = pattern.match(fname)
        if m:
            files.append((m.group(1), os.path.join(CACHE_DIR, fname)))
    files.sort()
    selected = files[-days:] if len(files) >= days else files
    result = []
    for date, path in selected:
        with open(path) as f:
            result.append(json.load(f))
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TWSE BSR scraper test")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--force", action="store_true", help="重新抓取（忽略快取）")
    args = parser.parse_args()

    data = fetch_and_cache(args.code, force=args.force)
    if not data:
        print(f"[ERROR] 無法取得 {args.code} BSR 資料")
        sys.exit(1)

    print(f"{args.code} BSR ({data['date']}) - 嘗試 {data.get('captcha_attempts', 1)} 次")
    print(f"全市場買進: {data['total_buy']:,} 股 / 賣出: {data['total_sell']:,} 股")
    print(f"分點數: {len(data['brokers'])}")
    print()
    # Top 10 net buyers
    sorted_brokers = sorted(data["brokers"].items(), key=lambda x: x[1]["buy"] - x[1]["sell"], reverse=True)
    print("Top 10 買超分點:")
    for bid, info in sorted_brokers[:10]:
        net = info["buy"] - info["sell"]
        print(f"  {bid} {info['name']:<20} 買 {info['buy']:>10,} / 賣 {info['sell']:>10,} = 淨 {net:+,}")


if __name__ == "__main__":
    main()
