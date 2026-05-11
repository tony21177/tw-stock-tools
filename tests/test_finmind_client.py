"""Smoke tests for finmind_client. Hits real FinMind API; skips if no token."""
import os
import subprocess
import sys
import unittest

# Token loaded once at module import
TOKEN = ""
try:
    out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
    for line in out.splitlines():
        if "FINMIND_TOKEN=" in line:
            TOKEN = line.split("FINMIND_TOKEN=")[1].split()[0]
            break
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import finmind_client


@unittest.skipUnless(TOKEN, "No FINMIND_TOKEN in crontab")
class TestFinmindClient(unittest.TestCase):
    def test_securities_lending_2313_2026_05_08(self):
        """2313 on 5/8 had a 190-張 議借 row (verified manually)."""
        rows = finmind_client.fetch_securities_lending(
            "2313", "2026-05-08", "2026-05-08", TOKEN)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-05-08")
        self.assertEqual(row["stock_id"], "2313")
        self.assertEqual(row["transaction_type"], "議借")
        self.assertEqual(row["volume"], 190)
        self.assertAlmostEqual(row["fee_rate"], 1.75, places=2)

    def test_short_sale_balances_2313_2026_05_08(self):
        """2313 SBL balance 5/8 should be 21,833,000 股 (21,833 張)."""
        rows = finmind_client.fetch_short_sale_balances(
            "2313", "2026-05-08", "2026-05-08", TOKEN)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["SBLShortSalesCurrentDayBalance"], 21833000)
        # 當日賣出 826,000 股 = 826 張
        self.assertEqual(row["SBLShortSalesShortSales"], 826000)
        # 當日還券 912,000 股 = 912 張
        self.assertEqual(row["SBLShortSalesReturns"], 912000)

    def test_stock_price_2330_q1_2008(self):
        """Sanity: 18-year historical depth available."""
        rows = finmind_client.fetch_stock_price(
            "2330", "2008-01-01", "2008-01-31", TOKEN)
        self.assertGreater(len(rows), 15)  # ~20 trading days in Jan
        self.assertEqual(rows[0]["stock_id"], "2330")
        self.assertEqual(rows[0]["date"][:7], "2008-01")


if __name__ == "__main__":
    unittest.main()
