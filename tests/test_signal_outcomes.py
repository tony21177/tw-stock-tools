"""訊號成效追蹤器 — date 正規化與報酬計算。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "concept_momentum"))
import signal_outcomes as so


def _mkroot():
    root = tempfile.mkdtemp()
    tr = os.path.join(root, "turnaround_relay_history")
    sw = os.path.join(root, "second_wave_history")
    os.makedirs(tr); os.makedirs(sw)
    # TR: 檔名=執行日, date=資料日 (週五) → entry 應為下一交易日 (週一 0706)
    json.dump({"date": "20260703", "candidates": [
        {"code": "2425", "name": "承啟", "layer1_passed": True, "abcd_score": 4}]},
        open(os.path.join(tr, "20260706.json"), "w"))
    # SW: date=執行日 (週一) → entry 應為 ≥date 第一個交易日 = 0706
    json.dump({"date": "20260706", "candidates": [
        {"code": "8043", "name": "蜜望實", "second_wave_score": 0.0267,
         "drop_pct": 0.22, "volume_ratio": 1.65}]},
        open(os.path.join(sw, "20260706.json"), "w"))
    return root


TRADING = ["20260702", "20260703", "20260706", "20260707", "20260708",
           "20260709", "20260710", "20260713"]


class TestNormalize(unittest.TestCase):
    def test_entry_dates(self):
        sigs = so.load_signals(_mkroot(), trading_dates=TRADING)
        by = {(s["strategy"], s["code"]): s for s in sigs}
        self.assertEqual(by[("turnaround_relay", "2425")]["entry_date"], "20260706")
        self.assertEqual(by[("second_wave", "8043")]["entry_date"], "20260706")
        self.assertEqual(by[("turnaround_relay", "2425")]["meta"]["abcd_score"], 4)


class TestOutcome(unittest.TestCase):
    def test_returns(self):
        # 慣例：h=1 = 進場日開→收 (100→101 = +1%)；h=2 = 隔日收 (100→103 = +3%)
        px = {"2425": {"20260706": {"aopen": 100.0, "aclose": 101.0},
                       "20260707": {"aopen": 102.0, "aclose": 103.0}}}
        taiex = {d: {"open": 100.0, "close": 100.0} for d in TRADING}
        sigs = [{"strategy": "turnaround_relay", "code": "2425",
                 "signal_date": "20260703", "entry_date": "20260706", "meta": {}}]
        out = so.compute_outcomes(sigs, lambda c: px.get(c, {}), taiex,
                                  trading_dates=TRADING, horizons=(1, 2))
        rec = out["signals"][0]
        self.assertAlmostEqual(rec["ret"]["1"]["abs"], 1.0, places=4)
        self.assertAlmostEqual(rec["ret"]["2"]["abs"], 3.0, places=4)
        self.assertAlmostEqual(rec["ret"]["2"]["exc"], 3.0, places=4)


if __name__ == "__main__":
    unittest.main()
