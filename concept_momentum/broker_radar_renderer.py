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
                 '<th title="依綜合分數降冪排序的名次">排名</th>'
                 '<th title="股票代號">代號</th>'
                 '<th title="股票中文名稱">名稱</th>'
                 '<th title="連續被主力雷達掃中的交易日數 — 從最新入榜日往前回看，連續幾日該檔都在 broker_radar_history/{date}.json 出現 (中間 gap 重置)。越高代表主力分點+融資雙連動持續越久，鎖籌訊號越強。'
                 '&#10;&#10;例：5/9 入榜 + 5/10 入榜 + 5/11 入榜 → 連續 3 日'
                 '&#10;例：5/9 入榜 + 5/10 沒入 + 5/11 入榜 → 連續 1 日 (gap 重置)">連續天數</th>'
                 '<th title="該檔最近一次入主力雷達榜的日期">最新入榜</th>'
                 '<th title="區間內累計買超最多的單一分點 (broker ID + 名稱)">Top 分點</th>'
                 '<th title="該分點在 5 日視窗內的累計淨買超 (張) — 反映該分點規模">區間 Top 分點淨買 (張)</th>'
                 '<th title="該標的在 5 日視窗內的融資餘額變化 (張) — 正值 = 散戶/主力同步加碼">融資增量 (張)</th>'
                 '<th title="綜合分數公式：連續天數 × (log(Top分點淨買+1) + sqrt(融資增量)) / 2；負值 clip 為 0">綜合分數</th>'
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
