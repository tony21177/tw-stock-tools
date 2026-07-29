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

# 「融資大減=斷頭潮」落底掃描:找融資急殺(斷頭/認賠)+ 股價下跌的洗盤股(反市場低接)
LOOKBACK = 5        # 觀察窗(交易日):近 5 日融資變化
MIN_DROP_PCT = 8.0  # 近 5 日融資減少 ≥ 此% 才算「大量」斷頭
MIN_BAL = 300       # 一週前融資餘額 ≥ 此(張),才談得上「大量」
CALL = 130.0        # 追繳/斷頭線(維持率參考)
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
    dk_all = [d.replace("-", "") for d in dates]
    latest = dk_all[-1]
    d1 = dk_all[-2] if len(dk_all) >= 2 else latest
    d5 = dk_all[-1 - LOOKBACK] if len(dk_all) > LOOKBACK else dk_all[0]
    recs = []
    for code, hist in margin_series.items():
        if not (len(code) == 4 and code.isdigit() and not code.startswith("00")):
            continue
        bald = {h["date"]: h["balance"] for h in hist}
        if latest not in bald:
            continue                                # 需最新日仍有融資
        bal = bald[latest]
        b1 = bald.get(d1, bal)
        b5 = bald.get(d5)
        if b5 is None or b5 < MIN_BAL:              # 需一週前有一定量的融資(才談「大量斷」)
            continue
        drop5 = b5 - bal                            # 5 日融資減少(張,正=減)
        drop5_pct = round(drop5 / b5 * 100, 1)
        drop1 = b1 - bal                            # 1 日融資減少(張)
        drop1_pct = round(drop1 / b1 * 100, 1) if b1 > 0 else 0.0
        prices = close_series.get(code, {})
        cur = prices.get(latest)
        p5 = prices.get(d5)
        if not cur or not p5:
            continue
        ret5 = round((cur / p5 - 1) * 100, 1)       # 5 日股價%
        if drop5_pct < MIN_DROP_PCT or ret5 >= 0:   # 要「融資大減 + 股價下跌」=斷頭賣壓
            continue
        cost = compute_recursive_cost(hist, prices)
        typ = market.get(code, "twse")
        ratio = RATIO_TPEX if typ == "tpex" else RATIO_TWSE
        mr = round(cur / (cost * ratio) * 100, 0) if cost and cost > 0 else None
        wash_gap = round(drop5_pct - abs(ret5), 1)  # 清洗強度=融資減幅−股價跌幅
        recs.append({
            "code": code, "name": names.get(code, ""),
            "market": "上櫃" if typ == "tpex" else ("興櫃" if typ == "emerging" else "上市"),
            "close": round(cur, 2), "ret5": ret5,
            "balance": bal, "bal5": b5,
            "drop5": drop5, "drop5_pct": drop5_pct,
            "drop1": drop1, "drop1_pct": drop1_pct,
            "mr": mr, "wash": wash_gap > 0, "wash_gap": wash_gap,
        })
    recs.sort(key=lambda r: -r["drop5_pct"])        # 融資減幅% 大→小
    return {"date": dates[-1], "n_days": len(dates), "rows": recs}


# ── 呈現 ────────────────────────────────────────────────
def format_report(data: dict, top: int = 30) -> str:
    if data.get("error"):
        return f"融資大減(斷頭潮)掃描: {data['error']}"
    d = data["date"].replace("-", "")
    rows = data["rows"]
    lines = [f"💥 融資大減(斷頭潮)掃描 ({d[:4]}/{d[4:6]}/{d[6:]})",
             f"近{LOOKBACK}日融資急殺+股價下跌=斷頭賣壓宣洩(低接觀察)",
             "━━━━━━━━━━━━",
             f"融資減幅% 排行 Top{min(top, len(rows))}(共{len(rows)}檔):"]
    for i, r in enumerate(rows[:top], 1):
        wash = "🧹清洗" if r["wash"] else ""
        mr = f"維持率{r['mr']:.0f}%" if r["mr"] is not None else ""
        lines.append(
            f"{i:2d}. {r['code']} {r['name']}({r['market']}) "
            f"融資{LOOKBACK}日 −{r['drop5_pct']:.0f}%(−{r['drop5']:,}張)"
            f" 股價{r['ret5']:+.0f}% {wash} 收{r['close']:g} {mr} 餘{r['balance']:,}張")
    if not rows:
        lines.append("  (無符合)")
    lines.append(f"\n🧹清洗=融資減幅>股價跌幅(斷頭殺過頭、浮額清洗、常見落底)。"
                 f"⚠ 融資/還原價 EOD 估算、非即時,斷頭≠保證反彈,非買賣訊號。")
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
  th{background:#fafafa;color:#555;cursor:pointer;user-select:none;}
  th:hover{background:#eef2f7;} th .ar{color:#0066cc;font-size:.9em;}
  .red{color:#fff;background:#c0392b;border-radius:3px;padding:1px 5px;}
  .org{color:#fff;background:#e67e22;border-radius:3px;padding:1px 5px;}
  .dn{color:#0a8a3a;}
  .small{font-size:.85em;color:#666;} .note{background:#fff3f2;border:1px solid #f5cfcf;border-radius:6px;padding:10px 14px;font-size:.88em;line-height:1.6;}
</style>"""
    d = data.get("date", "").replace("-", "")
    fmt = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>融資大減斷頭潮掃描</title>{css}</head><body>{nav}'
            f'<h1>💥 融資大減(斷頭潮)掃描 — {fmt}</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'
    rows = data["rows"]

    def _tbl(rows, tid):
        if not rows:
            return '<p class="small">(無符合)</p>'
        cols = ["#", "標的", "市場", "現價", f"{LOOKBACK}日股價%",
                f"{LOOKBACK}日融資減%", f"{LOOKBACK}日減(張)", "1日融資減%",
                "1日減(張)", "融資餘額", "維持率", "清洗強度"]
        h = (f'<div style="overflow-x:auto"><table id="{tid}"><thead><tr>'
             + "".join(f'<th onclick="sortT(\'{tid}\',{i})">{c}'
                       f'<span class="ar"></span></th>'
                       for i, c in enumerate(cols))
             + '</tr></thead><tbody>')
        for i, r in enumerate(rows, 1):
            mr = (f'<td data-v="{r["mr"]}">{r["mr"]:.0f}%</td>'
                  if r["mr"] is not None else '<td data-v="NaN">—</td>')
            wg = r["wash_gap"]
            wgtxt = (f'🧹+{wg:.0f}' if wg > 0 else f'{wg:.0f}')
            d1p = r["drop1_pct"]
            h += (f'<tr><td data-v="{i}">{i}</td>'
                  f'<td>{_h.escape(r["code"])} {_h.escape(r["name"])}</td>'
                  f'<td>{r["market"]}</td>'
                  f'<td data-v="{r["close"]}">{r["close"]:g}</td>'
                  f'<td data-v="{r["ret5"]}" class="dn">{r["ret5"]:+.1f}%</td>'
                  f'<td data-v="{r["drop5_pct"]}"><span class="red">−{r["drop5_pct"]:.0f}%</span></td>'
                  f'<td data-v="{r["drop5"]}">−{r["drop5"]:,}</td>'
                  f'<td data-v="{d1p}">{("−" if d1p>=0 else "+")}{abs(d1p):.0f}%</td>'
                  f'<td data-v="{r["drop1"]}">{"−" if r["drop1"]>=0 else "+"}{abs(r["drop1"]):,}</td>'
                  f'<td data-v="{r["balance"]}">{r["balance"]:,}</td>'
                  + mr +
                  f'<td data-v="{wg}">{wgtxt}</td></tr>')
        return h + '</tbody></table></div>'

    return (head +
            f'<section><p class="small">全市場 4 位數個股,近 <b>{LOOKBACK}</b> 交易日'
            f'<b>融資餘額大減(≥{MIN_DROP_PCT:.0f}%)且股價下跌</b> = 斷頭/認賠賣壓宣洩。'
            f'依融資減幅% 排序(共 {len(rows)} 檔),點標題可排序。'
            f'反市場低接觀察 —— ⚠ 斷頭≠保證反彈,非買賣訊號。</p></section>'
            f'<section><h3>💥 融資大減(斷頭潮)排行</h3>'
            + _tbl(rows, "twash") + '</section>'
            '<section class="note">📖 <b>邏輯</b>:「發生大量斷頭」的觀察指標是'
            '<b>融資餘額急速減少</b>(斷頭/認賠強制賣出湧出),不是維持率的水位。'
            f'<b>{LOOKBACK}日融資減%</b> =(5 交易日前餘額 − 今餘額)/5日前餘額;'
            f'同時要求 <b>{LOOKBACK}日股價下跌</b>(排除獲利了結那種漲時融資減)。'
            '<b>清洗強度</b> = 融資減幅% − 股價跌幅%(>0=🧹融資殺得比股價兇、浮額被洗掉,'
            '越大越徹底,常見落底;≤0=融資減幅其實沒超過股價跌)。'
            '<b>1日融資減%</b> 看今天剛發生的急斷頭(可點此欄排序抓「今天正在斷」的)。'
            '<b>維持率</b>(遞迴成本線估)供參:越低代表被斷的部位套越深。'
            '<br>⚠ 融資餘額為 EOD、還原價估算;斷頭賣壓宣洩<b>不保證</b>反彈(可能基本面壞)。'
            '單檔精確用 /chip 或 tw_margin_lookup。非買賣訊號。</section>'
            + _SORT_JS + '</body></html>')


_SORT_JS = """<script>
function sortT(tid,col){
  var t=document.getElementById(tid), tb=t.tBodies[0];
  var rows=Array.prototype.slice.call(tb.rows);
  var dir=(t.dataset.col==col && t.dataset.dir=='asc')?'desc':'asc';
  rows.sort(function(a,b){
    var x=a.cells[col].getAttribute('data-v'), y=b.cells[col].getAttribute('data-v'), r;
    if(x!==null && y!==null){
      var xn=parseFloat(x), yn=parseFloat(y);
      if(isNaN(xn)&&isNaN(yn))return 0; if(isNaN(xn))return 1; if(isNaN(yn))return -1;
      r=xn-yn;
    } else { r=a.cells[col].textContent.trim().localeCompare(b.cells[col].textContent.trim(),'zh-Hant'); }
    return dir=='asc'?r:-r;
  });
  rows.forEach(function(row){tb.appendChild(row);});
  t.dataset.col=col; t.dataset.dir=dir;
  var ths=t.tHead.rows[0].cells;
  for(var i=0;i<ths.length;i++){var a=ths[i].querySelector('.ar'); if(a)a.textContent='';}
  var ar=ths[col].querySelector('.ar'); if(ar)ar.textContent=(dir=='asc'?' ▲':' ▼');
}
</script>"""


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
