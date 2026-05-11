"""Side-by-side verification: TWSE direct vs FinMind for 借入交易 events.

Run BEFORE swapping fetch_lending_transactions to FinMind.
Usage:
  /usr/bin/python3 tools/verify_lending_lookup.py
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import finmind_client  # noqa


def _get_token():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=")[1].split()[0]
    return ""


def _twse_fetch(code: str, start: str, end: str) -> list[dict]:
    """Direct TWSE t13sa710 fetch (current production path)."""
    url = (f"https://www.twse.com.tw/SBL/t13sa710?"
           f"startDate={start.replace('-','')}&endDate={end.replace('-','')}"
           f"&stockNo={code}&response=json")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  [TWSE error {e.code}] retrying once after 5s")
        import time
        time.sleep(5)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    if data.get("stat") != "OK":
        return []
    out = []
    for row in data.get("data", []):
        # row format: [date_roc, code_name, type, volume, fee_rate, ...]
        roc = row[0]  # e.g., "115年05月08日"
        y, m, d = roc.replace("年", "/").replace("月", "/").replace("日", "").split("/")
        ad = f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"
        out.append({
            "date": ad,
            "volume": int(str(row[3]).replace(",", "")),
            "fee_rate": float(str(row[4]).replace(",", "")),
            "type": row[2].strip(),
        })
    return out


def _finmind_fetch(code: str, start: str, end: str, token: str) -> list[dict]:
    rows = finmind_client.fetch_securities_lending(code, start, end, token)
    return [{"date": r["date"],
             "volume": int(r["volume"]),
             "fee_rate": float(r["fee_rate"]),
             "type": r["transaction_type"]}
            for r in rows]


def _twse_sbl_fetch(code: str, date_str: str) -> dict:
    """Direct TWSE TWT93U fetch (上市 only)."""
    url = f"https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={date_str}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {}
    if data.get("stat") != "OK":
        return {}
    for row in data.get("data", []):
        if len(row) >= 14 and row[0].strip() == code:
            # cols 8-12: prev_balance, sell, return, adjust, today_balance (all 股)
            try:
                return {
                    "prev_balance_zhang": int(str(row[8]).replace(",", "")) // 1000,
                    "sell_zhang": int(str(row[9]).replace(",", "")) // 1000,
                    "return_zhang": int(str(row[10]).replace(",", "")) // 1000,
                    "today_balance_zhang": int(str(row[12]).replace(",", "")) // 1000,
                }
            except (ValueError, IndexError):
                return {}
    return {}


def _tpex_sbl_fetch(code: str, date_str: str) -> dict:
    """Direct TPEx SBL balance fetch (上櫃 only)."""
    d = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"
    url = f"https://www.tpex.org.tw/www/zh-tw/margin/sbl?date={urllib.parse.quote(d, safe='')}&response=json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return {}
    if data.get("stat", "").lower() != "ok":
        return {}
    tables = data.get("tables") or []
    for tbl in tables:
        for row in tbl.get("data", []):
            if len(row) >= 14 and row[0].strip() == code:
                try:
                    return {
                        "prev_balance_zhang": int(str(row[8]).replace(",", "")) // 1000,
                        "sell_zhang": int(str(row[9]).replace(",", "")) // 1000,
                        "return_zhang": int(str(row[10]).replace(",", "")) // 1000,
                        "today_balance_zhang": int(str(row[12]).replace(",", "")) // 1000,
                    }
                except (ValueError, IndexError):
                    return {}
    return {}


def _finmind_sbl_fetch(code: str, date_str: str, token: str) -> dict:
    """FinMind TaiwanDailyShortSaleBalances; same date in YYYY-MM-DD format."""
    s = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    rows = finmind_client.fetch_short_sale_balances(code, s, s, token)
    if not rows:
        return {}
    r = rows[0]
    return {
        "prev_balance_zhang": int(r.get("SBLShortSalesPreviousDayBalance", 0)) // 1000,
        "sell_zhang": int(r.get("SBLShortSalesShortSales", 0)) // 1000,
        "return_zhang": int(r.get("SBLShortSalesReturns", 0)) // 1000,
        "today_balance_zhang": int(r.get("SBLShortSalesCurrentDayBalance", 0)) // 1000,
    }


def verify_sbl_balance():
    token = _get_token()
    # (code, date, market): market "twse" uses TWT93U; "tpex" uses TPEx SBL endpoint
    # 1268 and 3491 are 上櫃 — TWSE TWT93U does NOT cover them, use TPEx direct instead
    test_cases = [
        ("2313", "20260508", "twse"),
        ("2313", "20260507", "twse"),
        ("1268", "20260508", "tpex"),
        ("2330", "20260508", "twse"),
    ]
    print("\n\n=== SBL balance verification ===")
    all_pass = True
    for code, date, market in test_cases:
        print(f"\n  {code} {date} [{market}]")
        direct = _twse_sbl_fetch(code, date) if market == "twse" else _tpex_sbl_fetch(code, date)
        fm = _finmind_sbl_fetch(code, date, token)
        src_label = "TWSE" if market == "twse" else "TPEx"
        print(f"    {src_label}: {direct}")
        print(f"    FM  : {fm}")
        if direct and fm:
            ok = all(direct.get(k) == fm.get(k) for k in ["prev_balance_zhang",
                                                           "sell_zhang",
                                                           "return_zhang",
                                                           "today_balance_zhang"])
            print(f"    {'PASS' if ok else 'FAIL'}")
            if not ok:
                all_pass = False
        elif not direct and not fm:
            print(f"    PASS (both empty)")
        else:
            print(f"    FAIL (one source empty, other not)")
            all_pass = False
    return all_pass


def main():
    token = _get_token()
    if not token:
        print("ERROR: no FINMIND_TOKEN")
        sys.exit(1)

    # Existing 借入 verification
    test_cases = [
        ("2313", "2026-05-04", "2026-05-08"),
        ("1268", "2026-05-04", "2026-05-08"),
        ("2330", "2026-05-04", "2026-05-08"),
    ]
    all_pass = True
    for code, start, end in test_cases:
        print(f"\n=== {code} 借入 {start} ~ {end} ===")
        twse = sorted(_twse_fetch(code, start, end), key=lambda r: (r["date"], r["volume"]))
        fm = sorted(_finmind_fetch(code, start, end, token), key=lambda r: (r["date"], r["volume"]))
        print(f"  TWSE: {len(twse)} rows | FinMind: {len(fm)} rows")
        if len(twse) != len(fm):
            print(f"  FAIL: row count differs")
            all_pass = False
            continue
        match = all(a["date"] == b["date"] and a["volume"] == b["volume"]
                    and abs(a["fee_rate"] - b["fee_rate"]) < 0.01
                    and a["type"] == b["type"] for a, b in zip(twse, fm))
        print(f"  {'PASS' if match else 'FAIL'}")
        if not match:
            for a, b in zip(twse, fm):
                if a != b:
                    print(f"    DIFF: TWSE={a} vs FinMind={b}")
            all_pass = False

    # SBL balance verification
    sbl_ok = verify_sbl_balance()
    all_pass = all_pass and sbl_ok

    print(f"\n{'='*40}\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
