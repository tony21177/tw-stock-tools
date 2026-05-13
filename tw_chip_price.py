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
HISTORY_DIR = os.path.join(HERE, "chip_price_history")
HISTORY_KEEP_DAYS = 10


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


def infer_bsr_trading_date(stock_code: str, bsr_rows: list[dict],
                           target: str | None = None) -> str:
    """Identify which trading day this BSR fetch represents.

    TWSE BSR's CSV has no date and FinMind's "latest day" can be one trading
    day ahead of BSR's between ~14:00 (FinMind close) and ~17:30 (BSR
    publish). Disambiguate by matching BSR's actual (price_low, price_high,
    total_volume) against FinMind's OHLC + Volume for the last few trading
    days. The day whose triple matches is BSR's day.

    Returns YYYYMMDD on success, "" if FinMind unavailable or no match.
    """
    if not bsr_rows:
        return ""
    import finmind_client
    token = _get_token()
    if not token:
        return ""
    bsr_low = min(r["price"] for r in bsr_rows)
    bsr_high = max(r["price"] for r in bsr_rows)
    bsr_volume = sum(r["buy"] for r in bsr_rows)
    target = target or datetime.now().strftime("%Y%m%d")
    end_dt = datetime.strptime(target, "%Y%m%d")
    start_dt = end_dt - timedelta(days=15)
    try:
        rows = finmind_client.fetch_stock_price(
            stock_code,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
            token,
        )
    except Exception:
        return ""
    if not rows:
        return ""
    # Walk newest → oldest. Match by exact volume first (most discriminating),
    # then by price range as fallback.
    for r in reversed(rows):
        try:
            fm_high = float(r.get("max", 0))
            fm_low = float(r.get("min", 0))
            fm_vol = int(r.get("Trading_Volume", 0))
        except (TypeError, ValueError):
            continue
        # Volume match — single-share precision suffices to identify the day
        if fm_vol == bsr_volume:
            return r["date"].replace("-", "")
        # Fallback: price range within 5 cents
        if abs(fm_high - bsr_high) < 0.05 and abs(fm_low - bsr_low) < 0.05:
            return r["date"].replace("-", "")
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


def broker_concentration_band(cells: list[dict], side: str = "buy",
                              threshold: float = 0.7) -> dict | None:
    """Find the tightest contiguous price range containing `threshold`
    fraction of this broker's `side`-volume.

    Each broker has their own price profile — uniform day-level high/mid/low
    bands hide the per-broker concentration. This finds, e.g., that 高盛
    bought 70% of their volume in a narrow $258~$264 cluster, while
    摩根大通 spread the same 70% across $250~$262.

    Returns {core_low, core_high, core_volume, core_pct, total_volume}
    or None if no `side`-volume in cells.
    """
    side_vol = sum(c[side] for c in cells)
    if side_vol == 0:
        return None
    target = side_vol * threshold
    sorted_cells = sorted(cells, key=lambda c: c["price"])
    n = len(sorted_cells)

    # Sliding window over price-sorted cells: shrink from left whenever the
    # window still covers >= target volume, track the smallest price-width
    # window that ever did.
    best_low_idx, best_high_idx, best_width = 0, n - 1, float("inf")
    left = 0
    cur_vol = 0
    for right in range(n):
        cur_vol += sorted_cells[right][side]
        while left < right and cur_vol - sorted_cells[left][side] >= target:
            cur_vol -= sorted_cells[left][side]
            left += 1
        if cur_vol >= target:
            width = sorted_cells[right]["price"] - sorted_cells[left]["price"]
            if width < best_width:
                best_width = width
                best_low_idx, best_high_idx = left, right

    core_volume = sum(
        sorted_cells[i][side]
        for i in range(best_low_idx, best_high_idx + 1)
    )
    return {
        "core_low": sorted_cells[best_low_idx]["price"],
        "core_high": sorted_cells[best_high_idx]["price"],
        "core_volume": core_volume,
        "core_pct": core_volume / side_vol,
        "total_volume": side_vol,
    }


def broker_top_cells(cells: list[dict], side: str = "buy",
                     n: int = 3) -> list[dict]:
    """Top `n` cells for `side` (buy/sell), sorted by that side's volume desc.

    Skips cells with zero `side`-volume. Returns at most `n` cells.
    """
    filtered = [c for c in cells if c[side] > 0]
    filtered.sort(key=lambda c: -c[side])
    return filtered[:n]


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

    # Fingerprint — each broker's concentration is computed against their
    # OWN price activity, not the day's uniform high/mid/low bands.
    def _emit_broker_detail(b: dict, side: str) -> None:
        cells = b.get("cells", [])
        band = broker_concentration_band(cells, side=side, threshold=0.7)
        if band:
            sign = "+" if side == "buy" else "-"
            label = "主買集中區" if side == "buy" else "主賣集中區"
            lines.append(
                f"    🎯 {label}: ${band['core_low']:.2f}~${band['core_high']:.2f} "
                f"({sign}{_fmt_zhang(band['core_volume'])}張，佔該分點"
                f"{'買進' if side == 'buy' else '賣出'}量 "
                f"{band['core_pct'] * 100:.0f}%)"
            )
        top = broker_top_cells(cells, side=side, n=3)
        if top:
            sign = "+" if side == "buy" else "-"
            parts = [
                f"${c['price']:.2f} {sign}{_fmt_zhang(c[side])}張"
                for c in top
            ]
            label = "Top 3 買價" if side == "buy" else "Top 3 賣價"
            lines.append(f"    {label}: {' / '.join(parts)}")

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
            _emit_broker_detail(b, "buy")
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
            _emit_broker_detail(b, "sell")

    # Continuity footer — pull recent history (default 5 trading days)
    continuity = _format_continuity(data, days=5)
    if continuity:
        lines.append("")
        lines.extend(continuity)

    return "\n".join(lines)


def save_history(data: dict, days_to_keep: int = HISTORY_KEEP_DAYS) -> None:
    """Save an analyze() output to the per-stock history archive.

    Writes to `chip_price_history/{code}_{date}.json` (full data including
    fingerprint cells and stage breakdown — typically 30-60 KB per file).
    Prunes the same stock's older entries so only the `days_to_keep` newest
    remain. Silently no-ops if data is missing stock_code or date.
    """
    import glob
    if not data.get("stock_code") or not data.get("date"):
        return
    os.makedirs(HISTORY_DIR, exist_ok=True)
    fp = os.path.join(HISTORY_DIR, f"{data['stock_code']}_{data['date']}.json")
    with open(fp, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    pattern = os.path.join(HISTORY_DIR, f"{data['stock_code']}_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    for old in files[days_to_keep:]:
        try:
            os.remove(old)
        except OSError:
            pass


def load_history(stock_code: str, days: int = HISTORY_KEEP_DAYS,
                 base_dir: str | None = None) -> list[dict]:
    """Read up to `days` most recent history entries for `stock_code`.

    Returns list sorted by date descending (newest first). Empty list if no
    history or directory missing. Silently skips files that fail to parse.
    `base_dir` resolves to HISTORY_DIR at call time when None (lets tests
    patch the module-level constant after import).
    """
    import glob
    if base_dir is None:
        base_dir = HISTORY_DIR
    pattern = os.path.join(base_dir, f"{stock_code}_*.json")
    files = sorted(glob.glob(pattern), reverse=True)[:days]
    out = []
    for fp in files:
        try:
            with open(fp) as f:
                out.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _format_continuity(data: dict, days: int = 5) -> list[str]:
    """Return a 連續性 footer comparing today's top buyers/sellers to history.

    For each of today's Top 3 buyers and sellers, counts how many of the past
    `days` trading days they appeared in that day's Top 3 (same side). Empty
    list if no usable history.
    """
    history = load_history(data["stock_code"], days=days + 1)
    today_date = data.get("date", "")
    history = [h for h in history if h.get("date") and h["date"] != today_date]
    if not history:
        return []

    today_buyers = data["fingerprint"]["top_buyers"][:3]
    today_sellers = data["fingerprint"]["top_sellers"][:3]
    today_buyer_ids = [b["broker_id"] for b in today_buyers]
    today_seller_ids = [s["broker_id"] for s in today_sellers]

    buyer_counts: dict[str, int] = {}
    seller_counts: dict[str, int] = {}
    for h in history:
        fp = h.get("fingerprint", {})
        past_buyers = [b["broker_id"] for b in fp.get("top_buyers", [])[:3]]
        past_sellers = [s["broker_id"] for s in fp.get("top_sellers", [])[:3]]
        for bid in today_buyer_ids:
            if bid in past_buyers:
                buyer_counts[bid] = buyer_counts.get(bid, 0) + 1
        for sid in today_seller_ids:
            if sid in past_sellers:
                seller_counts[sid] = seller_counts.get(sid, 0) + 1

    name_for = {b["broker_id"]: b["broker_name"] for b in today_buyers}
    name_for.update({s["broker_id"]: s["broker_name"] for s in today_sellers})

    n_history = len(history)
    lines = [f"【📅 近 {n_history} 個交易日連續性 (今日除外)】"]
    if today_buyer_ids:
        parts = [
            f"{name_for.get(bid, bid)} {buyer_counts.get(bid, 0)}/{n_history}"
            for bid in today_buyer_ids
        ]
        lines.append(f"  🟢 今日 Top 3 買方歷史 Top 3 命中: {' / '.join(parts)}")
    if today_seller_ids:
        parts = [
            f"{name_for.get(sid, sid)} {seller_counts.get(sid, 0)}/{n_history}"
            for sid in today_seller_ids
        ]
        lines.append(f"  🔴 今日 Top 3 賣方歷史 Top 3 命中: {' / '.join(parts)}")
    return lines


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
        # If TWSE returned no_data or empty, try TPEx (上櫃) as a fallback.
        if not bsr or not bsr.get("rows") or bsr.get("no_data"):
            print(f"[INFO] TWSE returned no data for {stock_code}, "
                  f"trying TPEx...", file=sys.stderr)
            try:
                import tpex_scraper
                bsr = tpex_scraper.fetch_tpex_with_prices(stock_code)
            except Exception as e:
                print(f"[ERROR] TPEx fetch failed for {stock_code}: {e}",
                      file=sys.stderr)
                return {}
            if not bsr or not bsr.get("rows") or bsr.get("no_data"):
                print(f"[WARN] No BSR data for {stock_code} on either TWSE "
                      f"or TPEx.", file=sys.stderr)
                return {}
        # Cache write deferred until after step 2 — we want to use FinMind's
        # authoritative trading date in the cache filename.

    # 2. Identify BSR's actual trading day by matching its price+volume
    # against FinMind history. FinMind closes earlier than BSR publishes
    # (~14:00 vs ~17:30), so during that window FinMind's "latest" is one
    # day ahead of BSR's; matching by volume disambiguates.
    inferred_date = infer_bsr_trading_date(stock_code, bsr["rows"], target)
    if inferred_date:
        trading_date = inferred_date
        bsr["date"] = trading_date
    else:
        trading_date = bsr.get("date") or target

    # 3. OHLC for stage range — fetched for the inferred trading day so
    # stage zones bucket BSR cells against that day's actual high/low.
    ohlc = get_ohlc(stock_code, trading_date)
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

    result = {
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
    # 5. Archive to per-stock history (rolling 10 trading days). Idempotent —
    # re-running on the same day overwrites the same file. Skip on --no-fetch
    # since that's typically a debug replay, not a fresh analysis.
    if not no_fetch:
        save_history(result)
    return result


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
