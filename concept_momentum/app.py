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


def _render_chip_price_page(code: str | None = None,
                            data: dict | None = None,
                            source: str = "",
                            error: str = "") -> str:
    """Render the chip-price form + optional result."""
    import tw_chip_price
    recent = _list_cached_history()[:30]
    recent_links = " &middot; ".join(
        f'<a href="/chip-price?code={c}&date={d}">{c} {d[4:6]}/{d[6:8]}</a>'
        for c, d in recent
    ) or "<em>(尚無快取)</em>"
    report_block = ""
    if data:
        report_text = tw_chip_price.format_report(data)
        # Colorize emoji headers for readability
        escaped = html_lib.escape(report_text)
        report_block = f'<pre class="report">{escaped}</pre>'
    if error:
        report_block = f'<div class="error">⚠ {html_lib.escape(error)}</div>'
    code_attr = html_lib.escape(code or "")
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
  pre.report {{ background: white; padding: 16px; border-radius: 6px;
                 font-size: 0.85em; line-height: 1.45;
                 box-shadow: 0 1px 3px rgba(0,0,0,0.06);
                 overflow-x: auto; white-space: pre-wrap;
                 font-family: "SF Mono", "Menlo", "Consolas", monospace; }}
  nav a {{ margin-right: 12px; color: #0066cc; text-decoration: none; }}
</style>
</head>
<body>
<nav><a href="/">← 大盤 dashboard</a> <a href="/chip-price">籌碼價量分析</a></nav>
<h1>📊 籌碼價量分析 (broker × price × time)</h1>

<form method="get" action="/chip-price">
  <label for="code">股票代號:</label>
  <input type="text" id="code" name="code" value="{code_attr}"
         placeholder="例: 2313" autofocus required>
  <button type="submit">查詢 (用快取)</button>
  <button type="submit" name="fresh" value="1" class="secondary">即時抓取 (5-15秒)</button>
</form>

<div class="recent">📂 近期快取 (點擊直接看)：{recent_links}</div>

{source_block}
{report_block}
</body>
</html>"""


@app.route("/chip-price")
def chip_price():
    code = (request.args.get("code") or "").strip()
    date = (request.args.get("date") or "").strip() or None
    force_fetch = request.args.get("fresh") == "1"
    if not code:
        return _render_chip_price_page()
    data, source = _load_or_run(code, date=date, force_fetch=force_fetch)
    if source.startswith("error:"):
        return _render_chip_price_page(code=code, error=source[7:].strip())
    return _render_chip_price_page(code=code, data=data, source=source)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"Dashboard: http://localhost:{args.port}/")
    app.run(host=args.host, port=args.port, debug=False)
