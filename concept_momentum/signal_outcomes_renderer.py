"""Render 訊號成效追蹤 (📈 訊號成效) tab HTML from signal_outcomes.json."""
from __future__ import annotations

_STRAT_LABELS = {
    "turnaround_relay": "🔄 轉機接力",
    "second_wave":      "🌊 強勢第二波",
    "broker_radar":     "🎯 主力雷達",
    "lending_radar":    "🌙 借券雷達",
    "short_retreat":    "🏳 空頭撤退",
}

_HORIZONS = [("1", "T+1 (當日收)"), ("5", "T+5 (~1週)"),
             ("10", "T+10 (~2週)"), ("20", "T+20 (~1月)")]


def _fmt_date(d: str) -> str:
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}/{d[4:6]}/{d[6:8]}"
    return d or "—"


def _pct_cell(val, positive_good=True) -> str:
    """Render a % value with pos/neg CSS class."""
    if val is None:
        return "<td>—</td>"
    cls = ("pos" if val > 0 else "neg") if positive_good else ("neg" if val > 0 else "pos")
    return f'<td class="{cls}">{val:+.2f}%</td>'


def _render_summary_table(summary: dict) -> str:
    """Per-strategy × horizon summary table."""
    if not summary:
        return '<p style="color:#888;text-align:center;padding:20px">無成效數據 — 請先執行 run_outcomes.py</p>'

    strat_order = ["turnaround_relay", "second_wave", "broker_radar",
                   "lending_radar", "short_retreat"]

    parts = [
        '<div class="table-scroll" style="overflow-x:auto;margin-bottom:24px;">',
        '<table class="market-breadth">',
        '<thead><tr>',
        '<th title="策略">策略</th>',
        '<th title="horizion">持有期</th>',
        '<th title="有完整 T+h 收盤價的訊號筆數">n</th>',
        '<th title="超額報酬均值 = 個股報酬 − TAIEX 同窗報酬，全策略筆數平均">超額均%</th>',
        '<th title="超額報酬中位數">中位%</th>',
        '<th title="個股報酬 > 0 的比例">勝率%</th>',
        '<th title="個股超額報酬 > 0 (打贏大盤) 的比例">贏大盤%</th>',
        '</tr></thead><tbody>',
    ]

    for strat in strat_order:
        sh = summary.get(strat)
        if not sh:
            continue
        label = _STRAT_LABELS.get(strat, strat)
        first = True
        n_rows = sum(1 for hk, _ in _HORIZONS if hk in sh)
        for hk, hlabel in _HORIZONS:
            hd = sh.get(hk)
            if not hd:
                continue
            if first:
                parts.append(f'<tr><td rowspan="{n_rows}"><b>{label}</b></td>')
                first = False
            else:
                parts.append('<tr>')
            exc_mean = hd.get("exc_mean")
            exc_med = hd.get("exc_med")
            win = hd.get("win")
            beat = hd.get("beat")
            parts.append(f'<td>{hlabel}</td>')
            parts.append(f'<td>{hd.get("n", "—")}</td>')
            parts.append(_pct_cell(exc_mean))
            parts.append(_pct_cell(exc_med))
            parts.append(f'<td>{"—" if win is None else f"{win:.0f}%"}</td>')
            parts.append(f'<td>{"—" if beat is None else f"{beat:.0f}%"}</td>')
            parts.append('</tr>')

    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_abcd_bucket_table(abcd: dict) -> str:
    """TR abcd_score 分桶表 (>=3 / <3 + per-score)."""
    if not abcd:
        return '<p style="color:#888">無 TR abcd 分桶數據</p>'

    parts = [
        '<div class="table-scroll" style="overflow-x:auto;margin-bottom:24px;">',
        '<table class="market-breadth">',
        '<thead><tr>',
        '<th title="ABCD 分桶">分桶</th>',
    ]
    for hk, hlabel in _HORIZONS:
        parts.append(f'<th colspan="3" title="{hlabel}">{hlabel}</th>')
    parts.append('</tr><tr><th></th>')
    for _ in _HORIZONS:
        parts.append('<th title="筆數">n</th>'
                     '<th title="超額均%">超額均</th>'
                     '<th title="贏大盤%">贏大盤</th>')
    parts.append('</tr></thead><tbody>')

    # Show >=3, <3 first, then per-score
    bucket_order = ["gte3", "lt3"] + [f"score_{i}" for i in range(5)]
    bucket_labels = {
        "gte3": "abcd ≥ 3 (強訊號)",
        "lt3": "abcd < 3 (弱訊號)",
        **{f"score_{i}": f"  score {i}/4" for i in range(5)},
    }

    for bk in bucket_order:
        bd = abcd.get(bk)
        if not bd:
            continue
        parts.append(f'<tr><td><b>{bucket_labels.get(bk, bk)}</b></td>')
        for hk, _ in _HORIZONS:
            hd = bd.get(hk)
            if not hd:
                parts.append('<td>—</td><td>—</td><td>—</td>')
                continue
            exc_cls = "pos" if hd.get("exc_mean", 0) > 0 else "neg"
            beat = hd.get("beat")
            parts.append(f'<td>{hd.get("n","—")}</td>')
            parts.append(f'<td class="{exc_cls}">{hd.get("exc_mean",0):+.1f}%</td>')
            parts.append(f'<td>{"—" if beat is None else f"{beat:.0f}%"}</td>')
        parts.append('</tr>')

    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_sw_tercile_table(sw: dict) -> str:
    """SW second_wave_score 三分位表。"""
    if not sw:
        return '<p style="color:#888">無 SW score 三分位數據</p>'

    parts = [
        '<div class="table-scroll" style="overflow-x:auto;margin-bottom:24px;">',
        '<table class="market-breadth">',
        '<thead><tr>',
        '<th title="SW score 分位">分位</th>',
    ]
    for hk, hlabel in _HORIZONS:
        parts.append(f'<th colspan="3" title="{hlabel}">{hlabel}</th>')
    parts.append('</tr><tr><th></th>')
    for _ in _HORIZONS:
        parts.append('<th>n</th><th>超額均</th><th>贏大盤</th>')
    parts.append('</tr></thead><tbody>')

    label_map = {
        "high_tercile": "高分位 (top 1/3)",
        "mid_tercile": "中分位 (mid 1/3)",
        "low_tercile": "低分位 (bot 1/3)",
    }
    for bk in ["high_tercile", "mid_tercile", "low_tercile"]:
        bd = sw.get(bk)
        if not bd:
            continue
        parts.append(f'<tr><td><b>{label_map.get(bk, bk)}</b></td>')
        for hk, _ in _HORIZONS:
            hd = bd.get(hk)
            if not hd:
                parts.append('<td>—</td><td>—</td><td>—</td>')
                continue
            exc_cls = "pos" if hd.get("exc_mean", 0) > 0 else "neg"
            beat = hd.get("beat")
            parts.append(f'<td>{hd.get("n","—")}</td>')
            parts.append(f'<td class="{exc_cls}">{hd.get("exc_mean",0):+.1f}%</td>')
            parts.append(f'<td>{"—" if beat is None else f"{beat:.0f}%"}</td>')
        parts.append('</tr>')

    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _render_recent_signals(signals: list[dict], n: int = 20) -> str:
    """最近 n 筆訊號明細 (code / 策略 / 進場日 / T+5 超額)。"""
    recent = signals[-n:] if len(signals) > n else signals
    recent = list(reversed(recent))  # most recent first

    if not recent:
        return '<p style="color:#888">無訊號明細</p>'

    parts = [
        '<div class="table-scroll" style="overflow-x:auto;margin-bottom:24px;">',
        '<table class="market-breadth">',
        '<thead><tr>',
        '<th title="股票代號">代號</th>',
        '<th title="股票名稱">名稱</th>',
        '<th title="策略">策略</th>',
        '<th title="訊號日 (資料日或執行日，視策略而定)">訊號日</th>',
        '<th title="進場日 (開盤買入日期)">進場日</th>',
        '<th title="T+1 超額報酬% = 進場日開→收報酬 − TAIEX 同窗">T+1 超額</th>',
        '<th title="T+5 (~1週) 超額報酬%">T+5 超額</th>',
        '<th title="T+20 (~1月) 超額報酬%">T+20 超額</th>',
        '</tr></thead><tbody>',
    ]

    for r in recent:
        ret = r.get("ret", {})
        code = r.get("code", "")
        name = r.get("meta", {}).get("name", code)
        strat = _STRAT_LABELS.get(r.get("strategy", ""), r.get("strategy", ""))
        sig_d = _fmt_date(r.get("signal_date", ""))
        ent_d = _fmt_date(r.get("entry_date", ""))
        h1 = ret.get("1", {}).get("exc")
        h5 = ret.get("5", {}).get("exc")
        h20 = ret.get("20", {}).get("exc")

        def _cell(v):
            if v is None:
                return '<td>—</td>'
            cls = "pos" if v > 0 else "neg"
            return f'<td class="{cls}">{v:+.1f}%</td>'

        parts.append(
            f'<tr>'
            f'<td>{code}</td>'
            f'<td>{name}</td>'
            f'<td style="font-size:0.85em">{strat}</td>'
            f'<td>{sig_d}</td>'
            f'<td>{ent_d}</td>'
            + _cell(h1) + _cell(h5) + _cell(h20)
            + '</tr>'
        )
    parts.append('</tbody></table></div>')
    return "\n".join(parts)


def _glossary_section() -> str:
    terms = [
        ("T+h 報酬 (成效追蹤)",
         "h=1 = 進場日開盤買→當日收盤賣，h=5 ≈ 1 週，h=10 ≈ 2 週，h=20 ≈ 1 個月。"
         "進場口徑：entry_date 的還原開盤價（開盤買最保守可實現）。"
         "成效 = (T+h 還原收 / 進場還原開) − 1 − TAIEX 同窗報酬。"),
        ("進場日 (entry) 正規化",
         "各策略 date 欄語意不同：\n"
         "• 轉機接力 / 主力雷達 / 借券雷達 / 空頭撤退：date = 資料日（前一交易日盤後），"
         "entry = date 之後的下一個交易日（隔日開盤）。\n"
         "• 強勢股第二波：date = 執行日（盤前 07:40），entry = ≥ date 的第一個交易日（當日開盤）。"),
        ("超額報酬 (exc)",
         "個股 T+h 報酬 − TAIEX 同窗報酬 (同進出場日視窗)。超額 > 0 = 打贏大盤；< 0 = 跑輸大盤。"),
        ("勝率 (win%)",
         "個股 T+h 絕對報酬 > 0 的比例 (漲的比例，不含 TAIEX baseline)。"),
        ("贏大盤% (beat%)",
         "個股 T+h 超額報酬 > 0 的比例 (打贏 TAIEX 的比例)。"),
        ("abcd 分桶 (TR)",
         "ABCD 接力評分 0-4 分。"
         "≥ 3 = A+B+C 或 A+B+D 等強訊號組合；< 3 = 弱訊號。"
         "分桶比較回答「高分訊號是否真的更好？」"),
        ("SW score 三分位",
         "second_wave_score = 五因子乘積（峰前漲幅 × 急跌幅 × 反彈幅 × 量比 × 距峰位置）。"
         "三分位比較回答「score 高的第二波 setup 是否實際報酬更好？」"),
        ("還原價 (adjusted)",
         "TaiwanStockPriceAdj 已做除權息還原，排除配息/配股造成的價格跳空。"),
    ]
    parts = [
        '<section style="margin-top:32px; padding:16px; background:#f8f9fa; '
        'border-radius:8px; font-size:0.9em;">',
        '<h3 style="margin:0 0 12px">📖 名詞解釋</h3>',
        '<dl style="margin:0;">',
    ]
    for term, desc in terms:
        desc_html = desc.replace("\n", "<br>")
        parts.append(
            f'<dt style="font-weight:600;margin-top:10px;">{term}</dt>'
            f'<dd style="margin:2px 0 0 1em;color:#444;">{desc_html}</dd>'
        )
    parts.append('</dl></section>')
    return "\n".join(parts)


def render_tab(data: dict | None) -> str:
    """Main entry point — render the full 訊號成效 tab HTML."""
    if data is None:
        return (
            '<div style="text-align:center;padding:40px;color:#888;">'
            '尚無成效數據。<br>執行：<code>python3 concept_momentum/run_outcomes.py</code>'
            '</div>'
        )

    generated = data.get("generated", "")[:16]
    n_failed = data.get("n_px_failed", 0)
    n_total = data.get("n_px_codes", 0)
    signals = data.get("signals", [])
    summary = data.get("summary", {})
    abcd = data.get("abcd_buckets", {})
    sw_tercile = data.get("sw_score_terciles", {})

    parts = [
        f'<h2 style="margin-bottom:6px;">📈 訊號成效（後照鏡）</h2>',
        f'<p class="meta">更新時間：{generated} ｜ 個股 px: {n_total} 檔，失敗 {n_failed} 檔</p>',
    ]

    # Per-strategy summary
    parts.append('<h3 style="margin-top:20px;">各策略 T+h 成效彙總</h3>')
    parts.append(_render_summary_table(summary))

    # TR abcd bucket
    parts.append('<h3 style="margin-top:20px;">🔬 轉機接力 abcd 分桶 (≥3 vs &lt;3 及 per-score)</h3>')
    parts.append('<p class="meta">回答：高 abcd 分數的訊號是否實際優於低分訊號？</p>')
    parts.append(_render_abcd_bucket_table(abcd))

    # SW score tercile
    parts.append('<h3 style="margin-top:20px;">🌊 強勢第二波 score 三分位</h3>')
    parts.append('<p class="meta">回答：second_wave_score 高的 setup 是否有更好的實際報酬？</p>')
    parts.append(_render_sw_tercile_table(sw_tercile))

    # Recent 20 signals
    parts.append('<h3 style="margin-top:20px;">最近 20 筆訊號明細</h3>')
    parts.append(_render_recent_signals(signals, n=20))

    # Glossary
    parts.append(_glossary_section())

    return "\n".join(parts)
