#!/usr/bin/env python3
"""
Flask web server for concept momentum dashboard.
Serves the generated HTML at http://localhost:5000/
Also serves /chip-price form + on-demand analysis for any stock.
"""

import glob
import html as html_lib
import json
import os
import sys
from datetime import datetime
from flask import Flask, request, send_from_directory, send_file

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
STATIC_DIR = os.path.join(HERE, "static")
TEMPLATES_DIR = os.path.join(HERE, "templates")
CHIP_PRICE_HISTORY = os.path.join(REPO, "chip_price_history")

# Ensure tw_chip_price is importable
if REPO not in sys.path:
    sys.path.insert(0, REPO)

app = Flask(__name__, static_folder=STATIC_DIR)


@app.after_request
def no_cache(resp):
    """Dashboard is regenerated daily — disable any caching so users always
    see the latest run, not yesterday's stale copy from browser cache."""
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def dashboard():
    html_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    if not os.path.exists(html_path):
        return ("Dashboard not generated yet. "
                "Run: python3 concept_charts.py"), 503
    return send_file(html_path)


@app.route("/png")
def latest_png():
    png_path = os.path.join(STATIC_DIR, "latest.png")
    if not os.path.exists(png_path):
        return "No PNG yet", 404
    return send_file(png_path)


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# ── /chip-price web UI ──────────────────────────────────────────────────

def _list_cached_history() -> list[tuple[str, str]]:
    """List existing chip_price_history files as (code, date) tuples,
    sorted by date desc then code asc. Used for quick-pick links."""
    out = []
    for fp in glob.glob(os.path.join(CHIP_PRICE_HISTORY, "*.json")):
        name = os.path.basename(fp)
        # Format: {code}_{date}.json
        parts = name.removesuffix(".json").rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 8 and parts[1].isdigit():
            out.append((parts[0], parts[1]))
    out.sort(key=lambda x: (-int(x[1]), x[0]))
    return out


def _load_or_run(code: str, date: str | None = None,
                 force_fetch: bool = False) -> tuple[dict, str]:
    """Return (analysis_dict, source_label).

    source_label: "cache" | "fresh fetch" | "error: ..."
    """
    if not force_fetch and date:
        fp = os.path.join(CHIP_PRICE_HISTORY, f"{code}_{date}.json")
        if os.path.exists(fp):
            with open(fp) as f:
                return json.load(f), f"快取 ({date})"
    if not force_fetch:
        # Find newest cache for this code
        files = sorted(glob.glob(os.path.join(CHIP_PRICE_HISTORY, f"{code}_*.json")),
                       reverse=True)
        if files:
            with open(files[0]) as f:
                d = json.load(f)
            return d, f"快取 ({d.get('date', '?')})"
    # Run fresh
    import tw_chip_price
    try:
        d = tw_chip_price.analyze(code, date=date)
        if not d:
            return {}, "error: 抓不到資料 (TWSE/TPEx 都無)"
        return d, "即時抓取"
    except Exception as e:
        return {}, f"error: {type(e).__name__}: {e}"


def _fmt_zhang(shares: int) -> str:
    """股 → 張 thousands-separated. Mirrors tw_chip_price._fmt_zhang."""
    return f"{int(shares / 1000):,}"


def _esc(s) -> str:
    return html_lib.escape(str(s))


def _render_report_html(data: dict) -> str:
    """Render the analysis dict as structured HTML tables (7 sections).

    Mirrors format_report() exactly — same info, just tabular instead of <pre>.
    Adaptive bands + cells + progression are recomputed here for display.
    """
    import tw_chip_price
    ohlc = data["ohlc"]
    day_low = ohlc["low"]
    day_high = ohlc["high"]
    code = data["stock_code"]
    name = data.get("name", "")
    date = data["date"]
    fmt_date = f"{date[:4]}/{date[4:6]}/{date[6:8]}" if len(date) == 8 else date
    change_pct = ((ohlc["close"] - ohlc["open"]) / ohlc["open"] * 100
                  if ohlc["open"] > 0 else 0)
    chg_cls = "neg" if change_pct < 0 else ("pos" if change_pct > 0 else "")
    total_zhang = _fmt_zhang(data.get("total_buy_shares", 0))

    parts = [f"""
<section class="header-card">
  <h2>{_esc(code)} {_esc(name)} 籌碼價格分析 ({fmt_date})</h2>
  <div class="ohlc">
    開盤 <b>${ohlc['open']:.2f}</b> / 收盤 <b>${ohlc['close']:.2f}</b>
    / 高 ${ohlc['high']:.2f} / 低 ${ohlc['low']:.2f}
    <span class="{chg_cls}">({change_pct:+.2f}%)</span>
  </div>
  <div class="ohlc">總量 <b>{total_zhang}</b> 張</div>
</section>"""]

    # ── Section 2: Top 10 大單 cells ──────────────────────────────────────
    parts.append('<section><h2>🔥 Top 10 大單 cells (broker × price)</h2>')
    parts.append('<table class="report-table"><thead><tr>'
                  '<th>#</th><th>分點</th><th>名稱</th><th class="num">價位</th>'
                  '<th>方向</th><th class="num">張數</th><th>標記</th>'
                  '</tr></thead><tbody>')
    for i, c in enumerate(data.get("top_cells", []), 1):
        side_cls = "buy" if c["side"] == "buy" else "sell"
        side_label = "買" if c["side"] == "buy" else "賣"
        parts.append(
            f'<tr><td>{i}</td><td>{_esc(c["broker_id"])}</td>'
            f'<td>{_esc(c["broker_name"])}</td>'
            f'<td class="num">${c["price"]:.2f}</td>'
            f'<td class="{side_cls}">{side_label}</td>'
            f'<td class="num {side_cls}">{_fmt_zhang(c["volume"])}</td>'
            f'<td>{_esc(c.get("tag", ""))}</td></tr>'
        )
    parts.append('</tbody></table></section>')

    # ── Section 3: 三階段分析 ──────────────────────────────────────────────
    basis = data.get("stage_basis", "price")
    if basis == "time":
        stage_caption = "以實際成交時間切分"
        zone_labels = {
            "early": "早盤 (前 25% 時間: 09:00 ~ ~10:08)",
            "mid":   "盤中 (中 50% 時間: ~10:08 ~ ~12:22)",
            "late":  "尾盤 (後 25% 時間: ~12:22 ~ 13:30)",
        }
    else:
        stage_caption = "以價格 quartile 為時間 proxy (無 tick 資料)"
        rng = day_high - day_low
        if rng > 0:
            zone_labels = {
                "early": f"早盤 (低 25%: ${day_low:.2f} ~ ${day_low + 0.25*rng:.2f})",
                "mid":   f"盤中 (中 50%: ${day_low + 0.25*rng:.2f} ~ ${day_low + 0.75*rng:.2f})",
                "late":  f"尾盤 (高 25%: ${day_low + 0.75*rng:.2f} ~ ${day_high:.2f})",
            }
        else:
            zone_labels = {"early": "早盤", "mid": "盤中", "late": "尾盤"}
    parts.append(f'<section><h2>⏰ 三階段分析 <small>({stage_caption})</small></h2>')
    for zone_key in ("early", "mid", "late"):
        zone_rows = data.get("stage", {}).get(zone_key, [])
        buyers = [r for r in zone_rows if r["net_shares"] > 0][:3]
        sellers = [r for r in zone_rows if r["net_shares"] < 0][:3]
        parts.append(f'<h3>{_esc(zone_labels[zone_key])}</h3>')
        if not buyers and not sellers:
            parts.append('<p class="empty">(本區無大量交易)</p>')
            continue
        parts.append('<table class="report-table stage-table"><tbody>')
        if buyers:
            cells = "".join(
                f'<td><span class="buy">🟢 {_esc(r["broker_name"])}</span> '
                f'<span class="num buy">+{_fmt_zhang(r["net_shares"])}張</span></td>'
                for r in buyers
            )
            parts.append(f'<tr><th>買方主力</th>{cells}</tr>')
        if sellers:
            cells = "".join(
                f'<td><span class="sell">🔴 {_esc(r["broker_name"])}</span> '
                f'<span class="num sell">{_fmt_zhang(r["net_shares"])}張</span></td>'
                for r in sellers
            )
            parts.append(f'<tr><th>賣方主力</th>{cells}</tr>')
        parts.append('</tbody></table>')
    parts.append('</section>')

    # ── Helper for buyer/seller fingerprint sections ────────────────────
    def _fingerprint_table(brokers: list[dict], side: str) -> str:
        rows = []
        sign = "+" if side == "buy" else "-"
        side_cls = "buy" if side == "buy" else "sell"
        for b in brokers:
            cells = b.get("cells", [])
            band = tw_chip_price.adaptive_concentration_band(
                cells, side=side, day_low=day_low, day_high=day_high,
                max_band_pct=0.25,
            )
            top3 = tw_chip_price.broker_top_cells(cells, side=side, n=3)
            pr_lo, pr_hi = b.get("price_range", (0, 0))
            band_html = "—"
            if band:
                band_html = (
                    f'${band["core_low"]:.2f}~${band["core_high"]:.2f}<br>'
                    f'<span class="{side_cls}">{sign}{_fmt_zhang(band["core_volume"])}</span>'
                    f' 張 ({band["core_pct"]*100:.0f}%)'
                )
            top3_html = "—"
            if top3:
                top3_html = " / ".join(
                    f'${c["price"]:.2f} <span class="{side_cls}">'
                    f'{sign}{_fmt_zhang(c[side])}</span>'
                    for c in top3
                )
            # Band progression
            progression = tw_chip_price.broker_band_progression(
                code, b["broker_id"], side=side, n_days=5,
            )
            today = data.get("date", "")
            past = [p for p in progression if p["date"] != today]
            prog_html = "—"
            if past:
                arrow_parts = []
                for p in past:
                    arrow_parts.append(
                        f'{p["date"][4:6]}/{p["date"][6:8]} '
                        f'${p["low"]:.2f}~${p["high"]:.2f}'
                    )
                if band:
                    arrow_parts.append(
                        f'{today[4:6]}/{today[6:8]} '
                        f'${band["core_low"]:.2f}~${band["core_high"]:.2f} (今)'
                    )
                lows = [p["low"] for p in past]
                if band:
                    lows.append(band["core_low"])
                trend = ("📈 推升中" if lows[-1] > lows[0]
                         else ("📉 下移" if lows[-1] < lows[0] else "➡ 盤整"))
                prog_html = f'<b>{trend}</b><br>' + ' → '.join(arrow_parts)
            net = b["net_shares"]
            net_html = (f'<span class="buy">+{_fmt_zhang(net)}</span>'
                        if net > 0
                        else f'<span class="sell">{_fmt_zhang(net)}</span>')
            rows.append(
                f'<tr>'
                f'<td>{_esc(b["broker_id"])}<br>{_esc(b["broker_name"])}</td>'
                f'<td class="num">{net_html} 張</td>'
                f'<td class="num">${b.get("avg_price", 0):.2f}</td>'
                f'<td class="num">${pr_lo:.2f}<br>~${pr_hi:.2f}</td>'
                f'<td>{band_html}</td>'
                f'<td class="num">{top3_html}</td>'
                f'<td class="small">{prog_html}</td>'
                f'</tr>'
            )
        if not rows:
            return '<p class="empty">(無)</p>'
        return (
            '<table class="report-table fp-table"><thead><tr>'
            '<th>分點</th><th class="num">淨</th><th class="num">avg</th>'
            '<th class="num">範圍</th><th>主買/賣集中區</th>'
            '<th class="num">Top 3 價位</th><th>📈 跨日軌跡</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
        )

    parts.append('<section><h2>🎯 Top 5 買超分點價格指紋</h2>')
    parts.append(_fingerprint_table(
        data.get("fingerprint", {}).get("top_buyers", []), "buy"))
    parts.append('</section>')

    parts.append('<section><h2>🎯 Top 5 賣超分點價格指紋</h2>')
    parts.append(_fingerprint_table(
        data.get("fingerprint", {}).get("top_sellers", []), "sell"))
    parts.append('</section>')

    # ── Section 6: 🌀 高賣低買 ────────────────────────────────────────────
    wash = data.get("wash_candidates", [])
    if wash:
        parts.append('<section><h2>🌀 高賣低買 — 同分點兩面操作 '
                      '(洗盤低接型態)</h2>')
        parts.append('<table class="report-table wash-table"><thead><tr>'
                      '<th>分點</th><th>賣</th><th>買</th>'
                      '<th class="num">高賣低買差</th><th class="num">淨</th>'
                      '<th>判定</th></tr></thead><tbody>')
        rng = max(day_high - day_low, 0.01)
        def _wash_side_detail(cells: list, side: str) -> str:
            """Render concentration band + Top 3 prices for one side of a
            wash candidate, matching _fingerprint_table layout."""
            if not cells:
                return ""
            sign = "+" if side == "buy" else "-"
            side_cls = "buy" if side == "buy" else "sell"
            band = tw_chip_price.adaptive_concentration_band(
                cells, side=side, day_low=day_low, day_high=day_high,
                max_band_pct=0.25,
            )
            top3 = tw_chip_price.broker_top_cells(cells, side=side, n=3)
            out = ""
            if band:
                out += (
                    f'<br><small>🎯 ${band["core_low"]:.2f}~${band["core_high"]:.2f} '
                    f'<span class="{side_cls}">{sign}{_fmt_zhang(band["core_volume"])}</span>'
                    f'張 ({band["core_pct"]*100:.0f}%)</small>'
                )
            if top3:
                top3_str = " / ".join(
                    f'${c["price"]:.2f} <span class="{side_cls}">'
                    f'{sign}{_fmt_zhang(c[side])}</span>'
                    for c in top3
                )
                out += f'<br><small>Top: {top3_str}</small>'
            return out

        for w in wash:
            net = w["net_shares"]
            net_html = (f'<span class="buy">+{_fmt_zhang(net)}</span>'
                        if net >= 0
                        else f'<span class="sell">{_fmt_zhang(net)}</span>')
            sell_t = w.get("sell_time_min")
            buy_t = w.get("buy_time_min")
            cells_w = w.get("cells", [])
            sell_str = (f'{_fmt_zhang(w["sell_shares"])}張 @${w["sell_avg"]:.2f}'
                        + (f'<br><small>~{tw_chip_price._minutes_to_hhmm(sell_t)}</small>'
                           if sell_t is not None else "")
                        + _wash_side_detail(cells_w, "sell"))
            buy_str = (f'{_fmt_zhang(w["buy_shares"])}張 @${w["buy_avg"]:.2f}'
                       + (f'<br><small>~{tw_chip_price._minutes_to_hhmm(buy_t)}</small>'
                          if buy_t is not None else "")
                       + _wash_side_detail(cells_w, "buy"))
            pct = w["price_gap"] / rng * 100
            pat = w.get("time_pattern", "")
            if pat == "真洗盤低接":
                verdict = '<span class="ok">✅ 真洗盤低接</span><br><small>先賣高、後買低</small>'
            elif pat == "追漲獲利出":
                verdict = '<span class="warn">⚠ 追漲獲利出</span><br><small>先買低、後賣高</small>'
            elif pat == "時序模糊":
                verdict = '<span class="muted">⏱ 時序模糊</span><br><small>買賣時間相近</small>'
            else:
                verdict = ('看似空、實際多<br><small>(淨賣但低接更多籌碼)</small>'
                           if net < 0
                           else '同分點兩面操作<br><small>(確實淨買)</small>')
            parts.append(
                f'<tr><td>{_esc(w["broker_id"])}<br>{_esc(w["broker_name"])}</td>'
                f'<td class="sell">{sell_str}</td>'
                f'<td class="buy">{buy_str}</td>'
                f'<td class="num">+${w["price_gap"]:.2f}<br><small>({pct:.0f}% 全日)</small></td>'
                f'<td class="num">{net_html} 張</td>'
                f'<td>{verdict}</td></tr>'
            )
        parts.append('</tbody></table></section>')

    # ── Section 7: 連續性 ────────────────────────────────────────────────
    continuity_lines = tw_chip_price._format_continuity(data, days=5)
    if continuity_lines:
        # The first line is "【📅 近 N 日連續性 ...】"; the next ones are the
        # buyer / seller match lines. Render as a small table.
        parts.append('<section><h2>📅 連續性</h2>')
        n_history = len([line for line in continuity_lines
                          if "Top 3" in line])
        # Simpler: just dump as <pre>
        joined = "\n".join(continuity_lines)
        parts.append(f'<pre class="continuity">{_esc(joined)}</pre>')
        parts.append('</section>')

    return "".join(parts)


def _load_raw_bsr(code: str, date: str) -> list[dict]:
    """Load the raw bsr_cache/{code}_{date}_prices.json (full per-(broker,
    price) rows). Returns [] if missing."""
    fp = os.path.join(REPO, "bsr_cache", f"{code}_{date}_prices.json")
    if not os.path.exists(fp):
        return []
    try:
        with open(fp) as f:
            d = json.load(f)
        return d.get("rows", [])
    except Exception:
        return []


def _render_broker_drilldown(code: str, date: str, broker_query: str,
                             ohlc: dict) -> str:
    """Render a deep-dive section for one or more brokers matching
    `broker_query` on stock `code` for `date`.

    Match logic:
      - exact broker_id (e.g. '5381')
      - substring in broker_name (e.g. '員林' matches all branches with 員林)
    """
    import tw_chip_price
    rows = _load_raw_bsr(code, date)
    if not rows:
        return (f'<section><h2>🔍 分點 "{_esc(broker_query)}" 深度</h2>'
                f'<div class="empty">找不到 bsr_cache/{code}_{date}_prices.json，'
                f'可能未 backfill。先按「即時抓取」會立刻 cache。</div></section>')

    # Match brokers
    q = broker_query.strip()
    matched_ids: dict[str, dict] = {}
    for r in rows:
        if (r["broker_id"] == q
                or q.lower() == r["broker_id"].lower()
                or q in r["broker_name"]):
            bid = r["broker_id"]
            matched_ids.setdefault(bid, {
                "broker_id": bid,
                "broker_name": r["broker_name"],
                "cells": [],
            })
            matched_ids[bid]["cells"].append({
                "price": r["price"],
                "buy": r["buy"],
                "sell": r["sell"],
            })
    if not matched_ids:
        return (f'<section><h2>🔍 分點 "{_esc(broker_query)}" 深度</h2>'
                f'<div class="empty">找不到符合的分點。試「代號」(5381) 或「分行名稱」'
                f'(員林、台南、信義 …)</div></section>')

    # Build price→time map (weighted-avg per price) + tick index (raw ticks
    # per price). The map is used for cells without leading-block matches;
    # the index drives per-cell exact matching via match_broker_cells_consistent.
    ptm = tw_chip_price.build_price_to_time_map(code, date)
    tick_idx = tw_chip_price.build_tick_index(code, date)
    day_low = ohlc.get("low", 0)
    day_high = ohlc.get("high", 0)
    rng = max(day_high - day_low, 0.01)

    parts = [f'<section><h2>🔍 分點 "{_esc(broker_query)}" 深度 '
              f'({len(matched_ids)} 個分點符合)</h2>']

    # Group-level summary table if multiple branches matched
    if len(matched_ids) > 1:
        grouped_buy = sum(sum(c["buy"] for c in b["cells"])
                          for b in matched_ids.values())
        grouped_sell = sum(sum(c["sell"] for c in b["cells"])
                           for b in matched_ids.values())
        grouped_net = grouped_buy - grouped_sell
        net_cls = "buy" if grouped_net > 0 else "sell"
        parts.append('<h3>群組合計</h3>')
        parts.append(
            f'<p>共 {len(matched_ids)} 個分點，合計買 '
            f'<span class="buy">+{_fmt_zhang(grouped_buy)}張</span> / 賣 '
            f'<span class="sell">-{_fmt_zhang(grouped_sell)}張</span> / '
            f'淨 <span class="{net_cls}">{"+" if grouped_net >= 0 else ""}'
            f'{_fmt_zhang(grouped_net)}張</span></p>'
        )

    # Sort matched brokers by absolute net descending so big players first
    sorted_brokers = sorted(
        matched_ids.values(),
        key=lambda b: -abs(sum(c["buy"] - c["sell"] for c in b["cells"])),
    )

    for b in sorted_brokers:
        cells = b["cells"]
        total_buy = sum(c["buy"] for c in cells)
        total_sell = sum(c["sell"] for c in cells)
        net = total_buy - total_sell
        buy_value = sum(c["price"] * c["buy"] for c in cells)
        sell_value = sum(c["price"] * c["sell"] for c in cells)
        buy_avg = buy_value / total_buy if total_buy else 0
        sell_avg = sell_value / total_sell if total_sell else 0
        net_cls = "buy" if net > 0 else "sell"

        # Adaptive bands
        buy_band = tw_chip_price.adaptive_concentration_band(
            cells, side="buy", day_low=day_low, day_high=day_high,
            max_band_pct=0.25,
        )
        sell_band = tw_chip_price.adaptive_concentration_band(
            cells, side="sell", day_low=day_low, day_high=day_high,
            max_band_pct=0.25,
        )

        # Per-cell time matching via cross-cell consistency (tick-level
        # leading-block detection). Cells need vol in 張 to match tick units;
        # raw BSR is in 股, so we divide by 1000 first.
        cells_zhang = [
            {"price": c["price"], "buy": c["buy"] // 1000,
             "sell": c["sell"] // 1000}
            for c in cells
        ]
        buy_matches = (tw_chip_price.match_broker_cells_consistent(
            cells_zhang, "buy", tick_idx) if tick_idx else {})
        sell_matches = (tw_chip_price.match_broker_cells_consistent(
            cells_zhang, "sell", tick_idx) if tick_idx else {})

        # Overall buy/sell time (volume-weighted over matched cells)
        def _overall_time(matches, cells, side):
            total_w, total_v = 0.0, 0
            for c in cells:
                v = c[side] // 1000
                if v == 0:
                    continue
                m = matches.get(c["price"])
                if not m:
                    continue
                total_w += m["time_min"] * v
                total_v += v
            return total_w / total_v if total_v > 0 else None
        buy_t = _overall_time(buy_matches, cells, "buy")
        sell_t = _overall_time(sell_matches, cells, "sell")
        # Fall back to old weighted-avg if no tick matches
        if buy_t is None and total_buy > 0 and ptm:
            buy_t = tw_chip_price.broker_time_estimate(cells, "buy", ptm)
        if sell_t is None and total_sell > 0 and ptm:
            sell_t = tw_chip_price.broker_time_estimate(cells, "sell", ptm)

        # Wash score if both sides have activity
        wash_html = ""
        if total_buy > 0 and total_sell > 0:
            wash_score = (sell_avg - buy_avg) / rng
            time_pattern = ""
            if buy_t is not None and sell_t is not None:
                if buy_t - sell_t >= 30:
                    time_pattern = "✅ 真洗盤低接 (先賣後買)"
                elif sell_t - buy_t >= 30:
                    time_pattern = "⚠ 追漲獲利出 (先買後賣)"
                else:
                    time_pattern = "⏱ 時序模糊"
            sign = "+" if wash_score >= 0 else ""
            wash_html = (
                f'<p><b>🌀 高賣低買:</b> sell_avg ${sell_avg:.2f} − '
                f'buy_avg ${buy_avg:.2f} = '
                f'<b>{sign}${sell_avg - buy_avg:.2f}</b> '
                f'(wash_score {wash_score:+.2f}); {time_pattern}</p>'
            )

        # Per-cell breakdown table
        cell_rows = []
        # Show all cells, sorted by total volume desc
        sorted_cells = sorted(cells, key=lambda c: -(c["buy"] + c["sell"]))
        for c in sorted_cells:
            buy_match = buy_matches.get(c["price"]) if c["buy"] > 0 else None
            sell_match = sell_matches.get(c["price"]) if c["sell"] > 0 else None
            primary_match = buy_match or sell_match
            if primary_match:
                t_str = tw_chip_price._minutes_to_hhmm(primary_match["time_min"])
                mt = primary_match["match_type"]
                confidence = {
                    "exact": "✅",
                    "exact_ambiguous": "≈",
                    "leading_block": "🎯",
                    "leading_block_consistent": "🎯+",
                    "window": "🔄",
                    "weighted": "≈",
                }.get(mt, "?")
                # Build alternative-candidates suffix
                alts = primary_match.get("alternatives") or []
                alt_html = ""
                if alts:
                    alt_parts = [
                        f"~{tw_chip_price._minutes_to_hhmm(a['time_min'])} "
                        f"(lead {a['lead_vol']}張)"
                        for a in alts
                    ]
                    alt_html = (f'<br><small class="muted">OR '
                                + " / ".join(alt_parts) + '</small>')
                # Scattered flag
                if primary_match.get("is_scattered"):
                    alt_html += ('<br><small class="warn">⚠ scattered: '
                                  '無 dominant tick，多筆小單估算誤差大</small>')
                t_html = f'~{t_str} <small>{confidence}</small>{alt_html}'
            else:
                t = ptm.get(c["price"]) if ptm else None
                t_str = tw_chip_price._minutes_to_hhmm(t) if t is not None else "?"
                t_html = f'~{t_str} <small>≈</small>'
            buy_html = (f'<span class="buy">+{_fmt_zhang(c["buy"])}</span>'
                        if c["buy"] > 0 else "")
            sell_html = (f'<span class="sell">-{_fmt_zhang(c["sell"])}</span>'
                         if c["sell"] > 0 else "")
            cell_rows.append(
                f'<tr><td class="num">${c["price"]:.2f}</td>'
                f'<td class="num">{buy_html}</td>'
                f'<td class="num">{sell_html}</td>'
                f'<td class="num small">{t_html}</td></tr>'
            )

        # Band progression (cross-day)
        prog_html = ""
        if net != 0:
            side = "buy" if net > 0 else "sell"
            progression = tw_chip_price.broker_band_progression(
                code, b["broker_id"], side=side, n_days=5,
            )
            past = [p for p in progression if p["date"] != date]
            band_today = buy_band if side == "buy" else sell_band
            if past or band_today:
                arrows = []
                for p in past:
                    arrows.append(
                        f'{p["date"][4:6]}/{p["date"][6:8]} '
                        f'${p["low"]:.2f}~${p["high"]:.2f}'
                    )
                if band_today:
                    arrows.append(
                        f'{date[4:6]}/{date[6:8]} '
                        f'${band_today["core_low"]:.2f}~'
                        f'${band_today["core_high"]:.2f} (今)'
                    )
                if len(arrows) >= 2:
                    lows = [p["low"] for p in past]
                    if band_today:
                        lows.append(band_today["core_low"])
                    trend = ("📈 推升中" if lows[-1] > lows[0]
                             else ("📉 下移" if lows[-1] < lows[0] else "➡ 盤整"))
                    prog_html = (f'<p class="small"><b>跨日軌跡 ({trend}):</b> '
                                 + ' → '.join(arrows) + '</p>')

        # Render
        parts.append(f'<h3>{_esc(b["broker_id"])} {_esc(b["broker_name"])}</h3>')
        parts.append(
            f'<p>淨 <span class="{net_cls}">{"+" if net >= 0 else ""}'
            f'{_fmt_zhang(net)}張</span> '
            f'(買 <span class="buy">+{_fmt_zhang(total_buy)}張</span> avg '
            f'${buy_avg:.2f}'
        )
        if buy_t is not None:
            parts.append(f' ~{tw_chip_price._minutes_to_hhmm(buy_t)}')
        parts.append(
            f' / 賣 <span class="sell">-{_fmt_zhang(total_sell)}張</span> avg '
            f'${sell_avg:.2f}'
        )
        if sell_t is not None:
            parts.append(f' ~{tw_chip_price._minutes_to_hhmm(sell_t)}')
        parts.append(')</p>')

        if buy_band and total_buy > 0:
            parts.append(
                f'<p><b>🎯 主買集中區:</b> ${buy_band["core_low"]:.2f}~'
                f'${buy_band["core_high"]:.2f} '
                f'(<span class="buy">+{_fmt_zhang(buy_band["core_volume"])}</span> 張, '
                f'{buy_band["core_pct"]*100:.0f}% of buy)</p>'
            )
        if sell_band and total_sell > 0:
            parts.append(
                f'<p><b>🎯 主賣集中區:</b> ${sell_band["core_low"]:.2f}~'
                f'${sell_band["core_high"]:.2f} '
                f'(<span class="sell">-{_fmt_zhang(sell_band["core_volume"])}</span> 張, '
                f'{sell_band["core_pct"]*100:.0f}% of sell)</p>'
            )

        if wash_html:
            parts.append(wash_html)
        if prog_html:
            parts.append(prog_html)

        # Per-cell table
        parts.append(
            '<table class="report-table"><thead><tr>'
            '<th class="num">價位</th><th class="num">買 (張)</th>'
            '<th class="num">賣 (張)</th><th class="num">~估算時間</th>'
            '</tr></thead><tbody>'
            + "".join(cell_rows) + '</tbody></table>'
        )

    parts.append('</section>')
    return "".join(parts)


def _render_chip_price_page(code: str | None = None,
                            data: dict | None = None,
                            source: str = "",
                            error: str = "",
                            broker_query: str = "",
                            broker_html: str = "") -> str:
    """Render the chip-price form + optional result."""
    recent = _list_cached_history()[:30]
    recent_links = " &middot; ".join(
        f'<a href="/chip-price?code={c}&date={d}">{c} {d[4:6]}/{d[6:8]}</a>'
        for c, d in recent
    ) or "<em>(尚無快取)</em>"
    report_block = ""
    if data:
        report_block = _render_report_html(data)
    if error:
        report_block = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    code_attr = html_lib.escape(code or "")
    broker_attr = html_lib.escape(broker_query or "")
    source_block = (f'<div class="source">資料來源：{html_lib.escape(source)}</div>'
                    if source else "")
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chip-Price 籌碼價量分析</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei",
           sans-serif; max-width: 1100px; margin: 1em auto; padding: 0 1em;
           background: #f7f7f9; color: #222; }}
  h1 {{ font-size: 1.4em; margin: 0.5em 0; }}
  form {{ display: flex; gap: 8px; align-items: center;
          background: white; padding: 12px; border-radius: 6px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 12px; }}
  input[type=text] {{ font-size: 16px; padding: 8px 12px; width: 120px;
                       border: 1px solid #ccc; border-radius: 4px; }}
  button {{ font-size: 16px; padding: 8px 16px; cursor: pointer;
            background: #0066cc; color: white; border: none;
            border-radius: 4px; }}
  button:hover {{ background: #0052a3; }}
  button.secondary {{ background: #888; }}
  .recent {{ background: white; padding: 12px; border-radius: 6px;
             margin-bottom: 12px; font-size: 0.85em; line-height: 1.6;
             box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .recent a {{ color: #0066cc; text-decoration: none; white-space: nowrap; }}
  .recent a:hover {{ text-decoration: underline; }}
  .source {{ font-size: 0.85em; color: #666; margin-bottom: 6px; }}
  .error {{ background: #fee; border: 1px solid #f99; padding: 12px;
            border-radius: 4px; color: #c00; }}
  pre.report, pre.continuity {{ background: white; padding: 12px;
                 border-radius: 6px; font-size: 0.85em; line-height: 1.5;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.06);
                 overflow-x: auto; white-space: pre-wrap;
                 font-family: "SF Mono", "Menlo", "Consolas", monospace; }}
  nav a {{ margin-right: 12px; color: #0066cc; text-decoration: none; }}
  section {{ background: white; padding: 12px 16px; border-radius: 6px;
              margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  section.header-card h2 {{ margin: 0 0 6px 0; font-size: 1.3em; }}
  section h2 {{ font-size: 1.05em; margin: 4px 0 8px 0;
                color: #333; border-bottom: 1px solid #eee; padding-bottom: 4px; }}
  section h2 small {{ font-weight: normal; color: #888; font-size: 0.85em; }}
  section h3 {{ font-size: 0.95em; margin: 12px 0 6px 0; color: #555; }}
  .ohlc {{ font-size: 0.95em; color: #444; margin: 2px 0; }}
  .ohlc b {{ color: #000; }}
  table.report-table {{ width: 100%; border-collapse: collapse;
                         font-size: 0.85em; }}
  table.report-table th, table.report-table td {{ padding: 5px 8px;
                                                    border-bottom: 1px solid #eee;
                                                    text-align: left;
                                                    vertical-align: top; }}
  table.report-table th {{ background: #fafafa; font-weight: 600;
                            color: #555; font-size: 0.9em; }}
  table.report-table .num {{ text-align: right;
                              font-variant-numeric: tabular-nums; }}
  .buy {{ color: #c30; font-weight: 500; }}
  .sell {{ color: #060; font-weight: 500; }}
  .pos {{ color: #c30; }}
  .neg {{ color: #060; }}
  .ok {{ color: #060; font-weight: 600; }}
  .warn {{ color: #c80; font-weight: 600; }}
  .muted {{ color: #888; }}
  .empty {{ color: #999; font-style: italic; padding: 8px; }}
  .small, small {{ font-size: 0.85em; color: #666; }}
  table.stage-table th {{ background: transparent; width: 100px;
                            color: #555; font-weight: normal; }}
  table.fp-table td {{ font-size: 0.9em; }}
  table.fp-table {{ table-layout: auto; }}
  table.wash-table td {{ font-size: 0.9em; }}
  @media (max-width: 768px) {{
    body {{ padding: 0 4px; margin: 0.5em auto; }}
    section {{ overflow-x: auto; }}
    table.report-table {{ font-size: 0.78em; }}
    table.report-table th, table.report-table td {{ padding: 4px 5px; }}
  }}
</style>
</head>
<body>
<nav><a href="/">← 大盤 dashboard</a> <a href="/chip-price">籌碼價量分析</a></nav>
<h1>📊 籌碼價量分析 (broker × price × time)</h1>

<form method="get" action="/chip-price">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 2313" autofocus required>
  <label for="broker">分點 (選填):</label>
  <input type="text" id="broker" name="broker" value="{broker_attr}"
         placeholder="例: 5381 或 員林" style="width:160px;">
  <button type="submit">查詢 (用快取)</button>
  <button type="submit" name="fresh" value="1" class="secondary">即時抓取 (5-15秒)</button>
</form>
<p class="small">💡 分點欄可輸入代號 (e.g. <code>5381</code>)、分行名稱 (e.g. <code>員林</code> = 所有 *員林 分行) 或銀行系名 (e.g. <code>第一</code> = 第一銀全系)</p>

<div class="recent">📂 近期快取 (點擊直接看)：{recent_links}</div>

{source_block}
{report_block}
{broker_html}
</body>
</html>"""


def _render_contract_liabilities_page(code: str = "", years: int = 3,
                                      rows: list[dict] | None = None,
                                      name: str = "",
                                      error: str = "") -> str:
    """Web page: 合約負債 history for a stock."""
    code_attr = html_lib.escape(code or "")
    body = ""
    if error:
        body = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif rows is not None and not rows:
        code_esc = html_lib.escape(code)
        body = (
            '<div class="empty">'
            f'<p><b>⚠ {code_esc} {html_lib.escape(name)} 沒有「合約負債」獨立科目資料</b></p>'
            '<p>原因：該公司 XBRL 申報時未把 <code>CurrentContractLiabilities</code> '
            '拆出，多半合併在「其他流動負債 (OtherCurrentLiabilities)」內。</p>'
            '<p>常見不揭露的類型：</p>'
            '<ul>'
            '<li>純代工製造業 (e.g., 2330 台積電 / 2317 鴻海) — PO 即收款，無實質預收</li>'
            '<li>部分 ODM (e.g., 6282 康舒) — 客戶用 PO 制不付訂金</li>'
            '<li>反例同業有揭露：'
            '<a href="/contract-liabilities?code=2308">2308 台達電</a> · '
            '<a href="/contract-liabilities?code=2301">2301 光寶科</a> · '
            '<a href="/contract-liabilities?code=6669">6669 緯穎</a> · '
            '<a href="/contract-liabilities?code=2454">2454 聯發科</a></li>'
            '</ul>'
            '<p><b>建議</b>：去 <a href="https://mops.twse.com.tw/" target="_blank">'
            '公開資訊觀測站 (MOPS)</a> 看該公司財報附註細目，'
            '或改用該集團母公司/同業作 proxy '
            '(e.g., 6282 → 看 2301 光寶科 或 2308 台達電)。</p>'
            '</div>'
        )
    elif rows:
        rows_html = []
        for r in rows:
            cur = r["current"]
            non = r["noncurrent"]
            tot = r["total"]
            qoq = r.get("qoq_pct")
            yoy = r.get("yoy_pct")
            qoq_cls = ("pos" if qoq is not None and qoq > 0
                       else ("neg" if qoq is not None and qoq < 0 else ""))
            yoy_cls = ("pos" if yoy is not None and yoy > 0
                       else ("neg" if yoy is not None and yoy < 0 else ""))
            qoq_str = (f"{'+' if qoq >= 0 else ''}{qoq:.1f}%"
                       if qoq is not None else "—")
            yoy_str = (f"{'+' if yoy >= 0 else ''}{yoy:.1f}%"
                       if yoy is not None else "—")
            non_str = f"{non / 1000:,.0f}" if non > 0 else "—"
            rows_html.append(
                f'<tr>'
                f'<td>{r["date"]}</td>'
                f'<td class="num">{cur / 1000:,.0f}</td>'
                f'<td class="num">{non_str}</td>'
                f'<td class="num"><b>{tot / 1000:,.0f}</b></td>'
                f'<td class="num {qoq_cls}">{qoq_str}</td>'
                f'<td class="num {yoy_cls}">{yoy_str}</td>'
                f'</tr>'
            )
        # CAGR
        cagr_str = ""
        if len(rows) >= 2 and rows[0]["total"] > 0:
            span_years = (
                (datetime.strptime(rows[-1]["date"], "%Y-%m-%d")
                 - datetime.strptime(rows[0]["date"], "%Y-%m-%d")).days
                / 365.25
            )
            if span_years > 0:
                cagr = ((rows[-1]["total"] / rows[0]["total"])
                        ** (1 / span_years) - 1) * 100
                cagr_cls = "pos" if cagr > 0 else "neg"
                cagr_str = (f'<p>📈 期間 CAGR: <span class="{cagr_cls}">'
                             f'<b>{cagr:+.1f}%</b></span> '
                             f'({rows[0]["date"]} → {rows[-1]["date"]})</p>')
        body = f"""
<section class="header-card">
  <h2>{_esc(code)} {_esc(name)} 合約負債 (近 {years} 年 / {len(rows)} 季)</h2>
  {cagr_str}
</section>
<section>
  <table class="report-table">
    <thead><tr>
      <th>季底</th>
      <th class="num">流動合約負債 (千元)</th>
      <th class="num">非流動 (千元)</th>
      <th class="num">合計 (千元)</th>
      <th class="num">QoQ%</th>
      <th class="num">YoY%</th>
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  <p class="small">註：合約負債 ↑ = 客戶預訂款增加 (未來營收能見度提升) /
     ↓ = 已轉認列為營收或新預訂下降</p>
</section>"""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>合約負債 — 台股單檔歷史</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei",
           sans-serif; max-width: 1100px; margin: 1em auto; padding: 0 1em;
           background: #f7f7f9; color: #222; }}
  h1 {{ font-size: 1.4em; margin: 0.5em 0; }}
  form {{ display: flex; gap: 8px; align-items: center;
          background: white; padding: 12px; border-radius: 6px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 12px; }}
  input[type=text], input[type=number] {{ font-size: 16px; padding: 8px 12px;
                       border: 1px solid #ccc; border-radius: 4px; }}
  input[type=text] {{ width: 120px; }}
  input[type=number] {{ width: 60px; }}
  button {{ font-size: 16px; padding: 8px 16px; cursor: pointer;
            background: #0066cc; color: white; border: none;
            border-radius: 4px; }}
  button:hover {{ background: #0052a3; }}
  nav a {{ margin-right: 12px; color: #0066cc; text-decoration: none; }}
  .error {{ background: #fee; border: 1px solid #f99; padding: 12px;
            border-radius: 4px; color: #c00; margin-bottom: 12px; }}
  .empty {{ background: white; padding: 16px; border-radius: 6px;
            color: #666; box-shadow: 0 1px 3px rgba(0,0,0,0.06);
            margin-bottom: 12px; }}
  section {{ background: white; padding: 12px 16px; border-radius: 6px;
              margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  section.header-card h2 {{ margin: 0 0 6px 0; font-size: 1.3em; }}
  table.report-table {{ width: 100%; border-collapse: collapse;
                         font-size: 0.9em; }}
  table.report-table th, table.report-table td {{ padding: 6px 10px;
                                                    border-bottom: 1px solid #eee;
                                                    text-align: left; }}
  table.report-table th {{ background: #fafafa; font-weight: 600;
                            color: #555; font-size: 0.9em; }}
  table.report-table .num {{ text-align: right;
                              font-variant-numeric: tabular-nums; }}
  .pos {{ color: #c30; }}
  .neg {{ color: #060; }}
  .small, small {{ font-size: 0.85em; color: #666; }}
  @media (max-width: 768px) {{
    body {{ padding: 0 4px; margin: 0.5em auto; }}
    section {{ overflow-x: auto; }}
    table.report-table {{ font-size: 0.78em; }}
    table.report-table th, table.report-table td {{ padding: 4px 5px; }}
  }}
</style>
</head>
<body>
<nav>
  <a href="/">← 大盤 dashboard</a>
  <a href="/chip-price">📋 籌碼價量</a>
  <a href="/contract-liabilities">💰 合約負債</a>
</nav>
<h1>💰 合約負債歷史</h1>

<form method="get" action="/contract-liabilities">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 6669" autofocus required>
  <label for="years">回看年數:</label>
  <input type="number" id="years" name="years" value="{years}" min="1" max="10">
  <button type="submit">查詢</button>
</form>
<p class="small">💡 合約負債 = 客戶預收款 / 訂金。
   ↑ = 未來營收能見度提升；↓ = 訂單已轉認列。常用於 ODM/工程/SaaS 業
   (e.g. <a href="/contract-liabilities?code=6669">6669 緯穎</a> ·
   <a href="/contract-liabilities?code=2454">2454 聯發科</a> ·
   <a href="/contract-liabilities?code=1101">1101 台泥</a>)</p>

{body}
</body>
</html>"""


@app.route("/contract-liabilities")
def contract_liabilities():
    import tw_contract_liabilities
    code = (request.args.get("code") or "").strip()
    try:
        years = int(request.args.get("years") or "3")
        years = max(1, min(years, 10))
    except ValueError:
        years = 3
    if not code:
        return _render_contract_liabilities_page()
    try:
        rows = tw_contract_liabilities.fetch_contract_liabilities(
            code, years=years)
        rows = tw_contract_liabilities.annotate_changes(rows)
    except Exception as e:
        return _render_contract_liabilities_page(
            code=code, years=years, error=f"{type(e).__name__}: {e}")
    name = tw_contract_liabilities._zh_name(code)
    return _render_contract_liabilities_page(code=code, years=years,
                                              rows=rows, name=name)


@app.route("/chip-price")
def chip_price():
    code = (request.args.get("code") or "").strip()
    date = (request.args.get("date") or "").strip() or None
    broker_query = (request.args.get("broker") or "").strip()
    force_fetch = request.args.get("fresh") == "1"
    if not code:
        return _render_chip_price_page()
    data, source = _load_or_run(code, date=date, force_fetch=force_fetch)
    if source.startswith("error:"):
        return _render_chip_price_page(code=code, error=source[7:].strip(),
                                        broker_query=broker_query)
    broker_html = ""
    if broker_query and data:
        broker_html = _render_broker_drilldown(
            code, data.get("date", date or ""), broker_query,
            ohlc=data.get("ohlc", {}),
        )
    return _render_chip_price_page(code=code, data=data, source=source,
                                    broker_query=broker_query,
                                    broker_html=broker_html)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"Dashboard: http://localhost:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False)
