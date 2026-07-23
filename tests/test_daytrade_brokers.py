"""Tests for daytrade_brokers — 隔日沖分點註冊表."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import daytrade_brokers as db  # noqa: E402


class TestNormalizeAndLookup(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(db.normalize("凱基-松山"), "凱基松山")
        self.assertEqual(db.normalize("凱基 松山"), "凱基松山")

    def test_is_daytrade_by_name(self):
        reg = {"brokers": {"凱基松山": {"codes": ["9268"], "web_count": 3,
                                         "data_score": 0.4,
                                         "confidence": "confirmed",
                                         "sources": ["seed", "web"]}}}
        self.assertTrue(db.is_daytrade("凱基松山", reg))
        self.assertTrue(db.is_daytrade("凱基-松山", reg))   # 正規化
        self.assertFalse(db.is_daytrade("永豐金總公司", reg))

    def test_is_daytrade_by_code(self):
        reg = {"brokers": {"凱基松山": {"codes": ["9268"], "web_count": 3,
                                         "data_score": 0.4,
                                         "confidence": "confirmed",
                                         "sources": ["seed"]}}}
        self.assertTrue(db.is_daytrade("9268", reg))

    def test_daytrade_info_substring_key(self):
        # 種子名稱是關鍵字，實際分點名可能更長
        reg = {"brokers": {"美林": {"codes": [], "web_count": 2,
                                     "data_score": 0.0,
                                     "confidence": "confirmed",
                                     "sources": ["seed"]}}}
        info = db.daytrade_info("美商美林分公司", reg)
        self.assertIsNotNone(info)
        self.assertEqual(info["confidence"], "confirmed")


class TestConfidence(unittest.TestCase):
    def test_confidence_levels(self):
        self.assertEqual(db._confidence(0, 0.0, True), "confirmed")   # seed
        self.assertEqual(db._confidence(2, 0.0, False), "confirmed")  # web>=2
        self.assertEqual(db._confidence(0, 0.6, False), "confirmed")  # data>=0.5
        self.assertEqual(db._confidence(1, 0.0, False), "candidate")  # web=1
        self.assertEqual(db._confidence(0, 0.35, False), "candidate")  # 0.3-0.5


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = db.REGISTRY
        db.REGISTRY = os.path.join(self.tmp.name, "reg.json")

    def tearDown(self):
        db.REGISTRY = self._orig
        self.tmp.cleanup()

    def test_merge_three_sources(self):
        seed = {"凱基松山": ["9268"]}
        web = {"美林": {"web_count": 3, "codes": ["1440"]}}
        data = {"永豐金匯立": {"data_score": 0.31, "codes": ["9A81"]}}
        reg = db.merge_registry(seed, web, data, "2026-07-23")
        b = reg["brokers"]
        self.assertEqual(b["凱基松山"]["sources"], ["seed"])
        self.assertEqual(b["凱基松山"]["confidence"], "confirmed")
        self.assertEqual(b["美林"]["confidence"], "confirmed")   # web>=2
        self.assertEqual(b["美林"]["web_count"], 3)
        self.assertEqual(b["永豐金匯立"]["sources"], ["data"])
        self.assertEqual(b["永豐金匯立"]["confidence"], "candidate")  # 0.31 中
        self.assertEqual(b["永豐金匯立"]["codes"], ["9A81"])

    def test_seed_plus_data_same_broker(self):
        # 同分點同時 seed + data → sources 合併
        seed = {"美林": ["1440"]}
        data = {"美林": {"data_score": 0.2, "codes": ["1440"]}}
        reg = db.merge_registry(seed, None, data, "2026-07-23")
        self.assertEqual(set(reg["brokers"]["美林"]["sources"]),
                         {"seed", "data"})


def _price_file(d, code, date, broker_rows):
    """broker_rows: [(bid, name, buy, sell)]."""
    rows = [{"broker_id": b, "broker_name": n, "price": 100.0,
             "buy": bu, "sell": se} for b, n, bu, se in broker_rows]
    path = os.path.join(d, f"{code}_{date}_prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"date": date, "stock_code": code, "rows": rows}, f)


class TestDetectFromData(unittest.TestCase):
    def test_score_is_dump_over_bigbuy_ratio(self):
        with tempfile.TemporaryDirectory() as d:
            # X1 每次大買隔日全倒 (score=1.0)；X2 大買但續抱 (score=0)
            # 6 檔股票 → 各 1 次大買事件 → X1 big_buys=6, dumps=6
            for code in ["1111", "2222", "3333", "4444", "5555", "6666"]:
                _price_file(d, code, "20260701", [
                    ("X1", "隔沖分點", 5_000_000, 0),
                    ("X2", "波段分點", 3_000_000, 0),
                    ("Z", "散", 2_000_000, 0)])
                _price_file(d, code, "20260702", [
                    ("X1", "隔沖分點", 0, 4_500_000),   # 倒掉 4500≥60%×5000
                    ("X2", "波段分點", 500_000, 0),      # 續抱
                    ("Z", "散", 0, 500_000)])
            out = db.detect_from_data(bsr_dir=d, days=50)
            self.assertIn("隔沖分點", out)
            self.assertNotIn("波段分點", out)          # dump 比例 0
            self.assertAlmostEqual(out["隔沖分點"]["data_score"], 1.0)
            self.assertEqual(out["隔沖分點"]["big_buys"], 6)
            self.assertEqual(out["隔沖分點"]["cycles"], 6)
            self.assertIn("X1", out["隔沖分點"]["codes"])

    def test_partial_dump_ratio(self):
        with tempfile.TemporaryDirectory() as d:
            # X1 大買 6 次、只倒 3 次 → score 0.5 = confirmed
            for i, code in enumerate(
                    ["1111", "2222", "3333", "4444", "5555", "6666"]):
                _price_file(d, code, "20260701",
                            [("X1", "半沖", 5_000_000, 0),
                             ("Z", "散", 5_000_000, 0)])
                # 前 3 檔隔日倒、後 3 檔續抱
                sell = 4_500_000 if i < 3 else 0
                buy = 0 if i < 3 else 100_000
                _price_file(d, code, "20260702",
                            [("X1", "半沖", buy, sell),
                             ("Z", "散", 0, 500_000)])
            out = db.detect_from_data(bsr_dir=d, days=50)
            self.assertAlmostEqual(out["半沖"]["data_score"], 0.5)

    def test_below_min_bigbuys_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            # 只 3 次大買 < DT_MIN_BIGBUYS(5) → 樣本不足不計
            for code in ["1111", "2222", "3333"]:
                _price_file(d, code, "20260701",
                            [("X1", "少沖", 5_000_000, 0),
                             ("Z", "散", 5_000_000, 0)])
                _price_file(d, code, "20260702",
                            [("X1", "少沖", 0, 4_500_000),
                             ("Z", "散", 0, 500_000)])
            out = db.detect_from_data(bsr_dir=d, days=50)
            self.assertNotIn("少沖", out)

    def test_low_dump_ratio_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            # 大買 6 次只倒 1 次 → score 0.17 < candidate(0.30) → 不收
            for i, code in enumerate(
                    ["1111", "2222", "3333", "4444", "5555", "6666"]):
                _price_file(d, code, "20260701",
                            [("X1", "偶沖", 5_000_000, 0),
                             ("Z", "散", 5_000_000, 0)])
                sell = 4_500_000 if i == 0 else 0
                _price_file(d, code, "20260702",
                            [("X1", "偶沖", 0 if i == 0 else 100_000, sell),
                             ("Z", "散", 0, 500_000)])
            out = db.detect_from_data(bsr_dir=d, days=50)
            self.assertNotIn("偶沖", out)


if __name__ == "__main__":
    unittest.main()


class TestUpdateFromWeb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = db.REGISTRY
        db.REGISTRY = os.path.join(self.tmp.name, "reg.json")

    def tearDown(self):
        db.REGISTRY = self._orig
        self.tmp.cleanup()

    def test_web_parse_and_crossref(self):
        from unittest import mock
        fake_out = ('some preamble\n{"brokers": ['
                    '{"name": "凱基松山", "codes": ["9268"], "source_count": 3},'
                    '{"name": "冷門分點", "codes": [], "source_count": 1}]}\n')
        fake_proc = mock.Mock(stdout=fake_out, stderr="", returncode=0)
        with mock.patch.object(db.os.path, "exists", return_value=True), \
             mock.patch("shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("subprocess.run", return_value=fake_proc):
            reg = db.update_from_web(write=True)
        b = reg["brokers"]
        self.assertEqual(b["凱基松山"]["web_count"], 3)
        self.assertEqual(b["凱基松山"]["confidence"], "confirmed")  # web>=2
        # 單一來源 → candidate
        self.assertEqual(b["冷門分點"]["web_count"], 1)
        self.assertEqual(b["冷門分點"]["confidence"], "candidate")

    def test_web_no_json_returns_none(self):
        from unittest import mock
        fake_proc = mock.Mock(stdout="抱歉查不到", stderr="", returncode=0)
        with mock.patch.object(db.os.path, "exists", return_value=True), \
             mock.patch("shutil.which", return_value="/usr/bin/claude"), \
             mock.patch("subprocess.run", return_value=fake_proc):
            self.assertIsNone(db.update_from_web(write=False))
