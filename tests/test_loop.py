from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.loop import abandon, enroll, finish, start, status, unenroll, verify
from ag.managed import ChainBroken, project_key, real_root
from ag.mcp import TOOLS, _call

PY = sys.executable


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return (completed.stdout or "").strip()


def _repo(directory: str) -> Path:
    root = Path(directory) / "app"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


class LoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        os.environ["AG_HOME"] = str(self.home)
        self.root = _repo(self._tmp.name)

    def tearDown(self) -> None:
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def test_realpath_collapses_same_checkout(self) -> None:
        a = real_root(self.root)
        b = real_root(self.root / ".")
        self.assertEqual(a, b)
        self.assertEqual(project_key(self.root), project_key(self.root / "."))

    def test_happy_path_ff_only_and_hook_blocks_canonical(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        opened = start(self.root, portrait="file landed on main")
        worktree = Path(str(opened["worktree"]))
        self.assertTrue(worktree.is_dir())
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        self.assertTrue(checked["verified_tree"])
        done = finish(self.root)
        self.assertEqual("completed", done["process"])
        self.assertEqual("passed", done["product"])
        self.assertTrue((self.root / "hello.txt").is_file())
        self.assertEqual("hi", (self.root / "hello.txt").read_text(encoding="utf-8").strip())
        blocked = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("canonical", (blocked.stderr or "") + (blocked.stdout or ""))

    def test_no_tests_stays_undeclared(self) -> None:
        enroll(self.root)
        start(self.root)
        worktree = Path(str(status(self.root)["worktree"]))
        (worktree / "note.txt").write_text("x\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("undeclared", checked["product"])
        self.assertTrue(checked["verified_tree"])
        done = finish(self.root)
        self.assertEqual("completed", done["process"])
        self.assertEqual("undeclared", done["product"])

    def test_digest_mismatch_and_failed_tests(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        start(self.root)
        worktree = Path(str(status(self.root)["worktree"]))
        (worktree / "a.txt").write_text("1\n", encoding="utf-8")
        verify(self.root)
        (worktree / "a.txt").write_text("2\n", encoding="utf-8")
        with self.assertRaises(ChainBroken) as mismatch:
            finish(self.root)
        self.assertIn("digest", str(mismatch.exception))
        abandon(self.root)
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(7)"])
        start(self.root)
        checked = verify(self.root)
        self.assertEqual("failed", checked["product"])
        self.assertFalse(checked["verified_tree"])
        with self.assertRaises(ChainBroken):
            finish(self.root)

    def test_mcp_tools_are_the_loop(self) -> None:
        names = [str(item["name"]) for item in TOOLS]
        self.assertEqual(
            [
                "ag_status",
                "ag_enroll",
                "ag_start",
                "ag_verify",
                "ag_finish",
                "ag_abandon",
                "ag_unenroll",
                "ag_heal",
                "ag_lift",
                "ag_usage",
                "ag_see",
                "ag_probe_insert",
                "ag_probe_run",
                "ag_probe_list",
                "ag_critic_pack",
                "ag_gui",
                "ag_plug",
            ],
            names,
        )
        enrolled = _call("ag_enroll", {"root": str(self.root), "test_argv": [PY, "-c", "raise SystemExit(0)"]})
        self.assertTrue(enrolled["hook_ok"])
        self.assertEqual("pending", _call("ag_status", {"root": str(self.root)})["product"])
        opened = _call("ag_start", {"root": str(self.root), "portrait": "done"})
        Path(str(opened["worktree"]), "z.txt").write_text("z\n", encoding="utf-8")
        checked = _call("ag_verify", {"root": str(self.root)})
        self.assertEqual("passed", checked["product"])
        done = _call("ag_finish", {"root": str(self.root)})
        self.assertEqual("completed", done["process"])
        after = _call("ag_status", {"root": str(self.root)})
        self.assertEqual("passed", after["product"])
        self.assertEqual("completed", after["process"])

    def test_enroll_refuses_dirty(self) -> None:
        (self.root / "dirt.txt").write_text("x\n", encoding="utf-8")
        with self.assertRaises(ChainBroken) as raised:
            enroll(self.root)
        self.assertIn("dirty", str(raised.exception))

    def test_unenroll_restores_canonical_commit(self) -> None:
        enroll(self.root)
        blocked = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        done = unenroll(self.root)
        self.assertTrue(done["unenrolled"])
        allowed = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "ok"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, allowed.returncode, allowed.stderr)

    def test_unenroll_refuses_open_task(self) -> None:
        enroll(self.root)
        start(self.root)
        with self.assertRaises(ChainBroken) as raised:
            unenroll(self.root)
        self.assertIn("abandon", str(raised.exception))
        abandon(self.root)
        unenroll(self.root)

    def test_worktree_commit_only_via_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        blocked = subprocess.run(
            ["git", "-C", str(worktree), "add", "hello.txt"],
            capture_output=True,
            text=True,
            check=True,
        )
        blocked = subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("ag_finish", (blocked.stderr or "") + (blocked.stdout or ""))
        verify(self.root)
        finish(self.root)
        self.assertEqual("hi", (self.root / "hello.txt").read_text(encoding="utf-8").strip())

    def test_previous_hook_runs_on_finish(self) -> None:
        old = Path(self._tmp.name) / "oldhooks"
        old.mkdir()
        marker = self.home / "prev-ran"
        posix_marker = str(marker).replace("\\", "/")
        (old / "pre-commit").write_text(f"#!/bin/sh\nprintf ran > '{posix_marker}'\n", encoding="utf-8")
        _git(self.root, "config", "core.hooksPath", str(old).replace("\\", "/"))
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        verify(self.root)
        finish(self.root)
        self.assertTrue(marker.is_file(), "previous pre-commit should run on ag_finish")
        self.assertEqual("ran", marker.read_text(encoding="utf-8"))

    def test_canonical_commit_refused_without_managed_record(self) -> None:
        enroll(self.root)
        from ag.managed import save_managed

        save_managed({"schema": "ag.managed.v1", "projects": []})
        blocked = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("canonical", (blocked.stderr or "") + (blocked.stdout or ""))

    def test_no_verify_refused_on_canonical(self) -> None:
        enroll(self.root)
        blocked = subprocess.run(
            ["git", "-C", str(self.root), "commit", "--allow-empty", "--no-verify", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("canonical", (blocked.stderr or "") + (blocked.stdout or ""))

    def test_worktree_ag_deliver_without_token_refused(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worktree), "add", "hello.txt"],
            capture_output=True,
            check=True,
        )
        env = os.environ.copy()
        env["AG_DELIVER"] = "1"
        blocked = subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", "nope"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertNotEqual(0, blocked.returncode)
        self.assertIn("token", ((blocked.stderr or "") + (blocked.stdout or "")).lower())

    def test_verify_lists_untracked_without_refusing(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        names = [Path(str(x)).name for x in (checked.get("verify") or {}).get("untracked") or []]
        self.assertIn("hello.txt", names)
        done = finish(self.root)
        self.assertEqual("passed", done["product"])
        self.assertEqual("hi", (self.root / "hello.txt").read_text(encoding="utf-8").strip())


if __name__ == "__main__":
    unittest.main()
