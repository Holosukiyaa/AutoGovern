"""Git hook entry. Lives beside loop so loop.py stays under the oversized-file needle."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def hook_main() -> int:
    from .catalog import enabled
    from .loop import (
        PREV_UNSET,
        _canonical_root,
        _deliver_token_ok,
        _is_canonical,
        _run_previous_pre_commit,
        git,
    )
    from .managed import ChainBroken, lookup_project
    from .see import note as usage_note

    try:
        toplevel = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
        canonical = _canonical_root(toplevel)
    except ChainBroken:
        sys.stderr.write("ag: hook cannot resolve git root; refusing commit\n")
        return 1
    if _is_canonical(toplevel):
        usage_note(canonical, "ship", 3, "block", "canonical commit")
        sys.stderr.write("ag: canonical checkout is not a work site; use ag_start\n")
        return 1
    if os.environ.get("AG_DELIVER") != "1":
        usage_note(canonical, "ship", 4, "block", "worktree commit")
        sys.stderr.write("ag: only ag_finish can commit\n")
        return 1
    if not _deliver_token_ok(canonical):
        usage_note(canonical, "ship", 4, "block", "deliver token")
        sys.stderr.write("ag: deliver token mismatch; only ag_finish can commit\n")
        return 1
    if lookup_project(canonical) is None:
        return 0
    if not enabled(canonical, "ship", 10):
        return 0
    code = _run_previous_pre_commit(toplevel)
    previous = git(toplevel, "config", "--local", "--get", "ag.previousHooksPath", check=False)
    if previous and previous != PREV_UNSET:
        usage_note(canonical, "ship", 10, "help" if code == 0 else "block", f"exit {code}")
    return code
