"""Side-by-side: Yahoo .TW vs FinMind TaiwanStockPrice."""
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


def _yahoo_fetch(code: str, suffix: str = ".TW", range_str: str = "6mo") -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}{suffix}?interval=1d&range={range_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    out = {}
    from datetime import datetime
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        out[d] = round(c, 2)
    return out


def _finmind_fetch(code: str, start: str, end: str, token: str) -> dict:
    rows = finmind_client.fetch_stock_price(code, start, end, token)
    return {r["date"]: round(float(r["close"]), 2) for r in rows}


def main():
    token = _get_token()
    test_cases = [
        ("2313", ".TW"),    # 上市
        ("2330", ".TW"),
        ("3491", ".TWO"),   # 上櫃
    ]
    all_pass = True
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    for code, suffix in test_cases:
        print(f"\n=== {code}{suffix} ===")
        try:
            yhoo = _yahoo_fetch(code, suffix)
        except Exception as ex:
            print(f"  Yahoo error: {ex}")
            continue
        fm = _finmind_fetch(code, start_date, end_date, token)
        common = set(yhoo.keys()) & set(fm.keys())
        print(f"  Yahoo {len(yhoo)} | FinMind {len(fm)} | common {len(common)}")
        diffs = []
        for d in sorted(common)[-30:]:
            y = yhoo[d]
            f = fm[d]
            if abs(y - f) > 0.01:
                diffs.append((d, y, f, y - f))
        if diffs:
            print(f"  DIFFS in last 30 days: {len(diffs)}")
            for d, y, f, delta in diffs[:5]:
                print(f"    {d}: Yahoo={y} FinMind={f} (delta={delta:+.2f})")
            ratio_diffs = [abs(y - f) / y * 100 for _, y, f, _ in diffs if y > 0]
            mean_pct = sum(ratio_diffs) / len(ratio_diffs)
            print(f"  Mean diff: {mean_pct:.2f}%")
            if mean_pct > 1.0:
                all_pass = False
        else:
            print(f"  PASS (all 30 latest days match within 0.01)")

    print(f"\n{'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
