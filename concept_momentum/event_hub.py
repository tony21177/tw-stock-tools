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


def _fmt_t(t):
    """發言時間 '92514' → '09:25'。"""
    t = "".join(c for c in str(t) if c.isdigit())
    if len(t) < 4:
        return "—"
    t = t.zfill(6)
    return f"{t[:2]}:{t[2:4]}"


def _mops(code, market="sii", kind="material"):
    """MOPS 深連結。kind: material=個股重大訊息 / insider=董監持股."""
    typek = "otc" if market == "otc" else "sii"
    if kind == "insider":
        # 董監持股轉讓/設質彙總
        return (f'https://mopsov.twse.com.tw/mops/web/t56sb21q1'
                f'?step=1&co_id={code}&TYPEK={typek}')
    return (f'https://mopsov.twse.com.tw/mops/web/t146sb05'
            f'?step=1&co_id={code}&TYPEK={typek}')


def _src(code, market="sii", kind="material"):
    return (f'<td><a href="{_mops(code, market, kind)}" target="_blank" '
            f'rel="noopener" class="small">MOPS ↗</a></td>')


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
    ("insider", "👤 內部人動向(事前申報轉讓 + 高設質)", "live",
     "⭐ <b>事前申報轉讓</b>:董監大額轉讓前 3 日申報(Layer 0 提前信號);"
     "<b>高設質</b>:大股東質押比例高 = 槓桿+潛在斷頭賣壓(月頻)。"),
    ("chip_precursor", "🔍 分點吸貨前兆(旗艦)", "dev",
     "模組 #1:全市場掃「單一分點連續大額吸貨+成本集中+集保大戶跳增」,"
     "在取得股權公告<b>前</b>抓策略買家足跡。需回測+跨市場分點掃描,開發中。"),
]


import re

# 取得股權主旨抽標的:取得[子公司][地名]X[股份有限公司][普通股/股份/股權/有價證券]
_TARGET_RE = re.compile(
    r"取得(?:(?:子公司|孫公司|轉投資|泰國|大陸|中國|越南|印度|美國|日本)){0,3}"
    r"(.+?)(?:股份有限公司|公司)?(?:之|百分之百)?"
    r"(?:普通股|特別股|股份|股票|股權|有價證券)")


def _extract_target(subject: str, rev: dict):
    """從取得股權主旨抽標的公司名 + 反查代號。回傳 (顯示名, 代號 or '')。"""
    s = subject.replace(" ", "")
    m = _TARGET_RE.search(s)
    if not m:
        return "", ""
    tgt = m.group(1).strip("之的股權有價證券百分比0123456789")
    if len(tgt) < 2:
        return tgt, ""
    # 反查:先完全比對,再要求「標的名 ⊇ finmind 全名」且全名 ≥2 字(避免單字誤配)
    code = rev.get(tgt, "")
    if not code:
        best = ""
        for full, c in rev.items():
            if len(full) >= 2 and (full == tgt or full in tgt):
                if len(full) > len(best):     # 取最長匹配
                    best, code = full, c
    return tgt, code


def _event_rows(events, etype, name, rev, limit=25):
    """列出某類型近期事件。strategic_buy 抽標的並連結。"""
    rows = [e for e in events if e["type"] == etype][:limit]
    if not rows:
        return '<p class="small">近 3 個月無此類事件(或快取尚未累積)。</p>'
    is_buy = etype == "strategic_buy"
    trs = []
    for e in rows:
        subj = _esc(e["subject"])
        tgt_cell = ""
        if is_buy:
            tgt, tcode = _extract_target(e["subject"], rev)
            if tcode:
                tgt_cell = (f'<td data-kx="{_esc(tcode)}" style="cursor:pointer;'
                            f'text-align:left"><b>{_esc(tcode)} {_esc(tgt)}</b> ↗</td>')
            elif tgt:
                tgt_cell = f'<td style="text-align:left">{_esc(tgt)}</td>'
            else:
                tgt_cell = '<td>—</td>'
        trs.append(
            f'<tr><td>{_fmt_d(e["date"])}</td><td class="small">{_fmt_t(e["time"])}</td>'
            f'<td data-kx="{_esc(e["code"])}" style="cursor:pointer">'
            f'{_esc(e["code"])} {_esc(e["name"])}</td>'
            + (tgt_cell if is_buy else "")
            + f'<td style="text-align:left">{subj}</td>'
            f'<td class="small">{"上市" if e["market"]=="sii" else "上櫃"}</td>'
            + _src(e["code"], e["market"]) + '</tr>')
    tgt_th = "<th>買進標的</th>" if is_buy else ""
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            f'<th title="MOPS 發言日 = 法定最早公開時點">最早得知</th><th>時間</th>'
            f'<th>買方/公司</th>{tgt_th}<th>主旨</th><th>市場</th><th>來源</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>'
            + ('<p class="small">「買進標的」= 從主旨抽取被取得的公司,可反查代號者加'
               '<b>粗體+↗</b>並可點看 K 線。標的即上市櫃股票時,這就是潛在的連動選股。</p>'
               if is_buy else ""))


def _capital_ce_rows(events, name):
    """現增/減資合併一區;分本公司(影響大)vs 子公司(影響小)。"""
    rows = [e for e in events if e["type"] in ("capital_increase", "capital_reduction")][:35]
    if not rows:
        return '<p class="small">近 3 個月無增減資事件。</p>'
    trs = []
    for e in rows:
        s = e["subject"]
        is_sub = ("子公司" in s or "孫公司" in s
                  or re.search(r"[A-Za-z]{3,}", s.replace(e["name"], "")))
        scope = ('<span class="small">子公司</span>' if is_sub
                 else '<b style="color:#ff6b6b">本公司</b>')
        if e["type"] == "capital_reduction":
            kind = "✂ 減資"
        elif re.search(r"(私募|海外存託|存託憑證|GDR)", s):
            kind = "🌐 私募/GDR"
        elif re.search(r"可轉換|轉換公司債|附認股", s):
            kind = "🔄 可轉債"
        else:
            kind = "📈 現增"
        trs.append(
            f'<tr><td>{_fmt_d(e["date"])}</td><td class="small">{_fmt_t(e["time"])}</td>'
            f'<td data-kx="{_esc(e["code"])}" style="cursor:pointer">'
            f'{_esc(e["code"])} {_esc(e["name"])}</td><td>{kind}</td>'
            f'<td>{scope}</td>'
            f'<td style="text-align:left">{_esc(e["subject"])}</td>'
            + _src(e["code"], e["market"]) + '</tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th title="MOPS 發言日 = 法定最早公開時點">最早得知</th><th>時間</th>'
            '<th>公司</th><th>類型</th><th>對象</th><th>主旨</th><th>來源</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>'
            '<p class="small"><b>本公司</b>現增/私募/CB = 直接稀釋股本(如環球晶 GDR),'
            '影響大;<b>子公司</b>增資多為集團內部調度,對母股影響小。減資分彌補虧損(利空)'
            '與現金減資(中性偏多),看主旨。</p>')


def _xfer_rows():
    """內部人事前申報轉讓(法定提前 3 日)。"""
    ed = _ed()
    xf = ed.load_xfer(months=2) or ed.fetch_insider_transfer()
    xf = [x for x in xf if x["shares"] >= 50000][:25]   # ≥50 張才列
    if not xf:
        return ('<p class="small">近期無 ≥50 張的內部人事前申報轉讓'
                '(或快取尚未累積)。</p>')
    trs = []
    for x in xf:
        zhang = x["shares"] / 1000
        method = _esc(x["method"])
        recv = f" → {_esc(x['receiver'])}" if x.get("receiver") else ""
        trs.append(
            f'<tr><td>{_fmt_d(x["date"])}</td>'
            f'<td data-kx="{_esc(x["code"])}" style="cursor:pointer">'
            f'{_esc(x["code"])} {_esc(x["name"])}</td>'
            f'<td style="text-align:left">{_esc(x["who"])} {_esc(x["person"])}</td>'
            f'<td>{zhang:,.0f} 張</td>'
            f'<td style="text-align:left" class="small">{method}{recv}</td>'
            + _src(x["code"], x.get("market", "sii"), "insider") + '</tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>申報日</th><th>公司</th><th>申報人</th><th>預定轉讓</th>'
            '<th>方式/受讓人</th><th>來源</th></tr></thead><tbody>' + "".join(trs)
            + '</tbody></table></div>'
            '<p class="small">⭐ <b>事前申報轉讓</b> = 董監/大股東大額轉讓,法規要求'
            '<b>轉讓前 3 日申報</b> —— 這是少數「還沒賣就先知道」的 Layer 0 提前信號。'
            '「洽特定人/鉅額逐筆」多為協議轉讓(未必利空,可能是引進策略股東);'
            '「一般交易」= 盤中賣出(較偏賣壓)。≥50 張才列。</p>')


_HOLD_FLOOR = 3_000_000   # 只看持股 ≥3,000 張的大股東(小額全質押=雜訊)


def _insider_rows(name, fut_set=None):
    ed = _ed()
    ins = ed.load_insider() or ed.fetch_insider()
    # 每檔取「持股夠大且設質比例最高」的內部人;需 持股≥3000張 且 設質≥50%
    by_code = {}
    for i in ins:
        if i["hold"] >= _HOLD_FLOOR and i["pledge_ratio"] >= 50:
            cur = by_code.get(i["code"])
            # 排序鍵:設質張數(絕對賣壓量)大者優先
            if not cur or i["pledge"] > cur["pledge"]:
                by_code[i["code"]] = i
    rows = sorted(by_code.values(), key=lambda x: -x["pledge"])[:30]
    if not rows:
        return '<p class="small">無「大持股(≥3,000 張)+高設質(≥50%)」的內部人。</p>'
    trs = []
    for i in rows:
        cls = "u-hot" if i["pledge_ratio"] >= 90 else ""
        trs.append(
            f'<tr class="{cls}"><td data-kx="{_esc(i["code"])}" style="cursor:pointer">'
            f'{_esc(i["code"])} {_esc(i["name"])}</td>'
            f'<td>{_esc(i["title"])}</td>'
            f'<td>{i["hold"]/1000:,.0f} 張</td>'
            f'<td>{i["pledge"]/1000:,.0f} 張</td>'
            f'<td>{i["pledge_ratio"]:.0f}%</td>'
            f'<td class="small">{i["month"][:4]}/{i["month"][4:6]}</td>'
            + _src(i["code"], "sii", "insider") + '</tr>')
    return ('<div class="table-scroll"><table class="report-table"><thead><tr>'
            '<th>公司</th><th>職稱</th><th>持股</th><th>設質</th>'
            '<th>設質比例</th><th>資料月</th><th>來源</th>'
            '</tr></thead><tbody>' + "".join(trs) + '</tbody></table></div>'
            '<p class="small">只列<b>持股 ≥3,000 張</b>的大股東(小額全質押是雜訊、無賣壓意義)。'
            '設質比例 = 質押 ÷ 持股;≥90% 標紅。<b>大持股 + 高設質 = 大股東高槓桿,'
            '股價跌時有被質押券商斷頭的賣壓風險</b>。月頻資料。</p>')


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
        elif key == "insider":
            body = ('<h4 style="margin:.5em 0 .3em">⭐ 事前申報轉讓(法定提前 3 日)</h4>'
                    + _xfer_rows()
                    + '<h4 style="margin:1em 0 .3em">高設質內部人</h4>'
                    + _insider_rows(name, fut_set))
        else:
            body = _event_rows(events, key, name, rev)
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
真 edge 在公告前的分點/集保籌碼痕跡(見旗艦模組)。<b>「最早得知」欄</b> = MOPS 發言日(法定最早公開時點);公開收購(提前5日)、事前申報轉讓(提前3日)因法規要求申報,結構上領先實際動作。完整研究見
<a href="https://github.com/tony21177/tw-stock-tools/blob/main/docs/strategies/event-driven.md">docs</a>。
點代號看 K 線。</p>
{roadmap}
{''.join(blocks)}
<p class="small">⚠ 本頁為事件彙整與研究工具,非買賣訊號;各事件的超額報酬多數未經回測,
逐批補上回測後才會標「已驗證」。事件以交易所公告為準。</p>
</body></html>"""
