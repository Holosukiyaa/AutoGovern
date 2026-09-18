from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.loop import enroll, finish, start, verify
from ag.catalog import list_lane
from ag.see import usage

PY = sys.executable


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        os.environ["AG_HOME"] = str(self.home)
        self.root = Path(self._tmp.name) / "app"
        self.root.mkdir()
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "t@t")
        _git(self.root, "config", "user.name", "t")
        _git(self.root, "config", "commit.gpgsign", "false")
        (self.root / "ok.py").write_text("x=1\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "init")

    def tearDown(self) -> None:
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def test_catalog_has_eleven_ship_items(self) -> None:
        items = list_lane("ship")
        self.assertEqual(11, len(items))
        self.assertEqual(["ship-1", "ship-2"], [item["code"] for item in items[:2]])

    def test_happy_path_records_help_and_hook_records_block(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        verify(self.root)
        finish(self.root)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "nope"],
            capture_output=True,
            check=False,
        )
        report = usage(self.root)
        by_code = {row["code"]: row for row in report["items"]}
        self.assertGreaterEqual(by_code["ship-9"]["help"], 1)
        self.assertGreaterEqual(by_code["ship-2"]["help"], 1)
        self.assertGreaterEqual(by_code["ship-6"]["help"], 1)
        self.assertGreaterEqual(by_code["ship-5"]["help"], 1)
        self.assertGreaterEqual(by_code["ship-3"]["block"], 1)
        self.assertIn("ship-11", report["never_used"])
        self.assertIn("ship-10", report["never_used"])


if __name__ == "__main__":
    unittest.main()
