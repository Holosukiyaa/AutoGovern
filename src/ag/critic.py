"""Read-only critic pack and one-shot critic chat.

Not a worker ticket. Does not write product files or refuse finish.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root
from .probe import evaluate as evaluate_probes
from .store import event_count, insert_critic_event, list_critic_events

PACK_SCHEMA = "ag.critic-pack.v1"
RUN_SCHEMA = "ag.critic-run.v1"
CONFIG_GUIDE_SCHEMA = "ag.config-guide.v1"
MAX_FILE_CHARS = 100_000
MAX_INLINE_FILE_CHARS = 12_000
DIFF_WINDOW_RADIUS = 30
MAX_CHECK_FILE_BYTES = 64_000
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_BACKTICK_TOKEN_RE = re.compile(r"`([^`\n]+)`")
_FILE_TOKEN_RE = re.compile(r"[\w./\\-]+\.(?:py|ts|tsx|js|css|json|md|sqlite|rs|go)")
_SHORTCUT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("silent-except-pass", re.compile(r"\bexcept\b.*:\s*pass\b")),
    ("mock-or-fixture", re.compile(r"\b(?:unittest\.mock|MagicMock|monkeypatch|pytest\.fixture)\b")),
    ("todo-or-unimplemented", re.compile(r"\b(?:TODO|FIXME|NotImplementedError)\b")),
    ("suppression-directive", re.compile(r"(?:#\s*type:\s*ignore|#\s*noqa|@ts-ignore|eslint-disable|!important)")),
)
_EXCEPT_HEADER_RE = re.compile(r"^\s*except\b.*:\s*(?:#.*)?$")
_PASS_LINE_RE = re.compile(r"^\s*pass\b(?:\s*#.*)?$")
_ASSERT_SIGNAL_RE = re.compile(r"\b(?:assert|AssertionError|unittest)\b")
_BINARY_CHECK_SUFFIXES = {
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".sqlite",
    ".db",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".exe",
    ".dll",
    ".pyd",
    ".so",
}
PROMPT_NAME = "critic_prompt.md"
PROMPT_VERSION = "ag.critic.v1"
CONFIG_NAME = "critic.json"
REPORT_NAME = "critic-last.json"
LOG_NAME = "critic.jsonl"
LOG_SCHEMA = "ag.critic-log.v1"
DEFAULT_LOG_LIMIT = 20
DEFAULT_TIMEOUT = 60
DEFAULT_API_KEY_ENV = "AG_CRITIC_API_KEY"
_EVIDENCE_REF = re.compile(r"[\w./\\-一-鿿]+:\d+|portrait:\S+|probe:\S+")
_MODEL_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("openai", ("gpt", "o1", "o3", "o4", "openai", "chatgpt")),
    ("anthropic", ("claude", "anthropic")),
    ("google", ("gemini", "palm", "bard", "google")),
    ("xai", ("grok", "xai")),
    ("moonshot", ("kimi", "moonshot")),
    ("deepseek", ("deepseek",)),
    ("alibaba", ("qwen", "tongyi")),
    ("meta", ("llama", "meta")),
    ("mistral", ("mistral", "mixtral", "codestral")),
    ("cohere", ("command", "cohere")),
)


def model_family(model: str) -> str:
    normalized = model.strip().lower()
    if "/" in normalized:
        normalized = normalized.split("/")[-1]
    token = re.split(r"[^a-z0-9]+", normalized)[0] if normalized else ""
    for family, prefixes in _MODEL_FAMILIES:
        if any(token.startswith(prefix) for prefix in prefixes):
            return family
    return token or "unknown"


def same_family(regulator_model: str, worker_model: str) -> bool:
    if not regulator_model.strip() or not worker_model.strip():
        return False
    return model_family(regulator_model) == model_family(worker_model)

TOOLS = [
    {
        "name": "ag_critic_pack",
        "description": (
            "Build a read-only exam pack: exam, diff, changed files, one-hop imports, matching probe tails, "
            "this_ticket_checks from worktree .ag-check/. "
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
    },
    {
        "name": "ag_critic_run",
        "description": (
            "One read-only critic chat on the exam pack. No tools, no worktree. "
            "Does not refuse finish. Rejected is critique, not a finish gate."
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
    },
    {
        "name": "ag_critic_log",
        "description": "Read-only critic audit log. Newest last. Does not delete or refuse finish.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["root"],
        },
    },
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


def annotate_diff_with_lines(
    diff_text: str,
    max_chars: int = 48_000,
) -> tuple[str, dict[str, list[int]]]:
    touched_lines: dict[str, list[int]] = {}
    out_lines: list[str] = []
    rel = ""
    old_lineno = 0
    new_lineno = 0
    in_hunk = False

    def _record_line(path_rel: str, lineno: int) -> None:
        if not path_rel or lineno <= 0:
            return
        bucket = touched_lines.setdefault(path_rel, [])
        if lineno not in bucket:
            bucket.append(lineno)

    for line in str(diff_text or "").splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
            out_lines.append(line)
            continue
        if line.startswith("--- "):
            in_hunk = False
            out_lines.append(line)
            continue
        if line.startswith("+++ "):
            in_hunk = False
            raw_target = line[4:].strip()
            if raw_target == "/dev/null":
                rel = ""
            elif raw_target.startswith("b/"):
                rel = _posix(raw_target[2:])
            else:
                rel = _posix(raw_target)
            out_lines.append(line)
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match:
            old_lineno = int(match.group(1))
            new_lineno = int(match.group(2))
            in_hunk = True
            out_lines.append(line)
            continue
        if in_hunk and rel:
            if line.startswith("+"):
                out_lines.append(f"{rel}:{new_lineno} | {line}")
                _record_line(rel, new_lineno)
                new_lineno += 1
                continue
            if line.startswith("-"):
                out_lines.append(f"{rel}:{old_lineno} | {line}")
                _record_line(rel, max(1, new_lineno))
                old_lineno += 1
                continue
            if line.startswith(" ") or line == "":
                out_lines.append(f"{rel}:{new_lineno} | {line}")
                _record_line(rel, new_lineno)
                old_lineno += 1
                new_lineno += 1
                continue
        out_lines.append(line)

    annotated_text = "\n".join(out_lines)
    if diff_text.endswith("\n") and annotated_text:
        annotated_text += "\n"
    if max_chars > 0 and len(annotated_text) > max_chars:
        annotated_text = annotated_text[:max_chars]
    return annotated_text, touched_lines


def _slim_file_entry(
    repo: Path,
    rel: str,
    touched_lines: list[int] | None = None,
) -> dict[str, Any]:
    path = repo / rel
    if not path.is_file():
        return {"path": rel, "content": ""}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"path": rel, "content": ""}
    lines = text.splitlines()
    if len(text) <= MAX_INLINE_FILE_CHARS:
        numbered = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines, 1))
        if len(numbered) > MAX_FILE_CHARS:
            numbered = numbered[:MAX_FILE_CHARS]
        return {
            "path": rel,
            "content": numbered,
            "slimmed": False,
            "original_chars": len(text),
            "slimmed_chars": len(numbered),
        }
    total_lines = len(lines)
    keep: set[int] = set(range(1, min(40, total_lines) + 1))
    for ln in (touched_lines or [1]):
        try:
            center = int(ln)
        except (TypeError, ValueError):
            continue
        start = max(1, center - DIFF_WINDOW_RADIUS)
        end = min(total_lines, center + DIFF_WINDOW_RADIUS)
        keep.update(range(start, end + 1))
    sorted_keep = sorted(keep)
    rendered: list[str] = []
    prev: int | None = None
    for lineno in sorted_keep:
        if prev is not None and lineno > prev + 1:
            rendered.append("  ... [unchanged lines omitted by script] ...")
        rendered.append(f"{lineno}: {lines[lineno - 1]}")
        prev = lineno
    if sorted_keep and sorted_keep[-1] < total_lines:
        rendered.append("  ... [unchanged lines omitted by script] ...")
    windowed = "\n".join(rendered)
    cap = MAX_INLINE_FILE_CHARS * 2
    if len(windowed) > cap:
        windowed = windowed[:cap]
    return {
        "path": rel,
        "content": windowed,
        "slimmed": True,
        "truncated": True,
        "original_chars": len(text),
        "slimmed_chars": len(windowed),
    }


def _added_diff_lines(diff_text: str) -> list[tuple[str, int, str]]:
    added: list[tuple[str, int, str]] = []
    rel = ""
    new_lineno = 0
    in_hunk = False
    for line in str(diff_text or "").splitlines():
        if line.startswith(("diff --git ", "--- ")):
            in_hunk = False
            continue
        if line.startswith("+++ "):
            in_hunk = False
            raw_target = line[4:].strip()
            if raw_target == "/dev/null":
                rel = ""
            elif raw_target.startswith("b/"):
                rel = _posix(raw_target[2:])
            else:
                rel = _posix(raw_target)
            continue
        match = _HUNK_HEADER_RE.match(line)
        if match:
            new_lineno = int(match.group(2))
            in_hunk = True
            continue
        if in_hunk and rel:
            if line.startswith("+"):
                added.append((rel, new_lineno, line[1:]))
                new_lineno += 1
            elif line.startswith(" ") or line == "":
                new_lineno += 1
    return added


def pack_prescreen(
    repo: Path,
    names: list[str],
    diff_text: str,
    redlines: list[str] | None = None,
    ticket_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    syntax_errors: list[str] = []
    for rel in names:
        path = repo / rel
        if not path.is_file():
            continue
        if rel.endswith(".py"):
            try:
                source_text = path.read_text(encoding="utf-8-sig", errors="replace")
                ast.parse(source_text, filename=rel)
            except SyntaxError as exc:
                syntax_errors.append(f"{rel}:{exc.lineno or 1}: SyntaxError: {exc.msg}")
            except OSError:
                continue
        elif rel.endswith(".json"):
            try:
                source_text = path.read_text(encoding="utf-8-sig", errors="replace")
                json.loads(source_text)
            except json.JSONDecodeError as exc:
                syntax_errors.append(f"{rel}:{exc.lineno or 1}: JSONDecodeError: {exc.msg}")
            except OSError:
                continue

    _, touched_map = annotate_diff_with_lines(diff_text)
    added_lines = _added_diff_lines(diff_text)

    redline_collisions: list[dict[str, str]] = []
    seen_collisions: set[tuple[str, str]] = set()
    for rl in (redlines or []):
        rl_text = str(rl or "").strip()
        if not rl_text:
            continue
        tokens: list[str] = []
        for tok in _BACKTICK_TOKEN_RE.findall(rl_text) + _FILE_TOKEN_RE.findall(rl_text):
            cleaned = tok.strip()
            if len(cleaned) >= 2 and cleaned not in tokens:
                tokens.append(cleaned)
        for tok in tokens:
            if len(redline_collisions) >= 15:
                break
            tok_posix = _posix(tok)
            for rel in names:
                if tok_posix and (tok_posix == rel or rel.endswith("/" + tok_posix) or tok in rel):
                    first_ln = (touched_map.get(rel) or [1])[0]
                    ev = f"{rel}:{first_ln}"
                    key = (tok, ev)
                    if key not in seen_collisions:
                        seen_collisions.add(key)
                        redline_collisions.append(
                            {"token": tok, "evidence": ev, "redline": rl_text[:80]}
                        )
                    if len(redline_collisions) >= 15:
                        break
            if len(redline_collisions) >= 15:
                break
            for rel, lineno, content in added_lines:
                if tok in content:
                    ev = f"{rel}:{lineno}"
                    key = (tok, ev)
                    if key not in seen_collisions:
                        seen_collisions.add(key)
                        redline_collisions.append(
                            {"token": tok, "evidence": ev, "redline": rl_text[:80]}
                        )
                    if len(redline_collisions) >= 15:
                        break

    shortcut_signals: list[dict[str, str]] = []
    seen_shortcuts: set[tuple[str, str]] = set()
    prev_except_rel = ""
    prev_except_line = -10
    for rel, lineno, content in added_lines:
        if rel.startswith(".ag-check/") or "/.ag-check/" in f"/{rel}":
            continue
        if rel.startswith("tests/") or "/test_" in f"/{rel}":
            continue
        if _EXCEPT_HEADER_RE.match(content):
            prev_except_rel = rel
            prev_except_line = lineno
        elif (
            prev_except_rel == rel
            and lineno == prev_except_line + 1
            and _PASS_LINE_RE.match(content)
        ):
            ev = f"{rel}:{lineno}"
            key = ("silent-except-pass", ev)
            if key not in seen_shortcuts and len(shortcut_signals) < 15:
                seen_shortcuts.add(key)
                shortcut_signals.append(
                    {"kind": "silent-except-pass", "evidence": ev, "line": content.strip()[:120]}
                )
        for kind, pattern in _SHORTCUT_PATTERNS:
            if pattern.search(content):
                ev = f"{rel}:{lineno}"
                key = (kind, ev)
                if key not in seen_shortcuts and len(shortcut_signals) < 15:
                    seen_shortcuts.add(key)
                    shortcut_signals.append(
                        {"kind": kind, "evidence": ev, "line": content.strip()[:120]}
                    )
        if len(shortcut_signals) >= 15:
            break

    checks_list = list(ticket_checks or [])
    check_file_count = len(checks_list)
    has_assertions = any(
        bool(_ASSERT_SIGNAL_RE.search(str(item.get("content") or "")))
        for item in checks_list
        if isinstance(item, dict)
    )
    return {
        "syntax_errors": syntax_errors,
        "redline_collisions": redline_collisions,
        "shortcut_signals": shortcut_signals,
        "check_quality": {
            "file_count": check_file_count,
            "has_assertions": has_assertions,
        },
    }


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
    source = repo / rel
    raw_source = content
    if source.is_file():
        try:
            raw_source = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw_source = content
    try:
        tree = ast.parse(raw_source)
    except (SyntaxError, ValueError):
        return []
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


def _ticket_checks(repo: Path) -> list[dict[str, Any]]:
    base = repo / ".ag-check"
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in _BINARY_CHECK_SUFFIXES or "__pycache__" in path.parts:
            continue
        try:
            rel = path.resolve().relative_to(repo.resolve()).as_posix()
            size = path.stat().st_size
        except (OSError, ValueError):
            continue
        if size > MAX_CHECK_FILE_BYTES:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                content = ""
            out.append({"path": rel, "truncated": True, "bytes": size, "content": content})
            continue
        out.append(_file_entry(repo, rel))
    return out


def pack(
    root: Path,
    *,
    exam: str | None = None,
    exam_file: str | None = None,
    base: str = "",
    head: str = "",
    tree: Path | None = None,
    redlines: list[str] | None = None,
) -> dict[str, Any]:
    store = real_root(root)
    repo = real_root(Path(tree)) if tree is not None else store
    exam_text = _read_exam(exam, exam_file)
    diff_text, names = _changed_names(repo, str(base or "").strip(), str(head or "").strip())
    annotated_diff, touched_map = annotate_diff_with_lines(diff_text)
    changed = [_slim_file_entry(repo, rel, touched_map.get(rel, [])) for rel in names]
    hops = neighbors(repo, changed)
    probe_run = (
        evaluate_probes(store, paths=names or None, awaken=False, tree=repo) if names else {"results": []}
    )
    results = probe_run.get("results") if isinstance(probe_run, dict) else []
    if not isinstance(results, list):
        results = []
    checks = _ticket_checks(repo)
    effective_redlines = _sealed_redlines(store) if redlines is None else redlines
    script_digest = pack_prescreen(
        repo,
        names,
        diff_text,
        redlines=effective_redlines,
        ticket_checks=checks,
    )
    raw_chars = sum(
        int(item.get("original_chars") or len(str(item.get("content") or "")))
        for item in changed
    )
    slimmed_chars = sum(
        int(item.get("slimmed_chars") or len(str(item.get("content") or "")))
        for item in changed
    )
    return {
        "schema": PACK_SCHEMA,
        "exam": exam_text,
        "diff": annotated_diff,
        "annotated_diff": annotated_diff,
        "changed_files": changed,
        "neighbors": hops,
        "probes": results,
        "this_ticket_checks": checks,
        "script_digest": script_digest,
        "token_stats": {
            "raw_file_chars": raw_chars,
            "slimmed_file_chars": slimmed_chars,
            "saved_chars": max(0, raw_chars - slimmed_chars),
        },
    }


def global_config_path() -> Path:
    return ag_home() / CONFIG_NAME


def config_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / CONFIG_NAME


def config_template() -> dict[str, Any]:
    """Fields a person edits. enabled stays false until they turn a seat on."""
    return {
        "enabled": False,
        "endpoint": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key_env": DEFAULT_API_KEY_ENV,
        "timeout": DEFAULT_TIMEOUT,
        "worker_model": "claude",
        "allow_same_family": False,
    }


def _write_config_template(path: Path) -> Path:
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config_template(), ensure_ascii=False, indent=2) + "\n"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return path
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return path


def ensure_global_config_file() -> Path:
    """Return global critic.json under AG_HOME. Create template only when absent."""
    return _write_config_template(global_config_path())


def ensure_config_file(root: Path) -> Path:
    """Return critic.json. Create the template only when the file is absent."""
    root = real_root(root)
    if not root.is_dir():
        raise ChainBroken(f"config root is not a directory: {root}")
    return _write_config_template(config_path(root))


def report_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / REPORT_NAME


def log_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / LOG_NAME


def _truthy(raw: str) -> bool:
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _apply_config_blob(cfg: dict[str, Any], path: Path) -> dict[str, Any] | None:
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"invalid-config: {exc}", "path": str(path)}
    if not isinstance(blob, dict):
        return {"error": "invalid-config: critic.json is not an object", "path": str(path)}
    if "enabled" in blob:
        cfg["enabled"] = bool(blob.get("enabled"))
    if blob.get("endpoint"):
        cfg["endpoint"] = str(blob["endpoint"]).strip()
    if blob.get("model"):
        cfg["model"] = str(blob["model"]).strip()
    if blob.get("api_key_env"):
        cfg["api_key_env"] = str(blob["api_key_env"]).strip()
    try:
        if blob.get("timeout") is not None:
            cfg["timeout"] = int(blob["timeout"])
    except (TypeError, ValueError):
        return {"error": "invalid-config: timeout must be an int", "path": str(path)}
    if blob.get("worker_model"):
        cfg["worker_model"] = str(blob["worker_model"]).strip()
    if "allow_same_family" in blob:
        cfg["allow_same_family"] = bool(blob.get("allow_same_family"))
    cfg["path"] = str(path)
    return None


def load_config(root: Path | None = None) -> dict[str, Any]:
    """Merge global critic.json, project critic.json, and AG_CRITIC_* env. Missing file is not an error."""
    g_path = global_config_path()
    p_path = config_path(root) if root is not None else None
    default_path = (
        str(p_path)
        if (p_path is not None and p_path.is_file())
        else str(g_path)
        if g_path.is_file()
        else str(p_path or g_path)
    )
    cfg: dict[str, Any] = {
        "enabled": False,
        "endpoint": "",
        "model": "",
        "api_key_env": DEFAULT_API_KEY_ENV,
        "timeout": DEFAULT_TIMEOUT,
        "worker_model": "",
        "allow_same_family": False,
        "path": default_path,
    }
    if g_path.is_file():
        err = _apply_config_blob(cfg, g_path)
        if err is not None:
            return err
    if p_path is not None and p_path.is_file():
        err = _apply_config_blob(cfg, p_path)
        if err is not None:
            return err
    enabled_env = os.environ.get("AG_CRITIC_ENABLED")
    if enabled_env is not None:
        cfg["enabled"] = _truthy(enabled_env)
    if os.environ.get("AG_CRITIC_ENDPOINT", "").strip():
        cfg["endpoint"] = os.environ["AG_CRITIC_ENDPOINT"].strip()
    if os.environ.get("AG_CRITIC_MODEL", "").strip():
        cfg["model"] = os.environ["AG_CRITIC_MODEL"].strip()
    if os.environ.get("AG_CRITIC_API_KEY_ENV", "").strip():
        cfg["api_key_env"] = os.environ["AG_CRITIC_API_KEY_ENV"].strip()
    timeout_env = os.environ.get("AG_CRITIC_TIMEOUT", "").strip()
    if timeout_env:
        try:
            cfg["timeout"] = int(timeout_env)
        except ValueError:
            return {"error": "invalid-config: AG_CRITIC_TIMEOUT must be an int", "path": cfg["path"]}
    if os.environ.get("AG_CRITIC_WORKER_MODEL", "").strip():
        cfg["worker_model"] = os.environ["AG_CRITIC_WORKER_MODEL"].strip()
    allow_env = os.environ.get("AG_CRITIC_ALLOW_SAME_FAMILY")
    if allow_env is not None:
        cfg["allow_same_family"] = _truthy(allow_env)
    return cfg


def _configured(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("enabled") and str(cfg.get("endpoint") or "").strip() and str(cfg.get("model") or "").strip())


def config_guide(root: Path | None = None, *, ensure_file: bool = False) -> dict[str, Any]:
    target_root = real_root(root) if root is not None else None
    has_project_root = target_root is not None and target_root.is_dir()
    if ensure_file:
        if has_project_root and target_root is not None:
            ensure_config_file(target_root)
        else:
            ensure_global_config_file()
    g_path = global_config_path()
    p_path = config_path(target_root) if (has_project_root and target_root is not None) else None
    cfg = load_config(target_root if has_project_root else None)
    api_key_env = str(cfg.get("api_key_env") or DEFAULT_API_KEY_ENV).strip() or DEFAULT_API_KEY_ENV
    api_key_present = bool(os.environ.get(api_key_env, "").strip())
    same_fam = bool(
        not cfg.get("allow_same_family")
        and same_family(str(cfg.get("model") or ""), str(cfg.get("worker_model") or ""))
    )
    reviewer_ready = bool(not cfg.get("error") and _configured(cfg) and api_key_present and not same_fam)
    missing: list[str] = []
    if cfg.get("error"):
        missing.append(str(cfg["error"]))
    if not cfg.get("enabled"):
        missing.append("enabled 为 false（请将 critic.json 中的 enabled 设为 true 以启用独立审核）")
    if not str(cfg.get("endpoint") or "").strip():
        missing.append("endpoint 为空（请填写兼容 OpenAI /chat/completions 的 API 地址，如 https://api.deepseek.com）")
    if not str(cfg.get("model") or "").strip():
        missing.append("model 为空（请填写审核模型名称，如 deepseek-chat）")
    if not api_key_present:
        missing.append(
            f"环境变量 {api_key_env} 未设置（请在终端或系统环境变量中设置该变量，不要将密钥明文写入 JSON）"
        )
    if same_fam:
        missing.append(
            "审核模型 model 与施工模型 worker_model 属于同一家族（请更换不同家族的审核模型，或将 allow_same_family 设为 true）"
        )
    ag_src = str(Path(__file__).resolve().parents[1])
    return {
        "schema": CONFIG_GUIDE_SCHEMA,
        "config_path": str(p_path or g_path),
        "global_config_path": str(g_path),
        "project_config_path": str(p_path) if p_path else "",
        "active_config_path": str(cfg.get("path") or (p_path or g_path)),
        "reviewer_ready": reviewer_ready,
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "missing": missing,
        "current": {
            "enabled": bool(cfg.get("enabled")),
            "endpoint": str(cfg.get("endpoint") or ""),
            "model": str(cfg.get("model") or ""),
            "api_key_env": api_key_env,
            "timeout": int(cfg.get("timeout") or DEFAULT_TIMEOUT),
            "worker_model": str(cfg.get("worker_model") or ""),
            "allow_same_family": bool(cfg.get("allow_same_family")),
        },
        "template": config_template(),
        "fields": {
            "enabled": "布尔值（true/false）：是否启用独立 DS 审核（ticket 开票审与 switch 交卷闸）",
            "endpoint": "字符串：兼容 OpenAI /chat/completions 的接口基础地址（如 https://api.deepseek.com）",
            "model": "字符串：审核模型名称（如 deepseek-chat 或 deepseek-reasoner）",
            "api_key_env": "字符串：读取 API Key 的系统环境变量名（默认 AG_CRITIC_API_KEY，切勿填入密钥明文）",
            "timeout": "整数：单次审核请求超时秒数（默认 60）",
            "worker_model": "字符串：施工方 AI 模型标识（用于同家族回避检查，如 claude / gpt / gemini / grok）",
            "allow_same_family": "布尔值：是否允许审核模型与施工模型同属一个模型家族（默认 false）",
        },
        "mcp_config_example": {
            "mcpServers": {
                "ag": {
                    "command": "<PYTHON_EXECUTABLE>",
                    "args": ["-m", "ag", "mcp"],
                    "env": {
                        "AG_HOME": "<AG_HOME>",
                        "PYTHONPATH": "<AG_REPO_ROOT>/src",
                        api_key_env: "<YOUR_API_KEY>",
                    },
                }
            },
            "detected_runtime": {
                "python_executable": sys.executable,
                "ag_home": str(ag_home()),
                "ag_src": ag_src,
            },
        },
        "ai_guide": [
            "1. 引导用户选择全局配置（global_config_path，所有项目共用）或当前项目配置（project_config_path）。",
            "2. 根据用户使用的审核服务商修改 JSON 中的 endpoint、model、worker_model，并将 enabled 设为 true。",
            f"3. 提醒用户在系统环境变量或 MCP 客户端 env 中设置 {api_key_env}（严禁将密钥明文写入 critic.json）。",
            "4. 配置完成后运行 `python -m ag config <PROJECT_ROOT>` 或调用 `ag_status` 确认 `reviewer_ready: true`。",
        ],
    }


def complete_chat(config: dict[str, Any], messages: list[dict[str, str]]) -> tuple[str, str]:
    url = str(config["endpoint"]).rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(str(config.get("api_key_env") or DEFAULT_API_KEY_ENV), "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = json.dumps(
        {
            "model": config["model"],
            "messages": messages,
            "temperature": 0,
            "stream": True,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    timeout = int(config.get("timeout") or DEFAULT_TIMEOUT)
    on_delta = config.get("on_delta")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content, reasoning = _read_chat_body(response, on_delta=on_delta if callable(on_delta) else None)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"failed: {exc}") from exc
    if not content.strip() and not reasoning.strip():
        raise RuntimeError("failed: empty message")
    return content, reasoning


def _decode_line(chunk: bytes | str) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", "replace")
    return str(chunk)


def _apply_delta(payload: dict[str, Any], content: str, reasoning: str) -> tuple[str, str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return content, reasoning
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else None
    message = first.get("message") if isinstance(first.get("message"), dict) else None
    piece = delta or message or {}
    extra_c = piece.get("content")
    extra_r = piece.get("reasoning_content")
    if isinstance(extra_c, str):
        content += extra_c
    if isinstance(extra_r, str):
        reasoning += extra_r
    return content, reasoning


def _read_chat_body(response: Any, *, on_delta: Any = None) -> tuple[str, str]:
    first = _decode_line(response.readline() or b"")
    rest_head = first.lstrip()
    if rest_head.startswith("{"):
        raw = first.encode("utf-8") + (response.read() or b"")
        body = json.loads(raw.decode("utf-8"))
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("failed: response has no message content") from exc
        if not isinstance(message, dict):
            raise RuntimeError("failed: response has no message content")
        content = message.get("content") if isinstance(message.get("content"), str) else ""
        reasoning = message.get("reasoning_content") if isinstance(message.get("reasoning_content"), str) else ""
        if callable(on_delta):
            on_delta(reasoning, content)
        return content, reasoning
    content = ""
    reasoning = ""

    def handle(line: str) -> bool:
        nonlocal content, reasoning
        text = line.strip()
        if not text or text.startswith(":"):
            return True
        if not text.startswith("data:"):
            return True
        data = text[5:].strip()
        if data == "[DONE]":
            return False
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return True
        if isinstance(payload, dict):
            content, reasoning = _apply_delta(payload, content, reasoning)
            if callable(on_delta):
                on_delta(reasoning, content)
        return True

    if first and not handle(first):
        return content, reasoning
    while True:
        chunk = response.readline()
        if not chunk:
            break
        if not handle(_decode_line(chunk)):
            break
    return content, reasoning


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = (text or "").strip()
    if not candidate:
        raise ValueError("critic output is not JSON")
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, re.S)
    if fence:
        candidate = fence.group(1).strip()
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    for value in found:
        if "verdict" in value or "items" in value:
            return value
    if found:
        return found[0]
    raise ValueError("critic output is not JSON")


def parse_verdict(text: str) -> dict[str, Any]:
    return _extract_json_object(text)


def _item_status(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "").strip().casefold()
    if status in {"pass", "passed"}:
        return "pass"
    if status in {"fail", "failed"}:
        return "fail"
    return status


def verdict_problems(verdict: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    raw = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    if raw in {"pass", "passed"}:
        outcome = "pass"
    elif raw in {"reject", "rejected", "fail", "failed"}:
        outcome = "reject"
    elif raw in {"unproven", "unknown", "uncertain", "unavailable"}:
        outcome = "unproven"
    else:
        problems.append(f"verdict must be pass|reject, got {raw!r}")
        outcome = ""
    items = verdict.get("items")
    if items is None:
        items = []
    if not isinstance(items, list):
        problems.append("items must be a list")
        items = []
    fails = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] must be an object")
            continue
        status = _item_status(item)
        if status not in {"pass", "fail"}:
            problems.append(f"items[{index}].status must be pass|fail")
            continue
        if status == "fail":
            fails += 1
            evidence = str(item.get("evidence") or "").strip()
            if not _EVIDENCE_REF.search(evidence):
                problems.append(
                    f"items[{index}] fail without path:line / portrait:… / probe:<id> evidence (作废)"
                )
    if outcome == "reject" and fails == 0:
        problems.append("verdict is reject but no item is fail")
    if outcome == "pass" and fails:
        problems.append("verdict is pass but some items are fail")
    return problems


def append_log(root: Path, **kwargs: Any) -> str:
    from .seat import append_log as seat_append

    if "pack" not in kwargs and "pack_blob" in kwargs:
        kwargs["pack"] = kwargs.pop("pack_blob")
    kwargs.pop("prompt_version", None)
    return seat_append("critic", root, **kwargs)


def list_log(root: Path, limit: int = DEFAULT_LOG_LIMIT) -> dict[str, Any]:
    repo = real_root(root)
    cap = int(limit) if limit else DEFAULT_LOG_LIMIT
    try:
        if event_count(repo) == 0:
            _backfill_jsonl(repo)
        entries = list_critic_events(repo, limit=cap)
    except Exception:
        entries = []
    return {"schema": LOG_SCHEMA, "root": str(repo), "entries": entries}


def _backfill_jsonl(root: Path) -> None:
    path = log_path(root)
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            try:
                insert_critic_event(root, row)
            except OSError:
                return


def _result(root: Path, **kwargs: Any) -> dict[str, Any]:
    from .seat import seat_result

    if "pack" not in kwargs and "pack_blob" in kwargs:
        kwargs["pack"] = kwargs.pop("pack_blob")
    return seat_result("critic", root, **kwargs)


def _sealed_redlines(root: Path) -> list[str]:
    from .loop import load_task
    from .managed import lookup_project, project_key

    item = lookup_project(root)
    if item is None:
        return []
    task = load_task(str(item.get("key") or project_key(root))) or {}
    raw = task.get("redlines") if isinstance(task, dict) else None
    if not isinstance(raw, list):
        return []
    return [str(line).strip() for line in raw if str(line).strip()]


def critic_run(
    root: Path,
    *,
    exam: str | None = None,
    exam_file: str | None = None,
    base: str = "",
    head: str = "",
    tree: Path | None = None,
    task_id: str = "",
    probe_red: list[str] | None = None,
    redlines: list[str] | None = None,
) -> dict[str, Any]:
    from .seat import seat_run

    return seat_run(
        "critic",
        root,
        exam=exam,
        exam_file=exam_file,
        base=base,
        head=head,
        tree=tree,
        task_id=task_id,
        probe_red=probe_red,
        redlines=_sealed_redlines(root) if redlines is None else redlines,
    )


def attach_verify(
    enrolled: Path,
    *,
    worktree: Path,
    portrait: str,
    task_id: str,
    probe_red: list[str],
    tests_failed: bool = False,
    redlines: list[str] | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    from .seat import attach_verify as seat_attach

    raw = seat_attach(
        "critic",
        enrolled,
        worktree=worktree,
        portrait=portrait,
        task_id=task_id,
        probe_red=probe_red,
        tests_failed=tests_failed,
        redlines=_sealed_redlines(enrolled) if redlines is None else redlines,
    )
    if isinstance(raw, tuple):
        return raw
    return raw, []


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or ""))
    common = dict(
        exam=args.get("exam"),
        exam_file=str(args.get("exam_file") or "") or None,
        base=str(args.get("base") or ""),
        head=str(args.get("head") or ""),
    )
    if name == "ag_critic_pack":
        return pack(root, **common)
    if name == "ag_critic_run":
        return critic_run(root, **common)
    if name == "ag_critic_log":
        limit = args.get("limit")
        return list_log(root, limit=int(limit) if limit not in (None, "") else DEFAULT_LOG_LIMIT)
    raise ChainBroken(f"see has no tool {name}")

