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
<nav><a href="/">← 大盤 dashboard</a> <a href="/chip-price">📋 籌碼價量</a> <a href="/contract-liabilities">💰 合約負債</a> <a href="/inventory">📦 存貨</a> <a href="/shareholders">👥 前十大股東</a></nav>
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


def _render_futures_basis_page(m: dict | None = None, error: str = "") -> str:
    """Web page: 期現貨基差 + 外資期貨留倉監控 (依「留倉沒多空意義」一文)."""
    body = ""
    if error:
        body = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    elif m is not None and m.get("error"):
        body = f'<div class="error">⚠ {html_lib.escape(m["error"])}</div>'
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
            '<b>三訊號同步</b>、<b>大台+富台同向極端</b>、月底轉倉。</p></section>')

        # 三訊號 + 同向極端 狀態卡
        def yn(b):
            return ('<b style="color:#c30">是</b>' if b
                    else '<span style="color:#999">否</span>')
        sig_box = (
            f'<section><h3>🚦 即時訊號狀態（最新 {_esc(L["date"])}）</h3>'
            f'<table class="report-table"><tbody>'
            f'<tr><td>基差（TX 日盤 − 加權現貨）</td>'
            f'<td class="num" style="color:{"#c30" if L["basis"]<0 else "#060"}">'
            f'{L["basis"]:+.0f} 點 ({L["basis_pct"]:+.2f}%)</td>'
            f'<td>套利成本 ±{cost}%｜超過 = {yn(m["basis_extreme"])}</td></tr>'
            f'<tr><td>三訊號同步（跌+逆價差+台幣貶）</td>'
            f'<td class="num">跌 {yn(three["twii_down"])}／逆價差 '
            f'{yn(three["backwardation"])}／台幣貶 {yn(three["twd_weak"])}</td>'
            f'<td>三者同時 = {yn(three["all"])} '
            f'{"→ 可認定外資大賣超(但賣超≠做空)" if three["all"] else ""}</td></tr>'
            f'<tr><td>大台(TX) + 富台(XIF) 同向極端</td>'
            f'<td class="num">TX 淨 {m["tx_net"]:+,} 口／XIF 淨 '
            f'{m["xif_net"]:+,} 口</td>'
            f'<td>同向且都高 = {yn(m["same_dir_extreme"])} '
            f'{"→ 投行水庫滿載，真的要留意" if m["same_dir_extreme"] else "→ 不同向，遊戲繼續、別腦補崩盤"}</td>'
            f'</tr></tbody></table>'
            f'<p class="small">⚠ FinMind 期貨為日收盤；文章強調「盤中 9:00-13:25」'
            f'基差最準，本頁為日盤收盤基準。逆價差 &gt; 成本 + 指數破底 → 套利客'
            f'一腳踹下、跌時特別兇。</p></section>')

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
        body = edu + sig_box + f"""
<section>
  <h3>📈 基差走勢（vs ±{cost}% 套利成本帶）</h3>
  <canvas id="basis-chart" height="130"></canvas>
  <p class="small">綠=正價差(期貨貴)，紅=逆價差(現貨貴)。落在 ±{cost}% 帶內 =
    套利無肉；逆價差跌破 -{cost}% = 套利客有利可圖，破底殺盤兇。</p>
</section>
<section>
  <h3>📊 外資期貨留倉（TX 大台 vs XIF 富台）— 僅供觀察，無多空意義</h3>
  <canvas id="oi-chart" height="120"></canvas>
  <p class="small">⚠ 此為投行套利對沖腳的影子。重點不是「淨空幾萬口」，而是
    <b>TX 與 XIF 是否同向且都極端</b>（同向高=水庫滿載才有事）。目前
    TX {L.get("fx_net",0):+,} / XIF {m["xif_net"]:+,} →
    {"同向極端" if m["same_dir_extreme"] else "未同向極端"}。</p>
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
      {{label:'外資 富台XIF 淨留倉(口)',data:{xif_oi},borderColor:'#0a0',borderWidth:1.5,
        pointRadius:0,tension:0.1,spanGaps:true,yAxisID:'y1'}}
    ]}},
    options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
      plugins:{{title:{{display:true,text:'外資期貨留倉淨額 (無多空意義，看是否同向極端)'}}}},
      scales:{{x:{{ticks:{{maxTicksLimit:12,font:{{size:9}}}}}},
        y:{{position:'left',title:{{display:true,text:'TX 口'}}}},
        y1:{{position:'right',title:{{display:true,text:'XIF 口'}},
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
    return _render_futures_basis_page(m=m)


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
