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
from .probe import evaluate, insert, missing_fragments
from .store import insert_heal_event

SCHEMA = "ag.heal-patrol.v1"
DEFAULT_MAX_LINES = 800
MIN_EVIDENCE = 20
GEARS = ("probes", "local", "repo", "mess")
MESS_FILES = 8
MESS_LINES = 80


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


def _posix(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


def _path_allowed(rel: str, paths: list[str]) -> bool:
    item = _posix(rel)
    if not item:
        return False
    for raw in paths:
        prefix = _posix(raw)
        if not prefix:
            continue
        if item == prefix or item.startswith(prefix + "/") or prefix.startswith(item + "/"):
            return True
    return False


def scan(tree: Path, *, max_lines: int, paths: list[str] | None = None) -> list[dict[str, Any]]:
    diseases: list[dict[str, Any]] = []
    for rel in _tracked(tree):
        if paths is not None and not _path_allowed(rel, paths):
            continue
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


def _probe_portrait(red: list[dict[str, str]]) -> str:
    if not red:
        return (
            "Done looks like: only existing needles were checked and none were red; "
            "do not open a repair ticket for this patrol unless a needle is red.\n"
            "Surfaces: none.\n"
            "Out of result: do not start a task for this patrol."
        )
    listed = "; ".join(str(item.get("exam_fragment") or item.get("id") or "") for item in red)
    return (
        "Done looks like: only existing needles were checked. Red needles are listed; "
        "do not open a repair ticket for patrol itself unless those reds need a dedicated repair.\n"
        f"Surfaces: {listed}.\n"
        "Out of result: do not plant new needles from this gear; do not inspect the ruler."
    )


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


def _plant(enrolled: Path, diseases: list[dict[str, Any]], limit: int) -> tuple[list[str], list[dict[str, str]]]:
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
    return needles, summaries


def _emit(enrolled: Path, scan_root: Path, gear: str, needles: list[str], diseases: list[dict[str, Any]], portrait: str) -> dict[str, Any]:
    heal_report_id = insert_heal_event(
        enrolled,
        {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "needles": needles,
            "diseases": diseases,
            "repair_portrait": portrait,
        },
    )
    return {
        "schema": SCHEMA,
        "root": str(enrolled),
        "tree": str(scan_root),
        "gear": gear,
        "heal_report_id": heal_report_id,
        "needles": needles,
        "diseases": diseases,
        "repair_portrait": portrait,
    }


def _as_paths(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    raise ChainBroken("paths must be a string or list of strings")


def _mess_excerpt(tree: Path, diseases: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    seen: set[str] = set()
    for item in diseases:
        rel = str(item.get("path") or "")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        path = tree / rel.replace("/", os.sep)
        lines: list[str] = []
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= MESS_LINES:
                        break
                    lines.append(line.rstrip("\n"))
        except OSError:
            lines = []
        chunks.append(rel + "\n" + "\n".join(lines))
        if len(chunks) >= MESS_FILES:
            break
    return "\n\n".join(chunks)


def _mess_portrait(enrolled: Path, scan_root: Path, summaries: list[dict[str, str]], diseases: list[dict[str, Any]]) -> str:
    base = _portrait(summaries)
    from .critic import _configured, complete_chat, load_config

    cfg = load_config(enrolled)
    if not _configured(cfg):
        return base + "\nUNPROVEN architecture judgment: critic not configured; mess narrative is script-only."
    excerpt = _mess_excerpt(scan_root, diseases)
    payload = {"diseases": summaries, "excerpts": excerpt}
    messages = [
        {
            "role": "system",
            "content": (
                "Write a short repair portrait from the disease list and excerpts only. "
                "Do not insert probes. Do not use worker diary or critic-last."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        extra = complete_chat(cfg, messages)
    except Exception:
        return base + "\nUNPROVEN architecture judgment: critic call failed."
    text = (extra or "").strip()
    if not text:
        return base + "\nUNPROVEN architecture judgment: empty critic reply."
    return base + "\n" + text[:4000]


def patrol(
    root: Path,
    *,
    gear: str | None = None,
    tree: Path | None = None,
    max_lines: Any = None,
    paths: Any = None,
) -> dict[str, Any]:
    enrolled = real_root(root)
    if lookup_project(enrolled) is None:
        raise ChainBroken("not enrolled")
    mode = str(gear or "").strip().casefold()
    if mode not in GEARS:
        raise ChainBroken("gear is required: probes|local|repo|mess")
    scan_root = real_root(Path(tree)) if tree is not None else enrolled
    limit = _max_lines(max_lines)
    wanted = _as_paths(paths)
    if mode == "local" and not wanted:
        raise ChainBroken("local gear requires --path / paths")
    if mode == "probes":
        ran = evaluate(enrolled, awaken=False, tree=scan_root)
        red_ids = [
            str(row.get("id") or "")
            for row in (ran.get("results") or [])
            if isinstance(row, dict) and row.get("verdict") == "red" and row.get("id")
        ]
        frags = missing_fragments(enrolled, red_ids)
        diseases = [
            {"id": rid, "exam_fragment": frag}
            for rid, frag in zip(red_ids, frags)
        ]
        return _emit(enrolled, scan_root, mode, [], diseases, _probe_portrait(diseases))
    path_filter = wanted if mode == "local" else None
    found = scan(scan_root, max_lines=limit, paths=path_filter)
    needles, summaries = _plant(enrolled, found, limit)
    if mode == "mess":
        portrait = _mess_portrait(enrolled, scan_root, summaries, found)
    else:
        portrait = _portrait(summaries)
    return _emit(enrolled, scan_root, mode, needles, summaries, portrait)


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "ag_heal_patrol":
        raise ChainBroken(f"heal has no tool {name}")
    tree = args.get("tree")
    return patrol(
        Path(str(args.get("root") or "")),
        gear=str(args.get("gear") or ""),
        tree=Path(str(tree)) if tree else None,
        max_lines=args.get("max_lines"),
        paths=args.get("paths") or args.get("path"),
    )
