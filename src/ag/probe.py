"""Out-of-tree observation probes. See lane. Never set product or refuse finish.

Definitions live under AG_HOME/projects/<key>/probes.json, not the product tree.
Heal-4 file-hash pins stay in plug/heal/4/probes.json and are not this store.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root

SCHEMA = "ag.probes.v1"
RUN_SCHEMA = "ag.probe.run.v1"
LIST_SCHEMA = "ag.probe.list.v1"
MIN_EVIDENCE = 20
DEFAULT_TTL = 10
TAIL_CHARS = 2000
CMD_TIMEOUT_S = 30
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
        "description": "List armed and archived probes (full fields). See lane; not a worker injection channel.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}},
            "required": ["root"],
        },
    },
]


def store_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / "probes.json"


def _posix(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


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


def list_probes(root: Path) -> dict[str, Any]:
    repo = real_root(root)
    path = store_path(repo)
    blob = _load(path)
    return {
        "schema": LIST_SCHEMA,
        "root": str(repo),
        "store": str(path),
        "probes": list(blob["probes"]),
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


def evaluate(root: Path, *, paths: list[str] | None = None, awaken: bool = False) -> dict[str, Any]:
    """Red/green tails only. Does not change probe lifetime or write probes.json."""
    repo = real_root(root)
    path = store_path(repo)
    wanted = [_posix(item) for item in (paths or []) if _posix(item)]
    path_filter = wanted or None
    results: list[dict[str, Any]] = []
    blob = _load(path)
    for row in blob["probes"]:
        if not _should_run(row, path_filter, awaken):
            continue
        observation = row.get("observation") if isinstance(row.get("observation"), dict) else {}
        verdict, exit_code, tail = _eval(repo, observation)
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


def run(root: Path, *, paths: list[str] | None = None, awaken: bool = False) -> dict[str, Any]:
    repo = real_root(root)
    path = store_path(repo)
    out = evaluate(repo, paths=paths, awaken=awaken)
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
    if name == "ag_probe_run":
        raw_paths = args.get("path")
        paths = _as_str_list(raw_paths, name="path") if raw_paths else []
        return run(root, paths=paths or None, awaken=bool(args.get("awaken")))
    if name == "ag_probe_list":
        return list_probes(root)
    raise ChainBroken(f"see has no tool {name}")
