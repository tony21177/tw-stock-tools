"""族群資金流 renderer — 排行表 + sparkline + 動能表欄位 + TG 摘要（純渲染）。"""

from concept_money_flow import FLOW_SHARE_PP, FLOW_INST_NTD

_TAG_DESC = {
    "🔥": "真流入：成交額占比升 + 法人買（熱度與真金同向）",
    "⚠": "出貨疑慮：成交額占比升 + 法人賣（散戶接刀風險）",
    "🧲": "低調吸收：成交額占比降 + 法人買（沒人注意但法人默默買）",
    "❄": "退潮：成交額占比降 + 法人賣（熱度與資金雙離開）",
    "—": "未達門檻，不強行分類",
}

_THRESHOLD_NOTE = (f"門檻：占比變化 ±{FLOW_SHARE_PP}pp 且 法人淨流 ±{FLOW_INST_NTD}億，"
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


def render_tab(view_rows: list[dict], asof: str) -> str:
    """排行表（34 主題全列，依法人淨流降冪）+ 圖例 + 使用時機盒。"""
    if not view_rows:
        return ('<p class="empty-state" style="text-align:center;padding:20px;color:#888;">'
                '尚無資金流資料 — 請先執行 '
                '<code>python3 concept_money_flow.py --backfill 60</code></p>')
    parts = [
        f'<p class="meta">資料至 {asof} | 法人淨流 = 淨股數 × 收盤價（近似值）</p>',
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
            f'<td>{r["name_zh"]}</td>'
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
    streak = r.get("streak", 0)
    s = f" 連{abs(streak)}日" if abs(streak) >= 2 else ""
    sv = r.get("share_vs_20d")
    sv_txt = f" 占比{sv:+.2f}pp" if sv is not None else ""
    return (f"{r.get('tag', '—')} {r['name_zh']} {r['inst_net_ntd']:+.1f}億"
            f"(外{r['foreign_net_ntd']:+.1f} 投{r['trust_net_ntd']:+.1f}){s}{sv_txt}")


def build_tg_summary(view_rows: list[dict], date_str: str) -> str:
    """Telegram 文字摘要：流入/流出 Top5 + ⚠ 出貨疑慮 + 連續 ≥5 日異常。"""
    lines = [f"💰 族群資金流 {date_str}",
             "法人淨流=淨股數×收盤價(近似) | 標記門檻未經回測",
             "━━━━━━━━━━━━"]
    pos = [r for r in view_rows if (r.get("inst_net_ntd") or 0) > 0][:5]
    neg = sorted([r for r in view_rows if (r.get("inst_net_ntd") or 0) < 0],
                 key=lambda r: r["inst_net_ntd"])[:5]
    lines.append("流入 Top5:")
    if pos:
        for r in pos:
            lines.append(f"  {_tg_row(r)}")
    else:
        lines.append("  （無）")
    lines.append("\n流出 Top5:")
    if neg:
        for r in neg:
            lines.append(f"  {_tg_row(r)}")
    else:
        lines.append("  （無）")
    warns = [r for r in view_rows if r.get("tag") == "⚠"]
    if warns:
        lines.append("\n⚠ 出貨疑慮（熱度升但法人賣）:")
        for r in warns:
            sv = r.get("share_vs_20d")
            sv_txt = f"占比{sv:+.2f}pp " if sv is not None else ""
            lines.append(f"  {r['name_zh']} {sv_txt}法人{r['inst_net_ntd']:+.1f}億")
    streaky = [r for r in view_rows if abs(r.get("streak", 0)) >= 5]
    if streaky:
        lines.append("\n📌 連續 ≥5 日:")
        for r in streaky:
            side = "買超" if r["streak"] > 0 else "賣超"
            lines.append(f"  {r['name_zh']} 連{abs(r['streak'])}日{side}")
    return "\n".join(lines)
