from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.checkup import checkup
from ag.queue import add_exists, add_unknown, run_queue
from ag.report import dashboard_view, problems


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
            dash = dashboard_view(root)
            self.assertTrue(any("无法验证" in str(row.get("text")) for row in dash["records"]))
            self.assertTrue(dash["tree"])
            files = {row["path"]: row for row in dash["files"]}
            self.assertTrue(files["keep.txt"]["probed"])
            self.assertEqual("exists", files["keep.txt"]["probes"][0]["kind"])
            self.assertGreaterEqual(dash["stats"]["green"], 1)
            self.assertTrue(any("无法验证" in line for line in dash["advice"]))

    def test_checkup_lists_fat_file_as_suggestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fat = root / "huge.py"
            fat.write_text("x\n" * 850, encoding="utf-8")
            out = checkup(root, insert=False)
            self.assertEqual("fat", out["suggestions"][0]["kind"])
            self.assertEqual("huge.py", out["suggestions"][0]["path"])
            self.assertIn("Not a trust fence", out["suggestions"][0]["claim"])
            self.assertEqual([], out["inserted"])

    def test_checkup_plants_exists_and_hash(self) -> None:
        from ag.queue import load_queue

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fat = root / "huge.py"
            fat.write_text("x\n" * 850, encoding="utf-8")
            out = checkup(root)
            kinds = {(row["kind"], row["path"]) for row in out["inserted"]}
            self.assertIn(("exists", "huge.py"), kinds)
            self.assertIn(("hash", "huge.py"), kinds)
            again = checkup(root)
            self.assertEqual([], again["inserted"])
            paths = [(item.get("kind"), item.get("path")) for item in load_queue(root)["items"]]
            self.assertEqual(1, paths.count(("exists", "huge.py")))


if __name__ == "__main__":
    unittest.main()
