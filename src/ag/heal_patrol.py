"""Heal-lane patrol. Scan for diseases, plant heal- needles, emit a repair portrait.

Does not write the product tree or refuse finish. Optional critic chat is unused in tests.
"""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, lookup_project, real_root
from .probe import insert
from .store import insert_heal_event

SCHEMA = "ag.heal-patrol.v1"
DEFAULT_MAX_LINES = 800
MIN_EVIDENCE = 20


def _max_lines(raw: Any) -> int:
    if raw not in (None, ""):
        try:
            value = int(raw)
            if value >= 1:
                return value
        except (TypeError, ValueError):
            pass
    env = os.environ.get("AG_HEAL_PATROL_MAX_LINES", "").strip()
    if env:
        try:
            value = int(env)
            if value >= 1:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_LINES


def _tracked(tree: Path) -> list[str]:
    ran = subprocess.run(
        ["git", "-C", str(tree), "ls-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if ran.returncode != 0:
        return []
    names: list[str] = []
    for line in ran.stdout.splitlines():
        rel = line.strip().strip('"').replace("\\", "/")
        if rel and rel not in names:
            names.append(rel)
    return names


def _is_glue(src: str) -> bool:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return False
    body: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            continue
        body.append(node)
    if not body:
        return False

    def _ok(node: ast.AST) -> bool:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return True
        if isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return True
        return False

    if not all(_ok(node) for node in body):
        return False
    return any(isinstance(node, ast.ImportFrom) for node in body)


def _evidence(text: str) -> str:
    blob = " ".join((text or "").split())
    if len(blob) >= MIN_EVIDENCE:
        return blob[:400]
    pad = " patrol-scan-evidence"
    return (blob + pad)[:MIN_EVIDENCE] if len(blob + pad) < MIN_EVIDENCE else (blob + pad)


def _line_count(path: Path) -> int:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def scan(tree: Path, *, max_lines: int) -> list[dict[str, Any]]:
    diseases: list[dict[str, Any]] = []
    for rel in _tracked(tree):
        path = tree / rel.replace("/", os.sep)
        if not path.is_file():
            continue
        n = _line_count(path)
        if n >= max_lines:
            diseases.append(
                {
                    "kind": "oversized",
                    "path": rel,
                    "exam_fragment": f"{rel} is over {max_lines} lines ({n})",
                    "lines": n,
                    "snippet": f"{rel} line_count={n} threshold={max_lines}",
                    "threshold": max_lines,
                }
            )
        if not rel.endswith(".py"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _is_glue(src):
            diseases.append(
                {
                    "kind": "glue",
                    "path": rel,
                    "exam_fragment": f"{rel} is a pure re-export barrel",
                    "snippet": src[:400] or f"{rel} glue-import-only",
                }
            )
    return diseases


def _heal_id(kind: str, rel: str) -> str:
    digest = hashlib.sha256(f"{kind}:{rel}".encode("utf-8")).hexdigest()[:12]
    return f"heal-{digest}"


def _oversized_observation(rel: str, threshold: int) -> dict[str, Any]:
    code = (
        "from pathlib import Path\n"
        f"p = Path({rel!r})\n"
        "n = sum(1 for _ in p.open(encoding='utf-8', errors='replace')) if p.is_file() else 0\n"
        f"raise SystemExit(0 if n < {int(threshold)} else 1)\n"
    )
    return {"kind": "command", "argv": [sys.executable, "-c", code], "expect_exit": 0}


def _glue_observation(rel: str) -> dict[str, Any]:
    code = (
        "import ast\n"
        "from pathlib import Path\n"
        f"p = Path({rel!r})\n"
        "src = p.read_text(encoding='utf-8', errors='replace') if p.is_file() else ''\n"
        "try:\n"
        "    tree = ast.parse(src)\n"
        "except (SyntaxError, ValueError):\n"
        "    raise SystemExit(0)\n"
        "body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, 'value', None), ast.Constant))]\n"
        "def ok(n):\n"
        "    if isinstance(n, (ast.Import, ast.ImportFrom)): return True\n"
        "    if isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id == '__all__' for t in n.targets): return True\n"
        "    return False\n"
        "raise SystemExit(0 if (not body or not all(ok(n) for n in body) or not any(isinstance(n, ast.ImportFrom) for n in body)) else 1)\n"
    )
    return {"kind": "command", "argv": [sys.executable, "-c", code], "expect_exit": 0}


def _portrait(diseases: list[dict[str, Any]]) -> str:
    if not diseases:
        return (
            "Done looks like: no patrol diseases; do not open a repair ticket.\n"
            "Surfaces: none.\n"
            "Out of result: do not start a task for this patrol."
        )
    names = [str(item.get("exam_fragment") or item.get("path") or "") for item in diseases]
    listed = "; ".join(n for n in names if n)
    return (
        "Done looks like: the listed diseases are gone — oversized files split or shortened, "
        "pure re-export barrels replaced with real modules or deleted.\n"
        f"Surfaces: {listed}. Empty: no such files. Success: heal- needles on those paths go green.\n"
        "Out of result: do not rewrite unrelated modules; do not open extra tickets; do not inspect the ruler."
    )


def patrol(root: Path, *, tree: Path | None = None, max_lines: Any = None) -> dict[str, Any]:
    enrolled = real_root(root)
    if lookup_project(enrolled) is None:
        raise ChainBroken("not enrolled")
    scan_root = real_root(Path(tree)) if tree is not None else enrolled
    limit = _max_lines(max_lines)
    diseases = scan(scan_root, max_lines=limit)
    needles: list[str] = []
    summaries: list[dict[str, str]] = []
    for item in diseases:
        rel = str(item.get("path") or "")
        kind = str(item.get("kind") or "")
        fragment = str(item.get("exam_fragment") or "")
        if not rel or not kind or not fragment:
            continue
        probe_id = _heal_id(kind, rel)
        if kind == "oversized":
            observation = _oversized_observation(rel, int(item.get("threshold") or limit))
        else:
            observation = _glue_observation(rel)
        try:
            insert(
                enrolled,
                observation=observation,
                exam_fragment=fragment,
                evidence=_evidence(str(item.get("snippet") or fragment)),
                area=[rel],
                id=probe_id,
            )
            needles.append(probe_id)
        except ChainBroken:
            continue
        summaries.append({"kind": kind, "path": rel, "exam_fragment": fragment})
    portrait = _portrait(summaries)
    heal_report_id = insert_heal_event(
        enrolled,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "needles": needles,
            "diseases": summaries,
            "repair_portrait": portrait,
        },
    )
    return {
        "schema": SCHEMA,
        "root": str(enrolled),
        "tree": str(scan_root),
        "heal_report_id": heal_report_id,
        "needles": needles,
        "diseases": summaries,
        "repair_portrait": portrait,
    }


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "ag_heal_patrol":
        raise ChainBroken(f"heal has no tool {name}")
    tree = args.get("tree")
    return patrol(
        Path(str(args.get("root") or "")),
        tree=Path(str(tree)) if tree else None,
        max_lines=args.get("max_lines"),
    )
