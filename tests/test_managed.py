from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.managed import add_project, load_managed, managed_path, project_snapshot
from ag.queue import add_exists, run_queue


class ManagedTests(unittest.TestCase):
    def test_register_other_project_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            other = Path(directory) / "app"
            other.mkdir()
            (other / "keep.txt").write_text("x", encoding="utf-8")
            home = Path(directory) / "home"
            home.mkdir()
            import ag.managed as managed

            original = managed.managed_path

            def fake_path() -> Path:
                return home / ".ag" / "managed.json"

            managed.managed_path = fake_path  # type: ignore[method-assign]
            try:
                item = add_project(other, note="other")
                self.assertEqual(str(other.resolve()), item["root"])
                add_exists(other, "keep.txt")
                run_queue(other)
                snap = project_snapshot(other)
                self.assertEqual(1, len(snap["items"]))
                self.assertTrue(snap["items"][0]["trusted"])
                blob = load_managed()
                self.assertEqual(1, len(blob["projects"]))
            finally:
                managed.managed_path = original  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()
