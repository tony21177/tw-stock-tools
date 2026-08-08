#!/usr/bin/env python3
"""
/event-trading 事件交易中樞 — 渲染器。

設計:可持續擴充的容器。每個事件類型 = 一個區塊(section),
資料來自 tw_event_data 的重訊分類與內部人快取。分批把模組從
「開發中」轉「上線」。詳見 docs/strategies/event-driven.md。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))


def _ed():
    import tw_event_data as ed
    return ed


def _names():
    """名稱查詢 + 反查(名稱→代號),供「取得股權」標的連結。"""
    try:
        from stock_names import get_name
    except Exception:
        get_name = None
    import json
    try:
        fm = json.load(open(os.path.join(HERE, "cache", "finmind_names.json")))
        fm = fm.get("names", fm) if isinstance(fm, dict) else {}
    except Exception:
        fm = {}
    rev = {}                       # 名稱 → 代號(取最短代號)
    for c, n in fm.items():
        if n and (n not in rev or len(c) < len(rev[n])):
            rev[n] = c

    def name(code):
        if get_name:
            x = get_name(code, "")
            if x and x != code:
                return x
        return fm.get(code, "")
    return name, rev


def _fmt_d(d):
    return f"{d[4:6]}/{d[6:]}" if d and len(d) == 8 else (d or "—")


def _esc(s):
    import html
    return html.escape(str(s))


# ── 模組登錄表(roadmap;新增事件在這裡加一列) ──────────────────
MODULES = [
    ("strategic_buy", "🤝 取得股權/策略投資", "live",
     "上市櫃公司在市場取得他公司股權(元太買台虹型)。重訊「取得…普通股/股份」,"
     "排除取得不動產/設備。⚠ 這是<b>事後 2 日</b>揭露,真 edge 在公告前的分點吸貨(模組 #1 旗艦開發中)。"),
    ("tender_offer", "🎯 公開收購", "live",
     "法定<b>開始前 5 日</b>公告 —— 唯一制度性提前的事件。通常溢價收購,消息一出被收購方常跳空。"),
    ("treasury", "💰 庫藏股買回", "live",
     "董事會決議買回自家股 = 護盤/信心訊號。⚠ 學術上買回宣告的超額報酬有限,需回測驗證。"),
    ("capital_ce", "📊 現增/減資/CB", "live",
     "現金增資(GDR/ADR,如環球晶)、私募、可轉債、減資。稀釋 vs 護盤方向不同,看類型。"),
    ("major_contract", "📝 重大契約/大單", "live",
     "簽訂合資/大單/供應協議(美光×環球晶型)。高影響但難提前,靠即時重訊。"),
    ("insider_pledge", "👤 內部人高設質", "live",
     "董監/大股東股票質押比例高 = 槓桿+潛在賣壓風險。⚠ 月頻資料。"
     "事前申報轉讓(法定提前 3 日)待接。"),
    ("chip_precursor", "🔍 分點吸貨前兆(旗艦)", "dev",
     "模組 #1:全市場掃「單一分點連續大額吸貨+成本集中+集保大戶跳增」,"
     "在取得股權公告<b>前</b>抓策略買家足跡。需回測+跨市場分點掃描,開發中。"),
]


def _event_rows(events, etype, name, limit=25):
    """列出某類型近期事件。strategic_buy 額外抽標的。"""
    rows = [e for e in events if e["type"] == etype][:limit]
    if not rows:
        return '<p class="small">近 3 個月無此類事件(或快取尚未累積)。</p>'
    trs = []
    for e in rows:
        star = ""
        subj = _esc(e["subject"])
        trs.append(
            f'<tr><td>{_fmt_d(e["date"])}</td>'
            f'<td data-kx="{_esc(e["code"])}" style="cursor:pointer">'
            f'{_esc(e["code"])} {_esc(e["name"])}{star}</td>'
            f'<td style="text-align:left">{subj}</td>'
            f'<td class="small">{"上市" if e["market"]=="sii" else "上櫃"}</td></tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>日期</th><th>公司</th><th>主旨</th><th>市場</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>')


def _capital_ce_rows(events, name):
    """現增/減資合併一區,標色分方向。"""
    rows = [e for e in events if e["type"] in ("capital_increase", "capital_reduction")][:30]
    if not rows:
        return '<p class="small">近 3 個月無增減資事件。</p>'
    trs = []
    for e in rows:
        kind = "✂ 減資" if e["type"] == "capital_reduction" else "📈 增資/CB"
        trs.append(
            f'<tr><td>{_fmt_d(e["date"])}</td>'
            f'<td data-kx="{_esc(e["code"])}" style="cursor:pointer">'
            f'{_esc(e["code"])} {_esc(e["name"])}</td><td>{kind}</td>'
            f'<td style="text-align:left">{_esc(e["subject"])}</td></tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>日期</th><th>公司</th><th>類型</th><th>主旨</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>')


def _insider_rows(name, fut_set=None):
    ed = _ed()
    ins = ed.load_insider() or ed.fetch_insider()
    # 每檔取設質比例最高的內部人;≥30% 才列
    by_code = {}
    for i in ins:
        if i["pledge_ratio"] >= 30 and i["hold"] > 0:
            cur = by_code.get(i["code"])
            if not cur or i["pledge_ratio"] > cur["pledge_ratio"]:
                by_code[i["code"]] = i
    rows = sorted(by_code.values(), key=lambda x: -x["pledge_ratio"])[:30]
    if not rows:
        return '<p class="small">無設質比例 ≥30% 的內部人(或快取未建)。</p>'
    trs = []
    for i in rows:
        cls = "u-hot" if i["pledge_ratio"] >= 80 else ""
        trs.append(
            f'<tr class="{cls}"><td data-kx="{_esc(i["code"])}" style="cursor:pointer">'
            f'{_esc(i["code"])} {_esc(i["name"])}</td>'
            f'<td>{_esc(i["title"])}</td><td>{i["pledge_ratio"]:.0f}%</td>'
            f'<td class="small">{i["month"][:4]}/{i["month"][4:6]}</td></tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>公司</th><th>職稱</th><th>設質比例</th><th>資料月</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>'
            '<p class="small">設質比例 = 質押股數 ÷ 該內部人持股;≥80% 標紅。'
            '高設質 = 大股東槓桿高,股價跌時有被斷頭賣壓的風險。月頻資料。</p>')


def render(nav: str, fut_set=None) -> str:
    ed = _ed()
    name, rev = _names()
    events = ed.load_material(months=3)
    asof = events[0]["date"] if events else "—"

    # roadmap 狀態表
    status_rows = []
    for key, label, st, desc in MODULES:
        badge = ('<span style="color:#34c98e">● 上線</span>' if st == "live"
                 else '<span style="color:#e6c56a">🏗 開發中</span>')
        status_rows.append(f'<tr><td>{label}</td><td>{badge}</td>'
                           f'<td style="text-align:left" class="small">{desc}</td></tr>')
    roadmap = ('<section><h3>📋 模組進度(持續擴充)</h3>'
               '<div class="table-scroll"><table class="report-table"><thead><tr>'
               '<th>事件模組</th><th>狀態</th><th>說明</th></tr></thead><tbody>'
               + "".join(status_rows) + '</tbody></table></div></section>')

    # 各上線模組區塊
    def sec(key, label, desc, body):
        return (f'<section><h3>{label}</h3>'
                f'<p class="small">{desc}</p>{body}</section>')

    blocks = []
    for key, label, st, desc in MODULES:
        if st != "live":
            continue
        if key == "capital_ce":
            body = _capital_ce_rows(events, name)
        elif key == "insider_pledge":
            body = _insider_rows(name, fut_set)
        else:
            body = _event_rows(events, key, name)
        blocks.append(sec(key, label, desc, body))
    # 旗艦開發中佔位
    dev = [m for m in MODULES if m[2] == "dev"]
    for key, label, st, desc in dev:
        blocks.append(f'<section style="opacity:.75"><h3>{label}</h3>'
                      f'<p class="small">{desc}</p>'
                      f'<p class="note" style="background:#2b230c;border:1px solid #5c4c1d;'
                      f'color:#e6c56a;padding:8px 12px;border-radius:4px">'
                      f'🏗 開發中 —— 這是唯一能跑在公告<b>前</b>的模組,'
                      f'需結合分點 BSR 吸貨偵測 + 集保大戶跳增 + 回測驗證,分批完成。</p></section>')

    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1100px;margin:1em auto;padding:0 1em;}
  h1{font-size:1.4em;margin:.4em 0}
  section{padding:12px 16px;margin-bottom:14px;border-radius:8px}
  h3{margin:.2em 0 .5em}
  table.report-table{width:100%;border-collapse:collapse;font-size:.9em}
  table.report-table th,table.report-table td{padding:6px 9px;text-align:right}
  table.report-table td:first-child,table.report-table th:first-child{text-align:left}
  .small{font-size:.84em;color:#8b98a9}
  .u-hot td{color:#ff6b6b;font-weight:600}
</style>"""
    return f"""<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎯 事件交易</title>{css}</head><body>{nav}
<h1>🎯 事件交易(Event-Driven)</h1>
<p class="small">資料日 {_fmt_d(asof)} · 資料源:TWSE/TPEx 官方重大訊息 OpenAPI + 內部人持股。
<b>核心理念:MOPS 是「法定確認」不是「最早」</b> —— 純等公告多半無超額報酬,
真 edge 在公告前的分點/集保籌碼痕跡(見旗艦模組)。完整研究見
<a href="https://github.com/tony21177/tw-stock-tools/blob/main/docs/strategies/event-driven.md">docs</a>。
點代號看 K 線。</p>
{roadmap}
{''.join(blocks)}
<p class="small">⚠ 本頁為事件彙整與研究工具,非買賣訊號;各事件的超額報酬多數未經回測,
逐批補上回測後才會標「已驗證」。事件以交易所公告為準。</p>
</body></html>"""
