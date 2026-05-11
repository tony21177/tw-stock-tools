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
             '<thead><tr>'
             '<th title="股票代號">代號</th>'
             '<th title="股票中文名稱">名稱</th>'
             '<th title="該檔最近一次入轉機接力 Layer 2 榜的日期">入榜日期</th>'
             '<th title="Layer 1 (轉機篩選器) 是否通過：毛利率改善 + 量能放大 + 借券回補 + 季線多頭 + GM≥0%">L1 通過</th>'
             '<th title="Layer 2 ABCD 接力訊號評分 (0-4)，每項通過 +1 分：'
             '&#10;&#10;A 漲停接力：過去 3 日 (不含今日) 任一日漲幅 ≥ +5% (或 ≥+9.5% 漲停)，且前日盤中未崩跌 (≥ -4%)。'
             '&#10;&#10;B 借券回補：近 3 日借券餘額均量 / 前 5 日均量 ≤ 0.97 (-3%)，或前日單日餘額變化 ≤ -3%。空方撤退訊號。'
             '&#10;&#10;C 籌碼集中：top 10 買方中外資 ≥ 2 家，或 top 5 買超合計 ≥ top 5 賣超合計。買方比賣方更集中。'
             '&#10;&#10;D 量能蓄勢：前日量 / 20 日均量 ≥ 1.0，或前日量 / 60 日均量 ≥ 1.5。明日續攻需有量能基礎。'
             '&#10;&#10;4/4 滿分 = 強烈接力訊號 (明日續攻機率最高)；2-3 分 = 部分訊號；≤1 分 = 雜訊。">ABCD 分數</th>'
             '<th title="連續入榜天數 — 從最近一次入榜日往前回看，連續幾日該檔都在 turnaround_relay_history/{date}.json 出現。一旦中間有一天 gap，連續天數 reset。連續越多日代表 L1+L2 訊號越穩定。'
             '&#10;&#10;例：5/9 入榜 + 5/10 入榜 + 5/11 入榜 → 連續 3 日'
             '&#10;例：5/9 入榜 + 5/10 沒入 + 5/11 入榜 → 連續 1 日 (gap 重置)">連續天數</th>'
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
             '<thead><tr>'
             '<th title="股票代號">代號</th>'
             '<th title="股票中文名稱">名稱</th>'
             '<th title="該檔最近一次入強勢股第二波榜的日期">入榜日期</th>'
             '<th title="第二波分數公式：rally_gain × drop_pct × bounce_pct × min(vol_ratio,3) × (today_vs_peak − 0.7)；越高代表 setup 越完美">第二波分數</th>'
             '<th title="峰值到低點的跌幅 (% from peak to trough)；典型 setup 為 -15~-25%">急跌%</th>'
             '<th title="近 3 日均量 / 急跌期均量 — 反彈時量能是否回來，越高越好">量比</th>'
             '<th title="連續入榜天數 — 從最近一次入榜日往前回看，連續幾日都被第二波 setup 掃中 (中間 gap 重置)。連續越多日代表底部盤整越穩。">連續天數</th>'
             '</tr></thead><tbody>']
    for r in rows:
        # drop_pct is stored as decimal magnitude (0.25 = 25% drop from peak to trough);
        # display as negative pct with green (drop direction).
        drop_raw = r.get('drop_pct', 0.0)
        drop_pct_display = -drop_raw * 100
        drop_cls = 'neg' if drop_raw > 0 else ''
        parts.append(
            '<tr>'
            f'<td>{r["code"]}</td>'
            f'<td>{r.get("name", r["code"])}</td>'
            f'<td>{_fmt_date(r.get("latest_date", ""))}</td>'
            f'<td>{r.get("second_wave_score", 0):.4f}</td>'
            f'<td class="{drop_cls}">{drop_pct_display:+.1f}%</td>'
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
