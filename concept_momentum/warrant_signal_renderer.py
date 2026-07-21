#!/usr/bin/env python3
"""權證量能觀察頁渲染 — /warrant-signal.

⚠ 重要：2026-07-21 回測（63 交易日）顯示此訊號**無預測 edge**（空方從未觸發、
多方無顯著正報酬、爆量端甚至反向）。本頁為**觀察工具、非買賣訊號**，用途是看
「哪些現股今天權證爆量、認購/認售偏向、哪家券商在發」，不代表會漲跌。
"""
import html as _html

YI = 1e8
_DIR_LABEL = {
    "bull": ("🔥 偏多", "資金偏押認購（爆量且認購佔比升）— 注意：回測無此方向 edge"),
    "bear": ("❄ 偏空", "資金偏押認售（爆量且認購佔比降）— 回測此方向從未觸發（認售太稀）"),
    "neutral": ("⚡ 中性", "爆量但認購/認售未明顯失衡（多為只有認購在交易）"),
}


def _esc(s) -> str:
    return _html.escape(str(s))


def _fmt_yi(v: float) -> str:
    return f"{v / YI:.2f}"


def render_backtest_caveat(bt: dict | None) -> str:
    """紅字揭露盒：回測無 edge。bt = warrant_backtest.json 內容或 None。"""
    period = ""
    if bt and bt.get("start"):
        period = (f"（回測 {bt['start'][4:6]}/{bt['start'][6:]}"
                  f"~{bt['end'][4:6]}/{bt['end'][6:]}，63 交易日）")
    return (
        '<section style="background:#fdecea;border:1px solid #f5b7b1;'
        'border-radius:6px;padding:12px 16px;margin-bottom:12px;">'
        '<b style="color:#c0392b;">⚠ 回測結論：此訊號無預測 edge — 本頁僅為觀察工具，'
        '非買賣訊號</b>'
        f'<p class="small" style="margin:6px 0 0;color:#7b241c;">{period}'
        '<b>空方（大跌）</b>：認售權證量僅認購 ~8%，訊號從未觸發、不可用。'
        '<b>多方（大漲）</b>：無統計顯著正報酬（t≈0、95% CI 全跨 0）；'
        '收緊爆量門檻反而<b>顯著為負</b>（權證大爆量常是券商分銷／散戶追高，'
        '非聰明錢）。<b>請勿當作進場訊號</b>，僅用於觀察權證資金聚集在哪些現股。</p>'
        '</section>')


def render_page(signal_rows: list[dict], day: dict, asof: str,
                backtest: dict | None = None) -> str:
    """完整 HTML：nav + 無 edge 揭露 + 當日權證爆量現股表。"""
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/chip-price">📋 籌碼價量</a> '
           '<a href="/money-flow">💰 族群資金流</a> '
           '<a href="/warrant-signal">🎰 權證量能</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
  table{width:100%;border-collapse:collapse;font-size:.86em;}
  th,td{padding:6px 9px;border-bottom:1px solid #eee;text-align:right;}
  th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left;}
  th{background:#fafafa;color:#555;}
  .pos{color:#c0392b;} .neg{color:#186a3b;}
  .small,small{font-size:.85em;color:#666;}
  details{margin:2px 0;} summary{cursor:pointer;color:#0066cc;}
  .meta{color:#666;font-size:.85em;}
</style>"""
    fmt_date = f"{asof[:4]}/{asof[4:6]}/{asof[6:]}" if len(asof) == 8 else asof
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>權證量能觀察</title>{css}</head><body>{nav}'
            f'<h1>🎰 權證量能觀察 — {fmt_date}</h1>')
    parts = [head, render_backtest_caveat(backtest)]

    if not signal_rows:
        parts.append('<section><p class="small">今日無權證爆量現股'
                     '（或尚無當日資料）。</p></section>')
        parts.append('</body></html>')
        return "\n".join(parts)

    unders = day.get("underlyings", {})
    parts.append(
        '<section><p class="meta">當日權證總成交金額 ≥ 近20日均 2 倍的現股。'
        '「認購佔比」= 認購(含牛證)成交金額 ÷ 全部權證；Δ = 今日 − 近20日均。'
        '金額單位億元、近似。</p>'
        '<table><thead><tr>'
        '<th>代號</th><th>方向</th><th>爆量倍數</th><th>權證總額(億)</th>'
        '<th>認購佔比</th><th>Δ占比</th><th>權證檔數</th><th>主要發行券商</th>'
        '</tr></thead><tbody>')
    for r in signal_rows:
        u = unders.get(r["code"], {})
        d_label, d_tip = _DIR_LABEL.get(r["direction"], ("—", ""))
        issuers = u.get("issuers", {})
        top_iss = sorted(issuers.items(), key=lambda x: -x[1])[:3]
        iss_txt = "、".join(f"{_esc(n)}" for n, _ in top_iss) or "—"
        tops = u.get("top_warrants", [])
        detail = "".join(
            f"<div class='small'>{_esc(w['name'])} "
            f"({_esc(w['issuer'] or '?')}/{'認購' if w['side']=='bull' else '認售'}) "
            f"{_fmt_yi(w['turnover'])}億</div>" for w in tops[:5])
        share_cls = "pos" if (r["bull_share_delta"] or 0) > 0 else (
            "neg" if (r["bull_share_delta"] or 0) < 0 else "")
        parts.append(
            f'<tr><td>{_esc(r["code"])}</td>'
            f'<td title="{_esc(d_tip)}">{d_label}</td>'
            f'<td>{r["surge_ratio"]:.1f}x</td>'
            f'<td>{_fmt_yi(r["warrant_turnover"])}</td>'
            f'<td>{r["bull_share"]:.2f}</td>'
            f'<td class="{share_cls}">{r["bull_share_delta"]:+.2f}</td>'
            f'<td>{u.get("n_warrants", "—")}</td>'
            f'<td style="text-align:left"><details><summary>{iss_txt}</summary>'
            f'{detail}</details></td></tr>')
    parts.append('</tbody></table>'
                 '<p class="small">🔥偏多／❄偏空／⚡中性 — 見上方回測揭露，'
                 '方向標記無驗證過的預測力，僅描述當日認購/認售偏向。</p></section>')
    parts.append('</body></html>')
    return "\n".join(parts)
