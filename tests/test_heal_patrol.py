from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.gui import write_dashboard
from ag.heal_patrol import patrol
from ag.loop import abandon, enroll, finish, start, thaw_canonical, verify
from ag.managed import ChainBroken
from ag.probe import list_probes, plant_from_reject

PY = sys.executable


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return (completed.stdout or "").strip()


class HealPatrolTests(unittest.TestCase):
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
        (self.root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "init")

    def tearDown(self) -> None:
        try:
            thaw_canonical(self.root)
        except Exception:
            pass
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def test_not_enrolled_refuses(self) -> None:
        with self.assertRaises(ChainBroken) as raised:
            patrol(self.root)
        self.assertIn("enroll", str(raised.exception).lower())

    def test_empty_scan_no_needles(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        out = patrol(self.root, max_lines=800)
        self.assertEqual("ag.heal-patrol.v1", out["schema"])
        self.assertEqual([], out["needles"])
        self.assertIn("hp-", str(out.get("heal_report_id") or ""))
        self.assertNotIn("cr-", str(out.get("heal_report_id") or ""))
        self.assertIn("no patrol diseases", out["repair_portrait"].lower())
        self.assertNotIn("observation", json.dumps(out))

    def test_plants_heal_needles_hides_observation_and_skips_unrelated_ticket(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        fat = "\n".join(f"v{i} = {i}" for i in range(60)) + "\n"
        (self.root / "fat.py").write_text(fat, encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "diseases")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        before = _git(self.root, "status", "--porcelain")
        out = patrol(self.root, max_lines=50)
        self.assertGreaterEqual(len(out["needles"]), 1)
        self.assertTrue(all(str(item).startswith("heal-") for item in out["needles"]))
        self.assertIn("Done looks like", out["repair_portrait"])
        self.assertNotIn("observation", json.dumps(out))
        self.assertEqual(before, _git(self.root, "status", "--porcelain"))
        listed = list_probes(self.root, full=False)
        heal_rows = [row for row in listed["probes"] if str(row.get("id") or "").startswith("heal-")]
        self.assertTrue(heal_rows)
        for row in heal_rows:
            self.assertNotIn("observation", row)
            self.assertIn("exam_fragment", row)
        html = write_dashboard(self.root, browse=False).read_text(encoding="utf-8")
        self.assertTrue(any(str(row.get("exam_fragment") or "") in html for row in heal_rows))
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        self.assertEqual([], checked.get("probe_red") or [])
        finish(self.root)

    def test_reject_still_plants_auto_needles(self) -> None:
        (self.root / "keep.py").write_text("bad_line = 1\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "keep")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        planted = plant_from_reject(
            self.root,
            items=[{"status": "fail", "evidence": "keep.py:1", "comment": "do not keep bad_line"}],
            tree=self.root,
        )
        self.assertTrue(planted)
        self.assertTrue(all(item.startswith("auto-") for item in planted))


if __name__ == "__main__":
    unittest.main()
