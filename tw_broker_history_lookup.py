#!/usr/bin/env python3
"""
個股分點歷史查詢（爬 HiStock branch.aspx）

HiStock 提供 N 天累積分點買/賣超，補足 TWSE BSR 只有當日資料的限制。
支援的天數：7, 10, 14, 30, 60, 90, 180, 270, 365（必須是這幾個值之一）。

使用範例：
    python3 tw_broker_history_lookup.py 3035            # 預設 10 天
    python3 tw_broker_history_lookup.py 3035 --days 30
    python3 tw_broker_history_lookup.py 2330 --days 60 --top 20

來源：https://histock.tw/stock/branch.aspx?no=<code>&day=<N>
"""

import argparse
import re
import sys
import urllib.request

ALLOWED_DAYS = {7, 10, 14, 30, 60, 90, 180, 270, 365}
URL = "https://histock.tw/stock/branch.aspx?no={code}&day={days}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def fetch_html(code: str, days: int) -> str:
    req = urllib.request.Request(
        URL.format(code=code, days=days),
        headers={"User-Agent": UA, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def _strip(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def parse_branch_page(html: str) -> dict:
    """Returns {'period':(from,to), 'sellers':[(name,buy,sell,net_sell,avg)],
    'buyers':[(name,buy,sell,net_buy,avg)]}"""
    period = None
    m = re.search(r"(\d{4}/\d+/\d+)\s*~\s*(\d{4}/\d+/\d+)", html)
    if m:
        period = (m.group(1), m.group(2))

    sellers, buyers = [], []
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr_match.group(1), re.DOTALL)
        if len(cells) < 10:
            continue
        clean = [_strip(c) for c in cells]
        # Layout: [seller_name, buy, sell, sell_over, avg, _, buyer_name, buy, sell, buy_over, avg]
        # Actually testing showed 9 cells: seller side(5) + buyer side(4 visible) — we saw
        # ['港商野村', '247', '1,278', '-1,031', '189.64', '大昌-樹林', '383', '31', ...]
        # Sometimes 11 cells with avg on both sides.
        try:
            seller = (
                clean[0],
                int(clean[1].replace(",", "")),
                int(clean[2].replace(",", "")),
                int(clean[3].replace(",", "")),
                float(clean[4]) if clean[4] not in ("", "-") else 0.0,
            )
            sellers.append(seller)
        except (ValueError, IndexError):
            pass

        # Buyer side: try cells[5..] then cells[6..]
        for offset in (5, 6):
            try:
                if len(clean) <= offset + 3:
                    continue
                avg = 0.0
                if len(clean) > offset + 4 and clean[offset + 4]:
                    try:
                        avg = float(clean[offset + 4])
                    except ValueError:
                        pass
                buyer = (
                    clean[offset],
                    int(clean[offset + 1].replace(",", "")),
                    int(clean[offset + 2].replace(",", "")),
                    int(clean[offset + 3].replace(",", "")),
                    avg,
                )
                if buyer[0] and buyer[3] != 0:
                    buyers.append(buyer)
                    break
            except (ValueError, IndexError):
                continue

    # Remove dups (HiStock duplicates rows for layout)
    seen_s = set()
    sellers_dedup = []
    for s in sellers:
        if s[0] in seen_s:
            continue
        seen_s.add(s[0])
        sellers_dedup.append(s)

    seen_b = set()
    buyers_dedup = []
    for b in buyers:
        if b[0] in seen_b:
            continue
        seen_b.add(b[0])
        buyers_dedup.append(b)

    return {"period": period, "sellers": sellers_dedup, "buyers": buyers_dedup}


def fetch_stock_name(code: str) -> str:
    try:
        sys.path.insert(0, "/home/kun/project/tw_stock_tools/concept_momentum")
        from stock_names import get_name
        return get_name(code, code)
    except Exception:
        return code


def format_report(code: str, days: int, parsed: dict, top: int = 10) -> str:
    name = fetch_stock_name(code)
    lines = []
    period = parsed.get("period")
    period_s = f"{period[0]} ~ {period[1]}" if period else "(期間未取得)"
    lines.append(f"{code} {name}  ({days} 天累積)")
    lines.append(f"期間: {period_s}")
    lines.append("")

    lines.append(f"━━ 買超 Top {top} ━━")
    if not parsed["buyers"]:
        lines.append("  (無資料)")
    for n, bv, sv, net, avg in parsed["buyers"][:top]:
        avg_s = f"@均價 {avg:.2f}" if avg else ""
        lines.append(f"  {n:18s} 買 {bv:>7,} 賣 {sv:>7,} 淨 +{net:>6,} {avg_s}")

    lines.append("")
    lines.append(f"━━ 賣超 Top {top} ━━")
    if not parsed["sellers"]:
        lines.append("  (無資料)")
    for n, bv, sv, net, avg in parsed["sellers"][:top]:
        avg_s = f"@均價 {avg:.2f}" if avg else ""
        lines.append(f"  {n:18s} 買 {bv:>7,} 賣 {sv:>7,} 淨 {net:>6,} {avg_s}")

    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="個股分點歷史查詢（HiStock 爬蟲）")
    p.add_argument("code", help="股票代號（4 位數）")
    p.add_argument("--days", type=int, default=10,
                   help=f"天數（必須是 {sorted(ALLOWED_DAYS)} 之一），預設 10")
    p.add_argument("--top", type=int, default=10, help="顯示前 N 名")
    args = p.parse_args()

    if args.days not in ALLOWED_DAYS:
        print(f"[ERROR] --days 必須是 {sorted(ALLOWED_DAYS)} 之一", file=sys.stderr)
        sys.exit(1)

    try:
        html = fetch_html(args.code, args.days)
    except Exception as e:
        print(f"[ERROR] 抓 HiStock 失敗: {e}", file=sys.stderr)
        sys.exit(2)

    parsed = parse_branch_page(html)
    print(format_report(args.code, args.days, parsed, top=args.top))


if __name__ == "__main__":
    main()
