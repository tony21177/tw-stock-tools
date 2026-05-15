#!/usr/bin/env python3
"""存貨歷史 — 給股票代號，輸出近 N 年每季存貨總額 + 營業成本 + 衍生比率。

衍生指標（從 FinMind 算）：
- 存貨週轉率 (Inventory Turnover) = 年化 COGS / 平均存貨
    年化 = 季 COGS × 4。平均存貨 = (期初 + 期末) / 2 (用前一季為期初)
- 存貨天數 DSI (Days Sales of Inventory) = 365 / 週轉率
- 存貨 / 季營收 比 = 期末存貨 / 季營收 (越低代表去化越快)

註：原料 / 在製品 / 半成品 / 成品 / 副產品 5 項拆分**不在** FinMind
balance sheet 內，只在 MOPS XBRL 申報的 AccountingItemsDetail.xml。
此版先給總額 + 衍生指標；拆分等 MOPS XBRL scraping 機制建好再加。

Usage:
  tw_inventory.py 2330                  # 近 5 年 (預設)
  tw_inventory.py 2330 --years 3        # 近 3 年
  tw_inventory.py 2330 --telegram       # 推 TG
  tw_inventory.py 2330 --json-out p.json
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


def fetch_inventory_series(stock_code: str, years: int = 5) -> list[dict]:
    """Return per-quarter rows: {date, inventory, revenue, cogs}.

    `inventory` is period-end balance, `revenue` and `cogs` are single-quarter
    flows. All in TWD 元. Sorted by date asc.
    """
    import finmind_client
    token = _get_token()
    if not token:
        return []
    end = datetime.now()
    start = end - timedelta(days=years * 366 + 90)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    try:
        bs = finmind_client.fetch_balance_sheet(stock_code, s, e, token)
        fs = finmind_client.fetch_financial_statements(stock_code, s, e, token)
    except Exception as ex:
        print(f"[ERROR] FinMind fetch failed: {ex}", file=sys.stderr)
        return []
    by_date: dict[str, dict] = {}
    for r in bs:
        if r.get("type") == "Inventories":
            d = by_date.setdefault(r["date"], {"date": r["date"]})
            d["inventory"] = float(r.get("value", 0))
    for r in fs:
        t = r.get("type", "")
        if t in ("Revenue", "CostOfGoodsSold"):
            d = by_date.setdefault(r["date"], {"date": r["date"]})
            d["revenue" if t == "Revenue" else "cogs"] = float(
                r.get("value", 0))
    out = []
    for d in sorted(by_date.values(), key=lambda x: x["date"]):
        d.setdefault("inventory", 0.0)
        d.setdefault("revenue", 0.0)
        d.setdefault("cogs", 0.0)
        # Skip quarters where balance sheet not yet filed (inventory 0).
        # Revenue/COGS publishes earlier than full balance sheet.
        if d["inventory"] <= 0:
            continue
        out.append(d)
    return out


def annotate(rows: list[dict]) -> list[dict]:
    """Add qoq_pct, yoy_pct, turnover, dsi_days, inv_rev_pct per row."""
    by_date = {r["date"]: r for r in rows}
    sr = sorted(rows, key=lambda r: r["date"])
    for i, r in enumerate(sr):
        prev_inv = sr[i - 1]["inventory"] if i > 0 else 0
        r["qoq_pct"] = ((r["inventory"] / prev_inv - 1) * 100
                        if prev_inv > 0 else None)
        cur = datetime.strptime(r["date"], "%Y-%m-%d")
        yoy_target = cur.replace(year=cur.year - 1).strftime("%Y-%m-%d")
        yoy_row = by_date.get(yoy_target)
        if yoy_row and yoy_row["inventory"] > 0:
            r["yoy_pct"] = (r["inventory"] / yoy_row["inventory"] - 1) * 100
        else:
            r["yoy_pct"] = None
        # Inventory turnover (annualized): COGS×4 / avg inventory
        avg_inv = ((r["inventory"] + prev_inv) / 2
                   if prev_inv > 0 else r["inventory"])
        if avg_inv > 0 and r["cogs"] > 0:
            r["turnover"] = (r["cogs"] * 4) / avg_inv
            r["dsi_days"] = 365 / r["turnover"]
        else:
            r["turnover"] = None
            r["dsi_days"] = None
        r["inv_rev_pct"] = (r["inventory"] / r["revenue"] * 100
                            if r["revenue"] > 0 else None)
    return sr


def _fmt_amt(v: float) -> str:
    if v <= 0:
        return "—"
    return f"{v / 1000:,.0f}"


def _fmt_pct(p):
    if p is None:
        return "—"
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.1f}%"


def _fmt_num(n, decimals=2):
    if n is None:
        return "—"
    return f"{n:.{decimals}f}"


def format_report(stock_code: str, rows: list[dict], years: int) -> str:
    name = _zh_name(stock_code)
    if not rows:
        return (f"{stock_code} {name} 存貨分析 (近 {years} 年)\n\n"
                f"⚠ FinMind 抓不到資料。可能股票代號錯誤、太新（<1 季）或下市。")
    lines = []
    lines.append(f"{stock_code} {name} 存貨 + 衍生指標 "
                  f"(近 {years} 年 / {len(rows)} 季)")
    lines.append("")
    lines.append("季底       | 存貨(千元)   | QoQ%   | YoY%   | "
                 "週轉率* | DSI天 | 存貨/營收")
    lines.append("-----------|-------------|--------|--------|"
                 "--------|-------|----------")
    for r in rows:
        inv = _fmt_amt(r["inventory"])
        qoq = _fmt_pct(r["qoq_pct"])
        yoy = _fmt_pct(r["yoy_pct"])
        to = _fmt_num(r["turnover"])
        dsi = _fmt_num(r["dsi_days"], 0)
        ir = _fmt_pct(r["inv_rev_pct"])
        lines.append(
            f"{r['date']} | {inv:>11s} | {qoq:>6s} | {yoy:>6s} | "
            f"{to:>6s} | {dsi:>5s} | {ir:>8s}"
        )
    lines.append("")
    lines.append("* 週轉率 = 年化 COGS / 平均存貨；DSI = 365/週轉率；"
                 "存貨/營收 = 期末存貨/該季營收")
    latest = rows[-1]
    first = rows[0]
    span_y = (datetime.strptime(latest["date"], "%Y-%m-%d")
              - datetime.strptime(first["date"], "%Y-%m-%d")).days / 365.25
    if first["inventory"] > 0 and span_y > 0:
        cagr = ((latest["inventory"] / first["inventory"]) ** (1 / span_y)
                - 1) * 100
        lines.append("")
        lines.append(f"📈 存貨 CAGR: {cagr:+.1f}% (從 {first['date']} → "
                      f"{latest['date']})")
    # Trend insights
    if latest["qoq_pct"] is not None and latest["yoy_pct"] is not None:
        qoq = latest["qoq_pct"]
        yoy = latest["yoy_pct"]
        if qoq > 10 and yoy > 20:
            verdict = "⚠ 存貨快速累積 — 出貨壓力 / 庫存風險"
        elif qoq < -10 and yoy < -10:
            verdict = "✅ 存貨大幅去化 — 出貨順暢 / 景氣轉好"
        elif qoq > 5:
            verdict = "↗ 存貨略增 — 預備拉貨或客戶下單轉冷需確認"
        elif qoq < -5:
            verdict = "↘ 存貨略減 — 出貨吃掉舊庫存"
        else:
            verdict = "→ 存貨平穩"
        lines.append(f"\n📊 最新季 ({latest['date']}) 解讀：{verdict}")
    lines.append("\n註：原料/在製品/半成品/成品/副產品 5 項拆分需 MOPS "
                  "XBRL 解析（待補）。此版先給總額。")
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
    parser = argparse.ArgumentParser(description="台股存貨歷史 + 衍生指標")
    parser.add_argument("code", help="股票代號")
    parser.add_argument("--years", type=int, default=5,
                        help="回看年數 (預設 5)")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--bot-token",
                        default=os.environ.get("TG_BOT_TOKEN", ""))
    parser.add_argument("--chat-id", default=DEFAULT_CHAT_ID)
    parser.add_argument("--json-out", help="結構化 JSON 輸出路徑")
    args = parser.parse_args()

    rows = fetch_inventory_series(args.code, years=args.years)
    rows = annotate(rows)
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
