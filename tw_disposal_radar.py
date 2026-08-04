#!/usr/bin/env python3
"""
處置雷達每日 cron(20:20):
  1. 更新當月注意/處置公告快取(tw_disposal_data)
  2. 組訊號:11 款門檻雷達 ≥70%、瀕臨處置(連4+/10日5+/30日10+)、即將解禁(≤2日)
  3. 任一非空才推 Telegram(訊號觸發制,無訊號日靜默)

用法:
  python3 tw_disposal_radar.py --dry-run     # 只印不推
  python3 tw_disposal_radar.py --telegram    # 推播(需 TG_BOT_TOKEN)
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

DEFAULT_CHAT_ID = "-5229750819"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def build_message() -> str | None:
    import disposal_rules as dr
    radar_rows, asof = dr.build_monitor_rows()
    att_rows, _ = dr.build_attention_status()

    hot = [r for r in radar_rows if (r.get("used") or 0) >= 70]
    near = [r for r in att_rows if not r["disposed"]
            and (r["streak"] >= 4 or r["n10"] >= 5 or r["n30"] >= 10)]
    releasing = [r for r in att_rows if r["disposed"]
                 and r.get("disp_left") is not None and r["disp_left"] <= 2]
    if not (hot or near or releasing):
        return None

    L = [f"⚖ 處置雷達 {asof}", "━━━━━━━━━━━━"]
    if hot:
        L.append("🔥 11款門檻雷達(千金股 6日起迄已用門檻%):")
        for r in hot[:8]:
            arrow = "▲" if r["diff"] > 0 else "▼"
            L.append(f"  {r['code']} {r['name']} {r['close']:,.0f} "
                     f"{arrow}{abs(r['diff']):,.0f}元 用掉{r['used']:.0f}%"
                     f"(門檻{r['th']})")
        L.append("  ⚠ 再約一根漲/跌停就觸發注意第11款")
    if near:
        L.append("🚨 瀕臨處置(注意累積進度):")
        for r in near[:8]:
            L.append(f"  {r['code']} {r['name']} 連{r['streak']}/5 "
                     f"10日{r['n10']}/6 30日{r['n30']}/12")
    if releasing:
        L.append("🔓 即將解禁(≤2日):")
        for r in releasing[:8]:
            end = r["disp_end"]
            L.append(f"  {r['code']} {r['name']} {end[4:6]}/{end[6:]} 解禁")
        L.append("  回測:解禁是彩券(H20超額+3.7%但中位-2.3%勝率48%);"
                 "二次+處置解禁較強(+4.6%)")
    L.append("━━━━━━━━━━━━")
    from site_nav import public_url
    L.append(f"詳細:{public_url('/disposal-rules')}")
    return "\n".join(L)


def send_tg(text: str, chat_id: str) -> bool:
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        print("缺 TG_BOT_TOKEN")
        return False
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(TG_API.format(token=token), data,
                                    timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print("TG error:", e)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chat", default=DEFAULT_CHAT_ID)
    args = ap.parse_args()

    # 1. 更新當月公告
    import tw_disposal_data as dd
    from datetime import datetime
    print(dd.update_month(datetime.now().strftime("%Y%m"), force=True))

    # 2-3. 組訊號並推
    msg = build_message()
    if msg is None:
        print("無訊號,靜默")
        return
    print(msg)
    if args.telegram and not args.dry_run:
        ok = send_tg(msg, args.chat)
        print("TG:", "ok" if ok else "fail")


if __name__ == "__main__":
    main()
