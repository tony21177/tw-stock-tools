#!/usr/bin/env python3
"""每日權證量能觀察 → LINE 推播.

⚠ 此訊號經 2026-07-21 回測證實**無預測 edge**（見 warrant_signal_backtest）。
推播僅為觀察用途，訊息內含無 edge 免責。收件者由 warrant_push_config.json
的 line_recipients 決定（沿用 line_push 共用模組）。

用法:
  warrant_push.py               # 讀最新日檔 → 推播
  warrant_push.py --dry-run     # 印訊息不推
  warrant_push.py --top 8       # Top N 爆量股（預設 8）

cron (18:40 平日，warrant_flow 18:30 抓完之後):
  40 18 * * 1-5 ... is_trading_day.py && LINE_CHANNEL_ID=.. LINE_CHANNEL_SECRET=.. \
    FINMIND_TOKEN=.. python3 warrant_push.py >> warrant_push.log 2>&1
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import line_push  # noqa: E402

FLOW_DIR = os.path.join(HERE, "cache", "warrant_flow")
CONFIG = os.path.join(HERE, "warrant_push_config.json")
YI = 1e8
_DIR = {"bull": "🔥偏多", "bear": "❄偏空", "neutral": "⚡中性"}


def _log(msg: str) -> None:
    from datetime import datetime
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def load_recipients() -> list[str]:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f).get("line_recipients", [])
    except Exception:
        return []


def build_message(rows: list[dict], day: dict, top: int = 8) -> str:
    date = day.get("date", "")
    date_fmt = f"{date[:4]}/{date[4:6]}/{date[6:]}" if len(date) == 8 else date
    lines = [f"🎰 權證量能觀察 {date_fmt}",
             "⚠ 回測無預測 edge、僅觀察用（非買賣訊號；空方訊號失效、"
             "多方爆量端反而偏弱）",
             "━━━━━━━━━━━━",
             "當日權證爆量現股（總額 ≥ 近20日均2倍）:"]
    unders = day.get("underlyings", {})
    if not rows:
        lines.append("（今日無爆量現股）")
    for r in rows[:top]:
        u = unders.get(r["code"], {})
        issuers = sorted((u.get("issuers") or {}).items(),
                         key=lambda x: -x[1])[:2]
        iss = "、".join(n for n, _ in issuers) or "—"
        lines.append(
            f"  {r['code']} {_DIR.get(r['direction'], '—')} "
            f"爆量{r['surge_ratio']:.1f}x 權證{r['warrant_turnover']/YI:.2f}億 "
            f"認購佔比{r['bull_share']:.0%}(Δ{r['bull_share_delta']:+.0%}) "
            f"發行:{iss}")
    lines.append("\n詳見網頁 /warrant-signal")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", type=int, default=8)
    args = ap.parse_args()

    import warrant_signal as ws
    files = sorted(glob.glob(os.path.join(FLOW_DIR, "*.json")))[-60:]
    days = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                days.append(json.load(fh))
        except Exception:
            continue
    if not days:
        _log("無 warrant_flow 日檔，跳過")
        return
    rows = ws.build_signal_rows(days)
    text = build_message(rows, days[-1], top=args.top)

    if args.dry_run:
        _log(f"[dry-run] {len(text)} 字元:\n{text}")
        return
    token = line_push.resolve_token()
    recipients = load_recipients()
    if not (token and recipients):
        _log("[WARN] LINE 憑證/收件者未設定，不推播")
        return
    for r in recipients:
        ok = line_push.push_text(text, token, r)
        _log(f"推 {r[:6]}…: {'✅' if ok else '❌'}")


if __name__ == "__main__":
    main()
