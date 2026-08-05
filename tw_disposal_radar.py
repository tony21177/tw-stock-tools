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
    import tw_disposal_analysis as ta
    # 先更新原始收盤快取(需 FINMIND_TOKEN;缺時用既有快取),再算所有訊號
    tok = os.environ.get("FINMIND_TOKEN")
    if tok:
        try:
            ta.update_raw_closes(tok)
        except Exception as e:
            print("raw update err:", e)
    radar_rows, asof = dr.build_monitor_rows()
    att_rows, _ = dr.build_attention_status()
    crosses = [e for e in ta.recent_tier_events(1)]

    hot = [r for r in radar_rows if (r.get("used") or 0) >= 70]
    near = [r for r in att_rows if not r["disposed"]
            and (r["streak"] >= 4 or r["n10"] >= 5 or r["n30"] >= 10)]
    releasing = [r for r in att_rows if r["disposed"]
                 and r.get("disp_left") is not None and r["disp_left"] <= 2]
    if not (hot or near or releasing or crosses):
        return None

    L = [f"⚖ 處置雷達 {asof}", "━━━━━━━━━━━━"]
    if crosses:
        from disposal_rules import _name_lookup
        nm = _name_lookup()
        L.append("📈 整數關卡跨越(回測 H20 +10.3%/勝率61%,中位也贏對照):")
        for e in crosses[:6]:
            L.append(f"  {e['code']} {nm(e['code'])} 首次站上 {e['tier']:,}"
                     f"(收 {e['close']:,.0f})")
    fz = [w for w in ta.free_zone_watch() if w["gap_pct"] <= 3.0]
    if fz:
        L.append("🎯 千元免費區候補(跨1000無監管摩擦,見/disposal-rules解讀8):")
        from disposal_rules import _name_lookup as _nl
        _n = _nl()
        for w in fz[:5]:
            kind = "突破型" if w["first_time"] else "收復型"
            L.append(f"  {w['code']} {_n(w['code'])} {w['close']:,.0f} "
                     f"差{w['gap_pct']}% 6日{w['mom6']:+.1f}% {kind}")
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
        import hashlib
        h = hashlib.md5(msg.encode()).hexdigest()
        hp = os.path.join(HERE, "concept_momentum", "cache", "disposal",
                          "last_push.md5")
        if os.path.exists(hp) and open(hp).read().strip() == h:
            print("內容與上次推播相同,跳過")
            return
        ok = send_tg(msg, args.chat)
        print("TG:", "ok" if ok else "fail")
        if ok:
            open(hp, "w").write(h)


if __name__ == "__main__":
    main()
