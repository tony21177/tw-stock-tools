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


def main():
    token = _get_token()
    if not token:
        print("ERROR: no FINMIND_TOKEN")
        sys.exit(1)

    test_cases = [
        ("2313", "2026-05-04", "2026-05-08"),
        ("1268", "2026-05-04", "2026-05-08"),
        ("2330", "2026-05-04", "2026-05-08"),
    ]
    all_pass = True
    for code, start, end in test_cases:
        print(f"\n=== {code} {start} ~ {end} ===")
        twse = sorted(_twse_fetch(code, start, end), key=lambda r: (r["date"], r["volume"]))
        fm = sorted(_finmind_fetch(code, start, end, token), key=lambda r: (r["date"], r["volume"]))
        print(f"  TWSE: {len(twse)} rows | FinMind: {len(fm)} rows")
        if len(twse) != len(fm):
            print(f"  FAIL: row count differs")
            all_pass = False
            continue
        match = True
        for a, b in zip(twse, fm):
            if (a["date"] != b["date"] or a["volume"] != b["volume"]
                    or abs(a["fee_rate"] - b["fee_rate"]) > 0.01
                    or a["type"] != b["type"]):
                print(f"  DIFF: TWSE={a} vs FinMind={b}")
                match = False
        if match:
            print(f"  PASS")
        else:
            all_pass = False

    print(f"\n{'='*40}\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
