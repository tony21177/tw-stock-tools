"""Render 主力雷達歷史榜 HTML table from sorted rows.

Pure function: list of dicts → HTML string.
"""

EMPTY_MSG = ('<p class="empty-state" style="text-align:center; padding: 40px; '
             'color: #888;">今日無主力雷達訊號</p>')


def _fmt_date(yyyymmdd: str) -> str:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return yyyymmdd or "—"
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def render_table(rows: list[dict], top_n: int = 30) -> str:
    """Render top N rows as HTML table.

    Empty list → friendly message, no <table>.
    """
    if not rows:
        return EMPTY_MSG

    parts = ['<div class="table-scroll" style="overflow-x:auto;">']
    parts.append('<table class="market-breadth">')
    parts.append('<thead><tr>'
                 '<th>排名</th><th>代號</th><th>名稱</th>'
                 '<th>連續天數</th><th>最新入榜</th>'
                 '<th>Top 分點</th><th>區間 Top 分點淨買 (張)</th>'
                 '<th>融資增量 (張)</th><th>綜合分數</th>'
                 '</tr></thead><tbody>')

    for i, r in enumerate(rows[:top_n], start=1):
        broker_label = (f"{r['top_broker_id']} {r['top_broker_name']}"
                        if r.get('top_broker_id') else "—")
        parts.append(
            '<tr>'
            f'<td>{i}</td>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{r["consecutive_days"]}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{broker_label}</td>'
            f'<td>{_fmt_int(r.get("top_broker_net_zhang"))}</td>'
            f'<td>{_fmt_int(r.get("margin_increase_zhang"))}</td>'
            f'<td>{r.get("score", 0):.1f}</td>'
            '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)
