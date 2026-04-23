#!/usr/bin/env python3
"""
概念動能圖表生成：PNG (matplotlib) + 互動 HTML (plotly)
"""

import json
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
TEMPLATES_DIR = os.path.join(HERE, "templates")


def setup_chinese_font():
    """Find a Chinese font available on the system."""
    candidates = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/mnt/c/Windows/Fonts/msjh.ttc",
        "/mnt/c/Windows/Fonts/msyh.ttc",
        "/mnt/c/Windows/Fonts/mingliu.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            font_manager.fontManager.addfont(path)
            prop = font_manager.FontProperties(fname=path)
            plt.rcParams["font.family"] = prop.get_name()
            plt.rcParams["axes.unicode_minus"] = False
            return prop.get_name()
    # Fallback
    plt.rcParams["font.family"] = ["DejaVu Sans"]
    return None


def generate_png(results: list[dict], target_date: str) -> str:
    """Generate summary PNG. Returns file path."""
    os.makedirs(STATIC_DIR, exist_ok=True)
    setup_chinese_font()

    top_n = min(15, len(results))
    top = results[:top_n]

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"台股概念動能監控  {target_date}", fontsize=16, fontweight="bold")

    # === Subplot 1: Top concepts sustainability score ===
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

    # === Subplot 2: Heatmap of 5d vs 20d returns ===
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

    # === Subplot 3: Breadth bar chart ===
    ax = axes[1, 0]
    names_b = [r["name_zh"][:10] for r in top][::-1]
    breadth = [r["breadth_20d"] for r in top][::-1]
    colors_b = ["#2ca02c" if b >= 70 else "#ff7f0e" if b >= 50 else "#d62728" for b in breadth]
    ax.barh(names_b, breadth, color=colors_b)
    ax.axvline(50, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("20 日廣度 (%)")
    ax.set_title("族群廣度（>60%=資金散進）", fontweight="bold")
    ax.set_xlim(0, 100)

    # === Subplot 4: RS vs volume ===
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
    # Also save as latest.png
    latest_path = os.path.join(STATIC_DIR, "latest.png")
    plt.savefig_bbox_inches = None
    import shutil
    shutil.copy(out_path, latest_path)
    return out_path


def generate_html(results: list[dict], taiex_rows: list[dict], target_date: str) -> str:
    """Generate interactive HTML dashboard. Returns file path."""
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    # Create summary table data
    table_data = []
    for i, r in enumerate(results, 1):
        table_data.append({
            "排名": i,
            "概念": r["name_zh"],
            "成分": r["stock_count"],
            "5d%": round(r["ret_5d"], 2),
            "20d%": round(r["ret_20d"], 2),
            "廣度5d": round(r["breadth_5d"], 1),
            "廣度20d": round(r["breadth_20d"], 1),
            "持續天": r["duration"],
            "量比": round(r["volume_ratio"], 2),
            "RS_5d": round(r["rs_5d"], 2),
            "RS_20d": round(r["rs_20d"], 2),
            "評分": round(r["sustainability_score"], 1),
        })

    # Build 4-panel figure
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("Top 15 概念評分", "5d/20d 報酬象限",
                        "族群廣度 (20d)", "相對強度 vs 量能"),
        specs=[[{"type": "bar"}, {"type": "scatter"}],
               [{"type": "bar"}, {"type": "scatter"}]],
        horizontal_spacing=0.12,
        vertical_spacing=0.15,
    )

    top_n = min(15, len(results))
    top = results[:top_n]

    # Panel 1: Score bars
    names = [r["name_zh"] for r in top][::-1]
    scores = [r["sustainability_score"] for r in top][::-1]
    colors = ["#d62728" if s >= 70 else "#ff7f0e" if s >= 50 else "#1f77b4" for s in scores]
    fig.add_trace(go.Bar(
        x=scores, y=names, orientation="h",
        marker_color=colors, text=[f"{s:.0f}" for s in scores], textposition="outside",
        hovertemplate="%{y}<br>評分: %{x:.1f}<extra></extra>",
    ), row=1, col=1)

    # Panel 2: Return scatter
    fig.add_trace(go.Scatter(
        x=[r["ret_20d"] for r in top], y=[r["ret_5d"] for r in top],
        mode="markers+text", text=[r["name_zh"][:6] for r in top],
        textposition="top center",
        marker=dict(
            size=[max(10, r["sustainability_score"] / 2) for r in top],
            color=[r["sustainability_score"] for r in top],
            colorscale="RdYlGn", showscale=False, line=dict(color="black", width=1),
        ),
        hovertemplate="%{text}<br>20d: %{x:.2f}%<br>5d: %{y:.2f}%<extra></extra>",
    ), row=1, col=2)

    # Panel 3: Breadth
    breadth_names = [r["name_zh"] for r in top][::-1]
    breadth_vals = [r["breadth_20d"] for r in top][::-1]
    breadth_colors = ["#2ca02c" if b >= 70 else "#ff7f0e" if b >= 50 else "#d62728" for b in breadth_vals]
    fig.add_trace(go.Bar(
        x=breadth_vals, y=breadth_names, orientation="h",
        marker_color=breadth_colors,
        text=[f"{b:.0f}%" for b in breadth_vals], textposition="outside",
        hovertemplate="%{y}<br>廣度: %{x:.1f}%<extra></extra>",
    ), row=2, col=1)

    # Panel 4: RS vs volume
    fig.add_trace(go.Scatter(
        x=[r["rs_20d"] for r in top], y=[r["volume_ratio"] for r in top],
        mode="markers+text", text=[r["name_zh"][:6] for r in top],
        textposition="top center",
        marker=dict(
            size=[max(10, r["sustainability_score"] / 2) for r in top],
            color=[r["sustainability_score"] for r in top],
            colorscale="RdYlGn", showscale=True,
            colorbar=dict(title="評分", x=1.02),
            line=dict(color="black", width=1),
        ),
        hovertemplate="%{text}<br>RS: %{x:.2f}%<br>量比: %{y:.2f}<extra></extra>",
    ), row=2, col=2)

    fig.update_xaxes(title_text="永續性評分", row=1, col=1, range=[0, 100])
    fig.update_xaxes(title_text="20 日報酬 (%)", row=1, col=2)
    fig.update_yaxes(title_text="5 日報酬 (%)", row=1, col=2)
    fig.update_xaxes(title_text="20 日廣度 (%)", row=2, col=1, range=[0, 100])
    fig.update_xaxes(title_text="相對強度 (%)", row=2, col=2)
    fig.update_yaxes(title_text="5d/20d 量比", row=2, col=2)

    fig.update_layout(
        title={
            "text": f"台股概念動能監控  {target_date}",
            "x": 0.5, "xanchor": "center",
            "font": {"size": 20},
        },
        height=800, showlegend=False,
        template="plotly_white",
    )

    chart_html = fig.to_html(include_plotlyjs="cdn", div_id="main-chart", full_html=False)

    # Build table HTML
    table_rows = ""
    for row in table_data:
        score_class = "score-high" if row["評分"] >= 70 else "score-mid" if row["評分"] >= 50 else "score-low"
        table_rows += f"""
        <tr>
            <td>{row['排名']}</td>
            <td><strong>{row['概念']}</strong></td>
            <td>{row['成分']}</td>
            <td class="{'pos' if row['5d%'] > 0 else 'neg'}">{row['5d%']:+.2f}</td>
            <td class="{'pos' if row['20d%'] > 0 else 'neg'}">{row['20d%']:+.2f}</td>
            <td>{row['廣度5d']}</td>
            <td>{row['廣度20d']}</td>
            <td>{row['持續天']}</td>
            <td>{row['量比']}</td>
            <td class="{'pos' if row['RS_5d'] > 0 else 'neg'}">{row['RS_5d']:+.2f}</td>
            <td class="{'pos' if row['RS_20d'] > 0 else 'neg'}">{row['RS_20d']:+.2f}</td>
            <td class="{score_class}">{row['評分']}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>台股概念動能監控 {target_date}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft JhengHei", sans-serif; margin: 0; padding: 20px; background: #f5f5f7; }}
  h1 {{ color: #1d1d1f; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .chart-wrap {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
  th {{ background: #1d1d1f; color: white; padding: 12px; text-align: left; position: sticky; top: 0; cursor: pointer; user-select: none; }}
  th:hover {{ background: #333; }}
  td {{ padding: 10px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f5f5f7; }}
  .pos {{ color: #d62728; font-weight: 600; }}
  .neg {{ color: #2ca02c; font-weight: 600; }}
  .score-high {{ background: #d62728; color: white; font-weight: bold; text-align: center; }}
  .score-mid {{ background: #ff7f0e; color: white; font-weight: bold; text-align: center; }}
  .score-low {{ background: #e0e0e0; text-align: center; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
</style>
</head>
<body>
<div class="container">
<h1>台股概念動能監控</h1>
<div class="meta">報告日期: {target_date} | 評分公式: 40% 廣度 + 20% 量能 + 20% RS + 20% 持續天數</div>
<div class="chart-wrap">{chart_html}</div>
<h2>詳細評分表</h2>
<table id="conceptTable">
<thead>
<tr>
<th>排名</th><th>概念</th><th>成分</th><th>5d%</th><th>20d%</th>
<th>廣度5d</th><th>廣度20d</th><th>持續天</th><th>量比</th>
<th>RS_5d</th><th>RS_20d</th><th>評分</th>
</tr>
</thead>
<tbody>{table_rows}</tbody>
</table>
<p class="meta" style="margin-top:20px;">指標說明：
<br>• <b>廣度</b>：概念內 N 日上漲股票 %，>60% 表示資金散進
<br>• <b>持續天</b>：概念指數連續站上 5MA 天數
<br>• <b>量比</b>：5 日均量 / 20 日均量，>1.2 表示量能放大
<br>• <b>RS</b>：概念報酬 - TAIEX 報酬，正值代表強於大盤
<br>• <b>評分</b>：永續性綜合分數，≥70 紅（高動能）, 50-70 橘, &lt;50 藍</p>
</div>
</body>
</html>
"""
    out_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    from data_fetcher import fetch_all_concepts, fetch_taiex
    from concept_momentum import analyze_all

    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        concepts = json.load(f)

    stocks = fetch_all_concepts(concepts)
    taiex = fetch_taiex()
    results = analyze_all(concepts, stocks, taiex)

    target_date = datetime.now().strftime("%Y-%m-%d")
    png = generate_png(results, target_date)
    html = generate_html(results, taiex, target_date)
    print(f"PNG: {png}")
    print(f"HTML: {html}")
