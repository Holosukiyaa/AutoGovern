from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.__main__ import main
from ag.critic import config_path, log_path, report_path
from ag.see import call

EVIDENCE = "already-seen observation text from this run"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


def _cli(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        try:
            code = main(argv)
        except SystemExit as exc:
            raw = exc.code
            code = 0 if raw is None else int(raw)
    return code, out.getvalue(), err.getvalue()


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


class CriticRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        os.environ["AG_HOME"] = str(self.home)
        for key in (
            "AG_CRITIC_ENABLED",
            "AG_CRITIC_ENDPOINT",
            "AG_CRITIC_MODEL",
            "AG_CRITIC_API_KEY_ENV",
            "AG_CRITIC_TIMEOUT",
        ):
            os.environ.pop(key, None)
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
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def _write_config(self) -> None:
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
            )
            + "\n",
            encoding="utf-8",
        )

    def test_unconfigured_is_unavailable_and_does_not_call_http(self) -> None:
        fake = _FakeHTTP(_chat_payload({"verdict": "pass", "items": [{"name": "x", "status": "pass", "comment": "ok"}]}))
        with patch("urllib.request.urlopen", fake):
            code, out, err = _cli(["critic-run", str(self.root), "--exam", "user: keep x = 1"])
        self.assertEqual(0, code, err)
        blob = json.loads(out)
        self.assertEqual("unavailable", blob["outcome"])
        self.assertEqual("not-configured", blob["reason"])
        self.assertEqual([], fake.requests)
        self.assertNotIn("proof", blob)
        self.assertNotIn("product", blob)
        self.assertNotIn("passed", blob)
        self.assertNotIn("proof", blob.get("pack") or {})

    def test_mock_reject_with_path_line_writes_ag_home_not_repo(self) -> None:
        self._write_config()
        verdict = {
            "verdict": "reject",
            "items": [
                {
                    "name": "exam",
                    "status": "fail",
                    "evidence": "ok.py:1",
                    "comment": "line missing the promised token",
                }
            ],
            "summary": "reject: restore x = 1",
        }
        fake = _FakeHTTP(_chat_payload(verdict))
        (self.root / "ok.py").write_text("x = 1\n# touch\n", encoding="utf-8")
        with patch("urllib.request.urlopen", fake):
            result = call(
                "ag_critic_run",
                {"root": str(self.root), "exam": "user: keep x = 1\nportrait: ok.py still has x = 1"},
            )
        self.assertEqual(1, len(fake.requests))
        self.assertEqual("rejected", result["outcome"])
        self.assertEqual("unit-critic", result["model"])
        self.assertEqual("ag.critic.v1", result["prompt_version"])
        report = Path(str(result["store"]))
        self.assertTrue(report.is_relative_to(self.home))
        self.assertEqual(report, report_path(self.root))
        self.assertTrue(report.is_file())
        self.assertFalse(any(path.name == "critic-last.json" for path in self.root.rglob("*")))
        self.assertFalse(any(path.name == "critic.json" for path in self.root.rglob("*")))
        request = fake.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(0, body["temperature"])
        self.assertEqual("unit-critic", body["model"])
        self.assertEqual("system", body["messages"][0]["role"])
        user = json.loads(body["messages"][1]["content"])
        self.assertEqual({"schema", "exam", "diff", "changed_files", "neighbors", "probes"}, set(user))
        self.assertNotIn("proof", user)
        self.assertNotIn("product", user)

    def test_fail_without_evidence_voids_as_unavailable(self) -> None:
        self._write_config()
        verdict = {
            "verdict": "reject",
            "items": [
                {
                    "name": "exam",
                    "status": "fail",
                    "evidence": "见上文",
                    "comment": "I think it failed",
                }
            ],
            "summary": "reject without a locator",
        }
        fake = _FakeHTTP(_chat_payload(verdict))
        with patch("urllib.request.urlopen", fake):
            code, out, err = _cli(["critic-run", str(self.root), "--exam", "user: keep x = 1"])
        self.assertEqual(0, code, err)
        blob = json.loads(out)
        self.assertEqual("unavailable", blob["outcome"])
        self.assertIn("作废", blob["reason"])
        self.assertNotEqual("rejected", blob["outcome"])

    def test_critic_run_does_not_change_probe_quiet_count(self) -> None:
        self._write_config()
        call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
                "exam_fragment": "ok.py contains x = 1",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "ttl-ten",
                "ttl_quiet_loops": 10,
            },
        )
        before = call("ag_probe_list", {"root": str(self.root), "full": True})["probes"][0]
        self.assertEqual(0, before["quiet_count"])
        (self.root / "ok.py").write_text("x = 1\n# run-touch\n", encoding="utf-8")
        verdict = {
            "verdict": "pass",
            "items": [{"name": "exam", "status": "pass", "comment": "ok.py still has x = 1"}],
            "summary": "pass",
        }
        fake = _FakeHTTP(_chat_payload(verdict))
        with patch("urllib.request.urlopen", fake):
            ran = call("ag_critic_run", {"root": str(self.root), "exam": "user: keep x = 1"})
        self.assertEqual("passed", ran["outcome"])
        after = call("ag_probe_list", {"root": str(self.root), "full": True})["probes"][0]
        self.assertEqual(0, after["quiet_count"])
        self.assertEqual("armed", after["state"])
        self.assertEqual(before["observation"], after["observation"])

    def test_help_names_config_path_and_env(self) -> None:
        code, out, _err = _cli(["critic-run", "--help"])
        self.assertEqual(0, code)
        text = out.lower()
        self.assertIn("critic.json", text)
        self.assertIn("ag_critic_endpoint", text)
        self.assertIn("critic-last.json", text)

    def test_two_cli_runs_append_jsonl_and_overwrite_last(self) -> None:
        self._write_config()
        pass_v = {
            "verdict": "pass",
            "items": [{"name": "exam", "status": "pass", "comment": "ok"}],
            "summary": "pass",
        }
        reject_v = {
            "verdict": "reject",
            "items": [{"name": "exam", "status": "fail", "evidence": "ok.py:1", "comment": "no"}],
            "summary": "reject",
        }
        fake1 = _FakeHTTP(_chat_payload(pass_v))
        with patch("urllib.request.urlopen", fake1):
            code1, out1, err1 = _cli(["critic-run", str(self.root), "--exam", "first exam"])
        self.assertEqual(0, code1, err1)
        first = json.loads(out1)
        fake2 = _FakeHTTP(_chat_payload(reject_v))
        with patch("urllib.request.urlopen", fake2):
            code2, out2, err2 = _cli(["critic-run", str(self.root), "--exam", "second exam"])
        self.assertEqual(0, code2, err2)
        second = json.loads(out2)
        log = log_path(self.root)
        last = report_path(self.root)
        self.assertTrue(log.is_relative_to(self.home))
        self.assertFalse(any(path.name == "critic.jsonl" for path in self.root.rglob("*")))
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(2, len(rows))
        self.assertEqual("passed", rows[0]["outcome"])
        self.assertEqual("rejected", rows[1]["outcome"])
        self.assertEqual(64, len(rows[0]["exam_sha256"]))
        last_blob = json.loads(last.read_text(encoding="utf-8"))
        self.assertEqual(second["outcome"], last_blob["outcome"])
        self.assertEqual("rejected", last_blob["outcome"])
        self.assertNotEqual(first["outcome"], last_blob["outcome"])
        help_code, help_out, _err = _cli(["critic-log", "--help"])
        self.assertEqual(0, help_code)
        self.assertIn("newest last", help_out.lower())
        code, out, err = _cli(["critic-log", str(self.root), "--limit", "1"])
        self.assertEqual(0, code, err)
        listed = json.loads(out)
        self.assertEqual(1, len(listed["entries"]))
        self.assertEqual("rejected", listed["entries"][0]["outcome"])


if __name__ == "__main__":
    unittest.main()
