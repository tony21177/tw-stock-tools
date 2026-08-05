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


def _stock_name(code: str, u: dict) -> str:
    """標的中文名：日檔的 name 優先，退回 stock_names。"""
    n = (u or {}).get("name")
    if n:
        return n
    try:
        from stock_names import get_name
        return get_name(code, "")
    except Exception:
        return ""



def _fmt_amt(v: float) -> str:
    """≥1億 → x.xx億;不足 → xxx萬。"""
    if v >= 1e8:
        return f"{v/1e8:.2f}億"
    return f"{v/1e4:,.0f}萬"


def _days_to_expiry(expiry: str, asof: str) -> int | None:
    from datetime import datetime
    try:
        return (datetime.strptime(expiry, "%Y%m%d")
                - datetime.strptime(asof, "%Y%m%d")).days
    except (ValueError, TypeError):
        return None


def _in_out(strike, close, is_call: bool) -> str:
    if not strike or not close:
        return ""
    diff = (close - strike) / strike * 100
    if not is_call:
        diff = -diff
    return f"價內{diff:.0f}%" if diff >= 0 else f"價外{-diff:.0f}%"


def build_message(rows: list[dict], day: dict, top: int = 8,
                  terms: dict | None = None) -> str:
    terms = terms or {}
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
        name = _stock_name(r["code"], u)
        # 主要權證明細：目前價/履約價/距到期/價內外/行使比例
        wt = ""
        tops = u.get("top_warrants", [])
        if tops:
            w0 = tops[0]
            t = terms.get(w0["code"], {})
            bits = []
            if w0.get("close") is not None:
                bits.append(f"權證價${w0['close']:g}")
            if w0.get("turnover"):
                bits.append(f"成交{_fmt_amt(w0['turnover'])}")
            if t.get("strike"):
                bits.append(f"履約${t['strike']:g}")
            dte = _days_to_expiry(t.get("expiry", ""), date)
            if dte is not None:
                bits.append(f"距到期{dte}天")
            io = _in_out(t.get("strike"), u.get("close"), w0["side"] == "bull")
            if io:
                bits.append(io)
            if t.get("conver"):
                bits.append(f"行使{t['conver']:g}")
            if bits:
                wt = f"\n     主要權證({w0['code']}): " + " ".join(bits)
        lines.append(
            f"  {r['code']} {name} {_DIR.get(r['direction'], '—')} "
            f"爆量{r['surge_ratio']:.1f}x 權證總額{_fmt_amt(r['warrant_turnover'])} "
            f"認購佔比{r['bull_share']:.0%}(Δ{r['bull_share_delta']:+.0%}) "
            f"發行:{iss}{wt}")
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
    try:
        import warrant_flow as wf
        terms = wf.load_terms()
    except Exception:
        terms = {}
    text = build_message(rows, days[-1], top=args.top, terms=terms)

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
