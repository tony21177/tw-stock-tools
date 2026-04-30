#!/usr/bin/env python3
"""
每日兩層篩選工作流 (cron 19:00 Mon-Fri)

Layer 1: tw_turnaround_screener.py
  毛利率改善 + 量能放大 + 借券回補 + 季線多頭 → 數百檔 → 數檔 candidates

Layer 2: tw_limitup_signal.py 對 Layer 1 候選做 ABCD 接力型評分
  A 漲停接力 / B 借券回補 / C 籌碼集中 / D 量能蓄勢
  顯示分數分級 (4/4 / 3/4 / 2/4 / ≤1/4)，協助判斷哪些 Layer 1 候選明日可能突破

兩層結果都推送 Telegram，使用者隔日可用實際漲跌「後照鏡」驗證 Layer 2 嚴格度，
逐步調整 ABCD 訊號條件。

Usage:
  python3 tw_daily_screen.py                # 預設模式：兩層都跑、推送 TG
  python3 tw_daily_screen.py --no-tg        # 不推 TG (測試)
  python3 tw_daily_screen.py --layer2-min 3 # Layer 2 只列 ≥3/4 (更嚴格)

環境變數:
  TG_BOT_TOKEN, FINMIND_TOKEN
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCREENER = os.path.join(HERE, "tw_turnaround_screener.py")
SIGNAL = os.path.join(HERE, "tw_limitup_signal.py")
DEFAULT_CHAT_ID = "-5229750819"


def main():
    p = argparse.ArgumentParser(description="每日兩層股票篩選")
    p.add_argument("--no-tg", action="store_true", help="不推 Telegram (測試)")
    p.add_argument("--layer2-min", type=int, default=2,
                   help="Layer 2 最低分數 (預設 2/4，cron 用 2 顯示完整分級)")
    p.add_argument("--bot-token", default=os.environ.get("TG_BOT_TOKEN", ""))
    p.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    p.add_argument("--token", default=os.environ.get("FINMIND_TOKEN", ""),
                   help="FinMind token")
    p.add_argument("--universe", default="all",
                   help="screener universe (all / concepts / 逗號代號)")
    args = p.parse_args()

    use_tg = not args.no_tg
    if use_tg and not args.bot_token:
        print("[ERROR] 需要 TG_BOT_TOKEN", file=sys.stderr)
        sys.exit(1)

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n🔁 每日兩層篩選 {today}\n", file=sys.stderr)

    # ====== Layer 1 ======
    json_path = tempfile.mktemp(suffix=".json", prefix="layer1_")
    cmd1 = [
        sys.executable, SCREENER,
        "--token", args.token,
        "--universe", args.universe,
        "--quiet",
        "--json-out", json_path,
    ]
    if use_tg:
        cmd1.extend(["--telegram", "--bot-token", args.bot_token,
                     "--chat-id", args.chat_id])
    print(f"▶️  Layer 1: tw_turnaround_screener ({args.universe})", file=sys.stderr)
    r1 = subprocess.run(cmd1, capture_output=False)
    if r1.returncode != 0:
        print(f"[ERROR] Layer 1 失敗 (exit {r1.returncode})", file=sys.stderr)
        sys.exit(2)

    # Read Layer 1 candidates
    try:
        with open(json_path) as f:
            layer1 = json.load(f)
    except FileNotFoundError:
        print("[INFO] Layer 1 無候選，跳過 Layer 2", file=sys.stderr)
        if use_tg:
            _push_text(f"📅 {today} Layer 1 無候選 — 不執行 Layer 2",
                       args.bot_token, args.chat_id)
        return

    if not layer1:
        print("[INFO] Layer 1 無候選，跳過 Layer 2", file=sys.stderr)
        if use_tg:
            _push_text(f"📅 {today} Layer 1 無候選 — 不執行 Layer 2",
                       args.bot_token, args.chat_id)
        os.unlink(json_path)
        return

    print(f"\n✅ Layer 1: {len(layer1)} 檔候選\n", file=sys.stderr)

    # ====== Layer 2 ======
    print(f"▶️  Layer 2: tw_limitup_signal (ABCD on {len(layer1)} codes)", file=sys.stderr)
    cmd2 = [
        sys.executable, SIGNAL,
        "--token", args.token,
        "--codes-file", json_path,
        "--min-score", str(args.layer2_min),
        "--header", f"🎯 Layer 2 — ABCD 接力型訊號 (Layer 1 → 篩 {len(layer1)} 檔)",
        "--quiet",
    ]
    if use_tg:
        cmd2.extend(["--telegram", "--bot-token", args.bot_token,
                     "--chat-id", args.chat_id])
    r2 = subprocess.run(cmd2, capture_output=False)
    if r2.returncode != 0:
        print(f"[ERROR] Layer 2 失敗 (exit {r2.returncode})", file=sys.stderr)

    # Cleanup
    try:
        os.unlink(json_path)
    except FileNotFoundError:
        pass

    print("\n✅ 完成", file=sys.stderr)


def _push_text(text: str, bot_token: str, chat_id: str) -> None:
    import urllib.parse, urllib.request
    try:
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
    except Exception as e:
        print(f"[ERROR] TG: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
