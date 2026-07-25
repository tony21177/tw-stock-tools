#!/usr/bin/env python3
"""林則行矩陣選股 — 低量箱型盤整 → 爆量突破 + 堆疊偵測.

林則行(前阿布達比主權基金經理人、日本 K 線大師,《飆股的長相》)純技術面
選股法。「矩陣」= 長期低量橫向箱型盤整後爆量突破:
  - 盤整 3-6 個月、震盪幅度 ≤15%(嚴格)、盤整期低量沉澱
  - 突破 = 今日收盤破天花板 + 今日量 = 箱型均量 2-10 倍
  - 多重矩陣堆疊(突破後更高位再形成新箱)= 大飆股相

⚠ 門檻先驗、未回測;純觀察/選股工具,非買賣訊號。假突破需看後續。
"""
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PRICE_DIR = os.path.join(HERE, "concept_momentum", "cache", "lin_matrix_prices")

# 參數(先驗、未回測)
MIN_BOX_DAYS = 60         # 盤整 ≥ 60 交易日(~3 個月)
MAX_BOX_DAYS = 130        # 最長回看 130 交易日(~6 個月)
AMP_TIER1 = 0.15          # ≤15% = ⭐ 標準矩陣
AMP_MAX = 0.15            # 嚴格:震盪幅度 ≤15% 才算矩陣(超過不算)
VOL_SETTLE_RATIO = 0.8    # 盤整期均量 < 長期均量 × 0.8 = 低量沉澱
BREAK_VOL_MIN = 2.0       # 突破量 ≥ 箱型均量 2 倍
BREAK_VOL_MAX = 10.0      # 突破量 ≤ 10 倍(過大 = 異常事件)
NEAR_CEILING = 0.8        # 箱內位階 ≥ 0.8 = 貼天花板


def detect_matrix(series: list[dict], as_of_idx: int = -1,
                  min_days: int = MIN_BOX_DAYS, max_days: int = MAX_BOX_DAYS,
                  amp_max: float = AMP_MAX,
                  vol_ratio: float = VOL_SETTLE_RATIO) -> dict | None:
    """單股序列(日升冪) → 最長低量箱型矩陣，無則 None。

    從 as_of 往回找最長窗口 [i, end] 滿足:
      (max_high−min_low)/min_low ≤ amp_max
      且 窗口均量 < 窗口之前同長度(或全序列)均量 × vol_ratio(低量沉澱)
    """
    n = len(series)
    end = as_of_idx if as_of_idx >= 0 else n + as_of_idx
    if end < min_days:
        return None
    best = None
    # 由最長窗口往短試,取第一個(=最長)符合的
    for span in range(min(max_days, end + 1), min_days - 1, -1):
        i = end - span + 1
        if i < 0:
            continue
        win = series[i:end + 1]
        highs = [b["high"] for b in win]
        lows = [b["low"] for b in win]
        hi, lo = max(highs), min(lows)
        if lo <= 0:
            continue
        amp = (hi - lo) / lo
        if amp > amp_max:
            continue
        box_avg_vol = sum(b["volume"] for b in win) / len(win)
        # 低量沉澱:箱型均量 < 該股較長期均量 × ratio。基準用箱型之前的
        # 全部歷史(最多回看 250 日),捕捉盤整前的活動/急漲量,而非緊鄰
        # 的另一個安靜箱(堆疊時緊鄰是低箱、會誤判)。
        pre = series[max(0, i - 250):i]
        base_vol = (sum(b["volume"] for b in pre) / len(pre) if pre
                    else box_avg_vol)
        if base_vol > 0 and box_avg_vol >= base_vol * vol_ratio:
            continue
        # 盤整期間平均 ATR:箱內每天真實區間的均值(True Range =
        # max(高−低, |高−昨收|, |低−昨收|))。第一根用箱型前一天收盤當昨收。
        prev_close = series[i - 1]["close"] if i > 0 else win[0]["low"]
        trs = []
        for b in win:
            tr = max(b["high"] - b["low"],
                     abs(b["high"] - prev_close),
                     abs(b["low"] - prev_close))
            trs.append(tr)
            prev_close = b["close"]
        atr = sum(trs) / len(trs)
        mid = (hi + lo) / 2
        best = {
            "start": win[0]["date"], "end": win[-1]["date"],
            "days": span, "floor": round(lo, 2), "ceiling": round(hi, 2),
            "amp_pct": round(amp * 100, 1),
            "box_avg_vol": box_avg_vol,
            "atr": round(atr, 2),
            "atr_pct": round(atr / mid * 100, 2) if mid > 0 else 0.0,
            "tier": "⭐" if amp <= AMP_TIER1 else "☆",
        }
        break
    return best


def classify(series: list[dict], matrix: dict) -> dict:
    """今日 K 對矩陣的關係:突破 / 箱內位階。series[-1] = 今日。"""
    today = series[-1]
    close = today["close"]
    vol = today["volume"]
    ceiling, floor = matrix["ceiling"], matrix["floor"]
    box_vol = matrix["box_avg_vol"] or 1
    vol_mult = vol / box_vol
    breakout = (close > ceiling
                and BREAK_VOL_MIN <= vol_mult <= BREAK_VOL_MAX)
    rng = (ceiling - floor) or 1
    box_pos = (close - floor) / rng
    return {
        "close": close, "vol_mult": round(vol_mult, 1),
        "breakout": breakout,
        "in_box": floor <= close <= ceiling,
        "box_pos": round(box_pos, 2),
        "near_ceiling": (floor <= close <= ceiling and box_pos >= NEAR_CEILING),
    }


def count_stacked(series: list[dict], top_matrix: dict) -> int:
    """從最新矩陣往回數連續「更低位置已突破矩陣」的堆疊層數(含當前=1)。

    啟發式:每往回一層,在當前矩陣 start 之前找一個天花板更低的低量箱,
    且其天花板 < 當前地板(代表突破後上移)。找得到就 +1、繼續往回。
    """
    date_idx = {b["date"]: i for i, b in enumerate(series)}
    layers = 1
    cur = top_matrix
    guard = 0
    while guard < 6:
        guard += 1
        start_i = date_idx.get(cur["start"])
        if start_i is None or start_i < MIN_BOX_DAYS:
            break
        lower = detect_matrix(series, as_of_idx=start_i - 1)
        if not lower or lower["ceiling"] >= cur["floor"]:
            break
        layers += 1
        cur = lower
    return layers


def build_signals(series_map: dict, names: dict | None = None) -> dict:
    """對每股 detect+classify+stack → 分三桶。

    回 {date, breakout:[...], watch:[...], boxed:[...]}。
    breakout = 今日突破;watch = 箱內貼天花板;boxed = 所有在箱內。
    每筆:code/name/floor/ceiling/days/amp_pct/atr/atr_pct/tier/box_pos/
    vol_mult/stack。
    """
    names = names or {}
    breakout, watch, boxed = [], [], []
    latest_date = ""
    for code, series in series_map.items():
        if len(series) < MIN_BOX_DAYS + 1:
            continue
        latest_date = max(latest_date, series[-1]["date"])
        # 矩陣 = 今日之前的盤整(排除今日突破日),再用今日判突破
        m = detect_matrix(series, as_of_idx=len(series) - 2)
        if not m:
            continue
        c = classify(series, m)
        stack = count_stacked(series, m)
        row = {
            "code": code, "name": names.get(code, ""),
            "floor": m["floor"], "ceiling": m["ceiling"],
            "days": m["days"], "amp_pct": m["amp_pct"],
            "atr": m["atr"], "atr_pct": m["atr_pct"], "tier": m["tier"],
            "box_pos": c["box_pos"], "vol_mult": c["vol_mult"],
            "stack": stack, "close": c["close"],
        }
        if c["breakout"]:
            breakout.append(row)
        elif c["near_ceiling"]:
            watch.append(row)
        if c["in_box"]:
            boxed.append(row)
    breakout.sort(key=lambda r: -r["vol_mult"])
    watch.sort(key=lambda r: -r["box_pos"])
    boxed.sort(key=lambda r: (-r["stack"], -r["box_pos"]))
    return {"date": latest_date, "breakout": breakout,
            "watch": watch, "boxed": boxed}


# ── 資料抓取(全市場單日 × N 天建序列，每日快取) ──────────────
def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        import subprocess
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=", 1)[1].split()[0]
    except Exception:
        pass
    return ""


def _fetch_day(date_iso: str, token: str) -> list[dict] | None:
    """全市場某日 OHLCV(快取 cache/lin_matrix_prices/{date}.json)。"""
    import re
    os.makedirs(PRICE_DIR, exist_ok=True)
    d8 = date_iso.replace("-", "")
    cache = os.path.join(PRICE_DIR, f"{d8}.json")
    if os.path.exists(cache):
        try:
            with open(cache, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    sys.path.insert(0, HERE)
    import finmind_client as fc
    try:
        rows = fc._call("TaiwanStockPrice",
                        {"start_date": date_iso, "end_date": date_iso}, token)
    except Exception:
        return None
    rows = [r for r in rows if r.get("date") == date_iso
            and re.fullmatch(r"\d{4}", str(r.get("stock_id", "")))
            and not str(r["stock_id"]).startswith("00")
            and r.get("close") and r.get("max") and r.get("min")]
    slim = [{"code": r["stock_id"], "date": d8, "open": r.get("open"),
             "high": r["max"], "low": r["min"], "close": r["close"],
             "volume": r.get("Trading_Volume", 0) or 0} for r in rows]
    if slim:
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False)
        os.replace(tmp, cache)
    return slim


def build_price_series(end_date: str | None = None, days: int = 140,
                       token: str | None = None) -> dict:
    """近 days 交易日全市場 → {code: [bars 日升冪]}。逐日查(快取)。"""
    token = token or _token()
    if not token:
        return {}
    sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
    import market_breadth
    end_date = end_date or datetime.now().strftime("%Y-%m-%d")
    d8 = end_date.replace("-", "")
    dates = market_breadth._twii_trading_dates(d8, days)
    series_map: dict[str, list] = {}
    for i, d in enumerate(dates):
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        rows = _fetch_day(iso, token)
        if not rows:
            continue
        if i and i % 30 == 0:
            print(f"[lin] 建序列 {i}/{len(dates)} 日…", file=sys.stderr,
                  flush=True)
        for r in rows:
            series_map.setdefault(r["code"], []).append(r)
    # 確保各股依日升冪
    for s in series_map.values():
        s.sort(key=lambda b: b["date"])
    return series_map


def fetch_signals(end_date: str | None = None, days: int = 140) -> dict:
    """建序列 + 產生訊號。回 build_signals 結果或 {error}。"""
    token = _token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    sm = build_price_series(end_date, days, token)
    if not sm:
        return {"error": "價格序列建立失敗"}
    names = {}
    try:
        sys.path.insert(0, HERE)
        from stock_names import get_name
        names = {c: get_name(c, "") for c in sm}
    except Exception:
        pass
    return build_signals(sm, names)


# ── 呈現 ────────────────────────────────────────────────────────
_STRATEGY_NOTE = (
    "林則行(前阿布達比主權基金經理人、日本 K 線大師,《飆股的長相》)矩陣選股:"
    "股票長期低量橫向盤整形成「箱型」(矩陣),某天爆量突破天花板 = 進場點。"
    "三條件 — ①盤整 3-6 個月(本工具 ≥60 交易日) ②震盪幅度 ≤15%(嚴格,"
    "⭐標準矩陣;超過不算) ③盤整期低量沉澱、突破當天量=箱型均量 2-10 倍。"
    "天花板=箱型區間高、地板=區間低;堆疊層數=連續矩陣往上疊(鈊象式大飆股相)。"
    "⚠ 門檻先驗未回測、非買賣訊號;爆量突破後仍可能假突破拉回,須看後續。")


def _fmt_row_line(r: dict) -> str:
    return (f"  {r['code']} {r['name']} {r['tier']} "
            f"矩陣 {r['floor']:g}~{r['ceiling']:g}(幅{r['amp_pct']:g}%,"
            f"{r['days']}日) 收{r['close']:g} "
            f"ATR{r.get('atr','-'):g}({r.get('atr_pct',0):g}%) "
            f"位階{r['box_pos']*100:.0f}% 量{r['vol_mult']:g}倍"
            + (f" 堆疊{r['stack']}層" if r['stack'] > 1 else ""))


def format_report(data: dict, top: int = 12) -> str:
    if data.get("error"):
        return f"林則行矩陣選股: {data['error']}"
    d = data["date"]
    lines = [f"📐 林則行矩陣選股 ({d[:4]}/{d[4:6]}/{d[6:]})",
             "低量箱型盤整→爆量突破｜⚠ 先驗未回測、非買賣訊號",
             "━━━━━━━━━━━━"]
    lines.append(f"🚀 今日爆量突破天花板({len(data['breakout'])}):")
    if data["breakout"]:
        for r in data["breakout"][:top]:
            lines.append(_fmt_row_line(r))
    else:
        lines.append("  (無)")
    lines.append(f"\n📦 盤整中·貼天花板待突破({len(data['watch'])}):")
    if data["watch"]:
        for r in data["watch"][:top]:
            lines.append(_fmt_row_line(r))
    else:
        lines.append("  (無)")
    lines.append("\n說明:⭐幅度≤15%(嚴格)｜ATR=盤整期平均真實區間(括號為佔股價%,"
                 "越小越牛皮)｜位階=箱內位置(貼天花板→突破在即)｜"
                 "量倍=今日量/箱型均量｜堆疊=連續矩陣層數(越多越強)")
    return "\n".join(lines)


def render_html(data: dict) -> str:
    import html as _h
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/chip-price">📋 籌碼價量</a> '
           '<a href="/stock-futures">🔥 個股期火熱</a> '
           '<a href="/lin-matrix">📐 林則行矩陣</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1080px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.85em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;}
  th:nth-child(1),td:nth-child(1),th:nth-child(2),td:nth-child(2){text-align:left;}
  th{background:#fafafa;color:#555;}
  .small,small{font-size:.85em;color:#666;}
  .note{background:#eef5ff;border:1px solid #cfe0f5;border-radius:6px;padding:10px 14px;font-size:.88em;line-height:1.6;}
  .pos{color:#c0392b;}
</style>"""
    d = data.get("date", "")
    fmt = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>林則行矩陣選股</title>{css}</head><body>{nav}'
            f'<h1>📐 林則行矩陣選股 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    def _tbl(rows, empty):
        if not rows:
            return f'<p class="small">{empty}</p>'
        h = ('<div style="overflow-x:auto"><table><thead><tr>'
             '<th>代號</th><th>名稱</th><th>級</th><th>矩陣(地板~天花板)</th>'
             '<th>幅度</th><th>盤整均ATR</th><th>盤整</th><th>收盤</th>'
             '<th>箱內位階</th><th>量倍</th><th>堆疊</th></tr></thead><tbody>')
        for r in rows:
            h += (f'<tr><td>{_h.escape(r["code"])}</td>'
                  f'<td>{_h.escape(r["name"])}</td><td>{r["tier"]}</td>'
                  f'<td>{r["floor"]:g} ~ {r["ceiling"]:g}</td>'
                  f'<td>{r["amp_pct"]:g}%</td>'
                  f'<td>{r.get("atr","-"):g} ({r.get("atr_pct",0):g}%)</td>'
                  f'<td>{r["days"]}日</td>'
                  f'<td>{r["close"]:g}</td>'
                  f'<td>{r["box_pos"]*100:.0f}%</td>'
                  f'<td class="{"pos" if r["vol_mult"]>=2 else ""}">'
                  f'{r["vol_mult"]:g}×</td>'
                  f'<td>{"🏗"*r["stack"] if r["stack"]>1 else "—"}</td></tr>')
        return h + '</tbody></table></div>'

    return (head +
            f'<section class="note">📖 <b>策略說明</b>：{_h.escape(_STRATEGY_NOTE)}</section>'
            f'<section><h3>🚀 今日爆量突破天花板（{len(data["breakout"])}）'
            '— 林則行經典進場點</h3>'
            + _tbl(data["breakout"], "今日無突破") + '</section>'
            f'<section><h3>📦 盤整中·貼天花板待突破（{len(data["watch"])}）'
            '— 箱內位階 ≥80%，突破在即</h3>'
            + _tbl(data["watch"], "無貼天花板者") + '</section>'
            f'<section><h3>📋 所有盤整中矩陣（{len(data["boxed"])}）'
            '— 依堆疊層數/位階</h3>'
            + _tbl(data["boxed"][:60], "無") +
            f'<p class="small">資料至 {fmt}｜⭐幅度≤15%(嚴格)｜'
            '盤整均ATR=盤整期間每日「真實區間」的平均(True Range='
            'max(當日高−低, |高−昨收|, |低−昨收|)),括號為佔股價%,'
            '數值越小代表盤整越牛皮、波動越低(林則行低量沉澱的直接量化)｜'
            '箱內位階=(收盤−地板)/(天花板−地板)｜量倍=今日量/箱型均量｜'
            '🏗=堆疊層數。⚠ 先驗未回測、觀察工具非買賣訊號</p></section>'
            '</body></html>')


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--days", type=int, default=140)
    ap.add_argument("--json-out")
    ap.add_argument("--line-to")
    args = ap.parse_args()
    data = fetch_signals(args.date, days=args.days)
    print(format_report(data))
    if args.json_out and not data.get("error"):
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)),
                    exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    if args.line_to and not data.get("error"):
        import line_push
        tok = line_push.resolve_token()
        if tok:
            for r in [x.strip() for x in args.line_to.split(",") if x.strip()]:
                ok = line_push.push_text(format_report(data), tok, r)
                print(f"LINE → {r[:6]}…: {'✅' if ok else '❌'}",
                      file=sys.stderr)


if __name__ == "__main__":
    main()
