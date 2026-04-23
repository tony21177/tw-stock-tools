#!/usr/bin/env python3
"""
台股借券單檔查詢
查詢指定股票昨天和今天的：
  - 借券交易（定價/競價/議借）
  - 還券
  - 借券賣出餘額
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

TWSE_SBL_URL = "https://www.twse.com.tw/SBL/t13sa710"
TWSE_SBL_RETURN_URL = "https://www.twse.com.tw/SBL/t13sa870"
TWSE_SBL_BALANCE_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U"
TPEX_SBL_BALANCE_URL = "https://www.tpex.org.tw/www/zh-tw/margin/sbl"


def to_ad_date(roc_str: str) -> str:
    """115年04月21日 -> 20260421"""
    s = roc_str.strip().replace("年", "/").replace("月", "/").replace("日", "")
    parts = s.split("/")
    if len(parts) == 3:
        return f"{int(parts[0]) + 1911}{int(parts[1]):02d}{int(parts[2]):02d}"
    return roc_str


def fetch_lending_transactions(code: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch all lending transactions (all types) for a stock code."""
    url = f"{TWSE_SBL_URL}?startDate={start_date}&endDate={end_date}&stockNo={code}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] TWSE SBL API: {e}", file=sys.stderr)
        return []

    if data.get("stat") != "OK" or not data.get("data"):
        return []

    records = []
    for row in data["data"]:
        date_str = to_ad_date(row[0])
        code_name = row[1].strip()
        tx_type = row[2].strip()
        try:
            volume = int(str(row[3]).replace(",", ""))
            fee_rate = float(str(row[4]).replace(",", ""))
        except (ValueError, IndexError):
            continue

        records.append({
            "date": date_str,
            "name": code_name,
            "type": tx_type,
            "volume": volume,
            "fee_rate": fee_rate,
        })
    return records


def _parse_sbl_row(row: list) -> dict:
    """Parse a standard SBL balance row (columns 8-12 are 借券賣出 group).
    Values are in shares (股); convert to lots (張) by dividing by 1000."""
    try:
        return {
            "name": row[1].strip(),
            "prev_balance": int(str(row[8]).replace(",", "")) / 1000,
            "sell": int(str(row[9]).replace(",", "")) / 1000,
            "return": int(str(row[10]).replace(",", "")) / 1000,
            "adjust": int(str(row[11]).replace(",", "")) / 1000,
            "today_balance": int(str(row[12]).replace(",", "")) / 1000,
        }
    except (ValueError, IndexError):
        return {}


def fetch_twse_sbl_balance(code: str, date_str: str) -> dict:
    """Fetch SBL balance for a TWSE (listed) stock on a specific date."""
    url = f"{TWSE_SBL_BALANCE_URL}?date={date_str}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] TWT93U API ({date_str}): {e}", file=sys.stderr)
        return {}

    if data.get("stat") != "OK" or not data.get("data"):
        return {}

    for row in data["data"]:
        if len(row) >= 14 and row[0].strip() == code:
            return _parse_sbl_row(row)
    return {}


def fetch_tpex_sbl_balance(code: str, date_str: str) -> dict:
    """Fetch SBL balance for a TPEx (OTC) stock on a specific date.
    date_str in YYYYMMDD, converted to YYYY/MM/DD for the API."""
    d = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"
    url = f"{TPEX_SBL_BALANCE_URL}?date={urllib.parse.quote(d, safe='')}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] TPEx SBL API ({date_str}): {e}", file=sys.stderr)
        return {}

    if data.get("stat", "").lower() != "ok":
        return {}

    tables = data.get("tables") or []
    for tbl in tables:
        for row in tbl.get("data", []):
            if len(row) >= 14 and row[0].strip() == code:
                return _parse_sbl_row(row)
    return {}


def fetch_return_details(code: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch return details (還券明細) from TWSE t13sa870.
    Returns completed returns with borrowing date, return date, volume, fee rate."""
    url = f"{TWSE_SBL_RETURN_URL}?startDate={start_date}&endDate={end_date}&stockNo={code}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[ERROR] t13sa870 API: {e}", file=sys.stderr)
        return []

    if data.get("stat") != "OK" or not data.get("data"):
        return []

    records = []
    for row in data["data"]:
        try:
            borrow_date = to_ad_date(row[0])
            tx_type = row[3].strip()
            volume = int(str(row[4]).replace(",", ""))
            fee_rate = float(str(row[5]).replace(",", ""))
            return_date = to_ad_date(row[7])
            days = int(row[8]) if row[8] else 0
        except (ValueError, IndexError):
            continue
        records.append({
            "borrow_date": borrow_date,
            "return_date": return_date,
            "type": tx_type,
            "volume": volume,
            "fee_rate": fee_rate,
            "days": days,
        })
    return records


def fetch_sbl_balance_for_date(code: str, date_str: str, market: str = "") -> dict:
    """Fetch SBL balance for a stock on a specific date.
    market: '上市' forces TWSE, '上櫃' forces TPEx. If empty, tries TWSE first."""
    if market == "上櫃":
        return fetch_tpex_sbl_balance(code, date_str)
    if market == "上市":
        return fetch_twse_sbl_balance(code, date_str)
    # Unknown market: try TWSE, fall back to TPEx
    result = fetch_twse_sbl_balance(code, date_str)
    if result:
        return result
    return fetch_tpex_sbl_balance(code, date_str)


def fetch_stock_price(code: str) -> dict:
    """Fetch price info from Yahoo Finance."""
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
            closes = indicators.get("close", [])
            closes = [c for c in closes if c is not None]

            # Today's change: compare today's close to yesterday's close
            if len(closes) >= 2:
                yest_close = closes[-2]
                change_pct = ((price - yest_close) / yest_close * 100) if yest_close else 0
            else:
                change_pct = 0

            market = "上櫃" if suffix == ".TWO" else "上市"
            name = meta.get("shortName", code)
            return {"price": price, "change_pct": change_pct, "market": market, "name": name}
        except Exception:
            continue
    return {}


def get_previous_trading_day(date_str: str) -> str:
    """Return previous weekday (ignores holidays)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    dt -= timedelta(days=1)
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.strftime("%Y%m%d")


def summarize_day(records: list[dict], date_str: str) -> dict:
    """Aggregate transactions by type for a specific date."""
    summary = defaultdict(lambda: {"volume": 0, "weighted_fee": 0.0})
    for r in records:
        if r["date"] != date_str:
            continue
        tx_type = r["type"]
        summary[tx_type]["volume"] += r["volume"]
        summary[tx_type]["weighted_fee"] += r["fee_rate"] * r["volume"]

    result = {}
    for tx_type, v in summary.items():
        vol = v["volume"]
        avg_fee = v["weighted_fee"] / vol if vol > 0 else 0.0
        result[tx_type] = {"volume": vol, "avg_fee_rate": avg_fee}
    return result


def format_report(code: str, today: str, yesterday: str,
                  today_lending: dict, yest_lending: dict,
                  today_returns: dict, yest_returns: dict,
                  today_sbl: dict, yest_sbl: dict,
                  price_info: dict) -> str:
    """Format the lookup report."""
    today_dt = datetime.strptime(today, "%Y%m%d").strftime("%Y-%m-%d")
    yest_dt = datetime.strptime(yesterday, "%Y%m%d").strftime("%Y-%m-%d")

    name = price_info.get("name") or today_sbl.get("name") or yest_sbl.get("name") or ""
    market = price_info.get("market", "")
    header = f"{code} {name}"
    if market:
        header += f" [{market}]"

    lines = [header]
    if price_info:
        sign = "+" if price_info.get("change_pct", 0) >= 0 else ""
        lines.append(f"現價: ${price_info['price']:,.2f}  {sign}{price_info['change_pct']:.2f}%")
    lines.append("")

    def format_day(label: str, date_str: str, lending: list, returns: list, sbl: dict) -> list[str]:
        out = [f"━━━ {label} ({date_str}) ━━━"]

        out.append("借券交易:")
        if not lending:
            out.append("  無交易")
        else:
            total_vol = sum(r["volume"] for r in lending)
            out.append(f"  合計: {total_vol:,}張 ({len(lending)}筆)")
            # Sort: 議借, 競價, 定價 order; within type by volume desc
            type_order = {"定價": 0, "競價": 1, "議借": 2}
            sorted_lending = sorted(lending, key=lambda r: (type_order.get(r["type"], 99), -r["volume"]))
            for r in sorted_lending:
                out.append(f"  [{r['type']}] {r['volume']:,}張 @ {r['fee_rate']:.2f}%")

        out.append("還券明細:")
        if not returns:
            out.append("  無還券")
        else:
            total_vol = sum(r["volume"] for r in returns)
            out.append(f"  合計: {total_vol:,}張 ({len(returns)}筆)")
            type_order = {"定價": 0, "競價": 1, "議借": 2}
            sorted_returns = sorted(returns, key=lambda r: (type_order.get(r["type"], 99), -r["volume"]))
            for r in sorted_returns:
                borrow_dt = datetime.strptime(r["borrow_date"], "%Y%m%d").strftime("%m/%d")
                out.append(f"  [{r['type']}] {r['volume']:,}張 @ {r['fee_rate']:.2f}% | 借於 {borrow_dt} | {r['days']}天")

        if sbl:
            out.append("借券賣出餘額:")
            out.append(f"  前日餘額: {sbl['prev_balance']:,.0f}張")
            out.append(f"  當日賣出: {sbl['sell']:,.0f}張")
            out.append(f"  當日還券: {sbl['return']:,.0f}張")
            if sbl.get("adjust"):
                out.append(f"  當日調整: {sbl['adjust']:,.0f}張")
            out.append(f"  當日餘額: {sbl['today_balance']:,.0f}張")
            if sbl['prev_balance'] > 0:
                change = ((sbl['today_balance'] - sbl['prev_balance']) / sbl['prev_balance']) * 100
                sign = "+" if change >= 0 else ""
                out.append(f"  餘額變化: {sign}{change:.1f}%")
        else:
            out.append("借券賣出餘額: 無資料")
        return out

    lines.extend(format_day("今日", today_dt, today_lending, today_returns, today_sbl))
    lines.append("")
    lines.extend(format_day("昨日", yest_dt, yest_lending, yest_returns, yest_sbl))

    return "\n".join(lines)


def summarize_returns_by_date(returns: list[dict], date_str: str) -> dict:
    """Aggregate return records by transaction type for stocks returned on a specific date."""
    summary = defaultdict(lambda: {"volume": 0, "weighted_fee": 0.0, "total_days": 0, "count": 0})
    for r in returns:
        if r["return_date"] != date_str:
            continue
        tx_type = r["type"]
        summary[tx_type]["volume"] += r["volume"]
        summary[tx_type]["weighted_fee"] += r["fee_rate"] * r["volume"]
        summary[tx_type]["total_days"] += r["days"] * r["volume"]
        summary[tx_type]["count"] += 1

    result = {}
    for tx_type, v in summary.items():
        vol = v["volume"]
        result[tx_type] = {
            "volume": vol,
            "avg_fee_rate": v["weighted_fee"] / vol if vol > 0 else 0.0,
            "avg_days": v["total_days"] / vol if vol > 0 else 0.0,
            "count": v["count"],
        }
    return result


def lookup(code: str, target_date: str | None = None) -> str:
    """Main lookup function."""
    today = target_date or datetime.now().strftime("%Y%m%d")
    yesterday = get_previous_trading_day(today)

    # Current price + market (determines which SBL API to use)
    price_info = fetch_stock_price(code)
    market = price_info.get("market", "")

    # Lending transactions (both days in one call) - keep raw per-transaction records
    lending_records = fetch_lending_transactions(code, yesterday, today)
    today_lending = [r for r in lending_records if r["date"] == today]
    yest_lending = [r for r in lending_records if r["date"] == yesterday]

    # Return details - query wider range since borrow_date can be much earlier
    return_records = fetch_return_details(code, "20250101", today)
    today_returns = [r for r in return_records if r["return_date"] == today]
    yest_returns = [r for r in return_records if r["return_date"] == yesterday]

    # SBL balance (route by market)
    today_sbl = fetch_sbl_balance_for_date(code, today, market)
    yest_sbl = fetch_sbl_balance_for_date(code, yesterday, market)

    return format_report(code, today, yesterday,
                         today_lending, yest_lending,
                         today_returns, yest_returns,
                         today_sbl, yest_sbl, price_info)


def main():
    parser = argparse.ArgumentParser(description="台股借券單檔查詢")
    parser.add_argument("code", help="股票代號，例如 2330")
    parser.add_argument("--date", help="指定今日日期 YYYYMMDD（預設今天）")
    args = parser.parse_args()

    report = lookup(args.code, args.date)
    print(report)


if __name__ == "__main__":
    main()
