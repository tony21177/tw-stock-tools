#!/usr/bin/env python3
"""一年高低點極端榜 (tw_extremes)

全市場個股(4 位數非 ETF)近一年:
  📉 距最高點跌幅最大 Top N — (現價 − 一年最高)/一年最高,最深的
  📈 距最低點漲幅最大 Top N — (現價 − 一年最低)/一年最低,最強的

價格用 **還原價**(FinMind TaiwanStockPriceAdj 全市場單日,含還原 high/low/close),
除權息不會被當成跌幅。一年最高/最低取 intraday 還原高/低;現價取最新交易日還原收盤。
逐日全市場快取 cache/year_prices/{date}.json(首建約 243 次抓取、之後每日增量)。

用法:
  tw_extremes.py                       # 極端榜(建/更新快取)
  tw_extremes.py --top 20 --json-out o.json
  tw_extremes.py --line-to a,b         # 推播
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
DAY_DIR = os.path.join(CACHE, "year_prices")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
YEAR_DAYS = 250                 # 回看交易日上限(約一年 243)
MIN_DAYS = 60                   # 需 ≥ 此交易日才進榜(排除剛上市)
ACTIVE_WITHIN = 2               # 最近 N 交易日內需有成交(排除停牌/下市櫃)


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


def _fm(dataset: str, params: dict, token: str) -> list[dict]:
    p = {"dataset": dataset, "token": token, **params}
    req = urllib.request.Request(FINMIND + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("data", [])


def _trading_dates(end_iso: str, token: str) -> list[str]:
    """近一年交易日(升冪),取自 2330 日線。"""
    start = (datetime.strptime(end_iso, "%Y-%m-%d")
             - timedelta(days=380)).strftime("%Y-%m-%d")
    rows = _fm("TaiwanStockPrice",
               {"data_id": "2330", "start_date": start, "end_date": end_iso},
               token)
    ds = sorted({r["date"] for r in rows})
    return ds[-YEAR_DAYS:]


def _day_prices(date_iso: str, token: str) -> dict:
    """某交易日全市場還原 {stock_id: [max, min, close]}。逐日快取。"""
    path = os.path.join(DAY_DIR, f"{date_iso.replace('-', '')}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    rows = _fm("TaiwanStockPriceAdj",
               {"start_date": date_iso, "end_date": date_iso}, token)
    out = {}
    for r in rows:
        if r.get("date") != date_iso:
            continue
        c = r.get("close")
        if c and r.get("max") and r.get("min"):
            out[r["stock_id"]] = [r["max"], r["min"], c]
    if out:
        os.makedirs(DAY_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, path)
    return out


def _in_universe(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


NAME_CACHE = os.path.join(CACHE, "finmind_names.json")


def _finmind_names(token: str, max_age_h: float = 168.0) -> dict:
    """全股中文名 {code: name}(FinMind TaiwanStockInfo,含興櫃/全額交割,
    補 TWSE ISIN 漏的)。週快取。"""
    if os.path.exists(NAME_CACHE):
        if (datetime.now().timestamp() - os.path.getmtime(NAME_CACHE)) / 3600 < max_age_h:
            try:
                with open(NAME_CACHE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    try:
        rows = _fm("TaiwanStockInfo", {}, token)
    except Exception:
        return {}
    m = {}
    for r in rows:
        sid, nm = r.get("stock_id"), r.get("stock_name")
        if sid and nm and sid not in m:
            m[sid] = nm
    if m:
        try:
            os.makedirs(CACHE, exist_ok=True)
            tmp = NAME_CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False)
            os.replace(tmp, NAME_CACHE)
        except Exception:
            pass
    return m


def _fut_star(code):
    """有個股期 → ★(全站標準)"""
    try:
        import tw_stock_futures as _sf
        return " ★" if code in _sf.fut_stock_set() else ""
    except Exception:
        return ""


def compute_extremes(end_iso: str | None = None, top: int = 20,
                     token: str | None = None) -> dict:
    token = token or _token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    end_iso = end_iso or datetime.now().strftime("%Y-%m-%d")
    try:
        dates = _trading_dates(end_iso, token)
    except Exception as e:
        return {"error": f"交易日曆抓取失敗: {type(e).__name__}: {e}"}
    if not dates:
        return {"error": "無交易日資料"}
    hi, lo, cur, hidate, lodate, ndays = {}, {}, {}, {}, {}, {}
    last_idx = {}                          # 該股最後出現的交易日 index
    for i, d in enumerate(dates):
        try:
            day = _day_prices(d, token)
        except Exception:
            continue
        if i % 40 == 0:
            print(f"[extremes] {i+1}/{len(dates)} {d}", file=sys.stderr, flush=True)
        for code, (mx, mn, cl) in day.items():
            if not _in_universe(code):
                continue
            if mx > hi.get(code, -1e18):
                hi[code] = mx; hidate[code] = d
            if mn < lo.get(code, 1e18):
                lo[code] = mn; lodate[code] = d
            cur[code] = cl                      # 日期升冪 → 最後 = 最新
            ndays[code] = ndays.get(code, 0) + 1
            last_idx[code] = i
    latest = dates[-1]
    active_min = len(dates) - ACTIVE_WITHIN    # 需在最近 ACTIVE_WITHIN 交易日內有成交
    try:
        sys.path.insert(0, os.path.join(HERE, "concept_momentum"))
        from stock_names import get_name
    except Exception:
        def get_name(c, d=""):
            return d
    fmnames = _finmind_names(token)      # 補 TWSE ISIN 漏的興櫃等

    def _name(code):
        nm = get_name(code, "")
        if not nm or nm == code:
            nm = fmnames.get(code, "")
        return "" if nm == code else nm
    recs = []
    n_delisted = 0
    for code, c in cur.items():
        if ndays[code] < MIN_DAYS or hi[code] <= 0 or lo[code] <= 0:
            continue
        if last_idx[code] < active_min:        # 近期無成交 = 停牌/下市櫃 → 排除
            n_delisted += 1
            continue
        dd = (c - hi[code]) / hi[code] * 100          # 距高(≤0)
        ru = (c - lo[code]) / lo[code] * 100          # 距低(≥0)
        recs.append({
            "code": code, "name": _name(code) + _fut_star(code),
            "close": round(c, 2),
            "yr_high": round(hi[code], 2), "high_date": hidate[code],
            "yr_low": round(lo[code], 2), "low_date": lodate[code],
            "drawdown": round(dd, 1), "rally": round(ru, 1),
            "ndays": ndays[code],
        })
    drop = sorted(recs, key=lambda r: r["drawdown"])[:top]
    rise = sorted(recs, key=lambda r: -r["rally"])[:top]
    return {"date": latest, "n_universe": len(recs), "n_days": len(dates),
            "n_delisted": n_delisted, "drawdown": drop, "rally": rise}


# ── 呈現 ────────────────────────────────────────────────
def _fmt_dt(d: str) -> str:
    """YYYYMMDD → YY/MM/DD(含年份,分辨去年/今年的高低點)。"""
    d = d.replace("-", "")
    return f"{d[2:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d


def format_report(data: dict, top: int = 20) -> str:
    if data.get("error"):
        return f"一年高低極端榜: {data['error']}"
    d = data["date"].replace("-", "")
    lines = [f"📊 一年高低極端榜 ({d[:4]}/{d[4:6]}/{d[6:]})",
             "還原價｜距一年高/低｜⚠ 觀察工具非買賣訊號",
             "━━━━━━━━━━━━",
             f"📉 距最高點跌幅最大 Top{min(top, len(data['drawdown']))}:"]
    for i, r in enumerate(data["drawdown"][:top], 1):
        lines.append(f"{i:2d}. {r['code']} {r['name']} {r['drawdown']:+.1f}%"
                     f"(高{r['yr_high']:g}@{_fmt_dt(r['high_date'])}→收{r['close']:g})")
    lines.append(f"\n📈 距最低點漲幅最大 Top{min(top, len(data['rally']))}:")
    for i, r in enumerate(data["rally"][:top], 1):
        lines.append(f"{i:2d}. {r['code']} {r['name']} {r['rally']:+.1f}%"
                     f"(低{r['yr_low']:g}@{_fmt_dt(r['low_date'])}→收{r['close']:g})")
    lines.append(f"\n樣本 {data['n_universe']} 檔・回看 {data['n_days']} 交易日"
                 f"(需≥{MIN_DAYS}日、已排除停牌/下市櫃 {data.get('n_delisted', 0)} 檔)"
                 f"｜還原價、除息不失真")
    return "\n".join(lines)


def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/extremes")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:960px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;}
  th:nth-child(2),td:nth-child(2){text-align:left;}
  th{background:#fafafa;color:#555;white-space:nowrap;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;} .small{font-size:.85em;color:#666;}
  .note{background:#eef5ff;border:1px solid #cfe0f5;border-radius:6px;padding:10px 14px;font-size:.88em;line-height:1.6;}
</style>"""
    d = data.get("date", "").replace("-", "")
    fmt = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>一年高低極端榜</title>{css}</head><body>{nav}'
            f'<h1>📊 一年高低極端榜 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    def _tbl(rows, kind):
        h = ('<div style="overflow-x:auto"><table><thead><tr>'
             '<th>#</th><th>標的</th><th>現價</th><th>一年高</th><th>高點日</th>'
             '<th>距高%</th><th>一年低</th><th>低點日</th><th>距低%</th>'
             '</tr></thead><tbody>')
        for i, r in enumerate(rows, 1):
            ddcls = "dn" if r["drawdown"] < 0 else ""
            rucls = "up" if r["rally"] > 0 else ""
            h += (f'<tr><td>{i}</td><td>{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                  f'<td>{r["close"]:g}</td><td>{r["yr_high"]:g}</td>'
                  f'<td>{_fmt_dt(r["high_date"])}</td>'
                  f'<td class="{ddcls}">{r["drawdown"]:+.1f}%</td>'
                  f'<td>{r["yr_low"]:g}</td><td>{_fmt_dt(r["low_date"])}</td>'
                  f'<td class="{rucls}">{r["rally"]:+.1f}%</td></tr>')
        return h + '</tbody></table></div>'

    return (head +
            f'<section><p class="small">全市場 4 位數個股(非 ETF)近一年極端榜。'
            f'還原價(除權息不失真)。樣本 {data["n_universe"]} 檔・回看 '
            f'{data["n_days"]} 交易日(上市未滿需≥{MIN_DAYS}日;'
            f'<b>已排除停牌/下市櫃 {data.get("n_delisted", 0)} 檔</b>'
            f'——近 {ACTIVE_WITHIN} 交易日無成交者)。⚠ 觀察工具、非買賣訊號。</p></section>'
            f'<section><h3>📉 距最高點跌幅最大 Top{len(data["drawdown"])}</h3>'
            + _tbl(data["drawdown"], "drop") + '</section>'
            f'<section><h3>📈 距最低點漲幅最大 Top{len(data["rally"])}</h3>'
            + _tbl(data["rally"], "rise") + '</section>'
            '<section class="note">📖 <b>計算方式</b>:'
            '<b>距高%</b> =(現價 − 近一年最高)/ 近一年最高(≤0,越負跌越深);'
            '<b>距低%</b> =(現價 − 近一年最低)/ 近一年最低(≥0,越大漲越多)。'
            '一年高/低取 intraday 還原高/低、現價取最新交易日還原收盤;'
            '皆用<b>還原價</b>,除權息不會被當成跌幅。上市未滿一年者以上市後資料計。</section>'
            '</body></html>')


def _push(report: str, recipients: list[str]) -> None:
    sys.path.insert(0, HERE)
    import line_push
    tok = line_push.resolve_token()
    for r in recipients:
        ok = line_push.push_text(report, tok, r)
        print(f"[line] → {r[:8]}…: {'✅' if ok else '❌'}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--line-to")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    data = compute_extremes(args.date, args.top)
    if data.get("error"):
        print(data["error"], file=sys.stderr)
    report = format_report(data, args.top)
    print(report)
    if args.line_to and not data.get("error"):
        _push(report, [x for x in args.line_to.split(",") if x.strip()])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n→ 已存 {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
