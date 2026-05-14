#!/usr/bin/env python3
"""合約負債歷史 — 給股票代號，輸出近 N 年每季 CurrentContractLiabilities
(+ NoncurrentContractLiabilities if reported) 與 QoQ / YoY 變化。

合約負債 = 客戶預收款 / 已收訂金但尚未交付商品/服務的金額。
- 季增 ↑ = 未來營收已被預訂，多為利多 (尤其電子代工 / 工程 / 軟體)
- 季減 ↓ = 訂單已轉認列為營收，或客戶取消預訂
- 趨勢 = leading indicator for revenue recognition

Usage:
  tw_contract_liabilities.py 6669                  # 近 3 年
  tw_contract_liabilities.py 6669 --years 5        # 近 5 年
  tw_contract_liabilities.py 6669 --telegram       # 推 TG
  tw_contract_liabilities.py 6669 --json-out path  # 同時寫 JSON
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "concept_momentum"))

DEFAULT_CHAT_ID = "-5229750819"


def _get_token() -> str:
    """FINMIND_TOKEN from env or crontab."""
    t = os.environ.get("FINMIND_TOKEN", "")
    if t:
        return t
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True,
                             text=True, timeout=5).stdout
        for line in out.splitlines():
            if "FINMIND_TOKEN=" in line:
                return line.split("FINMIND_TOKEN=")[1].split()[0]
    except Exception:
        pass
    return ""


def _zh_name(code: str) -> str:
    try:
        from stock_names import get_name
        return get_name(code, fallback="")
    except Exception:
        return ""


def fetch_contract_liabilities(stock_code: str, years: int = 3) -> list[dict]:
    """Pull all CurrentContractLiabilities + NoncurrentContractLiabilities
    rows for `stock_code` over the last `years` years.

    Returns list of {date, current, noncurrent, total} sorted by date asc.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return []
    end = datetime.now()
    start = end - timedelta(days=years * 366 + 90)
    try:
        rows = finmind_client.fetch_balance_sheet(
            stock_code,
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
            token,
        )
    except Exception as e:
        print(f"[ERROR] FinMind fetch failed: {e}", file=sys.stderr)
        return []
    by_date: dict[str, dict] = {}
    for r in rows:
        t = r.get("type", "")
        if t == "CurrentContractLiabilities":
            d = by_date.setdefault(r["date"],
                                   {"date": r["date"], "current": 0,
                                    "noncurrent": 0})
            d["current"] = float(r.get("value", 0))
        elif t == "NoncurrentContractLiabilities":
            d = by_date.setdefault(r["date"],
                                   {"date": r["date"], "current": 0,
                                    "noncurrent": 0})
            d["noncurrent"] = float(r.get("value", 0))
    out = []
    for d in sorted(by_date.values(), key=lambda x: x["date"]):
        d["total"] = d["current"] + d["noncurrent"]
        out.append(d)
    return out


def annotate_changes(rows: list[dict]) -> list[dict]:
    """Add `qoq_pct` and `yoy_pct` to each row.

    QoQ = (this quarter / previous quarter) - 1
    YoY = (this quarter / same quarter previous year) - 1
    Uses `total` (current + noncurrent). None when no comparison available.
    """
    by_date = {r["date"]: r for r in rows}
    sorted_rows = sorted(rows, key=lambda r: r["date"])
    out = []
    for i, r in enumerate(sorted_rows):
        prev_total = sorted_rows[i - 1]["total"] if i > 0 else 0
        r["qoq_pct"] = (
            (r["total"] - prev_total) / prev_total * 100
            if prev_total > 0 else None
        )
        cur_dt = datetime.strptime(r["date"], "%Y-%m-%d")
        yoy_target = cur_dt.replace(year=cur_dt.year - 1).strftime("%Y-%m-%d")
        yoy_row = by_date.get(yoy_target)
        if yoy_row and yoy_row["total"] > 0:
            r["yoy_pct"] = (r["total"] - yoy_row["total"]) / yoy_row["total"] * 100
        else:
            r["yoy_pct"] = None
        out.append(r)
    return out


def _fmt_amount(value: float) -> str:
    if value <= 0:
        return "—"
    return f"{value / 1000:,.0f}"


def _fmt_pct(pct):
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def format_report(stock_code: str, rows: list[dict], years: int) -> str:
    """Telegram-friendly text report. Rows must already be annotated."""
    name = _zh_name(stock_code)
    if not rows:
        return (f"{stock_code} {name} 合約負債分析 (近 {years} 年)\n\n"
                f"⚠ 此股票 FinMind 沒有「合約負債」獨立科目資料。\n\n"
                f"原因：該公司 XBRL 申報時未把 CurrentContractLiabilities 拆出，"
                f"多半合併在「其他流動負債 OtherCurrentLiabilities」內。\n\n"
                f"常見不揭露的類型：\n"
                f"  - 純代工製造業 (e.g., 2330 台積電 / 2317 鴻海) — PO 即收款，"
                f"無實質預收\n"
                f"  - 部分 ODM (e.g., 6282 康舒) — 客戶用 PO 制不付訂金\n"
                f"  - 反例同業有揭露：2308 台達電 / 2301 光寶科 / 6669 緯穎 / "
                f"2454 聯發科\n\n"
                f"建議：去 公開資訊觀測站 (MOPS) 看該公司財報附註細目，或改用"
                f"該集團母公司/同業同類比 (e.g., 6282 看 2301 光寶科 或 2308 台達電)。")
    lines = []
    lines.append(f"{stock_code} {name} 合約負債 (近 {years} 年 / "
                  f"{len(rows)} 季)")
    lines.append("")
    lines.append("季底       | 流動合約負債 | 非流動    | 合計 (千元)  | QoQ%   | YoY%")
    lines.append("-----------|-------------|----------|-------------|--------|-------")
    for r in rows:
        cur = _fmt_amount(r["current"])
        non = _fmt_amount(r["noncurrent"])
        tot = _fmt_amount(r["total"])
        qoq = _fmt_pct(r["qoq_pct"])
        yoy = _fmt_pct(r["yoy_pct"])
        lines.append(
            f"{r['date']} | {cur:>11s} | {non:>8s} | {tot:>11s} | {qoq:>6s} | {yoy:>6s}"
        )
    latest = rows[-1]
    first = rows[0]
    span_years = (datetime.strptime(latest["date"], "%Y-%m-%d")
                  - datetime.strptime(first["date"], "%Y-%m-%d")).days / 365.25
    if first["total"] > 0 and span_years > 0:
        cagr = ((latest["total"] / first["total"]) ** (1 / span_years) - 1) * 100
        lines.append("")
        lines.append(f"📈 期間 CAGR: {cagr:+.1f}% (從 {first['date']} → "
                      f"{latest['date']})")
    lines.append("")
    lines.append("註：合約負債 ↑ = 客戶預訂款增加 (未來營收能見度提升)")
    lines.append("     合約負債 ↓ = 已轉認列為營收，或新預訂下降")
    return "\n".join(lines)


def _send_telegram(text: str, bot_token: str, chat_id: str) -> bool:
    api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_len = 4000
    chunks: list[str] = []
    if len(text) <= max_len:
        chunks = [text]
    else:
        cur, lns = "", text.split("\n")
        for ln in lns:
            if len(cur) + len(ln) + 1 > max_len:
                chunks.append(cur)
                cur = ln
            else:
                cur = cur + "\n" + ln if cur else ln
        if cur:
            chunks.append(cur)
    ok = True
    for c in chunks:
        body = json.dumps({"chat_id": chat_id, "text": c}).encode()
        req = urllib.request.Request(
            api, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if not json.loads(resp.read().decode()).get("ok"):
                    ok = False
        except Exception as e:
            print(f"[TG error] {e}", file=sys.stderr)
            ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description="台股合約負債歷史查詢")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--years", type=int, default=3,
                        help="回看年數 (預設 3)")
    parser.add_argument("--telegram", action="store_true",
                        help="推送到 Telegram")
    parser.add_argument("--bot-token",
                        default=os.environ.get("TG_BOT_TOKEN", ""))
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--json-out", help="結構化 JSON 輸出路徑")
    args = parser.parse_args()

    rows = fetch_contract_liabilities(args.code, years=args.years)
    rows = annotate_changes(rows)
    report = format_report(args.code, rows, args.years)
    print(report)

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".",
                    exist_ok=True)
        with open(args.json_out, "w") as f:
            json.dump({
                "stock_code": args.code,
                "name": _zh_name(args.code),
                "years": args.years,
                "quarters": rows,
            }, f, ensure_ascii=False, indent=2)

    if args.telegram:
        if not args.bot_token:
            print("[ERROR] --telegram requires TG_BOT_TOKEN", file=sys.stderr)
            sys.exit(1)
        ok = _send_telegram(report, args.bot_token, args.chat_id)
        print(f"[TG] {'sent' if ok else 'partial/fail'}", file=sys.stderr)


if __name__ == "__main__":
    main()
