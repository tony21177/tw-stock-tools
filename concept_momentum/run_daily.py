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
from concept_momentum import analyze_all
from concept_charts import generate_png, generate_html

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
    """Build text summary for Telegram caption + detail message."""
    if not results:
        return f"概念動能監控 {target_date}\n\n無資料"

    lines = [f"概念動能監控 {target_date}"]
    lines.append("高動能（評分 ≥70，資金持續流入）")
    lines.append("━━━━━━━━━━")
    high = [r for r in results if r["sustainability_score"] >= 70]
    if not high:
        lines.append("（無）")
    else:
        for i, r in enumerate(high[:10], 1):
            lines.append(
                f"{i}. {r['name_zh']}  評分 {r['sustainability_score']:.0f}\n"
                f"   20d: {r['ret_20d']:+.1f}%  廣度 {r['breadth_20d']:.0f}%  "
                f"量比 {r['volume_ratio']:.1f}x  RS {r['rs_20d']:+.1f}%  持續 {r['duration']}天"
            )

    lines.append("")
    lines.append("弱勢（評分 <30，資金流出）")
    lines.append("━━━━━━━━━━")
    low = [r for r in results if r["sustainability_score"] < 30]
    if not low:
        lines.append("（無）")
    else:
        for r in low[:5]:
            lines.append(
                f"• {r['name_zh']}  評分 {r['sustainability_score']:.0f}  "
                f"20d: {r['ret_20d']:+.1f}%  RS {r['rs_20d']:+.1f}%"
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
    print("【步驟 3/4】計算動能指標...", file=sys.stderr)
    results = analyze_all(concepts, stocks, taiex)

    # Charts
    print("【步驟 4/4】生成圖表...", file=sys.stderr)
    target_date = datetime.now().strftime("%Y-%m-%d")
    png_path = generate_png(results, target_date)
    html_path = generate_html(results, taiex, target_date)
    print(f"PNG: {png_path}")
    print(f"HTML: {html_path}")

    # Summary text
    summary = build_summary(results, target_date)
    print()
    print(summary)

    # Telegram push
    if args.telegram:
        if not bot_token:
            print("[ERROR] 需要 TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        # Send photo with short caption
        short_caption = f"概念動能 {target_date}  Top 3: "
        for r in results[:3]:
            short_caption += f"{r['name_zh']}({r['sustainability_score']:.0f}) "
        print("推送 PNG...", file=sys.stderr)
        ok1 = send_telegram_photo(png_path, short_caption, bot_token, args.chat_id)
        time.sleep(1)
        print("推送文字摘要...", file=sys.stderr)
        ok2 = send_telegram_text(summary, bot_token, args.chat_id)
        if ok1 and ok2:
            print("推送成功")
        else:
            print("部分推送失敗", file=sys.stderr)


if __name__ == "__main__":
    main()
