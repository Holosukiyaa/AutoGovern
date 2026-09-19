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
from ag.see import call

PY = sys.executable
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


class ProbeAndCriticTests(unittest.TestCase):
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
        (self.root / "mod.py").write_text("import ok\nvalue = 2\n", encoding="utf-8")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-m", "init")

    def tearDown(self) -> None:
        os.environ.pop("AG_HOME", None)
        self._tmp.cleanup()

    def test_insert_without_evidence_refuses_and_does_not_write(self) -> None:
        observation = json.dumps({"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"})
        code, _out, err = _cli(
            [
                "probe",
                "insert",
                str(self.root),
                "--observation",
                observation,
                "--exam-fragment",
                "file still contains x = 1",
                "--evidence",
                "",
                "--area",
                "ok.py",
            ]
        )
        self.assertNotEqual(0, code)
        self.assertIn("evidence", err.lower())
        self.assertFalse(list(self.home.rglob("probes.json")))
        self.assertFalse(list(self.root.rglob("probes.json")))

    def test_insert_short_evidence_and_missing_kind_refuse(self) -> None:
        code, _out, err = _cli(
            [
                "probe",
                "insert",
                str(self.root),
                "--observation",
                json.dumps({"kind": "text_in_file", "path": "ok.py", "must_include": "x"}),
                "--exam-fragment",
                "pin this sentence",
                "--evidence",
                "too-short",
                "--area",
                "ok.py",
            ]
        )
        self.assertNotEqual(0, code)
        self.assertIn("20", err)
        code, _out, err = _cli(
            [
                "probe",
                "insert",
                str(self.root),
                "--observation",
                json.dumps({"path": "ok.py", "must_include": "x = 1"}),
                "--exam-fragment",
                "pin this sentence",
                "--evidence",
                EVIDENCE,
                "--area",
                "ok.py",
            ]
        )
        self.assertNotEqual(0, code)
        self.assertIn("kind", err.lower())
        code, _out, err = _cli(
            [
                "probe",
                "insert",
                str(self.root),
                "--observation",
                json.dumps({"kind": "hash", "path": "ok.py"}),
                "--exam-fragment",
                "pin this sentence",
                "--evidence",
                EVIDENCE,
                "--area",
                "ok.py",
            ]
        )
        self.assertNotEqual(0, code)
        self.assertIn("command or text_in_file", err)

    def test_insert_store_is_outside_repo_and_duplicate_id_refused(self) -> None:
        help_code, help_out, _err = _cli(["probe", "insert", "--help"])
        self.assertEqual(0, help_code)
        self.assertIn("duplicate id is refused", help_out.lower())
        observation = {"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"}
        first = call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": observation,
                "exam_fragment": "file still contains x = 1",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
            },
        )
        self.assertEqual("armed", first["state"])
        store = Path(str(first["store"]))
        self.assertTrue(store.is_relative_to(self.home))
        self.assertFalse(store.is_relative_to(self.root))
        self.assertFalse(any(path.name == "probes.json" for path in self.root.rglob("*")))
        with self.assertRaisesRegex(Exception, "duplicate"):
            call(
                "ag_probe_insert",
                {
                    "root": str(self.root),
                    "observation": observation,
                    "exam_fragment": "file still contains x = 1",
                    "evidence": EVIDENCE,
                    "area": ["ok.py"],
                },
            )
        listed = call("ag_probe_list", {"root": str(self.root)})
        self.assertEqual(1, len(listed["probes"]))
        listed_text = json.dumps(listed)
        self.assertNotIn("must_include", listed_text)
        self.assertNotIn(EVIDENCE, listed_text)
        self.assertNotIn("observation", listed["probes"][0])
        self.assertNotIn("evidence", listed["probes"][0])
        self.assertEqual("file still contains x = 1", listed["probes"][0]["exam_fragment"])
        code, out, err = _cli(["probe", "list", str(self.root)])
        self.assertEqual(0, code, err)
        cli_list = json.loads(out)
        self.assertNotIn("observation", cli_list["probes"][0])
        self.assertEqual(listed["probes"], cli_list["probes"])
        full = call("ag_probe_list", {"root": str(self.root), "full": True})
        self.assertEqual(["x = 1"], full["probes"][0]["observation"]["must_include"])
        self.assertEqual(EVIDENCE, full["probes"][0]["evidence"])
        help_code, help_out, _herr = _cli(["probe", "list", "--help"])
        self.assertEqual(0, help_code)
        self.assertIn("critic", help_out.lower())
        self.assertIn("worker channel", help_out.lower())

    def test_command_and_text_in_file_green_and_red(self) -> None:
        green_cmd = call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {
                    "kind": "command",
                    "argv": [PY, "-c", "print('needle-ok')"],
                    "expect_exit": 0,
                    "stdout_contains": "needle-ok",
                },
                "exam_fragment": "command still prints needle-ok",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "cmd-green",
            },
        )
        red_cmd = call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {
                    "kind": "command",
                    "argv": [PY, "-c", "raise SystemExit(2)"],
                    "expect_exit": 0,
                },
                "exam_fragment": "command should exit 0",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "cmd-red",
            },
        )
        green_text = call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
                "exam_fragment": "ok.py contains x = 1",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "text-green",
            },
        )
        red_text = call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {"kind": "text_in_file", "path": "ok.py", "must_include": "not-in-file"},
                "exam_fragment": "ok.py contains not-in-file",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "text-red",
            },
        )
        ran = call("ag_probe_run", {"root": str(self.root)})
        by_id = {row["id"]: row for row in ran["results"]}
        self.assertEqual("green", by_id[green_cmd["id"]]["verdict"])
        self.assertEqual(0, by_id[green_cmd["id"]]["exit"])
        self.assertIn("needle-ok", by_id[green_cmd["id"]]["tail"])
        self.assertEqual("red", by_id[red_cmd["id"]]["verdict"])
        self.assertEqual(2, by_id[red_cmd["id"]]["exit"])
        self.assertEqual("green", by_id[green_text["id"]]["verdict"])
        self.assertEqual("red", by_id[red_text["id"]]["verdict"])
        self.assertIn("not-in-file", by_id[red_text["id"]]["tail"])

    def test_green_reaches_ttl_archives_and_red_rearms(self) -> None:
        empty = call("ag_probe_run", {"root": str(self.root)})
        self.assertEqual([], empty["results"])
        call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {"kind": "text_in_file", "path": "ok.py", "must_include": "x = 1"},
                "exam_fragment": "ok.py contains x = 1",
                "evidence": EVIDENCE,
                "area": ["ok.py"],
                "id": "ttl-pin",
                "ttl_quiet_loops": 2,
            },
        )
        first = call("ag_probe_run", {"root": str(self.root)})
        self.assertEqual("armed", first["results"][0]["state"])
        self.assertEqual("green", first["results"][0]["verdict"])
        second = call("ag_probe_run", {"root": str(self.root)})
        self.assertEqual("archived", second["results"][0]["state"])
        listed = call("ag_probe_list", {"root": str(self.root)})
        row = listed["probes"][0]
        self.assertEqual("archived", row["state"])
        self.assertEqual(2, row["quiet_count"])
        self.assertEqual("ok.py contains x = 1", row["exam_fragment"])
        self.assertEqual(["ok.py"], row["area"])
        skipped = call("ag_probe_run", {"root": str(self.root)})
        self.assertEqual([], skipped["results"])
        (self.root / "ok.py").write_text("x = 0\n", encoding="utf-8")
        awakened = call("ag_probe_run", {"root": str(self.root), "path": ["ok.py"], "awaken": True})
        self.assertEqual(1, len(awakened["results"]))
        self.assertEqual("red", awakened["results"][0]["verdict"])
        self.assertEqual("armed", awakened["results"][0]["state"])
        listed = call("ag_probe_list", {"root": str(self.root)})
        self.assertEqual("armed", listed["probes"][0]["state"])
        self.assertEqual(0, listed["probes"][0]["quiet_count"])

    def test_critic_pack_json_has_no_forbidden_conclusion_keys(self) -> None:
        call(
            "ag_probe_insert",
            {
                "root": str(self.root),
                "observation": {"kind": "text_in_file", "path": "mod.py", "must_include": "import ok"},
                "exam_fragment": "mod.py still imports ok",
                "evidence": EVIDENCE,
                "area": ["mod.py"],
                "id": "mod-import",
            },
        )
        (self.root / "mod.py").write_text("import ok\nvalue = 3\n", encoding="utf-8")
        code, out, err = _cli(
            [
                "critic-pack",
                str(self.root),
                "--exam",
                "user: keep import ok\nportrait: mod.py still imports ok",
            ]
        )
        self.assertEqual(0, code, err)
        pack = json.loads(out)
        self.assertEqual(
            {"schema", "exam", "diff", "changed_files", "neighbors", "probes", "this_ticket_checks"},
            set(pack),
        )
        self.assertEqual([], pack.get("this_ticket_checks"))
        forbidden = {"proof", "product", "passed", "guidance", "lineage", "messages", "tool_trace"}
        self.assertFalse(forbidden & set(pack))
        self.assertIn("import ok", pack["exam"])
        self.assertTrue(any(item["path"] == "mod.py" for item in pack["changed_files"]))
        self.assertIn("ok.py", pack["neighbors"])
        self.assertNotIn("sys.py", pack["neighbors"])
        self.assertEqual(1, len(pack["probes"]))
        self.assertEqual("green", pack["probes"][0]["verdict"])
        prompt_code, prompt_out, _err = _cli(["critic-prompt"])
        self.assertEqual(0, prompt_code)
        self.assertIn("不许改文件", prompt_out)
        self.assertIn("UNPROVEN", prompt_out)
        self.assertIn("ag_probe_insert", prompt_out)
        self.assertIn("没有工地", prompt_out)
        self.assertIn("不是开关", prompt_out)
        self.assertIn("this_ticket_checks", prompt_out)
        self.assertIn("tests/", prompt_out)

    def test_critic_pack_does_not_change_probe_lifetime(self) -> None:
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
        self.assertEqual("armed", before["state"])
        self.assertEqual(0, before["quiet_count"])
        (self.root / "ok.py").write_text("x = 1\n# pack-touch\n", encoding="utf-8")
        first_code, first_out, first_err = _cli(
            ["critic-pack", str(self.root), "--exam", "user: keep x = 1\nportrait: ok.py still has x = 1"]
        )
        self.assertEqual(0, first_code, first_err)
        first_pack = json.loads(first_out)
        self.assertEqual(1, len(first_pack["probes"]))
        self.assertEqual("green", first_pack["probes"][0]["verdict"])
        self.assertEqual("armed", first_pack["probes"][0]["state"])
        second_code, second_out, second_err = _cli(
            ["critic-pack", str(self.root), "--exam", "user: keep x = 1\nportrait: ok.py still has x = 1"]
        )
        self.assertEqual(0, second_code, second_err)
        second_pack = json.loads(second_out)
        self.assertEqual("armed", second_pack["probes"][0]["state"])
        self.assertEqual("green", second_pack["probes"][0]["verdict"])
        after = call("ag_probe_list", {"root": str(self.root), "full": True})["probes"][0]
        self.assertEqual(before["state"], after["state"])
        self.assertEqual(before["quiet_count"], after["quiet_count"])
        self.assertEqual(before["ttl_quiet_loops"], after["ttl_quiet_loops"])
        self.assertEqual(before["observation"], after["observation"])
        self.assertEqual(before["exam_fragment"], after["exam_fragment"])
        self.assertEqual(0, after["quiet_count"])
        self.assertEqual("armed", after["state"])
        ran = call("ag_probe_run", {"root": str(self.root)})
        self.assertEqual("green", ran["results"][0]["verdict"])
        self.assertEqual(1, call("ag_probe_list", {"root": str(self.root)})["probes"][0]["quiet_count"])
        self.assertEqual("armed", call("ag_probe_list", {"root": str(self.root)})["probes"][0]["state"])


if __name__ == "__main__":
    unittest.main()

