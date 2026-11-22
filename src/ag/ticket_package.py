"""Ticket packages: validation, exact sealing, opening baselines and integrity gates."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager, nullcontext
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .history import digest
from .managed import ChainBroken
from .store import project_dir, replace_file

HEADINGS = ("要做成什么", "怎样算做成", "不做什么", "需要你拍板的事")
CHECK_TIMEOUT_S = 300


def draft_dir(root: Path) -> Path:
    return project_dir(root) / "draft"


def sealed_dir(root: Path, task_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ChainBroken("seal-invalid: task_id")
    return project_dir(root) / "tickets" / task_id


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def ensure_template(root: Path) -> tuple[Path, bool]:
    folder = draft_dir(root)
    if folder.exists():
        return folder / "ticket.md", False
    ticket = "\n\n".join("## " + h + "\n" + ("无" if h == HEADINGS[-1] else "请填写本段人话说明。") for h in HEADINGS) + "\n"
    spec = {"schema": "ag.ticket.v2", "kind": "feature", "origin": {"user_words": [], "source": "请填写来源/日期"},
            "results": [{"id": "r1", "text": "请描述触发条件与正向结果，以及非法输入或边界条件下的明确拒绝结果"}],
            "scope": {"allow": ["src/**"], "deny": [], "docs": []},
            "redlines": [{"text": "请填写具体边界并注明来源", "source": "ticket"}],
            "budget": {"files": 1, "lines": 100}, "checks": [{"file": "checks/check_example.py", "kind": "target", "serves": ["r1"]}]}
    atomic_write(folder / "ticket.md", ticket.encode("utf-8"))
    write_json(folder / "spec.json", spec)
    atomic_write(folder / "checks/check_example.py", b'raise SystemExit("Replace with a real result check before start")\n')
    return folder / "ticket.md", True


def _invalid(field: str, detail: str = "invalid value") -> None:
    raise ChainBroken(f"spec-invalid: {field}: {detail}")


def _text(value: Any, field: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        _invalid(field, f"expected text of at least {minimum} characters")
    return value


def _relative(value: Any, field: str) -> PurePosixPath:
    _text(value, field)
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        _invalid(field, "use a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        _invalid(field, "path must stay inside the package")
    return path


def file_hashes(folder: Path, *, ignore_pycache: bool = False) -> dict[str, str]:
    hashes = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if ignore_pycache and "__pycache__" in path.relative_to(folder).parts:
            continue
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ChainBroken(f"sealed-check-changed: links are not allowed: {rel}")
        if path.is_file() and rel != "seal.json":
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def draft_changed(root: Path, seal: dict[str, Any]) -> bool:
    try:
        return file_hashes(draft_dir(root)) != seal["files"]
    except (OSError, ChainBroken):
        return True


def load_draft(root: Path) -> dict[str, Any]:
    folder = draft_dir(root)
    if not folder.is_dir() or not all((folder / name).is_file() for name in ("ticket.md", "spec.json")):
        raise ChainBroken(f"ticket-package-missing: write ticket.md, spec.json and checks/ in {folder}")
    try:
        text = (folder / "ticket.md").read_text(encoding="utf-8")
        raw_spec = (folder / "spec.json").read_text(encoding="utf-8")
        spec = json.loads(raw_spec)
    except (ValueError, UnicodeError) as exc:
        _invalid("spec.json", str(exc))
    if not isinstance(spec, dict):
        _invalid("spec.json", "expected object")
    if spec.get("schema") != "ag.ticket.v2":
        _invalid("schema")
    if spec.get("kind") not in ("feature", "fix", "slim"):
        _invalid("kind")
    if spec["kind"] == "fix":
        _text(spec.get("root_cause"), "root_cause", 20)
    origin = spec.get("origin")
    words = origin.get("user_words") if isinstance(origin, dict) else None
    if not isinstance(words, list) or not words:
        _invalid("origin.user_words", "provide at least one user quotation")
    for i, word in enumerate(words):
        _text(word, f"origin.user_words[{i}]")
    _text(origin.get("source"), "origin.source")
    sections = {}
    for match in re.finditer(r"(?m)^##\s+([^\r\n]+)\s*$", text):
        sections.setdefault(match.group(1).strip(), []).append((match.start(), match.end()))
    for heading in HEADINGS:
        spans = sections.get(heading, [])
        if len(spans) != 1:
            raise ChainBroken(f"ticket-md-invalid: missing or duplicate section {heading}")
        start, end = spans[0]
        next_heading = re.search(r"(?m)^##\s+", text[end:])
        body = text[end:end + next_heading.start()] if next_heading else text[end:]
        if not body.strip():
            raise ChainBroken(f"ticket-md-invalid: empty section {heading}")
    results = spec.get("results")
    if not isinstance(results, list) or not results:
        _invalid("results")
    ids = set()
    for i, result in enumerate(results):
        if not isinstance(result, dict):
            _invalid(f"results[{i}]")
        rid = _text(result.get("id"), f"results[{i}].id")
        if rid in ids:
            _invalid("results", "duplicate id " + rid)
        ids.add(rid)
        _text(result.get("text"), f"results[{i}].text", 20)
    scope = spec.get("scope")
    if not isinstance(scope, dict):
        _invalid("scope")
    for key in ("allow", "deny", "docs"):
        patterns = scope.get(key, [])
        if not isinstance(patterns, list) or (key == "allow" and not patterns):
            _invalid("scope." + key)
        for i, pattern in enumerate(patterns):
            _relative(pattern, f"scope.{key}[{i}]")
    budget = spec.get("budget")
    if not isinstance(budget, dict):
        _invalid("budget")
    for key in ("files", "lines"):
        if type(budget.get(key)) is not int or budget[key] <= 0:
            _invalid("budget." + key, "expected positive integer")
    redlines = spec.get("redlines", [])
    if not isinstance(redlines, list):
        _invalid("redlines")
    for i, row in enumerate(redlines):
        if not isinstance(row, dict):
            _invalid(f"redlines[{i}]")
        _text(row.get("text"), f"redlines[{i}].text")
        if row.get("source") not in ("user", "standard", "ticket"):
            _invalid(f"redlines[{i}].source")
    continuation = spec.get("continuation_of", "")
    if not isinstance(continuation, str):
        _invalid("continuation_of")
    checks = spec.get("checks")
    if not isinstance(checks, list) or not checks:
        _invalid("checks")
    covered, seen_files = set(), set()
    for i, check in enumerate(checks):
        field = f"checks[{i}]"
        if not isinstance(check, dict):
            _invalid(field)
        rel = _relative(check.get("file"), field + ".file")
        path = folder.joinpath(*rel.parts)
        if len(rel.parts) < 2 or rel.parts[0] != "checks" or not re.fullmatch(r"check_.+\.py", rel.name) or not path.is_file() or not path.resolve().is_relative_to((folder / "checks").resolve()):
            _invalid(field + ".file", "expected an existing checks/check_*.py inside the package")
        if str(rel) in seen_files:
            _invalid(field + ".file", "duplicate check")
        seen_files.add(str(rel))
        if check.get("kind") not in ("target", "guard"):
            _invalid(field + ".kind")
        serves = check.get("serves")
        if not isinstance(serves, list) or not serves or any(not isinstance(r, str) for r in serves) or not (set(serves) <= ids or (check["kind"] == "guard" and serves == ["guard"])):
            _invalid(field + ".serves")
        if check["kind"] == "target":
            covered.update(serves)
    for rid in ids - covered:
        raise ChainBroken(f"result-uncovered: {rid}: add a target check")
    for path in folder.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            _invalid("checks", "package links are not allowed")
        if path.name == "seal.json" or path.suffix == ".tmp":
            _invalid(path.relative_to(folder).as_posix(), "reserved package file")
    from .guards import validate
    validate(root, spec, folder)
    return {"ticket": text, "spec": spec, "spec_text": raw_spec, "files": file_hashes(folder)}


def package_identity(seal: dict[str, Any]) -> str:
    return digest({name: seal[name] for name in ("task_id", "source_head", "files", "baseline", "ticket_review")})


def load_seal(root: Path, task: dict[str, Any], *, check_files: bool = True) -> dict[str, Any]:
    folder = sealed_dir(root, str(task["id"]))
    path = folder / "seal.json"
    if not path.exists():
        raise ChainBroken("legacy-ticket-format: no sealed package; use abandon then prepare draft/")
    try:
        seal = json.loads(path.read_text(encoding="utf-8"))
        if not (isinstance(seal, dict) and seal.get("schema") == "ag.seal.v1"):
            raise ValueError("missing or invalid seal field")
        if not (seal["task_id"] == task["id"] and seal["source_head"] == task["source_head"]):
            raise ValueError("missing or invalid seal field")
        if not (isinstance(seal["sealed_at"], str) and seal["sealed_at"]):
            raise ValueError("missing or invalid seal field")
        if not (isinstance(seal["files"], dict) and {"ticket.md", "spec.json"} <= seal["files"].keys()):
            raise ValueError("missing or invalid seal field")
        if not (all(isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for k, v in seal["files"].items())):
            raise ValueError("missing or invalid seal field")
        if not (isinstance(seal["baseline"], list) and seal["baseline"]):
            raise ValueError("missing or invalid seal field")
        if not (all(isinstance(row, dict) and row.get("kind") in {"target", "guard"} and isinstance(row.get("file"), str) and type(row.get("exit")) is int and isinstance(row.get("tail"), str) and isinstance(row.get("seconds"), (int, float)) for row in seal["baseline"])):
            raise ValueError("missing or invalid seal field")
        if not (isinstance(seal["ticket_review"], dict)):
            raise ValueError("missing or invalid seal field")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ChainBroken(f"seal-invalid: {path}: malformed seal") from exc
    if check_files:
        if file_hashes(folder) != seal["files"]:
            raise ChainBroken("sealed-check-changed: sealed files were modified, added or deleted")
        if task.get("intent_identity") and package_identity(seal) != task["intent_identity"]:
            raise ChainBroken("seal-invalid: sealed identity differs from the recorded review")
    return seal


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ChainBroken(f"baseline-source-error: {result.stderr.strip()}")


@contextmanager
def _source_copy(root: Path, source_head: str):
    """A detached, frozen opening checkout; always remove its worktree registration."""
    from .freeze import freeze_worktree, thaw_worktree

    with tempfile.TemporaryDirectory(prefix="ag-baseline-") as scratch:
        tree = Path(scratch) / "source"
        try:
            _git(root, "worktree", "add", "--detach", str(tree), source_head)
            freeze_worktree(tree)
            yield tree
        finally:
            if tree.exists():
                thaw_worktree(tree)
                _git(root, "worktree", "remove", "--force", str(tree))


def _baseline(folder: Path, worktree: Path, package: dict[str, Any]) -> list[dict[str, Any]]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(worktree / "src") + os.pathsep + str(worktree)
    baseline = []
    for check in package["spec"]["checks"]:
        started = time.perf_counter()
        try:
            result = subprocess.run([sys.executable, "-X", "utf8", str(folder / check["file"])], cwd=worktree, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT_S)
            code, tail = result.returncode, ((result.stdout or "") + (result.stderr or ""))[-1200:]
        except subprocess.TimeoutExpired:
            code, tail = 124, "baseline check timed out after 300s"
        row = {"file": check["file"], "kind": check["kind"], "exit": code, "tail": tail, "seconds": round(time.perf_counter() - started, 3)}
        baseline.append(row)
        if check["kind"] == "target" and code == 0:
            raise ChainBroken(f"baseline-target-green: {check['file']}")
        if check["kind"] == "guard" and code != 0:
            raise ChainBroken(f"baseline-guard-red: {check['file']}: {tail}")
    return baseline


@contextmanager
def prepare_package(root: Path, task: dict[str, Any], package: dict[str, Any], *, opening_tree: Path | None = None):
    """Prepare exact bytes, baseline and seal without changing any live ticket state."""
    folder = sealed_dir(root, task["id"])
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{task['id']}.pending-", dir=folder.parent) as scratch:
        pending = Path(scratch) / "package"
        pending.mkdir()
        for rel in package["files"]:
            atomic_write(pending / rel, (draft_dir(root) / rel).read_bytes())
        if file_hashes(pending) != package["files"]:
            raise ChainBroken("sealed-check-changed: draft changed while preparing; retry start")
        source = nullcontext(opening_tree) if opening_tree is not None else _source_copy(root, task["source_head"])
        with source as tree:
            baseline = _baseline(pending, tree, package)
        if file_hashes(pending) != package["files"]:
            raise ChainBroken("sealed-check-changed: baseline altered the prepared package")
        seal = {"schema": "ag.seal.v1", "task_id": task["id"], "source_head": task["source_head"],
                "sealed_at": datetime.now(timezone.utc).isoformat(), "files": package["files"],
                "baseline": baseline, "ticket_review": {}}
        write_json(pending / "seal.json", seal)
        yield pending, seal


@contextmanager
def install_prepared(root: Path, task: dict[str, Any], pending: Path):
    """Rollback until begin_review: package swap, task pointer and live permissions."""
    from .freeze import freeze_worktree, thaw_worktree

    folder = sealed_dir(root, task["id"])
    revisions = folder.with_name(folder.name + ".revisions")
    previous = revisions / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    task_path = project_dir(root) / "task.json"
    original_task = task_path.read_bytes() if task_path.exists() else None
    restore_writes = bool(task.get("intent_map_confirmed") and task.get("worktree_ready") and not task.get("thaw_error"))
    moved_old = installed = review_started = False

    def begin_review() -> None:
        nonlocal review_started
        review_started = True

    try:
        freeze_worktree(Path(task["worktree"]))
        if folder.exists():
            revisions.mkdir(exist_ok=True)
            folder.rename(previous)
            moved_old = True
        pending.rename(folder)
        installed = True
        yield begin_review
    except BaseException:
        if not review_started:
            if installed:
                folder.rename(pending)
            if moved_old:
                previous.rename(folder)
            if revisions.is_dir() and not any(revisions.iterdir()):
                revisions.rmdir()
            if original_task is not None:
                if task_path.read_bytes() != original_task:
                    atomic_write(task_path, original_task)
            else:
                task_path.unlink(missing_ok=True)
            if restore_writes:
                thaw_worktree(Path(task["worktree"]))
        raise


def complete_review(root: Path, task: dict[str, Any], seal: dict[str, Any]) -> None:
    review = task["ticket_review"]
    seal["ticket_review"] = {name: review.get(name) for name in ("outcome", "report_id")}
    write_json(sealed_dir(root, task["id"]) / "seal.json", seal)
    task["intent_identity"] = package_identity(seal)


def materials(root: Path, task_id: str) -> dict[str, Any]:
    folder = sealed_dir(root, task_id)
    spec_text = (folder / "spec.json").read_text(encoding="utf-8")
    spec = json.loads(spec_text)
    seal = json.loads((folder / "seal.json").read_text(encoding="utf-8"))
    return {"ticket.md": (folder / "ticket.md").read_text(encoding="utf-8"), "spec.json": spec_text,
            "results": spec["results"], "checks": [{**row, "source": (folder / row["file"]).read_text(encoding="utf-8")} for row in spec["checks"]], "baseline": seal["baseline"]}
