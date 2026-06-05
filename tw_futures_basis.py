"""期現貨基差 + 外資期貨留倉監控。

依據文章「期交所的外資留倉部位沒有多空意義」的論點建立：
  - 外資期貨留倉淨額 98% 是投行期現貨套利的對沖腳，淨部位≈0，沒有方向意義，
    不該拿來判斷行情（本工具會「顯示」它但標明此 caveat）。
  - 真正該看的：
    1. 盤中正逆價差 (基差) vs 套利來回成本 ~0.38% (36-38 bps)
       逆價差 > 成本 + 指數破底 → 套利客一腳踹下去 (跌時特別兇)
    2. 三訊號同步 (台股跌 + 逆價差 + 台幣貶) → 外資大賣超 (但賣超≠做空)
    3. 大台(TX) + 富台(XIF) 留倉「同向」且都累積很高 → 才是真的有事；
       大台空堆高但富台不同向 → 遊戲繼續，別腦補崩盤
    4. 月底轉倉積極度 (當月→次月) → 轉得積極代表預期風平浪靜

資料：FinMind（TaiwanFuturesDaily / TaiwanFuturesInstitutionalInvestors /
TaiwanStockPrice TAIEX）+ Yahoo TWD=X 匯率。

⚠ 限制：FinMind 期貨是日收盤 (EOD)，無即時盤中 tick。文章強調「看盤中」，本
工具以「日盤收盤基差」為基準 (clearly labeled)；真正盤中需即時 TAIFEX feed。
"""
from __future__ import annotations
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
ARB_COST_PCT = 0.38       # 期現貨套利來回成本 ~36-38 bps
DEFAULT_CHAT_ID = "-5229750819"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"


def _token() -> str:
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    import subprocess
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=")[1].split()[0]
    except Exception:
        pass
    return ""


def _fm(dataset: str, data_id: str | None, d0: str, d1: str,
        token: str) -> list[dict]:
    p = {"dataset": dataset, "start_date": d0, "end_date": d1, "token": token}
    if data_id:
        p["data_id"] = data_id
    req = urllib.request.Request(FINMIND_URL + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode()).get("data", [])
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(60)
                continue
            raise
    return []


def send_telegram(message: str, bot_token: str, chat_id: str) -> bool:
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(TG_API.format(token=bot_token), data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()).get("ok", False)
    except Exception as e:
        print(f"[ERROR] Telegram: {e}", file=sys.stderr)
        return False


def _front_close(fut_rows: list[dict], date: str) -> float | None:
    """日盤 (position) 近月 (6 碼 YYYYMM, 非週選) 收盤價。"""
    cands = [r for r in fut_rows if r["date"] == date
             and r.get("trading_session") == "position"
             and len(str(r.get("contract_date", ""))) == 6
             and r.get("close")]
    if not cands:
        return None
    cands.sort(key=lambda r: str(r["contract_date"]))
    return float(cands[0]["close"])


def _foreign_net_oi(inst_rows: list[dict], date: str) -> int | None:
    for r in inst_rows:
        if r["date"] == date and "外資" in r.get("institutional_investors", ""):
            return (r.get("long_open_interest_balance_volume", 0)
                    - r.get("short_open_interest_balance_volume", 0))
    return None


def fetch_monitor(days: int = 30) -> dict:
    """Build the full futures-basis monitor.

    Returns {series:[{date, tx, spot, basis, basis_pct, twii_chg, fx, fx_chg,
                      fx_net (外資TX淨留倉), xif_net (富台外資淨)}...],
             summary:{...}, latest:{...}} or {"error":...}.
    """
    import data_fetcher as df
    token = _token()
    if not token:
        return {"error": "無 FINMIND_TOKEN"}
    end = datetime.now()
    start = end - timedelta(days=days + 20)
    d0, d1 = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    try:
        tx = _fm("TaiwanFuturesDaily", "TX", d0, d1, token)
        spot = _fm("TaiwanStockPrice", "TAIEX", d0, d1, token)
        finst = _fm("TaiwanFuturesInstitutionalInvestors", "TX", d0, d1, token)
        xinst = _fm("TaiwanFuturesInstitutionalInvestors", "XIF", d0, d1, token)
    except Exception as e:
        return {"error": f"FinMind: {type(e).__name__}: {e}"}
    fx_rows = df.fetch_yahoo("TWD=X", "3mo")

    spot_map = {r["date"]: r for r in spot}
    fx_map = {f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}": r["close"]
              for r in fx_rows if r.get("close")}
    finst_dates = sorted(set(r["date"] for r in finst))
    xinst_dates = sorted(set(r["date"] for r in xinst))

    dates = sorted(set(r["date"] for r in tx) & set(spot_map.keys()))
    dates = [d for d in dates
             if d >= (end - timedelta(days=days)).strftime("%Y-%m-%d")]
    series = []
    prev_spot = prev_fx = None
    for d in dates:
        txc = _front_close(tx, d)
        sp = spot_map[d].get("close")
        if not txc or not sp:
            continue
        basis = txc - sp
        basis_pct = basis / sp * 100
        fxv = fx_map.get(d)
        row = {
            "date": d, "tx": round(txc, 1), "spot": round(sp, 2),
            "basis": round(basis, 1), "basis_pct": round(basis_pct, 3),
            "twii_chg": round((sp / prev_spot - 1) * 100, 2) if prev_spot else None,
            "fx": round(fxv, 3) if fxv else None,
            "fx_chg": round((fxv / prev_fx - 1) * 100, 3)
                      if (fxv and prev_fx) else None,
            "fx_net": _foreign_net_oi(finst, d) if d in finst_dates else None,
            "xif_net": _foreign_net_oi(xinst, d) if d in xinst_dates else None,
        }
        series.append(row)
        prev_spot, prev_fx = sp, (fxv or prev_fx)

    if not series:
        return {"error": "無重疊資料"}

    latest = series[-1]
    # 三訊號同步 (最新交易日): 台股跌 + 逆價差 + 台幣貶
    three = {
        "twii_down": (latest["twii_chg"] is not None and latest["twii_chg"] < 0),
        "backwardation": latest["basis"] < 0,
        "twd_weak": (latest["fx_chg"] is not None and latest["fx_chg"] > 0),
    }
    three["all"] = all(three[k] for k in ("twii_down", "backwardation", "twd_weak"))
    # 基差是否超過套利成本
    basis_extreme = abs(latest["basis_pct"]) > ARB_COST_PCT
    # 大台 vs 富台 同向極端
    tx_net = latest.get("fx_net")
    xif_net = latest.get("xif_net")
    same_dir_extreme = False
    if tx_net is not None and xif_net is not None:
        same_sign = (tx_net < 0 and xif_net < 0) or (tx_net > 0 and xif_net > 0)
        same_dir_extreme = same_sign and abs(tx_net) >= 50000 and abs(xif_net) >= 3000

    return {
        "series": series, "latest": latest, "arb_cost": ARB_COST_PCT,
        "three_signal": three, "basis_extreme": basis_extreme,
        "tx_net": tx_net, "xif_net": xif_net,
        "same_dir_extreme": same_dir_extreme,
    }


TAIFEX_MIS = "https://mis.taifex.com.tw/futures/api/getQuoteList"


def intraday_basis() -> dict:
    """盤中即時基差，從 TAIFEX MIS 一次取得臺指現貨(TXF-S) + 近月臺指期。
    盤中(09:00-13:45)為即時 (~5-20 秒延遲)；收盤後為最後一筆。

    Returns {spot, future, basis, basis_pct, spot_low, spot_high, near_low
    (現貨距今日低 ≤0.3%), fut_time, spot_time, date} or {"error":...}.
    這是文章最推的「盤中正逆價差」，可在 09:00-13:25 期間判斷套利客動向。
    """
    body = json.dumps({
        "MarketType": "0", "SymbolType": "F", "KindID": "1", "CID": "TXF",
        "ExpireMonth": "", "RowSize": "全部", "PageNo": "",
        "SortColumn": "", "AscDesc": "A",
    }).encode()
    req = urllib.request.Request(
        TAIFEX_MIS, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0",
                 "Origin": "https://mis.taifex.com.tw",
                 "Referer": "https://mis.taifex.com.tw/"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return {"error": f"TAIFEX MIS: {type(e).__name__}: {e}"}
    qs = data.get("RtData", {}).get("QuoteList", [])
    spot = next((q for q in qs if q.get("SymbolID") == "TXF-S"), None)
    fut = next((q for q in qs if str(q.get("SymbolID", "")).endswith("-F")), None)
    if not spot or not fut:
        return {"error": "TAIFEX 無臺指現貨/近月期報價"}

    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    sp = f(spot.get("CLastPrice"))
    fu = f(fut.get("CLastPrice"))
    lo = f(spot.get("CLowPrice"))
    hi = f(spot.get("CHighPrice"))
    if sp is None or fu is None or sp <= 0:
        return {"error": "TAIFEX 報價解析失敗"}
    basis = fu - sp
    near_low = (lo is not None and (sp - lo) / sp <= 0.003)

    def hhmmss(t):
        t = str(t or "").zfill(6)
        return f"{t[:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
    return {
        "spot": round(sp, 2), "future": round(fu, 1),
        "basis": round(basis, 1), "basis_pct": round(basis / sp * 100, 3),
        "spot_low": round(lo, 2) if lo else None,
        "spot_high": round(hi, 2) if hi else None,
        "near_low": near_low,
        "fut_name": fut.get("DispCName", ""),
        "fut_time": hhmmss(fut.get("CTime")),
        "spot_time": hhmmss(spot.get("CTime")),
        "date": str(spot.get("CDate", "")),
    }


def build_intraday_alert() -> tuple[str | None, dict]:
    """盤中告警 (文章 #1 訊號): 逆價差超過套利成本 + 現貨接近今日低
    → 套利客有利可圖、破底殺盤兇。只在這個 setup 觸發。"""
    ib = intraday_basis()
    if ib.get("error"):
        return None, ib
    bp = ib["basis_pct"]
    # 觸發: 逆價差 (basis<0) 且絕對值 > 套利成本 且 現貨接近今日低
    if not (ib["basis"] < 0 and abs(bp) > ARB_COST_PCT and ib["near_low"]):
        return None, ib
    msg = (
        f"⚡ 盤中基差殺盤警示 ({ib['fut_time']})\n\n"
        f"🔴 逆價差 {ib['basis']:+.0f} 點 ({bp:+.2f}%) 已超過套利成本 ±{ARB_COST_PCT}%"
        f"，且現貨 {ib['spot']:.0f} 接近今日低 {ib['spot_low']:.0f}\n\n"
        f"  近月期 {ib['future']:.0f} vs 現貨 {ib['spot']:.0f}\n"
        f"  → 期貨低於現貨超過成本 + 指數準備破底，套利客有利可圖、會「一腳踹下」"
        f"搶價差。這就是「漲時慢吞吞、跌時特別兇」的時刻。\n"
        f"⚠ 這不是有人看空，是一群套利的人同時衝。賣超≠做空。"
    )
    return msg, ib


def build_alert() -> tuple[str | None, dict]:
    """告警: 僅在「有意義」的訊號觸發 (基差逆價差極端 / 大台富台同向極端 /
    三訊號同步)。不對外資留倉淨額本身告警 (文章: 沒有多空意義)。"""
    m = fetch_monitor(days=20)
    if m.get("error"):
        return None, m
    L = m["latest"]
    three = m["three_signal"]
    secs = []
    if m["same_dir_extreme"]:
        secs.append(
            f"🔴 大台+富台留倉同向極端\n"
            f"  外資 TX 淨 {m['tx_net']:+,} 口 + 富台 XIF 淨 {m['xif_net']:+,} 口"
            f" 同向且都高 → 投行套利水庫接近滿載，這才是真的要留意 (文章重點)。")
    if three["all"]:
        secs.append(
            f"🔴 三訊號同步 = 外資大賣超 (但賣超≠做空)\n"
            f"  台股跌 {L['twii_chg']:+.2f}% + 逆價差 {L['basis']:+.0f} 點 + "
            f"台幣貶 {L['fx_chg']:+.2f}% 三者同時出現。")
    if m["basis_extreme"] and L["basis"] < 0:
        secs.append(
            f"🟠 逆價差超過套利成本\n"
            f"  基差 {L['basis']:+.0f} 點 ({L['basis_pct']:+.2f}%) 已超過 "
            f"±{ARB_COST_PCT}% 套利成本線 → 套利客有利可圖，破底時殺盤會兇。")
    if not secs:
        return None, m
    msg = (
        f"📐 期現貨基差/留倉警示 ({L['date']})\n\n"
        + "\n\n".join(secs) +
        f"\n\n基差 {L['basis']:+.0f} 點 ({L['basis_pct']:+.2f}%, 套利成本 ±{ARB_COST_PCT}%)\n"
        f"外資 TX 留倉淨 {m['tx_net']:+,} 口 / 富台 XIF 淨 {m['xif_net']:+,} 口\n"
        f"⚠ 外資留倉淨額 98% 是投行套利對沖腳，本身沒有多空意義；以上是「有意義」訊號。"
    )
    return msg, m


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="期現貨基差 + 外資留倉監控")
    ap.add_argument("--alert", action="store_true", help="盤後告警 (EOD 結構訊號)")
    ap.add_argument("--intraday", action="store_true",
                    help="盤中告警 (即時逆價差+破底, TAIFEX MIS)")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--bot-token")
    ap.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    if args.intraday:
        msg, ib = build_intraday_alert()
        if ib.get("error"):
            print("ERROR:", ib["error"], file=sys.stderr); sys.exit(1)
        if not msg:
            print(f"[OK] 盤中基差 {ib['basis']:+.0f} 點 ({ib['basis_pct']:+.2f}%) "
                  f"@ {ib['fut_time']}，無殺盤 setup，不告警。")
            sys.exit(0)
        print(msg)
        if args.telegram:
            # 30 分鐘冷卻，避免殺盤 setup 持續時每 5 分鐘洗版
            cd = os.path.join(HERE, ".intraday_basis_alert.marker")
            import subprocess
            try:
                last = os.path.getmtime(cd) if os.path.exists(cd) else 0
                now = float(subprocess.run(["date", "+%s"], capture_output=True,
                                           text=True).stdout.strip())
            except Exception:
                last, now = 0, 1
            if now - last < 1800:
                print("[冷卻中] 30 分鐘內已告警過，略過推送。")
                sys.exit(0)
            tok = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")
            if tok and send_telegram(msg, tok, args.chat_id):
                open(cd, "w").close()
        sys.exit(0)

    if args.alert:
        msg, m = build_alert()
        if m.get("error"):
            print("ERROR:", m["error"], file=sys.stderr); sys.exit(1)
        if not msg:
            L = m["latest"]
            print(f"[OK] 基差 {L['basis']:+.0f} 點 ({L['basis_pct']:+.2f}%)，"
                  f"無極端訊號，不告警。")
            sys.exit(0)
        print(msg)
        if args.telegram:
            tok = args.bot_token or os.environ.get("TG_BOT_TOKEN", "")
            if not tok:
                print("[ERROR] 需要 TG_BOT_TOKEN", file=sys.stderr); sys.exit(1)
            send_telegram(msg, tok, args.chat_id)
        sys.exit(0)

    m = fetch_monitor(args.days)
    if m.get("error"):
        print("ERROR:", m["error"]); sys.exit(1)
    L = m["latest"]
    print(f"期現貨基差監控 (最新 {L['date']}, {len(m['series'])} 交易日)")
    print(f"  TX 期貨日盤 {L['tx']} vs 加權現貨 {L['spot']} = 基差 {L['basis']:+.0f} 點"
          f" ({L['basis_pct']:+.2f}%)  [套利成本 ±{ARB_COST_PCT}%]")
    print(f"  外資 TX 留倉淨 {m['tx_net']:+,} 口 | 富台 XIF 淨 {m['xif_net']:+,} 口")
    print(f"  ⚠ 外資留倉淨額 98% 是投行套利對沖腳，無多空意義")
    t = m["three_signal"]
    print(f"  三訊號 (跌/逆價差/台幣貶): {t['twii_down']}/{t['backwardation']}/{t['twd_weak']}"
          f" → 同步={t['all']}")
    print(f"  大台富台同向極端: {m['same_dir_extreme']}")
    print("  近 8 日基差:")
    for r in m["series"][-8:]:
        print(f"    {r['date']}  TX {r['tx']:>8.0f}  現貨 {r['spot']:>8.0f}  "
              f"基差 {r['basis']:>+6.0f} ({r['basis_pct']:>+5.2f}%)  "
              f"外資TX淨 {str(r['fx_net']) if r['fx_net'] is not None else '-':>8}")
