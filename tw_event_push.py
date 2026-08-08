#!/usr/bin/env python3
"""
事件推播 — 每日挑當天「新的高價值事件」推 Telegram(睏霸數錢)。

高價值事件(按重要性):
  🎯 公開收購(法定提前 5 日,溢價行情)
  🤝 取得股權/策略投資(含被取得標的,標的即上市櫃時=連動選股)
  ⭐ 大額事前申報轉讓(≥300 張,董監要賣/協議轉讓)
  📈 本公司現增/私募/CB(直接稀釋)
  📝 重大契約/大單

去重:pushed_events.json 記已推事件 key,只推沒推過的。
訊號觸發制 —— 當天無高價值新事件則靜默。20:15 cron(接在 20:10 事件抓取後)。

用法:
  python3 tw_event_push.py --dry-run
  python3 tw_event_push.py --telegram
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

DEFAULT_CHAT_ID = "-5229750819"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"
PUSHED = os.path.join(HERE, "concept_momentum", "cache", "events", "pushed_events.json")

# 要推的事件類型與標題
PUSH_TYPES = {
    "tender_offer": "🎯 公開收購",
    "strategic_buy": "🤝 取得股權",
    "capital_increase": "📈 現增/私募/CB",
    "major_contract": "📝 重大契約",
}


def _load_pushed() -> set:
    if os.path.exists(PUSHED):
        try:
            return set(json.load(open(PUSHED)))
        except Exception:
            return set()
    return set()


def _save_pushed(keys: set):
    os.makedirs(os.path.dirname(PUSHED), exist_ok=True)
    # 只留最近 2000 筆避免無限膨脹
    json.dump(sorted(keys)[-2000:], open(PUSHED, "w"), ensure_ascii=False)


def _ekey(e) -> str:
    return f"{e['code']}|{e['date']}|{e['subject'][:30]}"


def build_message(latest_only: bool = True) -> tuple[str | None, set]:
    import tw_event_data as ed
    import event_hub
    name, rev = event_hub._names()
    mat = ed.load_material(months=2)
    if not mat:
        return None, set()
    latest = mat[0]["date"]
    pushed = _load_pushed()
    new_keys = set()

    # 重訊類高價值事件(當日 + 未推過)
    buckets = {t: [] for t in PUSH_TYPES}
    for e in mat:
        if latest_only and e["date"] != latest:
            continue
        if e["type"] not in PUSH_TYPES:
            continue
        k = _ekey(e)
        if k in pushed:
            continue
        buckets[e["type"]].append(e)
        new_keys.add(k)

    # 大額事前申報轉讓(≥300 張)
    xfers = []
    for x in (ed.load_xfer(months=1) or []):
        if x["shares"] < 300000:
            continue
        if latest_only and x["date"] != latest:
            continue
        k = f"xfer|{x['code']}|{x['date']}|{x['person']}|{x['shares']}"
        if k in pushed:
            continue
        xfers.append(x)
        new_keys.add(k)

    if not any(buckets.values()) and not xfers:
        return None, set()

    L = [f"🎯 事件雷達 {latest[4:6]}/{latest[6:]}", "━━━━━━━━━━━━"]
    for t, label in PUSH_TYPES.items():
        evs = buckets[t]
        if not evs:
            continue
        L.append(f"{label}:")
        for e in evs[:6]:
            line = f"  {e['code']} {e['name']}"
            if t == "strategic_buy":
                tgt, tcode = event_hub._extract_target(e["subject"], rev)
                if tgt:
                    line += f" → 取得【{tgt}{('/'+tcode) if tcode else ''}】"
            L.append(line)
            L.append(f"    {e['subject'][:46]}")
    if xfers:
        L.append("⭐ 大額事前申報轉讓(≥300張,提前3日):")
        for x in xfers[:6]:
            L.append(f"  {x['code']} {x['name']} {x['who']} "
                     f"{x['shares']/1000:,.0f}張 {x['method']}")
    L.append("━━━━━━━━━━━━")
    from site_nav import public_url
    L.append(f"詳細:{public_url('/event-trading')}")
    L.append("⚠ 事件彙整非買賣訊號;超額報酬多未回測")
    return "\n".join(L), new_keys


def send_tg(text, chat_id):
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        print("缺 TG_BOT_TOKEN")
        return False
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(TG_API.format(token=token), data, timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print("TG error:", e)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chat", default=DEFAULT_CHAT_ID)
    ap.add_argument("--all-days", action="store_true",
                    help="不限當日(首次測試用)")
    a = ap.parse_args()

    # 先確保事件資料最新
    try:
        import tw_event_data as ed
        ed.update_daily()
    except Exception as e:
        print("event data update err:", e)

    msg, new_keys = build_message(latest_only=not a.all_days)
    if msg is None:
        print("無高價值新事件,靜默")
        return
    print(msg)
    if a.telegram and not a.dry_run:
        if send_tg(msg, a.chat):
            print("TG: ok")
            pushed = _load_pushed() | new_keys
            _save_pushed(pushed)
        else:
            print("TG: fail")


if __name__ == "__main__":
    main()
