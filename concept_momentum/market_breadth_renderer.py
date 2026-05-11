"""HTML table renderer for the market breadth tab.

Pure function: takes list-of-dict rows, returns HTML string. No I/O.
"""

DASH = "—"  # em-dash for missing cells


def _fmt_int(v) -> str:
    if v is None:
        return DASH
    return f"{int(round(v)):,}"


def _fmt_pct(v, sign: bool = False) -> str:
    if v is None:
        return DASH
    if sign:
        return f"{v:+.2f}%"
    return f"{v:.1f}%"


def _fmt_yi(v, sign: bool = True) -> str:
    if v is None:
        return DASH
    if sign:
        return f"{v:+.2f}"
    return f"{v:,.0f}"


def _color_class(v) -> str:
    """Return 'pos' if v>0, 'neg' if v<0, '' otherwise."""
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def render_table(rows: list[dict]) -> str:
    """Render rows (any order) as descending-by-date HTML table.

    rows = [{date, twii_close, twii_change_pct, pct_above_20ma, ..., margin_delta_yi}]

    Per AC: empty list returns friendly message, no <table> element.
    """
    if not rows:
        return ('<p class="empty-state" style="text-align:center; padding: 40px; '
                'color: #888;">目前尚無數據，請稍後再試</p>')

    sorted_rows = sorted(rows, key=lambda r: r["date"], reverse=True)

    parts = ['<div class="table-scroll" style="overflow-x:auto;">']
    parts.append('<table class="market-breadth">')
    parts.append('<thead><tr>'
                 '<th title="交易日 (YYYY/MM/DD)">日期</th>'
                 '<th title="加權指數 (TAIEX) 當日收盤點位">加權指數</th>'
                 '<th title="大盤 vs 前一交易日的漲跌百分比">漲跌幅%</th>'
                 '<th title="收盤價站上 20 日均線 (月線) 的個股比例 (寬度池：上市+上櫃 4 位代號 ~2,300 檔)">&gt;20MA%</th>'
                 '<th title="收盤價站上 50 日均線 (季線) 的個股比例">&gt;50MA%</th>'
                 '<th title="收盤價站上 200 日均線 (年線) 的個股比例">&gt;200MA%</th>'
                 '<th title="當日創 200 日新高的個股數 (收盤價 > 過去 200 日 max)">200日新高</th>'
                 '<th title="外資+陸資 (含外資自營商) 當日淨買賣超金額 (億 NTD)">外資(億)</th>'
                 '<th title="投信 (投資信託) 當日淨買賣超金額 (億 NTD)">投信(億)</th>'
                 '<th title="自營商 (自行買賣+避險) 當日淨買賣超金額 (億 NTD)">自營(億)</th>'
                 '<th title="三大法人 (外資+投信+自營) 加總淨買賣超金額 (億 NTD)">法人合計(億)</th>'
                 '<th title="大盤每日融資使用金額 (上市+上櫃合計，億 NTD)">融資(億)</th>'
                 '<th title="融資餘額 vs 前一交易日的變化 (億 NTD; 正 = 散戶加碼，負 = 散戶退場)">融資增減(億)</th>'
                 '</tr></thead>')
    parts.append('<tbody>')

    for r in sorted_rows:
        chg_cls = _color_class(r["twii_change_pct"])
        f_cls = _color_class(r["foreign_yi"])
        t_cls = _color_class(r["trust_yi"])
        d_cls = _color_class(r["dealer_yi"])
        tot_cls = _color_class(r["total_yi"])
        md_cls = _color_class(r["margin_delta_yi"])

        parts.append(
            '<tr>'
            f'<td>{_fmt_date(r["date"])}</td>'
            f'<td>{_fmt_int(r["twii_close"])}</td>'
            f'<td class="{chg_cls}">{_fmt_pct(r["twii_change_pct"], sign=True)}</td>'
            f'<td>{_fmt_pct(r["pct_above_20ma"])}</td>'
            f'<td>{_fmt_pct(r["pct_above_50ma"])}</td>'
            f'<td>{_fmt_pct(r["pct_above_200ma"])}</td>'
            f'<td>{_fmt_int(r["new_high_200d"])}</td>'
            f'<td class="{f_cls}">{_fmt_yi(r["foreign_yi"])}</td>'
            f'<td class="{t_cls}">{_fmt_yi(r["trust_yi"])}</td>'
            f'<td class="{d_cls}">{_fmt_yi(r["dealer_yi"])}</td>'
            f'<td class="{tot_cls}">{_fmt_yi(r["total_yi"])}</td>'
            f'<td>{_fmt_yi(r["margin_balance_yi"], sign=False)}</td>'
            f'<td class="{md_cls}">{_fmt_yi(r["margin_delta_yi"])}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)
