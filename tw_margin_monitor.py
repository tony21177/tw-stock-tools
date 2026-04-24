#!/usr/bin/env python3
"""
台股融資維持率預警
用 FIFO 從過去 3 個月的融資買/賣/償還資料估算目前融資餘額的加權平均成本，
再用當前股價計算維持率，篩選 <140% 的標的。

維持率 = 當前股價 / (加權平均買進價 × 融資成數)
  融資成數 M：上市 60%、上櫃 50%（一般股；警示/管理/全額交割另計）
  警戒線：140%、追繳線：130%

資料來源：
  今日餘額：TWSE OpenAPI + TPEx OpenAPI
  3 個月歷史：FinMind TaiwanStockMarginPurchaseShortSale（per-stock）
  股價：Yahoo Finance
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta

DEFAULT_CHAT_ID = "-5229750819"
TWSE_OPENAPI_MARGIN = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
TPEX_OPENAPI_MARGIN = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
CACHE_DIR = os.path.expanduser("~/project/tw_stock_tools/margin_cache")

TWSE_MARGIN_RATIO = 0.60
TPEX_MARGIN_RATIO = 0.50

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _http_get_json(url: str, timeout: int = 30, retries: int = 3) -> dict | list | None:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(5 * (2 ** attempt))
                continue
            print(f"[WARN] HTTP {e.code}: {url[:120]}", file=sys.stderr)
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"[WARN] {e}: {url[:120]}", file=sys.stderr)
            return None
    return None


def fetch_twse_today_margin() -> dict:
    """Fetch today's TWSE margin balance from OpenAPI.
    Returns {code: {balance, market}}."""
    data = _http_get_json(TWSE_OPENAPI_MARGIN)
    if not data:
        return {}
    result = {}
    for row in data:
        try:
            code = row["股票代號"].strip()
            balance = int(str(row.get("融資今日餘額", "0")).replace(",", "") or "0")
        except (ValueError, KeyError):
            continue
        result[code] = {"balance": balance, "market": "上市"}
    return result


def fetch_tpex_today_margin() -> dict:
    """Fetch today's TPEx margin balance from OpenAPI."""
    data = _http_get_json(TPEX_OPENAPI_MARGIN)
    if not data:
        return {}
    result = {}
    for row in data:
        try:
            code = row["SecuritiesCompanyCode"].strip()
            balance = int(str(row.get("MarginPurchaseBalance", "0")).replace(",", "") or "0")
        except (ValueError, KeyError):
            continue
        result[code] = {"balance": balance, "market": "上櫃"}
    return result


def fetch_finmind_history(code: str, start_date: str, end_date: str, token: str) -> list[dict]:
    """Fetch per-stock 3-month margin history from FinMind.
    Returns list of {date, buy, sell, repay, balance}.
    Cached per stock+end_date to avoid re-fetches."""
    ensure_cache_dir()
    cache = os.path.join(CACHE_DIR, f"finmind_{code}_{end_date}.json")
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)

    url = (f"{FINMIND_URL}?dataset=TaiwanStockMarginPurchaseShortSale"
           f"&data_id={code}&start_date={start_date}&end_date={end_date}&token={token}")
    data = _http_get_json(url)
    if data is None or data.get("msg") != "success":
        return []

    rows = []
    for r in data.get("data", []):
        rows.append({
            "date": r["date"].replace("-", ""),
            "buy": int(r.get("MarginPurchaseBuy") or 0),
            "sell": int(r.get("MarginPurchaseSell") or 0),
            "repay": int(r.get("MarginPurchaseCashRepayment") or 0),
            "balance": int(r.get("MarginPurchaseTodayBalance") or 0),
        })
    rows.sort(key=lambda x: x["date"])
    with open(cache, "w") as f:
        json.dump(rows, f)
    return rows


def fetch_yahoo_history(code: str) -> dict:
    """Fetch 3-month daily closes from Yahoo Finance.
    Returns {prices: {YYYYMMDD: close}, current_price, market, name, change_pct}."""
    for suffix in [".TW", ".TWO"]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range=3mo"
        data = _http_get_json(url, timeout=15, retries=2)
        if not data:
            continue
        try:
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            market = "上櫃" if suffix == ".TWO" else "上市"
            meta = result["meta"]
            current_price = meta["regularMarketPrice"]
            name = meta.get("shortName", code)
            prices = {}
            close_values = []
            for ts, c in zip(timestamps, closes):
                if c is None:
                    continue
                d = datetime.fromtimestamp(ts).strftime("%Y%m%d")
                prices[d] = c
                close_values.append(c)
            change_pct = 0
            if len(close_values) >= 2:
                yest = close_values[-2]
                change_pct = ((current_price - yest) / yest * 100) if yest else 0
            return {
                "prices": prices,
                "current_price": current_price,
                "market": market,
                "name": name,
                "change_pct": change_pct,
            }
        except (KeyError, IndexError, TypeError):
            continue
    return {}


def compute_fifo_cost(history: list[dict], daily_prices: dict) -> tuple[float, int]:
    """
    history: list of {date, buy, sell, repay} ascending by date
    daily_prices: {date_str: close_price}
    Returns (weighted_avg_cost, remaining_lots) using FIFO.
    """
    lots = deque()
    for entry in history:
        date = entry["date"]
        price = daily_prices.get(date)
        buy = entry["buy"]
        reduce = entry["sell"] + entry["repay"]

        if buy > 0 and price is not None:
            lots.append([buy, price])

        while reduce > 0 and lots:
            oldest = lots[0]
            if oldest[0] <= reduce:
                reduce -= oldest[0]
                lots.popleft()
            else:
                oldest[0] -= reduce
                reduce = 0

    total_vol = sum(l[0] for l in lots)
    if total_vol == 0:
        return 0.0, 0
    total_cost = sum(l[0] * l[1] for l in lots)
    return total_cost / total_vol, int(total_vol)


def compute_cohort_buckets(history: list[dict], daily_prices: dict,
                             current_price: float, current_balance: int,
                             margin_ratio: float) -> dict:
    """Balance-change based cohort distribution. Returns bucket dict + tracked/legacy split."""
    from collections import deque as _dq
    sorted_hist = sorted(history, key=lambda x: x["date"])
    if not sorted_hist:
        return {"buckets": {}, "tracked": 0, "legacy": current_balance, "danger_pct": 0}

    legacy = sorted_hist[0]["balance"]
    lots = _dq()
    prev = legacy
    for entry in sorted_hist:
        price = daily_prices.get(entry["date"])
        today_bal = entry["balance"]
        delta = today_bal - prev
        if delta > 0 and price is not None:
            lots.append([entry["date"], delta, price])
        elif delta < 0:
            reduce = -delta
            while reduce > 0 and lots:
                if lots[0][1] <= reduce:
                    reduce -= lots[0][1]
                    lots.popleft()
                else:
                    lots[0][1] -= reduce
                    reduce = 0
            if reduce > 0:
                legacy = max(0, legacy - reduce)
        prev = today_bal

    tracked = sum(l[1] for l in lots)
    legacy_vol = max(0, current_balance - tracked)

    buckets = {"<130": 0, "130-140": 0, "140-150": 0, "150-170": 0, "170+": 0}
    for _, v, p in lots:
        r = (current_price / (p * margin_ratio)) * 100
        if r < 130: buckets["<130"] += v
        elif r < 140: buckets["130-140"] += v
        elif r < 150: buckets["140-150"] += v
        elif r < 170: buckets["150-170"] += v
        else: buckets["170+"] += v

    # Danger %: tracked volume in <140 zone, as % of tracked
    danger_vol = buckets["<130"] + buckets["130-140"]
    danger_pct = danger_vol / tracked * 100 if tracked else 0

    return {
        "buckets": buckets,
        "tracked": tracked,
        "legacy": legacy_vol,
        "danger_pct": danger_pct,
        "danger_vol": danger_vol,
    }


def analyze(target_date: str, threshold: float, min_balance: int, finmind_token: str, max_stocks: int = 0) -> list[dict]:
    """Main analysis. threshold: maintenance ratio % (e.g. 140)."""
    # Compute date range
    end_dt = datetime.strptime(target_date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=95)
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    print(f"分析區間: {start_date} 到 {end_date}", file=sys.stderr)

    # Step 1: Today's snapshot
    print("抓取今日融資餘額快照...", file=sys.stderr)
    twse_today = fetch_twse_today_margin()
    time.sleep(0.5)
    tpex_today = fetch_tpex_today_margin()
    print(f"  TWSE: {len(twse_today)} 檔, TPEx: {len(tpex_today)} 檔", file=sys.stderr)

    today_data = {}
    for code, info in twse_today.items():
        today_data[code] = info
    for code, info in tpex_today.items():
        if code not in today_data:
            today_data[code] = info

    target_codes = [c for c, info in today_data.items() if info["balance"] >= min_balance]
    target_codes.sort(key=lambda c: today_data[c]["balance"], reverse=True)
    if max_stocks > 0:
        target_codes = target_codes[:max_stocks]
    print(f"融資餘額 >= {min_balance} 張: {len(target_codes)} 檔", file=sys.stderr)

    # Step 2: Per-stock history + prices
    results = []
    for i, code in enumerate(target_codes):
        history = fetch_finmind_history(code, start_date, end_date, finmind_token)
        time.sleep(0.2)  # FinMind rate limit: 600/hr → 6/s → 0.17s each; pad to 0.2
        if not history:
            continue

        price_data = fetch_yahoo_history(code)
        if not price_data:
            continue
        time.sleep(0.1)

        avg_cost, remaining = compute_fifo_cost(history, price_data["prices"])
        if remaining == 0 or avg_cost == 0:
            continue

        market = price_data["market"]
        ratio = TPEX_MARGIN_RATIO if market == "上櫃" else TWSE_MARGIN_RATIO
        current_price = price_data["current_price"]
        current_balance = today_data[code]["balance"]

        maintenance = (current_price / (avg_cost * ratio)) * 100
        trigger = avg_cost * ratio * 1.30

        cohort = compute_cohort_buckets(history, price_data["prices"],
                                        current_price, current_balance, ratio)

        if maintenance >= threshold:
            continue

        results.append({
            "code": code,
            "name": price_data["name"],
            "market": market,
            "current_price": current_price,
            "change_pct": price_data["change_pct"],
            "avg_cost": avg_cost,
            "remaining_lots": remaining,
            "balance_today": current_balance,
            "maintenance_ratio": maintenance,
            "trigger_price": trigger,
            "margin_ratio": ratio,
            "cohort_buckets": cohort["buckets"],
            "cohort_tracked": cohort["tracked"],
            "cohort_legacy": cohort["legacy"],
            "cohort_danger_pct": cohort["danger_pct"],
            "cohort_danger_vol": cohort["danger_vol"],
        })

        if (i + 1) % 50 == 0:
            print(f"  進度 {i+1}/{len(target_codes)}, 命中 {len(results)}", file=sys.stderr)

    results.sort(key=lambda x: x["maintenance_ratio"])
    return results


def format_output(results: list[dict], target_date: str, threshold: float) -> str:
    dt = datetime.strptime(target_date, "%Y%m%d").strftime("%Y-%m-%d")
    lines = [f"融資維持率預警 {dt}  (警戒 <{threshold:.0f}%)\n"]

    if not results:
        lines.append("今日無符合條件的標的")
        return "\n".join(lines)

    lines.append("估算：FIFO 加權 + 批次分布")
    lines.append("  融資成數：上市 60%、上櫃 50%")
    lines.append("  追蹤批次 = 餘額實際增加的日期，依進場價估維持率")
    lines.append("━━━━━━━━━━━━")

    # Resort: prioritize stocks with high danger_pct (% of tracked in <140%)
    results_sorted = sorted(results, key=lambda x: (-x.get("cohort_danger_pct", 0), x["maintenance_ratio"]))

    for r in results_sorted:
        sign = "+" if r["change_pct"] >= 0 else ""
        bucket = r.get("cohort_buckets", {})
        tracked = r.get("cohort_tracked", 0)
        legacy = r.get("cohort_legacy", 0)
        danger_pct = r.get("cohort_danger_pct", 0)
        danger_vol = r.get("cohort_danger_vol", 0)

        def pct(key):
            v = bucket.get(key, 0)
            return f"{v/tracked*100:.0f}%" if tracked else "-"

        lines.append(
            f"{r['code']} {r['name']} [{r['market']}]\n"
            f"  現價: ${r['current_price']:,.2f} {sign}{r['change_pct']:.2f}%\n"
            f"  整體維持率: {r['maintenance_ratio']:.1f}% | 加權成本: ${r['avg_cost']:,.2f}\n"
            f"  融資餘額: {r['balance_today']:,}張 (追蹤 {tracked:,} + 舊部位 {legacy:,})\n"
            f"  批次分布: 追繳區 {pct('<130')} | 危險區 {pct('130-140')} | 警戒 {pct('140-150')} | 尚可 {pct('150-170')} | 安全 {pct('170+')}\n"
            f"  危險部位: {danger_vol:,}張 ({danger_pct:.1f}% 追蹤量)"
        )
        lines.append("")

    lines.append(f"共篩出 {len(results)} 檔（依「追蹤量中危險部位比例」由高至低排序）")
    return "\n".join(lines)


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API_URL.format(token=bot_token)
    max_len = 4000
    if len(message) <= max_len:
        chunks = [message]
    else:
        chunks = []
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
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                if not result.get("ok"):
                    all_ok = False
        except Exception as e:
            print(f"[ERROR] Telegram: {e}", file=sys.stderr)
            all_ok = False
        if i < len(chunks) - 1:
            time.sleep(0.5)
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="台股融資維持率預警")
    parser.add_argument("--date", help="指定日期 YYYYMMDD（預設今天）")
    parser.add_argument("--threshold", type=float, default=140.0)
    parser.add_argument("--min-balance", type=int, default=500, help="融資餘額門檻 張數 (預設 500)")
    parser.add_argument("--max-stocks", type=int, default=0, help="最多分析前 N 檔（0=全部，依融資餘額排序）")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--bot-token")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--finmind-token")
    args = parser.parse_args()

    bot_token = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")
    finmind_token = args.finmind_token or os.environ.get("FINMIND_TOKEN", "")
    if not finmind_token:
        print("[ERROR] 需要 FinMind token (--finmind-token 或 FINMIND_TOKEN 環境變數)", file=sys.stderr)
        sys.exit(1)

    target_date = args.date or datetime.now().strftime("%Y%m%d")

    results = analyze(target_date, args.threshold, args.min_balance, finmind_token, args.max_stocks)
    output = format_output(results, target_date, args.threshold)
    print(output)

    if args.telegram:
        if not bot_token:
            print("[ERROR] need bot token", file=sys.stderr)
            sys.exit(1)
        if send_telegram(output, bot_token, args.chat_id):
            print("推送成功")
        else:
            print("推送失敗", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
