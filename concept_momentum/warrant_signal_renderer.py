#!/usr/bin/env python3
"""權證量能觀察頁渲染 — /warrant-signal.

⚠ 重要：2026-07-21 回測（63 交易日）顯示此訊號**無預測 edge**（空方從未觸發、
多方無顯著正報酬、爆量端甚至反向）。本頁為**觀察工具、非買賣訊號**，用途是看
「哪些現股今天權證爆量、認購/認售偏向、哪家券商在發」，不代表會漲跌。
"""
import html as _html

YI = 1e8
_DIR_LABEL = {
    "bull": ("🔥 偏多", "資金偏押認購（爆量且認購佔比升）— 注意：回測無此方向 edge"),
    "bear": ("❄ 偏空", "資金偏押認售（爆量且認購佔比降）— 回測此方向從未觸發（認售太稀）"),
    "neutral": ("⚡ 中性", "爆量但認購/認售未明顯失衡（多為只有認購在交易）"),
}


def _esc(s) -> str:
    return _html.escape(str(s))


def _fut_star(code):
    """有個股期 → ★(全站標準)"""
    try:
        import tw_stock_futures as _sf
        return " ★" if code in _sf.fut_stock_set() else ""
    except Exception:
        return ""


def _stock_name(code: str) -> str:
    try:
        from stock_names import get_name
        return get_name(code, "")
    except Exception:
        return ""


def _fmt_yi(v: float) -> str:
    return f"{v / YI:.2f}"


def _warrant_glossary() -> str:
    """每欄意義 + 資料源 + 算法(可收合)。"""
    return """
<details class="wg"><summary>📖 欄位完整說明(意義・資料來源・如何計算)</summary>
<div style="font-size:.9em;line-height:1.7">

<p><b>資料源</b>:TWSE(證交所)每日<b>六類權證成交彙總</b> —
認購 0999、牛證 0999C、可展延牛證 0999X(以上歸<b>偏多 bull</b>);
認售 0999P、熊證 0999B、可展延熊證 0999Y(以上歸<b>偏空 bear</b>)。
把每檔權證的成交金額<b>按其標的現股彙總</b>,寫成每日檔。約盤後傍晚更新。
⚠ 這是<b>觀察工具、非買賣訊號</b> —— 回測顯示方向標記無預測 edge(見頁首紅字盒)。</p>

<h4>這頁在做什麼</h4>
<p>找出「當日<b>權證</b>總成交金額爆量」的<b>現股</b> —— 有人透過權證(槓桿工具)
大量押注某檔股票的方向。爆量 + 認購/認售偏向,反映權證交易者當天的多空傾向。</p>

<h4>各欄位</h4>
<ul>
<li><b>代號 / 名稱</b>:被押注的<b>現股</b>(不是權證本身)。★=有個股期貨;點代號看 K 線。</li>
<li><b>方向</b>:🔥偏多(認購佔比明顯升)／❄偏空(認售升)／⚡中性(無明顯偏向)。
判定看下面「Δ占比」的正負與大小。<b>無驗證過的預測力,僅描述當日偏向。</b></li>
<li><b>爆量倍數</b>:今日該股所有權證總成交金額 ÷ <b>近 20 交易日均</b>。
2.0x = 今天權證量是平常的兩倍。<b>入榜門檻 ≥ 2 倍</b>。</li>
<li><b>權證總額(億)</b>:今日該股全部權證(認購+認售)成交金額合計。
<b>另有 1,000 萬底檻</b> —— 總額不足 1,000 萬不出榜(濾小額雜訊)。</li>
<li><b>認購佔比</b>:認購(含牛證)成交金額 ÷ 全部權證成交金額。
1.00 = 當天該股權證全是看漲方向、無人買認售。</li>
<li><b>Δ占比</b>:今日認購佔比 − 近 20 日均認購佔比。<b>正(紅)</b>=偏多情緒比平常濃、
<b>負(綠)</b>=偏空升溫。這是判方向的關鍵欄(絕對佔比高但天天如此=沒新意)。</li>
<li><b>權證檔數</b>:該股當天有成交的權證檔數。</li>
<li><b>主要發行券商</b>:成交額最大的發行商(從權證名稱擷取,如「台積電元大…」→元大)。
點開可展開<b>該股前 5 大權證明細</b>。</li>
</ul>

<h4>展開明細每檔權證的欄位</h4>
<ul>
<li><b>權證名(券商/認購或認售) X.XX億</b>:該權證成交金額。</li>
<li><b>權證價 $</b>:權證自身收盤價(通常幾角~幾元,槓桿商品)。</li>
<li><b>履約 $</b>:履約價(strike)—— 認購是「有權用這價買現股」的價位。</li>
<li><b>距到期 N 天</b>:離到期日剩幾個日曆天。越短時間價值流失越快。</li>
<li><b>價內 X% / 價外 X%</b>:現股現價相對履約價的位置。認購「價內」=現價已高於履約
(已有內含價值)、「價外」=現價還低於履約(純賭方向)。權證量能常集中在價外(便宜、槓桿高)。</li>
<li><b>行使 X</b>:行使比例(conversion ratio)—— 1 張權證可換多少股現股。
如 0.007 表示 143 張權證才對應 1 張現股。</li>
</ul>

<p style="color:#666;margin-top:8px">FinMind 無權證資料,故此頁走 TWSE 官方彙總。
判讀提醒:權證爆量只說明「有人用槓桿押方向」,是不是聰明錢無法從此頁得知 ——
回測已證實方向標記無預測力,請當市場情緒觀察、勿當進場訊號。</p>
</div></details>"""


def render_backtest_caveat(bt: dict | None) -> str:
    """紅字揭露盒：回測無 edge。bt = warrant_backtest.json 內容或 None。"""
    period = ""
    if bt and bt.get("start"):
        period = (f"（回測 {bt['start'][4:6]}/{bt['start'][6:]}"
                  f"~{bt['end'][4:6]}/{bt['end'][6:]}，63 交易日）")
    return (
        '<section style="background:#fdecea;border:1px solid #f5b7b1;'
        'border-radius:6px;padding:12px 16px;margin-bottom:12px;">'
        '<b style="color:#c0392b;">⚠ 回測結論：此訊號無預測 edge — 本頁僅為觀察工具，'
        '非買賣訊號</b>'
        f'<p class="small" style="margin:6px 0 0;color:#7b241c;">{period}'
        '<b>空方（大跌）</b>：認售權證量僅認購 ~8%，訊號從未觸發、不可用。'
        '<b>多方（大漲）</b>：無統計顯著正報酬（t≈0、95% CI 全跨 0）；'
        '收緊爆量門檻反而<b>顯著為負</b>（權證大爆量常是券商分銷／散戶追高，'
        '非聰明錢）。<b>請勿當作進場訊號</b>，僅用於觀察權證資金聚集在哪些現股。</p>'
        '</section>')


def _days_to_expiry(expiry: str, asof: str) -> int | None:
    from datetime import datetime
    try:
        e = datetime.strptime(expiry, "%Y%m%d")
        a = datetime.strptime(asof, "%Y%m%d")
        return (e - a).days
    except (ValueError, TypeError):
        return None


def _in_out(strike: float | None, close: float | None, is_call: bool) -> str:
    """價內外標示。close/strike 缺則 —。"""
    if not strike or not close:
        return ""
    diff = (close - strike) / strike * 100
    if not is_call:
        diff = -diff
    if diff >= 0:
        return f"價內{diff:.0f}%"
    return f"價外{-diff:.0f}%"


def render_page(signal_rows: list[dict], day: dict, asof: str,
                backtest: dict | None = None, terms: dict | None = None) -> str:
    """完整 HTML：nav + 無 edge 揭露 + 當日權證爆量現股表。"""
    nav = __import__("site_nav").nav_html("/warrant-signal")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:6px 9px;border-bottom:1px solid #eee;text-align:right;}
  th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left;}
  th{background:#fafafa;color:#555;}
  .pos{color:#c0392b;} .neg{color:#186a3b;}
  .small,small{font-size:.85em;color:#666;}
  details{margin:2px 0;} summary{cursor:pointer;color:#0066cc;}
  .meta{color:#666;font-size:.85em;}
  details.wg{background:#fff;border:1px solid #e5e5ea;border-radius:6px;
    margin:0 0 12px;padding:8px 14px;}
  details.wg>summary{font-weight:600;}
  details.wg h4{margin:12px 0 3px;font-size:1em;color:#111;}
  details.wg ul{margin:2px 0 6px;padding-left:20px;}
</style>"""
    fmt_date = f"{asof[:4]}/{asof[4:6]}/{asof[6:]}" if len(asof) == 8 else asof
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>權證量能觀察</title>{css}</head><body>{nav}'
            f'<h1>🎰 權證量能觀察 — {fmt_date}</h1>')
    parts = [head, render_backtest_caveat(backtest)]

    if not signal_rows:
        parts.append('<section><p class="small">今日無權證爆量現股'
                     '（或尚無當日資料）。</p></section>')
        parts.append('</body></html>')
        return "\n".join(parts)

    unders = day.get("underlyings", {})
    parts.append(_warrant_glossary())
    parts.append(
        '<section><p class="meta">當日權證總成交金額 ≥ 近20日均 2 倍的現股。'
        '「認購佔比」= 認購(含牛證)成交金額 ÷ 全部權證；Δ = 今日 − 近20日均。'
        '金額單位億元、近似。訊號門檻:權證總成交金額(量×價)≥1,000 萬(濾小額雜訊)。</p>'
        '<table><thead><tr>'
        '<th>代號</th><th>名稱</th><th>方向</th><th>爆量倍數</th>'
        '<th>權證總額(億)</th><th>認購佔比</th><th>Δ占比</th>'
        '<th>權證檔數</th><th>主要發行券商</th>'
        '</tr></thead><tbody>')
    for r in signal_rows:
        u = unders.get(r["code"], {})
        d_label, d_tip = _DIR_LABEL.get(r["direction"], ("—", ""))
        issuers = u.get("issuers", {})
        top_iss = sorted(issuers.items(), key=lambda x: -x[1])[:3]
        iss_txt = "、".join(f"{_esc(n)}" for n, _ in top_iss) or "—"
        tops = u.get("top_warrants", [])
        close = u.get("close")
        terms = terms or {}
        detail_parts = []
        for w in tops[:5]:
            t = terms.get(w["code"], {})
            extra = ""
            bits = []
            if w.get("close") is not None:
                bits.append(f"權證價${w['close']:g}")
            if t:
                dte = _days_to_expiry(t.get("expiry", ""), asof)
                io = _in_out(t.get("strike"), close, w["side"] == "bull")
                if t.get("strike"):
                    bits.append(f"履約${t['strike']:g}")
                if dte is not None:
                    bits.append(f"距到期{dte}天")
                if io:
                    bits.append(io)
                if t.get("conver"):
                    bits.append(f"行使{t['conver']:g}")
            if bits:
                extra = " ｜ " + " ".join(bits)
            detail_parts.append(
                f"<div class='small'>{_esc(w['name'])} "
                f"({_esc(w['issuer'] or '?')}/"
                f"{'認購' if w['side']=='bull' else '認售'}) "
                f"{_fmt_yi(w['turnover'])}億{extra}</div>")
        detail = "".join(detail_parts)
        share_cls = "pos" if (r["bull_share_delta"] or 0) > 0 else (
            "neg" if (r["bull_share_delta"] or 0) < 0 else "")
        name = (u.get("name") or _stock_name(r["code"])) + _fut_star(r["code"])
        parts.append(
            f'<tr><td data-kx="{_esc(r["code"])}" style="cursor:pointer">{_esc(r["code"])}</td>'
            f'<td style="text-align:left">{_esc(name)}</td>'
            f'<td title="{_esc(d_tip)}">{d_label}</td>'
            f'<td>{r["surge_ratio"]:.1f}x</td>'
            f'<td>{_fmt_yi(r["warrant_turnover"])}</td>'
            f'<td>{r["bull_share"]:.2f}</td>'
            f'<td class="{share_cls}">{r["bull_share_delta"]:+.2f}</td>'
            f'<td>{u.get("n_warrants", "—")}</td>'
            f'<td style="text-align:left"><details><summary>{iss_txt}</summary>'
            f'{detail}</details></td></tr>')
    parts.append('</tbody></table>'
                 '<p class="small">🔥偏多／❄偏空／⚡中性 — 見上方回測揭露，'
                 '方向標記無驗證過的預測力，僅描述當日認購/認售偏向。</p></section>')
    parts.append('</body></html>')
    return "\n".join(parts)
