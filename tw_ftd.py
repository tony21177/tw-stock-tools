#!/usr/bin/env python3
"""
FTD 反彈確認日 (tw_ftd) — 歐尼爾/IBD Follow-Through Day

規則(IBD 口徑):
  1. 市場修正中(收盤自參考高點回檔 ≥ CORR_PCT)
  2. 嘗試反彈 Day 1:修正期間第一根收漲(此前低點=反彈防線 rally_low)
  3. 反彈存活:盤中低點不跌破 rally_low;跌破 → 重新等 Day 1
  4. FTD:反彈第 ≥4 天,單日漲幅 ≥ FTD_PCT(1.7%,舊版 1.25%)
     且 量 > 前一日(台股用成交金額,美股用成交量)→ 確認可能轉上升趨勢
  5. 失敗:FTD 後跌破 rally_low(歷史約 25-30% 失敗)

指數:加權 TAIEX(FinMind,2004 起)、S&P500 ^GSPC、Nasdaq ^IXIC(Yahoo 25y)。
內建回測:全歷史 FTD 事件 → 失敗率(FAIL_WIN 內跌破防線)+ 後續 H20/H60 報酬
vs 對照組。頁面顯示各指數當前狀態(修正中/嘗試反彈第N天/FTD確認)+ 歷史事件表。

用法:
  tw_ftd.py --build              # 抓資料+偵測+回測+寫 cache
  tw_ftd.py --build --telegram   # 同上,「今日新 FTD」才推(有去重)
  tw_ftd.py --html               # debug 網頁
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
LATEST = os.path.join(CACHE, "ftd_latest.json")
PUSHED = os.path.join(CACHE, "ftd_pushed.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

CORR_PCT = 6.0     # 修正門檻:自參考高點收盤回檔 ≥6% 進入「修正中」
FTD_PCT = 1.7      # FTD 單日漲幅門檻%(IBD 現行 1.7,舊版 1.25)
MIN_DAY = 4        # 反彈第 ≥4 天才算 FTD
FAIL_WIN = 25      # 回測:FTD 後 N 交易日內跌破防線 = 失敗

INDICES = [
    ("TAIEX", "加權指數", "finmind"),
    ("GSPC", "S&P 500", "yahoo:^GSPC"),
    ("IXIC", "Nasdaq", "yahoo:^IXIC"),
]


# ── 資料 ────────────────────────────────────────────────
def _fetch_taiex(token: str, start: str = "2004-01-01") -> list[dict]:
    p = {"dataset": "TaiwanStockPrice", "data_id": "TAIEX",
         "start_date": start, "token": token}
    req = urllib.request.Request(FINMIND + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        rows = json.load(r).get("data", [])
    out = []
    for r in rows:
        if not (r.get("close") and r.get("min") and r.get("max")):
            continue
        out.append({"date": r["date"], "close": r["close"], "low": r["min"],
                    "vol": r.get("Trading_money") or 0})   # 台股量能=成交金額
    return out


def _fetch_yahoo(symbol: str, rng: str = "25y") -> list[dict]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range={rng}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    r = data["chart"]["result"][0]
    ts = r.get("timestamp", [])
    q = r.get("indicators", {}).get("quote", [{}])[0]
    out = []
    for i, t in enumerate(ts):
        c = q.get("close", [])[i] if i < len(q.get("close", [])) else None
        lo = q.get("low", [])[i] if i < len(q.get("low", [])) else None
        v = q.get("volume", [])[i] if i < len(q.get("volume", [])) else None
        if c is None or lo is None:
            continue
        out.append({"date": datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                    "close": c, "low": lo, "vol": v or 0})
    return out


# ── FTD 狀態機 ──────────────────────────────────────────
def detect(days: list[dict]) -> dict:
    """走全歷史。回傳 {events:[...], status:{...}}。
    events: {date, i, rally_day, pct, vol_ratio, rally_low, corr_peak, corr_depth}
    status: 目前狀態(uptrend/correction/rally)+ context。"""
    if len(days) < 30:
        return {"events": [], "status": None}
    refpeak = days[0]["close"]
    refpeak_date = days[0]["date"]
    state = "uptrend"
    corr_low = None
    corr_low_date = None
    rally_day = 0
    rally_low = None
    rally_start = None
    events = []
    last_ftd = None
    for i in range(1, len(days)):
        d = days[i]
        c, lo, v = d["close"], d["low"], d["vol"]
        pc, pv = days[i - 1]["close"], days[i - 1]["vol"]
        if state == "uptrend":
            if c > refpeak:
                refpeak, refpeak_date = c, d["date"]
            elif c <= refpeak * (1 - CORR_PCT / 100):
                state = "correction"
                corr_low, corr_low_date = lo, d["date"]
                rally_day = 0
        else:
            if c > refpeak:                      # 收復前高:修正結束(無 FTD)
                state = "uptrend"
                refpeak, refpeak_date = c, d["date"]
                continue
            if state == "correction":
                if lo < corr_low:
                    corr_low, corr_low_date = lo, d["date"]
                if c > pc:                       # Day 1
                    state = "rally"
                    rally_day = 1
                    rally_low = min(corr_low, lo)
                    rally_start = d["date"]
            elif state == "rally":
                if lo < rally_low:               # 跌破防線 → 反彈失敗重來
                    state = "correction"
                    corr_low, corr_low_date = lo, d["date"]
                    rally_day = 0
                    continue
                rally_day += 1
                pct = (c / pc - 1) * 100
                if (rally_day >= MIN_DAY and pct >= FTD_PCT
                        and v > 0 and pv > 0 and v > pv):
                    ev = {"date": d["date"], "i": i, "rally_day": rally_day,
                          "pct": round(pct, 2), "vol_ratio": round(v / pv, 2),
                          "rally_low": rally_low, "rally_start": rally_start,
                          "corr_peak": refpeak,
                          "corr_depth": round((corr_low / refpeak - 1) * 100, 1)}
                    events.append(ev)
                    last_ftd = ev
                    state = "uptrend"
                    refpeak, refpeak_date = c, d["date"]   # 後續以 FTD 日重新起算
    # 目前狀態
    today = days[-1]
    dd = (today["close"] / refpeak - 1) * 100
    status = {
        "state": state, "date": today["date"], "close": today["close"],
        "refpeak": refpeak, "refpeak_date": refpeak_date,
        "drawdown": round(dd, 1),
        "corr_low": corr_low, "corr_low_date": corr_low_date,
        "rally_day": rally_day, "rally_low": rally_low,
        "rally_start": rally_start,
        "last_ftd": ({"date": last_ftd["date"], "pct": last_ftd["pct"]}
                     if last_ftd else None),
    }
    return {"events": events, "status": status}


def evaluate(days: list[dict], events: list[dict]) -> dict:
    """回測:每個 FTD 事件 → 失敗(FAIL_WIN 內 low<rally_low)+ H20/H60 報酬。
    對照組=所有日的 H20/H60。"""
    closes = [d["close"] for d in days]
    lows = [d["low"] for d in days]
    for ev in events:
        i = ev["i"]
        fail = False
        fail_day = None
        for j in range(i + 1, min(i + 1 + FAIL_WIN, len(days))):
            if lows[j] < ev["rally_low"]:
                fail, fail_day = True, days[j]["date"]
                break
        ev["failed"] = fail
        ev["fail_date"] = fail_day
        for h in (20, 60):
            ev[f"h{h}"] = (round((closes[i + h] / closes[i] - 1) * 100, 1)
                           if i + h < len(closes) else None)
    def _st(vals):
        vals = [v for v in vals if v is not None]
        n = len(vals)
        if not n:
            return {"n": 0}
        mean = sum(vals) / n
        win = sum(1 for v in vals if v > 0) / n * 100
        return {"n": n, "mean": round(mean, 2), "win": round(win, 1)}
    base20 = [(closes[i + 20] / closes[i] - 1) * 100
              for i in range(len(closes) - 20)]
    base60 = [(closes[i + 60] / closes[i] - 1) * 100
              for i in range(len(closes) - 60)]
    done = [e for e in events if e["h20"] is not None]
    return {
        "n_ftd": len(events),
        "fail_rate": (round(sum(1 for e in events if e["failed"])
                            / len(events) * 100, 1) if events else None),
        "h20": _st([e["h20"] for e in done]),
        "h60": _st([e["h60"] for e in done]),
        "base20": _st(base20), "base60": _st(base60),
    }


# ── build ───────────────────────────────────────────────
def build(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    out = {"as_of": datetime.now().strftime("%Y-%m-%d %H:%M"), "indices": []}
    for idx_id, name, src in INDICES:
        try:
            if src == "finmind":
                if not token:
                    continue
                days = _fetch_taiex(token)
            else:
                days = _fetch_yahoo(src.split(":")[1])
        except Exception as e:
            out["indices"].append({"id": idx_id, "name": name,
                                   "error": f"{type(e).__name__}: {e}"})
            continue
        det = detect(days)
        bt = evaluate(days, det["events"])
        out["indices"].append({
            "id": idx_id, "name": name,
            "window": f'{days[0]["date"]}~{days[-1]["date"]}',
            "status": det["status"],
            "events": [{k: v for k, v in e.items() if k != "i"}
                       for e in det["events"]][-20:],   # 頁面近 20 筆
            "backtest": bt,
        })
    return out


def build_and_save(token: str | None = None) -> dict:
    data = build(token)
    os.makedirs(CACHE, exist_ok=True)
    tmp = LATEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, LATEST)
    return data


# ── 推播(僅「最新資料日=FTD 日」且未推過)────────────────
def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(TG_API_URL.format(token=bot_token), data=body,
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print(f"Telegram 失敗: {e}", file=sys.stderr)
        return False


def push_new_ftd(data: dict, bot_token: str, chat_id: str):
    try:
        with open(PUSHED, encoding="utf-8") as f:
            pushed = json.load(f)
    except Exception:
        pushed = {}
    sent = False
    for idx in data["indices"]:
        evs = idx.get("events") or []
        st = idx.get("status") or {}
        if not evs:
            continue
        last = evs[-1]
        if last["date"] != st.get("date"):        # 只推「今天剛發生」的 FTD
            continue
        if pushed.get(idx["id"]) == last["date"]:
            continue
        bt = idx.get("backtest", {})
        msg = "\n".join([
            f"🚀 FTD 反彈確認日 — {idx['name']} {last['date']}",
            "",
            f"漲幅 +{last['pct']:.2f}%(量增 {last['vol_ratio']:.2f}x)",
            f"嘗試反彈第 {last['rally_day']} 天(起點 {last['rally_start']},"
            f" 防線 {last['rally_low']:,.0f})",
            f"本波修正深度 {last['corr_depth']}%",
            "",
            f"歷史({bt.get('n_ftd', 0)} 次):失敗率 {bt.get('fail_rate')}%,"
            f" 20日後勝率 {bt.get('h20', {}).get('win')}%"
            f" 平均 {bt.get('h20', {}).get('mean')}%",
            "守住防線前別重壓;跌破防線=FTD 失敗停損訊號。",
            "⚠ 觀察工具非買賣訊號。詳: http://localhost:5000/ftd",
        ])
        if send_telegram(msg, bot_token, chat_id):
            pushed[idx["id"]] = last["date"]
            sent = True
            print(f"已推 {idx['name']} FTD {last['date']}")
    if sent:
        with open(PUSHED, "w", encoding="utf-8") as f:
            json.dump(pushed, f)


# ── 呈現 ────────────────────────────────────────────────
def render_html(data: dict) -> str:
    import html as _h
    nav = ('<nav><a href="/">← 大盤 dashboard</a> '
           '<a href="/market-tomorrow">🌏 明天大盤預期</a> '
           '<a href="/option-flow">📊 選擇權法人</a> '
           '<a href="/margin-scan">💥 融資斷頭潮</a> '
           '<a href="/seasonality">📅 月份季節性</a></nav>')
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  table{width:100%;border-collapse:collapse;font-size:.85em;}
  th,td{padding:4px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th{background:#eef2f7;} th:first-child,td:first-child{text-align:left;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;}
  .st{display:inline-block;padding:2px 10px;border-radius:4px;font-weight:600;}
  .st-up{background:#eafaf0;color:#1e7d45;border:1px solid #bfe8cf;}
  .st-corr{background:#fdeeee;color:#b03a2e;border:1px solid #f0c2c2;}
  .st-rally{background:#fff8e1;color:#9a6d00;border:1px solid #eed9a0;}
  .ok{color:#1e7d45;} .bad{color:#b03a2e;}
  .small{font-size:.85em;color:#666;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>FTD 反彈確認日</title>{css}</head><body>{nav}'
            f'<h1>🚀 FTD 反彈確認日(歐尼爾 Follow-Through Day)</h1>')
    body = []
    for idx in data.get("indices", []):
        if idx.get("error"):
            body.append(f'<section><h3>{_h.escape(idx["name"])}</h3>'
                        f'⚠ {_h.escape(idx["error"])}</section>')
            continue
        st = idx["status"]
        state = st["state"]
        if state == "uptrend":
            lf = st.get("last_ftd")
            extra = (f'(上次 FTD {lf["date"]} +{lf["pct"]}%)' if lf else "")
            badge = f'<span class="st st-up">上升趨勢 {extra}</span>'
            detail = (f'參考高點 {st["refpeak"]:,.0f}({st["refpeak_date"]}),'
                      f'現距高點 {st["drawdown"]:+.1f}%'
                      f'(回檔 ≥{CORR_PCT:.0f}% 轉入修正)')
        elif state == "correction":
            badge = '<span class="st st-corr">修正中 — 等嘗試反彈 Day 1(收漲日)</span>'
            detail = (f'高點 {st["refpeak"]:,.0f}({st["refpeak_date"]})→ '
                      f'修正低 {st["corr_low"]:,.0f}({st["corr_low_date"]}),'
                      f'現距高點 {st["drawdown"]:+.1f}%。下一根收漲=Day 1 開始數。')
        else:
            need = max(MIN_DAY - st["rally_day"], 0)
            badge = (f'<span class="st st-rally">嘗試反彈 第 {st["rally_day"]} 天</span>')
            detail = (f'反彈起點 {st["rally_start"]},防線 {st["rally_low"]:,.0f}'
                      f'(盤中跌破=重數)。'
                      + (f'還需 {need} 天後才進入 FTD 觀察窗;'
                         if need > 0 else '已在 FTD 觀察窗內:')
                      + f'單日 +{FTD_PCT}% 且量增 = FTD。現距高點 {st["drawdown"]:+.1f}%。')
        bt = idx["backtest"]
        bt_line = ""
        if bt.get("n_ftd"):
            bt_line = (f'<p class="small">🧪 回測({idx["window"]}):共 <b>{bt["n_ftd"]}</b> 次 FTD,'
                       f'失敗率 <b>{bt["fail_rate"]}%</b>({FAIL_WIN}日內跌破防線);'
                       f'FTD 後 20 日勝率 <b>{bt["h20"]["win"]}%</b>/平均 <b>{bt["h20"]["mean"]:+.1f}%</b>'
                       f'(對照全部日 {bt["base20"]["win"]}%/{bt["base20"]["mean"]:+.1f}%),'
                       f'60 日 {bt["h60"]["win"]}%/{bt["h60"]["mean"]:+.1f}%'
                       f'(對照 {bt["base60"]["win"]}%/{bt["base60"]["mean"]:+.1f}%)。</p>')
        rows = []
        for e in reversed(idx["events"]):
            res = ('<span class="bad">✗ 失敗</span>' if e["failed"]
                   else '<span class="ok">✓ 成功</span>')
            h20 = f'{e["h20"]:+.1f}%' if e["h20"] is not None else "—"
            h60 = f'{e["h60"]:+.1f}%' if e["h60"] is not None else "—"
            rows.append(
                f'<tr><td>{e["date"]}</td><td>+{e["pct"]:.2f}%</td>'
                f'<td>{e["vol_ratio"]:.2f}x</td><td>第{e["rally_day"]}天</td>'
                f'<td>{e["corr_depth"]}%</td><td>{res}'
                f'{("<span class=small>(" + str(e["fail_date"]) + ")</span>") if e["failed"] else ""}</td>'
                f'<td class="{"up" if (e["h20"] or 0) > 0 else "dn"}">{h20}</td>'
                f'<td class="{"up" if (e["h60"] or 0) > 0 else "dn"}">{h60}</td></tr>')
        table = ('<table><thead><tr><th>FTD 日</th><th>漲幅</th><th>量比</th>'
                 '<th>反彈第N天</th><th>修正深度</th><th>結果</th>'
                 '<th>20日後</th><th>60日後</th></tr></thead><tbody>'
                 + "".join(rows) + '</tbody></table>') if rows else \
                '<p class="small">(尚無 FTD 事件)</p>'
        body.append(f'<section><h3>{_h.escape(idx["name"])} '
                    f'<span class="small">{st["date"]}</span></h3>'
                    f'<p>{badge}</p><p class="small">{detail}</p>{bt_line}'
                    f'<h3 style="margin-top:.8em">近 20 次 FTD 事件</h3>{table}</section>')

    glossary = f"""<section class="note">📖 <b>FTD 白話 + 規則</b><br>
• <b>FTD(Follow-Through Day,反彈確認日)</b>:歐尼爾/IBD 的熊市結束確認訊號。
邏輯:底部第一根反彈可能只是跌深反彈,但若反彈能活過幾天、且在<b>第 4 天之後</b>出現
<b>大漲(≥{FTD_PCT}%)+ 量增(高於前一日)</b>,代表機構真金白銀進場 → 修正可能結束。<br>
• <b>流程</b>:修正中(距高點 ≥{CORR_PCT:.0f}%)→ 創低後第一根收漲=<b>嘗試反彈 Day 1</b>
→ 不破反彈防線就一直數 → 第 4 天起等大漲量增日=FTD。<b>盤中跌破防線=重來</b>。<br>
• <b>量</b>:台股用<b>成交金額</b>(台股慣例)、美股用成交量;只比「有沒有比昨天多」。<br>
• <b>怎麼用</b>:FTD ≠ 精準抄底,是「恢復進場的較安全時點」——歷史每個大底幾乎都有 FTD,
但 FTD 出現不保證是底(歷史約 25-30% 失敗,見上方各指數回測)。IBD 用法:FTD 後分批試單,
<b>跌破反彈防線=FTD 失敗、立刻退出</b>;失敗本身也是資訊(真轉強前常見 2-3 次失敗的 FTD)。<br>
• <b>與其他工具搭配</b>:融資斷頭潮(多方投降)+ 選擇權自營收 put(恐慌極值)標記「底部區」,
FTD 確認「反轉啟動」——前兩者找區域、FTD 給進場時機。<br>
⚠ 參數:修正門檻 {CORR_PCT:.0f}%、FTD 門檻 {FTD_PCT}%(IBD 現行;舊版 1.25%)、
第 ≥{MIN_DAY} 天、失敗判定 {FAIL_WIN} 交易日內跌破防線。非買賣訊號。</section>"""

    foot = (f'<p class="small">🕒 每交易日 07:35(抓隔夜美股)+ 21:45(抓台股)更新,'
            f'新 FTD 觸發才推 Telegram · 更新於 {_h.escape(data.get("as_of", ""))}</p>')
    return head + "".join(body) + glossary + foot + '</body></html>'


# ── CLI ─────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()

    if args.html:
        if os.path.exists(LATEST):
            with open(LATEST, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = build()
        sys.stdout.write(render_html(data))
        return

    data = build_and_save()
    for idx in data["indices"]:
        if idx.get("error"):
            print(f"{idx['name']}: ⚠ {idx['error']}")
            continue
        st = idx["status"]
        bt = idx["backtest"]
        state_zh = {"uptrend": "上升趨勢", "correction": "修正中",
                    "rally": f"嘗試反彈第{st['rally_day']}天"}[st["state"]]
        print(f"{idx['name']:8} {st['date']} {state_zh} 距高點{st['drawdown']:+.1f}% "
              f"| 歷史FTD {bt.get('n_ftd')}次 失敗率{bt.get('fail_rate')}%")
    if args.telegram:
        bot = os.environ.get("TG_BOT_TOKEN", "")
        if bot:
            push_new_ftd(data, bot, args.chat_id)
        else:
            print("無 TG_BOT_TOKEN,略過推播", file=sys.stderr)


if __name__ == "__main__":
    main()
