#!/usr/bin/env python3
"""
每日 orchestrator：抓資料 → 分析 → 生成圖表 → 推送 Telegram
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from data_fetcher import fetch_all_concepts, fetch_taiex
from concept_momentum import analyze_all, add_score_history
from concept_charts import generate_png, generate_trend_png, generate_html
from rerating_detector import compute_rerating, format_rerating_report
from business_drift_detector import detect_drift, format_drift_report

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


def build_summary(results: list[dict], target_date: str) -> str:
    """Build main summary: high-momentum concepts with top 5 leaders each."""
    if not results:
        return f"概念動能監控 {target_date}\n\n無資料"

    lines = [f"概念動能監控 {target_date}"]
    lines.append("高動能族群（評分 ≥70）+ 領漲 Top 5")
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
            if leaders:
                for L in leaders[:5]:
                    lines.append(
                        f"   • {L['code']} {L['name'][:20]}  "
                        f"5d:{L['ret_5d']:+.1f}% 20d:{L['ret_20d']:+.1f}%"
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

    # Charts
    print("【步驟 5/5】生成圖表...", file=sys.stderr)
    target_date = datetime.now().strftime("%Y-%m-%d")
    png_path = generate_png(results, target_date)
    trend_png = generate_trend_png(results, target_date)
    html_path = generate_html(results, taiex, target_date)
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
    rerating_summary = format_rerating_report(rerating, concepts, top_n=15)
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
