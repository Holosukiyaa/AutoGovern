"""Read-only critic pack. Exam + diff + changed files + one-hop neighbors + probe tails.

Not a worker ticket. Does not write product files, call an LLM, or refuse finish.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

from .managed import ChainBroken, real_root
from .probe import run as run_probes

PACK_SCHEMA = "ag.critic-pack.v1"
MAX_FILE_CHARS = 100_000
PROMPT_NAME = "critic_prompt.md"

TOOLS = [
    {
        "name": "ag_critic_pack",
        "description": (
            "Build a read-only exam pack: exam, diff, changed files, one-hop imports, matching probe tails. "
            "Not a worker ticket. Does not include proof, product, or passed as a conclusion."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "exam": {"type": "string"},
                "exam_file": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
            },
            "required": ["root"],
        },
    }
]


def prompt_path() -> Path:
    return Path(__file__).with_name(PROMPT_NAME)


def prompt_text() -> str:
    path = prompt_path()
    if not path.is_file():
        raise ChainBroken(f"missing {PROMPT_NAME}")
    return path.read_text(encoding="utf-8")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _posix(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


def _read_exam(exam: str | None, exam_file: str | None) -> str:
    file_path = str(exam_file or "").strip()
    text = exam if exam is not None else ""
    if file_path and not str(text).strip():
        path = Path(file_path)
        if not path.is_file():
            raise ChainBroken(f"exam file not found: {path}")
        return path.read_text(encoding="utf-8", errors="replace")
    if not str(text).strip() and not file_path:
        raise ChainBroken("exam is required")
    return str(text)


def _changed_names(repo: Path, base: str, head: str) -> tuple[str, list[str]]:
    if base and head:
        diff = _git(repo, "diff", base, head)
        names = _git(repo, "diff", "--name-only", base, head)
        extra: list[str] = []
    elif base:
        diff = _git(repo, "diff", base)
        names = _git(repo, "diff", "--name-only", base)
        extra_run = _git(repo, "ls-files", "-o", "--exclude-standard")
        extra = extra_run.stdout.splitlines() if extra_run.returncode == 0 else []
    elif head:
        raise ChainBroken("--head requires --base")
    else:
        diff = _git(repo, "diff", "HEAD")
        names = _git(repo, "diff", "--name-only", "HEAD")
        extra_run = _git(repo, "ls-files", "-o", "--exclude-standard")
        extra = extra_run.stdout.splitlines() if extra_run.returncode == 0 else []
    diff_text = diff.stdout or ""
    files: list[str] = []
    for raw in list(names.stdout.splitlines()) + extra:
        rel = _posix(raw)
        if rel and rel not in files:
            files.append(rel)
    return diff_text, files


def _file_entry(repo: Path, rel: str) -> dict[str, Any]:
    path = repo / rel
    if not path.is_file():
        return {"path": rel, "content": ""}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"path": rel, "content": "", "truncated": True}
    if len(text) > MAX_FILE_CHARS:
        return {"path": rel, "content": text[:MAX_FILE_CHARS], "truncated": True}
    return {"path": rel, "content": text}


def _candidate_files(base: Path) -> list[Path]:
    return [base.with_suffix(".py"), base / "__init__.py"]


def _existing_rel(repo: Path, path: Path) -> str | None:
    try:
        resolved = path.resolve()
        repo_res = repo.resolve()
        rel = resolved.relative_to(repo_res)
    except (OSError, ValueError):
        return None
    if resolved.is_file():
        return rel.as_posix()
    return None


def _resolve_module(repo: Path, source: Path, module: str, level: int) -> str | None:
    if level:
        base = source.parent
        for _ in range(max(0, level - 1)):
            base = base.parent
            try:
                base.resolve().relative_to(repo.resolve())
            except (OSError, ValueError):
                return None
        if module:
            base = base.joinpath(*module.split("."))
        for candidate in _candidate_files(base):
            rel = _existing_rel(repo, candidate)
            if rel:
                return rel
        return None
    if not module:
        return None
    parts = Path(*module.split("."))
    roots = [repo, repo / "src", source.parent]
    for root in roots:
        for candidate in _candidate_files(root / parts):
            rel = _existing_rel(repo, candidate)
            if rel:
                return rel
    return None


def _neighbors_from_file(repo: Path, rel: str, content: str) -> list[str]:
    if not rel.endswith(".py"):
        return []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []
    source = repo / rel
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _resolve_module(repo, source, alias.name, 0)
                if hit and hit not in found and hit != rel:
                    found.append(hit)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = int(node.level or 0)
            if level and not module:
                for alias in node.names:
                    hit = _resolve_module(repo, source, alias.name, level)
                    if hit and hit not in found and hit != rel:
                        found.append(hit)
                continue
            hit = _resolve_module(repo, source, module, level)
            if hit and hit not in found and hit != rel:
                found.append(hit)
    return found


def neighbors(repo: Path, changed_files: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for item in changed_files:
        rel = str(item.get("path") or "")
        content = str(item.get("content") or "")
        for hit in _neighbors_from_file(repo, rel, content):
            if hit not in out:
                out.append(hit)
    return out


def pack(
    root: Path,
    *,
    exam: str | None = None,
    exam_file: str | None = None,
    base: str = "",
    head: str = "",
) -> dict[str, Any]:
    repo = real_root(root)
    exam_text = _read_exam(exam, exam_file)
    diff_text, names = _changed_names(repo, str(base or "").strip(), str(head or "").strip())
    changed = [_file_entry(repo, rel) for rel in names]
    hops = neighbors(repo, changed)
    probe_run = run_probes(repo, paths=names or None, awaken=False) if names else {"results": []}
    results = probe_run.get("results") if isinstance(probe_run, dict) else []
    if not isinstance(results, list):
        results = []
    return {
        "schema": PACK_SCHEMA,
        "exam": exam_text,
        "diff": diff_text,
        "changed_files": changed,
        "neighbors": hops,
        "probes": results,
    }


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name != "ag_critic_pack":
        raise ChainBroken(f"see has no tool {name}")
    return pack(
        Path(str(args.get("root") or "")),
        exam=args.get("exam"),
        exam_file=str(args.get("exam_file") or "") or None,
        base=str(args.get("base") or ""),
        head=str(args.get("head") or ""),
    )
