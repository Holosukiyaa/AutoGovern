from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.heal import run as heal_run
from ag.lift import run as lift_run
from ag.loop import enroll, start
from ag.see import run as see_run

PY = sys.executable


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


class AdviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["AG_HOME"] = str(Path(self._tmp.name) / "home")
        Path(os.environ["AG_HOME"]).mkdir()
        self.root = Path(self._tmp.name) / "app"
        self.root.mkdir()
        _git(self.root, "init")
        _git(self.root, "config", "user.email", "t@t")
        _git(self.root, "config", "user.name", "t")
        _git(self.root, "config", "commit.gpgsign", "false")
        (self.root / "ok.py").write_text("x=1\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "init")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")

    def tearDown(self) -> None:
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def test_lift_heal_see_return_numbered_findings_without_blocking(self) -> None:
        lifted = lift_run(self.root)
        self.assertEqual("lift", lifted["lane"])
        seqs = [row["seq"] for row in lifted["findings"]]
        self.assertEqual(list(range(1, 12)), seqs)
        healed = heal_run(self.root)
        self.assertEqual([1, 2, 3, 4], [row["seq"] for row in healed["findings"]])
        seen = see_run(self.root)
        self.assertEqual(list(range(1, 10)), [row["seq"] for row in seen["findings"]])
        self.assertIn("cannot set product", lifted["reminder"])


if __name__ == "__main__":
    unittest.main()
