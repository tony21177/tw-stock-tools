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
             '<thead><tr>'
             '<th title="股票代號">代號</th>'
             '<th title="股票中文名稱">名稱</th>'
             '<th title="該檔最近一次入借券雷達榜的日期 (議借量爆增日)">入榜日期</th>'
             '<th title="當日議借交易量 (張) — 借券平台議借總量">議借量 (張)</th>'
             '<th title="當日量 / 過去 5 日均量；2x 以上 = 議借爆量；新上榜股可能無歷史，顯示 —">5日均量倍數</th>'
             '<th title="議借利率%；>7% (紅) = 高成本做空 (空頭強烈意願)，<1% (綠) = 機構議借/套利券源 (非方向性)">利率%</th>'
             '<th title="連續入榜天數 — 從最新入榜日往前回看，連續幾日議借爆量 (中間 gap 重置)。連續越多日 = 空方持續建倉。">連續天數</th>'
             '</tr></thead><tbody>']
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
             '<thead><tr>'
             '<th title="股票代號">代號</th>'
             '<th title="股票中文名稱">名稱</th>'
             '<th title="該檔最近一次入空頭撤退榜的日期 (借券賣出餘額大幅減少日)">入榜日期</th>'
             '<th title="借券賣出餘額 vs 前日的變化%；大幅負 (-10%+) = 空方大規模回補 (利多訊號)">餘額變化%</th>'
             '<th title="股票當日漲跌%；綠 = 跌, 紅 = 漲。空方撤退+股價漲 = 強烈轉多訊號">今日漲跌%</th>'
             '<th title="連續入榜天數 — 從最新入榜日往前回看，連續幾日借券賣餘大減 (中間 gap 重置)。連續越多日 = 空方持續撤退。">連續天數</th>'
             '</tr></thead><tbody>']
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
