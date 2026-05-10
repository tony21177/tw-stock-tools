"""Render 借券動向 (借券雷達 + 空頭撤退) — two stacked sub-tables."""


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _empty_msg() -> str:
    return ('<p class="empty-state" style="text-align:center; padding: 20px; '
            'color: #888;">近 5 個交易日無候選</p>')


def _rate_class(rate: float) -> str:
    """Rate > 7% = pos (red, 高成本做空), < 1% = neg (green, 套利可能), else ''."""
    if rate is None:
        return ""
    if rate > 7:
        return "pos"
    if rate < 1:
        return "neg"
    return ""


def _signed_class(v: float) -> str:
    if v is None or v == 0:
        return ""
    return "pos" if v > 0 else "neg"


def _render_radar(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>議借量 (張)</th><th>5日均量倍數</th><th>利率%</th>'
             '<th>連續天數</th></tr></thead><tbody>']
    for r in rows:
        rate = r.get("rate_pct", 0.0)
        rate_cls = _rate_class(rate)
        ratio = r.get("ratio_5d")
        ratio_str = "—" if ratio is None else f"{ratio:.2f}x"
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{int(r.get("lending_zhang", 0)):,}</td>'
            f'<td>{ratio_str}</td>'
            f'<td class="{rate_cls}">{rate:.2f}%</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_retreat(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>餘額變化%</th><th>今日漲跌%</th>'
             '<th>連續天數</th></tr></thead><tbody>']
    for r in rows:
        bc = r.get("balance_change_pct", 0.0)
        tc = r.get("today_change_pct", 0.0)
        bc_cls = _signed_class(bc)
        tc_cls = _signed_class(tc)
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td class="{bc_cls}">{bc:+.2f}%</td>'
            f'<td class="{tc_cls}">{tc:+.2f}%</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def render_table(radar_rows: list[dict], retreat_rows: list[dict]) -> str:
    return (
        '<h3 style="margin-top: 16px;">🌙 借券雷達 (議借爆量)</h3>'
        + _render_radar(radar_rows)
        + '<h3 style="margin-top: 24px;">🌙 空頭撤退 (借券賣餘大減)</h3>'
        + _render_retreat(retreat_rows)
    )
