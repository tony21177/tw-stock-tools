#!/usr/bin/env python3
"""全市場融資維持率斷頭掃描 (tw_margin_scan)

掃全市場個股(4 位數非 ETF、有融資餘額)的融資維持率,找出:
  🔴 追繳/斷頭區  維持率 < 130%(券商發追繳令、補繳不足即斷頭處分)
  🟠 斷頭邊緣      130% ≤ 維持率 < 140%(警戒)

維持率 = 現價 ÷ (遞迴融資成本線 × 融資成數) × 100%
  遞迴成本線(XQ/三竹口徑,重用 tw_margin_monitor.compute_recursive_cost):
    今日成本 = (昨成本×(餘額−買進) + 收盤×買進) ÷ 餘額;種子不敏感、近一年即收斂
  融資成數:上市(twse)6 成、上櫃(tpex)5 成 —— 同時列 5 成/6 成兩口徑
  (實際成數依券商與個股而異)

資料:全市場融資買/餘額(FinMind TaiwanStockMarginPurchaseShortSale 逐日,
  快取 cache/margin_hist/)+ 還原收盤(重用 tw_extremes 逐日快取 year_prices)。
⚠ 用還原收盤(除息不失真、但與看盤軟體「原始價」口徑略異)→ 這是全市場**篩選**;
  單檔精確請用 tw_margin_lookup.py(原始價 + 即時價 + FIFO 套牢分析)。

用法:
  tw_margin_scan.py                     # 掃描(建/更新快取)
  tw_margin_scan.py --line-to a,b       # 推播
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
MARGIN_DIR = os.path.join(CACHE, "margin_hist")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

import tw_extremes as ex                                   # noqa: E402
from tw_margin_monitor import compute_recursive_cost        # noqa: E402

WARN = 140.0        # 斷頭邊緣(警戒)上界
CALL = 130.0        # 追繳/斷頭線
MIN_BALANCE = 100   # 融資餘額 ≥ N 張才掃(排除零星)
RATIO_TWSE = 0.60
RATIO_TPEX = 0.50


def _margin_day(date_iso: str, token: str) -> dict:
    """某交易日全市場融資 {code: [buy, balance]}(張)。逐日快取。"""
    path = os.path.join(MARGIN_DIR, f"{date_iso.replace('-', '')}.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    p = {"dataset": "TaiwanStockMarginPurchaseShortSale", "token": token,
         "start_date": date_iso, "end_date": date_iso}
    req = urllib.request.Request(FINMIND + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.load(r).get("data", [])
    except Exception:
        return {}
    out = {}
    for r in rows:
        if r.get("date") != date_iso:
            continue
        code = r.get("stock_id", "")
        bal = int(r.get("MarginPurchaseTodayBalance") or 0)
        buy = int(r.get("MarginPurchaseBuy") or 0)
        if code:
            out[code] = [buy, bal]
    if out:
        os.makedirs(MARGIN_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, path)
    return out


def _market_map(token: str) -> dict:
    """{code: type}  type ∈ twse/tpex/emerging(TaiwanStockInfo,週快取)。"""
    cache = os.path.join(CACHE, "stock_market_type.json")
    if os.path.exists(cache):
        if (datetime.now().timestamp() - os.path.getmtime(cache)) / 3600 < 168:
            try:
                with open(cache, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    try:
        rows = ex._fm("TaiwanStockInfo", {}, token)
    except Exception:
        return {}
    m = {r["stock_id"]: r.get("type", "")
         for r in rows if r.get("stock_id")}
    if m:
        try:
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(m, f)
        except Exception:
            pass
    return m


def scan(end_iso: str | None = None, token: str | None = None) -> dict:
    token = token or ex._token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    end_iso = end_iso or datetime.now().strftime("%Y-%m-%d")
    try:
        dates = ex._trading_dates(end_iso, token)
    except Exception as e:
        return {"error": f"交易日曆抓取失敗: {type(e).__name__}: {e}"}
    if not dates:
        return {"error": "無交易日資料"}
    market = _market_map(token)
    names = ex._finmind_names(token)
    close_series: dict = {}      # code -> {YYYYMMDD: adj_close}
    margin_series: dict = {}     # code -> [{date, buy, balance}]
    for i, d in enumerate(dates):
        dk = d.replace("-", "")
        try:
            dp = ex._day_prices(d, token)          # {code:[mx,mn,cl]} 還原
            md = _margin_day(d, token)             # {code:[buy,bal]}
        except Exception:
            continue
        if i % 30 == 0:
            print(f"[margin-scan] {i+1}/{len(dates)} {d}", file=sys.stderr, flush=True)
        for code, v in dp.items():
            close_series.setdefault(code, {})[dk] = v[2]
        for code, (buy, bal) in md.items():
            margin_series.setdefault(code, []).append(
                {"date": dk, "buy": buy, "balance": bal})
    latest = dates[-1].replace("-", "")
    recs = []
    for code, hist in margin_series.items():
        if not (len(code) == 4 and code.isdigit() and not code.startswith("00")):
            continue
        bal = hist[-1]["balance"]
        if hist[-1]["date"] != latest or bal < MIN_BALANCE:
            continue                                # 需最新日仍有餘額
        prices = close_series.get(code, {})
        cur = prices.get(latest)
        if not cur:
            continue
        cost = compute_recursive_cost(hist, prices)
        if not cost or cost <= 0:
            continue
        mr6 = round(cur / (cost * RATIO_TWSE) * 100, 1)
        mr5 = round(cur / (cost * RATIO_TPEX) * 100, 1)
        typ = market.get(code, "twse")
        mr = mr5 if typ == "tpex" else mr6          # 市場成數口徑
        if mr >= WARN:                              # 只留警戒以下
            continue
        recs.append({
            "code": code, "name": names.get(code, ""),
            "market": "上櫃" if typ == "tpex" else ("興櫃" if typ == "emerging" else "上市"),
            "close": round(cur, 2), "cost": round(cost, 2),
            "mr": mr, "mr6": mr6, "mr5": mr5, "balance": bal,
        })
    recs.sort(key=lambda r: r["mr"])
    called = [r for r in recs if r["mr"] < CALL]
    edge = [r for r in recs if CALL <= r["mr"] < WARN]
    return {"date": dates[-1], "n_days": len(dates),
            "called": called, "edge": edge}


# ── 呈現 ────────────────────────────────────────────────
def format_report(data: dict, top: int = 30) -> str:
    if data.get("error"):
        return f"融資維持率斷頭掃描: {data['error']}"
    d = data["date"].replace("-", "")
    called, edge = data["called"], data["edge"]

    def _row(r):
        return (f"  {r['code']} {r['name']}({r['market']}) 維持率 {r['mr']:.0f}%"
                f"(6成{r['mr6']:.0f}/5成{r['mr5']:.0f})"
                f" 收{r['close']:g} 成本{r['cost']:g} 融資{r['balance']:,}張")

    lines = [f"⚠️ 融資維持率斷頭掃描 ({d[:4]}/{d[4:6]}/{d[6:]})",
             "維持率=現價÷(遞迴成本線×融資成數)｜還原價篩選、非即時",
             "━━━━━━━━━━━━",
             f"🔴 追繳/斷頭區 維持率<130%({len(called)}檔):"]
    for r in called[:top]:
        lines.append(_row(r))
    if not called:
        lines.append("  (無)")
    lines.append(f"\n🟠 斷頭邊緣 130~140%({len(edge)}檔):")
    for r in edge[:top]:
        lines.append(_row(r))
    if not edge:
        lines.append("  (無)")
    lines.append("\n⚠ 維持率為估算(遞迴成本線、還原價);券商實際成數/整戶維持率"
                 "不同。單檔精確用 /chip 或 tw_margin_lookup。非買賣訊號。")
    return "\n".join(lines)


def render_html(data: dict) -> str:
    import html as _h
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/extremes">📊 一年高低榜</a> '
           '<a href="/stock-futures">🔥 個股期火熱</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:960px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:5px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th:nth-child(2),td:nth-child(2),th:nth-child(3),td:nth-child(3){text-align:left;}
  th{background:#fafafa;color:#555;}
  .red{color:#fff;background:#c0392b;border-radius:3px;padding:1px 5px;}
  .org{color:#fff;background:#e67e22;border-radius:3px;padding:1px 5px;}
  .small{font-size:.85em;color:#666;} .note{background:#fff3f2;border:1px solid #f5cfcf;border-radius:6px;padding:10px 14px;font-size:.88em;line-height:1.6;}
</style>"""
    d = data.get("date", "").replace("-", "")
    fmt = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>融資維持率斷頭掃描</title>{css}</head><body>{nav}'
            f'<h1>⚠️ 融資維持率斷頭掃描 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    def _tbl(rows, badge):
        if not rows:
            return '<p class="small">(無)</p>'
        h = ('<div style="overflow-x:auto"><table><thead><tr>'
             '<th>#</th><th>標的</th><th>市場</th><th>維持率</th><th>6成</th>'
             '<th>5成</th><th>現價</th><th>成本線</th><th>融資餘額(張)</th>'
             '</tr></thead><tbody>')
        for i, r in enumerate(rows, 1):
            h += (f'<tr><td>{i}</td><td>{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                  f'<td>{r["market"]}</td>'
                  f'<td><span class="{badge}">{r["mr"]:.0f}%</span></td>'
                  f'<td>{r["mr6"]:.0f}%</td><td>{r["mr5"]:.0f}%</td>'
                  f'<td>{r["close"]:g}</td><td>{r["cost"]:g}</td>'
                  f'<td>{r["balance"]:,}</td></tr>')
        return h + '</tbody></table></div>'

    return (head +
            f'<section><p class="small">全市場 4 位數個股(融資餘額 ≥{MIN_BALANCE} 張)近一年'
            f'({data["n_days"]} 交易日)遞迴融資成本線估維持率。維持率欄用<b>市場成數</b>'
            f'(上市6成/上櫃5成),另列 6 成/5 成兩口徑。⚠ 觀察工具、非買賣訊號。</p></section>'
            f'<section><h3>🔴 追繳/斷頭區 — 維持率 &lt; 130%（{len(data["called"])}）</h3>'
            + _tbl(data["called"], "red") + '</section>'
            f'<section><h3>🟠 斷頭邊緣 — 維持率 130% ~ 140%（{len(data["edge"])}）</h3>'
            + _tbl(data["edge"], "org") + '</section>'
            '<section class="note">📖 <b>計算/口徑</b>:'
            '<b>維持率</b> = 現價 ÷ (遞迴融資成本線 × 融資成數) × 100%。'
            '<b>遞迴成本線</b>(XQ/三竹同款)= 逐日「今日成本=(昨成本×(餘額−買進)+收盤×買進)÷餘額」,'
            '近一年迭代(種子不敏感、會收斂)。<b>融資成數</b>:上市 6 成、上櫃 5 成(法規);'
            '實際依券商/個股而異,故同列 6 成(較保守、維持率較低)與 5 成兩口徑。'
            '<b>&lt;130%</b>=追繳線(券商發追繳令、補繳不足即斷頭處分);<b>130~140%</b>=警戒邊緣。'
            '<br>⚠ 用<b>還原收盤</b>估(除息不失真、與看盤軟體原始價略異),且個股維持率≠整戶維持率;'
            '此為全市場<b>篩選</b>,單檔精確請用 /chip 或 tw_margin_lookup(原始價+即時價)。非買賣訊號。</section>'
            '</body></html>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--line-to")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    data = scan(args.date)
    if data.get("error"):
        print(data["error"], file=sys.stderr)
    print(format_report(data))
    if args.line_to and not data.get("error"):
        ex._push(format_report(data), [x for x in args.line_to.split(",") if x.strip()])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n→ 已存 {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
