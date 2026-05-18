#!/usr/bin/env python3
"""
每日 orchestrator：抓資料 → 分析 → 生成圖表 → 推送 Telegram
"""

import argparse
import glob
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BROKER_HISTORY_DIR = os.path.join(HERE, "cache", "broker_radar_history")
TR_HISTORY_DIR = os.path.join(HERE, "cache", "turnaround_relay_history")
SW_HISTORY_DIR = os.path.join(HERE, "cache", "second_wave_history")
LENDING_HISTORY_DIR = os.path.join(HERE, "cache", "lending_radar_history")
RETREAT_HISTORY_DIR = os.path.join(HERE, "cache", "short_retreat_history")

from data_fetcher import fetch_all_concepts, fetch_taiex
from concept_momentum import analyze_all, add_score_history
from concept_charts import generate_png, generate_trend_png, generate_html
from rerating_detector import compute_rerating, format_rerating_report
from business_drift_detector import detect_drift, format_drift_report
from market_breadth import run_today as run_market_breadth, BREADTH_DIR
from market_breadth_renderer import render_table
from broker_radar_history import load_broker_radar_rows
from broker_radar_renderer import render_table as render_broker_table
from premarket_signals import load_turnaround_relay_rows, load_second_wave_rows
from premarket_signals_renderer import render_table as render_premarket_table
from lending_history import load_lending_radar_rows, load_short_retreat_rows
from lending_history_renderer import render_table as render_lending_table

DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}"


def send_telegram_photo(photo_path: str, caption: str, bot_token: str, chat_id: str) -> bool:
    """Send photo via Telegram. Caption max 1024 chars."""
    url = TG_API_URL.format(token=bot_token) + "/sendPhoto"
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    # multipart form data
    boundary = "----WebKitFormBoundary" + str(int(time.time() * 1000))
    lines = []

    for key, value in [("chat_id", chat_id), ("caption", caption)]:
        lines.append(f"--{boundary}")
        lines.append(f'Content-Disposition: form-data; name="{key}"')
        lines.append("")
        lines.append(value)

    with open(photo_path, "rb") as f:
        photo_data = f.read()

    lines.append(f"--{boundary}")
    lines.append(f'Content-Disposition: form-data; name="photo"; filename="chart.png"')
    lines.append("Content-Type: image/png")
    lines.append("")

    body = "\r\n".join(lines).encode()
    body += b"\r\n" + photo_data
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ok", False)
    except Exception as e:
        print(f"[ERROR] Telegram photo: {e}", file=sys.stderr)
        return False


def send_telegram_text(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API_URL.format(token=bot_token) + "/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ok", False)
    except Exception as e:
        print(f"[ERROR] Telegram text: {e}", file=sys.stderr)
        return False


def detect_ignition_events(results: list[dict], target_yyyymmdd: str,
                            score_jump: float = 8.0,
                            yest_max: float = 3.0,
                            today_min: float = 10.0,
                            lookback_days: int = 30) -> list[dict]:
    """Find concepts whose sustainability_score jumped from dormant (<yest_max)
    to strong (>=today_min) versus the most-recent prior trading day.

    Loads the prior day's analysis_*.json from cache and computes per-theme
    score delta. Returns list of ignition events sorted by delta desc.
    """
    results_dir = os.path.join(HERE, "cache", "results")
    files = sorted(glob.glob(os.path.join(results_dir, "analysis_*.json")))
    today_file = os.path.join(results_dir, f"analysis_{target_yyyymmdd}.json")
    # Find the most recent earlier file
    prior = None
    for fp in reversed(files):
        if os.path.basename(fp) == os.path.basename(today_file):
            continue
        if os.path.basename(fp) < os.path.basename(today_file):
            prior = fp
            break
    if not prior:
        return []
    try:
        with open(prior) as f:
            yest = {x["theme_key"]: x for x in json.load(f)}
    except (OSError, json.JSONDecodeError):
        return []

    events = []
    for r in results:
        tk = r.get("theme_key")
        y = yest.get(tk)
        if not y:
            continue
        t_score = r.get("sustainability_score", 0)
        y_score = y.get("sustainability_score", 0)
        delta = t_score - y_score
        if y_score < yest_max and t_score >= today_min and delta >= score_jump:
            events.append({
                "name_zh": r["name_zh"],
                "yest_score": y_score,
                "today_score": t_score,
                "delta": delta,
                "stock_count": r.get("stock_count", 0),
                "breadth_5d": r.get("breadth_5d", 0),
                "volume_ratio": r.get("volume_ratio", 0),
                "leaders": r.get("leaders", [])[:3],
            })
    events.sort(key=lambda e: -e["delta"])
    return events


def build_ignition_summary(results: list[dict], target_date: str,
                            target_yyyymmdd: str) -> str:
    """Telegram summary of today's ignition events (休眠 → 轉強)."""
    events = detect_ignition_events(results, target_yyyymmdd)
    lines = [f"🔥 族群點火警示 {target_date}"]
    lines.append("（休眠 score<3 → 今日 score≥10, Δ≥8）")
    lines.append("━━━━━━━━━━━━")
    if not events:
        lines.append("（今日無新點火族群）")
        return "\n".join(lines)
    for e in events:
        # Strength heuristic — historical pattern (8 cases, 2026-04-23 onwards):
        #  - stock_count >= 7 + volume_ratio >= 0.95 = high probability real
        #  - stock_count <= 4 = high prob 假點火 (1-day spike)
        if e["stock_count"] >= 7 and e["volume_ratio"] >= 0.95:
            tag = "✅ 高機率真點火"
        elif e["stock_count"] <= 4:
            tag = "⚠ 小族群假點火風險高"
        else:
            tag = "🟡 觀察 1-2 日確認"
        lines.append(f"\n{e['name_zh']}  {e['yest_score']:.1f} → "
                      f"{e['today_score']:.1f}  Δ +{e['delta']:.1f}")
        lines.append(f"  子數 {e['stock_count']} / 廣度 {e['breadth_5d']:.0f}%"
                      f" / 量比 {e['volume_ratio']:.2f}x  {tag}")
        leaders_str = " / ".join(
            f"{L['code']} {L['name'][:6]}" for L in e["leaders"])
        if leaders_str:
            lines.append(f"  領漲: {leaders_str}")
    lines.append("\n📊 歷史模式（過去 17 個交易日 5 個點火樣本）:")
    lines.append("  • 子數 ≥7 + 量比 ≥0.95 → 全 4 個真點火 ×3-4 倍 sustained")
    lines.append("  • 子數 ≤4 → 唯一假點火案例 (折疊螢幕 5/7 噴 40→0)")
    return "\n".join(lines)


def build_summary(results: list[dict], target_date: str) -> str:
    """Build main summary: high-momentum concepts with leaders 🟢 + laggards 🔴.

    族群內配對交易視角：做多 leader / 放空 laggard。"""
    if not results:
        return f"概念動能監控 {target_date}\n\n無資料"

    lines = [f"概念動能監控 {target_date}"]
    lines.append("高動能族群（評分 ≥70）— 🟢 多 leaders / 🔴 空 laggards")
    lines.append("━━━━━━━━━━━━")
    high = [r for r in results if r["sustainability_score"] >= 70]
    if not high:
        lines.append("（今日無高動能族群）")
    else:
        for i, r in enumerate(high, 1):
            lines.append(f"\n{i}. {r['name_zh']}  評分 {r['sustainability_score']:.0f}")
            lines.append(
                f"   20d: {r['ret_20d']:+.1f}%  廣度 {r['breadth_20d']:.0f}%  "
                f"量比 {r['volume_ratio']:.1f}x  RS {r['rs_20d']:+.1f}%  持續 {r['duration']}天"
            )
            leaders = r.get("leaders", [])
            laggards = r.get("laggards", [])
            for L in leaders[:5]:
                lines.append(
                    f"   🟢 {L['code']} {L['name'][:18]}  "
                    f"5d:{L['ret_5d']:+.1f}% 20d:{L['ret_20d']:+.1f}%"
                )
            for L in laggards[:5]:
                lines.append(
                    f"   🔴 {L['code']} {L['name'][:18]}  "
                    f"5d:{L['ret_5d']:+.1f}% 20d:{L['ret_20d']:+.1f}%"
                )
            if leaders and laggards:
                lines.append(
                    f"   ↳ 配對提示：多 {leaders[0]['code']} / 空 {laggards[0]['code']}"
                )
    return "\n".join(lines)


def build_weak_summary(results: list[dict], target_date: str) -> str:
    """Secondary message: weak concepts."""
    lines = [f"弱勢族群監控 {target_date}"]
    low = [r for r in results if r["sustainability_score"] < 30]
    lines.append("評分 <30（資金流出，不建議進場）")
    lines.append("━━━━━━━━━━━━")
    if not low:
        lines.append("（無）")
    else:
        for r in low:
            lines.append(
                f"• {r['name_zh']}  評分 {r['sustainability_score']:.0f}  "
                f"20d: {r['ret_20d']:+.1f}%  RS {r['rs_20d']:+.1f}%  廣度 {r['breadth_20d']:.0f}%"
            )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="概念動能每日分析")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--bot-token")
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--skip-fetch", action="store_true", help="跳過抓資料（用現有快取）")
    args = parser.parse_args()

    bot_token = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")

    # Load concepts
    with open(os.path.join(HERE, "cache", "concepts.json")) as f:
        concepts = json.load(f)

    # Fetch data
    if not args.skip_fetch:
        print("【步驟 1/4】抓取概念股價格資料...", file=sys.stderr)
        stocks = fetch_all_concepts(concepts)
        print("【步驟 2/4】抓取加權指數...", file=sys.stderr)
        taiex = fetch_taiex()
    else:
        # Use existing cache
        stocks = fetch_all_concepts(concepts)  # will read cache
        taiex = fetch_taiex()

    # Analyze
    print("【步驟 3/5】計算動能指標...", file=sys.stderr)
    results = analyze_all(concepts, stocks, taiex)

    print("【步驟 4/5】計算 3 個月評分歷史（Top 10）...", file=sys.stderr)
    add_score_history(concepts, results[:10], stocks, taiex)

    # Save results for downstream tools (e.g., tw_broker_monitor reads strong concepts)
    results_dir = os.path.join(HERE, "cache", "results")
    os.makedirs(results_dir, exist_ok=True)
    results_file = os.path.join(results_dir, f"analysis_{datetime.now().strftime('%Y%m%d')}.json")
    serializable = []
    for r in results:
        rcopy = {k: v for k, v in r.items() if k != "concept_index"}
        serializable.append(rcopy)
    with open(results_file, "w") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"  已存 {results_file}", file=sys.stderr)

    # Charts
    print("【步驟 5/5】生成圖表...", file=sys.stderr)
    target_date = datetime.now().strftime("%Y-%m-%d")
    png_path = generate_png(results, target_date)
    trend_png = generate_trend_png(results, target_date)
    # Market breadth — fetch + compute + render
    target_yyyymmdd = datetime.now().strftime("%Y%m%d")
    finmind_token = os.environ.get("FINMIND_TOKEN", "")
    breadth_html = ""
    if finmind_token:
        print("計算大盤寬度...", file=sys.stderr)
        try:
            run_market_breadth(target_yyyymmdd, finmind_token, verbose=True)
        except Exception as e:
            print(f"[WARN] market_breadth: {e}", file=sys.stderr)
        # Load last 60 breadth rows for table
        if os.path.isdir(BREADTH_DIR):
            files = sorted(f for f in os.listdir(BREADTH_DIR) if f.endswith(".json"))[-60:]
            rows = []
            for fname in files:
                with open(os.path.join(BREADTH_DIR, fname)) as f:
                    rows.append(json.load(f))
            breadth_html = render_table(rows)

    # Strategy history tabs
    print("載入策略歷史榜...", file=sys.stderr)
    broker_rows = load_broker_radar_rows(BROKER_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    broker_html = render_broker_table(broker_rows)

    tr_rows = load_turnaround_relay_rows(TR_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    sw_rows = load_second_wave_rows(SW_HISTORY_DIR, target_yyyymmdd, lookback_days=10)
    premarket_html = render_premarket_table(tr_rows, sw_rows)

    lending_rows = load_lending_radar_rows(LENDING_HISTORY_DIR, target_yyyymmdd, lookback_days=5)
    retreat_rows = load_short_retreat_rows(RETREAT_HISTORY_DIR, target_yyyymmdd, lookback_days=5)
    lending_html = render_lending_table(lending_rows, retreat_rows)

    html_path = generate_html(
        results, taiex, target_date,
        breadth_table_html=breadth_html,
        broker_radar_html=broker_html,
        premarket_signals_html=premarket_html,
        lending_history_html=lending_html,
    )
    print(f"Snapshot PNG: {png_path}")
    print(f"Trend PNG: {trend_png}")
    print(f"HTML: {html_path}")

    summary = build_summary(results, target_date)
    weak_summary = build_weak_summary(results, target_date)
    print()
    print(summary)
    print()
    print(weak_summary)

    # Rerating analysis (β-adjusted, recent window, filter mega-caps)
    print("\n計算 rerating 訊號（β 調整）...", file=sys.stderr)
    rerating = compute_rerating(concepts, results, stocks, taiex_rows=taiex)
    rerating_summary = format_rerating_report(rerating, concepts, top_n=15,
                                              theme_results=results)
    print()
    print(rerating_summary)

    # Business drift analysis (news-based)
    print("\n計算業務轉型訊號（新聞分析）...", file=sys.stderr)
    drifts = detect_drift(concepts, stocks_data=stocks)
    drift_summary = format_drift_report(drifts, concepts, top_n=15)
    print()
    print(drift_summary)
    print()
    print(rerating_summary)

    # Telegram push
    if args.telegram:
        if not bot_token:
            print("[ERROR] 需要 TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        short_caption = f"概念動能 {target_date}  Top 3: "
        for r in results[:3]:
            short_caption += f"{r['name_zh']}({r['sustainability_score']:.0f}) "

        print("推送 Snapshot PNG...", file=sys.stderr)
        ok1 = send_telegram_photo(png_path, short_caption, bot_token, args.chat_id)
        time.sleep(1)

        if trend_png:
            print("推送 Trend PNG...", file=sys.stderr)
            trend_caption = f"概念動能 3 個月趨勢 {target_date}"
            ok_trend = send_telegram_photo(trend_png, trend_caption, bot_token, args.chat_id)
            time.sleep(1)
        else:
            ok_trend = True

        print("推送強勢族群文字摘要...", file=sys.stderr)
        ok2 = send_telegram_text(summary, bot_token, args.chat_id)
        time.sleep(1)

        print("推送弱勢族群摘要...", file=sys.stderr)
        ok3 = send_telegram_text(weak_summary, bot_token, args.chat_id)
        time.sleep(1)

        print("推送族群點火警示...", file=sys.stderr)
        ignition_summary = build_ignition_summary(
            results, target_date,
            datetime.now().strftime("%Y%m%d"))
        ok_ignition = send_telegram_text(
            ignition_summary, bot_token, args.chat_id)
        time.sleep(1)

        print("推送 rerating 摘要...", file=sys.stderr)
        ok4 = send_telegram_text(rerating_summary, bot_token, args.chat_id)
        time.sleep(1)

        print("推送業務轉型摘要...", file=sys.stderr)
        ok5 = send_telegram_text(drift_summary, bot_token, args.chat_id)

        if ok1 and ok_trend and ok2 and ok3 and ok4 and ok5:
            print("推送成功")
        else:
            print("部分推送失敗", file=sys.stderr)


if __name__ == "__main__":
    main()
