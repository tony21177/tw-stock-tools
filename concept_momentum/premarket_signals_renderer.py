"""Render 盤前訊號 (TR + 強勢股第二波) HTML — two stacked sub-tables."""


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _empty_msg() -> str:
    return ('<p class="empty-state" style="text-align:center; padding: 20px; '
            'color: #888;">近 10 個交易日無候選</p>')


def _render_tr(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>L1 通過</th><th>ABCD 分數</th><th>連續天數</th>'
             '</tr></thead><tbody>']
    for r in rows:
        l1 = '✓' if r.get('layer1_passed') else '—'
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{l1}</td>'
            f'<td>{r.get("abcd_score", 0)}</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_sw(rows: list[dict]) -> str:
    if not rows:
        return _empty_msg()
    parts = ['<div class="table-scroll" style="overflow-x:auto;">',
             '<table class="market-breadth">',
             '<thead><tr><th>代號</th><th>名稱</th><th>入榜日期</th>'
             '<th>第二波分數</th><th>急跌%</th><th>量比</th><th>連續天數</th>'
             '</tr></thead><tbody>']
    for r in rows:
        drop = r.get('drop_pct', 0.0)
        drop_cls = 'pos' if drop > 0 else 'neg' if drop < 0 else ''
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{r.get("second_wave_score", 0):.2f}</td>'
            f'<td class="{drop_cls}">{drop:+.1f}%</td>'
            f'<td>{r.get("volume_ratio", 0):.2f}x</td>'
            f'<td>{r.get("consecutive_days", 1)}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def render_table(tr_rows: list[dict], sw_rows: list[dict]) -> str:
    """Render two stacked sub-tables. Each section either shows table or
    empty message."""
    return (
        '<h3 style="margin-top: 16px;">🌅 轉機接力 (TR Layer 2 ABCD)</h3>'
        + _render_tr(tr_rows)
        + '<h3 style="margin-top: 24px;">🌅 強勢股第二波</h3>'
        + _render_sw(sw_rows)
    )
