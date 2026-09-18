from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from unittest.mock import patch

from ag.critic import config_path, log_path, report_path
from ag.loop import abandon, enroll, finish, start, status, thaw_canonical, unenroll, verify
from ag.managed import ChainBroken, project_key, real_root
from ag.mcp import TOOLS, _call
from ag.probe import insert, list_probes

PY = sys.executable
PIN_EVIDENCE = "already-seen observation text from this run"


class _FakeHTTP:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: object = None) -> "_FakeHTTP":
        self.requests.append(request)
        return self

    def __enter__(self) -> "_FakeHTTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _chat_payload(verdict: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(verdict, ensure_ascii=False)}}]}


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
        try:
            thaw_canonical(self.root)
        except Exception:
            pass
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
                "ag_critic_run",
                "ag_critic_log",
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

    def test_path_hit_red_probe_fails_product_and_refuses_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
            exam_fragment="ok.py contains x = 1",
            evidence="already-seen observation text from this run",
            area=["ok.py"],
            id="ok-pin",
        )
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "ok.py").write_text("broken\n", encoding="utf-8")
        before = _git(self.root, "rev-parse", "HEAD")
        checked = verify(self.root)
        self.assertEqual("failed", checked["product"])
        self.assertEqual(["ok-pin"], checked.get("probe_red") or [])
        self.assertEqual(["ok.py contains x = 1"], checked.get("missing") or [])
        dumped = json.dumps(checked)
        self.assertNotIn("must_include", dumped)
        blob = json.dumps(checked.get("probes") or [])
        self.assertNotIn("observation", blob)
        self.assertTrue(checked["verified_tree"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        text = str(raised.exception)
        self.assertIn("probe", text.lower())
        self.assertIn("ok-pin", text)
        self.assertEqual(before, _git(self.root, "rev-parse", "HEAD"))
        self.assertFalse((self.root / "ok.py").read_text(encoding="utf-8").startswith("broken"))

    def test_green_probe_after_fix_allows_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
            exam_fragment="ok.py contains x = 1",
            evidence="already-seen observation text from this run",
            area=["ok.py"],
            id="ok-pin",
        )
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "ok.py").write_text("broken\n", encoding="utf-8")
        self.assertEqual("failed", verify(self.root)["product"])
        (worktree / "ok.py").write_text("x = 1\n# fixed\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        self.assertEqual([], checked.get("probe_red") or [])
        done = finish(self.root)
        self.assertEqual("passed", done["product"])
        self.assertIn("x = 1", (self.root / "ok.py").read_text(encoding="utf-8"))

    def test_no_probes_tests_green_still_passed(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "only.txt").write_text("n\n", encoding="utf-8")
        checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        self.assertEqual([], checked.get("probe_red") or [])
        self.assertEqual([], checked.get("missing") or [])
        self.assertEqual([], checked.get("probes") or [])
        done = finish(self.root)
        self.assertEqual("passed", done["product"])

    def test_critic_rejected_does_not_refuse_finish(self) -> None:
        from ag.critic import report_path

        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        path = report_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"outcome": "rejected", "reason": "mock", "items": [], "summary": "no"}),
            encoding="utf-8",
        )
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        self.assertEqual("passed", verify(self.root)["product"])
        done = finish(self.root)
        self.assertEqual("passed", done["product"])
        self.assertTrue((self.root / "keep.txt").is_file())

    def test_andersen_blocks_verify_and_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic(model="gpt-4o", worker_model="gpt-4o-mini")
        worktree = Path(str(start(self.root, portrait="keep file")["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        fake = _FakeHTTP(_chat_payload({"verdict": "pass", "items": [{"name": "x", "status": "pass", "comment": "x"}]}))
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        critic = checked.get("critic") or {}
        self.assertEqual("unavailable", critic.get("outcome"))
        self.assertIn("andersen", str(critic.get("reason") or "").casefold())
        self.assertTrue(critic.get("configured"))
        self.assertEqual([], fake.requests)
        self.assertEqual("failed", checked["product"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        self.assertIn("unavailable", str(raised.exception).lower())

    def test_andersen_exemption_verify_can_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic(model="gpt-4o", worker_model="gpt-4o-mini", allow_same_family=True)
        worktree = Path(str(start(self.root, portrait="keep file")["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "pass",
                    "items": [{"name": "exam", "status": "pass", "comment": "ok"}],
                    "summary": "pass",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual(1, len(fake.requests))
        self.assertEqual("passed", (checked.get("critic") or {}).get("outcome"))
        self.assertEqual("passed", checked["product"])
        rows = [json.loads(line) for line in log_path(self.root).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertTrue(rows[-1].get("allow_same_family"))
        done = finish(self.root)
        self.assertEqual("passed", done["product"])

    def _enable_critic(self, **extra: object) -> None:
        path = config_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        blob: dict = {
            "enabled": True,
            "endpoint": "https://example.test/v1",
            "model": "unit-critic",
            "api_key_env": "AG_CRITIC_API_KEY",
            "timeout": 5,
        }
        blob.update(extra)
        path.write_text(json.dumps(blob) + "\n", encoding="utf-8")

    def test_verify_calls_critic_run_with_worktree_pack(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        worktree = Path(str(start(self.root, portrait="keep hello.txt")["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "pass",
                    "items": [{"name": "exam", "status": "pass", "comment": "hello landed"}],
                    "summary": "pass",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        critic = checked.get("critic") or {}
        self.assertEqual("passed", critic.get("outcome"))
        self.assertEqual("ag.critic.v1", critic.get("prompt_version"))
        self.assertEqual(1, len(fake.requests))
        store = Path(str(critic.get("store") or ""))
        self.assertTrue(store.is_file())
        self.assertTrue(store.is_relative_to(self.home))
        self.assertFalse((self.root / "critic-last.json").exists())
        body = json.loads(fake.requests[0].data.decode("utf-8"))
        user = json.loads(body["messages"][1]["content"])
        self.assertEqual({"schema", "exam", "diff", "changed_files", "neighbors", "probes"}, set(user))
        self.assertEqual("keep hello.txt", user["exam"])
        names = [str(item.get("path") or "") for item in user.get("changed_files") or []]
        self.assertIn("hello.txt", names)
        done = finish(self.root)
        self.assertEqual("passed", done["product"])

    def test_unconfigured_portrait_still_passed_and_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root, portrait="keep hello.txt")["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        fake = _FakeHTTP(_chat_payload({"verdict": "pass", "items": [{"name": "x", "status": "pass", "comment": "x"}]}))
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        critic = checked.get("critic") or {}
        self.assertEqual("unavailable", critic.get("outcome"))
        self.assertEqual("not-configured", critic.get("reason"))
        self.assertFalse(critic.get("configured"))
        self.assertEqual([], fake.requests)
        self.assertEqual("passed", checked["product"])
        rows = [json.loads(line) for line in log_path(self.root).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(1, len(rows))
        self.assertEqual("unavailable", rows[0]["outcome"])
        self.assertEqual("not-configured", rows[0]["reason"])
        done = finish(self.root)
        self.assertEqual("passed", done["product"])

    def test_verify_empty_portrait_skips_http(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        fake = _FakeHTTP(_chat_payload({"verdict": "pass", "items": [{"name": "x", "status": "pass", "comment": "x"}]}))
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual("unavailable", (checked.get("critic") or {}).get("outcome"))
        self.assertIn("no-exam", str((checked.get("critic") or {}).get("reason") or ""))
        self.assertTrue((checked.get("critic") or {}).get("configured"))
        self.assertEqual([], fake.requests)
        self.assertEqual("failed", checked["product"])
        rows = [json.loads(line) for line in log_path(self.root).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(1, len(rows))
        self.assertIn("no-exam", rows[0]["reason"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        self.assertIn("unavailable", str(raised.exception).lower())

    def test_verify_critic_reject_fails_product_and_refuses_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        worktree = Path(str(start(self.root, portrait="keep file")["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        before = _git(self.root, "rev-parse", "HEAD")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "reject",
                    "items": [
                        {
                            "name": "exam",
                            "status": "fail",
                            "evidence": "keep.txt:1",
                            "comment": "not enough",
                        }
                    ],
                    "summary": "reject",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual("rejected", (checked.get("critic") or {}).get("outcome"))
        self.assertEqual("failed", checked["product"])
        self.assertTrue(checked["verified_tree"])
        rows = [json.loads(line) for line in log_path(self.root).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(1, len(rows))
        self.assertEqual("rejected", rows[0]["outcome"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        text = str(raised.exception).lower()
        self.assertIn("critic", text)
        self.assertIn("rejected", text)
        self.assertEqual(before, _git(self.root, "rev-parse", "HEAD"))
        self.assertFalse((self.root / "keep.txt").exists())

    def test_verify_critic_network_fail_fails_product_and_refuses_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        worktree = Path(str(start(self.root, portrait="keep file")["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            checked = verify(self.root)
        critic = checked.get("critic") or {}
        self.assertEqual("unavailable", critic.get("outcome"))
        self.assertIn("failed", str(critic.get("reason") or ""))
        self.assertTrue(critic.get("configured"))
        self.assertEqual("failed", checked["product"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        self.assertIn("unavailable", str(raised.exception).lower())
        self.assertFalse((self.root / "keep.txt").exists())

    def test_verify_critic_void_fails_product_and_refuses_finish(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        worktree = Path(str(start(self.root, portrait="keep file")["worktree"]))
        (worktree / "keep.txt").write_text("k\n", encoding="utf-8")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "reject",
                    "items": [
                        {
                            "name": "exam",
                            "status": "fail",
                            "evidence": "见上文",
                            "comment": "no locator",
                        }
                    ],
                    "summary": "void",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        critic = checked.get("critic") or {}
        self.assertEqual("unavailable", critic.get("outcome"))
        self.assertIn("作废", str(critic.get("reason") or ""))
        self.assertEqual("failed", checked["product"])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        self.assertIn("unavailable", str(raised.exception).lower())

    def test_probe_red_fails_even_if_critic_passed(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
            exam_fragment="ok.py contains x = 1",
            evidence=PIN_EVIDENCE,
            area=["ok.py"],
            id="ok-pin",
        )
        worktree = Path(str(start(self.root, portrait="keep x = 1")["worktree"]))
        (worktree / "ok.py").write_text("broken\n", encoding="utf-8")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "pass",
                    "items": [{"name": "exam", "status": "pass", "comment": "ok"}],
                    "summary": "pass",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual("passed", (checked.get("critic") or {}).get("outcome"))
        self.assertEqual("failed", checked["product"])
        self.assertIn("ok-pin", checked.get("probe_red") or [])
        with self.assertRaises(ChainBroken) as raised:
            finish(self.root)
        self.assertIn("probe", str(raised.exception).lower())

    def test_verify_critic_does_not_double_count_quiet(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        self._enable_critic()
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
            exam_fragment="ok.py contains x = 1",
            evidence=PIN_EVIDENCE,
            area=["ok.py"],
            id="ok-pin",
            ttl_quiet_loops=10,
        )
        self.assertEqual(0, list_probes(self.root)["probes"][0]["quiet_count"])
        worktree = Path(str(start(self.root, portrait="keep x = 1")["worktree"]))
        (worktree / "ok.py").write_text("x = 1\n# v\n", encoding="utf-8")
        fake = _FakeHTTP(
            _chat_payload(
                {
                    "verdict": "pass",
                    "items": [{"name": "exam", "status": "pass", "comment": "ok"}],
                    "summary": "pass",
                }
            )
        )
        with patch("urllib.request.urlopen", fake):
            checked = verify(self.root)
        self.assertEqual("passed", checked["product"])
        self.assertEqual(1, len(fake.requests))
        self.assertEqual(1, list_probes(self.root)["probes"][0]["quiet_count"])

    def test_start_freezes_canonical_tracked_file_worktree_writable(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        with self.assertRaises(OSError):
            (self.root / "ok.py").write_text("blocked\n", encoding="utf-8")
        (worktree / "ok.py").write_text("x = 1\n# wt\n", encoding="utf-8")
        self.assertIn("# wt", (worktree / "ok.py").read_text(encoding="utf-8"))
        listed = _call("ag_probe_list", {"root": str(self.root)})
        self.assertTrue(all("observation" not in row for row in listed.get("probes") or []))
        abandon(self.root)
        (self.root / "ok.py").write_text("x = 1\n", encoding="utf-8")

    def test_finish_thaws_canonical(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "hello.txt").write_text("hi\n", encoding="utf-8")
        self.assertEqual("passed", verify(self.root)["product"])
        finish(self.root)
        (self.root / "ok.py").write_text("x = 1\n# after-finish\n", encoding="utf-8")
        self.assertIn("after-finish", (self.root / "ok.py").read_text(encoding="utf-8"))

    def test_abandon_thaws_canonical(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        start(self.root)
        with self.assertRaises(OSError):
            (self.root / "ok.py").write_text("blocked\n", encoding="utf-8")
        abandon(self.root)
        (self.root / "ok.py").write_text("x = 1\n# after-abandon\n", encoding="utf-8")

    def test_probe_red_finish_keeps_freeze_until_abandon(self) -> None:
        enroll(self.root, test_argv=[PY, "-c", "raise SystemExit(0)"])
        insert(
            self.root,
            observation={"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
            exam_fragment="ok.py contains x = 1",
            evidence=PIN_EVIDENCE,
            area=["ok.py"],
            id="ok-pin",
        )
        worktree = Path(str(start(self.root)["worktree"]))
        (worktree / "ok.py").write_text("broken\n", encoding="utf-8")
        self.assertEqual("failed", verify(self.root)["product"])
        with self.assertRaises(ChainBroken):
            finish(self.root)
        with self.assertRaises(OSError):
            (self.root / "ok.py").write_text("still-frozen\n", encoding="utf-8")
        abandon(self.root)
        (self.root / "ok.py").write_text("x = 1\n# thawed\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()



