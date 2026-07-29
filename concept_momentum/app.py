#!/usr/bin/env python3
"""
Flask web server for concept momentum dashboard.
Serves the generated HTML at http://localhost:5000/
Also serves /chip-price form + on-demand analysis for any stock.
"""

import glob
import html as html_lib
import json
import math
import os
import sys
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory, send_file

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

    # ── Section 6: 🌀 同分點兩面操作 — 高賣低買 OR 低賣高買 ────────────────
    wash = data.get("wash_candidates", [])
    # Defensive runtime filter (commit d1fab38 + 2026-05-20 v2 強化):
    # (a) max side ≥ 1% × day vol  (filter noise micro-trades)
    # (b) min side ≥ 1% × day vol  (filter lopsided e.g. 214 買 / 1 賣)
    # (c) min/max ratio ≥ 10%  (genuine two-sided activity, not one-side dominant)
    day_total_vol = data.get("total_buy_shares", 0)
    if wash and day_total_vol > 0:
        vol_thresh = day_total_vol * 0.01
        def _is_genuine_wash(w):
            b = w.get("buy_shares", 0)
            s = w.get("sell_shares", 0)
            if max(b, s) < vol_thresh:
                return False
            if min(b, s) < vol_thresh:
                return False  # lopsided: one side too small relative to day
            ratio = min(b, s) / max(b, s) if max(b, s) > 0 else 0
            return ratio >= 0.10
        wash = [w for w in wash if _is_genuine_wash(w)]
    if wash:
        parts.append('<section><h2>🌀 同分點兩面操作 '
                      '(高賣低買 / 低賣高買 型態)</h2>')
        parts.append('<table class="report-table wash-table"><thead><tr>'
                      '<th>分點</th><th>類型</th><th>賣</th><th>買</th>'
                      '<th class="num">買賣價差</th><th class="num">淨</th>'
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
            gap = w["price_gap"]
            pct = abs(gap) / rng * 100
            pat = w.get("time_pattern", "")
            wash_type = w.get("wash_type",
                              "高賣低買" if gap > 0 else "低賣高買")
            if pat == "真洗盤低接":
                verdict = '<span class="ok">✅ 真洗盤低接</span><br><small>先賣高、後買低 (主力低接)</small>'
            elif pat == "追漲獲利出":
                verdict = '<span class="warn">⚠ 追漲獲利出</span><br><small>先買低、後賣高 (短線獲利)</small>'
            elif pat == "認錯買回":
                verdict = '<span class="warn">⚠ 認錯買回</span><br><small>先賣低、後追高 (認賠補回或翻多)</small>'
            elif pat == "殺低出貨":
                verdict = '<span class="warn" style="color:#c30">❌ 殺低出貨</span><br><small>先買高、後殺低 (恐慌賣)</small>'
            elif pat == "時序模糊":
                verdict = '<span class="muted">⏱ 時序模糊</span><br><small>買賣時間相近</small>'
            elif wash_type == "高賣低買":
                verdict = ('看似空、實際多<br><small>(淨賣但低接累積)</small>'
                           if net < 0
                           else '高賣低買<br><small>(同分點兩面，淨買)</small>')
            else:  # 低賣高買
                verdict = ('低賣高買<br><small>(賣低後追高 — 認錯買回)</small>'
                           if net > 0
                           else '低賣高買<br><small>(淨賣，殺低出貨)</small>')
            type_cls = "buy" if wash_type == "高賣低買" else "warn"
            type_color = "#c30" if wash_type == "低賣高買" else "#0a7e0a"
            gap_sign = "+" if gap > 0 else ""
            gap_label = "高賣低買差" if gap > 0 else "低賣高買差"
            parts.append(
                f'<tr><td>{_esc(w["broker_id"])}<br>{_esc(w["broker_name"])}</td>'
                f'<td><span style="color:{type_color};font-weight:600">'
                f'{wash_type}</span></td>'
                f'<td class="sell">{sell_str}</td>'
                f'<td class="buy">{buy_str}</td>'
                f'<td class="num">{gap_label}<br>{gap_sign}${gap:.2f}'
                f'<br><small>({pct:.0f}% 全日)</small></td>'
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

    # 📅 Multi-day timing pattern (per matched broker) — surfaces "always
    # buys late after sell-off" / "always sells early into morning rally"
    # type patterns. Only run when there are ≤3 matched brokers (else table
    # gets huge); for single-broker queries this is most useful.
    if len(sorted_brokers) <= 3:
        for b in sorted_brokers:
            timing = tw_chip_price.broker_timing_pattern(
                code, b["broker_id"], n_days=8)
            if not timing:
                continue
            parts.append(
                f'<section><h3>📅 {_esc(b["broker_id"])} '
                f'{_esc(b["broker_name"])} 近 {len(timing)} 日時段 pattern</h3>'
                f'<p class="meta">每日 OHLC 走勢 + 該分點當日買賣時段分布 '
                f'(早盤 09:00-10:08 / 盤中 10:08-12:22 / 尾盤 12:22-13:30)</p>'
            )
            parts.append(
                '<table class="report-table"><thead><tr>'
                '<th>日期</th><th class="num">OHLC</th><th>走勢</th>'
                '<th class="num">當日買/賣</th>'
                '<th>早盤</th><th>盤中</th><th>尾盤</th>'
                '<th>主場時段</th>'
                '</tr></thead><tbody>'
            )
            for row in timing:
                d = row["date"]
                d_short = f"{d[4:6]}/{d[6:8]}"
                ohlc = row["ohlc"]
                if ohlc:
                    ohlc_str = (f"O{ohlc['open']:.0f}/H{ohlc['high']:.0f}/"
                                f"L{ohlc['low']:.0f}/C{ohlc['close']:.0f}")
                    pct = ((ohlc["close"] - ohlc["open"]) / ohlc["open"]
                           * 100 if ohlc["open"] else 0)
                    pct_cls = "pos" if pct > 0 else "neg"
                    pct_str = (f'<br><span class="{pct_cls}">'
                               f'{"+" if pct >= 0 else ""}{pct:.1f}%</span>')
                else:
                    ohlc_str = "—"
                    pct_str = ""
                trend = row["trend"]
                trend_color = ("#c30" if trend == "開高走低"
                               else "#0a7e0a" if trend == "開低走高"
                               else "#666")
                trend_html = (f'<span style="color:{trend_color};'
                              f'font-weight:600">{trend}</span>')

                total_buy = row["total_buy_zhang"]
                total_sell = row["total_sell_zhang"]
                total_str = (
                    f'<span class="buy">+{total_buy}</span> / '
                    f'<span class="sell">-{total_sell}</span> 張'
                )

                # Stage cells: show net only (buy - sell per stage)
                stages = [
                    ("早盤", row["early_buy"], row["early_sell"]),
                    ("盤中", row["mid_buy"], row["mid_sell"]),
                    ("尾盤", row["late_buy"], row["late_sell"]),
                ]
                stage_htmls = []
                # Determine dominant stage by net abs activity (only for
                # 該日 net signal — to highlight pattern)
                net_per_stage = [abs(b - s) for _, b, s in stages]
                max_stage_idx = (net_per_stage.index(max(net_per_stage))
                                 if max(net_per_stage) > 0 else -1)
                for i, (name, sb, ss) in enumerate(stages):
                    if sb == 0 and ss == 0:
                        stage_htmls.append('<td class="muted">—</td>')
                        continue
                    snet = sb - ss
                    bg = (' style="background:#fff4e0"' if i == max_stage_idx
                          else '')
                    cell = ""
                    if sb:
                        cell += f'<span class="buy">+{sb}</span>'
                    if ss:
                        if cell:
                            cell += " / "
                        cell += f'<span class="sell">-{ss}</span>'
                    stage_htmls.append(f'<td{bg}>{cell}</td>')

                stages_named = ["早盤", "盤中", "尾盤"]
                dominant = (stages_named[max_stage_idx]
                            if max_stage_idx >= 0 else "—")
                # Bold dominant if it covers ≥60% of day's net
                dom_pct = 0
                if sum(net_per_stage) > 0:
                    dom_pct = (max(net_per_stage) / sum(net_per_stage)
                               * 100)
                dom_html = (f"<b>{dominant}</b>" if dom_pct >= 60
                            else dominant)
                if dom_pct >= 60:
                    dom_html += (f' <small>({dom_pct:.0f}%)</small>')

                parts.append(
                    f'<tr>'
                    f'<td>{d_short}</td>'
                    f'<td class="num small">{ohlc_str}{pct_str}</td>'
                    f'<td>{trend_html}</td>'
                    f'<td class="num">{total_str}</td>'
                    + "".join(stage_htmls)
                    + f'<td>{dom_html}</td>'
                    f'</tr>'
                )
            parts.append('</tbody></table>')
            parts.append(
                '<p class="small">📌 主場時段 = 該日 (買-賣) 絕對值最大的時段。'
                '佔比 ≥60% 才視為「明確 pattern」(加粗顯示)。'
                '⚠ OHLC 來自 FinMind，沒抓到的日期會空白。</p>'
            )
            # ── 結論分析 (pattern conclusion) ──
            # User feedback (2026-05-21): 不應該只用「主場時段日數」判定 pattern,
            # 買的張數 (volume) 跟價格 (low pick vs chase high) 都該納入考量。
            stage_count = {"早盤": 0, "盤中": 0, "尾盤": 0}
            stage_strong = {"早盤": 0, "盤中": 0, "尾盤": 0}
            stage_volume = {"早盤": 0, "盤中": 0, "尾盤": 0}  # accum |net|
            stage_buy_vol = {"早盤": 0, "盤中": 0, "尾盤": 0}  # buy only
            stage_buy_val = {"早盤": 0.0, "盤中": 0.0, "尾盤": 0.0}
            # Price position: where in day range did broker buy (0 = at low,
            # 100 = at high). Aggregate across days for the dominant stage.
            stage_price_pos: dict = {"早盤": [], "盤中": [], "尾盤": []}
            trend_stage: dict = {}
            total_buy_all = 0
            total_sell_all = 0
            for row in timing:
                stages = [
                    ("早盤", row["early_buy"], row["early_sell"],
                     row.get("early_buy_avg")),
                    ("盤中", row["mid_buy"], row["mid_sell"],
                     row.get("mid_buy_avg")),
                    ("尾盤", row["late_buy"], row["late_sell"],
                     row.get("late_buy_avg")),
                ]
                nets = [abs(b - s) for _, b, s, _ in stages]
                if sum(nets) == 0:
                    continue
                max_idx = nets.index(max(nets))
                dom_stage = ["早盤", "盤中", "尾盤"][max_idx]
                dom_pct = max(nets) / sum(nets) * 100
                stage_count[dom_stage] += 1
                if dom_pct >= 60:
                    stage_strong[dom_stage] += 1
                # Accumulate per-stage stats
                ohlc = row.get("ohlc", {})
                hi = ohlc.get("high", 0)
                lo = ohlc.get("low", 0)
                rng = max(hi - lo, 0.01)
                for name, sb, ss, buy_avg in stages:
                    stage_volume[name] += abs(sb - ss)
                    stage_buy_vol[name] += sb
                    if buy_avg is not None:
                        stage_buy_val[name] += buy_avg * sb
                    # Price position 0-100% for this day's buys in this stage
                    if buy_avg is not None and lo > 0 and hi > lo:
                        pos = (buy_avg - lo) / rng * 100
                        stage_price_pos[name].append(
                            (pos, sb))  # weighted by volume
                trend_stage.setdefault(row["trend"], []).append(dom_stage)
                total_buy_all += row["total_buy_zhang"]
                total_sell_all += row["total_sell_zhang"]
            n_days = len(timing)
            # Pick top_stage by VOLUME share (not day count) — user feedback:
            # 1 day with 190 張 in 尾盤 weighs more than 3 days with 5 張 each
            # in 早盤. Total net volume better reflects "real pattern".
            total_vol = sum(stage_volume.values()) or 1
            stage_vol_pct = {s: v / total_vol * 100
                             for s, v in stage_volume.items()}
            sorted_stages = sorted(stage_volume.items(),
                                   key=lambda x: -x[1])
            top_stage = sorted_stages[0][0]
            top_cnt = stage_count[top_stage]
            top_strong = stage_strong[top_stage]
            top_vol_pct = stage_vol_pct[top_stage]
            # Volume-weighted avg buy price position for top stage
            top_pos_data = stage_price_pos[top_stage]
            top_avg_pos = (sum(p * v for p, v in top_pos_data) /
                           sum(v for _, v in top_pos_data)
                           if top_pos_data and sum(v for _, v in top_pos_data) > 0
                           else None)
            # Volume-weighted avg buy price (raw NT$)
            top_vwap = (stage_buy_val[top_stage] / stage_buy_vol[top_stage]
                        if stage_buy_vol[top_stage] > 0 else None)
            # Net direction
            net_total = total_buy_all - total_sell_all
            direction = ("**淨買方**" if net_total > total_sell_all
                         else "**淨賣方**" if net_total < -total_buy_all * 0.2
                         else "雙向 (買賣相近)")
            # Behavior on 開高走低 days
            ohk_lo_stages = trend_stage.get("開高走低", [])
            ohk_hi_stages = trend_stage.get("開低走高", [])
            mid_stages = trend_stage.get("中性", [])
            ohk_lo_late_pct = (ohk_lo_stages.count("尾盤") /
                                len(ohk_lo_stages) * 100
                                if ohk_lo_stages else 0)
            conclusion_parts = []
            # Volume-share view (primary)
            conclusion_parts.append(
                f'<li><b>主要時段 (按淨量):</b> {top_stage} 佔 '
                f'{top_vol_pct:.0f}% 累計淨量 '
                f'({stage_volume[top_stage]} 張)。'
                f'早盤 {stage_vol_pct["早盤"]:.0f}% / '
                f'盤中 {stage_vol_pct["盤中"]:.0f}% / '
                f'尾盤 {stage_vol_pct["尾盤"]:.0f}%</li>'
            )
            # Day-count view (secondary)
            conclusion_parts.append(
                f'<li><b>主場日數分布:</b> 早盤 {stage_count["早盤"]} / '
                f'盤中 {stage_count["盤中"]} / 尾盤 {stage_count["尾盤"]} 天'
                f' (top {top_stage}: {top_cnt}/{n_days}, '
                f'明確 pattern {top_strong}/{n_days})</li>'
            )
            # Price position (where in day range did broker buy in top_stage)
            if top_avg_pos is not None and top_vwap is not None:
                pos_label = (
                    "🟢 接近低點" if top_avg_pos < 35
                    else "🔴 追逼高點" if top_avg_pos > 65
                    else "中位區"
                )
                conclusion_parts.append(
                    f'<li><b>{top_stage}買進價位:</b> 均買 '
                    f'${top_vwap:.2f}，位於當日範圍 '
                    f'{top_avg_pos:.0f}% 位置 → {pos_label}</li>'
                )
            if ohk_lo_stages:
                ohk_summary = (
                    f"開高走低 ({len(ohk_lo_stages)} 天) "
                    + " / ".join(ohk_lo_stages)
                )
                if ohk_lo_late_pct >= 60:
                    note = (f' → ⭐ <b>弱勢日尾盤接刀 pattern</b> '
                            f'({ohk_lo_late_pct:.0f}%)')
                else:
                    note = ''
                conclusion_parts.append(
                    f'<li><b>開高走低時:</b> {ohk_summary}{note}</li>'
                )
            if ohk_hi_stages:
                conclusion_parts.append(
                    f'<li><b>開低走高時:</b> {len(ohk_hi_stages)} 天 '
                    + " / ".join(ohk_hi_stages) + '</li>'
                )
            if mid_stages:
                conclusion_parts.append(
                    f'<li><b>中性盤:</b> {len(mid_stages)} 天 '
                    + " / ".join(mid_stages) + '</li>'
                )
            conclusion_parts.append(
                f'<li><b>{n_days} 日累計:</b> 買 +{total_buy_all} / '
                f'賣 -{total_sell_all} 張 = '
                f'淨 {"+" if net_total >= 0 else ""}{net_total} 張 '
                f'({direction})</li>'
            )
            # Behavior label + detailed explanation
            label_key = None
            label_short = ""
            label_long = ""
            # Pattern threshold (user feedback 2026-05-21): top_stage 應該
            # 用 volume share 而非單純日數判斷。任一條件成立即視為明確 pattern:
            # 1. top_stage 佔累計淨量 ≥50% (volume-dominant)
            # 2. top_stage 強勢日佔 ≥40% 天數 (day-count-dominant, 原邏輯)
            # 這樣 "1 天 190 張在尾盤 + 3 天 30 張各在早盤" 仍會被歸尾盤
            # (因為尾盤 volume share > 50%) — 反映 user 真實意圖
            volume_dominant = top_vol_pct >= 50
            count_dominant = top_strong >= n_days * 0.4
            if volume_dominant or count_dominant:
                if top_stage == "尾盤" and net_total > 0:
                    # Distinguish 真低接 vs 追高: depends on price position
                    if top_avg_pos is not None and top_avg_pos < 35:
                        label_key = "尾盤低接型"
                        label_short = (
                            '🎯 <b>尾盤低接型</b> — 尾盤淨買主場 '
                            f'({top_vol_pct:.0f}% 淨量) 且'
                            f'<b>接近當日低點</b> (均買位置 {top_avg_pos:.0f}%)，'
                            '<b>中期累積部位</b> (持有期難從短期資料判定，'
                            '但確定不是當沖)')
                    elif top_avg_pos is not None and top_avg_pos > 65:
                        label_key = "尾盤追高型"
                        label_short = (
                            '⚠ <b>尾盤追高型</b> — 尾盤淨買主場 '
                            f'({top_vol_pct:.0f}% 淨量) 但'
                            f'<b>接近當日高點</b> (均買位置 {top_avg_pos:.0f}%)，'
                            '可能是收盤前 FOMO 或被動 algo execution')
                    else:
                        label_key = "尾盤中位接型"
                        label_short = (
                            '🎯 <b>尾盤中位接型</b> — 尾盤淨買主場 '
                            f'({top_vol_pct:.0f}% 淨量), 均買位置'
                            f' {top_avg_pos:.0f}% (中性)，'
                            '<b>中期累積部位</b>')
                    label_long = (
                        '<p style="background:#fff4e0;padding:8px 12px;'
                        'border-left:3px solid #c30;border-radius:4px;">'
                        '<b>⚠ 誠實聲明</b>: 這個判定是 <b>process of elimination'
                        ' (排除法)</b>，不是直接觀察出來的。我們能觀察的是「該分點'
                        '尾盤淨買」+「跨日建倉」+「沒當沖結算」+「逢弱勢加碼」'
                        '+「量級偏大」，但<b>持有期 (1 週 vs 1 個月 vs 半年) '
                        '無法從 N 日短期資料直接判定</b>。下面是排除其他可能性後'
                        '的最合理推論。</p>'
                        '<p><b>可觀察的事實 (硬證據)</b></p>'
                        '<ul>'
                        '<li><b>淨買方</b>：賣量遠小於買量</li>'
                        '<li><b>尾盤集中接刀</b>：不追早盤拉高</li>'
                        '<li><b>跨日連續建倉</b>：N 日內天天買 → 不是 day trade</li>'
                        '<li><b>接近低點接</b>：均成本 ≤ 全日範圍中位</li>'
                        '<li><b>量級偏大</b>：累計 N 百張 → 散戶很少這樣分批</li>'
                        '</ul>'
                        '<p><b>排除法推論</b> — 各種策略能否解釋觀察:</p>'
                        '<table style="width:100%;border-collapse:collapse;'
                        'font-size:0.95em;margin:6px 0;">'
                        '<tr style="background:#fafafa;"><th style="padding:4px 8px;'
                        'border-bottom:1px solid #ddd;text-align:left;">策略類型</th>'
                        '<th style="padding:4px 8px;border-bottom:1px solid #ddd;'
                        'text-align:left;">符合觀察?</th></tr>'
                        '<tr><td style="padding:4px 8px;">當沖 (day trade)</td>'
                        '<td style="padding:4px 8px;">❌ 不能 (sell << buy)</td></tr>'
                        '<tr><td style="padding:4px 8px;">長期 position (≥6 月)</td>'
                        '<td style="padding:4px 8px;">🟡 可能但太快 '
                        '(5-7 天就建 400+ 張)</td></tr>'
                        '<tr style="background:#e7f5e7"><td style="padding:4px 8px;">'
                        '<b>中期累積 (含 swing 2-30 天)</b></td>'
                        '<td style="padding:4px 8px;">✅ <b>完美符合</b></td></tr>'
                        '<tr><td style="padding:4px 8px;">ETF rebalance</td>'
                        '<td style="padding:4px 8px;">🟡 應該更系統化，不會 OHLC '
                        '逢低加碼</td></tr>'
                        '<tr><td style="padding:4px 8px;">TWAP/VWAP algo</td>'
                        '<td style="padding:4px 8px;">🟡 通常在盤中，不集中尾盤'
                        '</td></tr>'
                        '<tr><td style="padding:4px 8px;">做市 / 流動性</td>'
                        '<td style="padding:4px 8px;">❌ 應該兩向，不是單邊大買'
                        '</td></tr>'
                        '</table>'
                        '<p><b>持有期類別 (參考)</b></p>'
                        '<ul>'
                        '<li>當沖 (day trade)：1 天內買進賣出</li>'
                        '<li><b>波段 swing trade：持有 2-30 天</b>，目標 5-15% 中期</li>'
                        '<li>中期 position：1-3 個月</li>'
                        '<li>長期 position：6 個月以上</li>'
                        '</ul>'
                        '<p><b>實務含意</b>：</p>'
                        '<ul>'
                        '<li>可確定：該分點短線不會大砍 (不是當沖)</li>'
                        '<li>不能確定：他是 swing (2-30 天) 還是更長期 — 需更多歷史'
                        '才能精確分辨</li>'
                        '<li>跟他們同方向 = 有大戶背書</li>'
                        '<li>他們均成本可能是支撐 / 停損參考線</li>'
                        '</ul>'
                        '<p><b>常見玩家</b>：自營商、中小型投信基金、私募、'
                        '千張級大戶、量化中期策略</p>'
                        '<p><b>要更精確分辨 swing vs position?</b> 觀察 20-30 個'
                        '交易日 — 如果該分點繼續加碼沒減 → 長期 position; '
                        '某日大量賣出 → swing 出場; 每隔幾週進出 → 確認 swing</p>'
                    )
                elif top_stage == "尾盤" and net_total < 0:
                    label_key = "尾盤倒貨型"
                    label_short = ('⚠ <b>尾盤倒貨型</b> — 在收盤前出貨，'
                                   '可能是<b>短線投機客 day-trade 結算</b>或<b>法人減碼</b>')
                    label_long = (
                        '<p><b>什麼是 day-trade 結算?</b></p>'
                        '<p>day trade = 當沖。當沖客當天買進，當天 12:00-13:30 收盤前必出，'
                        '避免收盤後留倉風險。當沖客大量集中在尾盤倒貨是常見現象。</p>'
                        '<p><b>為什麼判定為尾盤倒貨型?</b></p>'
                        '<ul>'
                        '<li>尾盤是該分點淨賣的主場時段</li>'
                        '<li>N 日累計淨賣 → 整體在出貨</li>'
                        '<li>可能解讀: (1) 當沖結算 (2) 法人逐日減碼 swing 部位</li>'
                        '</ul>'
                        '<p><b>實務含意</b>：跟這分點同方向 = 跟跌 / 跟空; '
                        '反方向 = 接他們倒的貨 (要注意是否他們有未公開的負面訊息)</p>'
                    )
                elif top_stage == "早盤" and net_total > 0:
                    label_key = "早盤追擊型"
                    label_short = ('🚀 <b>早盤追擊型</b> — 開盤就積極建倉，'
                                   '可能是<b>動能策略 (momentum)</b>')
                    label_long = (
                        '<p><b>動能策略 (Momentum Strategy)</b></p>'
                        '<p>「強者恆強」邏輯：股票一旦開盤跳空向上或開高走高，'
                        '法人/演算法系統會在早盤前 30 分鐘搶進，期待當日續強。</p>'
                        '<p><b>為什麼判定為早盤追擊型?</b></p>'
                        '<ul>'
                        '<li>早盤 09:00-10:08 是主場時段</li>'
                        '<li>淨買累積大 → 不是測試單，是真實建倉</li>'
                        '<li>常見於：法人量化交易、跟風者、ETF rebalance</li>'
                        '</ul>'
                        '<p><b>注意</b>：早盤追擊風險較高，若股票尾盤反轉拉回，他們可能套高。'
                        '5/12 的 9A81 就是這種情境 (早盤 +68 但收盤 -5.4%)。</p>'
                    )
                elif top_stage == "早盤" and net_total < 0:
                    label_key = "早盤出貨型"
                    label_short = ('📉 <b>早盤出貨型</b> — 開盤立刻倒貨，'
                                   '可能是<b>停損</b>或<b>反向獲利了結</b>')
                    label_long = (
                        '<p><b>典型行為</b>：開盤後 30 分鐘內大量倒貨。常見於：</p>'
                        '<ul>'
                        '<li>觸發前一日設定的停損價</li>'
                        '<li>昨晚有負面消息 (財報miss/政策 etc) 開盤倒貨</li>'
                        '<li>大戶逢開盤拉高賣出 (反向獲利)</li>'
                        '</ul>'
                        '<p><b>注意</b>：早盤倒貨後股價往往會繼續走弱 (因為其他人跟賣)。'
                        '跟同方向 = 跟賣; 反向 = 接他們的籌碼 (要評估為何他們急著出)</p>'
                    )
                elif top_stage == "盤中":
                    direction_word = "布局" if net_total > 0 else "出貨"
                    label_key = f"盤中{direction_word}型"
                    label_short = (f'⚖ <b>盤中{direction_word}型</b> — '
                                   '避開早盤情緒激動 + 尾盤搶賣，挑盤中相對冷靜時段操作')
                    label_long = (
                        '<p><b>盤中 (10:08-12:22) 是什麼樣的時段?</b></p>'
                        '<p>早盤情緒激動 (開盤跳空/搶買搶賣) 結束、尾盤恐慌 (收盤前砍倉) 還沒開始，'
                        '盤中是「相對冷靜」的成交時段。法人和聰明資金常選這時段操作，'
                        '因為買賣價差 (spread) 較合理。</p>'
                        '<p><b>為什麼判定?</b></p>'
                        '<ul>'
                        '<li>盤中是該分點主場時段</li>'
                        f'<li>整體方向: 淨{direction_word}</li>'
                        '<li>常見於：法人 algorithmic execution (TWAP/VWAP 演算法)、'
                        '價值型投資者、不想壓低/拉高市場的大戶</li>'
                        '</ul>'
                    )
            else:
                label_key = "多時段混合"
                label_short = ('🔀 <b>多時段混合操作</b> — '
                               f'{top_stage} 略多但無明確 pattern (佔比 < 60%)')
                label_long = (
                    '<p><b>為什麼沒明確 pattern?</b></p>'
                    '<p>該分點 N 日操作分散在多個時段，沒有任一時段佔 ≥60%。'
                    '可能是：</p>'
                    '<ul>'
                    '<li>多個客戶/帳戶共享同一分點（不同人不同 pattern）</li>'
                    '<li>該分點本身策略靈活、見機操作</li>'
                    '<li>樣本天數太少 (N < 5)，pattern 還沒成形</li>'
                    '</ul>'
                    '<p>建議：等累積 N ≥ 6 再判讀，或細看每日 OHLC + 時段對應</p>'
                )
            if label_short:
                conclusion_parts.append(f'<li>{label_short}</li>')
                if label_long:
                    conclusion_parts.append(
                        '<li><details style="margin-top:6px;">'
                        f'<summary style="cursor:pointer;font-weight:600;color:#0066cc;">'
                        f'▶ 點此展開「{label_key}」詳細解讀 (專有名詞 + 推論依據)'
                        '</summary>'
                        '<div style="margin-top:8px;padding:10px 14px;'
                        'background:white;border-radius:4px;line-height:1.6;">'
                        + label_long +
                        '</div></details></li>'
                    )

            parts.append(
                '<div style="background:#f8f9fa;padding:12px 16px;'
                'border-left:4px solid #0066cc;border-radius:4px;margin-top:8px">'
                f'<b>📊 {n_days} 日 pattern 結論：</b>'
                '<ul style="margin:8px 0 0 0;line-height:1.7;">'
                + ''.join(conclusion_parts) + '</ul></div>'
            )
            parts.append('</section>')

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

        # Wash score requires meaningful two-sided activity. Past noise
        # cases that triggered misleading "真洗盤低接":
        # (1) 11 股 buy + 3,000 股 sell — 零股 + 大單，不是 wash (commit 99de3e4)
        # (2) 214 張 buy + 1 張 sell — 大買 + 1 張小賣，不是 wash
        # Three thresholds applied:
        #   a. each side ≥ 1 張 (1000股) — exclude 零股
        #   b. each side ≥ 1% × day total volume — exclude noise (commit d1fab38)
        #   c. min(buy, sell) / max(buy, sell) ≥ 10% — exclude lopsided one-sided
        wash_html = ""
        day_vol = sum(r.get("buy", 0) for r in rows)
        side_ratio = (min(total_buy, total_sell) / max(total_buy, total_sell)
                      if max(total_buy, total_sell) > 0 else 0)
        passes_threshold = (
            total_buy >= 1000 and total_sell >= 1000 and
            (day_vol == 0 or min(total_buy, total_sell) >= day_vol * 0.01) and
            side_ratio >= 0.10
        )
        if passes_threshold:
            wash_score = (sell_avg - buy_avg) / rng
            wash_type = "高賣低買" if wash_score > 0 else "低賣高買"
            time_pattern = ""
            if buy_t is not None and sell_t is not None:
                sell_first = buy_t - sell_t >= 30
                buy_first = sell_t - buy_t >= 30
                if wash_type == "高賣低買":
                    if sell_first:
                        time_pattern = "✅ 真洗盤低接 (先賣高、後買低)"
                    elif buy_first:
                        time_pattern = "⚠ 追漲獲利出 (先買低、後賣高)"
                    else:
                        time_pattern = "⏱ 時序模糊"
                else:  # 低賣高買
                    if sell_first:
                        time_pattern = ("⚠ 認錯買回 (先賣低、後追高 — "
                                        "認賠補回或翻多)")
                    elif buy_first:
                        time_pattern = ("❌ 殺低出貨 (先買高、後殺低 — "
                                        "恐慌賣)")
                    else:
                        time_pattern = "⏱ 時序模糊"
            sign = "+" if wash_score >= 0 else ""
            wash_html = (
                f'<p><b>🌀 {wash_type}:</b> sell_avg ${sell_avg:.2f} − '
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
                    "exact_ambiguous_multi_cluster": "❓",
                    "leading_block": "🎯",
                    "leading_block_consistent": "🎯+",
                    "window": "🔄",
                    "weighted": "≈",
                    "weighted_multi_cluster": "❓",
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
                # Multi-cluster surfacing (Pattern D — 1-3張 + 熱門價)
                if mt in ("weighted_multi_cluster",
                          "exact_ambiguous_multi_cluster"):
                    cl = primary_match.get("clusters") or []
                    if cl:
                        rng_parts = [
                            f"~{tw_chip_price._minutes_to_hhmm(x['first_min'])}"
                            f"–{tw_chip_price._minutes_to_hhmm(x['last_min'])} "
                            f"({x['tick_count']} ticks, {x['vol']}張)"
                            for x in cl
                        ]
                        alt_html += ('<br><small class="warn">⚠ 多 cluster (你的單在其中一個):<br>'
                                      + ' / '.join(rng_parts) + '</small>')
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
    narrative_block = ""
    if data:
        report_block = _render_report_html(data)
        try:
            narrative_block = _render_narrative_block(
                code or data.get("stock_code", ""), data.get("date", ""))
        except Exception as e:
            narrative_block = (f'<section><h2>🤖 AI 行為敘事</h2>'
                               f'<p class="small">⚠ 無法載入：{_esc(e)}</p></section>')
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
<nav><a href="/">← 大盤 dashboard</a> <a href="/chip-price">📋 籌碼價量</a> <a href="/chip-compare?code=3491">📉 兩波對比</a> <a href="/contract-liabilities">💰 合約負債</a> <a href="/inventory">📦 存貨</a> <a href="/shareholders">👥 前十大股東</a></nav>
<h1>📊 籌碼價量分析 (broker × price × time)</h1>

<form method="get" action="/chip-price" style="flex-wrap:wrap;">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 2313" autofocus required style="width:100px;">
  <label for="broker">分點 (選填):</label>
  <input type="text" id="broker" name="broker" value="{broker_attr}"
         placeholder="例: 9A81 / 5381 / 員林 / 永豐"
         style="width:200px;">
  <button type="submit">查詢 (用快取)</button>
  <button type="submit" name="fresh" value="1" class="secondary">即時抓取 (5-15秒)</button>
</form>
<p class="small">💡 <b>分點欄填了會多顯示「📅 N 日時段 pattern」</b> (該分點過去 6-8 日的早盤/盤中/尾盤買賣分布) +「🔍 分點深度」(per-cell 時間 + 價位分布)。</p>
<p class="small">分點欄可輸入：(1) 代號 e.g. <code>9A81</code>、<code>5381</code>  (2) 分行名稱 e.g. <code>員林</code> = 所有 *員林 分行  (3) 銀行系名 e.g. <code>永豐</code> = 永豐金全系  (4) 中文名 e.g. <code>永豐金匯立</code></p>
<p class="small">範例：
 <a href="/chip-price?code=3491&broker=9A81">3491 + 9A81 永豐金匯立 時段 pattern</a> ·
 <a href="/chip-price?code=2313&broker=8843">2313 + 玉山高雄</a> ·
 <a href="/chip-price?code=7750&broker=1470">7750 + 台灣摩根</a></p>

<div class="recent">📂 近期快取 (點擊直接看)：{recent_links}</div>

{source_block}
{report_block}
{narrative_block}
{broker_html}
</body>
</html>"""


def _render_contract_liabilities_page(code: str = "", years: int = 3,
                                      rows: list[dict] | None = None,
                                      name: str = "",
                                      error: str = "",
                                      source_label: str = "") -> str:
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
            '<p><b>建議</b>：'
            f'<a href="/contract-liabilities?code={code_esc}&years={years}&pdf=1"'
            ' style="display:inline-block;padding:6px 14px;background:#0066cc;'
            'color:white;text-decoration:none;border-radius:4px;font-weight:600">'
            '🔍 從 MOPS 季報 PDF 附註查 (約 30 秒)</a><br>'
            '<small>會自動下載該公司過去 N 年季報 PDF，解析「其他流動負債」附註內的合約負債明細。</small></p>'
            '<p>或去 <a href="https://mops.twse.com.tw/" target="_blank">'
            '公開資訊觀測站 (MOPS)</a> 手動看，'
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
        source_html = (
            f'<p class="meta" style="font-size:0.85em">資料源：'
            f'{html_lib.escape(source_label)}</p>' if source_label else "")
        body = f"""
<section class="header-card">
  <h2>{_esc(code)} {_esc(name)} 合約負債 (近 {years} 年 / {len(rows)} 季)</h2>
  {source_html}
  {cagr_str}
</section>"""
        body += f"""
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
  <a href="/inventory">📦 存貨</a>
  <a href="/shareholders">👥 前十大股東</a>
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


def _episode_svg(series: list[dict], episodes: list[dict]) -> str:
    """雙軸 SVG：價格(左, log-ish 線性) + 借券賣出餘額 SBL(右)，兩波窗口陰影。"""
    if not series:
        return ""
    W, H = 960, 300
    padL, padR, padT, padB = 52, 56, 16, 28
    pw, ph = W - padL - padR, H - padT - padB
    n = len(series)
    pxs = [p["px"] for p in series if p["px"]]
    sbls = [p["sbl"] for p in series if p.get("sbl")]
    if not pxs:
        return ""
    pmin, pmax = min(pxs), max(pxs)
    smin, smax = (min(sbls), max(sbls)) if sbls else (0, 1)
    prng = (pmax - pmin) or 1
    srng = (smax - smin) or 1

    def x(i):
        return padL + pw * i / max(n - 1, 1)

    def yp(v):
        return padT + ph * (1 - (v - pmin) / prng)

    def ys(v):
        return padT + ph * (1 - (v - smin) / srng)

    date_to_i = {p["d"]: i for i, p in enumerate(series)}
    parts = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;'
             'background:#fff;border:1px solid #eee;border-radius:6px;">']
    # 兩波窗口陰影
    shade = ["rgba(255,120,80,0.08)", "rgba(80,140,255,0.08)"]
    for k, ep in enumerate(episodes):
        i0 = next((date_to_i[d] for d in sorted(date_to_i)
                   if d >= ep["peak_date"]), None)
        i1 = next((date_to_i[d] for d in sorted(date_to_i, reverse=True)
                   if d <= ep["ep_end"]), None)
        if i0 is not None and i1 is not None and i1 > i0:
            parts.append(f'<rect x="{x(i0):.0f}" y="{padT}" '
                         f'width="{x(i1)-x(i0):.0f}" height="{ph}" '
                         f'fill="{shade[k % 2]}"/>')
    # 價格線
    pts = " ".join(f"{x(i):.1f},{yp(p['px']):.1f}"
                   for i, p in enumerate(series) if p["px"])
    parts.append(f'<polyline points="{pts}" fill="none" '
                 'stroke="#c0392b" stroke-width="1.6"/>')
    # SBL 線
    if sbls:
        spts = " ".join(f"{x(i):.1f},{ys(p['sbl']):.1f}"
                        for i, p in enumerate(series) if p.get("sbl"))
        parts.append(f'<polyline points="{spts}" fill="none" '
                     'stroke="#2471a3" stroke-width="1.4" '
                     'stroke-dasharray="4 2"/>')
    # 軸標
    parts.append(f'<text x="{padL}" y="12" font-size="11" fill="#c0392b">'
                 f'━ 收盤價 ${pmin:.0f}–${pmax:.0f}</text>')
    parts.append(f'<text x="{W-padR-4}" y="12" font-size="11" fill="#2471a3" '
                 f'text-anchor="end">┄ 借券賣出餘額(張) {smin:.0f}–{smax:.0f}</text>')
    # x 軸月標
    seen = set()
    for i, p in enumerate(series):
        ym = p["d"][:7]
        if ym not in seen and p["d"][8:10] in ("01", "02", "03", "04", "05"):
            seen.add(ym)
            if len(seen) % 2 == 0:
                parts.append(f'<text x="{x(i):.0f}" y="{H-8}" font-size="9" '
                             f'fill="#888" text-anchor="middle">{ym[2:]}</text>')
    parts.append('</svg>')
    return "".join(parts)


def _render_chip_compare_page(code: str = "3491", data: dict | None = None,
                              error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/chip-price">📋 籌碼價量</a> '
           '<a href="/money-flow">💰 族群資金流</a> <a href="/warrant-signal">🎰 權證量能</a> <a href="/stock-futures">🔥 個股期火熱</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.4em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  form{background:#fff;padding:10px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  input{font-size:15px;padding:6px 10px;border:1px solid #ccc;border-radius:4px;width:100px;}
  button{font-size:15px;padding:6px 14px;background:#0066cc;color:#fff;border:none;border-radius:4px;cursor:pointer;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:6px 9px;border-bottom:1px solid #eee;text-align:right;}
  th:first-child,td:first-child{text-align:left;}
  th{background:#fafafa;color:#555;}
  .pos{color:#c0392b;} .neg{color:#186a3b;}
  .ep25{border-left:3px solid #e67e22;} .ep26{border-left:3px solid #2980b9;}
  .small,small{font-size:.85em;color:#666;}
  .err{background:#fee;border:1px solid #f99;padding:12px;border-radius:4px;color:#c00;}
  .note{background:#fdf6e8;color:#a06000;padding:8px 12px;border-radius:4px;font-size:.85em;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{code} 兩波籌碼對比</title>{css}</head><body>{nav}'
            f'<h1>📉 昇達科式「兩波下殺」籌碼對比 — {code}</h1>'
            f'<form method="get"><label>代號 </label>'
            f'<input name="code" value="{html_lib.escape(code)}"> '
            f'<button>比對</button> '
            f'<span class="small">預設比 2025 春(3-8月) vs 2026(5月至今)</span></form>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="err">⚠ {_esc(error)}</div>' + tail
    if not data or not data.get("episodes"):
        return head + '<section>無資料</section>' + tail

    eps = data["episodes"]
    svg = _episode_svg(data.get("series", []), eps)

    def _f(v, suf="", sign=False):
        if v is None:
            return "—"
        s = f"{v:+,.0f}" if sign else f"{v:,.0f}"
        return f"{s}{suf}"

    def _seg_cells(seg):
        if not seg:
            return "<td colspan=4 class='small'>（無此段）</td>"
        pc = seg["px_chg_pct"]
        pc_cls = "neg" if pc < 0 else "pos"
        f = seg["f_cum"]
        return (f"<td>${seg['px0']:,.0f}→${seg['px1']:,.0f} "
                f"<span class='{pc_cls}'>({pc:+.0f}%)</span></td>"
                f"<td class='{'neg' if f<0 else 'pos'}'>{_f(f,'張',True)}</td>"
                f"<td>{_f(seg.get('sbl0'))}→{_f(seg.get('sbl1'),'張')} "
                f"<small>峰{_f(seg.get('sbl_peak'))}</small></td>"
                f"<td>{_f(seg.get('mgn0'))}→{_f(seg.get('mgn1'),'張')}</td>")

    rows = []
    labels = [("2025 春", "ep25"), ("2026", "ep26")]
    for ep, (lbl, cls) in zip(eps, labels):
        rows.append(
            f'<tr class="{cls}"><td><b>{lbl} 下跌段</b><br>'
            f'<small>{ep["peak_date"][2:]}高 ${ep["peak_px"]:,.0f} '
            f'→ {ep["low_date"][2:]}低 ${ep["low_px"]:,.0f}</small></td>'
            f'{_seg_cells(ep["fall"])}</tr>')
        if ep.get("base"):
            rows.append(
                f'<tr class="{cls}"><td>{lbl} 築底/反彈段</td>'
                f'{_seg_cells(ep["base"])}</tr>')

    findings = (
        '<section><h3 style="margin:.2em 0">🔍 判讀（自動計算＋人工歸納）</h3>'
        '<ul class="small" style="line-height:1.7">'
        '<li><b>下跌驅動力不同</b>：2025 下跌段外資幾乎沒賣、借券小增 = 無量陰跌；'
        '2026 下跌段外資大賣＋借券同步加碼 = 外資主導殺盤（籌碼與價同向、像真去化）。</li>'
        '<li><b>築底期借券行為相反</b>：2025 築底反彈段借券<b>暴增到高峰</b>（空方低檔總攻→'
        '結果押錯、成軋空燃料、8 月起漲）；2026 落底至今借券未再放大（空方克制），'
        '<b>缺 2025 那種軋空柴火</b>。</li>'
        '<li><b>融資兩期都穩定</b>（2025 ~4,700 張、2026 ~3,300 張，沒有斷頭去槓桿潮）'
        '— 融資戶抱住沒跑，與 5347 跌停日狂砍融資相反，是本檔特徵。</li>'
        '<li><b>雷同</b>：兩次外資都站賣方、下跌全程無外資大買承接；跌幅級距相近。</li>'
        '<li><b>規模</b>：2025 借券高峰 6,406 張 vs 2026 目前 ~3,600 張，'
        '今年絕對空方部位還不到去年築底時六成。</li>'
        '</ul></section>')

    caveat = (
        '<p class="note">⚠ <b>限制</b>：(1) <b>券商分點無歷史 API</b>，'
        '2025 那波完全沒有分點細節，本頁只用官方借券＋法人＋融資；'
        '(2) 2026 仍進行中，「低點」是暫時低點非確認底；'
        '(3) 除息前借券會有召回/還券擾動（制度性、非空方撤退）；'
        '(4) 外資淨額為官方三大法人（股→張），借券為 SBL 賣出餘額。</p>')

    tbl = ('<section>' + (svg or '') +
           '<table><thead><tr><th>時期／段</th><th>價格(段內)</th>'
           '<th>外資累計淨</th><th>借券賣出餘額(SBL)</th><th>融資餘額</th>'
           '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>' +
           f'<p class="small">資料至 {_esc(data.get("asof",""))}｜'
           '借券/外資 單位股已換算張；融資 balance 原生為張。</p></section>')
    return head + tbl + findings + caveat + tail


@app.route("/lin-matrix")
def lin_matrix_page():
    import glob as _glob
    import lin_matrix as lm
    # 優先讀當日 cron 產生的 JSON 歷史(快)；無則即時算(慢)
    hist_dir = os.path.join(HERE, "cache", "lin_matrix_history")
    files = sorted(_glob.glob(os.path.join(hist_dir, "*.json")))
    data = None
    if files:
        try:
            with open(files[-1], encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if data is None:
        try:
            data = lm.fetch_signals(request.args.get("date") or None)
        except Exception as e:
            data = {"error": f"{type(e).__name__}: {e}"}
    return lm.render_html(data)


@app.route("/margin-scan")
def margin_scan_page():
    import tw_margin_scan as ms
    cache = os.path.join(HERE, "cache", "margin_scan_latest.json")
    data = None
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if data is None:
        try:
            data = ms.scan(request.args.get("date") or None)
        except Exception as e:
            data = {"error": f"{type(e).__name__}: {e}"}
    return ms.render_html(data)


@app.route("/extremes")
def extremes_page():
    import tw_extremes as ex
    cache = os.path.join(HERE, "cache", "extremes_latest.json")
    data = None
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
    if data is None:
        try:
            data = ex.compute_extremes(request.args.get("date") or None,
                                       int(request.args.get("top", 20)))
        except Exception as e:
            data = {"error": f"{type(e).__name__}: {e}"}
    return ex.render_html(data)


@app.route("/market-tomorrow")
def market_tomorrow_page():
    import tw_market_overnight as mo
    try:
        raw = mo._fetch_raw()
        night = mo.fetch_night_returns() or None
        pred = mo.predict_next(raw, night)
        bt = mo.backtest(raw, night)
    except Exception as e:
        pred, bt = {"error": f"{type(e).__name__}: {e}"}, None
    return mo.render_html(pred, bt)


@app.route("/stock-futures")
def stock_futures_page():
    import tw_stock_futures as sf
    date = (request.args.get("date") or "").strip() or None
    try:
        data = sf.fetch_ranking(date, top_n=30)
    except Exception as e:
        data = {"error": f"{type(e).__name__}: {e}"}
    return sf.render_html(data)


@app.route("/warrant-signal")
def warrant_signal_page():
    import glob as _glob
    import warrant_signal as ws
    import warrant_signal_renderer as wsr
    flow_dir = os.path.join(HERE, "cache", "warrant_flow")
    files = sorted(_glob.glob(os.path.join(flow_dir, "*.json")))[-60:]
    days = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                days.append(json.load(fh))
        except Exception:
            continue
    if not days:
        return wsr.render_page([], {}, "", backtest=None)
    try:
        rows = ws.build_signal_rows(days)
    except Exception:
        rows = []
    bt = None
    bt_path = os.path.join(HERE, "cache", "warrant_backtest.json")
    if os.path.exists(bt_path):
        try:
            with open(bt_path, encoding="utf-8") as fh:
                bt = json.load(fh)
        except Exception:
            bt = None
    try:
        import warrant_flow as wf
        terms = wf.load_terms()
    except Exception:
        terms = {}
    return wsr.render_page(rows, days[-1], days[-1].get("date", ""),
                           backtest=bt, terms=terms)


@app.route("/chip-compare")
def chip_compare():
    import chip_episode_compare as cec
    from datetime import datetime as _dt
    code = (request.args.get("code") or "3491").strip()
    episodes = [("2025-03-21", "2025-08-31"),
                ("2026-05-29", _dt.now().strftime("%Y-%m-%d"))]
    try:
        data = cec.build_compare(code, episodes)
    except Exception as e:
        return _render_chip_compare_page(code=code, error=f"{type(e).__name__}: {e}")
    if data.get("error"):
        return _render_chip_compare_page(code=code, error=data["error"])
    return _render_chip_compare_page(code=code, data=data)


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
    source_label = "FinMind TaiwanStockBalanceSheet"
    # PDF fallback: when FinMind has no top-level 合約負債 (e.g. 3491,
    # 6282, 2330 — bury it under 其他流動負債), parse the MOPS quarterly
    # report PDF footnote instead. Only triggered on user-explicit
    # ?pdf=1 to avoid auto-downloading 12+ PDFs per query.
    if not rows and request.args.get("pdf") == "1":
        try:
            import mops_pdf
            pdf_series = mops_pdf.fetch_contract_liabilities_series(
                code, years=years)
            if pdf_series:
                rows = [
                    {"date": d, "current": amt * 1000, "noncurrent": 0,
                     "total": amt * 1000}
                    for d, amt in sorted(pdf_series.items())
                ]
                rows = tw_contract_liabilities.annotate_changes(rows)
                source_label = "MOPS 季報 PDF 附註 (其他流動負債明細)"
        except Exception as e:
            return _render_contract_liabilities_page(
                code=code, years=years,
                error=f"PDF fallback failed: {type(e).__name__}: {e}")
    return _render_contract_liabilities_page(
        code=code, years=years, rows=rows, name=name,
        source_label=source_label)


def _breakdown_commentary(series: dict, inv_rows: list[dict] | None = None) -> str:
    """Generate accounting/industry expert commentary on inventory breakdown.

    判定邏輯：YoY 為主方向 + QoQ 連 2 季同向加倍強化 + 營收交叉驗證。
    - 訊號方向由 YoY 決定（扣季節性）
    - 若近 2 季 QoQ 也與 YoY 同方向 → 標 ⚡ 加倍強化
    - 若近 2 季 QoQ 反向 → 標 ↻ YoY 訊號減弱 (轉折)
    - inv_rows 帶營收時，再做存貨 vs 營收交叉檢查：存貨雙升但營收沒同步
      → 觸發「庫存壓力劇增 / 跌價損失風險」警訊
    """
    dates = sorted(series.keys())
    if len(dates) < 5:
        return ""  # Need ≥5 quarters for meaningful YoY
    latest = series[dates[-1]]
    yoy = series[dates[-5]]
    prev_q = series[dates[-2]]
    prev2_q = series[dates[-3]] if len(dates) >= 3 else None
    if not yoy:
        return ""

    def _qoq_accel(yp, q_now, q_prev, thresh=1.0):
        """Return (html_tag, accelerated_bool, reversed_bool).
        accelerated = QoQ 連 2 季都與 YoY 同向
        reversed    = QoQ 連 2 季都與 YoY 反向 (轉折訊號)
        """
        if yp is None or q_now is None or q_prev is None:
            return ("", False, False)
        if abs(q_now) < thresh or abs(q_prev) < thresh:
            return ("", False, False)
        yoy_up = yp > 0
        both_up = q_now > 0 and q_prev > 0
        both_dn = q_now < 0 and q_prev < 0
        if (yoy_up and both_up) or ((not yoy_up) and both_dn):
            return (' <b style="color:#c00">⚡ QoQ 連 2 季同向強化</b>', True, False)
        if (yoy_up and both_dn) or ((not yoy_up) and both_up):
            return (' <span style="color:#888">↻ 近 2 季 QoQ 反向，YoY 訊號減弱</span>',
                    False, True)
        return ("", False, False)

    cat_meta = {
        "raw_materials": ("原料",
            ("備料增加 → 預期未來 1-2 季產能放大",
             "備料下降 → 預期訂單轉冷 / 庫存去化中")),
        "work_in_progress": ("在製品",
            ("在製產能滿載 → 1-3 個月內轉認列營收，**最強 leading indicator**",
             "在製下降 → 訂單轉淡 / 完工出貨")),
        "finished_goods": ("製成品",
            ("⚠ 製成品堆積 → 出貨壓力或客戶 push-out (warning signal)",
             "製成品下降 → 出貨順暢")),
        "in_transit": ("在途存貨",
            ("物流增加 / 大批採購中",
             "在途下降 / 集中收貨")),
        "materials_supplies": ("物料及零件 / 消耗品",
            ("輔料備料同步增加",
             "輔料消化")),
        "merchandise": ("商品",
            ("通路品擴大",
             "通路品減少")),
        "semi_finished": ("半成品",
            ("中間製程庫存增加",
             "中間製程消耗")),
        "byproducts": ("副產品", ("副產品累積", "副產品下降")),
    }

    accel_map = {}  # key → True if YoY 方向被 QoQ 連 2 季確認
    items = []
    for key, (label, (up_msg, down_msg)) in cat_meta.items():
        v_latest = latest.get(key, 0)
        v_yoy = yoy.get(key, 0)
        v_prev = prev_q.get(key, 0) if prev_q else 0
        v_prev2 = prev2_q.get(key, 0) if prev2_q else 0
        if v_latest == 0 and v_yoy == 0:
            continue
        yoy_pct = ((v_latest - v_yoy) / v_yoy * 100) if v_yoy > 0 else None
        qoq_pct = ((v_latest - v_prev) / v_prev * 100) if v_prev > 0 else None
        qoq_prev_pct = ((v_prev - v_prev2) / v_prev2 * 100) if v_prev2 > 0 else None
        accel_tag, accelerated, reversed_ = _qoq_accel(
            yoy_pct, qoq_pct, qoq_prev_pct)
        accel_map[key] = accelerated
        msg = up_msg if yoy_pct is not None and yoy_pct > 0 else down_msg
        yoy_str = (f'<span class="{"pos" if yoy_pct >= 0 else "neg"}">'
                   f'{"+" if yoy_pct >= 0 else ""}{yoy_pct:.0f}%</span>'
                   if yoy_pct is not None else "—")
        qoq_str = (f'<span class="{"pos" if qoq_pct >= 0 else "neg"}">'
                   f'{"+" if qoq_pct >= 0 else ""}{qoq_pct:.0f}%</span>'
                   if qoq_pct is not None else "—")
        items.append(
            f'<li><b>{label}</b> {v_latest / 1000:,.0f} 千元 '
            f'(YoY {yoy_str}, QoQ {qoq_str}) — {msg}{accel_tag}</li>'
        )

    # Overall total trend
    tot_latest = latest.get("_total", 0)
    tot_yoy = yoy.get("_total", 0)
    tot_prev = prev_q.get("_total", 0) if prev_q else 0
    tot_prev2 = prev2_q.get("_total", 0) if prev2_q else 0
    tot_yoy_pct = ((tot_latest - tot_yoy) / tot_yoy * 100) if tot_yoy > 0 else None
    tot_qoq_pct = ((tot_latest - tot_prev) / tot_prev * 100) if tot_prev > 0 else None
    tot_qoq_prev_pct = ((tot_prev - tot_prev2) / tot_prev2 * 100) if tot_prev2 > 0 else None
    _, tot_accel, _ = _qoq_accel(tot_yoy_pct, tot_qoq_pct, tot_qoq_prev_pct)
    # Strongest signals
    headline = ""
    fg = latest.get("finished_goods", 0)
    fg_yoy = yoy.get("finished_goods", 0)
    fg_yoy_pct = ((fg - fg_yoy) / fg_yoy * 100) if fg_yoy > 0 else 0
    wip = latest.get("work_in_progress", 0)
    wip_yoy = yoy.get("work_in_progress", 0)
    wip_yoy_pct = ((wip - wip_yoy) / wip_yoy * 100) if wip_yoy > 0 else 0
    raw = latest.get("raw_materials", 0)
    raw_yoy = yoy.get("raw_materials", 0)
    raw_yoy_pct = ((raw - raw_yoy) / raw_yoy * 100) if raw_yoy > 0 else 0
    # accel flags from per-item map
    wip_accel = accel_map.get("work_in_progress", False)
    raw_accel = accel_map.get("raw_materials", False)
    fg_accel = accel_map.get("finished_goods", False)

    def _amp(prefix_accel: bool) -> str:
        return "⚡ **加倍強化** — " if prefix_accel else ""

    # ── 營收交叉驗證：存貨雙升但營收沒跟上 → 庫存壓力警訊 ─────────────
    # 用 rev_yoy 與 rev_qoq 跟存貨 YoY/QoQ 比；若存貨 ↑↑ 但營收沒同步成長
    # → 「庫存壓力劇增 + 跌價損失 / 打庫存風險」
    rev_yoy_pct = rev_qoq_pct = None
    rev_pressure = False
    rev_warning_text = ""
    if inv_rows and len(inv_rows) >= 5:
        try:
            sorted_rows = sorted(inv_rows, key=lambda r: r.get("date", ""))
            r_latest = sorted_rows[-1].get("revenue", 0) or 0
            r_yoy = sorted_rows[-5].get("revenue", 0) or 0
            r_prev = sorted_rows[-2].get("revenue", 0) or 0
            if r_yoy > 0:
                rev_yoy_pct = (r_latest - r_yoy) / r_yoy * 100
            if r_prev > 0:
                rev_qoq_pct = (r_latest - r_prev) / r_prev * 100
            # 觸發條件：存貨 YoY > +10% 且 QoQ > +1% 且 (rev_yoy < inv_yoy-10pp 或 rev_yoy<0)
            if (tot_yoy_pct is not None and tot_yoy_pct > 10
                    and tot_qoq_pct is not None and tot_qoq_pct > 1
                    and rev_yoy_pct is not None
                    and (rev_yoy_pct < tot_yoy_pct - 10 or rev_yoy_pct < 0)):
                rev_pressure = True
                gap = tot_yoy_pct - rev_yoy_pct
                rev_warning_text = (
                    f"🔴 **警訊：庫存壓力劇增**（存貨 YoY +{tot_yoy_pct:.0f}% / "
                    f"QoQ +{tot_qoq_pct:.0f}% 雙升，但營收 YoY {'+' if rev_yoy_pct>=0 else ''}"
                    f"{rev_yoy_pct:.0f}% 沒跟上，差距 {gap:.0f}pp → "
                    f"庫存堆積中，注意未來跌價損失 / 打庫存風險）"
                )
        except Exception:
            pass

    if rev_pressure:
        headline = rev_warning_text
    elif wip_yoy_pct > 20 and raw_yoy_pct > 20 and fg_yoy_pct < 15:
        amp = _amp(wip_accel and raw_accel)
        headline = f"🟢 **強訊號：產能拉貨**（{amp}原料+在製大幅增加但製成品控制 → 客戶要貨積極，1-3 季內營收動能）"
    elif fg_yoy_pct > 25 and wip_yoy_pct < 10:
        amp = _amp(fg_accel)
        headline = f"🔴 **警訊：庫存堆積**（{amp}製成品大幅增加但在製品停滯 → 客戶 push-out / 出貨遲緩，毛利壓力）"
    elif wip_yoy_pct > 30:
        amp = _amp(wip_accel)
        headline = f"🟢 **強訊號：在製暴增**（{amp}在製品 YoY +{wip_yoy_pct:.0f}% → 預期未來 1-3 季營收大幅增長）"
    elif tot_yoy_pct and tot_yoy_pct < -15:
        amp = _amp(tot_accel)
        headline = f"🟡 **去化中**（{amp}整體存貨 YoY 大降 → 出貨好但要看新訂單能不能補上）"
    elif tot_yoy_pct and tot_yoy_pct > 30:
        amp = _amp(tot_accel)
        headline = f"🟡 **存貨快速擴大**（{amp}整體 YoY 大增，要分辨是好的備料還是堆積）"
    else:
        headline = "→ 存貨結構平穩，無明顯訊號"

    # Revenue cross-check display row
    rev_html = ""
    if rev_yoy_pct is not None or rev_qoq_pct is not None:
        ry = (f'<span class="{"pos" if rev_yoy_pct >= 0 else "neg"}">'
              f'{"+" if rev_yoy_pct >= 0 else ""}{rev_yoy_pct:.1f}%</span>'
              if rev_yoy_pct is not None else "—")
        rq = (f'<span class="{"pos" if rev_qoq_pct >= 0 else "neg"}">'
              f'{"+" if rev_qoq_pct >= 0 else ""}{rev_qoq_pct:.1f}%</span>'
              if rev_qoq_pct is not None else "—")
        gap_html = ""
        if rev_yoy_pct is not None and tot_yoy_pct is not None:
            gap = tot_yoy_pct - rev_yoy_pct
            if gap > 10:
                gap_html = (f' &nbsp;<span style="color:#c00">⚠ 存貨領先營收 '
                            f'{gap:.0f}pp，庫存堆積中</span>')
            elif gap < -10:
                gap_html = (f' &nbsp;<span style="color:#0a0">✓ 營收領先存貨 '
                            f'{-gap:.0f}pp，去化順暢</span>')
        rev_html = (f'<p><b>📊 營收交叉:</b> YoY {ry} / QoQ {rq}{gap_html}</p>')

    return f"""
<section>
  <h3>💡 會計 + 產業視角解讀</h3>
  <p><b>整體存貨 YoY:</b>
     <span class="{"pos" if tot_yoy_pct and tot_yoy_pct >= 0 else "neg"}">
     {("+" if tot_yoy_pct >= 0 else "") + f"{tot_yoy_pct:.1f}%" if tot_yoy_pct is not None else "—"}</span>
     ({dates[-5][:7]} → {dates[-1][:7]})</p>
  {rev_html}
  <p style="font-size:1.05em; margin:8px 0;">{headline}</p>
  <h4 style="margin-top:14px; font-size:0.95em;">逐項解讀：</h4>
  <ul class="commentary-list" style="line-height:1.7;">
    {''.join(items)}
  </ul>
  <p class="small" style="margin-top:10px;">
    判定邏輯：<b>YoY 為主</b>（扣季節性）+ <b>QoQ 連 2 季同向</b>加倍強化。
    若兩季 QoQ 都跟 YoY 同方向 → 標 <b style="color:#c00">⚡ 加倍強化</b>（趨勢正在加速）；
    若兩季 QoQ 都跟 YoY 反向 → 標 <span style="color:#888">↻ YoY 訊號減弱</span>（轉折中，YoY 還沒翻但動能已轉）。
    QoQ 變動 &lt;1% 視為持平不計入。<br>
    原料↑=備料 (1-2 季 leading) / 在製品↑=訂單在線 (1-3 月最強 leading) /
    製成品↑=⚠ 出貨壓力 (lagging warning) / 在途↑=物流增加。
    產業差異：純代工 (e.g. 2330/2317) 看在製品; PCB/組裝 (e.g. 2313) 看製成品堆積;
    電源/工業 (e.g. 6282) 看原料 vs 製成品比例。
  </p>
</section>
"""


def _breakdown_section_html(series: dict | None,
                             inv_rows: list[dict] | None = None) -> str:
    """Render the optional 5-item inventory breakdown (stacked bar chart +
    table). Used by _render_inventory_page when ?breakdown=1 was provided.
    Returns '' if no series given.
    """
    if not series:
        return ""
    if "_error" in series:
        return (f'<div class="error">⚠ 拆分載入失敗: '
                f'{html_lib.escape(series["_error"])}</div>')
    # Standardized category order + zh labels (for display + chart legend)
    cat_order = [
        ("raw_materials", "原料", "#3b82f6"),
        ("work_in_progress", "在製品", "#10b981"),
        ("semi_finished", "半成品", "#f59e0b"),
        ("finished_goods", "製成品", "#ef4444"),
        ("byproducts", "副產品", "#8b5cf6"),
        ("merchandise", "商品", "#ec4899"),
        ("materials_supplies", "物料及零件", "#6b7280"),
        ("in_transit", "在途存貨", "#14b8a6"),
    ]
    dates = sorted(series.keys())
    if not dates:
        return ('<section><h3>📦 拆分明細</h3>'
                '<p class="empty">未取得拆分資料 (公司可能 IFRSs 申報沒拆 / '
                '或 MOPS 下載失敗)。</p></section>')
    # Find which categories actually appear (non-zero)
    used_cats = []
    for key, label, color in cat_order:
        if any(series[d].get(key, 0) > 0 for d in dates):
            used_cats.append((key, label, color))
    # Also catch any "other:" keys (uncategorized) for transparency.
    # Exclude *_label suffix entries (those carry the raw 中文 string).
    other_keys = set()
    for d in dates:
        for k, v in series[d].items():
            if k.startswith("other:") and not k.endswith("_label") \
                    and isinstance(v, (int, float)) and v > 0:
                other_keys.add(k)
    for k in sorted(other_keys):
        label = k.split(":", 1)[1][:8]
        used_cats.append((k, label, "#a3a3a3"))

    # Build chart datasets
    datasets = []
    for key, label, color in used_cats:
        vals = [round(series[d].get(key, 0) / 1000, 0) for d in dates]
        datasets.append({
            "label": label, "data": vals,
            "backgroundColor": color, "borderColor": color,
            "borderWidth": 1, "stack": "stack1",
        })
    chart_data = json.dumps({
        "labels": dates, "datasets": datasets,
    }, ensure_ascii=False)

    # Build date → revenue / inv_rev_pct / dsi map from inv_rows
    rev_map: dict[str, float] = {}
    ratio_map: dict[str, float | None] = {}
    dsi_map: dict[str, float | None] = {}
    if inv_rows:
        for r in inv_rows:
            d = r.get("date")
            if not d:
                continue
            rev_map[d] = float(r.get("revenue", 0) or 0)
            ratio_map[d] = r.get("inv_rev_pct")
            dsi_map[d] = r.get("dsi_days")

    # Table rows
    table_rows = []
    for d in dates:
        e = series[d]
        cells = [f'<td>{d}</td>']
        for key, label, _ in used_cats:
            v = e.get(key, 0)
            cls = "num" if v else "num muted"
            cells.append(f'<td class="{cls}">{v / 1000:,.0f}</td>' if v
                          else '<td class="num muted">—</td>')
        total = e.get("_total", 0)
        cells.append(f'<td class="num"><b>{total / 1000:,.0f}</b></td>')
        # Revenue + inv/revenue ratio
        rev = rev_map.get(d, 0)
        ratio = ratio_map.get(d)
        if rev > 0:
            cells.append(f'<td class="num">{rev / 1000:,.0f}</td>')
        else:
            cells.append('<td class="num muted">—</td>')
        if ratio is not None:
            # 存貨銷售比顏色：>100% 紅 (庫存高於季營收) / 50-100% 中 / <50% 綠
            color = ("#c00" if ratio > 100 else
                     "#a60" if ratio > 50 else "#0a0")
            cells.append(
                f'<td class="num" style="color:{color}">{ratio:.0f}%</td>')
        else:
            cells.append('<td class="num muted">—</td>')
        # DSI (Days Sales of Inventory) — 跨季節更穩定
        dsi = dsi_map.get(d)
        if dsi is not None:
            dsi_color = ("#c00" if dsi > 90 else
                         "#a60" if dsi > 60 else "#0a0")
            cells.append(
                f'<td class="num" style="color:{dsi_color}">{dsi:.0f}</td>')
        else:
            cells.append('<td class="num muted">—</td>')
        table_rows.append('<tr>' + ''.join(cells) + '</tr>')

    th_cats = ''.join(
        f'<th class="num">{label} (千元)</th>' for _, label, _ in used_cats)

    commentary = _breakdown_commentary(series, inv_rows=inv_rows)
    return f"""
<section>
  <h3>📦 拆分明細 (從 MOPS 財報 PDF 解析，{len(dates)} 個季底)</h3>
  <canvas id="breakdown-chart" height="140"></canvas>
  <table class="report-table" style="margin-top:12px;">
    <thead><tr>
      <th>季底</th>
      {th_cats}
      <th class="num">存貨總額 (千元)</th>
      <th class="num">季營收 (千元)</th>
      <th class="num">存貨/營收</th>
      <th class="num">DSI 天</th>
    </tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
  <p class="small">資料源：公開資訊觀測站 IFRSs 合併財報 (附註十二 / 存貨明細)。
     不同公司揭露科目不同（半導體：原料/在製品/製成品/物料及零件；
     傳產：原料/在製品/成品/商品 etc）。<br>
     <b>存貨/營收 (存銷比) = 期末存貨 / 該季營收</b>；
     <span style="color:#0a0">&lt;50%</span> 健康 /
     <span style="color:#a60">50-100%</span> 偏高 /
     <span style="color:#c00">&gt;100%</span> 庫存堆積 (一季賣不完)。
     單季營收當分母會被淡旺季干擾。<br>
     <b>DSI 天 (Days Sales of Inventory) = 365 / 週轉率</b>，
     週轉率 = 年化 COGS / 平均存貨；幾天能賣完，跨產業 / 跨季節更穩定可比。
     <span style="color:#0a0">&lt;60 天</span> /
     <span style="color:#a60">60-90 天</span> /
     <span style="color:#c00">&gt;90 天</span> 為通用門檻
     (半導體常見 60-90 偏正常；零售業 30 天就嫌多)。</p>
</section>
{commentary}
<script>
  (function() {{
    const D = {chart_data};
    new Chart(document.getElementById('breakdown-chart'), {{
      type: 'bar',
      data: D,
      options: {{
        responsive: true,
        interaction: {{ mode:'index', intersect:false }},
        scales: {{
          x: {{ stacked: true }},
          y: {{ stacked: true,
                ticks: {{ callback: v => v >= 1e6 ? (v/1e6).toFixed(1)+'B'
                                          : v >= 1e3 ? (v/1e3).toFixed(0)+'M'
                                          : v }},
                title: {{ display:true, text:'存貨 (千元)' }} }}
        }}
      }}
    }});
  }})();
</script>"""


def _render_inventory_page(code: str = "", years: int = 5,
                            rows: list[dict] | None = None,
                            name: str = "", error: str = "",
                            breakdown_series: dict | None = None,
                            bd_years: int = 3) -> str:
    """Web page: 存貨歷史 + 衍生指標 for a stock, with Chart.js charts."""
    code_attr = html_lib.escape(code or "")
    body = ""
    if error:
        body = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif rows is not None and not rows:
        code_esc = html_lib.escape(code)
        body = (
            '<div class="empty">'
            f'<p><b>⚠ {code_esc} {html_lib.escape(name)} 抓不到存貨資料</b></p>'
            '<p>可能股票代號錯誤、太新（&lt;1 季）或下市。FinMind '
            'TaiwanStockBalanceSheet 找不到 Inventories 項目。</p>'
            '</div>'
        )
    elif rows:
        rows_html = []
        labels, inv_vals, qoq_vals, yoy_vals = [], [], [], []
        turnover_vals, dsi_vals, inv_rev_vals = [], [], []
        for r in rows:
            inv = r["inventory"]
            qoq = r.get("qoq_pct")
            yoy = r.get("yoy_pct")
            to = r.get("turnover")
            dsi = r.get("dsi_days")
            ir = r.get("inv_rev_pct")
            qoq_cls = ("pos" if qoq is not None and qoq > 0
                       else ("neg" if qoq is not None and qoq < 0 else ""))
            yoy_cls = ("pos" if yoy is not None and yoy > 0
                       else ("neg" if yoy is not None and yoy < 0 else ""))
            qoq_str = (f"{'+' if qoq >= 0 else ''}{qoq:.1f}%"
                       if qoq is not None else "—")
            yoy_str = (f"{'+' if yoy >= 0 else ''}{yoy:.1f}%"
                       if yoy is not None else "—")
            to_str = f"{to:.2f}" if to is not None else "—"
            dsi_str = f"{dsi:.0f}" if dsi is not None else "—"
            ir_str = f"{ir:.1f}%" if ir is not None else "—"
            rows_html.append(
                f'<tr>'
                f'<td>{r["date"]}</td>'
                f'<td class="num"><b>{inv / 1000:,.0f}</b></td>'
                f'<td class="num {qoq_cls}">{qoq_str}</td>'
                f'<td class="num {yoy_cls}">{yoy_str}</td>'
                f'<td class="num">{to_str}</td>'
                f'<td class="num">{dsi_str}</td>'
                f'<td class="num">{ir_str}</td>'
                f'</tr>'
            )
            labels.append(r["date"])
            inv_vals.append(round(inv / 1000, 0))  # 千元
            qoq_vals.append(round(qoq, 2) if qoq is not None else None)
            yoy_vals.append(round(yoy, 2) if yoy is not None else None)
            turnover_vals.append(round(to, 2) if to is not None else None)
            dsi_vals.append(round(dsi, 0) if dsi is not None else None)
            inv_rev_vals.append(round(ir, 2) if ir is not None else None)
        cagr_str = ""
        if len(rows) >= 2 and rows[0]["inventory"] > 0:
            span_years = (
                (datetime.strptime(rows[-1]["date"], "%Y-%m-%d")
                 - datetime.strptime(rows[0]["date"], "%Y-%m-%d")).days
                / 365.25
            )
            if span_years > 0:
                cagr = ((rows[-1]["inventory"] / rows[0]["inventory"])
                        ** (1 / span_years) - 1) * 100
                cagr_cls = "pos" if cagr > 0 else "neg"
                cagr_str = (f'<p>📈 存貨 CAGR: <span class="{cagr_cls}">'
                             f'<b>{cagr:+.1f}%</b></span> '
                             f'({rows[0]["date"]} → {rows[-1]["date"]})</p>')
        chart_data = json.dumps({
            "labels": labels, "inv": inv_vals,
            "qoq": qoq_vals, "yoy": yoy_vals,
            "turnover": turnover_vals, "dsi": dsi_vals,
            "inv_rev": inv_rev_vals,
        }, ensure_ascii=False)
        body = f"""
<section class="header-card">
  <h2>{_esc(code)} {_esc(name)} 存貨歷史 (近 {years} 年 / {len(rows)} 季)</h2>
  {cagr_str}
</section>

<section>
  <h3>📈 存貨總額 + QoQ/YoY 變化率</h3>
  <canvas id="inv-chart" height="120"></canvas>
</section>

<section>
  <h3>⚙ 存貨週轉率 (年化) + DSI 存貨天數</h3>
  <canvas id="eff-chart" height="120"></canvas>
</section>

<section>
  <h3>📊 季度明細</h3>
  <table class="report-table">
    <thead><tr>
      <th>季底</th>
      <th class="num">存貨 (千元)</th>
      <th class="num">QoQ%</th>
      <th class="num">YoY%</th>
      <th class="num">週轉率*</th>
      <th class="num">DSI (天)</th>
      <th class="num">存貨/季營收</th>
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  <p class="small">* 週轉率 = 年化 COGS / 平均存貨；DSI = 365/週轉率；
     存貨/營收 = 期末存貨/該季營收。<br>
     存貨 ↑ 通常是出貨壓力或拉貨；↓ 表示去化順暢。
     週轉率 ↑ + DSI ↓ = 庫存效率提升 (景氣轉好)。</p>
  <p class="small">原料 / 在製品 / 半成品 / 成品 / 副產品 等項目拆分（從 MOPS 財報 PDF 解析）：</p>
  <form method="get" action="/inventory" class="small" style="margin:6px 0 12px">
    <input type="hidden" name="code" value="{code_attr}">
    <input type="hidden" name="years" value="{years}">
    <input type="hidden" name="breakdown" value="1">
    <label for="bd_years">拆分明細回看:</label>
    <select id="bd_years" name="bd_years">
      <option value="2"{' selected' if bd_years==2 else ''}>2 年 (~8 季，約 8 秒)</option>
      <option value="3"{' selected' if bd_years==3 else ''}>3 年 (~12 季，約 12 秒)</option>
      <option value="5"{' selected' if bd_years==5 else ''}>5 年 (~20 季，約 20 秒)</option>
      <option value="8"{' selected' if bd_years==8 else ''}>8 年 (~32 季，約 30 秒)</option>
    </select>
    <button type="submit">載入拆分</button>
  </form>
</section>
{_breakdown_section_html(breakdown_series, inv_rows=rows)}

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
  const D = {chart_data};
  const fmtThousand = v => v >= 1e6 ? (v/1e6).toFixed(1)+'B'
                          : v >= 1e3 ? (v/1e3).toFixed(1)+'M'
                          : v.toFixed(0);
  new Chart(document.getElementById('inv-chart'), {{
    type: 'bar',
    data: {{
      labels: D.labels,
      datasets: [
        {{ type:'bar', label:'存貨 (千元)', yAxisID:'y',
           data: D.inv, backgroundColor:'rgba(0,102,204,0.4)',
           borderColor:'rgba(0,102,204,1)', borderWidth:1, order:2 }},
        {{ type:'line', label:'QoQ %', yAxisID:'y1',
           data: D.qoq, borderColor:'#c30', backgroundColor:'#c30',
           tension:0.2, fill:false, pointRadius:3, order:1 }},
        {{ type:'line', label:'YoY %', yAxisID:'y1',
           data: D.yoy, borderColor:'#060', backgroundColor:'#060',
           borderDash:[4,4], tension:0.2, fill:false, pointRadius:3, order:0 }},
      ]
    }},
    options: {{
      responsive: true, interaction:{{ mode:'index', intersect:false }},
      scales: {{
        y: {{ position:'left',
              ticks:{{ callback: v => fmtThousand(v) }},
              title:{{ display:true, text:'存貨 (千元)' }} }},
        y1: {{ position:'right',
               ticks:{{ callback: v => v + '%' }},
               grid:{{ drawOnChartArea:false }},
               title:{{ display:true, text:'變化率 %' }} }}
      }}
    }}
  }});
  new Chart(document.getElementById('eff-chart'), {{
    type: 'line',
    data: {{
      labels: D.labels,
      datasets: [
        {{ label:'存貨週轉率 (年化)', yAxisID:'y',
           data: D.turnover, borderColor:'#0066cc',
           backgroundColor:'rgba(0,102,204,0.1)', fill:true,
           tension:0.2, pointRadius:3 }},
        {{ label:'DSI 存貨天數', yAxisID:'y1',
           data: D.dsi, borderColor:'#c30',
           backgroundColor:'#c30',
           tension:0.2, fill:false, pointRadius:3 }},
        {{ label:'存貨/營收 %', yAxisID:'y1',
           data: D.inv_rev, borderColor:'#060',
           backgroundColor:'#060', borderDash:[4,4],
           tension:0.2, fill:false, pointRadius:3 }},
      ]
    }},
    options: {{
      responsive: true, interaction:{{ mode:'index', intersect:false }},
      scales: {{
        y: {{ position:'left',
              title:{{ display:true, text:'週轉率 (次/年)' }} }},
        y1: {{ position:'right',
               grid:{{ drawOnChartArea:false }},
               title:{{ display:true, text:'天數 / %' }} }}
      }}
    }}
  }});
</script>"""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>存貨歷史 — 台股單檔</title>
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
  section h3 {{ margin: 0 0 8px 0; font-size: 1.05em; color: #444; }}
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
  <a href="/inventory">📦 存貨</a>
  <a href="/shareholders">👥 前十大股東</a>
</nav>
<h1>📦 存貨歷史 + 衍生指標</h1>

<form method="get" action="/inventory">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 2330" autofocus required>
  <label for="years">回看年數:</label>
  <input type="number" id="years" name="years" value="{years}" min="1" max="10">
  <button type="submit">查詢</button>
</form>
<p class="small">💡 存貨 ↑↓ 是出貨景氣 leading indicator。配合週轉率 + DSI 看效率。
   範例：<a href="/inventory?code=2330">2330 台積電</a> ·
   <a href="/inventory?code=2317">2317 鴻海</a> ·
   <a href="/inventory?code=2454">2454 聯發科</a> ·
   <a href="/inventory?code=3008">3008 大立光</a></p>

{body}
</body>
</html>"""


@app.route("/inventory")
def inventory():
    import tw_inventory
    code = (request.args.get("code") or "").strip()
    breakdown = request.args.get("breakdown") == "1"
    try:
        years = int(request.args.get("years") or "5")
        years = max(1, min(years, 10))
    except ValueError:
        years = 5
    if not code:
        return _render_inventory_page()
    try:
        rows = tw_inventory.fetch_inventory_series(code, years=years)
        rows = tw_inventory.annotate(rows)
    except Exception as e:
        return _render_inventory_page(
            code=code, years=years, error=f"{type(e).__name__}: {e}")
    name = tw_inventory._zh_name(code)
    breakdown_series = None
    if breakdown and rows:
        try:
            bd_years = int(request.args.get("bd_years") or "3")
            bd_years = max(1, min(bd_years, 10))
        except ValueError:
            bd_years = 3
        try:
            import mops_pdf
            breakdown_series = mops_pdf.fetch_breakdown_series(
                code, years=bd_years)
        except Exception as e:
            breakdown_series = {"_error": f"{type(e).__name__}: {e}"}
    bd_years_val = 3
    if breakdown and rows:
        try:
            bd_years_val = max(1, min(int(request.args.get("bd_years") or "3"), 10))
        except ValueError:
            bd_years_val = 3
    return _render_inventory_page(code=code, years=years,
                                   rows=rows, name=name,
                                   breakdown_series=breakdown_series,
                                   bd_years=bd_years_val)


# 集保戶股權分散表 tier → 張 group mapping (tiers are in 股; 1 張 = 1000 股)
_DIST_GROUPS = {
    "散戶 (<10張)": ["1-999", "1,000-5,000", "5,001-10,000"],
    "中實戶 (10-400張)": ["10,001-15,000", "15,001-20,000", "20,001-30,000",
                          "30,001-40,000", "40,001-50,000", "50,001-100,000",
                          "100,001-200,000", "200,001-400,000"],
    "大戶 (400-1000張)": ["400,001-600,000", "600,001-800,000",
                          "800,001-1,000,000"],
    "千張大戶 (>1000張)": ["more than 1,000,001"],
}


def _holding_distribution_data(code: str, weeks: int = 16) -> dict:
    """Fetch 集保大戶分布 (TDCC weekly distribution). Returns
    {latest_date, latest_tiers, latest_groups, trend} or {"error": ...}."""
    import tw_inventory
    import finmind_client
    from datetime import datetime, timedelta
    token = tw_inventory._get_token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    end = datetime.now()
    start = end - timedelta(days=weeks * 7 + 21)
    try:
        rows = finmind_client.fetch_holding_distribution(
            code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), token)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    if not rows:
        return {"error": "集保無資料"}

    by_date: dict[str, dict] = {}
    for r in rows:
        lvl = r.get("HoldingSharesLevel", "")
        if lvl in ("total", "差異數調整（說明4）"):
            continue
        by_date.setdefault(r["date"], {})[lvl] = {
            "people": r.get("people", 0),
            "percent": r.get("percent", 0.0),
            "unit": r.get("unit", 0),  # 股數 (= 張數 × 1000)
        }
    dates = sorted(by_date.keys())
    if not dates:
        return {"error": "集保無有效分級資料"}

    def group_stats(tiers: dict) -> dict:
        # Per group: pct (持股比例), lots (張數 = 股數/1000), people (人數)
        out = {}
        for g, levels in _DIST_GROUPS.items():
            pct = sum(tiers.get(L, {}).get("percent", 0.0) for L in levels)
            shares = sum(tiers.get(L, {}).get("unit", 0) for L in levels)
            ppl = sum(tiers.get(L, {}).get("people", 0) for L in levels)
            out[g] = {"pct": round(pct, 2), "lots": round(shares / 1000),
                      "people": ppl}
        return out

    trend = [{"date": d, "groups": group_stats(by_date[d])} for d in dates]
    latest = dates[-1]
    tier_order = [L for g in _DIST_GROUPS.values() for L in g]
    latest_tiers = [{"level": L, **by_date[latest][L]}
                    for L in tier_order if L in by_date[latest]]
    return {"latest_date": latest, "latest_tiers": latest_tiers,
            "latest_groups": group_stats(by_date[latest]), "trend": trend}


def _holding_distribution_html(dist: dict | None) -> str:
    """Render 集保大戶分布 section: group summary + tier table + 2 charts."""
    if not dist:
        return ""
    if dist.get("error"):
        return (f'<section><h3>📊 集保大戶分布</h3>'
                f'<p class="small">⚠ 無法載入：{_esc(dist["error"])}</p></section>')
    groups = dist["latest_groups"]
    g_big = groups["千張大戶 (>1000張)"]["pct"]
    g_retail = groups["散戶 (<10張)"]["pct"]
    # group summary cards (% + 張數 + 人數)
    cards = "".join(
        f'<div style="flex:1;min-width:140px;background:#fafafa;border-radius:6px;'
        f'padding:10px 12px;text-align:center;">'
        f'<div style="font-size:0.82em;color:#666;">{_esc(g)}</div>'
        f'<div style="font-size:1.4em;font-weight:700;color:'
        f'{"#c30" if "千張" in g else "#060" if "散戶" in g else "#444"};">'
        f'{st["pct"]:.2f}%</div>'
        f'<div style="font-size:0.78em;color:#888;">{st["lots"]:,} 張 · '
        f'{st["people"]:,} 人</div></div>'
        for g, st in groups.items())
    # tier table
    trows = "".join(
        f'<tr><td>{_esc(t["level"])}</td>'
        f'<td class="num">{t["people"]:,}</td>'
        f'<td class="num">{round(t["unit"]/1000):,}</td>'
        f'<td class="num">{t["percent"]:.2f}%</td></tr>'
        for t in dist["latest_tiers"])
    trend = dist["trend"]
    labels = json.dumps([t["date"][5:] for t in trend])
    big_series = json.dumps([t["groups"]["千張大戶 (>1000張)"]["pct"] for t in trend])
    retail_series = json.dumps([t["groups"]["散戶 (<10張)"]["pct"] for t in trend])
    big_holder_series = json.dumps([t["groups"]["大戶 (400-1000張)"]["pct"] for t in trend])
    tier_labels = json.dumps([t["level"] for t in dist["latest_tiers"]])
    tier_pcts = json.dumps([t["percent"] for t in dist["latest_tiers"]])

    # Weekly group table (most recent first): per group show %/張數/人數, plus
    # week-over-week Δ on 千張大戶's 張數 (the most actionable accumulation
    # signal). Grouped 2-row header; wide table scrolls horizontally on mobile.
    GORDER = ["千張大戶 (>1000張)", "大戶 (400-1000張)",
              "中實戶 (10-400張)", "散戶 (<10張)"]
    wk_rows = []
    rev = list(reversed(trend))  # newest first
    for idx, t in enumerate(rev):
        g = t["groups"]
        big_lots = g["千張大戶 (>1000張)"]["lots"]
        prev_lots = (rev[idx + 1]["groups"]["千張大戶 (>1000張)"]["lots"]
                     if idx + 1 < len(rev) else None)
        if prev_lots is None:
            delta_html = '<td class="num muted">—</td>'
        else:
            d = big_lots - prev_lots
            color = "#c30" if d > 0 else "#060" if d < 0 else "#999"
            delta_html = (f'<td class="num" style="color:{color}">'
                          f'{"+" if d >= 0 else ""}{d:,} 張</td>')
        cells = [f'<td>{_esc(t["date"])}</td>']
        for gi, gname in enumerate(GORDER):
            st = g[gname]
            pc = ("#c30" if "千張" in gname else
                  "#060" if "散戶" in gname else "#444")
            cells.append(
                f'<td class="num" style="color:{pc};font-weight:600">'
                f'{st["pct"]:.2f}%</td>'
                f'<td class="num">{st["lots"]:,}</td>'
                f'<td class="num">{st["people"]:,}</td>')
            if gi == 0:  # 千張大戶 Δ right after its block
                cells.append(delta_html)
        wk_rows.append("<tr>" + "".join(cells) + "</tr>")
    weekly_table = "".join(wk_rows)
    return f"""
<section>
  <h3>📊 集保大戶分布 (TDCC 每週，最新 {_esc(dist["latest_date"])})</h3>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">{cards}</div>
  <canvas id="dist-trend" height="150"></canvas>
  <p class="small" style="margin:6px 0 14px;">
    🔴 千張大戶 {g_big:.2f}% / 🟢 散戶(&lt;10張) {g_retail:.2f}% 趨勢 —
    千張大戶 ↑ + 散戶 ↓ = 籌碼集中 (偏多)；反之 = 籌碼分散。</p>
  <canvas id="dist-bar" height="130"></canvas>
  <h4 style="margin:18px 0 6px;font-size:0.95em;color:#444;">📅 各群組週變化 (近 {len(trend)} 週)</h4>
  <div style="overflow-x:auto;">
  <table class="report-table" style="white-space:nowrap;">
    <thead>
    <tr>
      <th rowspan="2">週 (週五)</th>
      <th class="num" colspan="3" style="border-left:2px solid #ddd;color:#c30">千張大戶 (&gt;1000張)</th>
      <th class="num" rowspan="2" style="color:#c30">千張張數Δ</th>
      <th class="num" colspan="3" style="border-left:2px solid #ddd">大戶 (400-1000張)</th>
      <th class="num" colspan="3" style="border-left:2px solid #ddd">中實戶 (10-400張)</th>
      <th class="num" colspan="3" style="border-left:2px solid #ddd;color:#060">散戶 (&lt;10張)</th>
    </tr>
    <tr>
      <th class="num" style="border-left:2px solid #ddd">%</th><th class="num">張數</th><th class="num">人數</th>
      <th class="num" style="border-left:2px solid #ddd">%</th><th class="num">張數</th><th class="num">人數</th>
      <th class="num" style="border-left:2px solid #ddd">%</th><th class="num">張數</th><th class="num">人數</th>
      <th class="num" style="border-left:2px solid #ddd">%</th><th class="num">張數</th><th class="num">人數</th>
    </tr>
    </thead>
    <tbody>{weekly_table}</tbody>
  </table>
  </div>
  <p class="small" style="margin:6px 0 14px;">每組顯示 持股比例% / 張數 / 人數。
    千張張數Δ = 千張大戶持股張數的週變化；連續正值 = 大戶持續吸籌、籌碼集中 (偏多)；
    連續負值 = 大戶減碼、籌碼分散。</p>
  <h4 style="margin:18px 0 6px;font-size:0.95em;color:#444;">📋 最新一週各級距明細 ({_esc(dist["latest_date"])})</h4>
  <table class="report-table">
    <thead><tr><th>持股級距 (股)</th><th class="num">人數</th>
      <th class="num">張數</th><th class="num">持股比例</th></tr></thead>
    <tbody>{trows}</tbody>
  </table>
  <p class="small">資料來源：集保結算所 (TDCC) 股權分散表，每週五更新。
    級距以「股」計 (÷1000 = 張)。千張大戶 = 持股 &gt; 1,000,000 股 (1000 張)。</p>
</section>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  new Chart(document.getElementById('dist-trend'), {{
    type:'line',
    data:{{labels:{labels},datasets:[
      {{label:'千張大戶 %',data:{big_series},borderColor:'#c30',
        backgroundColor:'rgba(204,51,0,.1)',tension:.2,yAxisID:'y'}},
      {{label:'大戶 400-1000張 %',data:{big_holder_series},borderColor:'#e8a',
        borderDash:[4,3],tension:.2,yAxisID:'y'}},
      {{label:'散戶 <10張 %',data:{retail_series},borderColor:'#060',
        backgroundColor:'rgba(0,102,0,.08)',tension:.2,yAxisID:'y'}}
    ]}},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
      plugins:{{title:{{display:true,text:'籌碼集中度趨勢 (千張大戶 vs 散戶)'}}}},
      scales:{{y:{{title:{{display:true,text:'持股比例 %'}}}}}}}}
  }});
  new Chart(document.getElementById('dist-bar'), {{
    type:'bar',
    data:{{labels:{tier_labels},datasets:[
      {{label:'最新持股比例 %',data:{tier_pcts},backgroundColor:'#0066cc'}}
    ]}},
    options:{{responsive:true,plugins:{{legend:{{display:false}},
      title:{{display:true,text:'最新各級距持股分布'}}}},
      scales:{{x:{{ticks:{{maxRotation:60,minRotation:45,font:{{size:9}}}}}},
        y:{{title:{{display:true,text:'%'}}}}}}}}
  }});
}})();
</script>"""


def _history_commentary(history: dict) -> str:
    """Auto-generate plain-language 解讀 bullets from the N-year matrix:
    biggest accumulator / reducer / new entrants / exits / steady holders /
    volatile holders. Returns an HTML box, or '' if nothing notable."""
    years = history.get("years", [])
    rows = history.get("rows", [])
    if len(years) < 2 or not rows:
        return ""
    ynew, yold = years[-1], years[0]

    def stats(r):
        by = r["by_year"]
        pres = [y for y in years if y in by]
        vals = [by[y] for y in pres]
        first, last = by[pres[0]], by[pres[-1]]
        return {
            "name": r["name"], "by": by, "pres": pres,
            "first": first, "last": last, "latest": r["latest"],
            "delta": (r["latest"] - first) if r["latest"] is not None else None,
            "vol": (max(vals) - min(vals)) if len(vals) >= 2 else 0.0,
            "peak": max(vals), "peak_y": pres[vals.index(max(vals))],
        }
    S = [stats(r) for r in rows]
    inq = [s for s in S if s["latest"] is not None]   # in newest year
    bullets = []

    # biggest accumulator (positive delta, in newest year)
    acc = [s for s in inq if s["delta"] is not None and s["delta"] >= 0.5]
    if acc:
        b = max(acc, key=lambda s: s["delta"])
        bullets.append(
            f'🔴 <b>最大買盤</b>：{_esc(b["name"])} '
            f'{b["first"]:.2f}%→{b["last"]:.2f}%（{yold}→{ynew} '
            f'<span style="color:#c30">+{b["delta"]:.2f}pp</span>），期間持續加碼。')

    # biggest reducer still on the list
    red = [s for s in inq if s["delta"] is not None and s["delta"] <= -0.5]
    if red:
        b = min(red, key=lambda s: s["delta"])
        bullets.append(
            f'🟢 <b>最大減持（仍在榜）</b>：{_esc(b["name"])} '
            f'{b["first"]:.2f}%→{b["last"]:.2f}%'
            f'（<span style="color:#060">{b["delta"]:.2f}pp</span>）。')

    # new entrants: in newest year, absent in oldest
    newcomers = [s for s in inq if yold not in s["by"]
                 and min(s["pres"]) == ynew]
    if newcomers:
        names = "、".join(f'{_esc(s["name"])}（{s["last"]:.2f}%）'
                          for s in sorted(newcomers, key=lambda s: -s["last"])[:4])
        bullets.append(f'★ <b>{ynew} 年新進榜</b>：{names}。')

    # notable exits: gone by newest year, had a meaningful peak (>=2%)
    exits = [s for s in S if s["latest"] is None and s["peak"] >= 2.0]
    if exits:
        names = "、".join(
            f'{_esc(s["name"])}（{s["peak_y"]} 年曾 {s["peak"]:.2f}%）'
            for s in sorted(exits, key=lambda s: -s["peak"])[:4])
        bullets.append(f'⬇ <b>已退榜（曾為大股東）</b>：{names}。')

    # steady holders: present all years, low volatility
    steady = [s for s in inq if len(s["pres"]) == len(years) and s["vol"] <= 0.15]
    if steady:
        names = "、".join(f'{_esc(s["name"])}（≈{s["last"]:.2f}%）'
                          for s in sorted(steady, key=lambda s: -s["last"])[:5])
        bullets.append(f'⚓ <b>長期穩定（鐵桿）</b>：{names}。')

    # volatile: big swing, peak not at an endpoint (進出明顯)
    volatile = [s for s in S if s["vol"] >= 1.5
                and s["peak_y"] not in (yold, ynew)]
    if volatile:
        b = max(volatile, key=lambda s: s["vol"])
        bullets.append(
            f'🔄 <b>大進大出</b>：{_esc(b["name"])} '
            f'{b["peak_y"]} 年衝到 {b["peak"]:.2f}% 後又回落，部位不穩定。')

    if not bullets:
        return ""
    lis = "".join(f'<li style="margin:4px 0;line-height:1.6">{b}</li>'
                  for b in bullets)
    return (f'<div style="background:#f7faff;border:1px solid #d6e4f5;'
            f'border-radius:6px;padding:10px 16px;margin:12px 0;">'
            f'<b style="color:#0066cc">💡 籌碼變化解讀（自動產生）</b>'
            f'<ul style="margin:6px 0 2px;padding-left:20px">{lis}</ul></div>')


def _shareholders_history_html(history: dict | None, code: str,
                                hist_years: int) -> str:
    """Render the multi-year 前十大股東 matrix (holder × year, pct cells)."""
    code_esc = html_lib.escape(code)
    # toggle / year selector form
    opts = "".join(
        f'<option value="{y}"{" selected" if y == hist_years else ""}>{y} 年</option>'
        for y in (3, 5, 8, 10))
    form = f"""
<section>
  <h3>📅 前十大股東 N 年變化</h3>
  <form method="get" action="/shareholders" class="small" style="margin:4px 0">
    <input type="hidden" name="code" value="{code_esc}">
    <input type="hidden" name="history" value="1">
    <label>回看年數:
      <select name="hist_years">{opts}</select></label>
    <button type="submit">載入 N 年變化</button>
    <span class="muted">（從各年度 MOPS 年報 F17 表解析，第一次約每年 3 秒）</span>
  </form>
"""
    if history is None:
        return form + "</section>"
    if history.get("error"):
        return form + (f'<p class="small">⚠ {html_lib.escape(history["error"])}'
                       f'</p></section>')
    years = history.get("years", [])
    rows = history.get("rows", [])
    if not years or not rows:
        return form + '<p class="small">查無多年度資料。</p></section>'

    ynew, yold = years[-1], years[0]
    th = "".join(f'<th class="num">{y}年</th>' for y in years)
    body_rows = []
    for r in rows:
        by = r["by_year"]
        cells = []
        for y in years:
            if y in by:
                cells.append(f'<td class="num">{by[y]:.2f}%</td>')
            else:
                cells.append('<td class="num muted">—</td>')
        # trend arrow: newest vs oldest available value for this holder
        present = [y for y in years if y in by]
        trend = ""
        if len(present) >= 2:
            delta = by[present[-1]] - by[present[0]]
            if delta > 0.05:
                trend = f'<span style="color:#c30">▲ +{delta:.2f}</span>'
            elif delta < -0.05:
                trend = f'<span style="color:#060">▼ {delta:.2f}</span>'
            else:
                trend = '<span class="muted">→ 持平</span>'
        elif r["latest"] is not None and len(present) == 1:
            trend = '<span style="color:#c30">★ 新進榜</span>'
        if r["latest"] is None:
            trend = '<span class="muted">已退榜</span>'
        body_rows.append(
            f'<tr><td>{html_lib.escape(r["name"])}</td>{"".join(cells)}'
            f'<td>{trend}</td></tr>')

    # Line chart: top-6 holders present in the newest year (by latest pct).
    # null for years a holder was off the top-10 → Chart.js shows a gap.
    chart_rows = [r for r in rows if r["latest"] is not None][:6]
    palette = ["#c30", "#06c", "#0a0", "#e80", "#90c", "#0aa"]
    labels = json.dumps([f"{y}年" for y in years])
    datasets = []
    for i, r in enumerate(chart_rows):
        data = [r["by_year"].get(y) for y in years]  # None → gap
        nm = r["name"][:14] + ("…" if len(r["name"]) > 14 else "")
        datasets.append({
            "label": nm, "data": data,
            "borderColor": palette[i % len(palette)],
            "backgroundColor": palette[i % len(palette)],
            "tension": 0.2, "spanGaps": False,
        })
    chart_json = json.dumps({"labels": json.loads(labels),
                             "datasets": datasets}, ensure_ascii=False)

    return form + f"""
  <canvas id="sh-hist-chart" height="150"></canvas>
  {_history_commentary(history)}
  <div style="overflow-x:auto;margin-top:12px;">
  <table class="report-table" style="white-space:nowrap;">
    <thead><tr><th>股東名稱</th>{th}<th>{yold}→{ynew} 變化</th></tr></thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
  </div>
  <p class="small">每格為該年度年報揭露的持股比例 (%)。— = 該年未進前十大。
    ▲/▼ 為最舊→最新年度的變化 (pp)；★ 新進榜 / 已退榜 表示期間進出前十大。
    折線圖為最新年度前 6 大股東；線中斷表示該年未進前十大。
    註：保管銀行受託專戶名稱逐年略有差異，可能造成同一機構分列。</p>
</section>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  var el=document.getElementById('sh-hist-chart');
  if(!el||typeof Chart==='undefined') return;
  new Chart(el, {{
    type:'line',
    data:{chart_json},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
      plugins:{{title:{{display:true,text:'前十大股東持股比例 N 年趨勢'}},
        legend:{{labels:{{boxWidth:12,font:{{size:10}}}}}}}},
      scales:{{y:{{title:{{display:true,text:'持股比例 %'}}}}}}}}
  }});
}})();
</script>"""


def _render_shareholders_page(code: str = "", name: str = "",
                               data: dict | None = None,
                               error: str = "",
                               dist: dict | None = None,
                               history: dict | None = None,
                               hist_years: int = 5) -> str:
    """Web page: 前十大股東 (年報) + N 年變化 + 集保大戶分布 (TDCC 每週)."""
    code_attr = html_lib.escape(code or "")
    body = ""
    if error:
        body = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif data is not None and data.get("error"):
        body = (f'<div class="empty"><p><b>⚠ {html_lib.escape(code)} '
                f'{html_lib.escape(name)} 查無前十大股東</b></p>'
                f'<p>{html_lib.escape(data["error"])}</p>'
                f'<p class="small">可能：股票代號錯誤、公司年報尚未上傳 MOPS、'
                f'或年報股權結構格式非標準無法解析。</p></div>')
    elif data is not None:
        sh = data.get("shareholders", [])
        rd = data.get("record_date")
        dy = data.get("data_year")
        rd_str = f"停止過戶日 {rd}" if rd else "停止過戶日 (年報未標準揭露)"
        total_pct = sum(s["pct"] for s in sh)
        any_rel = any(s.get("relations") for s in sh)
        rows_html = []
        for i, s in enumerate(sh, 1):
            rels = s.get("relations") or []
            if rels:
                rel_html = "<br>".join(
                    f'{html_lib.escape(r["name"])}'
                    f'<span style="color:#888">'
                    f'（{html_lib.escape(r["relation"][:16])}）</span>'
                    for r in rels)
            else:
                rel_html = '<span class="muted">—</span>'
            rel_cell = f'<td style="font-size:0.85em">{rel_html}</td>' if any_rel else ""
            rows_html.append(
                f'<tr><td class="num">{i}</td>'
                f'<td>{html_lib.escape(s["name"])}</td>'
                f'<td class="num">{s["shares"]:,}</td>'
                f'<td class="num">{s["pct"]:.2f}%</td>{rel_cell}</tr>')
        rel_th = '<th>關係人 (備註)</th>' if any_rel else ""
        rel_foot = "<td></td>" if any_rel else ""
        body = f"""
<section class="header-card">
  <h2>{_esc(code)} {_esc(name)} 前十大股東</h2>
  <p class="small">資料來源：MOPS 民國 {dy} 年報「主要股東名單」· {rd_str}
     · 來源檔 {_esc(data.get("source_pdf",""))}</p>
</section>
<section>
  <table class="report-table">
    <thead><tr>
      <th class="num">#</th><th>股東名稱</th>
      <th class="num">持有股數</th><th class="num">持股比例</th>{rel_th}
    </tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
    <tfoot><tr style="font-weight:600;border-top:2px solid #ddd">
      <td></td><td>前十大合計</td>
      <td class="num">{sum(s["shares"] for s in sh):,}</td>
      <td class="num">{total_pct:.2f}%</td>{rel_foot}
    </tr></tfoot>
  </table>
  <p class="small">⚠ 前十大股東名單來自<b>年報</b>，每年股東會前更新一次
     (停止過戶日為股權快照日)，<b>非即時</b>。盤中籌碼請看 /chip-price 或
     下方集保大戶分布。持股單位為「股」(÷1000 = 張)。<br>
     「關係人 (備註)」= 年報揭露的前十大股東相互間配偶 / 二親等 / 法人關係。</p>
</section>"""

    # Multi-year 前十大股東 變化 (toggle form always shown once a stock is
    # queried; matrix renders when ?history=1 loaded it).
    if not error and (data is not None and not data.get("error")):
        body += _shareholders_history_html(history, code, hist_years)

    # Append 集保大戶分布 section (shows even if top-10 parse failed, as long
    # as a code was queried) — gives a weekly, more current chip view.
    if not error and dist is not None:
        body += _holding_distribution_html(dist)

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>前十大股東 — 台股單檔</title>
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
            background: #0066cc; color: white; border: none; border-radius: 4px; }}
  button:hover {{ background: #0052a3; }}
  nav a {{ margin-right: 12px; color: #0066cc; text-decoration: none; }}
  .error {{ background: #fee; border: 1px solid #f99; padding: 12px;
            border-radius: 4px; color: #c00; margin-bottom: 12px; }}
  .empty {{ background: white; padding: 16px; border-radius: 6px;
            color: #666; box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 12px; }}
  section {{ background: white; padding: 12px 16px; border-radius: 6px;
              margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  section.header-card h2 {{ margin: 0 0 6px 0; font-size: 1.3em; }}
  table.report-table {{ width: 100%; border-collapse: collapse; font-size: 0.9em; }}
  table.report-table th, table.report-table td {{ padding: 6px 10px;
                            border-bottom: 1px solid #eee; text-align: left; }}
  table.report-table th {{ background: #fafafa; font-weight: 600; color: #555; }}
  table.report-table .num {{ text-align: right;
                              font-variant-numeric: tabular-nums; }}
  .small, small {{ font-size: 0.85em; color: #666; }}
  @media (max-width: 768px) {{
    body {{ padding: 0 4px; }} section {{ overflow-x: auto; }}
    table.report-table {{ font-size: 0.8em; }}
  }}
</style>
</head>
<body>
<nav>
  <a href="/">← 大盤 dashboard</a>
  <a href="/chip-price">📋 籌碼價量</a>
  <a href="/contract-liabilities">💰 合約負債</a>
  <a href="/inventory">📦 存貨</a>
  <a href="/shareholders">👥 前十大股東</a>
</nav>
<h1>👥 前十大股東 (年報)</h1>

<form method="get" action="/shareholders">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 2330" autofocus required>
  <button type="submit">查詢</button>
</form>
<p class="small">💡 從 MOPS 年報「主要股東名單」解析，每年股東會前更新。
   範例：<a href="/shareholders?code=2330">2330 台積電</a> ·
   <a href="/shareholders?code=2317">2317 鴻海</a> ·
   <a href="/shareholders?code=2313">2313 華通</a> ·
   <a href="/shareholders?code=6282">6282 康舒</a></p>

{body}
</body>
</html>"""


@app.route("/shareholders")
def shareholders():
    code = (request.args.get("code") or "").strip()
    if not code:
        return _render_shareholders_page()
    try:
        import tw_inventory
        name = tw_inventory._zh_name(code)
    except Exception:
        name = ""
    try:
        import mops_pdf
        data = mops_pdf.fetch_major_shareholders(code)
    except Exception as e:
        return _render_shareholders_page(
            code=code, name=name, error=f"{type(e).__name__}: {e}")
    dist = _holding_distribution_data(code)
    # Multi-year history is lazy (downloads up to N F17 PDFs) — only when asked.
    history = None
    hist_years = 5
    if request.args.get("history") == "1":
        try:
            hist_years = max(2, min(int(request.args.get("hist_years") or "5"), 10))
        except ValueError:
            hist_years = 5
        try:
            history = mops_pdf.fetch_shareholders_history(code, years=hist_years)
        except Exception as e:
            history = {"error": f"{type(e).__name__}: {e}", "years": [], "rows": []}
    return _render_shareholders_page(code=code, name=name, data=data, dist=dist,
                                     history=history, hist_years=hist_years)


def _render_adr_premium_page(period: str = "6mo", data: dict | None = None,
                             error: str = "", mixed: dict | None = None) -> str:
    """Web page: TSM (台積電 ADR) vs 2330 折溢價，可選 1 週 ~ 10 年區間。"""
    import tw_adr_premium
    # 最新混合即時溢價 box (2330 today vs TSM latest overnight close)
    mixed_box = ""
    if mixed and not mixed.get("error") and mixed.get("premium") is not None:
        mp = mixed["premium"]
        mc = "#c30" if mp > 0 else "#060"
        if mixed.get("aligned"):
            note = f'兩邊皆 {mixed["tw_date"]} 收盤（已對齊）。'
        else:
            note = (f'2330 {mixed["tw_date"]} 收盤 vs TSM {mixed["tsm_date"]} '
                    f'美股收盤（跨時點：TSM 當日盤台北今晚才開，明早才對齊）。')
        mixed_box = (
            f'<section style="border-left:4px solid {mc}">'
            f'<h3>📍 最新即時溢價（混合最新報價）</h3>'
            f'<div style="font-size:1.6em;font-weight:700;color:{mc}">'
            f'{mp:+.2f}%</div>'
            f'<p class="small">TSM ${mixed["tsm"]} ({mixed["tsm_date"]}) × '
            f'{mixed["fx"]} = 理論 {mixed["theoretical"]:.0f} vs '
            f'2330 實際 {mixed["tw"]:.0f} ({mixed["tw_date"]})<br>{note}<br>'
            f'⚠ 此為跨時點即時參考，與下方「同日收盤」歷史序列定義不同；'
            f'反映 2330 今日收盤相對昨夜 ADR 的位置。</p></section>')

    opts = "".join(
        f'<option value="{k}"{" selected" if k == period else ""}>'
        f'{tw_adr_premium.PERIODS[k][2]}</option>'
        for k in tw_adr_premium.PERIOD_ORDER)
    plabel = tw_adr_premium.PERIODS.get(period, ("", 0, period))[2]
    body = ""
    if error:
        body = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif data is not None and data.get("error"):
        body = f'<div class="error">⚠ {html_lib.escape(data["error"])}</div>'
    elif data is not None:
        s = data["summary"]
        ser = data["series"]
        cur = s["current"]
        cur_color = "#c30" if cur > 0 else "#060"
        # summary cards
        cards = [
            ("當前折溢價", f'{cur:+.2f}%', cur_color,
             f'{s["current_date"]} · TSM ${s["current_tsm"]}×{s["current_fx"]}/5'
             f'=理論{s["current_theo"]:.0f} vs 實際{s["current_tw"]:.0f}'),
            (f"近 {plabel}均值", f'{s["mean"]:+.2f}%', "#444",
             f'當前位於 {s["pctile"]:.0f} 百分位'),
            ("區間最高 (溢價)", f'{s["max"]:+.2f}%', "#c30", s["max_date"]),
            ("區間最低 (折價)", f'{s["min"]:+.2f}%', "#060", s["min_date"]),
        ]
        card_html = "".join(
            f'<div style="flex:1;min-width:160px;background:#fafafa;'
            f'border-radius:6px;padding:10px 14px;">'
            f'<div style="font-size:0.82em;color:#666">{_esc(t)}</div>'
            f'<div style="font-size:1.5em;font-weight:700;color:{c}">{v}</div>'
            f'<div style="font-size:0.74em;color:#999">{_esc(sub)}</div></div>'
            for t, v, c, sub in cards)
        # chart data (downsample labels but keep all points)
        labels = json.dumps([r["date"] for r in ser])
        prem = json.dumps([r["premium"] for r in ser])
        mean_line = json.dumps([s["mean"]] * len(ser))
        # rebase 2330 + 加權指數 to 100 at window start (different scale →
        # right axis, normalized so the two price series are comparable).
        tw0 = next((r["tw"] for r in ser if r.get("tw")), None)
        twii0 = next((r["twii"] for r in ser if r.get("twii")), None)
        tw_idx = json.dumps([round(r["tw"] / tw0 * 100, 2) if tw0 and r.get("tw")
                             else None for r in ser])
        twii_idx = json.dumps([round(r["twii"] / twii0 * 100, 2)
                               if twii0 and r.get("twii") else None
                               for r in ser])
        # 折溢價斜率 + 轉折訊號 (module helper). Window adapts to point density.
        n = len(ser)
        win = max(2, min(5, n // 3)) if n >= 6 else 2
        sig = tw_adr_premium.slope_signals(ser, win=win)
        slope = sig["slope"]
        slope_line = json.dumps(slope)
        slope_win = win
        # marker datasets: plot the premium value at turn points (sit on the
        # 折溢價 line). turn+ = green ▲, turn- = red ▼.
        pos_set = set(sig["pos_idx"])
        neg_set = set(sig["neg_idx"])
        mark_pos = json.dumps([ser[i]["premium"] if i in pos_set else None
                               for i in range(n)])
        mark_neg = json.dumps([ser[i]["premium"] if i in neg_set else None
                               for i in range(n)])
        st = sig["stats"]
        # stats box (this period's backtest of the turn signal)
        def _stat_line(label, s, dirword, color):
            if not s:
                return f'<li>{label}：本區間無此訊號</li>'
            return (f'<li>{label}（{s["n"]} 次）：隔日{dirword}命中 '
                    f'<b style="color:{color}">{s["hit"]:.0f}%</b>，'
                    f'平均隔日報酬 <b style="color:{color}">{s["mean"]:+.2f}%</b></li>')
        stats_box = (
            f'<div style="background:#f7faff;border:1px solid #d6e4f5;'
            f'border-radius:6px;padding:10px 16px;margin:10px 0;">'
            f'<b style="color:#0066cc">📐 斜率轉折 → 隔日 2330 統計（本區間回測）</b>'
            f'<ul style="margin:6px 0 2px;padding-left:20px;line-height:1.7">'
            f'{_stat_line("🟢 斜率剛轉正", st["pos"], "收紅", "#c30")}'
            f'{_stat_line("🔴 斜率剛轉負", st["neg"], "收黑", "#060")}'
            f'<li class="small" style="color:#888">基準：全區間隔日收紅率 '
            f'{st["base_up"]:.0f}%（n={st["base_n"]}）。訊號命中率明顯高於基準才有參考價值。'
            f'多數漲跌反映在開盤跳空 → 需趁開盤前後進場。</li></ul></div>')
        # table: most recent 20 rows (newest first)
        trows = "".join(
            f'<tr><td>{_esc(r["date"])}</td>'
            f'<td class="num">{r["tsm"]:.2f}</td>'
            f'<td class="num">{r["fx"]:.3f}</td>'
            f'<td class="num">{r["theoretical"]:.0f}</td>'
            f'<td class="num">{r["tw"]:.0f}</td>'
            f'<td class="num" style="color:{"#c30" if r["premium"]>0 else "#060"}">'
            f'{r["premium"]:+.2f}%</td></tr>'
            for r in reversed(ser[-20:]))
        body = f"""
<section class="header-card">
  <h2>TSM ADR vs 2330 折溢價（近 {plabel}）</h2>
  <p class="small">換股比例 1:5 · 理論價 = TSM(USD)×匯率÷5 · 折溢價 =
     (理論價/2330實際價 − 1)。資料：Yahoo (TSM / 2330.TW / TWD=X) 日收盤。</p>
</section>
<section>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">{card_html}</div>
  {stats_box}
  <div id="adr-toggles" style="display:flex;gap:14px;flex-wrap:wrap;
       font-size:0.85em;margin-bottom:8px">
    <label><input type="checkbox" data-ds="0" checked> 🔵 折溢價</label>
    <label><input type="checkbox" data-ds="5" checked> ▲ 斜率轉正</label>
    <label><input type="checkbox" data-ds="6" checked> ▼ 斜率轉負</label>
    <label><input type="checkbox" data-ds="4" checked> 🟣 斜率線</label>
    <label><input type="checkbox" data-ds="1"> 🔴 區間均值</label>
    <label><input type="checkbox" data-ds="2"> 🟡 2330</label>
    <label><input type="checkbox" data-ds="3"> 🟢 加權指數</label>
  </div>
  <canvas id="adr-chart" height="150"></canvas>
  <p class="small" style="margin:6px 0 0">
    勾選方塊控制顯示哪些線。🔵 折溢價(左軸)；▲▼ = 斜率剛轉正/負的點 (標在折溢價線上)；
    🟣 斜率(右軸 pp/日)；🟡 2330 / 🟢 加權指數(右軸 期初=100)；🔴 區間均值。</p>
</section>
<section>
  <h3>近 20 個交易日明細</h3>
  <table class="report-table">
    <thead><tr><th>日期</th><th class="num">TSM (USD)</th>
      <th class="num">USD/TWD</th><th class="num">理論價</th>
      <th class="num">2330 實際</th><th class="num">折溢價</th></tr></thead>
    <tbody>{trows}</tbody>
  </table>
  <p class="small">⚠ 時間差：TSM 當日收盤比 2330 同日收盤晚約 14.5 小時，同日配對
    反映美股盤後對 2330 的看法。除權息日附近 (台美除息日不同步) 會有假性折溢價。</p>
</section>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  var el=document.getElementById('adr-chart'); if(!el||typeof Chart==='undefined')return;
  var ch=new Chart(el,{{type:'line',
    data:{{labels:{labels},datasets:[
      {{label:'折溢價 %',data:{prem},borderColor:'#0066cc',
        borderWidth:1.5,pointRadius:0,tension:0.1,yAxisID:'y'}},
      {{label:'區間均值',data:{mean_line},borderColor:'#c30',
        borderWidth:1,borderDash:[6,4],pointRadius:0,yAxisID:'y',hidden:true}},
      {{label:'2330 (期初=100)',data:{tw_idx},borderColor:'#e8a200',
        borderWidth:1,pointRadius:0,tension:0.1,yAxisID:'y1',spanGaps:true,hidden:true}},
      {{label:'加權指數 (期初=100)',data:{twii_idx},borderColor:'#0a0',
        borderWidth:1,pointRadius:0,tension:0.1,yAxisID:'y1',spanGaps:true,hidden:true}},
      {{label:'折溢價斜率 ({slope_win}日, pp/日)',data:{slope_line},
        borderColor:'#90c',borderWidth:1.5,borderDash:[3,2],pointRadius:0,
        tension:0.1,yAxisID:'y2',spanGaps:true}},
      {{label:'斜率轉正',data:{mark_pos},yAxisID:'y',showLine:false,
        pointStyle:'triangle',pointRadius:6,pointBackgroundColor:'#0a0',
        pointBorderColor:'#0a0'}},
      {{label:'斜率轉負',data:{mark_neg},yAxisID:'y',showLine:false,
        pointStyle:'triangle',rotation:180,pointRadius:6,
        pointBackgroundColor:'#c30',pointBorderColor:'#c30'}}
    ]}},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
      plugins:{{legend:{{display:false}},title:{{display:true,
        text:'折溢價斜率轉折 (▲轉正 ▼轉負) → 隔日 2330 訊號'}}}},
      scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:9}}}}}},
        y:{{position:'left',title:{{display:true,text:'折溢價 %'}},
            grid:{{color:function(c){{return c.tick.value===0?'#999':'#eee'}}}}}},
        y1:{{position:'right',title:{{display:true,text:'指數 (期初=100)'}},
            grid:{{drawOnChartArea:false}}}},
        y2:{{position:'right',title:{{display:true,text:'斜率 pp/日'}},
            grid:{{drawOnChartArea:false}}}}}}}}
  }});
  document.querySelectorAll('#adr-toggles input[data-ds]').forEach(function(cb){{
    cb.addEventListener('change',function(){{
      ch.setDatasetVisibility(parseInt(cb.dataset.ds), cb.checked);
      ch.update();
    }});
  }});
}})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TSM/2330 折溢價</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif;
         max-width: 1100px; margin: 1em auto; padding: 0 1em; background: #f7f7f9; color: #222; }}
  h1 {{ font-size: 1.4em; margin: 0.5em 0; }}
  form {{ display:flex; gap:8px; align-items:center; background:white; padding:12px;
         border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.06); margin-bottom:12px; }}
  select {{ font-size:16px; padding:6px 10px; border:1px solid #ccc; border-radius:4px; }}
  button {{ font-size:16px; padding:8px 16px; cursor:pointer; background:#0066cc;
           color:white; border:none; border-radius:4px; }}
  nav a {{ margin-right:12px; color:#0066cc; text-decoration:none; }}
  .error {{ background:#fee; border:1px solid #f99; padding:12px; border-radius:4px;
           color:#c00; margin-bottom:12px; }}
  section {{ background:white; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,0.06); }}
  section.header-card h2 {{ margin:0 0 6px 0; font-size:1.3em; }}
  section h3 {{ margin:0 0 8px 0; font-size:1.05em; color:#444; }}
  table.report-table {{ width:100%; border-collapse:collapse; font-size:0.9em; }}
  table.report-table th, table.report-table td {{ padding:6px 10px;
        border-bottom:1px solid #eee; text-align:left; }}
  table.report-table th {{ background:#fafafa; font-weight:600; color:#555; }}
  table.report-table .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .small, small {{ font-size:0.85em; color:#666; }}
</style>
</head>
<body>
<nav>
  <a href="/">← 大盤 dashboard</a>
  <a href="/chip-price">📋 籌碼價量</a>
  <a href="/inventory">📦 存貨</a>
  <a href="/shareholders">👥 前十大股東</a>
  <a href="/adr-premium">🇺🇸 ADR 折溢價</a>
</nav>
<h1>🇺🇸 TSM ADR vs 2330 折溢價</h1>
<form method="get" action="/adr-premium">
  <label>區間:
    <select name="period">{opts}</select></label>
  <button type="submit">查詢</button>
</form>
{mixed_box}
{body}
</body>
</html>"""


def _render_futures_basis_page(m: dict | None = None, error: str = "",
                                intraday: dict | None = None) -> str:
    """Web page: 期現貨基差 + 外資期貨留倉監控 (依「留倉沒多空意義」一文)."""
    # 盤中即時基差框 (TAIFEX MIS)
    intra_box = ""
    if intraday and not intraday.get("error"):
        ib = intraday
        bc = "#c30" if ib["basis"] < 0 else "#060"
        warn = ""
        if ib["basis"] < 0 and abs(ib["basis_pct"]) > 0.38 and ib.get("near_low"):
            warn = ('<div style="color:#c30;font-weight:700;margin-top:4px">'
                    '⚡ 殺盤 setup：逆價差超成本 + 現貨接近今日低 → 套利客易一腳踹下</div>')
        intra_box = (
            f'<section style="border-left:4px solid {bc}">'
            f'<h3>⚡ 盤中即時基差（TAIFEX，期 {_esc(ib["fut_time"])}/現 {_esc(ib["spot_time"])}）</h3>'
            f'<div style="font-size:1.6em;font-weight:700;color:{bc}">'
            f'基差 {ib["basis"]:+.0f} 點（{ib["basis_pct"]:+.2f}%）'
            f'{"逆價差" if ib["basis"]<0 else "正價差"}</div>'
            f'<p class="small">{_esc(ib["fut_name"])} {ib["future"]:.0f} vs '
            f'臺指現貨 {ib["spot"]:.0f}｜今日 高 {ib.get("spot_high","-")} / '
            f'低 {ib.get("spot_low","-")}（現貨距今日低 '
            f'{"≤0.3% 接近破底" if ib.get("near_low") else "尚遠"}）｜'
            f'套利成本 ±0.38%。盤中 (09:00-13:45) 即時更新，收盤後為最後一筆。{warn}</p>'
            f'</section>')
    body = intra_box
    if error:
        body += f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif m is not None and m.get("error"):
        body += f'<div class="error">⚠ {html_lib.escape(m["error"])}</div>'
    elif m is not None:
        ser = m["series"]
        L = m["latest"]
        cost = m["arb_cost"]
        three = m["three_signal"]
        # 教育 banner (文章核心)
        edu = (
            '<section style="border-left:4px solid #c30;background:#fff8f8">'
            '<h3>⚠ 先讀：外資期貨留倉淨額「沒有多空意義」</h3>'
            '<p class="small" style="line-height:1.7">'
            '期交所那張「外資大台留倉淨空 N 萬口」的圖 100% 正確、有公信力，'
            '<b>但不值得拿來判斷行情</b>——因為它 98% 來自 6-8 家投行的'
            '<b>期現貨套利對沖腳</b>（買一籃子現貨、空期貨），淨部位≈0、沒有方向。'
            '把「果」當「因」在上面做文章，回測勝率連 5 成都不到。<br>'
            '真正該看的是下面這幾項：<b>盤中正逆價差 vs 套利成本</b>、'
            '<b>三訊號同步</b>、<b>基差-留倉套利一致性</b>、'
            '<b>富台 OI 規模佐證</b>、月底轉倉。</p></section>')

        # 三訊號 + 同向極端 狀態卡
        def yn(b):
            return ('<b style="color:#c30">是</b>' if b
                    else '<span style="color:#999">否</span>')
        twn = m.get("twn_oi") or {}
        if twn.get("latest_oi") is not None:
            _tp = twn.get("prev_oi")
            _tdelta = (f"（Δ{twn['latest_oi']-_tp:+,}）" if _tp is not None else "")
            twn_row = (
                f'<tr><td>富台(SGX TWN)近月 OI<br><span class="small">'
                f'部位規模佐證（總 OI，非外資淨額）</span></td>'
                f'<td class="num">{twn["latest_oi"]:,} 口{_tdelta}</td>'
                f'<td>SGX 富台總未平倉。升=全市場在富台佈更多部位；與大台'
                f'外資空單/基差一起看是否同步擴張（總 OI 無方向，僅規模佐證）</td></tr>')
        else:
            twn_row = ''
        sig_box = (
            f'<section><h3>🚦 即時訊號狀態（最新 {_esc(L["date"])}）</h3>'
            f'<table class="report-table"><tbody>'
            f'<tr><td>基差（TX 日盤 − 加權現貨）</td>'
            f'<td class="num" style="color:{"#c30" if L["basis"]<0 else "#060"}">'
            f'{L["basis"]:+.0f} 點 ({L["basis_pct"]:+.2f}%)</td>'
            f'<td>原始基差（未除息調整）</td></tr>'
            f'<tr><td>🎯 除息調整後基差<br><span class="small">'
            f'(+ 結算前剩餘除息點數 D，還原旺季結構性逆價差)</span></td>'
            f'<td class="num" style="color:{"#c30" if L.get("adj_basis",0)<0 else "#060"}">'
            f'{L.get("adj_basis",0):+.0f} 點 ({L.get("adj_basis_pct",0):+.2f}%)<br>'
            f'<span class="small">D={L.get("div_points",0):+.0f} 點'
            + (f"／覆蓋率{L['div_coverage_pct']}%"
               if L.get("div_coverage_pct") is not None else "")
            + '</span></td>'
            f'<td>套利成本 ±{cost}%｜超過 = {yn(m["basis_extreme"])}'
            f'（用調整後判斷）</td></tr>'
            f'<tr><td>三訊號同步（跌+逆價差+台幣貶）</td>'
            f'<td class="num">跌 {yn(three["twii_down"])}／逆價差 '
            f'{yn(three["backwardation"])}／台幣貶 {yn(three["twd_weak"])}</td>'
            f'<td>三者同時 = {yn(three["all"])} '
            f'{"→ 可認定外資大賣超(但賣超≠做空)" if three["all"] else ""}</td></tr>'
            f'<tr><td>基差-留倉套利一致性<br><span class="small">'
            f'(大台外資淨額 × 基差，主訊號)</span></td>'
            f'<td class="num">外資 TX 淨 {m["tx_net"]:+,} 口<br>'
            f'調整後基差 {L.get("adj_basis",0):+.0f} 點 '
            f'({"正價差" if L.get("adj_basis",0)>0 else "逆價差"})</td>'
            f'<td>{"✅ 正價差 + 大空單 = 純套利印證，那串空單沒有方向意義" if m["arb_consistent"] else ("🔴 逆價差 + 空單續增 = 罕見，可能真有方向" if m["directional_warn"] else "—")}</td>'
            f'</tr>'
            f'{twn_row}'
            f'</tbody></table>'
            f'<p class="small">⚠ FinMind 期貨為日收盤；文章強調「盤中 9:00-13:25」'
            f'基差最準，本頁為日盤收盤基準。逆價差 &gt; 成本 + 指數破底 → 套利客'
            f'一腳踹下、跌時特別兇。</p></section>')

        # 富台(SGX TWN)近月 OI — TradingView 自動抓 SGX:TWN1!
        twn = m.get("twn_oi") or {}
        if twn.get("latest_oi") is not None:
            d = twn["latest_date"]
            dfmt = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d
            prev = twn.get("prev_oi")
            delta = (f' <span style="color:{"#c30" if twn["latest_oi"]>prev else "#060"}">'
                     f'Δ{twn["latest_oi"]-prev:+,}</span>' if prev is not None else "")
            src = "TradingView 自動抓取" if twn.get("source") == "live" else "快取"
            twn_box = (
                f'<section><h3>🇸🇬 富台(SGX TWN)近月未平倉口數</h3>'
                f'<table class="report-table"><tbody>'
                f'<tr><td>最新 OI（近月 TWN1!）</td>'
                f'<td class="num">{twn["latest_oi"]:,} 口{delta}</td>'
                f'<td>{src}・{_esc(dfmt)}</td></tr></tbody></table>'
                f'<p class="small">資料來源：TradingView SGX:TWN1!（近月連續合約）即時 OI。'
                f'SGX 官網本身有 Akamai 反爬蟲擋自動化，改由 TradingView scanner '
                f'端點取得，每次更新自動記錄建立歷史。</p></section>')
        else:
            twn_box = (
                '<section><h3>🇸🇬 富台(SGX TWN)近月未平倉口數</h3>'
                '<p class="small">TradingView 端點暫時抓不到。可手動補：'
                '<code>tw_futures_basis.py --log-twn-oi &lt;口數&gt;</code></p>'
                '</section>')

        # 外資/法人 近月 vs 遠月 台指部位
        lt = m.get("large_trader")
        ob = m.get("oi_by_month")
        def _net(v):
            if v is None:
                return "—"
            col = "#c30" if v < 0 else ("#060" if v > 0 else "#666")
            tag = "淨空" if v < 0 else ("淨多" if v > 0 else "")
            return f'<span style="color:{col}">{v:+,} 口 {tag}</span>'
        if lt or ob:
            parts = ['<section><h3>🧭 外資/法人 台指 近月 vs 遠月 部位</h3>']
            if lt:
                nl = lt.get("near_label") or "近月"
                parts.append(
                    '<p class="small"><b>特定法人前十大未沖銷淨部位</b>'
                    '（TAIFEX 大額交易人表，特定法人＝外資＋投信＋自營大戶，'
                    '<b>非純外資</b>）：</p>'
                    '<table class="report-table"><tbody>'
                    f'<tr><td>近月（{_esc(nl)}）</td><td class="num">'
                    f'{_net(lt["spec_near_net"])}</td>'
                    f'<td class="small">買 {lt["spec_near_buy"]:,} / 賣 {lt["spec_near_sell"]:,}</td></tr>'
                    f'<tr><td>遠月（次月以後）</td><td class="num">{_net(lt["spec_far_net"])}</td>'
                    f'<td class="small">= 全契約 − 近月 − 週契約</td></tr>'
                    f'<tr><td>週契約</td><td class="num">{_net(lt["spec_week_net"])}</td>'
                    f'<td class="small">最近到期週選</td></tr>'
                    f'<tr><td><b>全契約合計</b></td><td class="num">{_net(lt["spec_all_net"])}</td>'
                    f'<td class="small">買 {lt["spec_all_buy"]:,} / 賣 {lt["spec_all_sell"]:,}</td></tr>'
                    '</tbody></table>')
            if ob:
                bm = "、".join(f'{m_[:4]}/{m_[4:]} {oi_:,}' for m_, oi_ in ob["by_month"][:4])
                roll = ("次月已超過近月 → 轉倉過半"
                        if ob["next_oi"] > ob["near_oi"] else "部位仍集中近月")
                parts.append(
                    '<p class="small"><b>市場逐月未平倉（全市場 OI，看轉倉）</b>：</p>'
                    '<table class="report-table"><tbody>'
                    f'<tr><td>近月 {ob["near"][:4]}/{ob["near"][4:]}</td>'
                    f'<td class="num">{ob["near_oi"]:,} 口</td>'
                    f'<td class="small">{_esc(roll)}</td></tr>'
                    + (f'<tr><td>次月 {ob["next"][:4]}/{ob["next"][4:]}</td>'
                       f'<td class="num">{ob["next_oi"]:,} 口</td><td></td></tr>' if ob["next"] else '')
                    + f'<tr><td>遠月合計</td><td class="num">{ob["far_oi"]:,} 口</td><td></td></tr>'
                    f'<tr><td><b>總 OI</b></td><td class="num">{ob["total"]:,} 口</td><td></td></tr>'
                    '</tbody></table>')
            parts.append(
                '<p class="small">📌 <b>怎麼看</b>：特定法人空單若集中在<b>遠月</b>＝法人對'
                '中長線偏空的押注（近月易受結算/套利干擾，遠月較反映方向觀點）。結算日'
                '（每月第 3 個週三）前後近月 OI 會驟降、轉到次月＝<b>轉倉</b>，屬正常換月不是'
                '減碼。⚠ 純外資分月免費資料拿不到，此處特定法人為其 proxy。</p></section>')
            lt_box = "".join(parts)
        else:
            lt_box = ''

        # 圖表資料
        labels = json.dumps([r["date"] for r in ser])
        basis_pct = json.dumps([r["basis_pct"] for r in ser])
        cost_hi = json.dumps([cost] * len(ser))
        cost_lo = json.dumps([-cost] * len(ser))
        tx_oi = json.dumps([r.get("fx_net") for r in ser])
        xif_oi = json.dumps([r.get("xif_net") for r in ser])
        # 明細表
        trows = "".join(
            f'<tr><td>{_esc(r["date"])}</td>'
            f'<td class="num">{r["tx"]:.0f}</td>'
            f'<td class="num">{r["spot"]:.0f}</td>'
            f'<td class="num" style="color:{"#c30" if r["basis"]<0 else "#060"}">'
            f'{r["basis"]:+.0f} ({r["basis_pct"]:+.2f}%)</td>'
            f'<td class="num">{r["fx_net"]:+,}</td>'
            f'<td class="num">{(("%+.2f%%" % r["twii_chg"]) if r["twii_chg"] is not None else "—")}</td>'
            f'<td class="num">{(("%+.2f%%" % r["fx_chg"]) if r["fx_chg"] is not None else "—")}</td></tr>'
            for r in reversed(ser[-15:]))
        body = intra_box + edu + sig_box + twn_box + lt_box + f"""
<section>
  <h3>📈 基差走勢（vs ±{cost}% 套利成本帶）</h3>
  <canvas id="basis-chart" height="130"></canvas>
  <p class="small">綠=正價差(期貨貴)，紅=逆價差(現貨貴)。落在 ±{cost}% 帶內 =
    套利無肉；逆價差跌破 -{cost}% = 套利客有利可圖，破底殺盤兇。</p>
</section>
<section>
  <h3>📊 外資 TX 留倉 vs 基差 — 套利印證</h3>
  <canvas id="oi-chart" height="120"></canvas>
  <p class="small">⚠ 外資 TX 淨空 {L.get("fx_net",0):+,} 口是投行套利對沖腳的影子，
    <b>本身沒有多空意義</b>。<b>驗證方法</b>：紅線(外資TX淨空)往下擴大時，藍線
    (基差)若維持<b>正價差</b> → 投行「賣貴期貨買現貨」套利，那串空單被基差完全解釋、
    沒有方向。只有「逆價差還一直加空」才罕見、可能真有方向。<br>
    <b>📌 富台(SGX TWN)定位</b>：上方訊號表已接回富台近月 OI（TradingView 自動抓）。
    但拿到的是<b>總 OI、非外資淨部位</b>（SGX 不免費公布法人淨額），所以無法做文章原本
    「大台外資 vs 富台外資 同向」的方向交叉，只能當<b>部位規模佐證</b>：富台 OI 與大台
    外資空單若同步擴張、基差又維持正價差 → 佐證投行跨市場套利/避險在加碼，仍非方向訊號。</p>
</section>
<section>
  <h3>近 15 日明細</h3>
  <table class="report-table">
    <thead><tr><th>日期</th><th class="num">TX 期</th><th class="num">加權現貨</th>
      <th class="num">基差</th><th class="num">外資TX淨留倉</th>
      <th class="num">加權漲跌</th><th class="num">台幣</th></tr></thead>
    <tbody>{trows}</tbody>
  </table>
</section>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  if(typeof Chart==='undefined')return;
  new Chart(document.getElementById('basis-chart'),{{type:'line',
    data:{{labels:{labels},datasets:[
      {{label:'基差 %',data:{basis_pct},borderColor:'#0066cc',borderWidth:1.5,
        pointRadius:0,tension:0.1}},
      {{label:'+{cost}% 成本',data:{cost_hi},borderColor:'#999',borderWidth:1,
        borderDash:[4,3],pointRadius:0}},
      {{label:'-{cost}% 成本',data:{cost_lo},borderColor:'#999',borderWidth:1,
        borderDash:[4,3],pointRadius:0}}
    ]}},
    options:{{responsive:true,plugins:{{title:{{display:true,text:'期現貨基差 % (TX 日盤 vs 加權)'}}}},
      scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:9}}}}}},
        y:{{title:{{display:true,text:'基差 %'}},
            grid:{{color:function(c){{return c.tick.value===0?'#999':'#eee'}}}}}}}}}}
  }});
  new Chart(document.getElementById('oi-chart'),{{type:'line',
    data:{{labels:{labels},datasets:[
      {{label:'外資 TX 淨留倉(口)',data:{tx_oi},borderColor:'#c30',borderWidth:1.5,
        pointRadius:0,tension:0.1,spanGaps:true,yAxisID:'y'}},
      {{label:'基差 %',data:{basis_pct},borderColor:'#06c',borderWidth:1.5,
        pointRadius:0,tension:0.1,spanGaps:true,yAxisID:'y1'}}
    ]}},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
      plugins:{{title:{{display:true,text:'外資TX淨空 vs 基差 — 空單擴大時基差正價差=純套利印證'}}}},
      scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:9}}}}}},
        y:{{position:'left',title:{{display:true,text:'外資TX淨留倉 口'}}}},
        y1:{{position:'right',title:{{display:true,text:'基差 %'}},
            grid:{{drawOnChartArea:false}}}}}}}}
  }});
}})();
</script>"""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>期現貨基差 / 外資留倉</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif;
         max-width: 1100px; margin: 1em auto; padding: 0 1em; background: #f7f7f9; color: #222; }}
  h1 {{ font-size: 1.4em; margin: 0.5em 0; }}
  nav a {{ margin-right:12px; color:#0066cc; text-decoration:none; }}
  .error {{ background:#fee; border:1px solid #f99; padding:12px; border-radius:4px;
           color:#c00; margin-bottom:12px; }}
  section {{ background:white; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,0.06); }}
  section h3 {{ margin:0 0 8px 0; font-size:1.05em; color:#444; }}
  table.report-table {{ width:100%; border-collapse:collapse; font-size:0.9em; }}
  table.report-table th, table.report-table td {{ padding:6px 10px;
        border-bottom:1px solid #eee; text-align:left; }}
  table.report-table th {{ background:#fafafa; font-weight:600; color:#555; }}
  table.report-table .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .small, small {{ font-size:0.85em; color:#666; }}
</style></head>
<body>
<nav>
  <a href="/">← 大盤 dashboard</a>
  <a href="/chip-price">📋 籌碼價量</a>
  <a href="/shareholders">👥 前十大股東</a>
  <a href="/adr-premium">🇺🇸 ADR 折溢價</a>
  <a href="/futures-basis">📐 期貨基差</a>
</nav>
<h1>📐 期現貨基差 / 外資期貨留倉監控</h1>
{body}
</body>
</html>"""


@app.route("/futures-basis")
def futures_basis():
    try:
        import tw_futures_basis
        m = tw_futures_basis.fetch_monitor(days=30)
    except Exception as e:
        return _render_futures_basis_page(error=f"{type(e).__name__}: {e}")
    try:
        intraday = tw_futures_basis.intraday_basis()
    except Exception:
        intraday = None
    return _render_futures_basis_page(m=m, intraday=intraday)


# 回測術語說明 — 兩個回測頁共用
_BACKTEST_GLOSSARY = {
    "持有天數 (H)": "進場後抱幾個交易日才賣。5日≈一週、20日≈一個月。同一訊號在不同 H 下表現可能差很多。",
    "事件研究": "event study。針對『每次訊號觸發』這個事件，量它之後的報酬分布，再跟基準比 — 適合『挑個股』型訊號(非排名)。",
    "絕對報酬": "進場後 H 日單純的漲跌% (不減大盤)。看『有沒有賺到錢』，但沒扣掉大盤本身的漲跌。",
    "超額報酬 (vs 大盤)": "個股/族群報酬 − 同期加權指數報酬。正=贏大盤。也叫 alpha。衡量「贏不贏大盤」。",
    "淨超額": "超額報酬再扣掉來回交易成本 (成本值見各頁表格)。這才是真正能放口袋的數字。",
    "基準 (baseline)": "現版用<b>日期配對基準</b>（date-matched baseline）：與訊號<b>同一天</b>隨機抽 100 檔股票，算它們之後 H 日平均超額報酬，作為「那天隨便買」的比較基準。這樣才能排除「那段期間市場本來就漲/跌」的干擾。edge = 個股超額 − 此基準。⚠ 舊版用同 universe 所有股票日平均，兩者定義不同、數字不可比。",
    "edge": "量化/賭場術語=優勢。本頁定義：訊號超額 − 同日期隨機抽 100 檔股票的平均超額（date-matched 基準），衡量純選股力（排除「那天市場本來就漲/跌」的干擾）。⚠ edge 大 ≠ 很賺：edge 只說明比「同日亂買」強多少，賺不賺仍看「超額 vs 大盤 > 0」。",
    "alpha": "超額報酬，一般指 vs 大盤。≈本頁的「淨超額」。",
    "賺錢率 / 勝率": "進場後絕對報酬>0 的比例 (有沒有賺錢，不管贏不贏大盤)。",
    "贏大盤率 (beat rate)": "進場後超額報酬>0 的比例 (有沒有贏大盤)。",
    "中位數 vs 均值": "均值被少數大贏家拉高。若『均值正、但中位數負』= 多數筆其實輸，靠少數飆股撐 → 報酬右偏，要分散才接得住。",
    "IC (資訊係數)": "Spearman 等級相關：當期『分數排名』與『之後報酬排名』吻合度，−1~+1。>0.1 算不錯。旁邊 % = 為正的期數比例(穩定度)。",
    "多空價差": "高分前1/3族群平均超額 − 低分後1/3族群平均超額。越大代表分數越能分辨強弱。",
    "累積淨超額 / 權益曲線": "把每期淨超額逐筆累加(非複利)畫成線，看整體趨勢與回檔。",
    "最大回撤 (MaxDD)": "權益曲線從歷史高點回落的最大跌幅。衡量最痛要忍受多少。",
    "報酬/波動": "單期淨超額 ÷ 單期報酬標準差 (類 Sharpe)，越高=每單位波動換到越多報酬、越穩。",
    "Calmar": "總報酬 ÷ 最大回撤。每承受 1 單位回撤換到多少報酬，越高越好。",
    "point-in-time": "重建訊號時『只用當天(t)以前看得到的資料』，不偷看未來，確保測的是當下真能下的單。",
    "episode 去重": "同一波型態會連續好幾天觸發，只取『首次』當進場，避免重複樣本灌水。",
    "CI / 信賴區間": "把樣本重抽 5000 次（bootstrap）得到均值的分佈範圍（95% 信心水準）。判讀：<b>區間含 0 = 統計上跟 0 沒差別（不顯著），可能只是運氣</b>；區間全正才算可信。CI 越寬 = 樣本少或離散大、結論越不可靠。",
    "t 統計量": "用樣本均值 ÷ 標準誤算出來的假設檢定分數，越大越顯著。|t| > 2 約等同 p < 0.05（顯著）。跟 CI 搭配看：CI 含 0 時 t 通常也 < 2。數字旁邊標 ✓顯著 = CI 下界 > 0。",
    "日期配對基準 (date-matched)": "與訊號<b>同一天</b>隨機抽 100 檔股票，算它們之後 H 日平均超額報酬，作為「那天隨便買」的比較基準。這樣排除「那段時間大盤本來就漲/跌」的干擾；edge = 個股超額 − 此基準。比舊版「同 universe 所有日期均值」更精準，但隨機抽樣本身有 bootstrap 誤差。",
    "除權息剔除": "若某次進場後的持有期間內有<b>除權息</b>，該樣本直接排除（n_skipped_div 就是被剔掉的筆數）。除息日股價會跳空下降（配發現金），不剔除會讓報酬看起來比實際差，污染統計。剔除後樣本數減少，CI 會變寬。",
    "隔日開盤進場": "訊號通常在 18:00 後才產出，當天已無法買進；<b>隔日開盤</b>是最早能下單的時機，也是較真實的進場假設。對照組「訊號日收盤進場」= 理想化假設（提前知道訊號），報酬通常更高，但現實中做不到。",
    "非重疊 rebalance": "權益曲線用<b>非重疊</b>窗口（步進 ≥ 持有天數 H）計算，每筆資金只算一次。若用比 H 更密的 rebalance（如每 5 日 rebalance、但持有 20 日），同一段期間會被計入 4 次，報酬虛膨 4 倍。IC 允許重疊觀察（偵測相關性），但其 CI 另用 block bootstrap 校正時序自相關。",
    "block bootstrap CI": "IC 的信賴區間不能直接用獨立重抽樣 bootstrap — 相鄰期的 IC 有時序相關（自相關）。改用 <b>block bootstrap</b>：把連續幾期一塊抽，保留時序結構，再算 CI，比較不會低估不確定性。CI ✓ = 下界 > 0，表示 IC 顯著為正。",
    "樣本不足警語 (n<30)": "⚠<30 標示表示該持有期的樣本數不足 30 筆。統計中央極限定理在 n<30 時可靠性下降，CI 會很寬；看到這個標示時，數字僅供方向參考，不宜下強結論。累積更多歷史事件後才建議重新評估。",
    "財報可用日 (法定死線)": (
        "point-in-time 重建中，FinMind 的 <code>TaiwanStockFinancialStatements</code> 的 <code>date</code> 欄是<b>季度期末日</b>，"
        "不是公告日。回測以法定申報死線當作「資料可用日」：Q1(3/31)→5/15、Q2(6/30)→8/14、Q3(9/30)→11/14、Q4(12/31)→翌年3/31。"
        "這是<b>保守估計</b>（多數公司會提早公告，實際可用日更早），因此回測 edge 是<b>低估</b>而非高估。"
        "⚠ 陷阱：若用 FinMind date 直接當進場日，等於財報一出就用，會引入前視偏誤（look-ahead bias）。"
    ),
    "ABD overlay": (
        "Layer 2 訊號在 Layer 1 事件日的三訊號評分（0-3 分）：<br>"
        "A = 漲停接力（近 3 日有漲 ≥5%，且前日盤中未崩 ≤-4%）；"
        "B = 借券回補（借券賣餘近 3d/前 5d ≤ 0.97 或前日單日 ≤-3%）；"
        "D = 量能蓄勢（前日量 / 20d 均量 ≥1.0 或 / 60d 均量 ≥1.5）。"
        "C 訊號（籌碼集中）需分點歷史資料，無公開歷史，誠實跳過，故 overlay 名稱為 ABD。<br>"
        "<b>ge2 組（ABD≥2）</b> = 當日至少兩個 overlay 訊號同步觸發；<b>lt2 組（ABD&lt;2）</b> = 否。"
        "比較兩組前向報酬差異，可回答「Layer 2 是否在 Layer 1 之上加值」。"
    ),
    "借券賣出餘額 (SBL)": (
        "<b>Securities Borrowing and Lending</b>（借券賣出）的每日未平倉張數。"
        "放空者向券商借股票來賣，SBL 餘額代表市場上「尚未還券」的借出量，"
        "俗稱「空頭部位」的一種衡量。⚠ 陷阱：SBL 減少不一定是空頭平倉——"
        "也可能是到期強制還券（制度性還券）或轉換融券；判斷前須排除明顯的「一次性大量還券」。"
    ),
    "議借": (
        "<b>議借</b>（Negotiated Lending）是借券交易的一種型態，由借方與出借方直接協議數量與利率，"
        "與「競價」借券（公開競標）相對。議借量爆增代表機構/大戶有大量借券需求，"
        "可能為放空建倉（高利率 &gt;7%）或避險/套利（低利率 &lt;1%）。"
        "本策略用 <code>TaiwanStockSecuritiesLending</code> 中 transaction_type='議借' 的記錄。"
    ),
    "利率帶 (<1% / >7%)": (
        "議借的量加權平均費率。<br>"
        "<b>&lt;1% (low_rate)</b>：利率極低，出借方幾乎無報酬，借方可能為套利或避險目的，"
        "市場上「容易借到」意味空頭成本低；與之後股價走勢關係較複雜。<br>"
        "<b>&gt;7% (high_rate)</b>：高費率代表<b>難借、供不應求</b>，"
        "空頭仍願付高價借股票，通常是對個股下跌有強烈信念；"
        "歷史上高費率議借後股價往往繼續弱勢（空頭佔優）。"
        "⚠ 兩個利率帶方向含義不同，<b>不可混讀</b>。"
    ),
    "分層標記 (⭐/◐/▽)": (
        "2026-07-07 對第二波(second_wave) 502 個 episodes 做子群分析（2025 訓練 / 2026 驗證，兩年方向一致）："
        "「距前高」= 今日收盤價 ÷ 這波峰值收盤價。例：峰值 100 元、今收 85 元 → 85%，屬「早期」（反彈才走到峰值的 85%，還有上行空間）；今收 92 元 → 92% ≥88%，屬「已近前高」（大部分反彈已走完才被掃到 = 追高）。88% 是子群回測掃出的分界。<br>"
        "距前高 &lt;88%（反彈早期）且 20 日均成交額 ≥11 億的訊號，20 日超額報酬 +11.9%（95% CI 全正，中位數 +7.2%，n=52）；"
        "現行約 72% 的訊號（已反彈至 ≥88%）幾乎無 edge（+0.05%，CI 含 0）。<br>"
        "三層定義：⭐ = 距前高&lt;88% 且 20 日均成交額 ≥11 億（早期+大額）；"
        "◐ = 距前高&lt;88% 但成交額未達門檻（早期，籌碼較薄）；"
        "▽ = 距前高 ≥88%（已近前高，反彈晚期，現行大多數訊號屬此層）。<br>"
        "⚠ 陷阱：此分層是<b>事後子群挖掘</b>（約 20 種切法中挑出的組合），⭐ 組樣本僅 n=52，"
        "+11.9% / ≈0 是<b>歷史統計、非保證</b>，目前正透過訊號成效追蹤器 forward-test（分層桶會隨新訊號累積更新）。"
        "⚠ <b>2022-2024 OOS 驗證不成立</b>（⭐ 組 2024 年 -2.4%、&lt;88% 與 ≥88% 無差異）— "
        "此分層是 2025-26 動能市的 regime 現象，非任何市況皆有效的規則；大盤轉弱時分層參考性下降。"
    ),
    "借券急跌標記 (借↓/借↑)": (
        "急跌是「洗盤」還是「真跌」的籌碼判別：量測第二波急跌期 (峰值→低點) 借券賣出餘額變化。<br>"
        "借↓ = 變化 ≤ -5%（空方回補），借↑ = 變化 ≥ +5%（空方加碼），"
        "介於 ±5% 內或資料缺（fail-open）標 —。<br>"
        "episode 條件化回測：2025-26 動能市 (n=529) 回補組 20 日超額 +6.51%（95% CI [+2.9,+10.4]，贏 51%）、"
        "持平組 +0.21%、增加組 -0.86%（中位數 -4.5%，贏 37%，單調遞減）；"
        "OOS 2022-24 (n=556) 回補 +2.22% / 持平 +0.45% / 增加 -1.00%（單調性成立但信賴區間跨 0，"
        "其中 2022 年增加組 -5.88% CI 全負；<b>2023 年為反例年</b>：回補 -1.2% vs 增加 +0.6%）。<br>"
        "⚠ 陷阱：不對稱結論——<b>借↑（空方加碼）是跨年較穩定的避開訊號</b>；"
        "<b>借↓（空方回補）是 2025-26 動能市放大的加分訊號，2023 年有反例</b>，非任何市況皆成立。"
        "定位是<b>標記 + forward-test</b>，不改變第二波篩選條件本身。融資餘額變化已測無鑑別力，不採用。"
    ),
    "up_only (減量且當日上漲)": (
        "<b>up_only</b> 是「空頭撤退」訊號的子集：SBL 餘額日減 ≥10% <b>且</b> 個股當日收漲。"
        "live 系統的「轉多訊號」分組規則（tw_lending_monitor.py）正是這條邏輯——"
        "空頭縮手 + 股價已開始反彈，視為更強的轉多確認。"
        "回測中若 up_only 組 edge 顯著優於 all 組，支持此分組規則有選股力；"
        "若差異不顯著或反轉，則分組條件需重新評估。"
    ),
}


def _glossary_section(keys: list[str], title: str = "📚 術語說明") -> str:
    rows = "".join(
        f'<tr><td style="white-space:nowrap;font-weight:600">{_esc(k)}</td>'
        f'<td>{_BACKTEST_GLOSSARY[k]}</td></tr>'
        for k in keys if k in _BACKTEST_GLOSSARY)
    return (f'<section><h3>{title}</h3>'
            f'<table class="report-table"><tbody>{rows}</tbody></table></section>')


def _render_concept_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/chip-price">📋 籌碼價量</a>'
           '<a href="/shareholders">👥 前十大股東</a>'
           '<a href="/adr-premium">🇺🇸 ADR 折溢價</a>'
           '<a href="/futures-basis">📐 期貨基差</a>'
           '<a href="/concept-backtest">🧪 族群策略回測</a></nav>')
    css = """<style>
  body { font-family: -apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:1100px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  section h3 { margin:0 0 8px 0; font-size:1.05em; color:#444; }
  table.report-table { width:100%; border-collapse:collapse; font-size:.9em; }
  table.report-table th,table.report-table td { padding:6px 10px; border-bottom:1px solid #eee; text-align:left; }
  table.report-table th { background:#fafafa; font-weight:600; color:#555; }
  table.report-table .num { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:#060; } .neg { color:#c30; }
  .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  .cards { display:flex; gap:10px; flex-wrap:wrap; }
  .card { flex:1; min-width:130px; background:#fafbff; border:1px solid #e6e9f5; border-radius:6px; padding:10px 12px; }
  .card .v { font-size:1.4em; font-weight:700; } .card .k { font-size:.8em; color:#777; }
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>族群資金流向策略回測</title>{css}</head><body>{nav}'
            f'<h1>🧪 族群資金流向策略 — 回測</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>tw_concept_backtest.py --json-out '
                       'concept_momentum/cache/concept_backtest.json</code></p></section>') + tail

    s = data["strategy"]; b = data.get("benchmark"); f = data.get("filter")
    p = data["params"]
    hs = [str(h) for h in p["horizons"]]
    hmax = hs[-1]
    # 變體：原複合分數(A)已淘汰不顯示，只留 動能+門檻過濾(C，正式推送) + 純動能(B)
    variants = []
    if f:
        variants.append(("filter", "動能+門檻過濾 ⭐推送", "#2a9d4a", f))
    if b:
        variants.append(("benchmark", "純動能 ret_20d", "#cc8800", b))
    if not variants:                               # 舊 JSON 無 B/C 時退回 A
        variants = [("strategy", "複合分數(加權)", "#3366cc", s)]
    # 摘要卡以正式推送變體(C)為主
    primary = variants[0][3]
    primary_label = variants[0][1]
    sh = primary["horizons"][hmax]
    def cls(v): return "pos" if v is not None and v > 0 else "neg"
    cards = (
        f'<p class="small" style="margin:.2em 0">摘要卡＝<b>{primary_label}</b>（H={hmax}d）</p>'
        '<div class="cards">'
        f'<div class="card"><div class="k">IC (H={hmax}d)</div>'
        f'<div class="v {cls(sh["ic"])}">{sh["ic"]:+.2f}</div>'
        f'<div class="small">>0 比例 {sh["ic_pos"]:.0f}%</div></div>'
        f'<div class="card"><div class="k">多空價差</div>'
        f'<div class="v {cls(sh["spread"])}">{sh["spread"]:+.1f}%</div></div>'
        f'<div class="card"><div class="k">高分組命中率</div>'
        f'<div class="v">{sh["hit"]:.0f}%</div></div>'
        f'<div class="card"><div class="k">選股淨超額</div>'
        f'<div class="v {cls(sh["l2"])}">{sh["l2"]:+.1f}%</div>'
        f'<div class="small">勝率 {sh["l2_win"]:.0f}% · 扣{p["cost"]}%</div></div>'
        '</div>')
    meta = (f'<p class="small">回測區間 {s["start"]}~{s["end"]}・{s["n_rebalance"]} 個 '
            f'rebalance 點（每 {p["rebalance"]} 日）・前 {p["topk"]} 名族群選股・'
            f'生成 {_esc(data["generated"])}</p>')

    # 風險調整後裁決 (用最長 horizon，數據驅動：報酬最高 + 風險調整最高各挑一)
    verdict = ""
    if b and f:
        rows3 = [(lbl, v["horizons"].get(hmax, {})) for _, lbl, _, v in variants]
        best_ret = max(rows3, key=lambda r: r[1].get("l2", -999))
        best_rr = max(rows3, key=lambda r: r[1].get("ret_risk", -999))
        best_cal = max(rows3, key=lambda r: r[1].get("calmar", -999))
        fb = p.get("filter_breadth", 50); fv = p.get("filter_vol", 1.0)
        txt = (f"原本把廣度/量能當<b>加權評分</b>會稀釋動能；改成<b>門檻過濾</b>"
               f"（只選 廣度≥{fb:.0f}%、量能≥{fv} 的族群，再按 ret_20d 排）後，"
               f"H={hmax}d 的單期淨超額 {f['horizons'][hmax]['l2']:+.2f}% 與報酬/波動 "
               f"{f['horizons'][hmax]['ret_risk']} 是三者最高 → "
               f"<b>廣度/量能當『排除項』有價值，當『加分項』沒有</b>。<br>"
               f"但門檻過濾的最大回撤 -{f['horizons'][hmax]['max_dd']}% 也最深"
               f"（通過門檻的多是同向強勢股、一起崩），Calmar {f['horizons'][hmax]['calmar']} "
               f"未必最佳。<br>📌 報酬最高：<b>{best_ret[0]}</b>／報酬-波動最高："
               f"<b>{best_rr[0]}</b>／Calmar 最高：<b>{best_cal[0]}</b>。")
        verdict = (f'<section style="background:#eef4fb;border:1px solid #9bf"><h3>⚖️ '
                   f'三變體裁決 (H={hmax}d)</h3><p>{txt}</p></section>')

    # 指標比較表 (3 欄)
    def fmtv(v, fmt, pct):
        return f'{fmt.format(v)}{pct}' if v is not None else '—'
    def row(name, key, fmt="{:+.2f}", pct="", neg=False):
        cells = ""
        for _, _, _, v in variants:
            hv = v["horizons"].get(hrow, {})
            val = hv.get(key)
            if neg and val is not None:
                val = -val
            cells += f'<td class="num">{fmtv(val, fmt, pct)}</td>'
        return f'<tr><td>{name}</td>{cells}</tr>'
    def ci_row(name, key):
        """Render a CI row where JSON value is [lo, hi]."""
        cells = ""
        for _, _, _, v in variants:
            hv = v["horizons"].get(hrow, {})
            ci = hv.get(key)
            if ci and len(ci) == 2:
                sig = " ✓" if ci[0] > 0 else ""
                cells += f'<td class="num"><small>[{ci[0]:+.3f}, {ci[1]:+.3f}]{sig}</small></td>'
            else:
                cells += '<td class="num">—</td>'
        return f'<tr><td><small>{name}</small></td>{cells}</tr>'
    def ci_row_l2(name, key):
        """Render a CI row for L2 (2 decimal places)."""
        cells = ""
        for _, _, _, v in variants:
            hv = v["horizons"].get(hrow, {})
            ci = hv.get(key)
            if ci and len(ci) == 2:
                sig = " ✓" if ci[0] > 0 else ""
                cells += f'<td class="num"><small>[{ci[0]:+.2f}, {ci[1]:+.2f}]{sig}</small></td>'
            else:
                cells += '<td class="num">—</td>'
        return f'<tr><td><small>{name}</small></td>{cells}</tr>'
    def l2n_row(name, key):
        """Render L2 n and rebalance info."""
        cells = ""
        for _, _, _, v in variants:
            hv = v["horizons"].get(hrow, {})
            n_val = hv.get("l2_n"); rb = hv.get("l2_rebalance")
            cells += (f'<td class="num"><small>n={n_val}, reb={rb}d</small></td>'
                      if n_val is not None else '<td class="num">—</td>')
        return f'<tr><td><small>{name}</small></td>{cells}</tr>'
    tbl_rows = ""
    ncol = len(variants) + 1
    for h in hs:
        hrow = h
        tbl_rows += f'<tr><th colspan="{ncol}" style="background:#f0f3ff">持有 {h} 交易日</th></tr>'
        tbl_rows += row("IC (Spearman)", "ic", "{:+.3f}")
        tbl_rows += ci_row("IC 95% CI (block bootstrap)", "ic_ci")
        tbl_rows += row("多空價差 (高−低)", "spread", "{:+.2f}", "%")
        tbl_rows += row("高分組命中率", "hit", "{:.0f}", "%")
        tbl_rows += row("選股單期淨超額", "l2", "{:+.2f}", "%")
        tbl_rows += ci_row_l2("L2 95% CI (非重疊網格)", "l2_ci")
        tbl_rows += l2n_row("L2 非重疊樣本", "l2_n")
        tbl_rows += row("累積淨超額(總)", "total", "{:+.1f}", "%")
        tbl_rows += row("最大回撤 MaxDD", "max_dd", "{:.1f}", "%", neg=True)
        tbl_rows += row("報酬/波動", "ret_risk", "{:.2f}")
        tbl_rows += row("Calmar(總/MaxDD)", "calmar", "{:.2f}")
    th = "".join(f'<th class="num">{lbl}</th>' for _, lbl, _, _ in variants)
    table = (f'<section><h3>📊 三變體比較</h3>'
             f'<table class="report-table"><thead><tr><th>指標</th>{th}</tr></thead>'
             f'<tbody>{tbl_rows}</tbody></table>'
             f'<p class="small">門檻過濾變體因部分期間通過門檻的族群 &lt;6 個而略過，'
             f'樣本期數可能少於另兩者。CI ✓ = 下界 &gt; 0（95% 顯著正）。</p></section>')

    # 圖表
    hlabels = json.dumps([f"{h}日" for h in hs])
    def series(key):
        return [{"label": lbl, "color": col,
                 "data": [v["horizons"][h][key] for h in hs]}
                for _, lbl, col, v in variants]
    ic_ds = json.dumps([{"label": d["label"], "data": d["data"],
                         "backgroundColor": d["color"]} for d in series("ic")], ensure_ascii=False)
    sp_ds = json.dumps([{"label": d["label"], "data": d["data"],
                         "backgroundColor": d["color"]} for d in series("spread")], ensure_ascii=False)
    # 權益曲線 — 統一日期軸 (各變體 date 集合可能不同，缺的補 null)
    all_dates = sorted({e["date"] for _, _, _, v in variants
                        for e in v["horizons"][hmax]["equity"]})
    eq_labels = json.dumps(all_dates)
    eq_ds = []
    dash = {"strategy": [], "benchmark": [5, 4], "filter": [2, 3]}
    for key, lbl, col, v in variants:
        cum_by = {e["date"]: e["cum"] for e in v["horizons"][hmax]["equity"]}
        eq_ds.append({"label": lbl, "borderColor": col, "borderWidth": 2,
                      "pointRadius": 0, "tension": 0.1, "spanGaps": True,
                      "borderDash": dash.get(key, []),
                      "data": [cum_by.get(d) for d in all_dates]})
    eq_ds_json = json.dumps(eq_ds, ensure_ascii=False)

    charts = f"""
<section><h3>📈 IC by 持有天數（越高越準，>0.1 算不錯）</h3>
  <canvas id="ic" height="90"></canvas></section>
<section><h3>📊 多空價差 by 持有天數（高分組−低分組 超額%）</h3>
  <canvas id="sp" height="90"></canvas></section>
<section><h3>💰 選股權益曲線（H={hmax}d 累積淨超額%，非複利）</h3>
  <canvas id="eq" height="120"></canvas>
  <p class="small">每個 rebalance 點買前 {p["topk"]} 名族群 Top5 領漲股、持有 {hmax} 日、
    扣 {p["cost"]}% 成本後贏大盤的累計。三條線 = 三種選股訊號。</p></section>"""

    fb = p.get("filter_breadth", 50); fv = p.get("filter_vol", 1.0)
    reb = p.get("rebalance", 5); tk = p.get("topk", 3); cst = p.get("cost", 0.4)
    hlist = "、".join(f"{h}日" for h in hs)
    method = (
      '<section><h3>🔬 詳細回測方法</h3>'
      '<div class="small" style="line-height:1.7">'
      '<b>① 資料與重建手法</b><br>'
      f'用 FinMind 歷史日線（自 {_esc(s["start"][:4])} 起）抓 34 族群全部成員股 + 加權指數。'
      '每個交易日 t 的訊號都<b>只用 ≤ t 的資料</b> point-in-time 重建（直接呼叫正式程式的 '
      '<code>compute_score_for_date</code> / 同口徑廣度量能函式），所以測的是「當下真的看得到的訊號」，'
      '不是事後諸葛；也因此不受存檔天數限制，可回溯到價格資料起點。<br><br>'

      '<b>② 三個比較變體</b><br>'
      f'• <b>純動能</b>：族群成員等權近 20 日報酬(ret_20d) 直接排名。<br>'
      f'• <b>動能+門檻過濾</b>（正式採用）：族群須先通過 <b>廣度≥{fb:.0f}%</b>（成員過 5/20 日均線比例平均）'
      f'<b>且 量比≥{fv}</b>（近 5 日量 ÷ 近 20 日量），通過者再按 ret_20d 排名；沒過門檻剔除。'
      '＝把廣度/量能當「排除項」而非加分項。<br>'
      '（原複合分數加權法經回測較差，已淘汰、本頁不再顯示。）<br><br>'

      '<b>③ 回測流程</b><br>'
      f'從第 20 個交易日起（暖身夠算 20 日報酬），<b>每 {reb} 個交易日</b>取一個進場點 t：<br>'
      '　1. 重算所有族群分數、排名<br>'
      f'　2. 看接下來 <b>{hlist}</b>（持有天數 H）各族群的報酬<br>'
      '　3. 族群報酬減去同期加權指數報酬 = <b>超額報酬</b>（衡量贏不贏大盤）<br>'
      f'　4. 選股(Layer2)：買<b>前 {tk} 名</b>族群的 Top5 領漲股、等權、持有 H 日、'
      f'扣 <b>{cst}% 來回成本</b><br><br>'

      '<b>④ 指標定義</b><br>'
      '• <b>IC（資訊係數）</b>：當期「分數排名」與「之後超額報酬排名」的 Spearman 等級相關，'
      '−1~+1，>0.1 算不錯；旁邊 % 是 63 期裡 IC 為正的比例（穩定度）。<br>'
      '• <b>多空價差</b>：高分前1/3族群平均超額 − 低分後1/3族群平均超額，越大代表分數越能分辨強弱。<br>'
      '• <b>命中率</b>：高分組之後贏大盤的期數比例。<br>'
      '• <b>選股單期淨超額</b>：Layer2 每次進場、扣成本後贏大盤的平均 %。<br>'
      '• <b>累積淨超額</b>：把每期淨超額累加（非複利）。<br>'
      '• <b>最大回撤 MaxDD</b>：累積曲線從歷史高點回落的最大跌幅。<br>'
      '• <b>報酬/波動</b>：單期淨超額 ÷ 單期報酬標準差（類 Sharpe，越高越穩）。<br>'
      '• <b>Calmar</b>：總報酬 ÷ 最大回撤（每承受 1 單位回撤換到多少報酬）。<br><br>'

      '<b>⑤ 成本與假設</b><br>'
      f'來回成本固定 {cst}%（手續費+稅+滑價粗估）。族群指數/報酬為成員等權。'
      '選股 leaders 取 ret_5d>−5%、按 ret_20d 排序的前 5 名。'
      '</div></section>')

    caveat = ('<section><h3>⚠ 解讀與限制</h3><p class="small">'
              '1. 廣度/量能<b>當加權評分</b>會稀釋動能；<b>當門檻過濾</b>才有提升'
              '（報酬+報酬/波動），但會放大回撤。<br>'
              '2. 樣本 ~16 個月、63 期，且此段多頭/動能行情友善，換盤整盤未必續強。<br>'
              '3. 族群成員用當前 concepts.json 套過去 = 輕微 look-ahead。<br>'
              '4. 成本固定 0.4%，小型 leaders 實際滑價可能更差。<br>'
              '5. L2 權益曲線使用<b>非重疊網格</b>（步進 = max(rebalance, H)），'
              '避免 5d rebalance × 20d 持有造成 4x 報酬重複計數（舊版 H=20 total '
              '~334% 即為灌水；修正後為 ~72%）。IC 仍以較密的 rebalance 網格計算（允許重疊觀察），'
              '並加 block bootstrap 95% CI 校正自相關。<br>'
              '6. L2 信賴區間 ✓ = 下界 &gt; 0（95% 統計顯著）；H=20 樣本數 n≈16，CI 較寬、勿過度解讀。'
              '</p></section>')

    js = f"""<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const L={hlabels};
function bar(id,ds){{
  new Chart(document.getElementById(id),{{type:'bar',
    data:{{labels:L,datasets:ds}},
    options:{{responsive:true,plugins:{{legend:{{position:'top'}}}}}}}});
}}
bar('ic',{ic_ds});
bar('sp',{sp_ds});
new Chart(document.getElementById('eq'),{{type:'line',
  data:{{labels:{eq_labels},datasets:{eq_ds_json}}},
  options:{{responsive:true,plugins:{{legend:{{position:'top'}}}},
    scales:{{y:{{title:{{display:true,text:'累積淨超額 %'}}}}}}}}}});
</script>"""
    glossary = _glossary_section([
        "持有天數 (H)", "IC (資訊係數)", "多空價差", "超額報酬 (vs 大盤)",
        "淨超額", "alpha", "贏大盤率 (beat rate)", "賺錢率 / 勝率",
        "累積淨超額 / 權益曲線", "最大回撤 (MaxDD)", "報酬/波動", "Calmar",
        "point-in-time", "CI / 信賴區間", "非重疊 rebalance",
        "block bootstrap CI", "樣本不足警語 (n<30)"])
    return (head + cards + meta + verdict + table + charts + method
            + glossary + caveat + js + tail)


@app.route("/concept-backtest")
def concept_backtest():
    path = os.path.join(HERE, "cache", "concept_backtest.json")
    if not os.path.exists(path):
        return _render_concept_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_concept_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_concept_backtest_page(data=data)


def _render_second_wave_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/concept-backtest">🧪 族群策略回測</a>'
           '<a href="/second-wave-backtest">🌊 第二波回測</a></nav>')
    css = """<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:1100px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  section h3 { margin:0 0 8px 0; font-size:1.05em; color:#444; }
  table.report-table { width:100%; border-collapse:collapse; font-size:.9em; }
  table.report-table th,table.report-table td { padding:6px 10px; border-bottom:1px solid #eee; text-align:left; }
  table.report-table th { background:#fafafa; font-weight:600; color:#555; }
  table.report-table .num { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:#060; } .neg { color:#c30; } .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  .cards { display:flex; gap:10px; flex-wrap:wrap; }
  .card { flex:1; min-width:130px; background:#f3faf5; border:1px solid #cfe8d8; border-radius:6px; padding:10px 12px; }
  .card .v { font-size:1.4em; font-weight:700; } .card .k { font-size:.8em; color:#777; }
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>強勢股第二波回測</title>{css}</head><body>{nav}'
            f'<h1>🌊 強勢股第二波 — 回測（事件研究）</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>tw_second_wave_backtest.py --json-out '
                       'concept_momentum/cache/second_wave_backtest.json</code></p></section>') + tail
    r = data["result"]; p = data["params"]
    hs = [str(h) for h in p["horizons"]]
    hmax = hs[-1]
    H = r["horizons"]
    def cls(v): return "pos" if v is not None and v > 0 else "neg"
    hh = H[hmax]
    _edge_v = hh.get("edge_mean", hh.get("edge", 0))
    _edge_ci = hh.get("edge_ci")
    _edge_ci_str = (f"CI [{_edge_ci[0]:+.2f},{_edge_ci[1]:+.2f}]" if _edge_ci else "淨超額−基準")
    _ci = hh.get("exc_ci", [0, 0])
    cards = (
        f'<p class="small" style="margin:.2em 0">摘要＝持有 {hmax} 交易日</p><div class="cards">'
        f'<div class="card"><div class="k">絕對報酬(均)</div>'
        f'<div class="v {cls(hh["abs_mean"])}">{hh["abs_mean"]:+.1f}%</div>'
        f'<div class="small">賺錢率 {hh["win"]:.0f}%</div></div>'
        f'<div class="card"><div class="k">淨超額 vs 大盤</div>'
        f'<div class="v {cls(hh["net"])}">{hh["net"]:+.1f}%</div>'
        f'<div class="small">贏大盤率 {hh["beat"]:.0f}%</div></div>'
        f'<div class="card"><div class="k">超額中位數</div>'
        f'<div class="v {cls(hh["exc_med"])}">{hh["exc_med"]:+.1f}%</div>'
        f'<div class="small">均值 {hh["exc_mean"]:+.1f}%</div></div>'
        f'<div class="card"><div class="k">95% CI (超額均)</div>'
        f'<div class="v" style="font-size:.9em">[{_ci[0]:+.2f}, {_ci[1]:+.2f}]</div>'
        f'<div class="small">t={hh.get("t", 0):.2f}'
        f'{"  ✓顯著" if _ci[0] > 0 else ""}</div></div>'
        f'<div class="card"><div class="k">訊號 edge (均)</div>'
        f'<div class="v {cls(_edge_v)}">{_edge_v:+.1f}%</div>'
        f'<div class="small">{_edge_ci_str}</div></div>'
        f'<div class="card"><div class="k">進場樣本</div>'
        f'<div class="v">{r["n_episodes"]}</div>'
        f'<div class="small">{r["n_signal_days"]} 訊號日・除權息剔 {r.get("n_skipped_div", 0)}</div></div></div>')
    meta = (f'<p class="small">universe {r["universe"]} 檔（{r.get("universe_label","概念股子集")}）・'
            f'{r["start"]}~{r["end"]}・扣 {r["cost"]}% 成本・生成 {_esc(data["generated"])}</p>')

    def row(name, key, fmt="{:+.2f}", pct="%"):
        cells = "".join(f'<td class="num">{fmt.format(H[h].get(key, 0))}{pct}</td>' for h in hs)
        return f'<tr><td>{name}</td>{cells}</tr>'
    def ci_row(name, key):
        def _fmt(hd):
            ci = hd.get(key)
            if not ci:
                return "—"
            return f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"
        cells = "".join(f'<td class="num" style="white-space:nowrap">{_fmt(H[h])}</td>'
                        for h in hs)
        return f'<tr><td>{name}</td>{cells}</tr>'
    th = "".join(f'<th class="num">{h}日</th>' for h in hs)
    tbl = (f'<section><h3>📊 各持有天數表現</h3>'
           f'<table class="report-table"><thead><tr><th>指標</th>{th}</tr></thead><tbody>'
           + row("絕對報酬(均)", "abs_mean")
           + row("賺錢率", "win", "{:.0f}")
           + row("超額 vs 大盤(均)", "exc_mean")
           + row("超額 中位數", "exc_med")
           + ci_row("95% CI (超額均)", "exc_ci")
           + row("t-stat", "t", "{:.2f}", "")
           + row("贏大盤率", "beat", "{:.0f}")
           + row("扣成本淨超額", "net")
           + row("⭐訊號 edge (均)", "edge_mean")
           + ci_row("edge 95% CI", "edge_ci")
           + '</tbody></table>'
           '<p class="small">edge_mean = (股票超額−大盤) − 同日隨機 k=100 檔的基準超額。'
           'CI 含 0 = 該 horizon 無統計顯著 edge；edge_ci 全正 = 顯著。</p></section>')

    # 圖表
    hlabels = json.dumps([f"{h}日" for h in hs])
    edge_d = json.dumps([H[h].get("edge_mean", H[h].get("edge", 0)) for h in hs])
    _base_vals = []
    for _h in hs:
        if "baseline" in H[_h]:
            _base_vals.append(H[_h]["baseline"])
        elif "net" in H[_h] and "edge_mean" in H[_h]:
            _base_vals.append(H[_h]["net"] - H[_h]["edge_mean"])
        else:
            _base_vals.append(None)
    _has_base = any(v is not None for v in _base_vals)
    base_d = json.dumps([v if v is not None else 0 for v in _base_vals]) if _has_base else None
    net_d = json.dumps([H[h]["net"] for h in hs])
    eq = H[hmax]["equity"]
    eq_labels = json.dumps([e["date"] for e in eq])
    eq_cum = json.dumps([e["cum"] for e in eq])
    charts = f"""
<section><h3>📈 訊號 edge vs 基準 by 持有天數</h3>
  <canvas id="edge" height="90"></canvas>
  <p class="small">綠=訊號淨超額、灰=基準、藍=edge(差)。第二波是慢熱型，
    短天期接近基準，{hmax}日才拉開。</p></section>
<section><h3>💰 進場權益曲線（H={hmax}d 累積淨超額%，非複利）</h3>
  <canvas id="eq" height="110"></canvas>
  <p class="small">每觸發一次第二波就買進、持有 {hmax} 日、扣 {r["cost"]}% 成本後贏大盤的累計。</p></section>"""

    method = (
      '<section><h3>🔬 詳細回測方法</h3><div class="small" style="line-height:1.7">'
      '<b>① 為何用事件研究</b><br>'
      '第二波是<b>每檔股票的型態訊號</b>（強漲→急殺15-25%→反彈啟動），不是族群排名。'
      '所以不算 IC/多空，而是：每當某股某日觸發訊號，量它之後的報酬，比基準看有沒有 edge。<br><br>'
      '<b>② 訊號重建</b><br>'
      '直接 import 正式程式的 <code>detect_second_wave</code>（七項過濾：強勢底盤≥30%、'
      '高點近60日、急跌15-25%、急跌5-15日、反彈≥5%、量能甦醒、未破前高），對每檔股票'
      '<b>逐日 point-in-time</b> 跑（只用 ≤t 的資料）。<br><br>'
      '<b>③ episode 去重</b><br>'
      '同一波會連續觸發好幾天，只取<b>首次觸發</b>當進場點（避免重複樣本灌水）。'
      f'本次 {r["n_signal_days"]} 個訊號日 → 去重成 {r["n_episodes"]} 個進場。<br><br>'
      '<b>④ 三個比較對象</b><br>'
      '• <b>絕對報酬</b>：買進後 H 日漲跌%。<br>'
      '• <b>超額 vs 大盤</b>：減去同期加權指數，看贏不贏大盤。<br>'
      '• <b>基準 (edge baseline)</b>：與事件<b>同日期</b>隨機抽 k=100 檔股票，'
      '算它們平均超額（date-matched baseline）；訊號 edge = 超額 − 基準。<br><br>'
      '<b>⑤ 成本/資料</b><br>'
      f'扣 {r["cost"]}% 來回成本。universe = {r.get("universe_label","概念股子集")} {r["universe"]} 檔。'
      '</div></section>')

    usage = (
      '<section style="border-left:4px solid #e8a000;">'
      '<h3>📌 使用時機與限制</h3><div class="small" style="line-height:1.8">'
      '<b>✅ 適用時機</b><br>'
      '• <b>動能市（多頭、資金追強勢股的市況）</b>：分年 OOS 顯示本策略的 edge 集中在 2025-26 '
      '動能市（2026 全樣本 +2.4%、早期+大額 ⭐ 層 +12.9%）；<b>2022-2024 三年全策略超額 ≈0</b>，'
      '2022 熊市為負 — 大盤轉弱時應停用或大幅降低倉位。<br>'
      '• <b>持有約 20 個交易日</b>：短抱 5-10 天期望為負（訊號後第一週常還在洗盤）。<br>'
      '• <b>分散持有整份名單</b>：報酬是樂透型（中位數 -3~-4%、靠少數大贏家），'
      '單押一兩檔大概率體驗到中位數。<br>'
      '• 名單是「pattern 已成形的候選池」，進場前自查基本面沒轉壞、急跌非利空所致。<br>'
      '<b>❌ 不適用 / 已知限制</b><br>'
      '• 盤整或空頭市。⚠ 注意：<b>沒有可靠的「事前」動能市判斷指標</b> — 已回測六種'
      '（指數趨勢、寬度、漲停熱度、策略自體健康度），每一種在 2022-24 的 ON 條件下 ⭐ 仍為負；'
      '2024 也是指數多頭年但本策略無效，「動能市」非指數趨勢可捕捉。<br>'
      '• 短線交易（5-10 日無 edge）、重倉單押。<br>'
      '• <b>不要加機械式停損</b>：已回測四種出場（停損 trough / 移動停利 10% / 兩者並用 / 延長 cap40），'
      '全部輸給固定 20 天（⭐ 組 +10.0% vs +4.5~+7.5%）— 高波動股的收盤觸發式出場全是 whipsaw，'
      '停損專門賣在低點。風控靠<b>分散</b>與 20 天時間出場。<br>'
      '• 純技術面訊號：不看基本面與消息，急跌若是基本面惡化（非洗盤）照樣入選'
      '（可參考名單「借」欄：借↑ = 空方在急跌中加碼，跨年較穩的避開訊號）。<br>'
      '<b>🔭 regime 即時監測</b>：既然事前指標全敗，唯一可靠的是<b>事後追蹤</b> — '
      '訊號成效頁的 ⭐ 分層桶就是活體檢測：⭐ 組持續領先 = 動能 regime 健在；'
      '⭐ 開始失效 = regime 轉換警訊，考慮停用本策略。'
      '<a href="/signal-outcomes">→ 訊號成效</a></div></section>')

    is_all = p.get("universe") == "all" or r.get("universe_label") == "全市場"
    uni_cav = ('3. universe 為<b>全市場</b>（含小型低液性股），與正式 cron 一致；'
               '但這段多頭友善，空頭盤 edge 可能不同。<br>'
               if is_all else
               '3. universe 是概念股子集（正式 cron 掃全市場），且這段多頭友善，'
               '全市場/空頭盤的 edge 可能不同。<br>')
    caveat = ('<section><h3>⚠ 解讀與限制</h3><p class="small">'
              '1. <b>慢熱型</b>：5/10 日 edge 很小、贏大盤率 &lt;50%、中位數可能為負；'
              '要到 20 日才有明顯 edge → 第二波是「抱一個月」的 setup，不是短打。<br>'
              '2. 報酬右偏：均值 &gt;&gt; 中位數，靠少數大贏家拉高，多數只是接近大盤。<br>'
              + uni_cav +
              f'4. 成本 {r["cost"]}%（手續費6折+證交稅，零滑價假設），急跌反彈股流動性差時滑價可能更大；'
              '全市場含小型股時滑價影響更明顯。</p></section>')

    _base_dataset = (f"{{label:'基準',data:{base_d},backgroundColor:'#bbb'}},"
                    if _has_base else "")
    js = f"""<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const L={hlabels};
new Chart(document.getElementById('edge'),{{type:'bar',
  data:{{labels:L,datasets:[
    {{label:'淨超額',data:{net_d},backgroundColor:'#2a9d4a'}},
    {_base_dataset}
    {{label:'edge',data:{edge_d},backgroundColor:'#3366cc'}}]}},
  options:{{responsive:true,plugins:{{legend:{{position:'top'}}}}}}}});
new Chart(document.getElementById('eq'),{{type:'line',
  data:{{labels:{eq_labels},datasets:[{{label:'第二波進場',data:{eq_cum},
    borderColor:'#2a9d4a',borderWidth:2,pointRadius:0,tension:.1}}]}},
  options:{{responsive:true,plugins:{{legend:{{position:'top'}}}},
    scales:{{y:{{title:{{display:true,text:'累積淨超額 %'}}}}}}}}}});
</script>"""
    glossary = _glossary_section([
        "持有天數 (H)", "事件研究", "episode 去重", "絕對報酬", "超額報酬 (vs 大盤)",
        "淨超額", "基準 (baseline)", "edge", "賺錢率 / 勝率",
        "贏大盤率 (beat rate)", "中位數 vs 均值", "累積淨超額 / 權益曲線",
        "point-in-time", "CI / 信賴區間", "t 統計量",
        "日期配對基準 (date-matched)", "除權息剔除",
        "分層標記 (⭐/◐/▽)", "借券急跌標記 (借↓/借↑)"])
    return head + cards + usage + meta + tbl + charts + method + glossary + caveat + js + tail


@app.route("/second-wave-backtest")
def second_wave_backtest():
    path = os.path.join(HERE, "cache", "second_wave_backtest.json")
    if not os.path.exists(path):
        return _render_second_wave_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_second_wave_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_second_wave_backtest_page(data=data)


def _render_intraday_sim_page(code: str = "", data: dict | None = None,
                              error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/intraday-sim-backtest">🧪 此系統的校準回測</a>'
           '<a href="/concept-backtest">族群策略回測</a>'
           '<a href="/second-wave-backtest">第二波回測</a></nav>')
    css = """<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:1200px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  section h3 { margin:0 0 4px 0; font-size:1.02em; color:#444; }
  .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  form { display:flex; gap:6px; align-items:center; }
  input[type=text]{ width:90px; padding:6px 8px; border:1px solid #ccc; border-radius:4px; }
  button{ padding:6px 14px; background:#0066cc; color:#fff; border:none; border-radius:4px; cursor:pointer; }
  .grid3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; }
  @media (max-width:900px){ .grid3{ grid-template-columns:1fr; } }
  .meth { font-size:.8em; color:#555; background:#f3f6fb; border-radius:4px; padding:5px 8px; margin:4px 0; }
  table.report-table{ width:100%; border-collapse:collapse; font-size:.85em; }
  table.report-table td,table.report-table th{ padding:4px 8px; border-bottom:1px solid #eee; text-align:left; }
  .num{ text-align:right; font-variant-numeric:tabular-nums; }
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>盤中走勢模擬</title>{css}</head><body>{nav}'
            f'<h1>📉 股價盤中走勢模擬</h1>'
            f'<section><form action="/intraday-sim" method="get">'
            f'<input type="text" name="code" placeholder="股號" value="{_esc(code)}" required>'
            f'<button type="submit">模擬下一交易日</button>'
            f'<span class="small">輸入股號，模擬下一交易日 09:00–13:30 走勢</span>'
            f'</form></section>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        return head + ('<section class="small">輸入股號開始。根據該股<b>籌碼/型態/量價</b>'
                       '找歷史相似日，看它們隔天怎麼走 → A 情境劇本 / B 信心帶 / '
                       'C 蒙地卡羅三種模擬並列。<br>⚠ 盤中走勢本質不可精確預測，'
                       '本系統是「情境參考」非預言。</section>') + tail

    pc = data["prev_close"]
    grid = data["grid"]
    glabels = json.dumps([m if m.endswith(":00") or m.endswith(":30") else "" for m in grid])
    # 統一 y 範圍
    allvals = []
    for s in (data.get("scenarios") or []):
        if s.get("path"):
            allvals += s["path"]
    for key in ("band", "monte_carlo"):
        b = data.get(key)
        if b:
            allvals += b["p10"] + b["p90"]
    mkt = data.get("market") or {}
    for s in (mkt.get("scenarios") or []):
        if s.get("path"):
            allvals += s["path"]
    if mkt.get("band"):
        allvals += mkt["band"]["p10"] + mkt["band"]["p90"]
    ymin = math.floor(min(allvals + [-1])) - 1
    ymax = math.ceil(max(allvals + [1])) + 1

    info = (f'<section class="small">{_esc(data["code"])}・基準前收 <b>{pc}</b>'
            f'（{_esc(data["as_of"])} 收盤）・相似日樣本 <b>{data["n_analog"]}</b>'
            f'（個股自己歷史池，平均距離 {data.get("avg_dist")}）<br>'
            f'⚠ 盤中走勢不可精確預測；下列為「過去最像今天的日子隔天怎麼走」的情境參考，'
            f'非預言。y 軸左=距前收%、右=換算股價。</section>')

    def scen_tbl(scen):
        srows = "".join(
            f'<tr><td>{_esc(s["name"])}</td><td class="num">{s["prob"]:.0f}%</td>'
            f'<td class="num">n={s["count"]}</td>'
            f'<td class="num">{("收 %+.1f%%" % s["path"][-1]) if s.get("path") else "—"}</td></tr>'
            for s in scen)
        return (f'<table class="report-table"><thead><tr><th>劇本</th>'
                f'<th class="num">機率</th><th class="num">樣本</th>'
                f'<th class="num">預估收盤</th></tr></thead><tbody>{srows}</tbody></table>')

    scen = data.get("scenarios") or []
    mscen = mkt.get("scenarios") or []
    mn = mkt.get("n_analog", 0)
    mkt_note = (f"全市場 {mn} 個相似日（技術/量價子集，<b>不含籌碼</b>；"
                f"平均距離 {mkt.get('avg_dist')}）" if mn else
                ("（" + _esc(mkt.get("error", "市場池資料不足")) + "）"))

    charts = f"""
<h3 style="margin:6px 0">① 個股自己歷史池（完整特徵：籌碼+型態+量價）</h3>
<div class="grid3">
  <section><h3>A 情境劇本</h3>
    <div class="meth">過去籌碼/型態最像今天的 {data['n_analog']} 天，隔天走勢分群(機率見圖例)。</div>
    <canvas id="cA" height="150"></canvas>{scen_tbl(scen)}</section>
  <section><h3>B 最可能路徑 + 信心帶</h3>
    <div class="meth">{data['n_analog']} 個相似日逐分鐘中位數(粗線) + 25–75%(深) + 10–90%(淺)。</div>
    <canvas id="cB" height="150"></canvas></section>
  <section><h3>C 純蒙地卡羅(對照)</h3>
    <div class="meth">不看籌碼，只用該股波動度+開盤跳空隨機模擬，當「無資訊優勢」基準。</div>
    <canvas id="cC" height="150"></canvas></section>
</div>
<h3 style="margin:10px 0 6px">② 全市場池（技術+量價子集，無歷史籌碼）</h3>
<div class="grid3">
  <section><h3>A 情境劇本（全市場）</h3>
    <div class="meth">{mkt_note}：技術型態最像今天的全市場股票日，隔天走勢分群。</div>
    {'<canvas id="cAm" height="150"></canvas>' + scen_tbl(mscen) if mscen else '<p class="small">'+mkt_note+'</p>'}</section>
  <section><h3>B 信心帶（全市場）</h3>
    <div class="meth">全市場相似日逐分鐘中位數+信心帶。</div>
    {'<canvas id="cBm" height="150"></canvas>' if mkt.get('band') else '<p class="small">無資料</p>'}</section>
  <section><h3>C 蒙地卡羅</h3>
    <div class="meth">同上方 C（純統計基準與池無關）。</div>
    <p class="small">蒙地卡羅是純波動度模擬，跟用哪個池無關 → 見上方 ① 的 C。</p></section>
</div>"""

    gloss = ('<section><h3>📚 怎麼看</h3><p class="small">'
             '• <b>距前收%</b>：相對昨收的漲跌，0%＝平盤。右軸換算成股價。<br>'
             '• <b>A 情境劇本</b>：相似日隔天「分群」後的代表走勢，機率=該群佔比。'
             '看「哪種劇本機率高」+「劇本之間方向是否一致」。<br>'
             '• <b>B 信心帶</b>：把所有相似日疊起來的分布，帶越窄=越多相似日走法一致、越可信。<br>'
             '• <b>C 蒙地卡羅</b>：純隨機基準。若 A/B 的方向跟 C 差不多，代表「籌碼/型態沒給額外資訊」；'
             '若 A/B 明顯偏一邊而 C 中性，才是相似日法真的看出東西。<br>'
             '⚠ 全部是機率參考，不是預測那條線會長這樣。樣本少(相似日不足)時可信度低。</p></section>')

    # JS 資料
    def ser(arr):
        return json.dumps([round(x, 3) for x in arr])
    colors = ["#c0392b", "#e67e22", "#27ae60", "#2980b9", "#8e44ad", "#16a085", "#7f8c8d"]
    a_ds = []
    ci = 0
    for s in scen:
        if not s.get("path"):
            continue
        a_ds.append({"label": f'{s["name"]} {s["prob"]:.0f}%', "data": [round(x, 3) for x in s["path"]],
                     "borderColor": colors[ci % len(colors)], "borderWidth": 2,
                     "pointRadius": 0, "tension": 0.2})
        ci += 1
    a_ds_json = json.dumps(a_ds, ensure_ascii=False)
    band = data.get("band") or {"median": [], "p25": [], "p75": [], "p10": [], "p90": []}
    mc = data["monte_carlo"]
    # 市場池 A 線
    ma_ds = []
    ci = 0
    for s in mscen:
        if not s.get("path"):
            continue
        ma_ds.append({"label": f'{s["name"]} {s["prob"]:.0f}%', "data": [round(x, 3) for x in s["path"]],
                      "borderColor": colors[ci % len(colors)], "borderWidth": 2,
                      "pointRadius": 0, "tension": 0.2})
        ci += 1
    ma_ds_json = json.dumps(ma_ds, ensure_ascii=False)
    mband = mkt.get("band")

    js = f"""<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const G={glabels}, PC={pc}, YMIN={ymin}, YMAX={ymax};
const yscales = {{
  y:{{position:'left',min:YMIN,max:YMAX,title:{{display:true,text:'距前收 %'}}}},
  yp:{{position:'right',min:YMIN,max:YMAX,grid:{{drawOnChartArea:false}},
      title:{{display:true,text:'股價'}},
      ticks:{{callback:v=>(PC*(1+v/100)).toFixed(1)}}}}
}};
const baseOpt={{responsive:true,interaction:{{mode:'index',intersect:false}},
  plugins:{{legend:{{position:'top',labels:{{boxWidth:12,font:{{size:10}}}}}}}},
  scales:yscales,elements:{{point:{{radius:0}}}}}};
new Chart(document.getElementById('cA'),{{type:'line',
  data:{{labels:G,datasets:{a_ds_json}}},options:baseOpt}});
function mkBand(id,b,c){{
  new Chart(document.getElementById(id),{{type:'line',
   data:{{labels:G,datasets:[
     {{label:'90%',data:b.p90,borderColor:'transparent',backgroundColor:c+'18',fill:'+1',pointRadius:0}},
     {{label:'10%',data:b.p10,borderColor:'transparent',backgroundColor:'transparent',fill:false,pointRadius:0}},
     {{label:'75%',data:b.p75,borderColor:'transparent',backgroundColor:c+'33',fill:'+1',pointRadius:0}},
     {{label:'25%',data:b.p25,borderColor:'transparent',backgroundColor:'transparent',fill:false,pointRadius:0}},
     {{label:'中位數',data:b.median,borderColor:c,borderWidth:2.5,pointRadius:0,tension:.15}}
   ]}},options:{{...baseOpt,plugins:{{legend:{{display:false}}}}}}}});
}}
mkBand('cB',{json.dumps(band)},'#2980b9');
mkBand('cC',{json.dumps(mc)},'#7f8c8d');
if(document.getElementById('cAm')) new Chart(document.getElementById('cAm'),
  {{type:'line',data:{{labels:G,datasets:{ma_ds_json}}},options:baseOpt}});
{("if(document.getElementById('cBm')) mkBand('cBm'," + json.dumps(mband) + ",'#16a085');") if mband else ""}
</script>"""
    return head + info + charts + gloss + js + tail


def _render_intraday_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/intraday-sim">📉 盤中走勢模擬</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:900px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.4em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  section h3{margin:0 0 6px 0;font-size:1.05em;color:#444;}
  table.report-table{width:100%;border-collapse:collapse;font-size:.9em;}
  table.report-table td,table.report-table th{padding:6px 10px;border-bottom:1px solid #eee;text-align:left;}
  .num{text-align:right;font-variant-numeric:tabular-nums;} .small,small{font-size:.85em;color:#666;}
  .error{background:#fee;border:1px solid #f99;padding:12px;border-radius:4px;color:#c00;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>盤中模擬回測</title>{css}</head><body>{nav}'
            f'<h1>🧪 盤中走勢模擬 — 收盤層級校準回測</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>tw_intraday_sim_backtest.py --json-out '
                       'concept_momentum/cache/intraday_sim_backtest.json</code></p></section>') + tail
    pools = []
    if data.get("result"):
        pools.append(("market", data["result"]))
    if data.get("result_self"):
        pools.append(("self", data["result_self"]))
    if not pools:
        return head + '<section>無有效結果</section>' + tail

    js_charts = []
    body = ""
    for idx, (key, r) in enumerate(pools):
        naive = max(r["base_up_pct"], 100 - r["base_up_pct"])
        has_skill = r["skill_vs_zero"] > 2
        has_dir = r["dir_hit_pct"] > naive + 2
        if has_dir or has_skill:
            vtxt = f"<b>{r['pool']}</b>：在收盤層級有些微預測力（skill {r['skill_vs_zero']}%、方向 {r['dir_hit_pct']}%）。"
            vbg, vbd = "#eaf6ea", "#9c9"
        else:
            vtxt = (f"<b>{r['pool']}：收盤層級幾乎沒有預測力。</b> "
                    f"方向命中 {r['dir_hit_pct']}% ≈ 擲銅板、輸給「總是猜{'跌' if r['base_up_pct']<50 else '漲'}」的 {naive:.0f}%；"
                    f"相似日中位數誤差比「猜 0%」還{'大' if r['skill_vs_zero']<0 else '小'} (skill {r['skill_vs_zero']}%)；"
                    f"信心帶偏窄(過度自信)。")
            vbg, vbd = "#fdf2e0", "#e0a040"
        body += (f'<section style="background:{vbg};border:1px solid {vbd}">'
                 f'<h3>⚖️ {r["pool"]}（{r["n"]} 測試點）</h3><p class="small">{vtxt}</p>'
                 f'<table class="report-table"><tbody>'
                 f'<tr><td>方向命中率</td><td class="num">{r["dir_hit_pct"]}%</td>'
                 f'<td class="small">對照「總是猜{"跌" if r["base_up_pct"]<50 else "漲"}」{naive:.0f}%；≈50%=無方向力</td></tr>'
                 f'<tr><td>　有信心子集</td><td class="num">{r.get("dir_hit_conf_pct")}%</td><td></td></tr>'
                 f'<tr><td>信心帶 25–75% 覆蓋</td><td class="num">{r["cover_2575_pct"]}%</td>'
                 f'<td class="small">目標 50%；偏低=帶太窄</td></tr>'
                 f'<tr><td>信心帶 10–90% 覆蓋</td><td class="num">{r["cover_1090_pct"]}%</td>'
                 f'<td class="small">目標 80%</td></tr>'
                 f'<tr><td>MAE 相似日 / 猜0%</td><td class="num">{r["mae_analog"]} / {r["mae_zero"]}</td>'
                 f'<td class="small">相似日要更小才有用</td></tr>'
                 f'<tr><td>⭐ skill vs 猜0%</td><td class="num">{r["skill_vs_zero"]}%</td>'
                 f'<td class="small">正=有降誤差；負=無技巧</td></tr>'
                 f'</tbody></table>'
                 f'<canvas id="cc{idx}" height="100"></canvas>'
                 f'<p class="small">分位校準：預測中位數分 8 組的(預測,實際)平均，'
                 f'單調沿 45°=有方向訊息；散亂=沒。</p></section>')
        cl = json.dumps([c["pred"] for c in r["calib_curve"]])
        ca = json.dumps([c["actual"] for c in r["calib_curve"]])
        js_charts.append(f'new Chart(document.getElementById("cc{idx}"),{{type:"scatter",'
                         f'data:{{datasets:[{{data:{cl}.map((p,i)=>({{x:p,y:{ca}[i]}})),'
                         f'backgroundColor:"#2980b9",pointRadius:5}}]}},'
                         f'options:{{plugins:{{legend:{{display:false}}}},'
                         f'scales:{{x:{{title:{{display:true,text:"預測%"}}}},'
                         f'y:{{title:{{display:true,text:"實際%"}}}}}}}}}});')
    method = ('<section><h3>🔬 方法 + 結論</h3><p class="small">'
              '走前測：每個測試 (股票,日 t)，相似日<b>只取 &lt;t 過去日</b>(無未來洩漏)，'
              'K=40 最相似歷史日 → 它們<b>隔天日線收盤</b>報酬分布當預測，跟<b>實際隔天收盤</b>比。'
              '<b>市場技術池</b>=全市場、6 技術特徵、無籌碼；<b>個股自己池</b>=該股自己歷史、'
              '14 特徵(含借券/融資/法人)。<br>'
              '📌 兩池結論一致：<b>隔天「開盤→收盤」方向接近隨機，籌碼也沒救</b>'
              '(符合市場效率)。→ 本模擬系統請當<b>「情境/分布視覺化」</b>用，'
              '看「類似情況歷史走過哪些範圍」，<b>別當方向預測器</b>。<br>'
              '此測收盤結果；盤中路徑形狀校準是更後面的事。</p></section>')
    js = ('<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
          '<script>' + "".join(js_charts) + '</script>')
    return head + body + method + js + tail


@app.route("/intraday-sim-backtest")
def intraday_sim_backtest():
    path = os.path.join(HERE, "cache", "intraday_sim_backtest.json")
    if not os.path.exists(path):
        return _render_intraday_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_intraday_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_intraday_backtest_page(data=data)


def _render_broker_radar_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/concept-backtest">族群策略回測</a>'
           '<a href="/second-wave-backtest">第二波回測</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:960px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.4em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  section h3{margin:0 0 6px 0;font-size:1.05em;color:#444;}
  table.report-table{width:100%;border-collapse:collapse;font-size:.9em;}
  table.report-table td,table.report-table th{padding:6px 10px;border-bottom:1px solid #eee;text-align:left;}
  table.report-table th{background:#fafafa;font-weight:600;color:#555;}
  .num{text-align:right;font-variant-numeric:tabular-nums;} .small,small{font-size:.85em;color:#666;}
  .error{background:#fee;border:1px solid #f99;padding:12px;border-radius:4px;color:#c00;}
  .pos{color:#060;} .neg{color:#c30;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>主力雷達回測</title>{css}</head><body>{nav}'
            f'<h1>🎯 主力雷達 — 回測（事件研究）</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>tw_broker_radar_backtest.py --entry next --json-out '
                       'concept_momentum/cache/broker_radar_backtest.json</code></p></section>') + tail
    rs = data.get("result", {})         # 訊號日進場
    rn = data.get("result_next", {})    # 隔天進場
    hs = ["5", "10", "20"]

    def tbl(r, title):
        H = r.get("horizons", {})
        rows = ""
        for h in hs:
            v = H.get(h)
            if not v:
                continue
            ec = "pos" if v["exc_mean"] > 0 else "neg"
            mc = "pos" if v.get("exc_med", 0) > 0 else "neg"
            ci = v.get("exc_ci", [0, 0])
            ci_str = f"[{ci[0]:+.2f},{ci[1]:+.2f}]" if ci else "—"
            edge_v = v.get("edge_mean", v.get("edge", 0))
            edge_ci = v.get("edge_ci")
            edge_ci_str = (f'<br><small>[{edge_ci[0]:+.2f},{edge_ci[1]:+.2f}]</small>'
                           if edge_ci else "")
            ec2 = "pos" if edge_v > 0 else "neg"
            warn = (' <span style="color:#c80;font-size:.8em">⚠&lt;30</span>'
                    if v["n"] < 30 else "")
            rows += (f'<tr><td>{h} 日</td><td class="num">{v["n"]}{warn}</td>'
                     f'<td class="num {ec}">{v["exc_mean"]:+.2f}%</td>'
                     f'<td class="num {mc}">{v.get("exc_med", 0):+.2f}%</td>'
                     f'<td class="num" style="white-space:nowrap;font-size:.85em">{ci_str}</td>'
                     f'<td class="num">{v.get("t", 0):.2f}</td>'
                     f'<td class="num">{v["beat"]:.0f}%</td>'
                     f'<td class="num">{v["abs_mean"]:+.2f}%</td>'
                     f'<td class="num {ec2}">{edge_v:+.2f}%{edge_ci_str}</td></tr>')
        skipped = r.get("n_skipped_no_data", 0)
        skipped_note = f'，無資料跳過 {skipped}' if skipped else ''
        return (f'<section><h3>{title}（去重 {r.get("n_episodes")} 進場 / 原始 {r.get("n_events_raw")} 事件{skipped_note}）</h3>'
                f'<table class="report-table"><thead><tr><th>持有</th><th class="num">樣本</th>'
                f'<th class="num">超額vs大盤</th><th class="num">超額中位</th>'
                f'<th class="num">95% CI</th><th class="num">t</th>'
                f'<th class="num">贏大盤率</th><th class="num">絕對報酬</th>'
                f'<th class="num">edge(扣成本)</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
                f'<p class="small">edge = 個股超額 − 同日隨機基準 − 成本；'
                f'CI 含 0 = 統計上不顯著；⚠&lt;30 = 樣本不足，CI 很寬。</p></section>')

    v5 = rn.get("horizons", {}).get("5", {})
    v5_ci = v5.get("exc_ci", [0, 0])
    v5_ci_str = f"[{v5_ci[0]:+.2f},{v5_ci[1]:+.2f}]" if v5_ci else "—"
    verdict = (
        '<section style="background:#eef7ee;border:1px solid #9c9"><h3>⚖️ 裁決</h3>'
        f'<p class="small"><b>主力雷達短線 edge 尚未達統計顯著（CI 含 0）</b>；'
        f'隔天開盤進場、持有 5 日：超額大盤 <b>{v5.get("exc_mean","?")}%</b>、'
        f'贏大盤率 <b>{v5.get("beat","?")}%</b>、95%CI <b>{v5_ci_str}</b>。<br>'
        f'10-20 日 edge 漸增（date-matched 基準對比），但 CI 仍跨零。<br>'
        f'⚠ <b>樣本偏小</b>（{rn.get("n_episodes", "?")} 進場），CI 很寬，結論僅供方向參考；'
        '累積半年以上歷史後再回測才可信。<br>'
        '⚠ <b>事件由已部署的訊號版本產生</b>，改訊號參數後歷史事件不可比。</p></section>')

    method = ('<section><h3>🔬 方法 + 限制</h3><p class="small">'
              '主力雷達靠<b>分點 BSR</b>，BSR 無歷史 API → 不能重算歷史訊號。'
              '改用 cron 每天存下的<b>實際訊號輸出</b>(broker_radar_history/)做事件研究：'
              '被點名的 (股,日) → 量之後 H 日報酬 vs 大盤 vs 同期隨機股票日基準。<br>'
              '<b>v2 改動</b>：進場預設隔日<b>開盤</b>（訊號 18:00 才出，隔日開盤是最早可實現價）；'
              '基準改 date-matched（與事件同日期隨機 100 股票平均超額）；'
              '統計加 bootstrap 95% CI + t-stat。<br>'
              '「訊號日進場」=理想化(收盤即買，但訊號 18:00 才出)；'
              '「隔天開盤進場」=較真實。<br>'
              '⚠ 近期事件因尚無完整 20 日後續，H=20 樣本更少。'
              '⚠ 事件由已部署訊號版本產生，<b>改訊號參數後歷史事件不可比</b>。</p></section>')
    glossary = _glossary_section([
        "持有天數 (H)", "事件研究", "episode 去重", "超額報酬 (vs 大盤)",
        "淨超額", "基準 (baseline)", "edge", "贏大盤率 (beat rate)",
        "中位數 vs 均值", "CI / 信賴區間", "t 統計量",
        "日期配對基準 (date-matched)", "隔日開盤進場", "樣本不足警語 (n<30)"])
    return head + verdict + tbl(rn, "🟢 隔天開盤進場（較真實，v2 預設）") + tbl(rs, "理想化：訊號日收盤進場") + method + glossary + tail


@app.route("/broker-radar-backtest")
def broker_radar_backtest():
    path = os.path.join(HERE, "cache", "broker_radar_backtest.json")
    if not os.path.exists(path):
        return _render_broker_radar_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_broker_radar_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_broker_radar_backtest_page(data=data)


@app.route("/intraday-sim")
def intraday_sim():
    code = (request.args.get("code") or "").strip()
    if not code:
        return _render_intraday_sim_page()
    try:
        import tw_intraday_sim
        data = tw_intraday_sim.run(code, pool="both")
    except Exception as e:
        return _render_intraday_sim_page(code=code, error=f"{type(e).__name__}: {e}")
    if data.get("error"):
        return _render_intraday_sim_page(code=code, error=data["error"])
    return _render_intraday_sim_page(code=code, data=data)


_BACKTEST_GLOSSARY.update({
    "融資維持率": "擔保品市值 ÷ 融資金額 ×100%。跌到 130% 券商發追繳令、限期補錢否則斷頭賣出。"
                 "本頁的維持率是「市場整體」估算：用 3 個月融資買賣重建平均成本，不是任何特定投資人的真實數字。",
    "追繳價 / 警戒價": "現價再跌到哪裡，整體維持率會碰 130%（追繳）/ 140%（警戒）。距離越近，融資多殺多的引爆點越近——"
                 "跌破追繳價常引發強制賣壓連鎖（斷頭潮）。",
    "FIFO / LIFO / 比例扣減": "融資餘額減少時，要把減少量歸給哪一批進場者的三種假設：FIFO=老批先出場（最常見）、"
                 "LIFO=新批恐慌先跑、比例=大家等比例減。同一檔用不同規則算出的批次分布差異可能很大，建議切換比對做壓力測試。",
    "批次 (cohort)": "把融資餘額按進場日拆開的分組。整體平均維持率會掩蓋風險——例如平均 151% 看似安全，"
                 "但拆開後可能 9 成的追蹤量都擠在 130-140% 危險區，只是被舊部位拉高平均。看分布比看平均準。",
    "舊部位 (legacy)": "3 個月觀察期之前就存在的融資部位，成本無從得知，無法估維持率。舊部位佔比越高，本頁估算的參考性越低。",
})


_BACKTEST_GLOSSARY.update({
    "法人淨流 (億)": (
        "外資（含外資自營）+ 投信 + 自營商 當日淨買賣「股數」× 當日收盤價，"
        "加總成金額（億元）。正 = 淨買（資金流入）、負 = 淨賣（流出）。"
        "注意這是<b>近似值</b>：法人實際成交價分布在盤中各時點，這裡統一用收盤價換算。"
        "資料源 FinMind TaiwanStockInstitutionalInvestorsBuySell（原始單位是股數）。"),
    "成交額占比": (
        "族群成交金額 ÷ 全市場（上市櫃 4 位數普通股）成交金額 × 100%。"
        "代表市場資金的「注意力」有多少放在這個族群，不分買賣方向。"
        "一檔股票可屬多個主題 → 各族群占比加總會超過 100%；"
        "單一權值股爆量（如台積電）會讓它所屬的每個主題占比同時失真。"),
    "資金流標記 (🔥/⚠/🧲/❄)": (
        "占比變化與法人淨流的交叉判讀：🔥 占比升+法人買 = 真流入（熱度與真金同向）；"
        "⚠ 占比升+法人賣 = 出貨疑慮（人氣升但法人倒貨，散戶接刀風險）；"
        "🧲 占比降+法人買 = 低調吸收（沒人注意但法人默默買）；"
        "❄ 占比降+法人賣 = 退潮（熱度與資金雙離開）。"
        "門檻：占比變化 ±0.15pp 且 法人淨流 ±0.5 億、"
        "且淨流須 ≥ 總流量（|外資|+|投信|+|自營|）的 10% — 外資投信大額對沖"
        "（例：外資買 66 億、投信賣 66 億，淨流只剩 +2.77 億）的雜訊殘差不算方向訊號；"
        "未達門檻標 —（不強行分類）。"
        "注意 🔥 在大跌爆量日也可能出現（散戶恐慌賣、外資接刀/回補空單），"
        "≠ 看多訊號，需搭配價格判讀。"
        "<b>門檻為先驗設定、未經回測驗證</b>，累積數據後才能校準。"),
    "外資買賣超 (上市/上櫃)": (
        "上市/上櫃兩欄為<b>官方公布值</b>（TWSE 三大法人買賣金額統計表 / 櫃買中心三大法人"
        "彙總表的「外資及陸資買賣超金額」，實際成交金額口徑）— 與新聞、官網數字一致。"
        "極少數缺官方資料的日子以「淨股數 × 收盤價」近似回填並加 ~ 標示"
        "（近似與官方通常差數億內）。"
        "個股 Top15 榜因官方不提供個股金額，全部為近似值；榜單<b>排除 ETF</b>（只列 4 位數個股）；"
        "市場欄 ? = 分類快取缺該檔（極少數）。"),
    "占比 vs 20日均 (pp)": (
        "今日成交額占比 − 過去 20 個交易日的平均占比，單位百分點 (pp)。"
        "例：某族群平常占全市場成交額 3.0%、今日 3.8% → +0.8pp，熱度明顯升。"
        "歷史不足 20 日時用現有天數平均並標 *（樣本不足，數字較不穩）。"),
})


def _render_margin_lookup_page(code: str = "", method: str = "fifo",
                               report: str = "", error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/chip-price">📋 籌碼價量</a></nav>')
    css = """<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:900px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  form { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
  input[type=text]{ width:90px; padding:6px 8px; border:1px solid #ccc; border-radius:4px; }
  select{ padding:6px 8px; border:1px solid #ccc; border-radius:4px; }
  button{ padding:6px 14px; background:#0066cc; color:#fff; border:none; border-radius:4px; cursor:pointer; }
  pre.report { background:#fff; padding:14px 18px; border-radius:6px; font-size:.92em; line-height:1.55;
               overflow-x:auto; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  table.glossary { width:100%; border-collapse:collapse; font-size:.85em; }
  table.glossary td { padding:6px 8px; border-bottom:1px solid #eee; vertical-align:top; }
  table.glossary td:first-child { white-space:nowrap; font-weight:600; color:#444; }
</style>"""
    sel = {m: (" selected" if m == method else "") for m in ("fifo", "lifo", "proportional")}
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>融資維持率查詢</title>{css}</head><body>{nav}'
            f'<h1>💳 單檔融資維持率 + 批次分布</h1>'
            f'<section><form action="/margin-lookup" method="get">'
            f'<input type="text" name="code" placeholder="股號" value="{_esc(code)}" required>'
            f'<select name="method">'
            f'<option value="fifo"{sel["fifo"]}>FIFO 老批先扣</option>'
            f'<option value="lifo"{sel["lifo"]}>LIFO 新批先扣</option>'
            f'<option value="proportional"{sel["proportional"]}>比例扣減</option>'
            f'</select><button type="submit">查詢</button>'
            f'<span class="small">FIFO 重建 3 個月市場整體融資成本 → 維持率 + 批次 (cohort) 風險分布</span>'
            f'</form></section>')
    glossary = _glossary_section(["融資維持率", "追繳價 / 警戒價", "FIFO / LIFO / 比例扣減",
                                  "批次 (cohort)", "舊部位 (legacy)"])
    caveat = ('<section class="small">⚠ 注意：(1) 收盤後查詢時「現價」可能是盤中快照而非官方收盤價（Yahoo 資料源特性），'
              '關鍵決策前請以 FinMind/TWSE 官方收盤覆核；(2) 全部數字為市場整體估算，'
              '實際個別投資人成本與擔保品組合各異；(3) 融資成數用預設值（上市 60% / 上櫃 50%），'
              '警示股/處置股的降成數未反映。</section>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + glossary + caveat + tail
    if report:
        return head + f'<pre class="report">{_esc(report)}</pre>' + glossary + caveat + tail
    return head + glossary + caveat + tail


@app.route("/margin-lookup")
def margin_lookup():
    code = (request.args.get("code") or "").strip()
    method = (request.args.get("method") or "fifo").strip()
    if method not in ("fifo", "lifo", "proportional"):
        method = "fifo"
    if not code:
        return _render_margin_lookup_page(method=method)
    try:
        import tw_margin_lookup
        import tw_inventory
        token = tw_inventory._get_token() or ""
        report = tw_margin_lookup.lookup(code, finmind_token=token, method=method)
    except Exception as e:
        return _render_margin_lookup_page(code=code, method=method,
                                          error=f"{type(e).__name__}: {e}")
    return _render_margin_lookup_page(code=code, method=method, report=report)


@app.route("/adr-premium")
def adr_premium():
    import tw_adr_premium
    period = (request.args.get("period") or "").strip()
    if period not in tw_adr_premium.PERIODS:
        # backward-compat: old ?years=N links
        yrs = request.args.get("years")
        period = f"{max(1, min(int(yrs), 10))}y" if yrs and yrs.isdigit() \
            else "6mo"
        if period not in tw_adr_premium.PERIODS:
            period = "6mo"
    try:
        data = tw_adr_premium.fetch_premium_series(period)
    except Exception as e:
        return _render_adr_premium_page(period=period, error=f"{type(e).__name__}: {e}")
    try:
        mixed = tw_adr_premium.latest_mixed_premium()
    except Exception:
        mixed = None
    return _render_adr_premium_page(period=period, data=data, mixed=mixed)


@app.route("/api/chip-narrative", methods=["POST"])
def chip_narrative_start():
    """觸發 AI 行為敘事產生 (背景 thread, 每次 = 一次 Claude 呼叫)。"""
    code = (request.form.get("code") or "").strip()
    date = (request.form.get("date") or "").strip()
    mode = (request.form.get("mode") or "full").strip()
    force = request.form.get("force") == "1"
    if not code or not date:
        return jsonify({"state": "error", "error": "缺 code/date"}), 400
    import chip_narrative
    return jsonify(chip_narrative.start(code, date, mode=mode, force=force))


@app.route("/api/chip-narrative", methods=["GET"])
def chip_narrative_status():
    code = (request.args.get("code") or "").strip()
    date = (request.args.get("date") or "").strip()
    mode = (request.args.get("mode") or "full").strip()
    if not code or not date:
        return jsonify({"state": "error", "error": "缺 code/date"}), 400
    import chip_narrative
    return jsonify(chip_narrative.get_status(code, date, mode=mode))


def _md_lite(text: str) -> str:
    """Escape then convert the narrative's markdown subset (## / **) to
    HTML. Paragraphs split on blank lines; single newlines become <br>."""
    esc = html_lib.escape(text)
    import re as _re
    esc = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
    parts = []
    for block in esc.split("\n\n"):
        b = block.strip()
        if not b:
            continue
        if b.startswith("## "):
            parts.append(f"<h3>{b[3:]}</h3>")
        elif b.startswith("# "):
            parts.append(f"<h3>{b[2:]}</h3>")
        else:
            # list blocks keep line breaks
            parts.append("<p>" + b.replace("\n", "<br>") + "</p>")
    return "\n".join(parts)


def _render_narrative_block(code: str, date: str) -> str:
    """【🤖 AI 行為敘事】 section: cached result (完整版優先) or trigger
    buttons + polling JS. 完整版 = agentic 三線整合 (~5-10 分)；快速版 =
    只讀序列 (~1-2 分)。"""
    import chip_narrative
    st_full = chip_narrative.get_status(code, date, mode="full")
    st_quick = chip_narrative.get_status(code, date, mode="quick")
    code_js = html_lib.escape(code)
    date_js = html_lib.escape(date)
    explain = ('<p class="small">AI 產生的籌碼行為判讀，由本機 Claude CLI 執行。'
               '<b>完整版</b>＝跑三線整合（分點多日序列 + 借券/SBL + 融資 + '
               '30 天內除權息查核）再交叉寫敘事，約 5-10 分鐘；'
               '<b>快速版</b>＝只讀「近 10 日分點連續買賣序列」，約 1-2 分鐘。'
               '每次產生消耗一次 Claude 用量，同檔同日同版本存快取。'
               '⚠ 判讀基於分點慣性推論，非投資建議。</p>'
               '<p class="small" style="color:#555;background:#f4f6f8;'
               'padding:6px 10px;border-radius:4px;">📖 敘事名詞：'
               '<b>@N%＝價位位階</b>＝該分點當日買(賣)均價落在「當日最高低價區間」'
               '的百分位（0%=貼最低價、100%=貼最高價）。'
               '例：賣@23% 表示賣在當日低檔一路砍出（不計價出場）；'
               '買@90% 表示追在當日高點；買@10% 是耐心低接。'
               '<b>k＝千張</b>；<b>—</b>＝該日無資料（非零買賣）。'
               '外資分點含客戶委託、非全為外資自營；散戶指標為經驗 proxy。</p>')

    def _done_body(st, label):
        body = _md_lite(st.get("narrative", ""))
        meta = (f'<p class="small muted">{label}・產生於 '
                f'{_esc(st.get("generated_at", "?"))} '
                f'(耗時 {_esc(st.get("elapsed_sec", "?"))}s)</p>')
        return body + meta

    shown = ""
    if st_full["state"] == "done":
        shown = _done_body(st_full, "完整版 (三線整合)")
    elif st_quick["state"] == "done":
        shown = _done_body(st_quick, "快速版 (僅序列)")

    running = None
    if st_full["state"] == "running":
        running = ("full", "完整版 (約 5-10 分鐘)")
    elif st_quick["state"] == "running":
        running = ("quick", "快速版 (約 1-2 分鐘)")

    err = ""
    for st, label in ((st_full, "完整版"), (st_quick, "快速版")):
        if st["state"] == "error":
            err += (f'<p class="small" style="color:#c00">⚠ {label}上次失敗：'
                    f'{_esc(st.get("error", ""))}</p>')

    if running:
        mode_js, label = running
        inner = (shown + err +
                 f'<p id="cn-status">⏳ {label}產生中，完成後自動顯示…</p>'
                 f'<script>setTimeout(function(){{cnPoll("{code_js}","{date_js}","{mode_js}")}}, 8000);</script>')
    else:
        full_label = ("🔄 重新產生完整版" if st_full["state"] == "done"
                      else "🤖 完整版敘事 (三線整合, ~5-10分)")
        quick_label = ("🔄 重新產生快速版" if st_quick["state"] == "done"
                       else "⚡ 快速版 (僅序列, ~1-2分)")
        full_force = "true" if st_full["state"] == "done" else "false"
        quick_force = "true" if st_quick["state"] == "done" else "false"
        inner = (shown + err +
                 f'<button id="cn-btn" '
                 f'onclick="cnStart(\'{code_js}\',\'{date_js}\',\'full\',{full_force})">'
                 f'{full_label}</button> '
                 f'<button id="cn-btn2" class="secondary" '
                 f'onclick="cnStart(\'{code_js}\',\'{date_js}\',\'quick\',{quick_force})">'
                 f'{quick_label}</button> '
                 f'<span id="cn-status" class="small"></span>')
    js = """<script>
function cnPoll(code, date, mode) {
  fetch('/api/chip-narrative?code=' + code + '&date=' + date + '&mode=' + mode)
    .then(function(r){ return r.json(); })
    .then(function(s){
      if (s.state === 'done') { location.reload(); }
      else if (s.state === 'error') {
        var el = document.getElementById('cn-status');
        if (el) el.textContent = '⚠ ' + (s.error || '失敗');
        var b1 = document.getElementById('cn-btn');
        var b2 = document.getElementById('cn-btn2');
        if (b1) b1.disabled = false;
        if (b2) b2.disabled = false;
      } else { setTimeout(function(){ cnPoll(code, date, mode); }, 8000); }
    });
}
function cnStart(code, date, mode, force) {
  var b1 = document.getElementById('cn-btn');
  var b2 = document.getElementById('cn-btn2');
  if (b1) b1.disabled = true;
  if (b2) b2.disabled = true;
  var el = document.getElementById('cn-status');
  if (el) el.textContent = mode === 'full'
      ? '⏳ 完整版產生中 (約 5-10 分鐘)…' : '⏳ 快速版產生中 (約 1-2 分鐘)…';
  fetch('/api/chip-narrative', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: 'code=' + code + '&date=' + date + '&mode=' + mode +
          '&force=' + (force ? 1 : 0)
  }).then(function(){ setTimeout(function(){ cnPoll(code, date, mode); }, 8000); });
}
</script>"""
    return (f'<section id="narrative"><h2>🤖 AI 行為敘事 '
            f'<small>(分點多日序列判讀)</small></h2>'
            f'{explain}{inner}{js}</section>')


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
    # 快取日期比今天舊 → 提醒（BSR ~17:30 後公布當日資料；AI 敘事跟著
    # 顯示中的報告日期跑，避免使用者以為看的是今天）
    today_str = datetime.now().strftime("%Y%m%d")
    d_shown = (data or {}).get("date", "")
    if data and source.startswith("快取") and d_shown < today_str:
        source += (f' — ⚠ 這是 {d_shown[4:6]}/{d_shown[6:8]} 的資料，'
                   f'AI 敘事也會以該日為基準；要今天的請按'
                   f'「即時抓取」(當日 BSR 約 17:30 後公布)')
    broker_html = ""
    if broker_query and data:
        broker_html = _render_broker_drilldown(
            code, data.get("date", date or ""), broker_query,
            ohlc=data.get("ohlc", {}),
        )
    return _render_chip_price_page(code=code, data=data, source=source,
                                    broker_query=broker_query,
                                    broker_html=broker_html)


def _render_turnaround_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/second-wave-backtest">🌊 第二波回測</a>'
           '<a href="/turnaround-backtest">🔄 轉機接力回測</a></nav>')
    css = """<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:1100px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  section h3 { margin:0 0 8px 0; font-size:1.05em; color:#444; }
  table.report-table { width:100%; border-collapse:collapse; font-size:.9em; }
  table.report-table th,table.report-table td { padding:6px 10px; border-bottom:1px solid #eee; text-align:left; }
  table.report-table th { background:#fafafa; font-weight:600; color:#555; }
  table.report-table .num { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:#060; } .neg { color:#c30; } .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  .cards { display:flex; gap:10px; flex-wrap:wrap; }
  .card { flex:1; min-width:130px; background:#fff8f0; border:1px solid #f0d8b0; border-radius:6px; padding:10px 12px; }
  .card .v { font-size:1.4em; font-weight:700; } .card .k { font-size:.8em; color:#777; }
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>轉機接力回測</title>{css}</head><body>{nav}'
            f'<h1>🔄 轉機接力 Layer 1 — 回測（事件研究）</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        _nodata_glossary = _glossary_section([
            "持有天數 (H)", "事件研究", "point-in-time", "財報可用日 (法定死線)",
            "ABD overlay", "episode 去重", "CI / 信賴區間", "t 統計量",
        ])
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>python3 tw_turnaround_backtest.py --json-out '
                       'concept_momentum/cache/turnaround_backtest.json</code></p></section>'
                       ) + _nodata_glossary + tail
    r = data["result"]; p = data["params"]
    hs = [str(h) for h in p["horizons"]]
    hmax = hs[-1]
    H = r["horizons"]
    def cls(v): return "pos" if v is not None and v > 0 else "neg"
    hh = H.get(hmax, {})
    if not hh or not hh.get("n"):
        return head + ('<section><div class="error">回測資料不完整（horizons 為空）。'
                       '請重新執行 tw_turnaround_backtest.py。</div></section>') + tail
    _edge_v = hh.get("edge_mean", 0) or 0
    _edge_ci = hh.get("edge_ci")
    _edge_ci_str = (f"CI [{_edge_ci[0]:+.2f},{_edge_ci[1]:+.2f}]" if _edge_ci else "淨超額−基準")
    _ci = hh.get("exc_ci", [0, 0])
    cards = (
        f'<p class="small" style="margin:.2em 0">摘要＝持有 {hmax} 交易日</p><div class="cards">'
        f'<div class="card"><div class="k">絕對報酬(均)</div>'
        f'<div class="v {cls(hh.get("abs_mean",0))}">{hh.get("abs_mean",0):+.1f}%</div>'
        f'<div class="small">賺錢率 {hh.get("win",0):.0f}%</div></div>'
        f'<div class="card"><div class="k">淨超額 vs 大盤</div>'
        f'<div class="v {cls(hh.get("net",0))}">{hh.get("net",0):+.1f}%</div>'
        f'<div class="small">贏大盤率 {hh.get("beat",0):.0f}%</div></div>'
        f'<div class="card"><div class="k">超額中位數</div>'
        f'<div class="v {cls(hh.get("exc_med",0))}">{hh.get("exc_med",0):+.1f}%</div>'
        f'<div class="small">均值 {hh.get("exc_mean",0):+.1f}%</div></div>'
        f'<div class="card"><div class="k">95% CI (超額均)</div>'
        f'<div class="v" style="font-size:.9em">[{_ci[0]:+.2f}, {_ci[1]:+.2f}]</div>'
        f'<div class="small">t={hh.get("t",0):.2f}'
        f'{"  ✓顯著" if _ci[0] > 0 else ""}</div></div>'
        f'<div class="card"><div class="k">訊號 edge (均)</div>'
        f'<div class="v {cls(_edge_v)}">{_edge_v:+.1f}%</div>'
        f'<div class="small">{_edge_ci_str}</div></div>'
        f'<div class="card"><div class="k">進場樣本</div>'
        f'<div class="v">{r["n_episodes"]}</div>'
        f'<div class="small">GM 可過 {r["n_stocks_gm_pass"]} 檔</div></div></div>')
    meta = (f'<p class="small">回測區間 {p.get("start","2025-01-01")}~・'
            f'進場 {r.get("entry","next_open")}・扣 {r["cost"]}% 成本・'
            f'生成 {_esc(data["generated"])}</p>')

    def row(name, key, fmt="{:+.2f}", pct="%"):
        cells = "".join(f'<td class="num">{fmt.format(H.get(h, {}).get(key, 0))}{pct}</td>' for h in hs)
        return f'<tr><td>{name}</td>{cells}</tr>'
    def ci_row(name, key):
        def _fmt(hd):
            ci = hd.get(key)
            if not ci:
                return "—"
            return f"[{ci[0]:+.2f}, {ci[1]:+.2f}]"
        cells = "".join(f'<td class="num" style="white-space:nowrap">{_fmt(H.get(h, {}))}</td>'
                        for h in hs)
        return f'<tr><td>{name}</td>{cells}</tr>'
    th = "".join(f'<th class="num">{h}日</th>' for h in hs)
    tbl = (f'<section><h3>📊 各持有天數表現</h3>'
           f'<table class="report-table"><thead><tr><th>指標</th>{th}</tr></thead><tbody>'
           + row("絕對報酬(均)", "abs_mean")
           + row("賺錢率", "win", "{:.0f}")
           + row("超額 vs 大盤(均)", "exc_mean")
           + row("超額 中位數", "exc_med")
           + ci_row("95% CI (超額均)", "exc_ci")
           + row("t-stat", "t", "{:.2f}", "")
           + row("贏大盤率", "beat", "{:.0f}")
           + row("扣成本淨超額", "net")
           + row("⭐訊號 edge (均)", "edge_mean")
           + ci_row("edge 95% CI", "edge_ci")
           + '</tbody></table>'
           '<p class="small">edge_mean = (股票超額−大盤) − 同日隨機 k=100 檔的基準超額。</p></section>')

    # Layer 2 ABD overlay 對照表
    L2 = r.get("layer2", {})
    l2_rows = ""
    for h in hs:
        g = L2.get(h, {})
        ge2 = g.get("ge2", {}); lt2 = g.get("lt2", {})
        ge2_n = ge2.get("n", 0); lt2_n = lt2.get("n", 0)
        ge2_exc = ge2.get("exc_mean", 0) or 0; lt2_exc = lt2.get("exc_mean", 0) or 0
        ge2_ci = ge2.get("exc_ci"); lt2_ci = lt2.get("exc_ci")
        ge2_ci_s = (f"[{ge2_ci[0]:+.2f},{ge2_ci[1]:+.2f}]" if ge2_ci else "—")
        lt2_ci_s = (f"[{lt2_ci[0]:+.2f},{lt2_ci[1]:+.2f}]" if lt2_ci else "—")
        diff = ge2_exc - lt2_exc
        l2_rows += (
            f'<tr><td class="num">{h}日</td>'
            f'<td class="num">{ge2_n}</td>'
            f'<td class="num {cls(ge2_exc)}">{ge2_exc:+.2f}%</td>'
            f'<td class="num" style="white-space:nowrap">{ge2_ci_s}</td>'
            f'<td class="num">{lt2_n}</td>'
            f'<td class="num {cls(lt2_exc)}">{lt2_exc:+.2f}%</td>'
            f'<td class="num" style="white-space:nowrap">{lt2_ci_s}</td>'
            f'<td class="num {cls(diff)}" style="font-weight:600">{diff:+.2f}%</td></tr>'
        )
    l2_tbl = (
        '<section><h3>🔍 Layer 2 ABD overlay 對照（ge2 vs lt2）</h3>'
        '<table class="report-table"><thead><tr>'
        '<th>H</th>'
        '<th class="num">ge2 n</th><th class="num">ge2 超額均</th><th class="num">ge2 95%CI</th>'
        '<th class="num">lt2 n</th><th class="num">lt2 超額均</th><th class="num">lt2 95%CI</th>'
        '<th class="num">差值</th>'
        f'</tr></thead><tbody>{l2_rows}</tbody></table>'
        '<p class="small">ge2=同日 ABD≥2 訊號；lt2=ABD&lt;2。差值 = ge2超額 − lt2超額，正=overlay 加值。'
        '⚠ C 訊號（籌碼集中分點）無歷史資料，故 overlay 只含 A/B/D 三項，最高 3 分，≥2 = 多數訊號同步。</p>'
        '</section>'
    )

    method = (
        '<section><h3>🔬 詳細回測方法</h3><div class="small" style="line-height:1.7">'
        '<b>① 為何用事件研究</b><br>'
        '轉機接力是<b>四濾網（ABCD）同時通過</b>的個股型態訊號，不是族群排名。'
        '每當某股某日四網全過，量它之後的報酬，比基準看有沒有 edge。<br><br>'
        '<b>② point-in-time 訊號重建</b><br>'
        '直接 import 正式篩選器的純函數（margin_passes/volume_passes/ma60_passes/short_passes），'
        '逐日 as-of 截斷：財報用法定死線可用日（Q1→5/15、Q2→8/14、Q3→11/14、Q4→翌年3/31），'
        '量能/季線用 ≤t 的面板資料，借券餘額 as-of 截斷到 t 日。<br><br>'
        '<b>③ episode 去重（cooldown）</b><br>'
        '四濾網通過後的連續觸發只取首次進場，冷卻期 = max_horizon，'
        f'避免同一波重複計入。<br><br>'
        '<b>④ Layer 2 ABD overlay</b><br>'
        '在每個 Layer 1 事件日同時計算 A/B/D 三個 overlay 訊號（C 無歷史跳過），'
        '依 ABD 總分 ≥2 vs &lt;2 分兩組，比較前向超額報酬差異。<br><br>'
        '<b>⑤ 成本/資料</b><br>'
        f'扣 {r["cost"]}% 來回成本（手續費6折+證交稅）。'
        '毛利率來源：FinMind TaiwanStockFinancialStatements；'
        '價格面板：TaiwanStockPrice/Adj（v2，含 open/close/aopen/aclose）。'
        '</div></section>'
    )

    caveat = (
        '<section><h3>⚠ 解讀與限制</h3><p class="small">'
        '1. <b>PIT 保守規則</b>：用法定死線當可用日，比多數公司實際公告晚，低估 edge，不高估。<br>'
        '2. <b>C 訊號缺失</b>：Layer 2 overlay 只含 A/B/D，若 C（籌碼集中）有效，ge2 組可能被低估。<br>'
        '3. <b>回測期間偏短</b>：面板 start=2025-01-01，樣本涵蓋約 1.5 年，多為多頭期；空頭盤 edge 可能不同。<br>'
        '4. 成本 0.471%（手續費6折+證交稅，零滑價），轉機股流動性有時偏低，實際滑價可能更高。'
        '</p></section>'
    )

    glossary = _glossary_section([
        "持有天數 (H)", "事件研究", "episode 去重", "point-in-time",
        "財報可用日 (法定死線)", "ABD overlay",
        "絕對報酬", "超額報酬 (vs 大盤)", "淨超額",
        "基準 (baseline)", "edge", "賺錢率 / 勝率", "贏大盤率 (beat rate)",
        "中位數 vs 均值", "CI / 信賴區間", "t 統計量",
        "日期配對基準 (date-matched)", "隔日開盤進場",
    ])
    return head + cards + meta + tbl + l2_tbl + method + glossary + caveat + tail


@app.route("/turnaround-backtest")
def turnaround_backtest():
    path = os.path.join(HERE, "cache", "turnaround_backtest.json")
    if not os.path.exists(path):
        return _render_turnaround_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_turnaround_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_turnaround_backtest_page(data=data)


def _render_lending_backtest_page(data: dict | None = None, error: str = "") -> str:
    nav = ('<nav><a href="/">← 大盤 dashboard</a>'
           '<a href="/second-wave-backtest">🌊 第二波回測</a>'
           '<a href="/turnaround-backtest">🔄 轉機接力回測</a>'
           '<a href="/lending-backtest">🔻 借券回測</a></nav>')
    css = """<style>
  body { font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
         max-width:1200px; margin:1em auto; padding:0 1em; background:#f7f7f9; color:#222; }
  h1 { font-size:1.4em; margin:.4em 0; } nav a { margin-right:12px; color:#0066cc; text-decoration:none; }
  section { background:#fff; padding:12px 16px; border-radius:6px; margin-bottom:12px;
            box-shadow:0 1px 3px rgba(0,0,0,.06); }
  section h3 { margin:0 0 8px 0; font-size:1.05em; color:#444; }
  table.report-table { width:100%; border-collapse:collapse; font-size:.9em; }
  table.report-table th,table.report-table td { padding:6px 10px; border-bottom:1px solid #eee; text-align:left; }
  table.report-table th { background:#fafafa; font-weight:600; color:#555; }
  table.report-table .num { text-align:right; font-variant-numeric:tabular-nums; }
  .pos { color:#060; } .neg { color:#c30; } .small,small { font-size:.85em; color:#666; }
  .error { background:#fee; border:1px solid #f99; padding:12px; border-radius:4px; color:#c00; }
  .warn { background:#fff8e1; border:1px solid #ffe082; padding:6px 10px;
          border-radius:4px; color:#795548; font-size:.85em; display:inline-block; margin-bottom:6px; }
  .group-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  @media(max-width:700px){ .group-grid { grid-template-columns:1fr; } }
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>借券雷達 + 空頭撤退 回測</title>{css}</head><body>{nav}'
            f'<h1>🔻 借券雷達 + 空頭撤退 — 回測（事件研究）</h1>')
    tail = '</body></html>'
    if error:
        return head + f'<div class="error">{_esc(error)}</div>' + tail
    if not data:
        _nodata_glossary = _glossary_section([
            "借券賣出餘額 (SBL)", "議借", "利率帶 (<1% / >7%)",
            "up_only (減量且當日上漲)",
            "事件研究", "episode 去重", "CI / 信賴區間",
            "隔日開盤進場", "日期配對基準 (date-matched)", "樣本不足警語 (n<30)",
        ])
        return head + ('<section><p>尚無回測結果。請先跑：<br>'
                       '<code>python3 tw_lending_backtest.py --json-out '
                       'concept_momentum/cache/lending_backtest.json</code></p></section>'
                       ) + _nodata_glossary + tail

    r = data["result"]
    p = r.get("params", {})
    ec = r.get("event_counts", {})
    cost = p.get("cost", 0.471)
    hs = [str(h) for h in p.get("horizons", [5, 10, 20])]
    generated = _esc(data.get("generated", ""))

    def cls(v):
        return "pos" if v is not None and v > 0 else "neg"

    def _grp_table(grp_data: dict, label: str, note: str = "") -> str:
        """Render a single group's per-horizon table."""
        th = "".join(f'<th class="num">{h}日</th>' for h in hs)
        rows_html = ""
        n_warn = False

        def _val(h, key, fmt="{:+.2f}", pct="%", color=False):
            hd = grp_data.get(h, {})
            v = hd.get(key)
            if v is None:
                return '<td class="num">—</td>'
            s = fmt.format(v) + pct
            col_cls = f' class="num {cls(v)}"' if color else ' class="num"'
            return f'<td{col_cls}>{s}</td>'

        def _ci_val(h, key):
            hd = grp_data.get(h, {})
            ci = hd.get(key)
            if not ci:
                return '<td class="num">—</td>'
            return f'<td class="num" style="white-space:nowrap">[{ci[0]:+.2f},{ci[1]:+.2f}]</td>'

        for h in hs:
            hd = grp_data.get(h, {})
            if hd.get("n", 0) < 30:
                n_warn = True

        warn_html = '<span class="warn">⚠ 樣本不足 (n&lt;30) — 數字僅供方向參考</span>' if n_warn else ""

        def row(name, key, fmt="{:+.2f}", pct="%", color=False):
            cells = "".join(_val(h, key, fmt, pct, color) for h in hs)
            return f'<tr><td>{name}</td>{cells}</tr>'

        def ci_row(name, key):
            cells = "".join(_ci_val(h, key) for h in hs)
            return f'<tr><td>{name}</td>{cells}</tr>'

        def n_row():
            cells = ""
            for h in hs:
                hd = grp_data.get(h, {})
                n = hd.get("n", 0)
                mark = " ⚠" if n < 30 else ""
                cells += f'<td class="num">{n}{mark}</td>'
            return f'<tr><td>樣本數 (n)</td>{cells}</tr>'

        rows_html = (
            n_row()
            + row("絕對報酬(均)", "abs_mean")
            + row("賺錢率", "win", "{:.0f}")
            + row("超額 vs 大盤(均)", "exc_mean", color=True)
            + row("超額 中位數", "exc_med", color=True)
            + ci_row("95% CI (超額均)", "exc_ci")
            + row("t-stat", "t", "{:.2f}", "", False)
            + row("贏大盤率", "beat", "{:.0f}")
            + row("扣成本淨超額", "net", color=True)
            + row("訊號 edge (均)", "edge_mean", color=True)
            + ci_row("edge 95% CI", "edge_ci")
        )
        note_html = f'<p class="small">{note}</p>' if note else ""
        return (f'<div><h3>{label}</h3>'
                + warn_html
                + f'<table class="report-table"><thead><tr><th>指標</th>{th}</tr></thead>'
                f'<tbody>{rows_html}</tbody></table>'
                + note_html + '</div>')

    grids = (
        '<section><h3>📊 四組回測對照</h3>'
        '<p class="small">進場 = 訊號日隔日還原開盤；扣 '
        f'{cost:.3f}% 成本；生成 {generated}</p>'
        f'<p class="small">事件數：空頭撤退 all={ec.get("sbl_all",0)}'
        f' up_only={ec.get("sbl_up_only",0)}｜'
        f'議借 low_rate={ec.get("lending_low",0)} high_rate={ec.get("lending_high",0)}</p>'
        '<div class="group-grid">'
        + _grp_table(
            r["sbl_retreat"]["all"], "📉 空頭撤退 — all (SBL日減≥10%)",
            "全市場 SBL 餘額當日縮減 ≥10%（前日餘額 ≥200 張避免小基數雜訊）。"
            "隔日開盤進場，持有 H 日後賣出。")
        + _grp_table(
            r["sbl_retreat"]["up_only"], "📉↑ 空頭撤退 — up_only (減量且收漲)",
            "all 子集：SBL 減量且當日個股收漲。"
            "live 系統的「轉多訊號」分組——空頭縮手 + 股價已反彈，為更強轉多確認。"
            "若 up_only edge 顯著優於 all，支持此分組邏輯有選股力。")
        + _grp_table(
            r["lending_surge"]["low_rate"], "💡 議借雷達 — low_rate (<1%)",
            "議借量 &gt;5日均量×2 且利率 &lt;1%。低費率=容易借到/套利需求，"
            "方向含義複雜；與 high_rate 不可混讀。")
        + _grp_table(
            r["lending_surge"]["high_rate"], "🔥 議借雷達 — high_rate (>7%)",
            "議借量 &gt;5日均量×2 且利率 &gt;7%。高費率=難借/空頭強烈信念，"
            "歷史上高費率議借後股價通常繼續偏弱（對空方有利）。")
        + '</div></section>'
    )

    method = (
        '<section><h3>🔬 方法說明</h3><div class="small" style="line-height:1.7">'
        '<b>① 空頭撤退訊號</b><br>'
        '從 <code>TaiwanDailyShortSaleBalances</code> 取 SBL 每日餘額，'
        '當日相較前日縮減 ≥10%（前日餘額需 ≥200 張避免小基數偽訊號）視為「空頭撤退」。'
        'up_only 子集再加「當日個股收漲」條件，對齊 live 推播的轉多分組邏輯。<br><br>'
        '<b>② 借券雷達訊號</b><br>'
        '從 <code>TaiwanStockSecuritiesLending</code> 取 transaction_type=議借 的記錄，'
        '日彙總後計算量加權費率。當日議借量 &gt;前 5 日均量×2 為爆量門檻；'
        '再依費率分 low_rate (&lt;1%) 和 high_rate (&gt;7%) 兩組，兩者方向含義不同。<br><br>'
        '<b>③ episode 去重（cooldown）</b><br>'
        '每檔個股連續觸發的訊號只取首次，冷卻期 = max_horizon，避免同一波重複計入。<br><br>'
        '<b>④ up_only vs all 差異的意義</b><br>'
        'up_only 驗證的是 live 系統「借券減少 + 當日上漲 = 轉多訊號」這條分組規則有沒有 edge。'
        '若 up_only 超額 / edge 顯著高於 all，代表加「收漲」這個條件能過濾掉品質較差的事件；'
        '若差異不顯著，說明此條件對後續 H 日報酬沒有額外選股力。<br><br>'
        '<b>⑤ 成本與資料</b><br>'
        f'扣 {cost:.3f}% 來回成本（手續費 6 折 + 證交稅）。'
        '價格面板：TaiwanStockPrice/Adj v2（含 open/close/aopen/aclose）；'
        '面板 start=2025-01-01，涵蓋約 1.5 年，多為多頭期，空頭盤 edge 可能不同。'
        '</div></section>'
    )

    caveat = (
        '<section><h3>⚠ 解讀限制與樣本量 caveat</h3><p class="small">'
        '1. <b>樣本期間偏短</b>：2025-01-01 起，約 1.5 年，多為多頭環境；空頭期的表現可能不同，謹慎外推。<br>'
        '2. <b>議借 high_rate 樣本可能不足</b>：費率 &gt;7% 屬罕見，若 n&lt;30 數字僅供方向參考，需累積更多歷史才能下強結論。<br>'
        '3. <b>SBL 制度性還券</b>：到期強制還券、除權息前還券等制度因素會造成 SBL 大幅減少，'
        '但並非空頭主動平倉（轉多）。本回測未過濾這類事件，all/up_only 兩組均可能含雜訊。<br>'
        '4. <b>cost 0.471%</b>：借券股有時流動性偏低，實際滑價可能高於模型假設。'
        '</p></section>'
    )

    glossary = _glossary_section([
        "借券賣出餘額 (SBL)",
        "議借",
        "利率帶 (<1% / >7%)",
        "up_only (減量且當日上漲)",
        "事件研究",
        "episode 去重",
        "CI / 信賴區間",
        "t 統計量",
        "隔日開盤進場",
        "日期配對基準 (date-matched)",
        "樣本不足警語 (n<30)",
        "絕對報酬",
        "超額報酬 (vs 大盤)",
        "淨超額",
        "edge",
    ])
    return head + grids + method + glossary + caveat + tail


@app.route("/lending-backtest")
def lending_backtest():
    path = os.path.join(HERE, "cache", "lending_backtest.json")
    if not os.path.exists(path):
        return _render_lending_backtest_page()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return _render_lending_backtest_page(error=f"{type(e).__name__}: {e}")
    return _render_lending_backtest_page(data=data)


@app.route("/signal-outcomes")
def signal_outcomes_page():
    import signal_outcomes_renderer as sor
    path = os.path.join(HERE, "cache", "signal_outcomes.json")
    data = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            data = None
    body = sor.render_tab(data)
    css = """
<style>
body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#f5f5f7; margin:0; padding:16px; }
h2 { font-size:1.4em; margin:0 0 4px; }
h3 { font-size:1.05em; margin:16px 0 6px; }
p.meta { font-size:0.85em; color:#666; margin:0 0 12px; }
.table-scroll { overflow-x:auto; }
table.market-breadth { width:100%; border-collapse:collapse; background:#fff;
  border-radius:8px; overflow:hidden; margin-bottom:16px;
  box-shadow:0 2px 8px rgba(0,0,0,0.05); font-size:0.88em; }
table.market-breadth th,
table.market-breadth td { padding:6px 10px; border-bottom:1px solid #eee;
  text-align:right; }
table.market-breadth th { background:#fafafa; font-weight:600; text-align:center; }
table.market-breadth td:first-child,
table.market-breadth th:first-child { text-align:left; }
.pos { color:#0a7e0a; }
.neg { color:#c30; }
a { color:#007aff; text-decoration:none; }
a:hover { text-decoration:underline; }
</style>"""
    html = f"""<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📈 訊號成效追蹤</title>
{css}
</head><body>
<p><a href="/">&larr; 返回主控板</a></p>
{body}
</body></html>"""
    return html


@app.route("/money-flow")
def money_flow_page():
    import concept_money_flow as cmf
    import concept_money_flow_renderer as cmfr
    from datetime import datetime as _dt
    day_files = cmf.load_flow_days(_dt.now().strftime("%Y%m%d"), days=60)
    rows = []
    asof = "—"
    foreign_view = None
    if day_files:
        try:
            rows = cmf.build_view_rows(day_files, cmf.load_themes())
            asof = day_files[-1]["date"]
            foreign_view = cmf.build_foreign_view(day_files)
        except Exception:
            rows = []
            foreign_view = None
    body = cmfr.render_tab(rows, asof, foreign_view=foreign_view)
    glossary = _glossary_section(["法人淨流 (億)", "成交額占比",
                                  "資金流標記 (🔥/⚠/🧲/❄)", "占比 vs 20日均 (pp)",
                                  "外資買賣超 (上市/上櫃)"])
    css = """
<style>
body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#f5f5f7; margin:0; padding:16px; }
h2 { font-size:1.4em; margin:0 0 4px; }
p.meta { font-size:0.85em; color:#666; margin:0 0 12px; }
.table-scroll { overflow-x:auto; }
table.market-breadth { width:100%; border-collapse:collapse; background:#fff;
  border-radius:8px; overflow:hidden; margin-bottom:16px;
  box-shadow:0 2px 8px rgba(0,0,0,0.05); font-size:0.88em; }
table.market-breadth th,
table.market-breadth td { padding:6px 10px; border-bottom:1px solid #eee;
  text-align:right; }
table.market-breadth th { background:#fafafa; font-weight:600; text-align:center; }
table.market-breadth td:first-child,
table.market-breadth th:first-child { text-align:left; }
.pos { color:#0a7e0a; }
.neg { color:#c30; }
a { color:#007aff; text-decoration:none; }
a:hover { text-decoration:underline; }
</style>"""
    return f"""<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>💰 族群資金流</title>
{css}
</head><body>
<p><a href="/">&larr; 返回主控板</a></p>
<h2>💰 族群資金流（最近 60 個交易日）</h2>
{body}
{glossary}
</body></html>"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"Dashboard: http://localhost:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False)
