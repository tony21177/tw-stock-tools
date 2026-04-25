#!/usr/bin/env python3
"""
TPEx 上櫃券商買賣日報表查詢系統爬蟲

頁面：https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html
使用 Cloudflare Turnstile 防爬，須用 patchright + Xvfb (headed mode) 才能繞過。

注意：TPEx 同樣只有「當日」資料，沒有歷史日期參數。
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from patchright.sync_api import sync_playwright

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bsr_cache")
TPEX_BROKER_URL = "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/brokerBS.html"


def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _parse_csv(text: str) -> dict:
    """Parse TPEx CSV: 序號,券商,價格,買進股數,賣出股數
    Returns {broker_id: {name, buy, sell}}."""
    aggregates = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line or not line.startswith('"') or not line[1].isdigit():
            continue
        # CSV with quoted values
        parts = re.findall(r'"([^"]*)"', line)
        if len(parts) < 5:
            continue
        try:
            seq = int(parts[0])
            broker = parts[1].strip()
            buy = int(parts[3].replace(",", ""))
            sell = int(parts[4].replace(",", ""))
        except (ValueError, IndexError):
            continue
        m = re.match(r"^([A-Z0-9]{4,6})\s+(.+)$", broker)
        if m:
            bid, bname = m.group(1), m.group(2).strip()
        else:
            bid, bname = broker[:4], broker[4:].strip()

        agg = aggregates.setdefault(bid, {"name": bname, "buy": 0, "sell": 0})
        agg["buy"] += buy
        agg["sell"] += sell
    return aggregates


def _start_xvfb() -> tuple[subprocess.Popen | None, str]:
    """Start a fresh Xvfb on display :99 and override DISPLAY env.
    Returns (process, display). Always uses Xvfb to avoid issues with
    real X servers that may have anti-headless detection quirks."""
    display = ":99"
    # Clean up any existing Xvfb on :99
    subprocess.run(["pkill", "-f", "Xvfb :99"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1920x1080x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    os.environ["DISPLAY"] = display
    return proc, display


def fetch_tpex_broker(stock_code: str, max_attempts: int = 3) -> dict:
    """Fetch TPEx broker data for one OTC stock.
    Returns dict similar to bsr_scraper format."""
    xvfb_proc, _ = _start_xvfb()
    try:
        with sync_playwright() as p:
            for attempt in range(max_attempts):
                browser = p.chromium.launch(headless=False)
                try:
                    page = browser.new_page()
                    page.goto(TPEX_BROKER_URL, wait_until="domcontentloaded", timeout=30000)

                    # Wait for Turnstile to auto-solve
                    token = ""
                    for _ in range(25):
                        time.sleep(1)
                        token = page.evaluate("""() => {
                            const i = document.querySelector('input[name="cf-turnstile-response"]');
                            return i ? i.value : '';
                        }""")
                        if token:
                            break
                    if not token:
                        print(f"[WARN] {stock_code} no Turnstile token", file=sys.stderr)
                        continue

                    # Fill code, then click CSV download (BIG5)
                    page.fill('#tables-form input[name="code"]', stock_code)
                    try:
                        with page.expect_download(timeout=30000) as dl_info:
                            page.click('button[data-format="csv"]')
                        download = dl_info.value
                        with open(download.path(), "rb") as f:
                            csv_bytes = f.read()
                    except Exception as e:
                        # Maybe no data — check page text
                        text = page.locator("#tables-content").inner_text() if page.locator("#tables-content").count() else ""
                        if "查無" in text or "無資料" in text:
                            return {"date": datetime.now().strftime("%Y%m%d"),
                                    "stock_code": stock_code, "brokers": {},
                                    "total_buy": 0, "total_sell": 0, "no_data": True}
                        print(f"[WARN] {stock_code} download failed: {e}", file=sys.stderr)
                        continue

                    text = csv_bytes.decode("cp950", errors="replace")
                    brokers = _parse_csv(text)
                    if not brokers:
                        continue
                    total_buy = sum(b["buy"] for b in brokers.values())
                    total_sell = sum(b["sell"] for b in brokers.values())
                    return {
                        "date": datetime.now().strftime("%Y%m%d"),
                        "stock_code": stock_code,
                        "brokers": brokers,
                        "total_buy": total_buy,
                        "total_sell": total_sell,
                        "source": "tpex",
                    }
                finally:
                    browser.close()
    finally:
        if xvfb_proc:
            xvfb_proc.terminate()
    return {}


def fetch_and_cache_tpex(stock_code: str, force: bool = False) -> dict:
    """Cached version of fetch_tpex_broker."""
    _ensure_cache()
    today = datetime.now().strftime("%Y%m%d")
    cache_file = os.path.join(CACHE_DIR, f"{stock_code}_{today}.json")
    if os.path.exists(cache_file) and not force:
        with open(cache_file) as f:
            return json.load(f)
    data = fetch_tpex_broker(stock_code)
    if data:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TPEx broker scraper test")
    parser.add_argument("code", help="上櫃股票代號")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    data = fetch_and_cache_tpex(args.code, force=args.force)
    if not data:
        print(f"[ERROR] failed to fetch {args.code}")
        sys.exit(1)
    if data.get("no_data"):
        print(f"{args.code}: no broker data on TPEx today")
        return

    print(f"{args.code} TPEx ({data['date']})")
    print(f"全市場買 {data['total_buy']:,} 賣 {data['total_sell']:,}")
    print(f"分點數: {len(data['brokers'])}")
    sorted_brokers = sorted(data["brokers"].items(),
                             key=lambda x: x[1]["buy"] - x[1]["sell"], reverse=True)
    print("Top 10 買超分點:")
    for bid, info in sorted_brokers[:10]:
        net = info["buy"] - info["sell"]
        print(f"  {bid} {info['name']:<20} 買 {info['buy']:>10,} / 賣 {info['sell']:>10,} = 淨 {net:+,}")


if __name__ == "__main__":
    main()
