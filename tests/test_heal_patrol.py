from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unittest.mock import patch

from ag.__main__ import main
from ag.gui import write_dashboard
from ag.heal_patrol import patrol
from ag.loop import abandon, enroll, finish, start, status, thaw_canonical, verify
from ag.managed import ChainBroken
from ag.probe import insert, list_probes, plant_from_reject
from ag.store import load_pending, pending_path

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
            patrol(self.root, gear="repo")
        self.assertIn("enroll", str(raised.exception).lower())

    def test_default_gear_is_local(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        (self.root / "fat.py").write_text("x=1\n" * 60, encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "mix")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        with self.assertRaises(ChainBroken) as raised:
            patrol(self.root)
        self.assertIn("path", str(raised.exception).lower())
        out = patrol(self.root, paths=["glue.py"], max_lines=50)
        self.assertEqual("local", out["gear"])
        self.assertTrue(any(str(n).startswith("heal-") for n in out["needles"]))
        self.assertTrue(all("fat.py" not in str(item.get("path") or "") for item in out["diseases"]))
        err = io.StringIO()
        printed = io.StringIO()
        with patch("sys.stdout", printed), patch("sys.stderr", err):
            try:
                code = main(["heal-patrol", str(self.root)])
            except SystemExit as exc:
                code = 0 if exc.code is None else int(exc.code)
        self.assertNotEqual(0, code)
        self.assertIn("path", (err.getvalue() + printed.getvalue()).lower())

    def test_empty_scan_no_needles(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        out = patrol(self.root, gear="repo", max_lines=800)
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
        out = patrol(self.root, gear="repo", max_lines=50)
        self.assertGreaterEqual(len(out["needles"]), 1)
        self.assertEqual("repo", out["gear"])
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

    def test_gear_probes_reports_red_without_planting(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "not-in-file"},
            exam_fragment="ok.py still lacks the promised token",
            evidence="already-seen observation text from this run",
            area=["ok.py"],
            id="pre-red",
        )
        before = len(list_probes(self.root)["probes"])
        out = patrol(self.root, gear="probes")
        self.assertEqual([], out["needles"])
        self.assertEqual("probes", out["gear"])
        self.assertTrue(any("ok.py still lacks the promised token" in str(item.get("exam_fragment") or "") for item in out["diseases"]))
        self.assertIn("unless", out["repair_portrait"].lower())
        self.assertEqual(before, len(list_probes(self.root)["probes"]))

    def test_gear_local_requires_path_and_scopes_insert(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        fat = "\n".join(f"v{i} = {i}" for i in range(60)) + "\n"
        (self.root / "fat.py").write_text(fat, encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "both")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        with self.assertRaises(ChainBroken) as raised:
            patrol(self.root, gear="local")
        self.assertIn("path", str(raised.exception).lower())
        out = patrol(self.root, gear="local", paths=["glue.py"], max_lines=50)
        self.assertTrue(out["needles"])
        self.assertTrue(all(item.get("path") == "glue.py" for item in out["diseases"]))
        self.assertFalse(any("fat.py" in str(item.get("path") or "") for item in out["diseases"]))

    def test_gear_mess_unconfigured_skips_http(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "glue")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        fake_calls: list[object] = []

        def boom(*_a: object, **_k: object) -> object:
            fake_calls.append(1)
            raise AssertionError("urlopen")

        with patch("urllib.request.urlopen", boom):
            out = patrol(self.root, gear="mess", max_lines=800)
        self.assertEqual([], fake_calls)
        self.assertEqual("mess", out["gear"])
        self.assertIn("glue.py", out["repair_portrait"])
        self.assertIn("UNPROVEN", out["repair_portrait"])

    def test_gear_mess_configured_uses_chat_tuple(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "glue")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        from ag.critic import config_path

        path = config_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "endpoint": "https://example.test/v1",
                    "model": "unit-critic",
                    "api_key_env": "AG_CRITIC_API_KEY",
                    "timeout": 5,
                }
            ),
            encoding="utf-8",
        )
        payload = {"choices": [{"message": {"content": json.dumps({"repair_portrait": "Done looks like: barrel gone"})}}]}

        class Fake:
            n = 0

            def __call__(self, request, timeout=None):
                Fake.n += 1
                self._raw = json.dumps(payload).encode()
                self._idx = 0
                self._lines = self._raw.splitlines(keepends=True) or [self._raw]
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def readline(self):
                if self._idx >= len(self._lines):
                    return b""
                line = self._lines[self._idx]
                self._idx += 1
                return line

            def read(self):
                rest = b"".join(self._lines[self._idx :])
                self._idx = len(self._lines)
                return rest

        with patch("urllib.request.urlopen", Fake()):
            out = patrol(self.root, gear="mess", max_lines=800)
        self.assertEqual(1, Fake.n)
        self.assertIn("barrel gone", out["repair_portrait"])
        self.assertNotIn("critic call failed", out["repair_portrait"])

    def test_mess_enqueues_and_start_pops(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "glue")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        out = patrol(self.root, gear="mess", max_lines=800)
        self.assertTrue(out["needles"])
        seen = status(self.root)["pending_repairs"]
        self.assertEqual(1, seen["count"])
        self.assertIn("hp-", str(seen.get("head", {}).get("heal_report_id") or ""))
        self.assertFalse((self.root / "pending_repairs.json").exists())
        self.assertTrue(pending_path(self.root).is_file())
        opened = start(self.root)
        self.assertIn("glue.py", str(opened.get("portrait") or ""))
        self.assertEqual(0, status(self.root)["pending_repairs"]["count"])
        listed = list_probes(self.root, full=False)
        self.assertTrue(all("observation" not in row for row in listed["probes"]))
        abandon(self.root)

    def test_start_skip_pending_keeps_queue(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "glue")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        patrol(self.root, gear="mess", max_lines=800)
        self.assertEqual(1, len(load_pending(self.root)))
        opened = start(self.root, portrait="keep file", skip_pending=True)
        self.assertEqual("keep file", opened.get("portrait"))
        self.assertEqual(1, status(self.root)["pending_repairs"]["count"])
        abandon(self.root)

    def test_repo_and_probes_do_not_enqueue(self) -> None:
        (self.root / "glue.py").write_text("from ok import *\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "glue")
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        patrol(self.root, gear="repo", max_lines=800)
        self.assertEqual(0, status(self.root)["pending_repairs"]["count"])
        patrol(self.root, gear="probes")
        self.assertEqual(0, status(self.root)["pending_repairs"]["count"])

    def test_heal_patrol_module_never_starts(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "src" / "ag" / "heal_patrol.py").read_text(encoding="utf-8")
        self.assertNotIn("from .loop import start", src)
        self.assertNotIn("start(", src)


if __name__ == "__main__":
    unittest.main()


