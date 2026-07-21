import os, sys, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))
import warrant_flow as wf


class TestTypesAndIssuer(unittest.TestCase):
    def test_type_direction(self):
        self.assertEqual(wf.WARRANT_TYPES["0999"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999C"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999X"], "bull")
        self.assertEqual(wf.WARRANT_TYPES["0999P"], "bear")
        self.assertEqual(wf.WARRANT_TYPES["0999B"], "bear")
        self.assertEqual(wf.WARRANT_TYPES["0999Y"], "bear")

    def test_parse_issuer(self):
        self.assertEqual(wf.parse_issuer("AES凱基57購02"), "凱基")
        self.assertEqual(wf.parse_issuer("台積電元大99購01"), "元大")
        self.assertEqual(wf.parse_issuer("鴻海統一88售03"), "統一")

    def test_parse_issuer_unknown(self):
        self.assertEqual(wf.parse_issuer("XYZ"), "")


class TestParseTable(unittest.TestCase):
    PAYLOAD = {"stat": "OK", "tables": [
        {"title": "115年07月20日 每日收盤行情(認購權證(不含牛證))",
         "fields": ["暫停交易", "證券代號", "證券名稱", "成交股數", "成交筆數",
                    "成交金額", "開盤價", "最高價", "最低價", "收盤價",
                    "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量",
                    "最後揭示賣價", "最後揭示賣量", "本益比", "標的代號",
                    "標的名稱", "標的收盤價/指數"],
         "data": [
            ["", "030012", "AES凱基57購02", "36,000", "36", "3,600",
             "0.01", "0.02", "0.01", "0.01", "-", "0.00", "0.01", "100",
             "0.02", "50", "-", "2308", "台達電", "1,250.00"],
            ["", "030099", "壞資料", "-", "-", "-", "-", "-", "-", "-",
             "-", "-", "-", "-", "-", "-", "-", "2330", "台積電", "-"],
         ]}]}

    def test_parse_ok_row(self):
        rows = wf._parse_warrant_table(self.PAYLOAD)
        self.assertEqual(len(rows), 1)   # 壞資料列跳過
        r = rows[0]
        self.assertEqual(r["code"], "030012")
        self.assertEqual(r["underlying"], "2308")
        self.assertEqual(r["turnover"], 3600.0)
        self.assertEqual(r["volume"], 36000)

    def test_parse_no_title_table(self):
        self.assertEqual(wf._parse_warrant_table({"tables": [{}]}), [])


class TestAggregate(unittest.TestCase):
    ROWS = [
        {"code": "030001", "name": "台達電凱基購01", "side": "bull",
         "underlying": "2308", "turnover": 1000.0, "volume": 10000},
        {"code": "030002", "name": "台達電元大購02", "side": "bull",
         "underlying": "2308", "turnover": 3000.0, "volume": 20000},
        {"code": "070001", "name": "台達電凱基售01", "side": "bear",
         "underlying": "2308", "turnover": 500.0, "volume": 5000},
        {"code": "030999", "name": "台指凱基購", "side": "bull",
         "underlying": "IX0001", "turnover": 9999.0, "volume": 100},
    ]

    def test_aggregate_call_put(self):
        agg = wf.aggregate_by_underlying(self.ROWS)
        self.assertIn("2308", agg)
        self.assertNotIn("IX0001", agg)   # 指數標的排除
        u = agg["2308"]
        self.assertEqual(u["bull_turnover"], 4000.0)
        self.assertEqual(u["bear_turnover"], 500.0)
        self.assertEqual(u["n_warrants"], 3)

    def test_issuer_distribution(self):
        u = wf.aggregate_by_underlying(self.ROWS)["2308"]
        self.assertEqual(u["issuers"]["凱基"], 1500.0)  # 1000 + 500
        self.assertEqual(u["issuers"]["元大"], 3000.0)

    def test_top_warrants_sorted(self):
        u = wf.aggregate_by_underlying(self.ROWS)["2308"]
        self.assertEqual(u["top_warrants"][0]["code"], "030002")  # 最大額
        self.assertLessEqual(len(u["top_warrants"]), 5)
