"""Daily enroll gate. LoopTests stay off this lamp."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("test_critic_run", "test_lanes", "test_probe")


def load_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    tests_dir = str(ROOT / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    for name in NAMES:
        suite.addTests(loader.loadTestsFromName(name))
    return suite


def main() -> int:
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(load_suite())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
