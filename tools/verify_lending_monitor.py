"""Side-by-side verification: TWSE direct vs FinMind for whole-market borrow + SBL.

For lending mode: compare 議借量+利率 detection on a sample date.
For SBL mode: compare 餘額大減 detection on a sample date.
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import finmind_client


def _get_token():
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            return line.split("FINMIND_TOKEN=")[1].split()[0]
    return ""


def main():
    token = _get_token()
    # Check that whole-market SBL balances endpoint works
    print("=== Whole-market SBL balances 5/8 ===")
    rows = finmind_client.fetch_short_sale_balances_market("2026-05-08", token)
    print(f"  FinMind row count: {len(rows)}")
    print(f"  First 3 rows:")
    for r in rows[:3]:
        print(f"    {r}")
    # Spot-check 2313
    for r in rows:
        if r.get("stock_id") == "2313":
            print(f"  2313 found: SBLBalance={r.get('SBLShortSalesCurrentDayBalance')} 股")
            break
    else:
        print("  WARN: 2313 not in whole-market response")

    # Test if whole-market 借券交易 endpoint works (no data_id)
    print("\n=== Whole-market SecuritiesLending 5/8 ===")
    try:
        rows = finmind_client._call("TaiwanStockSecuritiesLending", {
            "start_date": "2026-05-08", "end_date": "2026-05-08",
        }, token)
        print(f"  FinMind row count: {len(rows)}")
        if rows:
            print(f"  First 3 rows:")
            for r in rows[:3]:
                print(f"    {r}")
            print(f"  Whole-market 借券交易 supported by FinMind")
        else:
            print(f"  Empty — FinMind may require per-stock data_id")
    except Exception as ex:
        print(f"  ERROR (likely needs data_id): {ex}")


if __name__ == "__main__":
    main()
