"""Physical chain: red must fail as specified, then green must pass."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.queue import ChainBroken, add_exists, add_hash, add_item, add_unknown, load_queue, run_queue, runs_path


PY = sys.executable


class QueueChainTests(unittest.TestCase):
    def test_red_then_green_is_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_item(
                root,
                argv=[PY, "-c", "raise SystemExit(0)"],
                expect_exit=0,
                red_argv=[PY, "-c", "raise SystemExit(2)"],
                red_expect_exit=2,
            )
            result = run_queue(root)
            self.assertTrue(result["ok"])
            self.assertEqual(1, len(result["trusted"]))
            last = result["trusted"][0]["last"]
            self.assertEqual(2, last["red_exit"])
            self.assertEqual(0, last["green_exit"])
            self.assertTrue(last["trusted"])
            stored = load_queue(root)["items"][0]["last"]
            self.assertTrue(stored["trusted"])

    def test_red_not_failing_breaks_the_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_item(
                root,
                argv=[PY, "-c", "raise SystemExit(0)"],
                expect_exit=0,
                red_argv=[PY, "-c", "raise SystemExit(0)"],
                red_expect_exit=1,
            )
            result = run_queue(root)
            self.assertFalse(result["ok"])
            self.assertEqual(1, len(result["broken"]))
            self.assertIn("red chain failed", result["broken"][0]["error"])

    def test_identical_red_and_green_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            same = [PY, "-c", "raise SystemExit(0)"]
            with self.assertRaises(ChainBroken):
                add_item(
                    root,
                    argv=same,
                    expect_exit=0,
                    red_argv=same,
                    red_expect_exit=0,
                )

    def test_exists_same_predicate_two_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("x", encoding="utf-8")
            add_exists(root, "keep.txt")
            result = run_queue(root)
            self.assertTrue(result["ok"])
            self.assertEqual("exists", result["trusted"][0]["kind"])

    def test_high_trust_first_then_halt_skips_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            add_item(
                root,
                argv=[PY, "-c", "raise SystemExit(0)"],
                expect_exit=0,
                red_argv=[PY, "-c", "raise SystemExit(2)"],
                red_expect_exit=2,
                note="low",
            )
            add_exists(root, "missing.txt")
            result = run_queue(root)
            self.assertFalse(result["ok"])
            self.assertEqual(1, len(result["broken"]))
            self.assertEqual("exists", result["broken"][0]["kind"])
            self.assertEqual(1, len(result["skipped"]))
            self.assertEqual("exec", result["skipped"][0]["kind"])
            stored = load_queue(root)["items"]
            self.assertTrue(stored[-1]["last"]["skipped"])
            self.assertFalse(stored[-1]["last"]["trusted"])

    def test_unknown_lowers_rate_and_does_not_stop_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("x", encoding="utf-8")
            add_exists(root, "keep.txt")
            add_unknown(root, note="intent of the UI cannot be verified")
            result = run_queue(root)
            self.assertTrue(result["runnable"])
            self.assertEqual(0.5, result["trust_rate"])
            self.assertEqual(1, len(result["trusted"]))
            self.assertEqual(1, len(result["unknown"]))
            self.assertIn("reminder", result)

    def test_hash_pin_reds_when_bytes_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "keep.txt"
            target.write_text("x", encoding="utf-8")
            add_hash(root, "keep.txt")
            self.assertTrue(run_queue(root)["ok"])
            target.write_text("changed", encoding="utf-8")
            result = run_queue(root)
            self.assertFalse(result["ok"])
            self.assertEqual("hash", result["broken"][0]["kind"])

    def test_run_writes_evidence_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("x", encoding="utf-8")
            add_exists(root, "keep.txt")
            result = run_queue(root)
            log = runs_path(root)
            self.assertTrue(log.is_file())
            line = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(result["run_id"], line["run_id"])
            self.assertEqual("keep.txt", line["items"][0]["path"])
            self.assertTrue(line["items"][0]["last"]["trusted"])
            self.assertEqual(result["run_id"], load_queue(root)["last_run"]["run_id"])


if __name__ == "__main__":
    unittest.main()
