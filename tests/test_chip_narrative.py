"""Tests for concept_momentum/chip_narrative.py (AI 分點行為敘事)."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "concept_momentum"))

import chip_narrative  # noqa: E402


class NarrativeDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = chip_narrative.NARRATIVE_DIR
        chip_narrative.NARRATIVE_DIR = self.tmp.name

    def tearDown(self):
        chip_narrative.NARRATIVE_DIR = self._orig
        self.tmp.cleanup()


class TestStatusLifecycle(NarrativeDirMixin):
    def test_none_initially(self):
        st = chip_narrative.get_status("2313", "20260716")
        self.assertEqual(st["state"], "none")

    def test_done_after_result_written(self):
        result_p, _ = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(result_p, {
            "code": "2313", "date": "20260716", "narrative": "測試敘事",
            "generated_at": "2026-07-17 00:00:00", "elapsed_sec": 1.0})
        st = chip_narrative.get_status("2313", "20260716")
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["narrative"], "測試敘事")
        self.assertEqual(
            chip_narrative.load_cached("2313", "20260716")["narrative"],
            "測試敘事")

    def test_running_and_stale_running(self):
        _, status_p = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(
            status_p, {"state": "running", "started_at": time.time()})
        self.assertEqual(
            chip_narrative.get_status("2313", "20260716")["state"], "running")
        chip_narrative._write_atomic(
            status_p, {"state": "running",
                       "started_at": time.time() - 999})
        st = chip_narrative.get_status("2313", "20260716")
        self.assertEqual(st["state"], "error")
        self.assertIn("逾時", st["error"])

    def test_error_state(self):
        _, status_p = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(
            status_p, {"state": "error", "error": "RuntimeError: x"})
        st = chip_narrative.get_status("2313", "20260716")
        self.assertEqual(st["state"], "error")


class TestGenerate(NarrativeDirMixin):
    def test_generate_success_writes_result_and_clears_status(self):
        with mock.patch.object(chip_narrative, "build_prompt",
                               return_value="PROMPT"), \
             mock.patch.object(chip_narrative, "_run_claude",
                               return_value="敘事內容") as rc:
            chip_narrative._generate("2313", "20260716")
        rc.assert_called_once_with("PROMPT", "quick")
        st = chip_narrative.get_status("2313", "20260716")
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["narrative"], "敘事內容")
        _, status_p = chip_narrative._paths("2313", "20260716")
        self.assertFalse(os.path.exists(status_p))

    def test_generate_failure_writes_error_status(self):
        with mock.patch.object(chip_narrative, "build_prompt",
                               side_effect=RuntimeError("無序列資料")):
            chip_narrative._generate("9999", "20260716")
        st = chip_narrative.get_status("9999", "20260716")
        self.assertEqual(st["state"], "error")
        self.assertIn("無序列資料", st["error"])

    def test_start_idempotent_when_done(self):
        result_p, _ = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(result_p, {
            "code": "2313", "date": "20260716", "narrative": "舊的"})
        with mock.patch.object(chip_narrative.subprocess, "Popen") as po:
            st = chip_narrative.start("2313", "20260716")
        self.assertEqual(st["state"], "done")
        po.assert_not_called()

    def test_start_force_regenerates(self):
        result_p, _ = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(result_p, {
            "code": "2313", "date": "20260716", "narrative": "舊的"})
        with mock.patch.object(chip_narrative.subprocess, "Popen") as po:
            st = chip_narrative.start("2313", "20260716", force=True)
        self.assertEqual(st["state"], "running")
        po.assert_called_once()
        self.assertTrue(
            po.call_args.kwargs.get("start_new_session"))
        self.assertFalse(os.path.exists(result_p))

    def test_start_skips_when_already_running(self):
        _, status_p = chip_narrative._paths("2313", "20260716")
        chip_narrative._write_atomic(
            status_p, {"state": "running", "started_at": time.time()})
        with mock.patch.object(chip_narrative.subprocess, "Popen") as po:
            st = chip_narrative.start("2313", "20260716")
        self.assertEqual(st["state"], "running")
        po.assert_not_called()


class TestFullMode(NarrativeDirMixin):
    def test_paths_mode_suffix(self):
        q, _ = chip_narrative._paths("2313", "20260716", "quick")
        f, _ = chip_narrative._paths("2313", "20260716", "full")
        self.assertTrue(q.endswith("2313_20260716.json"))
        self.assertTrue(f.endswith("2313_20260716_full.json"))

    def test_modes_cached_independently(self):
        fq, _ = chip_narrative._paths("2313", "20260716", "quick")
        chip_narrative._write_atomic(fq, {"narrative": "快"})
        self.assertEqual(
            chip_narrative.get_status("2313", "20260716", "quick")["state"],
            "done")
        self.assertEqual(
            chip_narrative.get_status("2313", "20260716", "full")["state"],
            "none")

    def test_start_full_passes_mode_to_worker(self):
        with mock.patch.object(chip_narrative.subprocess, "Popen") as po:
            st = chip_narrative.start("2313", "20260716", mode="full")
        self.assertEqual(st["state"], "running")
        cmd = po.call_args.args[0]
        self.assertIn("--full", cmd)
        self.assertIn("2313", cmd)
        self.assertIn("20260716", cmd)

    def test_start_unknown_mode_errors(self):
        st = chip_narrative.start("2313", "20260716", mode="bogus")
        self.assertEqual(st["state"], "error")

    def test_run_claude_full_uses_skip_permissions(self):
        fake = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(chip_narrative.subprocess, "run",
                               return_value=fake) as run, \
             mock.patch.object(chip_narrative.shutil, "which",
                               return_value="/usr/bin/claude"):
            chip_narrative._run_claude("p", mode="full")
            self.assertIn("--dangerously-skip-permissions",
                          run.call_args.args[0])
            chip_narrative._run_claude("p", mode="quick")
            self.assertNotIn("--dangerously-skip-permissions",
                             run.call_args.args[0])


class TestRunClaude(NarrativeDirMixin):
    def test_nonzero_exit_raises(self):
        fake = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch.object(chip_narrative.subprocess, "run",
                               return_value=fake), \
             mock.patch.object(chip_narrative.shutil, "which",
                               return_value="/usr/bin/claude"):
            with self.assertRaises(RuntimeError):
                chip_narrative._run_claude("p")

    def test_success_returns_stdout(self):
        fake = mock.Mock(returncode=0, stdout="  分析結果  ", stderr="")
        with mock.patch.object(chip_narrative.subprocess, "run",
                               return_value=fake) as run, \
             mock.patch.object(chip_narrative.shutil, "which",
                               return_value="/usr/bin/claude"):
            out = chip_narrative._run_claude("提示")
        self.assertEqual(out, "分析結果")
        self.assertEqual(run.call_args.kwargs["input"], "提示")


if __name__ == "__main__":
    unittest.main()
