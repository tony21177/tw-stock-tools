#!/usr/bin/env python3
"""Chip-price analysis: per-stock daily BSR with (broker × price) detail.

Usage:
  tw_chip_price.py <code>                # today, force re-fetch BSR
  tw_chip_price.py <code> --date YYYYMMDD  # use cached per-price file
  tw_chip_price.py <code> --telegram     # also push report to TG
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

DEFAULT_CHAT_ID = "-5229750819"


def _get_token() -> str:
    """Read FINMIND_TOKEN from env or crontab."""
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=")[1].split()[0]
    except Exception:
        pass
    return ""


def get_ohlc(stock_code: str, date: str | None = None) -> dict:
    """Fetch OHLC for stage analysis. Uses FinMind TaiwanStockPrice.

    Returns {open, high, low, close, date} for the most recent trading day
    at or before `date`. The returned `date` field (YYYYMMDD) is the actual
    trading day FinMind served — use this as the authoritative trading date
    for the chip-price report, since the TWSE BSR endpoint doesn't expose the
    trading day in its CSV or HTML response.
    Returns {} on failure or no data.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return {}
    target = date or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(target, "%Y%m%d")
    start_dt = end_dt - timedelta(days=10)
    try:
        rows = finmind_client.fetch_stock_price(
            stock_code,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
            token,
        )
    except Exception:
        return {}
    if not rows:
        return {}
    # Pick the row whose date is the target, or the latest available row <= target
    target_dash = f"{target[:4]}-{target[4:6]}-{target[6:8]}"
    match = [r for r in rows if r["date"] == target_dash]
    chosen = match[0] if match else rows[-1]
    chosen_dash = chosen.get("date", "")
    return {
        "open": float(chosen.get("open", 0)),
        "high": float(chosen.get("max", 0)),
        "low": float(chosen.get("min", 0)),
        "close": float(chosen.get("close", 0)),
        "date": chosen_dash.replace("-", "") if chosen_dash else "",
    }


ZONE_LOW_FRACTION = 0.25
ZONE_HIGH_FRACTION = 0.75


def stage_breakdown(rows: list[dict], low: float, high: float) -> dict:
    """Split rows into 3 price zones and aggregate buy/sell per broker per zone.

    Zones:
      early = [low, low + 0.25 × (high − low)]
      mid   = (low + 0.25 × range, low + 0.75 × range]
      late  = (low + 0.75 × range, high]

    Returns:
      {"early": [{broker_id, broker_name, buy_shares, sell_shares, net_shares}, ...],
       "mid":   [...],
       "late":  [...]}
    Each list sorted by abs(net_shares) descending.
    """
    rng = high - low
    if rng <= 0:
        # Flat price day — everything in mid
        zones = {"early": [], "mid": rows, "late": []}
    else:
        early_max = low + ZONE_LOW_FRACTION * rng
        late_min = low + ZONE_HIGH_FRACTION * rng
        zone_rows = {"early": [], "mid": [], "late": []}
        for r in rows:
            p = r["price"]
            if p <= early_max:
                zone_rows["early"].append(r)
            elif p <= late_min:
                zone_rows["mid"].append(r)
            else:
                zone_rows["late"].append(r)
        zones = zone_rows

    result = {}
    for zone, zrows in zones.items():
        per_broker = {}
        for r in zrows:
            bid = r["broker_id"]
            agg = per_broker.setdefault(bid, {
                "broker_id": bid,
                "broker_name": r["broker_name"],
                "buy_shares": 0,
                "sell_shares": 0,
            })
            agg["buy_shares"] += r["buy"]
            agg["sell_shares"] += r["sell"]
        for a in per_broker.values():
            a["net_shares"] = a["buy_shares"] - a["sell_shares"]
        sorted_list = sorted(per_broker.values(),
                              key=lambda x: -abs(x["net_shares"]))
        result[zone] = sorted_list
    return result


def broker_fingerprint(rows: list[dict], top_n: int = 5) -> dict:
    """Per-broker summary: total buy/sell, average price, price range.

    Returns:
      {"top_buyers": [{broker_id, broker_name, buy_shares, sell_shares,
                       net_shares, avg_price, price_range (lo, hi),
                       cells: [...sorted by abs(net) per price...]}, ...],
       "top_sellers": [...same shape, net_shares < 0...]}
    Sorted by abs(net_shares) descending.
    """
    per_broker = {}
    for r in rows:
        bid = r["broker_id"]
        agg = per_broker.setdefault(bid, {
            "broker_id": bid,
            "broker_name": r["broker_name"],
            "buy_shares": 0,
            "sell_shares": 0,
            "cells": [],
            "_buy_value": 0.0,
            "_sell_value": 0.0,
            "_min_price": float("inf"),
            "_max_price": 0.0,
        })
        agg["buy_shares"] += r["buy"]
        agg["sell_shares"] += r["sell"]
        agg["cells"].append({"price": r["price"], "buy": r["buy"], "sell": r["sell"]})
        agg["_buy_value"] += r["price"] * r["buy"]
        agg["_sell_value"] += r["price"] * r["sell"]
        if r["buy"] > 0 or r["sell"] > 0:
            agg["_min_price"] = min(agg["_min_price"], r["price"])
            agg["_max_price"] = max(agg["_max_price"], r["price"])

    for a in per_broker.values():
        a["net_shares"] = a["buy_shares"] - a["sell_shares"]
        total_shares = a["buy_shares"] + a["sell_shares"]
        weighted = a["_buy_value"] + a["_sell_value"]
        a["avg_price"] = round(weighted / total_shares, 2) if total_shares else 0
        a["price_range"] = (
            a["_min_price"] if a["_min_price"] != float("inf") else 0.0,
            a["_max_price"],
        )
        a["cells"].sort(key=lambda c: -(c["buy"] + c["sell"]))
        # drop internal accumulators
        del a["_buy_value"]
        del a["_sell_value"]
        del a["_min_price"]
        del a["_max_price"]

    buyers = [b for b in per_broker.values() if b["net_shares"] > 0]
    sellers = [b for b in per_broker.values() if b["net_shares"] < 0]
    buyers.sort(key=lambda x: -x["net_shares"])
    sellers.sort(key=lambda x: x["net_shares"])
    return {
        "top_buyers": buyers[:top_n],
        "top_sellers": sellers[:top_n],
    }


def _zone_and_tag(price: float, side: str, low: float, high: float) -> tuple[str, str]:
    """Return (zone, tag) for a (price, side) cell.

    Zones: early (≤ 25%), mid (25-75%), late (> 75%).
    Tags:
      buy@early → '⬇ 早盤搶低'
      buy@mid   → '↗ 盤中追進'
      buy@late  → '▽ 高檔追進'
      sell@early → '△ 低檔賣壓'
      sell@mid   → '↘ 盤中出脫'
      sell@late  → '⬆ 高檔倒貨'
    Flat day (rng ≤ 0): everything 'mid', tag without zone descriptor.
    """
    rng = high - low
    if rng <= 0:
        zone = "mid"
    else:
        f = (price - low) / rng
        if f <= ZONE_LOW_FRACTION:
            zone = "early"
        elif f <= ZONE_HIGH_FRACTION:
            zone = "mid"
        else:
            zone = "late"
    tags = {
        ("buy", "early"):  "⬇ 早盤搶低",
        ("buy", "mid"):    "↗ 盤中追進",
        ("buy", "late"):   "▽ 高檔追進",
        ("sell", "early"): "△ 低檔賣壓",
        ("sell", "mid"):   "↘ 盤中出脫",
        ("sell", "late"):  "⬆ 高檔倒貨",
    }
    return zone, tags.get((side, zone), "")


def top_cells(rows: list[dict], top_n: int = 10,
               low: float = 0.0, high: float = 0.0) -> list[dict]:
    """Top N (broker, price, side) cells by volume.

    Each row contributes up to 2 cells (one buy, one sell, if both > 0).
    Returns list sorted by volume descending:
      [{broker_id, broker_name, price, side ('buy'|'sell'), volume,
        zone, tag}, ...]
    """
    cells = []
    for r in rows:
        if r["buy"] > 0:
            zone, tag = _zone_and_tag(r["price"], "buy", low, high)
            cells.append({
                "broker_id": r["broker_id"],
                "broker_name": r["broker_name"],
                "price": r["price"],
                "side": "buy",
                "volume": r["buy"],
                "zone": zone,
                "tag": tag,
            })
        if r["sell"] > 0:
            zone, tag = _zone_and_tag(r["price"], "sell", low, high)
            cells.append({
                "broker_id": r["broker_id"],
                "broker_name": r["broker_name"],
                "price": r["price"],
                "side": "sell",
                "volume": r["sell"],
                "zone": zone,
                "tag": tag,
            })
    cells.sort(key=lambda c: -c["volume"])
    return cells[:top_n]


def _fmt_zhang(shares: int) -> str:
    """股 → 張 with thousands separator (e.g., 8200000 → '8,200')."""
    return f"{int(shares / 1000):,}"


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def format_report(data: dict) -> str:
    """Render the analysis result as Telegram-friendly text.

    data = {stock_code, name, date, ohlc, total_buy_shares, total_sell_shares,
            top_cells, stage, fingerprint, [optional] notes}
    """
    code = data["stock_code"]
    name = data.get("name", "")
    date = data["date"]
    ohlc = data["ohlc"]
    change_pct = ((ohlc["close"] - ohlc["open"]) / ohlc["open"] * 100
                  if ohlc["open"] > 0 else 0)

    lines = []
    lines.append(f"{code} {name} 籌碼價格分析 ({_fmt_date(date)})")
    lines.append(f"開盤 ${ohlc['open']:.2f} / 收盤 ${ohlc['close']:.2f} / "
                  f"高 ${ohlc['high']:.2f} / 低 ${ohlc['low']:.2f} "
                  f"({change_pct:+.2f}%)")
    lines.append(f"總量 {_fmt_zhang(data['total_buy_shares'])} 張")
    lines.append("")

    # Top cells
    lines.append("【🔥 Top 10 大單 cells (broker × price)】")
    if not data["top_cells"]:
        lines.append("  (無資料)")
    else:
        for i, c in enumerate(data["top_cells"], 1):
            side_label = "買" if c["side"] == "buy" else "賣"
            lines.append(
                f"{i}. {c['broker_id']} {c['broker_name']} @${c['price']:.2f} "
                f"{side_label} {_fmt_zhang(c['volume'])} 張 {c['tag']}"
            )
    lines.append("")

    # Stage analysis
    lines.append("【⏰ 三階段分析】")
    rng = ohlc["high"] - ohlc["low"]
    if rng > 0:
        lines.append(f"早盤 (低 25%: ${ohlc['low']:.2f} ~ "
                      f"${ohlc['low'] + 0.25 * rng:.2f}):")
    else:
        lines.append("早盤:")
    _emit_zone(lines, data["stage"].get("early", []))
    lines.append("")
    if rng > 0:
        lines.append(f"盤中 (中 50%: ${ohlc['low'] + 0.25 * rng:.2f} ~ "
                      f"${ohlc['low'] + 0.75 * rng:.2f}):")
    else:
        lines.append("盤中:")
    _emit_zone(lines, data["stage"].get("mid", []))
    lines.append("")
    if rng > 0:
        lines.append(f"尾盤 (高 25%: ${ohlc['low'] + 0.75 * rng:.2f} ~ "
                      f"${ohlc['high']:.2f}):")
    else:
        lines.append("尾盤:")
    _emit_zone(lines, data["stage"].get("late", []))
    lines.append("")

    # Fingerprint
    lines.append("【🎯 Top 5 買超分點價格指紋】")
    if not data["fingerprint"]["top_buyers"]:
        lines.append("  (無)")
    else:
        for b in data["fingerprint"]["top_buyers"]:
            pr_lo, pr_hi = b["price_range"]
            lines.append(
                f"  {b['broker_id']} {b['broker_name']} "
                f"+{_fmt_zhang(b['net_shares'])} 張 — "
                f"avg ${b['avg_price']:.2f}, 範圍 ${pr_lo:.2f}~${pr_hi:.2f}"
            )
    lines.append("")
    lines.append("【🎯 Top 5 賣超分點價格指紋】")
    if not data["fingerprint"]["top_sellers"]:
        lines.append("  (無)")
    else:
        for b in data["fingerprint"]["top_sellers"]:
            pr_lo, pr_hi = b["price_range"]
            lines.append(
                f"  {b['broker_id']} {b['broker_name']} "
                f"{_fmt_zhang(b['net_shares'])} 張 — "
                f"avg ${b['avg_price']:.2f}, 範圍 ${pr_lo:.2f}~${pr_hi:.2f}"
            )
    return "\n".join(lines)


def _emit_zone(lines: list[str], zone_rows: list[dict]) -> None:
    """Helper: append top 3 buyers + top 3 sellers from a zone's sorted rows."""
    buyers = [r for r in zone_rows if r["net_shares"] > 0][:3]
    sellers = [r for r in zone_rows if r["net_shares"] < 0][:3]
    if buyers:
        labels = " / ".join(
            f"{r['broker_name']} +{_fmt_zhang(r['net_shares'])} 張"
            for r in buyers
        )
        lines.append(f"  🟢 買方主力: {labels}")
    if sellers:
        labels = " / ".join(
            f"{r['broker_name']} {_fmt_zhang(r['net_shares'])} 張"
            for r in sellers
        )
        lines.append(f"  🔴 賣方主力: {labels}")
    if not buyers and not sellers:
        lines.append("  (本區無大量交易)")


def analyze(stock_code: str, date: str | None = None,
            no_fetch: bool = False) -> dict:
    """Run the full pipeline: BSR fetch → OHLC → top cells / stage / fingerprint.

    Returns a dict ready for format_report() (or empty dict on failure).
    """
    import bsr_scraper

    # 1. BSR fetch (or load cached per-price file).
    # `target` is only used to pick the cache file in --no-fetch mode. After
    # a live fetch we re-derive the trading date from FinMind (the BSR
    # endpoint doesn't expose the trading day, so we'd otherwise stamp with
    # datetime.now() and lie about T-1 data being today's).
    target = date or datetime.now().strftime("%Y%m%d")
    bsr = {}
    if no_fetch:
        cache_path = os.path.join(HERE, "bsr_cache",
                                  f"{stock_code}_{target}_prices.json")
        if not os.path.exists(cache_path):
            print(f"[ERROR] --no-fetch but cache missing: {cache_path}",
                  file=sys.stderr)
            return {}
        with open(cache_path) as f:
            bsr = json.load(f)
    else:
        bsr = bsr_scraper.fetch_bsr_with_prices(stock_code)
        # TPEx (上櫃) detection — fetch_bsr_with_prices is currently TWSE-only.
        # If we got 0 rows or a no_data flag, the stock may be 上櫃; tell user.
        if not bsr or not bsr.get("rows") or bsr.get("no_data"):
            print(f"[WARN] No TWSE BSR for {stock_code}. If 上櫃 (TPEx) stock, "
                  f"per-price detail is not yet supported. Use /chip (aggregate) "
                  f"instead.", file=sys.stderr)
            return {}
        # Cache write deferred until after step 2 — we want to use FinMind's
        # authoritative trading date in the cache filename.

    # 2. OHLC for stage range. The returned ohlc["date"] is FinMind's latest
    # available trading day for this stock — the same day TWSE BSR is
    # serving (BSR publishes after FinMind close prices, so FinMind's latest
    # is always >= TWSE BSR's day). Use this as the report's trading date.
    ohlc = get_ohlc(stock_code, target)
    if ohlc and ohlc.get("date"):
        trading_date = ohlc["date"]
        # Patch BSR's date stamp to match the authoritative trading day.
        bsr["date"] = trading_date
    else:
        # FinMind missing — fall back to whatever BSR returned (today).
        trading_date = bsr.get("date") or target
    if not ohlc:
        # Fallback: derive range from BSR rows themselves
        prices = [r["price"] for r in bsr["rows"]]
        ohlc = {"open": min(prices), "high": max(prices),
                "low": min(prices), "close": max(prices)}

    # Now write the cache with the corrected date in the filename.
    if not no_fetch:
        cache_path = os.path.join(HERE, "bsr_cache",
                                  f"{stock_code}_{trading_date}_prices.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(bsr, f, ensure_ascii=False)

    # 3. Top cells + stage + fingerprint
    cells = top_cells(bsr["rows"], top_n=10,
                       low=ohlc["low"], high=ohlc["high"])
    stage = stage_breakdown(bsr["rows"], ohlc["low"], ohlc["high"])
    fingerprint = broker_fingerprint(bsr["rows"], top_n=5)

    # 4. Resolve Chinese name
    try:
        from stock_names import get_name
        name = get_name(stock_code, "")
    except Exception:
        name = ""

    return {
        "stock_code": stock_code,
        "name": name,
        "date": bsr.get("date", target),
        "ohlc": ohlc,
        "total_buy_shares": bsr.get("total_buy_shares", 0),
        "total_sell_shares": bsr.get("total_sell_shares", 0),
        "top_cells": cells,
        "stage": stage,
        "fingerprint": fingerprint,
    }


def _send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    """Push report to Telegram chat. Chunks if > 4000 chars."""
    api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_len = 4000
    chunks = [text] if len(text) <= max_len else []
    if not chunks:
        cur, lines = "", text.split("\n")
        for ln in lines:
            if len(cur) + len(ln) + 1 > max_len:
                chunks.append(cur)
                cur = ln
            else:
                cur = cur + "\n" + ln if cur else ln
        if cur:
            chunks.append(cur)
    ok = True
    for c in chunks:
        body = json.dumps({"chat_id": chat_id, "text": c}).encode()
        req = urllib.request.Request(
            api, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if not json.loads(resp.read().decode()).get("ok"):
                    ok = False
        except Exception as e:
            print(f"[TG error] {e}", file=sys.stderr)
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description="台股單檔籌碼價格分析")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--date", help="日期 YYYYMMDD (預設今天)")
    parser.add_argument("--telegram", action="store_true",
                        help="推送報告到 Telegram")
    parser.add_argument("--bot-token",
                        default=os.environ.get("TG_BOT_TOKEN", ""))
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--json-out", help="同時寫結構化 JSON 到此路徑")
    parser.add_argument("--no-fetch", action="store_true",
                        help="只讀 cache，不打 TWSE")
    args = parser.parse_args()

    data = analyze(args.code, date=args.date, no_fetch=args.no_fetch)
    if not data:
        sys.exit(1)
    report = format_report(data)
    print(report)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".",
                    exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] --telegram requires TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = _send_telegram(report, args.bot_token, args.chat_id)
        print(f"[TG] {'sent' if ok else 'partial/fail'}", file=sys.stderr)


if __name__ == "__main__":
    main()
