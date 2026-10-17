"""Out-of-tree observation probes. See lane. Never set product or refuse finish.

Definitions live under AG_HOME/projects/<key>/probes.json, not the product tree.
Skips and removals are recorded in AG_HOME/projects/<key>/probe-audit.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root

SCHEMA = "ag.probes.v1"
RUN_SCHEMA = "ag.probe.run.v1"
LIST_SCHEMA = "ag.probe.list.v1"
AUDIT_NAME = "probe-audit.jsonl"
MIN_EVIDENCE = 20
DEFAULT_TTL = 10
TAIL_CHARS = 2000
CMD_TIMEOUT_S = 30
PLANT_HEAD_BYTES = 4096
PLANT_MAX_FILE_BYTES = 1_000_000
PLANT_MAX_LINE_CHARS = 400
KINDS = ("command", "text_in_file")

TOOLS = [
    {
        "name": "ag_probe_insert",
        "description": (
            "Insert an out-of-tree observation probe. Requires already-seen evidence. "
            "Duplicate id is refused; the existing probe is left unchanged. See lane; not delivery."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "observation": {"type": "object"},
                "exam_fragment": {"type": "string"},
                "evidence": {"type": "string"},
                "area": {"type": "array", "items": {"type": "string"}},
                "id": {"type": "string"},
                "ttl_quiet_loops": {"type": "integer"},
            },
            "required": ["root", "observation", "exam_fragment", "evidence", "area"],
        },
    },
    {
        "name": "ag_probe_drop",
        "description": (
            "Remove one out-of-tree probe by id and append a readable line to probe-audit.jsonl. "
            "Reduces pins only; an unknown id is refused and the store is left unchanged. See lane; not delivery."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "id": {"type": "string"},
                "reason": {"type": "string"},
                "by": {"type": "string"},
            },
            "required": ["root", "id"],
        },
    },
    {
        "name": "ag_probe_run",
        "description": (
            "Run armed out-of-tree probes. No LLM. Does not change product files or refuse finish. "
            "Optional path limits to area hits; archived run only with awaken and a path hit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "path": {"type": "array", "items": {"type": "string"}},
                "awaken": {"type": "boolean"},
            },
            "required": ["root"],
        },
    },
    {
        "name": "ag_probe_list",
        "description": "List armed and archived probes. Default omits observation and evidence. full=true for a critic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "full": {"type": "boolean"},
            },
            "required": ["root"],
        },
    },
]


def store_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / "probes.json"


def _posix(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


def audit_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / AUDIT_NAME


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_note(
    root: Path,
    *,
    action: str,
    probe_id: str,
    area: list[str] | None = None,
    reason: str = "",
    by: str = "",
) -> str:
    """Append one readable line. Skips and removals must never be silent."""
    from .store import append_project_jsonl

    row: dict[str, Any] = {
        "t": _utc_stamp(),
        "key": project_key(real_root(root)),
        "action": str(action),
        "id": str(probe_id),
        "area": [str(item) for item in (area or [])],
        "reason": str(reason),
    }
    if by:
        row["by"] = str(by)
    return append_project_jsonl(real_root(root), AUDIT_NAME, row)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _as_str_list(value: Any, *, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ChainBroken(f"{name} must be a string or list of strings")
            text = item.strip()
            if text:
                out.append(text)
        return out
    raise ChainBroken(f"{name} must be a string or list of strings")


def _relative_path(path: str, *, name: str) -> str:
    rel = _posix(path)
    if not rel or rel.startswith("/") or (len(rel) >= 2 and rel[1] == ":"):
        raise ChainBroken(f"{name} must be a repository-relative path")
    parts = rel.split("/")
    if ".." in parts or parts[0].endswith(":"):
        raise ChainBroken(f"{name} must be a repository-relative path")
    return rel


def area_hits(area: list[str], paths: list[str]) -> bool:
    areas = [_posix(item) for item in area if _posix(item)]
    wanted = [_posix(item) for item in paths if _posix(item)]
    if not areas or not wanted:
        return False
    for item in areas:
        for path in wanted:
            if item == path or item.startswith(path + "/") or path.startswith(item + "/"):
                return True
    return False


def _tail(text: str) -> str:
    blob = text or ""
    if len(blob) <= TAIL_CHARS:
        return blob
    return blob[-TAIL_CHARS:]


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"schema": SCHEMA, "probes": []}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ChainBroken("probe store is not JSON") from exc
    if not isinstance(blob, dict):
        raise ChainBroken("probe store is not an object")
    probes = blob.get("probes")
    if not isinstance(probes, list):
        probes = []
    return {"schema": SCHEMA, "probes": [row for row in probes if isinstance(row, dict)]}


def _save(path: Path, blob: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(blob, ensure_ascii=False, indent=2) + "\n")


def _normalize_observation(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChainBroken("observation must be a JSON object") from exc
    if not isinstance(raw, dict):
        raise ChainBroken("observation must be an object")
    kind = str(raw.get("kind") or "").strip()
    if not kind:
        raise ChainBroken("observation.kind is required")
    if kind not in KINDS:
        raise ChainBroken("observation kind must be command or text_in_file")
    if kind == "command":
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ChainBroken("command observation requires argv as a non-empty string array")
        expect = raw.get("expect_exit")
        if isinstance(expect, bool) or not isinstance(expect, int):
            raise ChainBroken("command observation requires expect_exit as an int")
        out: dict[str, Any] = {"kind": "command", "argv": list(argv), "expect_exit": int(expect)}
        stdout_contains = raw.get("stdout_contains")
        stderr_contains = raw.get("stderr_contains")
        if stdout_contains is not None:
            if not isinstance(stdout_contains, str):
                raise ChainBroken("stdout_contains must be a string")
            out["stdout_contains"] = stdout_contains
        if stderr_contains is not None:
            if not isinstance(stderr_contains, str):
                raise ChainBroken("stderr_contains must be a string")
            out["stderr_contains"] = stderr_contains
        return out
    path = _relative_path(str(raw.get("path") or ""), name="path")
    includes = _as_str_list(raw.get("must_include"), name="must_include")
    excludes = _as_str_list(raw.get("must_exclude"), name="must_exclude")
    if not includes and not excludes:
        raise ChainBroken("text_in_file requires must_include or must_exclude")
    body: dict[str, Any] = {"kind": "text_in_file", "path": path}
    if includes:
        body["must_include"] = includes
    if excludes:
        body["must_exclude"] = excludes
    return body


def _default_id(observation: dict[str, Any], exam_fragment: str, area: list[str]) -> str:
    blob = json.dumps(
        {"observation": observation, "exam_fragment": exam_fragment, "area": area},
        ensure_ascii=False,
        sort_keys=True,
    )
    return "p-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _clean_id(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ChainBroken("id is empty")
    if len(text) > 64 or not all(ch.isalnum() or ch in "-_" for ch in text):
        raise ChainBroken("id must be alphanumeric plus dash or underscore, max 64")
    return text


def insert(
    root: Path,
    *,
    observation: Any,
    exam_fragment: str,
    evidence: str,
    area: Any,
    id: str | None = None,
    ttl_quiet_loops: int = DEFAULT_TTL,
    task_id: str = "",
) -> dict[str, Any]:
    repo = real_root(root)
    evidence_text = str(evidence or "").strip()
    if not evidence_text:
        raise ChainBroken("evidence is required: already-seen observation text")
    if len(evidence_text) < MIN_EVIDENCE:
        raise ChainBroken(f"evidence must be at least {MIN_EVIDENCE} characters of already-seen observation text")
    fragment = str(exam_fragment or "").strip()
    if not fragment:
        raise ChainBroken("exam_fragment is required")
    areas = [_relative_path(item, name="area") for item in _as_str_list(area, name="area")]
    if not areas:
        raise ChainBroken("area is required: at least one repository-relative path")
    obs = _normalize_observation(observation)
    ttl = int(ttl_quiet_loops)
    if ttl < 1:
        raise ChainBroken("ttl_quiet_loops must be >= 1")
    probe_id = _clean_id(id) if id else _default_id(obs, fragment, areas)
    path = store_path(repo)
    blob = _load(path)
    for row in blob["probes"]:
        if str(row.get("id") or "") == probe_id:
            raise ChainBroken(f"duplicate probe id {probe_id}; insert refused, store unchanged")
    row = {
        "id": probe_id,
        "state": "armed",
        "quiet_count": 0,
        "ttl_quiet_loops": ttl,
        "area": areas,
        "exam_fragment": fragment,
        "observation": obs,
        "evidence": evidence_text,
    }
    if str(task_id or "").strip():
        row["task_id"] = str(task_id).strip()
    blob["probes"].append(row)
    _save(path, blob)
    return {
        "schema": SCHEMA,
        "id": probe_id,
        "state": "armed",
        "store": str(path),
        "quiet_count": 0,
        "ttl_quiet_loops": ttl,
    }


_WORKER_KEYS = ("id", "state", "quiet_count", "ttl_quiet_loops", "area", "exam_fragment")


def _public_row(row: dict[str, Any], *, full: bool) -> dict[str, Any]:
    if full:
        return dict(row)
    return {key: row[key] for key in _WORKER_KEYS if key in row}


_PATH_LINE = re.compile(r"([\w./\\-]+):(\d+)")

_DEFECT_HINTS = (
    "still", "missing", " defect", "defects", "violation", "violate", "leftover", "residue",
    "仍未", "仍有", "缺失", "未改", "错误", "违反", "残留", "缺陷", "仍是", "不应", "不该", "没有删",
)


def _line_at(tree: Path, rel: str, lineno: int) -> str:
    path = Path(tree) / rel.replace("\\", "/")
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    if lineno < 1 or lineno > len(lines):
        return ""
    return str(lines[lineno - 1] or "").strip()


def _binary_suffixes() -> set[str]:
    from .critic import _BINARY_CHECK_SUFFIXES

    return {str(item).lower() for item in _BINARY_CHECK_SUFFIXES}


def _bad_line_reason(snippet: str) -> str:
    if len(snippet) > PLANT_MAX_LINE_CHARS:
        return f"line-too-long:{len(snippet)}"
    for ch in snippet:
        if (ord(ch) < 32 and ch != "\t") or ord(ch) == 127:
            return "line-control-chars"
    return ""


def _git_lines(tree: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(tree), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return []
    return (completed.stdout or "").splitlines()


def _changed_lines(tree: Path, source_head: str) -> dict[str, set[int]]:
    """Lines added or modified by this ticket: {rel: {lineno}} from git diff source_head.

    A must_exclude pin aimed at one of these lines targets the deliverable itself,
    not a pre-existing defect. Physical fact from git, not wording.
    """
    out: dict[str, set[int]] = {}
    if not str(source_head or "").strip():
        return out
    current: str | None = None
    new_line = 0
    for line in _git_lines(tree, "diff", "--unified=0", source_head, "--"):
        if line.startswith("+++ b/"):
            current = line[6:].strip().replace("\\", "/")
            out.setdefault(current, set())
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if match and current is not None:
                new_line = int(match.group(1))
                span = int(match.group(2) or "1")
                for off in range(max(span, 1)):
                    out[current].add(new_line + off)
        elif line.startswith("+") and not line.startswith("+++"):
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            pass
        elif current is not None and not line.startswith("\\"):
            new_line += 1
    return out


def drop_newborn_for_task(root: Path, *, task_id: str, by: str = "") -> list[str]:
    """连座清除：票作废时，清掉该票种的、仍 armed、且从没绿过的新生探针。

    Only rows with task_id == this ticket AND state == armed AND quiet_count == 0.
    Old pins without task_id, manual pins, other tickets' pins, quiet_count>0 pins,
    and archived/dropped pins are never touched.
    """
    repo = real_root(root)
    tid = str(task_id or "").strip()
    if not tid:
        return []
    path = store_path(repo)
    blob = _load(path)
    dropped: list[str] = []
    for row in list(blob["probes"]):
        if str(row.get("task_id") or "") != tid:
            continue
        if str(row.get("state") or "armed") != "armed":
            continue
        if int(row.get("quiet_count") or 0) != 0:
            continue
        probe_id = str(row.get("id") or "")
        if not probe_id:
            continue
        drop(repo, id=probe_id, reason=f"票作废连座清理 task={tid}", by=by)
        dropped.append(probe_id)
    return dropped


def _plant_target(tree: Path, rel: str, lineno: int) -> tuple[str, str]:
    """Return (skip_reason, snippet). An empty skip_reason means the line can carry a pin."""
    path = Path(tree) / rel.replace("\\", "/")
    if not path.is_file():
        return "target-not-found", ""
    try:
        size = int(path.stat().st_size)
    except OSError as exc:
        return f"target-unreadable:{exc.__class__.__name__}", ""
    if size > PLANT_MAX_FILE_BYTES:
        return f"target-too-large:{size}", ""
    suffix = path.suffix.lower()
    if suffix in _binary_suffixes():
        return f"binary-suffix:{suffix}", ""
    try:
        with path.open("rb") as handle:
            head = handle.read(PLANT_HEAD_BYTES)
    except OSError as exc:
        return f"target-unreadable:{exc.__class__.__name__}", ""
    if b"\x00" in head:
        return "binary-nul-header", ""
    snippet = _line_at(Path(tree), rel, lineno)
    if not snippet:
        try:
            count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            count = 0
        if lineno < 1 or lineno > count:
            return f"line-out-of-range:{lineno}>{count}", ""
        return "line-empty", ""
    bad = _bad_line_reason(snippet)
    if bad:
        return bad, ""
    return "", snippet


def plant_from_reject(root: Path, *, items: Any, tree: Path, source_head: str = "", task_id: str = "") -> list[str]:
    """Ship autonomy: critic reject with path:line becomes a must_exclude pin. Heal does not call this.

    A pin that can never be satisfied must not land: binary, oversized, or abnormal target lines are
    skipped, and the skip reason is written to probe-audit.jsonl.
    """
    planted: list[str] = []
    if not isinstance(items, list):
        return planted
    repo = real_root(root)
    tree_root = Path(tree)
    changed = _changed_lines(tree_root, source_head)
    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().casefold()
        if status not in {"fail", "failed"}:
            continue
        evidence = str(item.get("evidence") or "").strip()
        match = _PATH_LINE.search(evidence)
        if not match:
            continue
        rel = match.group(1).replace("\\", "/")
        lineno = int(match.group(2))
        skip_reason, snippet = _plant_target(tree_root, rel, lineno)
        probe_id = "auto-" + hashlib.sha256(f"{rel}:{lineno}:{snippet}".encode("utf-8")).hexdigest()[:12]
        if skip_reason:
            audit_note(
                repo,
                action="skip-plant",
                probe_id=probe_id,
                area=[rel],
                reason=f"{rel}:{lineno} {skip_reason}",
            )
            continue
        name = str(item.get("name") or "")
        if not (rel.startswith("src/ag/") and rel.endswith(".py") and (tree_root / rel).is_file()):
            audit_note(
                repo,
                action="skip-plant",
                probe_id=probe_id,
                area=[rel],
                reason=f"{rel}:{lineno} 文件闸：非本票 src/ag/*.py 真实代码文件 task={task_id}",
            )
            continue
        if lineno not in changed.get(rel, set()):
            audit_note(
                repo,
                action="skip-plant",
                probe_id=probe_id,
                area=[rel],
                reason=f"{rel}:{lineno} 改动闸：证据行不在本票改动行集（指针非缺陷）task={task_id}",
            )
            continue
        defect_text = (name + " " + str(item.get("comment") or "")).casefold()
        if not any(hint in defect_text for hint in _DEFECT_HINTS):
            audit_note(
                repo,
                action="skip-plant",
                probe_id=probe_id,
                area=[rel],
                reason=f"{rel}:{lineno} 缺陷闸：文本未确证该行为缺陷 task={task_id}",
            )
            continue
        comment = str(item.get("comment") or "").strip()
        fragment = comment or f"{rel}:{lineno} must not keep this defect"
        evidence_text = f"{evidence} {comment} critic-reject auto-plant".strip()
        if len(evidence_text) < MIN_EVIDENCE:
            evidence_text = (evidence_text + " " + "observed-in-worktree")[:].strip()
            if len(evidence_text) < MIN_EVIDENCE:
                evidence_text = evidence_text + " " * (MIN_EVIDENCE - len(evidence_text))
        try:
            insert(
                repo,
                observation={"kind": "text_in_file", "path": rel, "must_exclude": snippet},
                exam_fragment=fragment,
                evidence=evidence_text,
                area=[rel],
                id=probe_id,
                task_id=task_id,
            )
        except ChainBroken as exc:
            audit_note(
                repo,
                action="skip-plant",
                probe_id=probe_id,
                area=[rel],
                reason=f"{rel}:{lineno} insert-refused {exc}",
            )
            continue
        planted.append(probe_id)
    return planted


def drop(root: Path, *, id: str, reason: str = "", by: str = "") -> dict[str, Any]:
    """Remove one pin by id. An unknown id is refused and the store is left unchanged."""
    repo = real_root(root)
    probe_id = _clean_id(id)
    path = store_path(repo)
    blob = _load(path)
    target = next((row for row in blob["probes"] if str(row.get("id") or "") == probe_id), None)
    if target is None:
        raise ChainBroken(f"probe {probe_id} not found; store unchanged")
    area = [str(item) for item in (target.get("area") or []) if isinstance(item, str)]
    blob["probes"] = [row for row in blob["probes"] if str(row.get("id") or "") != probe_id]
    _save(path, blob)
    audit = audit_note(
        repo,
        action="drop",
        probe_id=probe_id,
        area=area,
        reason=str(reason or ""),
        by=str(by or ""),
    )
    return {
        "schema": SCHEMA,
        "action": "drop",
        "id": probe_id,
        "dropped": [probe_id],
        "state": "dropped",
        "store": str(path),
        "audit": audit,
        "reason": str(reason or ""),
        "by": str(by or ""),
    }


def missing_fragments(root: Path, red_ids: list[str]) -> list[str]:
    blob = _load(store_path(real_root(root)))
    by_id = {str(item.get("id") or ""): item for item in blob["probes"]}
    out: list[str] = []
    for rid in red_ids:
        row = by_id.get(str(rid) or "") or {}
        frag = str(row.get("exam_fragment") or "").strip()
        out.append(frag or str(rid))
    return out


def list_probes(root: Path, *, full: bool = False) -> dict[str, Any]:
    repo = real_root(root)
    path = store_path(repo)
    blob = _load(path)
    return {
        "schema": LIST_SCHEMA,
        "root": str(repo),
        "store": str(path),
        "full": bool(full),
        "probes": [_public_row(row, full=full) for row in blob["probes"]],
    }


def _eval_command(repo: Path, observation: dict[str, Any]) -> tuple[str, int, str]:
    argv = [str(item) for item in observation["argv"]]
    try:
        ran = subprocess.run(
            argv,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CMD_TIMEOUT_S,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = _tail((exc.stdout or "") + ("\n" if exc.stdout and exc.stderr else "") + (exc.stderr or "") + "\ntimeout")
        return "red", -1, out
    except OSError as exc:
        return "red", -1, _tail(str(exc))
    stdout = ran.stdout or ""
    stderr = ran.stderr or ""
    tail = _tail(stdout + ("\n" if stdout and stderr else "") + stderr)
    expect = int(observation["expect_exit"])
    ok = ran.returncode == expect
    needle = observation.get("stdout_contains")
    if isinstance(needle, str) and needle not in stdout:
        ok = False
    err_needle = observation.get("stderr_contains")
    if isinstance(err_needle, str) and err_needle not in stderr:
        ok = False
    return ("green" if ok else "red"), int(ran.returncode), tail


def _eval_text(repo: Path, observation: dict[str, Any]) -> tuple[str, int, str]:
    rel = _posix(str(observation.get("path") or ""))
    path = repo / rel
    if not path.is_file():
        return "red", 1, f"missing {rel}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "red", 1, _tail(str(exc))
    missing = [item for item in observation.get("must_include") or [] if item not in text]
    present = [item for item in observation.get("must_exclude") or [] if item in text]
    if missing or present:
        bits = []
        if missing:
            bits.append("missing " + ", ".join(missing))
        if present:
            bits.append("excluded still present " + ", ".join(present))
        return "red", 1, _tail("; ".join(bits))
    return "green", 0, _tail(text)


def _eval(repo: Path, observation: dict[str, Any]) -> tuple[str, int, str]:
    kind = str(observation.get("kind") or "")
    if kind == "command":
        return _eval_command(repo, observation)
    if kind == "text_in_file":
        return _eval_text(repo, observation)
    return "red", 1, f"unknown kind {kind}"


def _should_run(row: dict[str, Any], paths: list[str] | None, awaken: bool) -> bool:
    state = str(row.get("state") or "armed")
    area = [str(item) for item in (row.get("area") or []) if isinstance(item, str)]
    if paths:
        if not area_hits(area, paths):
            return False
        if state == "archived":
            return bool(awaken)
        return True
    if state == "archived":
        return False
    return True


def evaluate(
    root: Path,
    *,
    paths: list[str] | None = None,
    awaken: bool = False,
    tree: Path | None = None,
) -> dict[str, Any]:
    """Red/green tails only. Does not change probe lifetime or write probes.json."""
    repo = real_root(root)
    cwd = real_root(Path(tree)) if tree is not None else repo
    path = store_path(repo)
    wanted = [_posix(item) for item in (paths or []) if _posix(item)]
    path_filter = wanted or None
    results: list[dict[str, Any]] = []
    blob = _load(path)
    for row in blob["probes"]:
        if not _should_run(row, path_filter, awaken):
            continue
        observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
        verdict, exit_code, tail = _eval(cwd, observation)
        results.append(
            {
                "id": str(row.get("id") or ""),
                "state": str(row.get("state") or "armed"),
                "verdict": verdict,
                "exit": exit_code,
                "tail": tail,
            }
        )
    return {"schema": RUN_SCHEMA, "root": str(repo), "results": results}


def run(
    root: Path,
    *,
    paths: list[str] | None = None,
    awaken: bool = False,
    tree: Path | None = None,
) -> dict[str, Any]:
    repo = real_root(root)
    path = store_path(repo)
    out = evaluate(repo, paths=paths, awaken=awaken, tree=tree)
    by_id = {str(item.get("id") or ""): item for item in out["results"]}
    blob = _load(path)
    dirty = False
    for row in blob["probes"]:
        hit = by_id.get(str(row.get("id") or ""))
        if hit is None:
            continue
        ttl = int(row.get("ttl_quiet_loops") or DEFAULT_TTL)
        if hit["verdict"] == "green":
            quiet = int(row.get("quiet_count") or 0) + 1
            row["quiet_count"] = quiet
            row["state"] = "archived" if quiet >= ttl else "armed"
        else:
            row["quiet_count"] = 0
            row["state"] = "armed"
        hit["state"] = str(row.get("state") or "armed")
        dirty = True
    if dirty:
        _save(path, blob)
    return out


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    root = Path(str(args.get("root") or ""))
    if name == "ag_probe_insert":
        return insert(
            root,
            observation=args.get("observation"),
            exam_fragment=str(args.get("exam_fragment") or ""),
            evidence=str(args.get("evidence") or ""),
            area=args.get("area"),
            id=str(args["id"]) if args.get("id") else None,
            ttl_quiet_loops=int(args.get("ttl_quiet_loops") or DEFAULT_TTL),
        )
    if name == "ag_probe_drop":
        return drop(
            root,
            id=str(args.get("id") or ""),
            reason=str(args.get("reason") or ""),
            by=str(args.get("by") or ""),
        )
    if name == "ag_probe_run":
        raw_paths = args.get("path")
        paths = _as_str_list(raw_paths, name="path") if raw_paths else []
        return run(root, paths=paths or None, awaken=bool(args.get("awaken")))
    if name == "ag_probe_list":
        return list_probes(root, full=bool(args.get("full")))
    raise ChainBroken(f"see has no tool {name}")
