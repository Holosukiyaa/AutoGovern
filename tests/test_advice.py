from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.catalog import plug, plug_dir
from ag.heal import run as heal_run
from ag.lift import run as lift_run
from ag.loop import enroll, load_task, start
from ag.managed import ChainBroken, lookup_project
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

    def test_unplug_skips_handler_core_cannot_unplug(self) -> None:
        plug(self.root, "lift-1", on=False)
        lifted = lift_run(self.root)
        self.assertIn("lift-1", lifted["skipped"])
        self.assertNotIn(1, [row["seq"] for row in lifted["findings"]])
        plug(self.root, "lift-1", on=True)
        lifted = lift_run(self.root)
        self.assertNotIn("lift-1", lifted["skipped"])
        with self.assertRaises(ChainBroken):
            plug(self.root, "ship-2", on=False)

    def test_unplug_deletes_strategy_folder_not_product_tree(self) -> None:
        heal_run(self.root)
        folder = plug_dir(self.root, "heal", 1)
        self.assertTrue(folder.is_dir())
        product = self.root / "ok.py"
        before = product.read_text(encoding="utf-8")
        plug(self.root, "heal-1", on=False)
        self.assertFalse(folder.exists())
        self.assertEqual(before, product.read_text(encoding="utf-8"))

    def test_unplug_one_keeps_others_and_gc_drops_removed_strategy(self) -> None:
        from ag.catalog import gc_plug, plug_list

        heal_run(self.root)
        see_run(self.root)
        lift_run(self.root)
        self.assertTrue(plug_dir(self.root, "heal", 1).is_dir())
        self.assertTrue(plug_dir(self.root, "see", 2).is_dir())
        plug(self.root, "heal-1", on=False)
        self.assertFalse(plug_dir(self.root, "heal", 1).exists())
        self.assertTrue(plug_dir(self.root, "see", 2).is_dir())
        healed = heal_run(self.root)
        self.assertIn("heal-1", healed["skipped"])
        self.assertEqual([2, 3, 4], [row["seq"] for row in healed["findings"]])
        plug(self.root, "heal-1", on=True)
        healed = heal_run(self.root)
        self.assertNotIn("heal-1", healed["skipped"])
        self.assertTrue(plug_dir(self.root, "heal", 1).is_dir())
        ghost = plug_dir(self.root, "gone", 99)
        ghost.mkdir(parents=True)
        (ghost / "dead.txt").write_text("x", encoding="utf-8")
        wiped = gc_plug(self.root)
        self.assertIn("gone-99", wiped)
        self.assertFalse(ghost.exists())
        self.assertTrue(plug_dir(self.root, "see", 2).is_dir())
        listed = plug_list(self.root)
        self.assertEqual([], listed.get("gc") or [])

    def test_heal_lists_stacked_css_doors_without_cutting(self) -> None:
        item = lookup_project(self.root) or {}
        task = load_task(str(item.get("key") or ""))
        self.assertTrue(task)
        worktree = Path(str(task["worktree"]))
        (worktree / "index.css").write_text("@import './a.css';\n@import './b.css';\n", encoding="utf-8")
        (worktree / "a.css").write_text(".guest-widget { color: red; }\n", encoding="utf-8")
        (worktree / "b.css").write_text(".guest-widget { color: blue; }\n", encoding="utf-8")
        healed = heal_run(self.root)
        by_seq = {row["seq"]: row for row in healed["findings"]}
        guests = [case["guest"] for case in (by_seq[1].get("cases") or [])]
        self.assertIn("guest-widget", guests)
        self.assertGreaterEqual(int(by_seq[1].get("doors") or 0), 1)
        self.assertFalse(by_seq[2].get("cut"))
        self.assertEqual("ag_start", by_seq[2].get("next"))
        self.assertIn("cannot set product", healed["reminder"])


if __name__ == "__main__":
    unittest.main()
