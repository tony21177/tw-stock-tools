#!/usr/bin/env python3
"""
概念動能圖表生成：PNG (matplotlib) + 互動 HTML (plotly)
包含當日快照 + 3 個月趨勢。
"""

import json
import os
import sys
import shutil
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
TEMPLATES_DIR = os.path.join(HERE, "templates")


def setup_chinese_font():
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/mnt/c/Windows/Fonts/msjh.ttc",
        "/mnt/c/Windows/Fonts/msyh.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            font_manager.fontManager.addfont(path)
            prop = font_manager.FontProperties(fname=path)
            plt.rcParams["font.family"] = prop.get_name()
            plt.rcParams["axes.unicode_minus"] = False
            return prop.get_name()
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return None


def _fmt_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[4:6]}/{yyyymmdd[6:8]}"


def generate_png(results: list[dict], target_date: str) -> str:
    """Snapshot PNG (4 panels): score, return quadrant, breadth, RS/volume."""
    os.makedirs(STATIC_DIR, exist_ok=True)
    setup_chinese_font()

    top_n = min(15, len(results))
    top = results[:top_n]

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"台股概念動能監控  {target_date}", fontsize=16, fontweight="bold")

    ax = axes[0, 0]
    names = [r["name_zh"] for r in top][::-1]
    scores = [r["sustainability_score"] for r in top][::-1]
    colors = ["#d62728" if s >= 70 else "#ff7f0e" if s >= 50 else "#1f77b4" for s in scores]
    ax.barh(names, scores, color=colors)
    ax.set_xlabel("永續性評分")
    ax.set_title(f"Top {top_n} 概念評分", fontweight="bold")
    ax.set_xlim(0, 100)
    for i, v in enumerate(scores):
        ax.text(v + 1, i, f"{v:.0f}", va="center", fontsize=9)

    ax = axes[0, 1]
    ret_5d = [r["ret_5d"] for r in top]
    ret_20d = [r["ret_20d"] for r in top]
    ax.scatter(ret_20d, ret_5d, s=[r["sustainability_score"] * 3 for r in top],
               c=[r["sustainability_score"] for r in top], cmap="RdYlGn", alpha=0.7, edgecolors="black")
    for r in top[:8]:
        ax.annotate(r["name_zh"][:6], (r["ret_20d"], r["ret_5d"]), fontsize=8,
                    xytext=(3, 3), textcoords="offset points")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.axvline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("20 日報酬 (%)")
    ax.set_ylabel("5 日報酬 (%)")
    ax.set_title("報酬象限（點大小=評分）", fontweight="bold")
    ax.grid(alpha=0.3)

    ax = axes[1, 0]
    names_b = [r["name_zh"][:10] for r in top][::-1]
    breadth = [r["breadth_20d"] for r in top][::-1]
    colors_b = ["#2ca02c" if b >= 70 else "#ff7f0e" if b >= 50 else "#d62728" for b in breadth]
    ax.barh(names_b, breadth, color=colors_b)
    ax.axvline(50, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("20 日廣度 (%)")
    ax.set_title("族群廣度（>60%=資金散進）", fontweight="bold")
    ax.set_xlim(0, 100)

    ax = axes[1, 1]
    rs = [r["rs_20d"] for r in top]
    vol = [r["volume_ratio"] for r in top]
    ax.scatter(rs, vol, s=[r["sustainability_score"] * 3 for r in top],
               c=[r["sustainability_score"] for r in top], cmap="RdYlGn", alpha=0.7, edgecolors="black")
    for r in top[:8]:
        ax.annotate(r["name_zh"][:6], (r["rs_20d"], r["volume_ratio"]), fontsize=8,
                    xytext=(3, 3), textcoords="offset points")
    ax.axhline(1.0, color="gray", linewidth=0.5, linestyle="--")
    ax.axvline(0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("相對強度 (vs TAIEX, %)")
    ax.set_ylabel("5d/20d 量能比")
    ax.set_title("相對強度 vs 量能", fontweight="bold")
    ax.grid(alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(STATIC_DIR, f"concept_momentum_{target_date}.png")
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    shutil.copy(out_path, os.path.join(STATIC_DIR, "latest.png"))
    return out_path


def generate_trend_png(results: list[dict], target_date: str, top_n: int = 8) -> str:
    """Trend PNG: score history for top N concepts + concept index price chart."""
    os.makedirs(STATIC_DIR, exist_ok=True)
    setup_chinese_font()

    top = [r for r in results[:top_n] if r.get("score_history")]
    if not top:
        return ""

    fig, axes = plt.subplots(2, 1, figsize=(14, 11))
    fig.suptitle(f"概念動能 3 個月趨勢  {target_date}", fontsize=16, fontweight="bold")

    # === Panel 1: Score time series ===
    ax = axes[0]
    palette = plt.cm.tab10(range(top_n))
    for i, r in enumerate(top):
        hist = r["score_history"]
        dates = [h["date"] for h in hist]
        scores = [h["score"] for h in hist]
        x_labels = [_fmt_date(d) for d in dates]
        ax.plot(range(len(hist)), scores, marker="o", markersize=3,
                label=f"{r['name_zh']}", color=palette[i], linewidth=1.5)
    ax.axhline(70, color="red", linestyle="--", alpha=0.5, label="高動能線 (70)")
    ax.axhline(50, color="orange", linestyle="--", alpha=0.5, label="中等線 (50)")
    ax.set_ylabel("永續性評分")
    ax.set_title(f"Top {top_n} 概念 3 個月評分走勢（看哪些是「長期強」）", fontweight="bold")
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    # Set x-ticks to dates sampled
    if top and top[0].get("score_history"):
        hist = top[0]["score_history"]
        n = len(hist)
        tick_every = max(1, n // 8)
        ax.set_xticks(range(0, n, tick_every))
        ax.set_xticklabels([_fmt_date(hist[i]["date"]) for i in range(0, n, tick_every)], rotation=45)

    # === Panel 2: Concept index price (normalized to 100 at start) ===
    ax = axes[1]
    for i, r in enumerate(top):
        ci = r.get("concept_index", [])
        if not ci:
            continue
        # Normalize to 100 at start
        base = ci[0]["value"]
        values = [p["value"] / base * 100 for p in ci]
        ax.plot(range(len(values)), values,
                label=f"{r['name_zh']}", color=palette[i], linewidth=1.5)
    ax.axhline(100, color="gray", linestyle="--", alpha=0.3)
    ax.set_ylabel("族群指數 (起始=100)")
    ax.set_title(f"Top {top_n} 概念 3 個月族群指數走勢", fontweight="bold")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    if top and top[0].get("concept_index"):
        ci = top[0]["concept_index"]
        n = len(ci)
        tick_every = max(1, n // 8)
        ax.set_xticks(range(0, n, tick_every))
        ax.set_xticklabels([_fmt_date(ci[i]["date"]) for i in range(0, n, tick_every)], rotation=45)

    plt.tight_layout()
    out_path = os.path.join(STATIC_DIR, f"concept_trend_{target_date}.png")
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close()
    shutil.copy(out_path, os.path.join(STATIC_DIR, "latest_trend.png"))
    return out_path


def _build_ignition_history_html(target_date: str,
                                  lookback_days: int = 30) -> str:
    """Scan past `lookback_days` analysis_*.json files for concepts that
    transitioned from dormant (score<3) to strong (score>=10) day-over-day.
    Returns HTML table of all ignition events found, plus follow-through
    score trajectory for each (to assess real vs fake ignition).
    """
    results_dir = os.path.join(HERE, "cache", "results")
    import glob as _glob
    files = sorted(_glob.glob(os.path.join(results_dir, "analysis_*.json")))
    if len(files) < 2:
        return '<p class="meta">需要至少 2 天歷史資料才能偵測點火</p>'
    by_date = {}
    for fp in files:
        date = os.path.basename(fp)[9:17]
        try:
            with open(fp) as f:
                by_date[date] = {x["theme_key"]: x for x in json.load(f)}
        except (OSError, json.JSONDecodeError):
            continue
    dates = sorted(by_date.keys())
    # Limit to lookback window
    cutoff = dates[-lookback_days:] if len(dates) > lookback_days else dates

    events = []
    for i in range(1, len(cutoff)):
        d_today = cutoff[i]
        d_yest = cutoff[i - 1]
        for tk, t in by_date[d_today].items():
            y = by_date[d_yest].get(tk)
            if not y:
                continue
            t_score = t.get("sustainability_score", 0)
            y_score = y.get("sustainability_score", 0)
            delta = t_score - y_score
            if y_score < 3 and t_score >= 10 and delta >= 8:
                # Follow-through: scores in subsequent days
                follow = []
                idx = dates.index(d_today)
                for d_fwd in dates[idx + 1:idx + 6]:
                    f_score = by_date[d_fwd].get(tk, {}).get(
                        "sustainability_score", 0)
                    follow.append((d_fwd, f_score))
                events.append({
                    "date": d_today, "theme": t["name_zh"],
                    "yest": y_score, "today": t_score, "delta": delta,
                    "stock_count": t.get("stock_count", 0),
                    "breadth": t.get("breadth_5d", 0),
                    "volume_ratio": t.get("volume_ratio", 0),
                    "leaders": t.get("leaders", [])[:3],
                    "follow": follow,
                })
    if not events:
        return '<p class="meta">過去 {} 個交易日無族群點火事件</p>'.format(
            len(cutoff))

    events.sort(key=lambda e: e["date"], reverse=True)
    rows = []
    for e in events:
        # Tag based on stock_count + volume_ratio heuristic
        if e["stock_count"] >= 7 and e["volume_ratio"] >= 0.95:
            tag = '<span style="color:#0a7e0a;font-weight:600">✅ 高機率真</span>'
        elif e["stock_count"] <= 4:
            tag = '<span style="color:#c30;font-weight:600">⚠ 假點火風險</span>'
        else:
            tag = '<span style="color:#ff7f0e;font-weight:600">🟡 觀察</span>'
        # Follow-through arrow
        follow_str = "（待觀察）"
        if e["follow"]:
            peak = max(f[1] for f in e["follow"])
            last_s = e["follow"][-1][1]
            multiplier = peak / e["today"] if e["today"] > 0 else 0
            n_days = len(e["follow"])
            if peak == 0:
                follow_str = (f'<span style="color:#c30">❌ 假 '
                              f'(後 {n_days} 日 score 全 0，徹底失溫)</span>')
            elif last_s == 0 and peak <= e["today"] * 1.2:
                follow_str = (f'<span style="color:#c30">❌ 假 '
                              f'(後 {n_days} 日最高僅 {peak:.0f}, '
                              f'最終回 0)</span>')
            elif multiplier >= 2.0:
                follow_str = (f'<span style="color:#0a7e0a">✅ 真 '
                              f'(後 {n_days} 日高點 {peak:.0f}, '
                              f'×{multiplier:.1f})</span>')
            else:
                follow_str = (f'後 {n_days} 日高點 {peak:.0f} '
                              f'(×{multiplier:.1f}), 最終 {last_s:.0f}')
        leaders = " / ".join(
            f"{L.get('code', '')} {L.get('name', '')[:6]}" for L in e["leaders"])
        rows.append(
            f'<tr>'
            f'<td>{e["date"][:4]}-{e["date"][4:6]}-{e["date"][6:8]}</td>'
            f'<td><b>{e["theme"]}</b></td>'
            f'<td class="num">{e["yest"]:.1f}</td>'
            f'<td class="num">{e["today"]:.1f}</td>'
            f'<td class="num"><b>+{e["delta"]:.1f}</b></td>'
            f'<td class="num">{e["stock_count"]}</td>'
            f'<td class="num">{e["breadth"]:.0f}%</td>'
            f'<td class="num">{e["volume_ratio"]:.2f}x</td>'
            f'<td>{tag}</td>'
            f'<td>{follow_str}</td>'
            f'<td style="font-size:0.85em;">{leaders}</td>'
            f'</tr>'
        )
    return (
        '<table><thead><tr>'
        '<th>點火日</th><th>族群</th><th class="num">昨</th>'
        '<th class="num">今</th><th class="num">Δ</th>'
        '<th class="num" title="子數 ≥7 較不易假點火">子數</th>'
        '<th class="num">5d 廣度</th>'
        '<th class="num" title="≥0.95 較不易假點火">量比</th>'
        '<th>預測</th><th>實際追蹤</th><th>領漲</th>'
        '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    )


def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str,
                  breadth_table_html: str = "",
                  broker_radar_html: str = "",
                  premarket_signals_html: str = "",
                  lending_history_html: str = "") -> str:
    """Interactive HTML dashboard with snapshot + trend + leaders."""
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    top_n = min(15, len(results))
    top = results[:top_n]

    # ============ Figure 1: Snapshot quadrants ============
    fig1 = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Top 15 概念評分", "5d/20d 報酬象限",
                        "族群廣度 (20d)", "相對強度 vs 量能"),
        specs=[[{"type": "bar"}, {"type": "scatter"}],
               [{"type": "bar"}, {"type": "scatter"}]],
        horizontal_spacing=0.12, vertical_spacing=0.15,
    )

    names = [r["name_zh"] for r in top][::-1]
    scores = [r["sustainability_score"] for r in top][::-1]
    colors = ["#d62728" if s >= 70 else "#ff7f0e" if s >= 50 else "#1f77b4" for s in scores]
    fig1.add_trace(go.Bar(x=scores, y=names, orientation="h",
        marker_color=colors, text=[f"{s:.0f}" for s in scores], textposition="outside",
        hovertemplate="%{y}<br>評分: %{x:.1f}<extra></extra>"), row=1, col=1)

    fig1.add_trace(go.Scatter(
        x=[r["ret_20d"] for r in top], y=[r["ret_5d"] for r in top],
        mode="markers+text", text=[r["name_zh"][:6] for r in top], textposition="top center",
        marker=dict(size=[max(10, r["sustainability_score"] / 2) for r in top],
                    color=[r["sustainability_score"] for r in top], colorscale="RdYlGn",
                    showscale=False, line=dict(color="black", width=1)),
        hovertemplate="%{text}<br>20d: %{x:.2f}%<br>5d: %{y:.2f}%<extra></extra>"), row=1, col=2)

    breadth_names = [r["name_zh"] for r in top][::-1]
    breadth_vals = [r["breadth_20d"] for r in top][::-1]
    breadth_colors = ["#2ca02c" if b >= 70 else "#ff7f0e" if b >= 50 else "#d62728" for b in breadth_vals]
    fig1.add_trace(go.Bar(x=breadth_vals, y=breadth_names, orientation="h",
        marker_color=breadth_colors, text=[f"{b:.0f}%" for b in breadth_vals], textposition="outside",
        hovertemplate="%{y}<br>廣度: %{x:.1f}%<extra></extra>"), row=2, col=1)

    fig1.add_trace(go.Scatter(
        x=[r["rs_20d"] for r in top], y=[r["volume_ratio"] for r in top],
        mode="markers+text", text=[r["name_zh"][:6] for r in top], textposition="top center",
        marker=dict(size=[max(10, r["sustainability_score"] / 2) for r in top],
                    color=[r["sustainability_score"] for r in top], colorscale="RdYlGn",
                    showscale=True, colorbar=dict(title="評分", x=1.02),
                    line=dict(color="black", width=1)),
        hovertemplate="%{text}<br>RS: %{x:.2f}%<br>量比: %{y:.2f}<extra></extra>"), row=2, col=2)

    fig1.update_xaxes(title_text="永續性評分", row=1, col=1, range=[0, 100])
    fig1.update_xaxes(title_text="20 日報酬 (%)", row=1, col=2)
    fig1.update_yaxes(title_text="5 日報酬 (%)", row=1, col=2)
    fig1.update_xaxes(title_text="20 日廣度 (%)", row=2, col=1, range=[0, 100])
    fig1.update_xaxes(title_text="相對強度 (%)", row=2, col=2)
    fig1.update_yaxes(title_text="5d/20d 量比", row=2, col=2)
    fig1.update_layout(title="今日快照", height=700, showlegend=False, template="plotly_white")

    snapshot_html = fig1.to_html(include_plotlyjs="cdn", div_id="snapshot", full_html=False)

    # ============ Figure 2: Score history trend ============
    trend_top = [r for r in results[:10] if r.get("score_history")]
    fig2 = go.Figure()
    for r in trend_top:
        hist = r["score_history"]
        dates = [h["date"] for h in hist]
        scores_h = [h["score"] for h in hist]
        fig2.add_trace(go.Scatter(
            x=dates, y=scores_h, mode="lines+markers", name=r["name_zh"],
            hovertemplate=f"{r['name_zh']}<br>%{{x}}<br>評分: %{{y:.1f}}<extra></extra>",
        ))
    fig2.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="高動能線 70")
    fig2.add_hline(y=50, line_dash="dash", line_color="orange", annotation_text="中等線 50")
    fig2.update_layout(
        title="Top 10 概念 3 個月評分走勢",
        xaxis_title="日期", yaxis_title="永續性評分", yaxis_range=[0, 100],
        height=500, template="plotly_white", hovermode="x unified",
    )
    trend_html = fig2.to_html(include_plotlyjs=False, div_id="trend", full_html=False)

    # ============ Figure 3: Concept index prices ============
    fig3 = go.Figure()
    for r in trend_top:
        ci = r.get("concept_index", [])
        if not ci:
            continue
        base = ci[0]["value"]
        fig3.add_trace(go.Scatter(
            x=[p["date"] for p in ci], y=[p["value"] / base * 100 for p in ci],
            mode="lines", name=r["name_zh"],
            hovertemplate=f"{r['name_zh']}<br>%{{x}}<br>%{{y:.2f}}<extra></extra>",
        ))
    fig3.add_hline(y=100, line_dash="dash", line_color="gray")
    fig3.update_layout(
        title="Top 10 概念 3 個月族群指數走勢（起始=100）",
        xaxis_title="日期", yaxis_title="族群指數",
        height=500, template="plotly_white", hovermode="x unified",
    )
    index_html = fig3.to_html(include_plotlyjs=False, div_id="index", full_html=False)

    # ============ 族群點火歷史榜 ============
    ignition_history_html = _build_ignition_history_html(target_date)

    # ============ Leaders + Laggards table (pairs trading view) ============
    def _member_rows(members, side):
        out = ""
        for L in members:
            five_class = "pos" if L["ret_5d"] > 0 else "neg"
            twenty_class = "pos" if L["ret_20d"] > 0 else "neg"
            tag = "🟢 多" if side == "leader" else "🔴 空"
            out += f"""
            <tr class="row-{side}">
                <td>{tag}</td>
                <td>{L['code']}</td>
                <td>{L['name']}</td>
                <td>[{L['market']}]</td>
                <td>${L['current_price']:.2f}</td>
                <td class="{five_class}">{L['ret_5d']:+.2f}%</td>
                <td class="{twenty_class}">{L['ret_20d']:+.2f}%</td>
                <td>{L['vol_ratio']:.2f}x</td>
            </tr>"""
        return out

    leader_sections = ""
    high_results = [r for r in results if r["sustainability_score"] >= 50]
    for r in high_results:
        leaders = r.get("leaders", [])
        laggards = r.get("laggards", [])
        if not leaders and not laggards:
            continue
        rows_html = _member_rows(leaders, "leader") + _member_rows(laggards, "laggard")
        pair_hint = ""
        if leaders and laggards:
            pair_hint = (f" <span class=\"badge\">配對：多 {leaders[0]['code']} "
                         f"／ 空 {laggards[0]['code']}</span>")
        leader_sections += f"""
        <h3>{r['name_zh']} <span class="badge">評分 {r['sustainability_score']:.0f}</span>{pair_hint}</h3>
        <table class="leader-table">
            <thead><tr>
              <th title="🟢 多 = leader (族群領漲，做多候選); 🔴 空 = laggard (族群落後，可空)">方向</th>
              <th title="股票代號">代號</th>
              <th title="股票中文名稱">名稱</th>
              <th title="上市 / 上櫃">市場</th>
              <th title="當日收盤價">現價</th>
              <th title="過去 5 個交易日報酬率 (含今日)">5d%</th>
              <th title="過去 20 個交易日報酬率 (含今日)">20d%</th>
              <th title="近 5d 均量 / 近 20d 均量；>1.5 = 量增">量比</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>"""

    # ============ Main table ============
    table_rows = ""
    for i, r in enumerate(results, 1):
        score_class = "score-high" if r["sustainability_score"] >= 70 else \
                      "score-mid" if r["sustainability_score"] >= 50 else "score-low"
        table_rows += f"""
        <tr>
            <td>{i}</td>
            <td><strong>{r['name_zh']}</strong></td>
            <td>{r['stock_count']}</td>
            <td class="{'pos' if r['ret_5d'] > 0 else 'neg'}">{r['ret_5d']:+.2f}</td>
            <td class="{'pos' if r['ret_20d'] > 0 else 'neg'}">{r['ret_20d']:+.2f}</td>
            <td>{r['breadth_5d']:.1f}</td>
            <td>{r['breadth_20d']:.1f}</td>
            <td>{r['duration']}</td>
            <td>{r['volume_ratio']:.2f}</td>
            <td class="{'pos' if r['rs_20d'] > 0 else 'neg'}">{r['rs_20d']:+.2f}</td>
            <td class="{score_class}">{r['sustainability_score']:.1f}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>台股概念動能監控 {target_date}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft JhengHei", sans-serif; margin: 0; padding: 20px; background: #f5f5f7; color: #1d1d1f; }}
  h1 {{ margin-top: 0; }}
  h2 {{ margin-top: 40px; border-bottom: 2px solid #1d1d1f; padding-bottom: 8px; }}
  h3 {{ margin-top: 28px; color: #d62728; }}
  .badge {{ background: #d62728; color: white; padding: 3px 10px; border-radius: 12px; font-size: 13px; margin-left: 8px; vertical-align: middle; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .chart-wrap {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
  th {{ background: #1d1d1f; color: white; padding: 10px; text-align: left; }}
  th[title] {{ cursor: help; position: relative; outline: none; border-bottom: 1px dotted rgba(255,255,255,0.4); }}
  th[title]:hover::after, th[title]:focus::after {{
    content: attr(title);
    position: absolute;
    top: 100%;
    left: 0;
    background: #1a1a1a;
    color: #fff;
    padding: 10px 14px;
    white-space: pre-wrap;
    width: max-content;
    max-width: min(320px, 80vw);
    z-index: 100;
    font-size: 13px;
    font-weight: normal;
    text-align: left;
    border-radius: 6px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    line-height: 1.5;
    pointer-events: none;
  }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f5f5f7; }}
  .pos {{ color: #d62728; font-weight: 600; }}
  .neg {{ color: #2ca02c; font-weight: 600; }}
  .score-high {{ background: #d62728; color: white; font-weight: bold; text-align: center; }}
  .score-mid {{ background: #ff7f0e; color: white; font-weight: bold; text-align: center; }}
  .score-low {{ background: #e0e0e0; text-align: center; }}
  .leader-table th {{ background: #444; font-size: 13px; }}
  .row-leader {{ background: #fff5f5; }}
  .row-laggard {{ background: #f0fdf4; }}
  .row-leader:hover {{ background: #ffe0e0; }}
  .row-laggard:hover {{ background: #d4f4dc; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .tab {{ padding: 10px 20px; background: #e0e0e0; border-radius: 8px 8px 0 0; cursor: pointer; user-select: none; }}
  .tab.active {{ background: #1d1d1f; color: white; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}
</style>
</head>
<body>
<div class="container">
<h1>台股概念動能監控</h1>
<div class="meta">報告日期: {target_date} | 評分: 40% 廣度 + 20% 量能 + 20% RS + 20% 持續天數</div>

<div class="lookup-bar" style="background:white;padding:14px 18px;border-radius:10px;margin-bottom:18px;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
  <div style="display:flex;flex-wrap:wrap;gap:14px;align-items:center;">
    <span style="font-weight:600;font-size:15px;">🔍 單檔快速查詢:</span>
    <form action="/chip-price" method="get" style="display:flex;gap:4px;">
      <input type="text" name="code" placeholder="股號" required style="width:80px;padding:6px 8px;font-size:14px;border:1px solid #ccc;border-radius:4px;">
      <button type="submit" style="padding:6px 12px;background:#0066cc;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px;">📋 籌碼價量</button>
    </form>
    <form action="/contract-liabilities" method="get" style="display:flex;gap:4px;">
      <input type="text" name="code" placeholder="股號" required style="width:80px;padding:6px 8px;font-size:14px;border:1px solid #ccc;border-radius:4px;">
      <button type="submit" style="padding:6px 12px;background:#0066cc;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px;">💰 合約負債</button>
    </form>
    <form action="/inventory" method="get" style="display:flex;gap:4px;">
      <input type="text" name="code" placeholder="股號" required style="width:80px;padding:6px 8px;font-size:14px;border:1px solid #ccc;border-radius:4px;">
      <button type="submit" style="padding:6px 12px;background:#0066cc;color:white;border:none;border-radius:4px;cursor:pointer;font-size:13px;">📦 存貨</button>
    </form>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('breadth')">📊 大盤寬度</div>
  <div class="tab" onclick="showTab('ignition')">🔥 族群點火</div>
  <div class="tab" onclick="showTab('broker')">🎯 主力雷達</div>
  <div class="tab" onclick="showTab('premarket')">🌅 盤前訊號</div>
  <div class="tab" onclick="showTab('lending')">🌙 借券動向</div>
  <div class="tab" onclick="showTab('snap')">🔥 今日快照</div>
  <div class="tab" onclick="showTab('trend')">📈 3 個月趨勢</div>
  <div class="tab" onclick="showTab('leaders')">強勢族群領漲股</div>
  <div class="tab" onclick="showTab('full')">完整排行</div>
  <a class="tab" href="/chip-price" style="text-decoration:none;color:inherit;">📋 籌碼價量查詢</a>
  <a class="tab" href="/contract-liabilities" style="text-decoration:none;color:inherit;">💰 合約負債</a>
  <a class="tab" href="/inventory" style="text-decoration:none;color:inherit;">📦 存貨</a>
</div>

<div id="tab-breadth" class="tab-content active chart-wrap">
  <h2>📊 大盤寬度（最近 60 個交易日）</h2>
  <p class="meta">寬度池 = 上市+上櫃 普通股 4 位代號 (~2,300 檔) | 紅 = 漲/買超 / 綠 = 跌/賣超 / 缺值 = —</p>
  {breadth_table_html}
</div>
<div id="tab-ignition" class="tab-content chart-wrap">
  <h2>🔥 族群點火歷史榜（30 個交易日視窗）</h2>
  <p class="meta">休眠 (score &lt; 3) → 轉強 (score ≥ 10) 且 Δ ≥ 8 視為點火 |
     歷史模式：子數 ≥7 + 量比 ≥0.95 = 高機率真點火 (×3-4 倍 sustained) |
     子數 ≤4 = 假點火風險高 (1 日噴出即破滅)</p>
  {ignition_history_html}
</div>
<div id="tab-broker" class="tab-content chart-wrap">
  <h2>🎯 主力雷達歷史榜（10 日視窗）</h2>
  <p class="meta">綜合分數 = 連續天數 × (log(Top 分點累計淨買 + 1) + sqrt(融資增量)) / 2 | Top 30</p>
  {broker_radar_html}
</div>
<div id="tab-premarket" class="tab-content chart-wrap">
  <h2>🌅 盤前訊號（10 日視窗）</h2>
  <p class="meta">盤前 07:30 / 07:40 cron 跑出的兩層篩選結果</p>
  {premarket_signals_html}
</div>
<div id="tab-lending" class="tab-content chart-wrap">
  <h2>🌙 借券動向（5 日視窗）</h2>
  <p class="meta">盤後 16:00 / 21:30 cron 跑出的議借爆量 + 借券賣餘大減</p>
  {lending_history_html}
</div>
<div id="tab-snap" class="tab-content chart-wrap">{snapshot_html}</div>
<div id="tab-trend" class="tab-content chart-wrap">{trend_html}{index_html}</div>
<div id="tab-leaders" class="tab-content chart-wrap">
  <h2>族群領漲股 + 弱勢成員（評分 ≥50，可配對交易）</h2>
  <p class="meta">🟢 多：5d &gt; -5%，依 20d 漲幅排序前 5；🔴 空：5d ≤ -5%，依 5d 跌幅最深排序前 5</p>
  {leader_sections if leader_sections else '<p>今日無評分 ≥70 的高動能族群</p>'}
</div>
<div id="tab-full" class="tab-content">
  <table>
    <thead><tr>
      <th title="依永續性評分降冪排序的名次">排名</th>
      <th title="概念族群中文名稱 (~34 個主題)">概念</th>
      <th title="該概念的成分股檔數">成分</th>
      <th title="族群指數近 5 日報酬率 (等權重組合)">5d%</th>
      <th title="族群指數近 20 日報酬率 (等權重組合)">20d%</th>
      <th title="族群成份中，近 5 日報酬 > 0 的個股比例 (%)">廣度5d</th>
      <th title="族群成份中，近 20 日報酬 > 0 的個股比例 (%) — 越高代表越多成分股同步上漲">廣度20d</th>
      <th title="族群連續維持高動能 (評分 ≥50) 的交易日數">持續</th>
      <th title="族群近 5d 均量 / 近 20d 均量；>1.5 = 資金進場明顯">量比</th>
      <th title="族群 vs 大盤 (^TWII) 過去 20 日的相對強度差 (族群報酬 − 大盤報酬)">RS20d</th>
      <th title="永續性評分 (0-100)：40% 廣度 + 20% 量能 + 20% RS + 20% 持續天數；≥70 強勢，<30 弱勢">評分</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>

</div>
<script>
function showTab(name) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  window.dispatchEvent(new Event('resize'));
}}

// Mobile-friendly tooltips: make th[title] tap-focusable so CSS :focus::after fires.
// Desktop: hover still works. Mobile: tap to show, tap elsewhere to hide.
document.addEventListener('DOMContentLoaded', function() {{
  document.querySelectorAll('th[title]').forEach(function(th) {{
    th.setAttribute('tabindex', '0');
    // Toggle focus: tap again to dismiss
    th.addEventListener('click', function(e) {{
      if (document.activeElement === th) {{ th.blur(); }} else {{ th.focus(); }}
    }});
  }});
  // Tap anywhere else clears any tooltip
  document.addEventListener('click', function(e) {{
    if (!e.target.matches('th[title]') && document.activeElement && document.activeElement.matches('th[title]')) {{
      document.activeElement.blur();
    }}
  }});
}});
</script>
</body>
</html>
"""
    out_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    from data_fetcher import fetch_all_concepts, fetch_taiex
    from concept_momentum import analyze_all, add_score_history

    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        concepts = json.load(f)
    stocks = fetch_all_concepts(concepts)
    taiex = fetch_taiex()
    results = analyze_all(concepts, stocks, taiex)
    add_score_history(concepts, results[:10], stocks, taiex)

    target_date = datetime.now().strftime("%Y-%m-%d")
    png1 = generate_png(results, target_date)
    png2 = generate_trend_png(results, target_date)
    html = generate_html(results, taiex, target_date)
    print(f"Snapshot PNG: {png1}")
    print(f"Trend PNG: {png2}")
    print(f"HTML: {html}")
