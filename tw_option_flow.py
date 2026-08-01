#!/usr/bin/env python3
"""
選擇權法人籌碼觀察 (tw_option_flow) — 「自營收 put」轉多訊號

觀察邏輯(社群實戰口徑):台指選擇權(TXO)自營商當 put「賣方」大量收權利金
= 造市者/專業戶賭「不跌」,沒事不會收那麼多 → 轉多觀察訊號。
  當日淨收權利金 = short_deal_amount − long_deal_amount(正=淨賣方/收錢)
  例 2026-07-30:自營賣權 賣8.96億 − 買7.26億 = 淨收 +1.70億(群訊「put 回收 2e」)

訊號(已回測 2020-2026,見 tw_option_flow_backtest.py:隔日無 edge、
5~10 日反彈傾向 —— 恐慌/波動事件標記,非隔日方向):
  🟢 轉多觀察:自營 put 淨收 ≥ 1 億 且 ≥ 近 60 交易日淨收的 P90(異常放大)
  🔴 避險/偏空觀察:自營 put 淨買 ≤ −1 億 且 ≤ P10(大買 put 避險)

頁面另列:自營 call 淨收、外資 put/call 淨收(對照)、自營 put 未平倉淨額、
當日加權指數漲跌%(context)。

資料:FinMind TaiwanOptionInstitutionalInvestors(TXO,三大法人×買賣權,
  金額單位千元;每交易日盤後公布)+ TaiwanStockPrice TAIEX(指數 context)。
⚠ caveat:自營商含造市/避險腳,淨收權利金不全是方向單;FinMind 為日合計、
  無法拆日盤/夜盤;非買賣訊號。

用法:
  tw_option_flow.py --build                 # 抓資料+寫 cache(網頁用)
  tw_option_flow.py --build --telegram      # 同上,訊號觸發時推 Telegram
  tw_option_flow.py --html > /tmp/o.html    # debug 網頁
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "concept_momentum", "cache")
LATEST = os.path.join(CACHE, "option_flow_latest.json")
FINMIND = "https://api.finmindtrade.com/api/v4/data"

DEFAULT_CHAT_ID = "-5229750819"
TG_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

SHOW_DAYS = 60          # 頁面顯示近 N 交易日
PCTL_WIN = 60           # 百分位視窗(交易日)
ABS_FLOOR = 1.0         # 訊號金額下限(億)
YI = 1e5                # 千元 → 億


def _fm(dataset: str, params: dict, token: str) -> list[dict]:
    p = {"dataset": dataset, "token": token, **params}
    req = urllib.request.Request(FINMIND + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    if payload.get("status") != 200:
        raise RuntimeError(f"FinMind {dataset}: {payload.get('msg')}")
    return payload.get("data", [])


def fetch_days(token: str, back_days: int = 220) -> list[dict]:
    """近 N 日曆日的 TXO 法人籌碼 → 每交易日一筆:
    {date, taiex_pct, dp(自營put淨收億), dc(自營call淨收億),
     fp(外資put), fc(外資call), dp_oi(自營put未平倉淨額億),
     dp_buy, dp_sell(自營put買/賣金額億)}"""
    start = (datetime.now() - timedelta(days=back_days)).strftime("%Y-%m-%d")
    rows = _fm("TaiwanOptionInstitutionalInvestors",
               {"data_id": "TXO", "start_date": start}, token)
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("date", "")
        who = r.get("institutional_investors", "")
        cp = r.get("call_put", "")
        if not d or who not in ("自營商", "外資") or cp not in ("買權", "賣權"):
            continue
        net = (r.get("short_deal_amount", 0) - r.get("long_deal_amount", 0)) / YI
        rec = by_date.setdefault(d, {})
        key = ("d" if who == "自營商" else "f") + ("p" if cp == "賣權" else "c")
        rec[key] = round(net, 2)
        if who == "自營商" and cp == "賣權":
            rec["dp_buy"] = round(r.get("long_deal_amount", 0) / YI, 2)
            rec["dp_sell"] = round(r.get("short_deal_amount", 0) / YI, 2)
            rec["dp_oi"] = round((r.get("short_open_interest_balance_amount", 0)
                                  - r.get("long_open_interest_balance_amount", 0)) / YI, 2)
        if who == "外資" and cp == "賣權":
            # 外資 put 未平倉淨(賣-買):長期為負=結構性淨買 put(現貨保險)。
            # 越深(往 P10 −5億)=避險需求越重;回升=撤保險。存量 context 用。
            rec["fp_oi"] = round((r.get("short_open_interest_balance_amount", 0)
                                  - r.get("long_open_interest_balance_amount", 0)) / YI, 2)
    # 加權指數 context
    try:
        trows = _fm("TaiwanStockPrice",
                    {"data_id": "TAIEX", "start_date": start}, token)
        tx = {}
        for r in trows:
            c = r.get("close")
            s = r.get("spread")
            if c and s is not None and (c - s) > 0:
                tx[r["date"]] = round(s / (c - s) * 100, 2)
        for d, rec in by_date.items():
            rec["taiex_pct"] = tx.get(d)
    except Exception:
        pass
    out = [{"date": d, **rec} for d, rec in sorted(by_date.items())]
    return out


def _pctl(vals: list[float], q: float) -> float:
    """簡單百分位(線性插值)。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def detect_signal(days: list[dict]) -> dict | None:
    """對最新一日判「自營 put 淨收/淨買異常」。樣本 <20 日不出訊號。"""
    if not days:
        return None
    today = days[-1]
    dp = today.get("dp")
    if dp is None:
        return None
    hist = [d["dp"] for d in days[:-1] if d.get("dp") is not None][-PCTL_WIN:]
    if len(hist) < 20:
        return None
    p90 = _pctl(hist, 0.90)
    p10 = _pctl(hist, 0.10)
    if dp >= ABS_FLOOR and dp >= p90:
        return {"kind": "bull", "date": today["date"], "dp": dp,
                "p90": round(p90, 2), "p10": round(p10, 2),
                "label": f"🟢 自營 put 異常收權利金 +{dp:.2f}億(≥P90 {p90:.2f})→ 轉多觀察"}
    if dp <= -ABS_FLOOR and dp <= p10:
        return {"kind": "bear", "date": today["date"], "dp": dp,
                "p90": round(p90, 2), "p10": round(p10, 2),
                "label": f"🔴 自營 put 異常大買 {dp:.2f}億(≤P10 {p10:.2f})→ 避險/偏空觀察"}
    return None


def build(token: str | None = None) -> dict:
    token = token or os.environ.get("FINMIND_TOKEN", "")
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    days = fetch_days(token)
    if not days:
        return {"error": "FinMind 無選擇權法人資料"}
    sig = detect_signal(days)
    return {
        "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days": days[-SHOW_DAYS:],
        "n_days": len(days),
        "signal": sig,
    }


def build_and_save(token: str | None = None) -> dict:
    data = build(token)
    if not data.get("error"):
        os.makedirs(CACHE, exist_ok=True)
        tmp = LATEST + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, LATEST)
    return data


# ── 推播 ────────────────────────────────────────────────
def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    url = TG_API_URL.format(token=bot_token)
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print(f"Telegram 失敗: {e}", file=sys.stderr)
        return False


def format_signal_msg(data: dict) -> str:
    sig = data["signal"]
    today = data["days"][-1]
    lines = [
        f"📊 選擇權法人籌碼訊號 {sig['date']}",
        "",
        sig["label"],
        "",
        f"自營 put:買 {today.get('dp_buy', 0):.2f}億 / 賣 {today.get('dp_sell', 0):.2f}億"
        f" → 淨收 {today.get('dp', 0):+.2f}億",
        f"自營 call 淨收 {today.get('dc', 0):+.2f}億"
        f" | 外資 put {today.get('fp', 0):+.2f}億 call {today.get('fc', 0):+.2f}億",
        f"加權今日 {today.get('taiex_pct', 0):+.2f}%",
        "",
        "收put=賭不跌(偏多)、大買put=避險(偏空)。",
        "🧪 回測(2020-26,26次):隔日無edge(勝率50%、還低於基準),",
        "5~10日反彈傾向明顯(勝率69%/73% vs 基準60%/63%)——",
        "此訊號=恐慌/波動事件標記,別當隔日方向用。",
        "⚠ 自營含造市/避險腳,觀察用非買賣訊號。",
        "詳: " + __import__("site_nav").public_url("/option-flow"),
    ]
    return "\n".join(lines)


# ── 呈現 ────────────────────────────────────────────────
def render_html(data: dict) -> str:
    import html as _h
    nav = __import__("site_nav").nav_html("/option-flow")
    css = """<style>
  body{font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif;
       max-width:1000px;margin:1em auto;padding:0 1em;background:#f7f7f9;color:#222;}
  h1{font-size:1.35em;margin:.3em 0;} h3{font-size:1.05em;margin:.6em 0 .3em;}
  nav a{margin-right:12px;color:#0066cc;text-decoration:none;}
  section{background:#fff;padding:12px 16px;border-radius:6px;margin-bottom:12px;
          box-shadow:0 1px 3px rgba(0,0,0,.06);overflow-x:auto;}
  table{width:100%;border-collapse:collapse;font-size:.85em;}
  th,td{padding:4px 8px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;}
  th{background:#eef2f7;position:sticky;top:0;z-index:2;}
  th:first-child,td:first-child{text-align:left;}
  .up{color:#c0392b;} .dn{color:#0a8a3a;}
  .sig{font-size:1.0em;padding:10px 14px;border-radius:6px;margin-bottom:12px;}
  .sigb{background:#eafaf0;border:1px solid #bfe8cf;}
  .sigs{background:#fdeeee;border:1px solid #f0c2c2;}
  .signone{background:#f4f4f6;border:1px solid #ddd;color:#555;}
  .hl{background:#fff8e1;}
  .small{font-size:.85em;color:#666;}
  .note{background:#fff9ec;border:1px solid #f0dca8;border-radius:6px;
        padding:10px 14px;font-size:.86em;line-height:1.65;}
</style>"""
    head = (f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>選擇權法人籌碼(自營收put)</title>{css}</head><body>{nav}'
            f'<h1>📊 選擇權法人籌碼 — 自營收 put 觀察</h1>')
    if data.get("error"):
        return head + f'<section>⚠ {_h.escape(str(data["error"]))}</section></body></html>'

    days = data.get("days", [])
    sig = data.get("signal")
    if sig:
        cls = "sigb" if sig["kind"] == "bull" else "sigs"
        sig_html = f'<section class="sig {cls}"><b>{_h.escape(sig["label"])}</b></section>'
    else:
        sig_html = ('<section class="sig signone">今日無訊號(自營 put 淨收在正常區間;'
                    '訊號=淨收≥1億且≥近60日P90,或淨買≤−1億且≤P10)</section>')

    rows_html = []
    for d in reversed(days):
        def cell(v, invert=False):
            if v is None:
                return '<td>—</td>'
            cls = ("up" if v > 0 else ("dn" if v < 0 else ""))
            return f'<td class="{cls}">{v:+.2f}</td>'
        tp = d.get("taiex_pct")
        tp_td = (f'<td class="{"up" if tp>0 else ("dn" if tp<0 else "")}">{tp:+.2f}%</td>'
                 if tp is not None else '<td>—</td>')
        hl = ' class="hl"' if sig and d["date"] == sig["date"] else ""
        rows_html.append(
            f'<tr{hl}><td>{d["date"]}</td>{tp_td}'
            + cell(d.get("dp")) + cell(d.get("dc"))
            + cell(d.get("fp")) + cell(d.get("fc"))
            + cell(d.get("dp_oi")) + cell(d.get("fp_oi")) + '</tr>')

    table = ('<section><h3>近 60 交易日(單位:億元;正=淨收權利金/淨賣方,負=淨買方)</h3>'
             '<div style="max-height:70vh;overflow:auto"><table><thead><tr>'
             '<th>日期</th><th>加權%</th><th>自營put淨收</th><th>自營call淨收</th>'
             '<th>外資put淨收</th><th>外資call淨收</th><th>自營put未平倉淨</th>'
             '<th>外資put未平倉淨</th>'
             '</tr></thead><tbody>' + "".join(rows_html) + '</tbody></table></div></section>')

    # 回測結論(tw_option_flow_backtest.py 產出;無檔案就不顯示)
    bt_html = ""
    bt_path = os.path.join(CACHE, "option_flow_backtest.json")
    if os.path.exists(bt_path):
        try:
            with open(bt_path, encoding="utf-8") as f:
                bt = json.load(f)
            bull, base = bt["bull"], bt["base"]

            def _r(h, lab):
                b, o = bull.get(h, {}), base.get(h, {})
                if not b.get("n"):
                    return ""
                return (f'<tr><td>{lab}</td>'
                        f'<td>{b["win"]:.0f}%</td><td>{b["mean"]*100:+.2f}%</td>'
                        f'<td class="small">{o["win"]:.0f}% / {o["mean"]*100:+.2f}%</td></tr>')
            bt_html = (
                '<section><h3>🧪 回測結論(' + _h.escape(bt.get("window", "")) + ','
                f'{bt.get("n_bull", 0)} 次🟢訊號,walk-forward 同參數)</h3>'
                '<table style="max-width:560px"><thead><tr><th>後續</th><th>勝率</th>'
                '<th>平均報酬</th><th>對照組(全部日)</th></tr></thead><tbody>'
                + _r("gap", "隔日開盤跳空") + _r("H1", "隔 1 日")
                + _r("H3", "隔 3 日") + _r("H5", "隔 5 日") + _r("H10", "隔 10 日")
                + '</tbody></table>'
                '<p class="small" style="color:#b03a2e;line-height:1.6">⚠ <b>「收put→隔天就漲」不成立</b>:'
                '隔日勝率/平均都<b>低於</b>對照組(訊號常出現在連續殺盤中,隔天可能續殺,'
                '例 2024-08-02 訊號隔日 −8.35%)。<b>真正的訊號價值在 5~10 天</b>:'
                '恐慌時 IV 飆高、權利金變肥,自營才收得到大錢 → 大額收 put ≈ '
                '<b>恐慌/波動事件標記</b>,之後 5~10 日常見 V 型反彈(勝率 69%/73% vs '
                '基準 60%/63%)。⚠ 樣本 26 次且叢集於同一波恐慌(如 2024-08 連 4 天)、'
                '報酬視窗重疊,t 值高估,當「傾向」看待。另:🔴 大買 put 訊號'
                '<b>不預測下跌</b>(之後反而偏漲)——兩種極端都只是「波動事件」的影子。</p>'
                '</section>')
        except Exception:
            bt_html = ""

    glossary = """<section class="note">📖 <b>怎麼看(白話)</b><br>
• <b>淨收權利金</b> = 當日「賣出金額 − 買進金額」。<b>正(紅)= 當日淨當賣方、把權利金收進口袋</b>;負(綠)= 淨當買方、付權利金出去。單位億元(FinMind 原始單位千元)。<br>
• <b>自營 put 淨收(主訊號)</b>:自營商大量<b>賣 put 收錢</b> = 賭「指數不跌破履約價」,收越多把握越大 —— 社群口徑「沒事不會收那麼多」= 轉多觀察。反過來<b>大買 put(大負值)</b>= 花大錢買下跌保險 = 避險/偏空觀察。<br>
• <b>自營 call 淨收</b>:收 call = 賭「漲不過」偏壓上檔;大買 call = 偏多。方向解讀與 put 相反。<br>
• <b>外資 put/call 淨收(當日流量)</b>:對照用,<b>日常可忽略</b> —— 回測 2020-26(1597 日):外資當日淨收中位數 ≈0、P90 僅 ±0.2億(自營的 1/3 以下),≥1億 的極端日 6.5 年只出現 4 次,樣本太少無統計意義。台指選擇權權利金流主要是自營商(造市)在做;外資的主戰場在期貨與現貨,選擇權多為避險腿,方向意圖被對沖抵銷。<b>方向訊號看自營、避險溫度看外資存量(下欄)。</b><br>
• <b>外資put未平倉淨(存量)</b>:賣方金額−買方金額。<b>長期為負 = 外資結構性「淨買 put」</b>(中位 −0.5億、P10 −5.1億)—— 持有大量台股現貨,put 是保險。讀法:<b>往深負走(&lt;−5億)= 避險需求急升</b>(外資在加保險、對後市防禦);<b>回升往 0 = 撤保險</b>(防禦解除、偏安心)。這是風向 context、變化速度比水位重要,非進出訊號。<br>
• <b>自營put未平倉淨</b>:未平倉(存量)的賣方金額−買方金額。正=整體淨賣方部位。當日淨收看「今天的行為」、未平倉看「累積的底牌」。<br>
• <b>訊號門檻</b>:淨收 ≥1億 且 ≥近60交易日P90(異常放大才叫訊號,平常的造市進出不算);淨買 ≤−1億 且 ≤P10 反向。觸發才推 Telegram。<br>
⚠ <b>限制</b>:自營商數字<b>含造市與避險腳</b>,不全是方向單;FinMind 為<b>日合計、無法拆日盤/夜盤</b>(群裡說的「昨晚收1e」看不到,只能看到隔天全日);資料盤後(約15:00後)公布;回測結論見上節(隔日無 edge、5~10 日反彈傾向),純觀察、非買賣訊號。</section>"""

    foot = (f'<p class="small">🕒 每交易日 17:00 更新(TAIFEX 15:00 公布、'
            f'FinMind 約 16~17 點同步)· 更新於 '
            f'{_h.escape(data.get("as_of", ""))} · 資料 FinMind '
            f'TaiwanOptionInstitutionalInvestors (TXO)</p>')
    return head + sig_html + table + bt_html + glossary + foot + '</body></html>'


# ── CLI ─────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--telegram", action="store_true", help="訊號觸發時推 Telegram")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    ap.add_argument("--html", action="store_true")
    args = ap.parse_args()

    if args.html:
        data = None
        if os.path.exists(LATEST):
            with open(LATEST, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = build()
        sys.stdout.write(render_html(data))
        return

    data = build_and_save()
    if data.get("error"):
        print(f"錯誤: {data['error']}", file=sys.stderr)
        sys.exit(1)
    today = data["days"][-1]
    print(f"{today['date']} 自營put淨收 {today.get('dp', 0):+.2f}億 "
          f"(買{today.get('dp_buy', 0):.2f}/賣{today.get('dp_sell', 0):.2f}) "
          f"call {today.get('dc', 0):+.2f}億 | 外資 put {today.get('fp', 0):+.2f} "
          f"call {today.get('fc', 0):+.2f}")
    sig = data.get("signal")
    if sig:
        print(sig["label"])
        if args.telegram:
            # 去重:同一訊號日只推一次(FinMind 同步有 lag,cron 抓到舊日
            # 資料時訊號會重複出現;比照 tw_ftd 的 pushed 機制)
            pushed_f = os.path.join(CACHE, "option_flow_pushed.json")
            try:
                with open(pushed_f, encoding="utf-8") as f:
                    pushed = json.load(f)
            except Exception:
                pushed = {}
            if pushed.get("TXO") == sig["date"]:
                print(f"訊號 {sig['date']} 已推過,略過")
            else:
                bot = os.environ.get("TG_BOT_TOKEN", "")
                if bot and send_telegram(format_signal_msg(data), bot, args.chat_id):
                    pushed["TXO"] = sig["date"]
                    with open(pushed_f, "w", encoding="utf-8") as f:
                        json.dump(pushed, f)
                    print("已推 Telegram")
                elif not bot:
                    print("無 TG_BOT_TOKEN,略過推播", file=sys.stderr)
    else:
        print("無訊號(正常區間)")


if __name__ == "__main__":
    main()
