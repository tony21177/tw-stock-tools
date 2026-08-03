"""族群資金流 renderer — 排行表 + sparkline + 動能表欄位 + TG 摘要（純渲染）。"""

from concept_money_flow import FLOW_SHARE_PP, FLOW_INST_NTD, FLOW_NET_GROSS_RATIO

_TAG_DESC = {
    "🔥": "真流入：成交額占比升 + 法人買（熱度與真金同向）。"
          "注意：大跌爆量日也可能出現（散戶恐慌賣、外資接刀/回補空單），"
          "≠ 看多訊號，需搭配價格判讀",
    "⚠": "出貨疑慮：成交額占比升 + 法人賣（散戶接刀風險）",
    "🧲": "低調吸收：成交額占比降 + 法人買（沒人注意但法人默默買）",
    "❄": "退潮：成交額占比降 + 法人賣（熱度與資金雙離開）",
    "—": "未達門檻或外資投信對沖（淨流是雜訊殘差），不強行分類",
}

_THRESHOLD_NOTE = (f"門檻：占比變化 ±{FLOW_SHARE_PP}pp 且 法人淨流 ±{FLOW_INST_NTD}億、"
                   f"且淨流須 ≥ 總流量(|外|+|投|+|自營|)的 {FLOW_NET_GROSS_RATIO:.0%}"
                   "（外資買 66 億、投信賣 66 億剩 +2.77 億這種對沖殘差不算方向訊號），"
                   "未達則標 —。門檻為先驗設定、未經回測驗證。")


def _sparkline_svg(values: list[float], width: int = 120, height: int = 28) -> str:
    """inline SVG 折線（法人淨流 5 日滾動累計）；跨 0 畫灰色零線。<2 點回 '—'。"""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return "—"
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        vmax = vmin + 1.0
    n = len(vals)

    def x(i):
        return round(i * (width - 2) / (n - 1) + 1, 1)

    def y(v):
        return round(height - 2 - (v - vmin) * (height - 4) / (vmax - vmin), 1)

    pts = " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(vals))
    zero = ""
    if vmin < 0 < vmax:
        zy = y(0)
        zero = (f'<line x1="1" y1="{zy}" x2="{width - 1}" y2="{zy}" '
                f'stroke="#ccc" stroke-width="1"/>')
    return (f'<svg width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" style="vertical-align:middle;">'
            f'{zero}<polyline points="{pts}" fill="none" '
            f'stroke="#1f77b4" stroke-width="1.5"/></svg>')


def _fmt_streak(streak: int) -> str:
    if streak > 0:
        return f"買{streak}日"
    if streak < 0:
        return f"賣{-streak}日"
    return "—"


def _fmt_yi(v: float | None) -> str:
    """億元格式化；None（舊日檔無此欄）→ —。"""
    return f"{v:+.1f}" if v is not None else "—"


def _cls_yi(v: float | None) -> str:
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def render_foreign_section(fv: dict | None) -> str:
    """🌏 外資買賣超（上市/上櫃 近10日 + 當日買賣超 Top15 個股）。fv=None → 空字串。"""
    if not fv:
        return ""
    parts = ['<h3 style="margin-top:24px;">🌏 外資買賣超（上市/上櫃）</h3>',
             '<p class="meta">官方公布值（TWSE / 櫃買中心，實際成交金額口徑，與新聞數字一致）；'
             '缺官方資料的日子以近似值回填並加 ~ 標示 | 近 10 個交易日</p>',
             '<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr>'
             '<th title="交易日">日期</th>'
             '<th title="上市（TWSE）外資及陸資買賣超金額（億）— 官方公布值；'
             '~ 開頭 = 該日缺官方資料，以淨股數×收盤價近似回填">上市外資(億)</th>'
             '<th title="上櫃（TPEx）外資及陸資買賣超金額（億）— 櫃買中心官方公布值；'
             '~ 開頭 = 近似回填">上櫃外資(億)</th>'
             '<th title="上市 + 上櫃 合計（億）">合計(億)</th>'
             '</tr></thead><tbody>']
    for r in fv.get("recent", []):
        d = r.get("date", "")
        d_txt = f"{d[:4]}/{d[4:6]}/{d[6:8]}" if len(d) == 8 else d
        approx = "" if r.get("official") else "~"

        def _v(key, _r=r, _a=approx):
            v = _r.get(key)
            return f"{_a}{v:+.2f}" if v is not None else "—"

        parts.append(
            '<tr>'
            f'<td>{d_txt}</td>'
            f'<td class="{_cls_yi(r.get("twse"))}">{_v("twse")}</td>'
            f'<td class="{_cls_yi(r.get("tpex"))}">{_v("tpex")}</td>'
            f'<td class="{_cls_yi(r.get("total"))}">{_v("total")}</td>'
            '</tr>')
    parts.append('</tbody></table></div>')

    def _top_table(title: str, rows: list[dict]) -> str:
        if not rows:
            return (f'<h3 style="margin-top:16px;">{title}</h3>'
                    '<p class="meta">（無）</p>')
        body = [f'<h3 style="margin-top:16px;">{title}</h3>',
                '<div class="table-scroll" style="overflow-x:auto;">',
                '<table class="market-breadth">',
                '<thead><tr>'
                '<th title="名次（依外資淨買賣金額排序）">#</th>'
                '<th title="股票代號">代號</th>'
                '<th title="股票中文名稱">名稱</th>'
                '<th title="上市 / 上櫃（? = 分類快取缺此檔）">市場</th>'
                '<th title="外資淨買賣金額（億，淨股數×收盤價近似）">外資(億)</th>'
                '</tr></thead><tbody>']
        for i, s in enumerate(rows, 1):
            ntd = s.get("ntd")
            body.append(
                '<tr>'
                f'<td>{i}</td>'
                f'<td>{s.get("code", "")}</td>'
                f'<td>{s.get("name", s.get("code", ""))}</td>'
                f'<td>{s.get("mkt", "?")}</td>'
                f'<td class="{_cls_yi(ntd)}">{_fmt_yi(ntd)}</td>'
                '</tr>')
        body.append('</tbody></table></div>')
        return "\n".join(body)

    asof = fv.get("asof", "")
    asof_txt = f"{asof[:4]}/{asof[4:6]}/{asof[6:8]}" if len(asof) == 8 else asof
    parts.append(_top_table(f'📈 外資買超 Top15 個股（{asof_txt}）', fv.get("top_buy", [])))
    parts.append(_top_table(f'📉 外資賣超 Top15 個股（{asof_txt}）', fv.get("top_sell", [])))
    return "\n".join(parts)


def render_tab(view_rows: list[dict], asof: str,
               foreign_view: dict | None = None) -> str:
    """排行表（34 主題全列，依成交值占比 vs 20日均降冪）+ 外資買賣超區
    + 圖例 + 使用時機盒。"""
    if not view_rows:
        return ('<p class="empty-state" style="text-align:center;padding:20px;color:#888;">'
                '尚無資金流資料 — 請先執行 '
                '<code>python3 concept_money_flow.py --backfill 60</code></p>')
    parts = [
        f'<p class="meta">資料至 {asof}｜<b>排序＝成交值占比 vs 20日均（pp，'
        f'業界類股資金流口徑、來自真實成交金額、精確）</b>；'
        f'法人淨流(億)＝淨股數×收盤價（近似輔助）</p>',
        '<div class="table-scroll" style="overflow-x:auto;">',
        '<table class="market-breadth">',
        '<thead><tr>'
        '<th title="主題板塊（concepts.json，一檔可屬多主題）">族群</th>'
        '<th title="占比變化 × 法人淨流 交叉判讀：'
        '&#10;🔥 真流入（占比升+法人買）&#10;⚠ 出貨疑慮（占比升+法人賣，散戶接刀）'
        '&#10;🧲 低調吸收（占比降+法人買）&#10;❄ 退潮（占比降+法人賣）'
        f'&#10;&#10;{_THRESHOLD_NOTE}">標記</th>'
        '<th title="族群內每檔（外資+投信+自營）淨買賣股數 × 當日收盤價 加總，單位億元。'
        '正=淨買（流入）。注意是近似值：法人實際成交價分布在盤中">今日法人淨流(億)</th>'
        '<th title="外資（含外資自營）單獨的淨流金額（億）">外資(億)</th>'
        '<th title="投信單獨的淨流金額（億）。自營商計入總計但不單獨列（多為避險單、雜訊高）">投信(億)</th>'
        '<th title="最近 5 個交易日法人淨流合計（億）">5日累計(億)</th>'
        '<th title="法人連續淨買/淨賣天數（尾端起算，0 中斷）">連續</th>'
        '<th title="族群成交金額 ÷ 全市場（上市櫃 4 位數普通股）成交金額。'
        '一檔可屬多主題 → 各族群占比加總會超過 100%">今日占比%</th>'
        '<th title="今日占比 − 過去 20 個交易日平均占比（百分點 pp）。正=熱度升。'
        '歷史不足 20 日時用現有天數平均並標 *">占比vs20日均(pp)</th>'
        '<th title="法人淨流 5 日滾動累計的 60 日走勢（灰線=0）">60日趨勢</th>'
        '</tr></thead><tbody>']
    for r in view_rows:
        net = r.get("inst_net_ntd") or 0.0
        cls = "pos" if net > 0 else ("neg" if net < 0 else "")
        sv = r.get("share_vs_20d")
        star = "*" if r.get("share_samples", 0) < 20 else ""
        sv_txt = f"{sv:+.2f}{star}" if sv is not None else "—"
        sv_cls = "pos" if (sv or 0) > 0 else ("neg" if (sv or 0) < 0 else "")
        share = r.get("mkt_share_pct")
        share_txt = f"{share:.2f}" if share is not None else "—"
        parts.append(
            '<tr>'
            f'<td>{r["name_zh"]}{_drivers_html(r)}</td>'
            f'<td title="{_TAG_DESC.get(r.get("tag", "—"), "")}">{r.get("tag", "—")}</td>'
            f'<td class="{cls}">{net:+.1f}</td>'
            f'<td>{r.get("foreign_net_ntd", 0) or 0:+.1f}</td>'
            f'<td>{r.get("trust_net_ntd", 0) or 0:+.1f}</td>'
            f'<td>{r.get("net_5d", 0) or 0:+.1f}</td>'
            f'<td>{_fmt_streak(r.get("streak", 0))}</td>'
            f'<td>{share_txt}</td>'
            f'<td class="{sv_cls}">{sv_txt}</td>'
            f'<td>{_sparkline_svg(r.get("spark", []))}</td>'
            '</tr>')
    parts.append('</tbody></table></div>')
    foreign_html = render_foreign_section(foreign_view)
    if foreign_html:
        parts.append(foreign_html)
    parts.append(
        '<p style="font-size:0.8em; color:#888; margin:4px 0 0;">'
        '🔥 真流入（占比升+法人買）　⚠ 出貨疑慮（占比升+法人賣）　'
        '🧲 低調吸收（占比降+法人買）　❄ 退潮（占比降+法人賣）　— 未達門檻<br>'
        f'{_THRESHOLD_NOTE}　占比欄標 * = 歷史樣本不足 20 日'
        '</p>')
    parts.append(
        '<p style="font-size:0.8em; color:#a06000; background:#fdf6e8; '
        'padding:6px 10px; border-radius:4px; margin:6px 0 0;">'
        '📌 <b>使用時機與限制</b>：本頁是<b>輪動觀察工具、非買賣訊號</b>——法人買不代表會漲。'
        '法人金額 = 淨股數 × 收盤價，是<b>近似</b>值；'
        '占比會因單一權值股爆量而失真（例：台積電同時屬多個主題）；'
        '一檔可屬多主題 → 占比加總 &gt;100%、族群間金額會重複計算；'
        '四象限門檻未經回測驗證，累積數據後才能校準。</p>')
    return "\n".join(parts)


def render_flow_cells(theme_key: str, flow_map: dict | None) -> str:
    """動能排行表用的兩個 <td>：法人淨流(億) + 標記。無資料回 — 。"""
    r = (flow_map or {}).get(theme_key)
    if not r:
        return "<td>—</td><td>—</td>"
    net = r.get("inst_net_ntd") or 0.0
    cls = "pos" if net > 0 else ("neg" if net < 0 else "")
    tag = r.get("tag", "—")
    return (f'<td class="{cls}">{net:+.1f}</td>'
            f'<td title="{_TAG_DESC.get(tag, "")}">{tag}</td>')


def _tg_row(r: dict) -> str:
    # 主數字 = 占比 vs 20日均（精確）；法人淨流(近似)括號輔助
    streak = r.get("streak", 0)
    s = f" 連{abs(streak)}日" if abs(streak) >= 2 else ""
    sv = r.get("share_vs_20d")
    star = "*" if r.get("share_samples", 0) < 20 else ""
    sv_txt = f"占比{sv:+.2f}pp{star}" if sv is not None else "占比—"
    return (f"{r.get('tag', '—')} {r['name_zh']} {sv_txt} "
            f"(法人{(r.get('inst_net_ntd') or 0):+.1f}億"
            f"／外{(r.get('foreign_net_ntd') or 0):+.1f} "
            f"投{(r.get('trust_net_ntd') or 0):+.1f}){s}")


def _drivers_html(r) -> str:
    """族群名下方小字行:各主力個股 span(data-kx 可點開 K 線彈窗)。無資料回空字串。"""
    ds = r.get("drivers") or []
    if not ds:
        return ""
    spans = []
    for d in ds[:4]:
        cls = "pos" if d["i"] > 0 else "neg"
        spans.append(
            f'<span data-kx="{d["c"]}" class="{cls}" style="cursor:pointer;">'
            f'{d["c"]}{d["n"]}{d["i"]:+g}</span>')
    return ('<div style="font-size:0.72em; opacity:0.85; margin-top:2px; '
            'white-space:nowrap;" title="法人淨買賣金額(億),點代號看 K 線">'
            + " ".join(spans) + "</div>")


def _tg_drivers(r) -> str | None:
    """族群主力個股一行:↳ 2330台積電-180 2317鴻海+25(億)。無資料回 None。"""
    ds = r.get("drivers") or []
    if not ds:
        return None
    parts = [f"{d['c']}{d['n']}{d['i']:+g}" for d in ds[:4]]
    return "    ↳ " + " ".join(parts) + "(億)"


def build_tg_summary(view_rows: list[dict], date_str: str) -> str:
    """Telegram 文字摘要：資金匯入/流出 Top5（依成交值占比 vs 20日均，
    業界類股資金流口徑、精確）+ ⚠ 出貨疑慮 + 連續 ≥5 日異常。"""
    lines = [f"💰 族群資金流 {date_str}",
             "排序=成交值占比vs20日均(精確,業界口徑) | 法人淨流=淨股數×收盤價(近似輔助) | 標記門檻未回測",
             "━━━━━━━━━━━━"]
    # 主指標：占比 vs 20日均（精確）。None 者不進榜（無足夠樣本）。
    rated = [r for r in view_rows if r.get("share_vs_20d") is not None]
    pos = sorted([r for r in rated if r["share_vs_20d"] > 0],
                 key=lambda r: -r["share_vs_20d"])[:5]
    neg = sorted([r for r in rated if r["share_vs_20d"] < 0],
                 key=lambda r: r["share_vs_20d"])[:5]
    lines.append("資金匯入 Top5（占比升）:")
    if pos:
        for r in pos:
            lines.append(f"  {_tg_row(r)}")
            d = _tg_drivers(r)
            if d:
                lines.append(d)
    else:
        lines.append("  （無）")
    lines.append("\n資金流出 Top5（占比降）:")
    if neg:
        for r in neg:
            lines.append(f"  {_tg_row(r)}")
            d = _tg_drivers(r)
            if d:
                lines.append(d)
    else:
        lines.append("  （無）")
    warns = [r for r in view_rows if r.get("tag") == "⚠"]
    if warns:
        lines.append("\n⚠ 出貨疑慮（熱度升但法人賣）:")
        for r in warns:
            sv = r.get("share_vs_20d")
            sv_txt = f"占比{sv:+.2f}pp " if sv is not None else ""
            lines.append(f"  {r['name_zh']} {sv_txt}法人{(r.get('inst_net_ntd') or 0):+.1f}億")
            sellers = [d for d in (r.get("drivers") or []) if d["i"] < 0][:3]
            if sellers:
                lines.append("    ↳ 賣壓:" + " ".join(
                    f"{d['c']}{d['n']}{d['i']:+g}" for d in sellers) + "(億)")
    streaky = [r for r in view_rows if abs(r.get("streak", 0)) >= 5]
    if streaky:
        lines.append("\n📌 連續 ≥5 日:")
        for r in streaky:
            side = "買超" if r["streak"] > 0 else "賣超"
            lines.append(f"  {r['name_zh']} 連{abs(r['streak'])}日{side}")
    return "\n".join(lines)
