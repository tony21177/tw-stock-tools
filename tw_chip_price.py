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


def _zone_and_tag(price: float, side: str, low: float, high: float,
                  price_to_time: dict | None = None,
                  session_minutes: float = 270.0) -> tuple[str, str]:
    """Return (zone, tag) for a (price, side) cell.

    Zones: early (≤ 25%), mid (25-75%), late (> 75%).
    Tags depend on whether tick data is available (price_to_time given):
    - Time-based (preferred): 早盤買進 / 盤中買進 / 尾盤買進 / 早盤賣壓 etc.
      Labels describe **WHEN** the trade happened (real time-of-day).
    - Price-quartile fallback (no tick): 低檔搶進 / 中檔買進 / 高檔追進 etc.
      Labels describe price level only (time unknown).

    Flat day (rng ≤ 0 in price-fallback) collapses to 'mid'.
    """
    if price_to_time:
        t = price_to_time.get(price)
        if t is not None:
            if t <= 0.25 * session_minutes:
                zone = "early"
            elif t <= 0.75 * session_minutes:
                zone = "mid"
            else:
                zone = "late"
            tags = {
                ("buy", "early"):  "⬇ 早盤買進",
                ("buy", "mid"):    "↗ 盤中買進",
                ("buy", "late"):   "⬆ 尾盤買進",
                ("sell", "early"): "△ 早盤賣壓",
                ("sell", "mid"):   "↘ 盤中賣壓",
                ("sell", "late"):  "▽ 尾盤倒貨",
            }
            return zone, tags.get((side, zone), "")
        # Price not in tick map — fall through to price-quartile

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
        ("buy", "early"):  "⬇ 低檔搶進",
        ("buy", "mid"):    "↗ 中檔買進",
        ("buy", "late"):   "▽ 高檔追進",
        ("sell", "early"): "△ 低檔賣壓",
        ("sell", "mid"):   "↘ 中檔出脫",
        ("sell", "late"):  "⬆ 高檔倒貨",
    }
    return zone, tags.get((side, zone), "")


def top_cells(rows: list[dict], top_n: int = 10,
               low: float = 0.0, high: float = 0.0,
               price_to_time: dict | None = None) -> list[dict]:
    """Top N (broker, price, side) cells by volume.

    Each row contributes up to 2 cells (one buy, one sell, if both > 0).
    Returns list sorted by volume descending:
      [{broker_id, broker_name, price, side ('buy'|'sell'), volume,
        zone, tag}, ...]

    `price_to_time` enables time-based zone/tag labels (consistent with
    time_stage_breakdown). Without it, falls back to price-quartile.
    """
    cells = []
    for r in rows:
        if r["buy"] > 0:
            zone, tag = _zone_and_tag(r["price"], "buy", low, high,
                                       price_to_time=price_to_time)
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
            zone, tag = _zone_and_tag(r["price"], "sell", low, high,
                                       price_to_time=price_to_time)
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


def build_tick_index(stock_code: str, date: str) -> dict[float, list[tuple[float, int]]]:
    """Per-price tick index: {price: [(time_min, volume_zhang), ...]} sorted
    by time ascending. Used by match_cell_to_ticks for exact volume matching.

    Verified empirically (2026-05-14): tick `volume` field is in 張 (not 股),
    matching the BSR cell `buy`/`sell` units. So a BSR cell `(price, 50)` can
    be matched directly to a tick `(price, vol=50)`.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return {}
    date_dash = (f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                 if len(date) == 8 else date)
    try:
        ticks = finmind_client.fetch_stock_price_tick(stock_code, date_dash, token)
    except Exception:
        return {}
    if not ticks:
        return {}
    by_price: dict[float, list[tuple[float, int]]] = {}
    for t in ticks:
        try:
            p = float(t["deal_price"])
            v = int(t["volume"])
        except (KeyError, ValueError, TypeError):
            continue
        if v <= 0:
            continue
        t_str = t.get("Time", "")
        parts = t_str.split(":")
        if len(parts) != 3:
            continue
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
        except ValueError:
            continue
        minutes = (h - 9) * 60 + m + s / 60.0
        by_price.setdefault(p, []).append((minutes, v))
    for p in by_price:
        by_price[p].sort()
    return by_price


def match_cell_to_ticks(price: float, shares_zhang: int,
                        tick_list: list[tuple[float, int]],
                        window_max: int = 30,
                        leading_threshold: float = 0.5) -> dict | None:
    """Pinpoint a broker cell's trade time by matching its volume against the
    raw tick stream at that price.

    Strategies in order of preference (confidence high → low):
      1. leading_block   — largest tick ≤ cell_vol that takes ≥ 50% of the
                            cell. Extends forward to neighbouring small ticks
                            until volumes sum to cell_vol (tight cluster).
                            This is the most reliable case for big-block
                            broker orders surrounded by 1-3張 cleanup ticks.
      2. exact           — exactly one tick has vol == shares_zhang
      3. window          — contiguous run of ticks sums to shares
      4. weighted        — fallback: vol-weighted avg time of all ticks

    Validated via user ground truth (2026-05-14):
      第一員林 \$50.30 52張 (50張 block at 11:35:38 + 2張 cleanup)
        → leading_block: 50張 dominant @ 11:35:38, plus 2x 1張 within 30s
        → time ~11:35:40, match_type=leading_block ✓
      第一員林 \$50.40 34張 (30張 block at 11:36:12 + 4張 cleanup)
        → leading_block: 30張 dominant @ 11:36:12 + extending
        → time ~11:36:20, match_type=leading_block ✓
    """
    if not tick_list or shares_zhang <= 0:
        return None

    # Strategy 1: leading-block — find a dominant tick STRICTLY SMALLER than
    # the cell, then extend to neighbours to cover the residual. We require
    # lead_v < shares because BSR cells of size ≥ 2張 almost always combine
    # multiple ticks (broker's main block + small cleanup). A single tick
    # with vol == shares is usually a different broker who coincidentally
    # traded the same lot size — handled by Strategy 2 only for tiny cells.
    candidates_by_vol = sorted(
        [(t, v, i) for i, (t, v) in enumerate(tick_list) if 0 < v < shares_zhang],
        key=lambda x: -x[1],
    )
    if candidates_by_vol:
        lead_t, lead_v, lead_i = candidates_by_vol[0]
        if lead_v >= leading_threshold * shares_zhang:
            # Extend forward and backward from lead_i to accumulate to shares
            cum = lead_v
            left, right = lead_i, lead_i
            n = len(tick_list)
            # Greedily add closest neighbours by time until we hit shares
            while cum < shares_zhang and (left > 0 or right < n - 1):
                add_left = (tick_list[left - 1] if left > 0 else None)
                add_right = (tick_list[right + 1] if right < n - 1 else None)
                if add_left is None:
                    pick_right = True
                elif add_right is None:
                    pick_right = False
                else:
                    # Pick the one with smaller time gap from current cluster
                    gap_left = tick_list[left][0] - add_left[0]
                    gap_right = add_right[0] - tick_list[right][0]
                    pick_right = gap_right <= gap_left
                if pick_right:
                    if cum + add_right[1] <= shares_zhang:
                        cum += add_right[1]
                        right += 1
                    else:
                        break
                else:
                    if cum + add_left[1] <= shares_zhang:
                        cum += add_left[1]
                        left -= 1
                    else:
                        break
            window = tick_list[left:right + 1]
            tot_v = sum(v for _, v in window)
            t_avg = sum(t * v for t, v in window) / tot_v
            # Pct of cell explained
            explained = tot_v / shares_zhang
            return {
                "time_min": t_avg,
                "match_type": "leading_block",
                "lead_vol": lead_v,
                "lead_pct": lead_v / shares_zhang,
                "explained": explained,
                "cluster_span_min": (tick_list[right][0] - tick_list[left][0]),
            }

    # Strategy 2: single-tick exact match — ONLY for small cells (< 10張)
    # where it's plausible the broker did one trade of that exact size.
    # For ≥ 10張 we skip this because exact-vol coincidence between brokers
    # is common (large round-lot orders).
    if shares_zhang < 10:
        exact_matches = [t for t, v in tick_list if v == shares_zhang]
        if len(exact_matches) == 1:
            return {"time_min": exact_matches[0], "match_type": "exact"}
        if len(exact_matches) > 1:
            # Detect multi-cluster across the candidate timestamps so user can
            # pick the right one. Reuses cluster gap threshold from Strategy 4.
            cluster_gap_min = 15
            sorted_matches = sorted(exact_matches)
            mc_clusters: list[list[float]] = [[sorted_matches[0]]]
            for t in sorted_matches[1:]:
                if t - mc_clusters[-1][-1] > cluster_gap_min:
                    mc_clusters.append([])
                mc_clusters[-1].append(t)
            t_avg = sum(exact_matches) / len(exact_matches)
            if len(mc_clusters) >= 2:
                return {
                    "time_min": t_avg,
                    "match_type": "exact_ambiguous_multi_cluster",
                    "candidate_count": len(exact_matches),
                    "clusters": [
                        {"first_min": c[0], "last_min": c[-1],
                         "tick_count": len(c), "vol": len(c) * shares_zhang}
                        for c in mc_clusters
                    ],
                }
            return {
                "time_min": t_avg,
                "match_type": "exact_ambiguous",
                "candidate_count": len(exact_matches),
            }

    # Strategy 3: sliding window summing to shares
    n = len(tick_list)
    best = None
    for i in range(n):
        cum = 0
        for j in range(i, min(i + window_max, n)):
            cum += tick_list[j][1]
            if cum == shares_zhang:
                window = tick_list[i:j + 1]
                tot_v = sum(v for _, v in window)
                t_avg = sum(t * v for t, v in window) / tot_v
                span = tick_list[j][0] - tick_list[i][0]
                if best is None or span < best["span"]:
                    best = {"time_min": t_avg, "span": span,
                            "match_type": "window",
                            "tick_count": j - i + 1}
                break
            if cum > shares_zhang:
                break
    if best:
        del best["span"]
        return best

    # Strategy 4: vol-weighted avg fallback (+ multi-cluster detection)
    tot_v = sum(v for _, v in tick_list)
    if tot_v == 0:
        return None
    t_avg = sum(t * v for t, v in tick_list) / tot_v

    # Detect multiple time-clusters (gap >= 15 min between consecutive ticks).
    # Small cells (1-3張) in a hot price with 2+ clusters → point estimate
    # lands in dead-zone between clusters and misleads. Better to surface
    # cluster ranges so user can pick the right one from their own memory.
    cluster_gap_min = 15
    clusters: list[list] = [[tick_list[0]]]
    for i in range(1, len(tick_list)):
        if tick_list[i][0] - tick_list[i - 1][0] > cluster_gap_min:
            clusters.append([])
        clusters[-1].append(tick_list[i])
    if len(clusters) >= 2 and shares_zhang <= 5:
        # Only surface clusters for tiny cells where they actually help
        cluster_info = []
        for c in clusters:
            c_vol = sum(v for _, v in c)
            cluster_info.append({
                "first_min": c[0][0],
                "last_min": c[-1][0],
                "vol": c_vol,
                "tick_count": len(c),
            })
        return {
            "time_min": t_avg,
            "match_type": "weighted_multi_cluster",
            "clusters": cluster_info,
        }
    return {"time_min": t_avg, "match_type": "weighted"}


def build_price_to_time_map(stock_code: str, date: str) -> dict:
    """For each price level, return the volume-weighted avg time-of-day
    (in minutes from 9:00 open) it was traded. Backed by FinMind tick data.

    Returns {price (float): minutes_from_open (float)} or {} on failure.

    This is the bridge between BSR's per-(broker, price) cells (no time) and
    intraday time-of-day. With this map we can estimate when each broker
    cell was likely traded: cell @ \$240 → mapped to ~minute 75 (10:15) etc.

    Stocks/days with high volatility at a single price level (e.g., closing
    auction at the day-low) will produce a clean late-time estimate for that
    price. Pricier levels traded only briefly (e.g., opening tick) will pin
    to early time.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return {}
    date_dash = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
    try:
        ticks = finmind_client.fetch_stock_price_tick(stock_code, date_dash, token)
    except Exception:
        return {}
    if not ticks:
        return {}
    by_price = {}
    for t in ticks:
        try:
            p = float(t["deal_price"])
            v = int(t["volume"])
        except (KeyError, ValueError, TypeError):
            continue
        if v <= 0:
            continue
        # Parse "HH:MM:SS.ffffff" → minutes from 09:00
        t_str = t.get("Time", "")
        parts = t_str.split(":")
        if len(parts) != 3:
            continue
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
        except ValueError:
            continue
        minutes_from_open = (h - 9) * 60 + m + s / 60.0
        if p not in by_price:
            by_price[p] = [0.0, 0]  # [weighted_sum, total_volume]
        by_price[p][0] += minutes_from_open * v
        by_price[p][1] += v
    return {p: data[0] / data[1] for p, data in by_price.items() if data[1] > 0}


def _minutes_to_hhmm(minutes: float) -> str:
    """Convert minutes-from-9:00 to '~HH:MM' format. Negative or >290 → edge."""
    if minutes < 0:
        return "盤前"
    if minutes > 290:  # past 13:50
        return "尾盤後"
    total = int(round(minutes))
    h = 9 + total // 60
    m = total % 60
    return f"{h:02d}:{m:02d}"


def time_stage_breakdown(rows: list[dict], price_to_time: dict,
                         session_minutes: float = 270.0) -> dict:
    """Bucket rows into 3 time zones (early/mid/late) by estimated time-of-day.

    Uses the price→time map from FinMind tick data to assign each (broker,
    price, side) row to its estimated trading time. Buckets:
      early = 0 - 25% of session  (09:00 - ~10:08)
      mid   = 25% - 75% of session  (~10:08 - ~12:22)
      late  = 75% - 100% of session  (~12:22 - 13:30)

    More accurate than price-quartile stage on V-shaped or 反轉 days where
    the same price level is traded multiple times across the session.

    Same return shape as stage_breakdown: {zone: [per-broker dict, ...]}.
    Rows whose price isn't in price_to_time are silently dropped.
    """
    if not price_to_time or session_minutes <= 0:
        return {"early": [], "mid": [], "late": []}
    early_max = 0.25 * session_minutes
    late_min = 0.75 * session_minutes
    zone_rows = {"early": [], "mid": [], "late": []}
    for r in rows:
        t = price_to_time.get(r["price"])
        if t is None:
            continue
        if t <= early_max:
            zone_rows["early"].append(r)
        elif t <= late_min:
            zone_rows["mid"].append(r)
        else:
            zone_rows["late"].append(r)
    result = {}
    for zone, zrows in zone_rows.items():
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
        result[zone] = sorted(per_broker.values(),
                              key=lambda x: -abs(x["net_shares"]))
    return result


def _cell_candidates(cell_vol: int, tick_list: list[tuple[float, int]],
                     leading_threshold: float = 0.7) -> list[dict]:
    """All plausible leading-block candidates for a cell.

    Each candidate: a tick whose vol >= leading_threshold * cell_vol and < cell_vol.
    For each, we extend forward/backward greedily to neighbours summing to
    cell_vol (or close), capturing the candidate's cluster span.
    """
    if not tick_list or cell_vol <= 0:
        return []
    n = len(tick_list)
    cands = []
    for i, (lead_t, lead_v) in enumerate(tick_list):
        if not (0 < lead_v < cell_vol):
            continue
        if lead_v < leading_threshold * cell_vol:
            continue
        # Extend to fill cell_vol
        cum = lead_v
        left, right = i, i
        while cum < cell_vol and (left > 0 or right < n - 1):
            add_left = tick_list[left - 1] if left > 0 else None
            add_right = tick_list[right + 1] if right < n - 1 else None
            if add_left is None:
                pick_right = True
            elif add_right is None:
                pick_right = False
            else:
                gap_left = tick_list[left][0] - add_left[0]
                gap_right = add_right[0] - tick_list[right][0]
                pick_right = gap_right <= gap_left
            if pick_right:
                if cum + add_right[1] <= cell_vol:
                    cum += add_right[1]
                    right += 1
                else:
                    break
            else:
                if cum + add_left[1] <= cell_vol:
                    cum += add_left[1]
                    left -= 1
                else:
                    break
        window = tick_list[left:right + 1]
        tot_v = sum(v for _, v in window)
        t_avg = sum(t * v for t, v in window) / tot_v
        cands.append({
            "lead_time": lead_t,
            "lead_vol": lead_v,
            "lead_pct": lead_v / cell_vol,
            "cluster_time": t_avg,
            "cluster_span_min": tick_list[right][0] - tick_list[left][0],
            "tick_count": right - left + 1,
            "explained": tot_v / cell_vol,
        })
    # Sort priority (ground-truth-validated 2026-05-14 across 4 cases):
    #
    # When ≥2 candidates have lead_pct ≥ 70%, prefer wider cluster_span_min
    # (broker accumulation pattern — lead + cleanup over time, vs another
    # broker's isolated coincidental same-vol tick).
    #
    # 3 / 4 ground-truth cases pass:
    #   ✅ 第一員林 \$50.30 52張 — 50張 span 14s wins over 51張 span 0s
    #   ✅ 第一員林 \$50.40 34張 — 30張 span 35s wins
    #   ✅ 兆豐台南 \$50.60 37張 — 30張 span 4 min wins over 35張 span 3s
    #
    # Known limitation:
    #   ❌ 兆豐台南 \$50.20  8張 — user did 4張 + 4×1張 in 4 SECONDS (compact);
    #      max single broker block = 4張 = 50% of cell (below 70%
    #      threshold for high-confidence bucket), and even at 50% threshold
    #      the span (4s) doesn't dominate other broker's 7張+1 span (7s).
    #      → Algorithm cannot disambiguate when broker fills in micro-burst
    #      that's indistinguishable from other brokers' similar bursts.
    #      Surfaced as `is_scattered=True` in result. User sees alternatives.
    high_pct = [c for c in cands if c["lead_pct"] >= 0.7]
    low_pct = [c for c in cands if c["lead_pct"] < 0.7]
    high_pct.sort(key=lambda c: (-c["cluster_span_min"], -c["lead_vol"]))
    low_pct.sort(key=lambda c: (-c["lead_vol"], -c["cluster_span_min"]))
    return high_pct + low_pct


def match_broker_cells_consistent(
    cells: list[dict], side: str, ticks_by_price: dict,
) -> dict[float, dict]:
    """Match each cell to a tick time, using cross-cell temporal consistency.

    Two-pass:
      1. For each cell, find candidate leading-blocks. Cells with a single
         dominant candidate become "anchors" (high confidence).
      2. Anchor centroid time = volume-weighted avg of anchor cluster times.
         For ambiguous cells (multiple candidates), pick the candidate whose
         time is closest to the anchor centroid.

    This resolves cases like 第一員林 \$50.30 52張: candidates 50張@11:35 and
    51張@13:20 are nearly equal in size. But \$50.40 34張 anchors to 11:36
    (only one dominant candidate). Centroid pulls \$50.30 toward 11:35.

    Returns {cell_price: {time_min, match_type, ...}}.
    """
    if not ticks_by_price:
        return {}
    # Phase 1: per-cell candidate enumeration
    cell_data: list[tuple[dict, list[dict]]] = []
    for c in cells:
        v = c[side]
        if v == 0:
            continue
        ticks = ticks_by_price.get(c["price"], [])
        cands = _cell_candidates(v, ticks)
        cell_data.append((c, cands))

    # Phase 2: identify anchors. A cell is an "anchor" if its top candidate is
    # clearly the best — either the only one, OR distinctly larger vol than
    # alternatives, OR distinctly wider cluster span (broker accumulation
    # pattern). Wider cluster = more ticks needed to cover the cell = more
    # like one broker's many small trades than another broker's coincidence.
    anchor_points: list[tuple[float, int]] = []
    for c, cands in cell_data:
        if not cands:
            continue
        if len(cands) == 1:
            anchor_points.append((cands[0]["cluster_time"], c[side]))
            continue
        top = cands[0]
        second = cands[1]
        if top["lead_vol"] >= 1.3 * second["lead_vol"]:
            anchor_points.append((top["cluster_time"], c[side]))
        elif (top["lead_vol"] == second["lead_vol"]
              and top["cluster_span_min"] >= 5 * max(second["cluster_span_min"], 1e-6)):
            # Same vol but top has 5x wider cluster = more like broker pattern
            anchor_points.append((top["cluster_time"], c[side]))

    centroid = None
    if anchor_points:
        tot_w = sum(w for _, w in anchor_points)
        centroid = sum(t * w for t, w in anchor_points) / tot_w

    # Phase 3: assign final times
    results = {}
    for c, cands in cell_data:
        vol = c[side]
        price = c["price"]
        ticks = ticks_by_price.get(price, [])
        if not cands:
            # No leading-block candidate — try single-cell match_cell_to_ticks
            # (for small cells / exact matches / weighted fallback)
            m = match_cell_to_ticks(price, vol, ticks)
            if m:
                results[price] = m
            continue
        if len(cands) == 1 or centroid is None:
            picked = cands[0]
        else:
            # Multiple candidates — pick the one closest to centroid
            picked = min(cands, key=lambda x: abs(x["cluster_time"] - centroid))
            top = cands[0]
            if picked["lead_vol"] >= 0.85 * top["lead_vol"]:
                # Cross-cell consistency selected a near-top candidate
                pass
        # Also surface up to 2 alternative candidates (different times from
        # the primary pick) so the UI can show "OR ~XX:XX" when ambiguity is
        # real. Each alt: {time_min, lead_vol, lead_pct, cluster_span_min}.
        alts = []
        for cd in cands:
            if cd is picked:
                continue
            if abs(cd["cluster_time"] - picked["cluster_time"]) < 5:
                # Same time window as picked — not a meaningful alternative
                continue
            alts.append({
                "time_min": cd["cluster_time"],
                "lead_vol": cd["lead_vol"],
                "lead_pct": cd["lead_pct"],
                "cluster_span_min": cd["cluster_span_min"],
            })
            if len(alts) >= 2:
                break
        # Detect "scattered" pattern: no candidate has lead_vol ≥ 50% of cell
        # (broker likely did many small ticks, no dominant block)
        max_lead_pct = max(c["lead_pct"] for c in cands) if cands else 0
        is_scattered = max_lead_pct < 0.5
        results[price] = {
            "time_min": picked["cluster_time"],
            "match_type": ("leading_block_consistent"
                           if centroid is not None and len(cands) >= 2
                           else "leading_block"),
            "lead_vol": picked["lead_vol"],
            "lead_pct": picked["lead_pct"],
            "cluster_span_min": picked["cluster_span_min"],
            "n_candidates": len(cands),
            "alternatives": alts,
            "is_scattered": is_scattered,
        }
    return results


def broker_time_estimate(cells: list[dict], side: str,
                         price_to_time: dict) -> float | None:
    """Volume-weighted avg time (minutes from open) the broker traded on `side`.

    Uses the price_to_time map to look up each cell's price. Cells whose price
    isn't in the map are skipped. Returns None if no estimable cells.
    """
    if not price_to_time:
        return None
    total_val = 0.0
    total_vol = 0
    for c in cells:
        v = c[side]
        if v == 0:
            continue
        t = price_to_time.get(c["price"])
        if t is None:
            continue
        total_val += t * v
        total_vol += v
    if total_vol == 0:
        return None
    return total_val / total_vol


def broker_wash_candidates(rows: list[dict], day_low: float, day_high: float,
                           top_n: int = 5, min_each_side: int = 1000,
                           min_wash_score: float = 0.05,
                           price_to_time: dict | None = None) -> list[dict]:
    """Detect 同分點 高賣低買 (sold high then bought low same day) — looks
    like distribution on net basis but is actually accumulation.

    Example: broker sells 5,000張 @ avg \$245 + buys 3,000張 @ avg \$238
    on a day with [low \$235, high \$250] range. Net is -2,000張 (looks like
    selling), but the broker accumulated 3,000張 at materially lower prices
    than they sold the 5,000張. That's 洗盤低接 — bullish for the smart
    side of the trade.

    For each broker with two-sided activity, computes:
      wash_score = (sell_avg_price - buy_avg_price) / day_range
        > 0  → sold higher than bought = 高賣低買 (bullish accumulation)
        < 0  → bought higher than sold = 追漲後出 (bearish distribution)

    Returns Top N sorted by wash_score weighted by log(min_volume) so
    noise from tiny-volume two-sided rows doesn't drown out real signal.
    Skips wash_score < min_wash_score and brokers without min_each_side
    on both sides.
    """
    import math
    per_broker = {}
    for r in rows:
        bid = r["broker_id"]
        agg = per_broker.setdefault(bid, {
            "broker_id": bid,
            "broker_name": r["broker_name"],
            "buy_shares": 0,
            "sell_shares": 0,
            "_buy_value": 0.0,
            "_sell_value": 0.0,
            "_cells": [],
        })
        agg["buy_shares"] += r["buy"]
        agg["sell_shares"] += r["sell"]
        agg["_buy_value"] += r["price"] * r["buy"]
        agg["_sell_value"] += r["price"] * r["sell"]
        agg["_cells"].append({"price": r["price"], "buy": r["buy"], "sell": r["sell"]})

    day_range = max(day_high - day_low, 0.01)
    candidates = []
    for b in per_broker.values():
        if b["buy_shares"] < min_each_side or b["sell_shares"] < min_each_side:
            continue
        buy_avg = b["_buy_value"] / b["buy_shares"]
        sell_avg = b["_sell_value"] / b["sell_shares"]
        wash_score = (sell_avg - buy_avg) / day_range
        if wash_score < min_wash_score:
            continue
        cand = {
            "broker_id": b["broker_id"],
            "broker_name": b["broker_name"],
            "buy_shares": b["buy_shares"],
            "sell_shares": b["sell_shares"],
            "net_shares": b["buy_shares"] - b["sell_shares"],
            "buy_avg": round(buy_avg, 2),
            "sell_avg": round(sell_avg, 2),
            "wash_score": wash_score,
            "price_gap": round(sell_avg - buy_avg, 2),
            "cells": b["_cells"],
        }
        # Time-based classification — needs tick data
        if price_to_time:
            buy_t = broker_time_estimate(b["_cells"], "buy", price_to_time)
            sell_t = broker_time_estimate(b["_cells"], "sell", price_to_time)
            if buy_t is not None and sell_t is not None:
                cand["buy_time_min"] = round(buy_t, 1)
                cand["sell_time_min"] = round(sell_t, 1)
                # ≥ 30 min difference = clear direction; else 模糊
                if buy_t - sell_t >= 30:
                    cand["time_pattern"] = "真洗盤低接"  # bought LATER than sold
                elif sell_t - buy_t >= 30:
                    cand["time_pattern"] = "追漲獲利出"  # sold LATER than bought
                else:
                    cand["time_pattern"] = "時序模糊"
        candidates.append(cand)
    candidates.sort(
        key=lambda c: -c["wash_score"] * math.log(
            min(c["buy_shares"], c["sell_shares"]) + 1
        )
    )
    return candidates[:top_n]


def adaptive_concentration_band(cells: list[dict], side: str,
                                day_low: float, day_high: float,
                                max_band_pct: float = 0.25) -> dict | None:
    """Pick the tightest meaningful concentration band for a broker.

    Tries thresholds 70% → 60% → 50% → 40% → 30%, picks the highest whose
    resulting band width is ≤ `max_band_pct` of the day's range. Default
    25% prevents the misleading "$237.5–$245.5 contains 71%" type bands
    where the broker's activity is too spread to be actionable.

    Falls back to narrowest threshold (30%) if every higher one is too wide.
    Returned dict has the standard concentration_band keys plus
    `threshold_used`.
    """
    day_range = max(day_high - day_low, 0.01)
    for t in (0.7, 0.6, 0.5, 0.4, 0.3):
        band = broker_concentration_band(cells, side=side, threshold=t)
        if not band:
            return None
        width = band["core_high"] - band["core_low"]
        if width / day_range <= max_band_pct:
            band["threshold_used"] = t
            return band
    band = broker_concentration_band(cells, side=side, threshold=0.3)
    if band:
        band["threshold_used"] = 0.3
    return band


def broker_band_progression(stock_code: str, broker_id: str,
                            side: str = "buy", n_days: int = 4,
                            threshold: float = 0.7) -> list[dict]:
    """Return the broker's main `side`-band for each of the last n_days.

    Reads chip_price_history, finds the broker in each day's
    fingerprint.top_buyers/top_sellers, runs broker_concentration_band on
    their cells. Used to render multi-day price-band progression — was the
    broker pushing the band upward day-by-day (推升) or staying flat
    (averaging in)?

    Returns list of {date, low, high, volume, pct} ordered by date asc.
    Empty if no history or broker absent.
    """
    history = load_history(stock_code, days=n_days)
    if not history:
        return []
    side_key = "top_buyers" if side == "buy" else "top_sellers"
    progression = []
    for h in history:
        broker = next(
            (b for b in h.get("fingerprint", {}).get(side_key, [])
             if b.get("broker_id") == broker_id),
            None,
        )
        if not broker:
            continue
        cells = broker.get("cells", [])
        if not cells:
            continue
        band = broker_concentration_band(cells, side=side, threshold=threshold)
        if not band:
            continue
        progression.append({
            "date": h.get("date", ""),
            "low": band["core_low"],
            "high": band["core_high"],
            "volume": band["core_volume"],
            "pct": band["core_pct"],
        })
    progression.sort(key=lambda x: x["date"])
    return progression


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

    # Stage analysis — time-based when tick data was available, else price quartile
    basis = data.get("stage_basis", "price")
    if basis == "time":
        lines.append("【⏰ 三階段分析】(以實際成交時間切分)")
        lines.append("早盤 (前 25% 時間: 09:00 ~ ~10:08):")
        _emit_zone(lines, data["stage"].get("early", []))
        lines.append("")
        lines.append("盤中 (中 50% 時間: ~10:08 ~ ~12:22):")
        _emit_zone(lines, data["stage"].get("mid", []))
        lines.append("")
        lines.append("尾盤 (後 25% 時間: ~12:22 ~ 13:30):")
        _emit_zone(lines, data["stage"].get("late", []))
        lines.append("")
    else:
        lines.append("【⏰ 三階段分析】(以價格 quartile 為時間 proxy — 無 tick 資料)")
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
        band = adaptive_concentration_band(
            cells, side=side, day_low=ohlc["low"], day_high=ohlc["high"],
            max_band_pct=0.25,
        )
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
        # C 軌跡 — multi-day main-band progression (skip if < 2 history days)
        progression = broker_band_progression(
            data["stock_code"], b["broker_id"], side=side, n_days=5,
        )
        today = data.get("date", "")
        past = [p for p in progression if p["date"] != today]
        if len(past) >= 1:
            arrow_parts = [
                f"{p['date'][4:6]}/{p['date'][6:8]} ${p['low']:.2f}~${p['high']:.2f}"
                for p in past
            ]
            # Append today's band as the rightmost point
            if band:
                arrow_parts.append(
                    f"{today[4:6]}/{today[6:8]} "
                    f"${band['core_low']:.2f}~${band['core_high']:.2f} (今)"
                )
            # Heuristic: if low end shifted up over time, label as 推升
            lows = [p["low"] for p in past]
            if band:
                lows.append(band["core_low"])
            trend = "推升中" if lows[-1] > lows[0] else (
                "下移" if lows[-1] < lows[0] else "盤整"
            )
            label = "主買區軌跡" if side == "buy" else "主賣區軌跡"
            lines.append(f"    📈 {label} ({trend}): "
                          + " → ".join(arrow_parts))

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

    # Wash candidates — 高賣低買 same-day pattern (淨賣超但實際低接收貨)
    wash = data.get("wash_candidates", [])
    if wash:
        rng = max(ohlc["high"] - ohlc["low"], 0.01)
        lines.append("")
        lines.append("【🌀 高賣低買 — 同分點兩面操作 (洗盤低接型態)】")
        for w in wash:
            net = w["net_shares"]
            net_str = (f"淨買 +{_fmt_zhang(net)}張" if net > 0
                       else f"淨賣 {_fmt_zhang(net)}張")
            pct_of_range = w["price_gap"] / rng * 100
            pat = w.get("time_pattern", "")
            # Choose interpretation based on time pattern (preferred) or net (fallback)
            if pat == "真洗盤低接":
                interpret = "← ✅ 真洗盤低接 (確認順序: 先賣高、後買低)"
            elif pat == "追漲獲利出":
                interpret = "← ⚠ 追漲獲利出 (順序: 先買低、後賣高 — 非洗盤)"
            elif pat == "時序模糊":
                interpret = "← ⏱ 時序模糊 (買賣時間相近，無法區分)"
            else:
                interpret = (
                    "← 看似空、實際多 (淨賣但低接更多籌碼)"
                    if net < 0
                    else "← 同分點兩面操作，但確實淨買"
                )
            buy_t = w.get("buy_time_min")
            sell_t = w.get("sell_time_min")
            time_str = ""
            if buy_t is not None and sell_t is not None:
                time_str = (f" / 賣 ~{_minutes_to_hhmm(sell_t)} "
                              f"/ 買 ~{_minutes_to_hhmm(buy_t)}")
            lines.append(
                f"  {w['broker_id']} {w['broker_name']}: "
                f"賣 {_fmt_zhang(w['sell_shares'])}張 (avg ${w['sell_avg']:.2f}) "
                f"/ 買 {_fmt_zhang(w['buy_shares'])}張 (avg ${w['buy_avg']:.2f})"
                f"{time_str}"
            )
            lines.append(
                f"    → 高賣低買差 +${w['price_gap']:.2f} "
                f"({pct_of_range:.0f}% of 全日範圍)，{net_str} {interpret}"
            )
            _emit_broker_detail(w, "sell")
            _emit_broker_detail(w, "buy")

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


def _aggregate_broker_history(history: list[dict]) -> dict[str, dict]:
    """Aggregate per-broker net activity over the historical window
    (fingerprint-based, top 5 only). Kept as fallback when bsr_cache missing.

    For each broker appearing in any day's `fingerprint.top_buyers` or
    `top_sellers`, sums net_shares across days and tracks days_appeared +
    biggest single-day move. A broker who appeared infrequently but with
    large size will rank high by total_net even with low days_appeared —
    this captures the 「間歇式大量」main-controller pattern that pure
    hit-count continuity misses.
    """
    agg: dict[str, dict] = {}
    for h in history:
        date = h.get("date", "")
        fp = h.get("fingerprint", {})
        for b in fp.get("top_buyers", []) + fp.get("top_sellers", []):
            bid = b["broker_id"]
            rec = agg.setdefault(bid, {
                "broker_id": bid,
                "broker_name": b["broker_name"],
                "total_net": 0,
                "days_appeared": 0,
                "max_day_net": 0,
                "max_day_date": "",
            })
            rec["total_net"] += b["net_shares"]
            rec["days_appeared"] += 1
            if abs(b["net_shares"]) > abs(rec["max_day_net"]):
                rec["max_day_net"] = b["net_shares"]
                rec["max_day_date"] = date
    return agg


def _aggregate_broker_full_bsr(stock_code: str, dates: list[str]) -> dict[str, dict]:
    """Aggregate per-broker net across `dates` from raw bsr_cache (all 800+
    brokers per day, not just top 5). Replaces fingerprint-based aggregation
    when bsr_cache is available — gives complete picture for 連續性 section.

    Each bsr_cache/{stock_code}_{date}.json has {brokers: {bid: {name, buy, sell}}}
    in 股 units. Returns same shape as _aggregate_broker_history.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    bsr_dir = os.path.join(here, "bsr_cache")
    agg: dict[str, dict] = {}
    for date in dates:
        fp = os.path.join(bsr_dir, f"{stock_code}_{date}.json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp) as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for bid, info in d.get("brokers", {}).items():
            net = info.get("buy", 0) - info.get("sell", 0)
            if net == 0:
                continue
            rec = agg.setdefault(bid, {
                "broker_id": bid,
                "broker_name": info.get("name", bid),
                "total_net": 0,
                "days_appeared": 0,
                "max_day_net": 0,
                "max_day_date": "",
            })
            rec["total_net"] += net
            rec["days_appeared"] += 1
            if abs(net) > abs(rec["max_day_net"]):
                rec["max_day_net"] = net
                rec["max_day_date"] = date
    return agg


def _list_bsr_cache_dates(stock_code: str, max_days: int = 30) -> list[str]:
    """Return up to `max_days` most-recent bsr_cache dates for stock_code,
    sorted desc (newest first). Excludes _prices.json files.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    bsr_dir = os.path.join(here, "bsr_cache")
    import glob as _glob
    files = _glob.glob(os.path.join(bsr_dir, f"{stock_code}_*.json"))
    dates = []
    for f in files:
        name = os.path.basename(f).replace(f"{stock_code}_", "").replace(".json", "")
        if "_" in name:  # skip _prices.json
            continue
        if len(name) == 8 and name.isdigit():
            dates.append(name)
    dates.sort(reverse=True)
    return dates[:max_days]


def _format_continuity(data: dict, days: int = 5) -> list[str]:
    """Return a 連續性 footer with three views of historical activity:

    1. Top 3 hit-count (existing) — who consistently makes today's Top 3
    2. N-day cumulative ranking (new) — top accumulators regardless of
       consistency, with ⚡ marker for 間歇大量 (≤40% days but ranked top)
    3. Today's Top 3 N-day fingerprint (new) — for each of today's leaders,
       show their past N-day cumulative + biggest single-day, with `burst`
       tag if today alone is ≥60% of their full window activity

    `days` is the TOTAL number of trading days in the window, including
    today when BSR is published. So days=5 means 1 trading week (Mon-Fri).
    """
    stock_code = data["stock_code"]
    today_date = data.get("date", "")
    today_buyers = data["fingerprint"]["top_buyers"][:3]
    today_sellers = data["fingerprint"]["top_sellers"][:3]
    today_has_data = bool(today_buyers or today_sellers)

    # Pick the `days` most-recent trading days from bsr_cache (the canonical
    # source — bsr_cache has more history than chip_price_history).
    available_dates = _list_bsr_cache_dates(stock_code, max_days=days * 2)
    if today_has_data and today_date and today_date not in available_dates:
        available_dates = sorted([today_date] + available_dates, reverse=True)
    window_dates = available_dates[:days]
    history_dates = [d for d in window_dates if d != today_date]

    # Also pull fingerprint history for Section A hit-rate (needs per-day Top 3)
    history_fp = load_history(stock_code, days=days)
    history_fp = [h for h in history_fp
                  if h.get("date") and h["date"] in history_dates]

    if not window_dates:
        return []
    today_buyer_ids = [b["broker_id"] for b in today_buyers]
    today_seller_ids = [s["broker_id"] for s in today_sellers]

    buyer_counts: dict[str, int] = {}
    seller_counts: dict[str, int] = {}
    for h in history_fp:
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

    n_history = len(history_dates)
    lines = [f"【📅 近 {n_history} 個交易日連續性 (今日除外)】"]

    # === Section A: Top 3 hit count (existing) ===
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

    # === Section B: N-day cumulative ranking (NEW) ===
    # Read from bsr_cache (full per-broker, all 800+ per day) for richer
    # cumulative ranking. Includes today when BSR is published (per user
    # feedback 2026-05-15: 連續性要包含今天，only exclude today when BSR
    # not yet published).
    agg = _aggregate_broker_full_bsr(stock_code, window_dates)
    n_window = len(window_dates)
    # Burst threshold: 出現天數 ≤ 40% of window (rounded down, min 1) =「間歇大量」
    intermittent_threshold = max(1, int(n_window * 0.4))
    buyers_ranked = sorted(
        [r for r in agg.values() if r["total_net"] > 0],
        key=lambda r: -r["total_net"],
    )[:5]
    sellers_ranked = sorted(
        [r for r in agg.values() if r["total_net"] < 0],
        key=lambda r: r["total_net"],
    )[:5]
    window_label = (f"近 {n_window} 日 (含今日 {today_date[4:6]}/{today_date[6:8]})"
                    if today_has_data
                    else f"近 {n_history} 日 (今日數據未公布)")
    if buyers_ranked or sellers_ranked:
        lines.append("")
        lines.append(f"【💰 {window_label} 累積淨買/賣 Top 5】(含間歇大量)")
    def _signed_z(shares: int) -> str:
        """Always sign-prefix 張 — handles negative naturally via format spec."""
        return f"{int(shares / 1000):+,}"

    if buyers_ranked:
        lines.append("  🟢 累積買方 (不限今日 Top 3)")
        for r in buyers_ranked:
            tag = " ⚡ 間歇大量" if r["days_appeared"] <= intermittent_threshold else ""
            md = r["max_day_date"]
            md_short = f"{md[4:6]}/{md[6:8]}" if len(md) == 8 else md
            lines.append(
                f"    {r['broker_name']} {_signed_z(r['total_net'])}張  "
                f"出現 {r['days_appeared']}/{n_window} 天  "
                f"最大日 {md_short} {_signed_z(r['max_day_net'])}{tag}"
            )
    if sellers_ranked:
        lines.append("  🔴 累積賣方 (不限今日 Top 3)")
        for r in sellers_ranked:
            tag = " ⚡ 間歇大量" if r["days_appeared"] <= intermittent_threshold else ""
            md = r["max_day_date"]
            md_short = f"{md[4:6]}/{md[6:8]}" if len(md) == 8 else md
            lines.append(
                f"    {r['broker_name']} {_signed_z(r['total_net'])}張  "
                f"出現 {r['days_appeared']}/{n_window} 天  "
                f"最大日 {md_short} {_signed_z(r['max_day_net'])}{tag}"
            )

    # === Section C: Today's Top 3 N-day fingerprint (NEW) ===
    # agg now INCLUDES today (when published), so rec.total_net is the FULL
    # window total. To still surface today vs prior days separately for
    # readability, subtract today_net from rec.total_net to get past-only.
    today_leaders = [(b, "buy") for b in today_buyers] + \
                    [(s, "sell") for s in today_sellers]
    if today_leaders:
        lines.append("")
        lines.append(f"【⚡ 今日 Top 3 之 {window_label} 累積指紋】")
        for b, side in today_leaders:
            bid = b["broker_id"]
            today_net = b["net_shares"]
            emoji = "🟢" if side == "buy" else "🔴"
            rec = agg.get(bid)
            if rec is None:
                lines.append(
                    f"  {emoji} {b['broker_name']}: 今 {_signed_z(today_net)}張，"
                    f"前 {n_history} 日未進 Top 5 → 新進場"
                )
            else:
                # Past-only (excluding today): subtract today's contribution
                past_net = rec["total_net"] - (today_net if today_has_data else 0)
                past_days = rec["days_appeared"] - (1 if today_has_data else 0)
                full_total = rec["total_net"]
                today_pct = (abs(today_net) / max(abs(full_total), 1)) * 100
                burst = " ← burst (今佔大半)" if today_pct >= 60 else ""
                md = rec["max_day_date"]
                md_short = f"{md[4:6]}/{md[6:8]}" if len(md) == 8 else md
                lines.append(
                    f"  {emoji} {b['broker_name']}: 今 {_signed_z(today_net)}張 + "
                    f"前 {past_days}/{n_history} 天 "
                    f"{_signed_z(past_net)}張 "
                    f"= {n_window} 日累積 {_signed_z(full_total)}張 "
                    f"(歷史最大日 {md_short} "
                    f"{_signed_z(rec['max_day_net'])}){burst}"
                )

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

    # 3. Top cells + stage + fingerprint + wash candidates
    fingerprint = broker_fingerprint(bsr["rows"], top_n=5)
    # Build price→time map from FinMind tick data — used for top_cells tags,
    # wash-candidate time direction AND time-based stage breakdown. Falls
    # back to None on failure → tags + stage use price-quartile heuristic.
    try:
        price_to_time = build_price_to_time_map(stock_code, trading_date)
    except Exception:
        price_to_time = {}
    cells = top_cells(bsr["rows"], top_n=10,
                       low=ohlc["low"], high=ohlc["high"],
                       price_to_time=price_to_time)
    wash = broker_wash_candidates(
        bsr["rows"], day_low=ohlc["low"], day_high=ohlc["high"], top_n=5,
        price_to_time=price_to_time,
    )
    # Prefer time-based stage when tick data is available (correct on V-shaped
    # / reversal days); fall back to price-quartile heuristic otherwise.
    if price_to_time:
        stage = time_stage_breakdown(bsr["rows"], price_to_time)
        stage_basis = "time"
    else:
        stage = stage_breakdown(bsr["rows"], ohlc["low"], ohlc["high"])
        stage_basis = "price"

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
        "stage_basis": stage_basis,
        "fingerprint": fingerprint,
        "wash_candidates": wash,
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
