from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.checkup import checkup
from ag.queue import add_exists, add_unknown, run_queue
from ag.report import problems


class ReportTests(unittest.TestCase):
    def test_report_points_at_unknown_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "keep.txt").write_text("x", encoding="utf-8")
            add_exists(root, "keep.txt")
            add_unknown(root, note="UI taste cannot be verified")
            run_queue(root)
            rep = problems(root)
            kinds = {row["kind"] for row in rep["problems"]}
            self.assertIn("unknown", kinds)
            unknown = next(row for row in rep["problems"] if row["kind"] == "unknown")
            self.assertIn("runs.jsonl", unknown["blame"]["evidence"])
            self.assertTrue(unknown["blame"]["run_id"])

    def test_checkup_lists_fat_file_as_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fat = root / "huge.py"
            fat.write_text("x\n" * 850, encoding="utf-8")
            out = checkup(root)
            self.assertEqual("fat", out["suggestions"][0]["kind"])
            self.assertEqual("huge.py", out["suggestions"][0]["path"])
            self.assertIn("Not a trust fence", out["suggestions"][0]["claim"])


if __name__ == "__main__":
    unittest.main()
