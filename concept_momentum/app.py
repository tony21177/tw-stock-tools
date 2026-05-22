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
<nav><a href="/">← 大盤 dashboard</a> <a href="/chip-price">📋 籌碼價量</a> <a href="/contract-liabilities">💰 合約負債</a> <a href="/inventory">📦 存貨</a></nav>
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


def _breakdown_commentary(series: dict) -> str:
    """Generate accounting/industry expert commentary on inventory breakdown.

    Looks at YoY growth for each category in the latest quarter and applies
    rule-of-thumb interpretation. Each category has known signal semantics:

    - 原料 ↑: 備料增加，預期 1-2 季後產能上升 (leading indicator)
    - 在製品 ↑: 訂單在生產，1-3 個月後轉營收 (strongest near-term signal)
    - 製成品 ↑: 出貨壓力 / 客戶 push-out / 庫存堆積風險 (lagging, 警訊)
    - 在途存貨 ↑: 物流時間長 / 大批採購中
    - 物料及零件 / 消耗品: 跟原料同步觀察
    - 商品: 通路 / 純代工才看
    """
    dates = sorted(series.keys())
    if len(dates) < 5:
        return ""  # Need ≥5 quarters for meaningful YoY
    latest = series[dates[-1]]
    yoy = series[dates[-5]] if len(dates) >= 5 else None
    prev_q = series[dates[-2]] if len(dates) >= 2 else None
    if not yoy:
        return ""

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

    items = []
    for key, (label, (up_msg, down_msg)) in cat_meta.items():
        v_latest = latest.get(key, 0)
        v_yoy = yoy.get(key, 0)
        v_prev = prev_q.get(key, 0) if prev_q else 0
        if v_latest == 0 and v_yoy == 0:
            continue
        yoy_pct = ((v_latest - v_yoy) / v_yoy * 100) if v_yoy > 0 else None
        qoq_pct = ((v_latest - v_prev) / v_prev * 100) if v_prev > 0 else None
        msg = up_msg if yoy_pct is not None and yoy_pct > 0 else down_msg
        yoy_str = (f'<span class="{"pos" if yoy_pct >= 0 else "neg"}">'
                   f'{"+" if yoy_pct >= 0 else ""}{yoy_pct:.0f}%</span>'
                   if yoy_pct is not None else "—")
        qoq_str = (f'<span class="{"pos" if qoq_pct >= 0 else "neg"}">'
                   f'{"+" if qoq_pct >= 0 else ""}{qoq_pct:.0f}%</span>'
                   if qoq_pct is not None else "—")
        items.append(
            f'<li><b>{label}</b> {v_latest / 1000:,.0f} 千元 '
            f'(YoY {yoy_str}, QoQ {qoq_str}) — {msg}</li>'
        )

    # Overall total trend
    tot_latest = latest.get("_total", 0)
    tot_yoy = yoy.get("_total", 0)
    tot_yoy_pct = ((tot_latest - tot_yoy) / tot_yoy * 100) if tot_yoy > 0 else None
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
    if wip_yoy_pct > 20 and raw_yoy_pct > 20 and fg_yoy_pct < 15:
        headline = "🟢 **強訊號：產能拉貨**" \
                   "（原料+在製大幅增加但製成品控制 → 客戶要貨積極，1-3 季內營收動能）"
    elif fg_yoy_pct > 25 and wip_yoy_pct < 10:
        headline = "🔴 **警訊：庫存堆積**" \
                   "（製成品大幅增加但在製品停滯 → 客戶 push-out / 出貨遲緩，毛利壓力）"
    elif wip_yoy_pct > 30:
        headline = "🟢 **強訊號：在製暴增**" \
                   f"（在製品 YoY +{wip_yoy_pct:.0f}% → 預期未來 1-3 季營收大幅增長）"
    elif tot_yoy_pct and tot_yoy_pct < -15:
        headline = "🟡 **去化中**（整體存貨 YoY 大降 → 出貨好但要看新訂單能不能補上）"
    elif tot_yoy_pct and tot_yoy_pct > 30:
        headline = "🟡 **存貨快速擴大**（整體 YoY 大增，要分辨是好的備料還是堆積）"
    else:
        headline = "→ 存貨結構平穩，無明顯訊號"

    return f"""
<section>
  <h3>💡 會計 + 產業視角解讀</h3>
  <p><b>整體存貨 YoY:</b>
     <span class="{"pos" if tot_yoy_pct and tot_yoy_pct >= 0 else "neg"}">
     {("+" if tot_yoy_pct >= 0 else "") + f"{tot_yoy_pct:.1f}%" if tot_yoy_pct is not None else "—"}</span>
     ({dates[-5][:7]} → {dates[-1][:7]})</p>
  <p style="font-size:1.05em; margin:8px 0;">{headline}</p>
  <h4 style="margin-top:14px; font-size:0.95em;">逐項解讀：</h4>
  <ul class="commentary-list" style="line-height:1.7;">
    {''.join(items)}
  </ul>
  <p class="small" style="margin-top:10px;">
    解讀邏輯：原料↑=備料 (1-2 季 leading) / 在製品↑=訂單在線 (1-3 月最強 leading) /
    製成品↑=⚠ 出貨壓力 (lagging warning) / 在途↑=物流增加。
    產業差異：純代工 (e.g. 2330/2317) 看在製品; PCB/組裝 (e.g. 2313) 看製成品堆積;
    電源/工業 (e.g. 6282) 看原料 vs 製成品比例。
  </p>
</section>
"""


def _breakdown_section_html(series: dict | None) -> str:
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
        table_rows.append('<tr>' + ''.join(cells) + '</tr>')

    th_cats = ''.join(
        f'<th class="num">{label} (千元)</th>' for _, label, _ in used_cats)

    commentary = _breakdown_commentary(series)
    return f"""
<section>
  <h3>📦 拆分明細 (從 MOPS 財報 PDF 解析，{len(dates)} 個季底)</h3>
  <canvas id="breakdown-chart" height="140"></canvas>
  <table class="report-table" style="margin-top:12px;">
    <thead><tr>
      <th>季底</th>
      {th_cats}
      <th class="num">合計</th>
    </tr></thead>
    <tbody>{''.join(table_rows)}</tbody>
  </table>
  <p class="small">資料源：公開資訊觀測站 IFRSs 合併財報 (附註十二 / 存貨明細)。
     不同公司揭露科目不同（半導體：原料/在製品/製成品/物料及零件；
     傳產：原料/在製品/成品/商品 etc）。</p>
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
{_breakdown_section_html(breakdown_series)}

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
