#!/usr/bin/env python3
"""
台股借券異常監控
1. 議借量突增：議借量 > 5日均量 ×2 且 利率 <1% 或 >7%
2. 借券賣出大幅減少：當日餘額比前日餘額減少 >10%
資料來源：TWSE SBL API + Yahoo Finance
"""

import argparse
import json
import urllib.request
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta
import sys
import time

DEFAULT_CHAT_ID = "-5229750819"
TWSE_SBL_URL = "https://www.twse.com.tw/SBL/t13sa710"
TWSE_SBL_BALANCE_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def to_ad_date(roc_date_str: str) -> str:
    """Convert ROC date string like '115年04月17日' to 'YYYYMMDD'."""
    roc_date_str = roc_date_str.strip()
    parts = roc_date_str.replace("年", "/").replace("月", "/").replace("日", "").split("/")
    if len(parts) == 3:
        year = int(parts[0]) + 1911
        return f"{year}{int(parts[1]):02d}{int(parts[2]):02d}"
    return roc_date_str


def get_trading_dates(target_date: str, days: int = 6) -> tuple[str, str]:
    """Return (start_date, end_date) in YYYYMMDD for fetching data.
    Goes back extra days to account for weekends/holidays."""
    dt = datetime.strptime(target_date, "%Y%m%d")
    start = dt - timedelta(days=days + 10)  # extra buffer for holidays
    return start.strftime("%Y%m%d"), target_date


def fetch_twse_lending(start_date: str, end_date: str) -> list[dict]:
    """Fetch negotiated lending data from TWSE SBL API."""
    url = f"{TWSE_SBL_URL}?startDate={start_date}&endDate={end_date}&type=N&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] TWSE API 失敗: {e}", file=sys.stderr)
        return []

    if data.get("stat") != "OK" or not data.get("data"):
        print(f"[WARN] TWSE API 回傳無資料: {data.get('stat')}", file=sys.stderr)
        return []

    records = []
    for row in data["data"]:
        date_str = to_ad_date(row[0])
        code_name = row[1].strip()
        tx_type = row[2].strip()

        if tx_type != "議借":
            continue

        parts = code_name.split()
        if len(parts) < 2:
            continue
        code = parts[0].strip()
        name = " ".join(parts[1:]).strip()

        try:
            volume = int(str(row[3]).replace(",", ""))
        except (ValueError, IndexError):
            continue

        try:
            fee_rate = float(str(row[4]).replace(",", ""))
        except (ValueError, IndexError):
            fee_rate = 0.0

        try:
            close_price = float(str(row[5]).replace(",", ""))
        except (ValueError, IndexError):
            close_price = 0.0

        records.append({
            "date": date_str,
            "code": code,
            "name": name,
            "volume": volume,
            "fee_rate": fee_rate,
            "close_price": close_price,
        })

    return records


def fetch_sbl_short_selling(date_str: str) -> list[dict]:
    """Fetch daily SBL short selling balance from TWSE TWT93U.
    Returns stocks where 借券賣出餘額 decreased >10% from previous day."""
    url = f"{TWSE_SBL_BALANCE_URL}?date={date_str}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] TWSE TWT93U API 失敗: {e}", file=sys.stderr)
        return []

    if data.get("stat") != "OK" or not data.get("data"):
        print(f"[WARN] TWSE TWT93U 無資料: {data.get('stat')}", file=sys.stderr)
        return []

    results = []
    for row in data["data"]:
        if len(row) < 14:
            continue
        code = row[0].strip()
        name = row[1].strip()

        try:
            # Values are in shares (股); convert to lots (張)
            prev_balance = int(str(row[8]).replace(",", "")) / 1000
            today_balance = int(str(row[12]).replace(",", "")) / 1000
        except (ValueError, IndexError):
            continue

        if prev_balance <= 0:
            continue

        change_pct = ((today_balance - prev_balance) / prev_balance) * 100

        if change_pct > -10.0:
            continue

        results.append({
            "code": code,
            "name": name,
            "prev_balance": prev_balance,
            "today_balance": today_balance,
            "change_pct": change_pct,
        })

    results.sort(key=lambda x: x["change_pct"])
    return results


def fetch_stock_info(code: str) -> dict:
    """Fetch current price, change%, volume from Yahoo Finance."""
    for suffix in [".TW", ".TWO"]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=5d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta["regularMarketPrice"]

            indicators = result.get("indicators", {}).get("quote", [{}])[0]
            volumes = indicators.get("volume", [])
            volumes = [v for v in volumes if v is not None]
            closes = indicators.get("close", [])
            closes = [c for c in closes if c is not None]

            today_vol = volumes[-1] if volumes else 0
            prev_vol = volumes[-2] if len(volumes) >= 2 else 0
            vol_change_pct = ((today_vol - prev_vol) / prev_vol * 100) if prev_vol else 0

            # Today's change: compare today's close to yesterday's close
            if len(closes) >= 2:
                yest_close = closes[-2]
                change_pct = ((price - yest_close) / yest_close * 100) if yest_close else 0
            else:
                change_pct = 0

            # Yesterday's change: compare yesterday's close to day-before's close
            if len(closes) >= 3:
                yest_close = closes[-2]
                day_before = closes[-3]
                yest_change_pct = ((yest_close - day_before) / day_before * 100) if day_before else 0
            else:
                yest_change_pct = 0

            market = "上櫃" if suffix == ".TWO" else "上市"
            return {
                "price": price,
                "change_pct": change_pct,
                "yest_change_pct": yest_change_pct,
                "volume": today_vol,
                "vol_change_pct": vol_change_pct,
                "market": market,
            }
        except Exception:
            continue
    return {}


def analyze_lending(records: list[dict], target_date: str) -> list[dict]:
    """Analyze lending data: find stocks with volume spike >100% vs 5-day avg
    AND fee rate <1% or >7%."""

    daily = defaultdict(lambda: {"volume": 0, "weighted_fee": 0.0, "name": "", "close_price": 0.0})

    for r in records:
        key = (r["code"], r["date"])
        daily[key]["volume"] += r["volume"]
        daily[key]["weighted_fee"] += r["fee_rate"] * r["volume"]
        daily[key]["name"] = r["name"]
        daily[key]["close_price"] = r["close_price"]

    for key in daily:
        vol = daily[key]["volume"]
        if vol > 0:
            daily[key]["avg_fee_rate"] = daily[key]["weighted_fee"] / vol
        else:
            daily[key]["avg_fee_rate"] = 0.0

    all_dates = sorted(set(d for _, d in daily.keys()))

    if target_date not in all_dates:
        if all_dates:
            target_date = all_dates[-1]
        else:
            return []

    target_idx = all_dates.index(target_date)
    prior_dates = all_dates[max(0, target_idx - 5):target_idx]

    target_stocks = {code for (code, date) in daily if date == target_date}

    results = []
    for code in target_stocks:
        today_data = daily.get((code, target_date))
        if not today_data or today_data["volume"] == 0:
            continue

        today_vol = today_data["volume"]
        today_rate = today_data["avg_fee_rate"]

        if not (today_rate < 1.0 or today_rate > 7.0):
            continue

        prior_vols = []
        for d in prior_dates:
            v = daily.get((code, d), {}).get("volume", 0)
            if v > 0:
                prior_vols.append(v)

        if not prior_vols:
            avg_5d = 0
        else:
            avg_5d = sum(prior_vols) / len(prior_vols)

        if avg_5d > 0:
            spike_pct = ((today_vol - avg_5d) / avg_5d) * 100
        else:
            spike_pct = 999.0

        if spike_pct < 100.0:
            continue

        results.append({
            "code": code,
            "name": today_data["name"],
            "today_vol": today_vol,
            "avg_5d": avg_5d,
            "spike_pct": spike_pct,
            "fee_rate": today_rate,
            "close_price": today_data["close_price"],
            "rate_category": "low" if today_rate < 1.0 else "high",
        })

    results.sort(key=lambda x: x["spike_pct"], reverse=True)
    return results


def enrich_with_stock_info(results: list[dict]) -> list[dict]:
    """Add stock price and volume info from Yahoo Finance."""
    for r in results:
        info = fetch_stock_info(r["code"])
        if info:
            r["price"] = info["price"]
            r["change_pct"] = info["change_pct"]
            r["trade_volume"] = info["volume"]
            r["vol_change_pct"] = info["vol_change_pct"]
            r["market"] = info["market"]
        else:
            r["price"] = r.get("close_price", 0)
            r["change_pct"] = 0
            r["trade_volume"] = 0
            r["vol_change_pct"] = 0
            r["market"] = "上市"
        time.sleep(0.2)
    return results


def format_lending_output(results: list[dict], target_date: str) -> str:
    """Format 議借量異常 results as a separate message."""
    dt = datetime.strptime(target_date, "%Y%m%d")
    date_str = dt.strftime("%Y-%m-%d")

    lines = [f"借券議借異常監控 {date_str}\n"]

    if not results:
        lines.append("今日無符合條件的標的")
        return "\n".join(lines)

    low_rate = [r for r in results if r["rate_category"] == "low"]
    high_rate = [r for r in results if r["rate_category"] == "high"]

    def format_stock(r):
        sign = "+" if r["change_pct"] >= 0 else ""
        vol_sign = "+" if r["vol_change_pct"] >= 0 else ""
        avg_str = f"{r['avg_5d']:,.0f}" if r["avg_5d"] > 0 else "N/A"
        spike_str = f"+{r['spike_pct']:.0f}%" if r["avg_5d"] > 0 else "新出現"
        vol_str = f"{r['trade_volume']:,.0f}" if r['trade_volume'] else "N/A"
        vol_chg = f"({vol_sign}{r['vol_change_pct']:.0f}%)" if r['trade_volume'] else ""

        return (
            f"{r['code']} {r['name']} [{r['market']}]\n"
            f"  議借量: {r['today_vol']:,}張 | 5日均: {avg_str}張 | {spike_str}\n"
            f"  利率: {r['fee_rate']:.2f}% | 收盤: ${r['price']:,.2f} {sign}{r['change_pct']:.2f}%\n"
            f"  成交量: {vol_str}張 {vol_chg}"
        )

    if low_rate:
        lines.append("利率 <1%（低利率，可能有特定目的借券）")
        lines.append("━━━━━━━━━━━━")
        for r in low_rate:
            lines.append(format_stock(r))
            lines.append("")

    if high_rate:
        lines.append("利率 >7%（高利率，借券需求強勁）")
        lines.append("━━━━━━━━━━━━")
        for r in high_rate:
            lines.append(format_stock(r))
            lines.append("")

    lines.append(f"共篩出 {len(results)} 檔標的")
    return "\n".join(lines)


def format_sbl_output(sbl_results: list[dict], target_date: str) -> str:
    """Format 借券賣出大幅減少 results as a separate message."""
    dt = datetime.strptime(target_date, "%Y%m%d")
    date_str = dt.strftime("%Y-%m-%d")

    lines = [f"借券賣出大幅減少監控 {date_str}\n"]

    if not sbl_results:
        lines.append("今日無符合條件的標的")
        return "\n".join(lines)

    def format_sbl_stock(r):
        today_sign = "+" if r.get("change_pct_price", 0) >= 0 else ""
        yest_sign = "+" if r.get("yest_change_pct", 0) >= 0 else ""
        market = r.get("market", "上市")
        return (
            f"{r['code']} {r['name']} [{market}]\n"
            f"  借券賣出餘額: {r['today_balance']:,.0f}張 | 昨日: {r['prev_balance']:,.0f}張 | {r['change_pct']:.1f}%\n"
            f"  昨日漲幅: {yest_sign}{r.get('yest_change_pct', 0):.2f}% | 今日: ${r.get('price', 0):,.2f} {today_sign}{r.get('change_pct_price', 0):.2f}%"
        )

    # Highlight: 借券減少 + 今日上漲（空方回補 + 股價上漲）
    bullish = [r for r in sbl_results if r.get("change_pct_price", 0) > 0]
    others = [r for r in sbl_results if r.get("change_pct_price", 0) <= 0]

    if bullish:
        lines.append("借券減少且今日上漲（轉多訊號）")
        lines.append("━━━━━━━━━━━━")
        for r in bullish:
            lines.append(format_sbl_stock(r))
            lines.append("")
        lines.append(f"精選 {len(bullish)} 檔")
        lines.append("")

    if others:
        lines.append("其他借券減少標的")
        lines.append("━━━━━━━━━━━━")
        for r in others:
            lines.append(format_sbl_stock(r))
            lines.append("")

    lines.append(f"共篩出 {len(sbl_results)} 檔標的")
    return "\n".join(lines)


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    """Send message via Telegram Bot API. Splits long messages at 4096 char limit."""
    url = TG_API_URL.format(token=bot_token)

    max_len = 4000
    chunks = []
    if len(message) <= max_len:
        chunks = [message]
    else:
        lines = message.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > max_len:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            chunks.append(chunk)

    all_ok = True
    for i, text in enumerate(chunks):
        payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                if not result.get("ok", False):
                    all_ok = False
        except Exception as e:
            print(f"[ERROR] Telegram 推送失敗 (part {i+1}): {e}", file=sys.stderr)
            all_ok = False
        if i < len(chunks) - 1:
            time.sleep(0.5)
    return all_ok


def is_trading_day(date_str: str) -> bool:
    """Check if the given date is a weekday (basic check, doesn't account for holidays)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    return dt.weekday() < 5


def main():
    parser = argparse.ArgumentParser(description="台股借券異常監控")
    parser.add_argument("--date", help="指定日期 YYYYMMDD（預設今天）")
    parser.add_argument("--mode", choices=["lending", "sbl", "both"], default="both",
                        help="lending=只跑議借異常, sbl=只跑借券賣出減少, both=兩個都跑（預設）")
    parser.add_argument("--telegram", action="store_true", help="推送到 Telegram")
    parser.add_argument("--bot-token", help="Telegram Bot Token（或設 TG_BOT_TOKEN 環境變數）")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID, help="Telegram Chat ID")
    args = parser.parse_args()

    import os
    bot_token = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")

    target_date = args.date or datetime.now().strftime("%Y%m%d")

    if not is_trading_day(target_date):
        print(f"{target_date} 非交易日，跳過")
        return

    print(f"正在抓取 {target_date} 借券資料 (mode={args.mode})...")

    lending_output = None
    sbl_output = None

    # 1. 議借量異常
    if args.mode in ("lending", "both"):
        start_date, end_date = get_trading_dates(target_date)
        records = fetch_twse_lending(start_date, end_date)

        if records:
            print(f"取得 {len(records)} 筆議借記錄，分析中...")
            results = analyze_lending(records, target_date)
            if results:
                print(f"篩出 {len(results)} 檔議借異常標的，抓取股價資訊...")
                results = enrich_with_stock_info(results)
        else:
            print("無法取得議借資料")
            results = []

        lending_output = format_lending_output(results, target_date)
        print("\n" + lending_output)

    # 2. 借券賣出大幅減少
    if args.mode in ("sbl", "both"):
        if args.mode == "both":
            time.sleep(3)  # avoid TWSE rate limiting
        print("抓取借券賣出餘額資料...")
        sbl_results = fetch_sbl_short_selling(target_date)
        if sbl_results:
            print(f"篩出 {len(sbl_results)} 檔借券賣出減少標的，抓取股價資訊...")
            for r in sbl_results:
                info = fetch_stock_info(r["code"])
                if info:
                    r["price"] = info["price"]
                    r["change_pct_price"] = info["change_pct"]
                    r["yest_change_pct"] = info["yest_change_pct"]
                    r["market"] = info["market"]
                else:
                    r["price"] = 0
                    r["change_pct_price"] = 0
                    r["yest_change_pct"] = 0
                    r["market"] = "上市"
                time.sleep(0.2)
        else:
            print("無借券賣出大幅減少的標的")

        sbl_output = format_sbl_output(sbl_results, target_date)
        print("\n" + sbl_output)

    if args.telegram:
        if not bot_token:
            print("[ERROR] 需要 Telegram Bot Token（--bot-token 或 TG_BOT_TOKEN 環境變數）", file=sys.stderr)
            sys.exit(1)
        print("\n推送到 Telegram...")
        all_ok = True
        if lending_output:
            if not send_telegram(lending_output, bot_token, args.chat_id):
                all_ok = False
            time.sleep(1)
        if sbl_output:
            if not send_telegram(sbl_output, bot_token, args.chat_id):
                all_ok = False
        if all_ok:
            print("推送成功!")
        else:
            print("部分推送失敗!", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
