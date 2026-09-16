"""Dispatch small fences. High trust first. Cannot bar → do not mark green."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE_NAME = "queue.json"
RUNS_NAME = "runs.jsonl"
ABSENT = "__ag_absent__"


class ChainBroken(Exception):
    """A physical check did not produce the expected result."""


def queue_path(root: Path) -> Path:
    return root.resolve() / ".ag" / QUEUE_NAME


def runs_path(root: Path) -> Path:
    return root.resolve() / ".ag" / RUNS_NAME


def git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root.resolve()), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "path": item.get("path"),
        "pin": item.get("pin"),
        "note": item.get("note"),
        "scope": item.get("scope"),
        "argv": item.get("argv"),
        "red_argv": item.get("red_argv"),
        "expect_exit": item.get("expect_exit"),
        "red_expect_exit": item.get("red_expect_exit"),
        "last": item.get("last"),
        "speech": speech(item),
    }


def load_queue(root: Path) -> dict[str, Any]:
    path = queue_path(root)
    if not path.is_file():
        return {"schema": "ag.queue.v1", "items": []}
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        raise ChainBroken("queue file is not an object")
    items = blob.get("items")
    if not isinstance(items, list):
        items = []
    out = {"schema": "ag.queue.v1", "items": items}
    if isinstance(blob.get("last_run"), dict):
        out["last_run"] = blob["last_run"]
    return out


def save_queue(root: Path, queue: dict[str, Any]) -> Path:
    path = queue_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def speech(item: dict[str, Any]) -> dict[str, str]:
    """Larger scope → broader speech. Not a trust root."""
    kind = str(item.get("kind") or "")
    path = str(item.get("path") or "").replace("\\", "/").rstrip("/")
    if kind == "unknown":
        return {"breadth": "wide", "claim": str(item.get("note") or "cannot verify")}
    if kind == "hash":
        return {"breadth": "precise", "claim": f"bytes of {path} match pin"}
    if kind == "exists":
        name = path.rsplit("/", 1)[-1]
        if "." in name:
            return {"breadth": "precise", "claim": f"{path} exists"}
        return {"breadth": "broad", "claim": f"{path} exists as a tree"}
    return {"breadth": "broad", "claim": "custom command"}


def trust_rank(item: dict[str, Any]) -> tuple[int, str]:
    kind = str(item.get("kind") or "")
    if kind == "exists":
        return (0, "0" + str(item.get("path") or ""))
    if kind == "hash":
        return (0, "1" + str(item.get("path") or ""))
    if kind == "unknown":
        return (2, str(item.get("note") or item.get("id") or ""))
    blob = json.dumps(item.get("argv") or [], ensure_ascii=False)
    return (1, f"{len(blob):08d}")


def _safe_target(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ChainBroken(f"path escapes root: {rel}") from exc
    return target


def _exists_exit(root: Path, rel: str) -> int:
    return 0 if _safe_target(root, rel).exists() else 1


def _file_digest(path: Path) -> str:
    # Same idea as AG2C util.file digest: sha256 of raw bytes.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_exit(root: Path, rel: str, pin: str) -> int:
    target = _safe_target(root, rel)
    if not target.is_file():
        return 1
    return 0 if _file_digest(target) == pin else 1


def _run(argv: list[str], cwd: Path) -> int:
    if not argv:
        raise ChainBroken("empty argv")
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    return int(completed.returncode)


def add_exists(root: Path, rel: str, *, note: str = "") -> dict[str, Any]:
    rel = str(rel).replace("\\", "/").strip().strip("/")
    if not rel or rel == ABSENT:
        raise ChainBroken("exists probe needs a real relative path")
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "exists",
        "path": rel,
        "note": str(note or ""),
        "last": None,
    }
    queue = load_queue(root)
    queue["items"].append(item)
    save_queue(root, queue)
    return item


def add_hash(root: Path, rel: str, *, note: str = "") -> dict[str, Any]:
    rel = str(rel).replace("\\", "/").strip().strip("/")
    if not rel or rel == ABSENT:
        raise ChainBroken("hash probe needs a real relative file")
    target = _safe_target(root.resolve(), rel)
    if not target.is_file():
        raise ChainBroken(f"cannot pin missing file: {rel}")
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "hash",
        "path": rel,
        "pin": _file_digest(target),
        "note": str(note or ""),
        "last": None,
    }
    queue = load_queue(root)
    queue["items"].append(item)
    save_queue(root, queue)
    return item


def add_unknown(root: Path, *, note: str, scope: str = "") -> dict[str, Any]:
    note = str(note or "").strip()
    if not note:
        raise ChainBroken("unknown item needs a note saying what cannot be verified")
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "unknown",
        "scope": str(scope or ""),
        "note": note,
        "last": None,
    }
    queue = load_queue(root)
    queue["items"].append(item)
    save_queue(root, queue)
    return item


def add_item(
    root: Path,
    *,
    argv: list[str],
    expect_exit: int,
    red_argv: list[str],
    red_expect_exit: int,
    note: str = "",
) -> dict[str, Any]:
    if not argv or not red_argv:
        raise ChainBroken("probe needs argv and red_argv")
    if red_expect_exit == expect_exit and red_argv == argv:
        raise ChainBroken("red chain cannot be identical to green chain")
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "exec",
        "argv": list(argv),
        "expect_exit": int(expect_exit),
        "red_argv": list(red_argv),
        "red_expect_exit": int(red_expect_exit),
        "note": str(note or ""),
        "last": None,
    }
    queue = load_queue(root)
    queue["items"].append(item)
    save_queue(root, queue)
    return item


def run_item(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    cwd = root.resolve()
    kind = str(item.get("kind") or "exec")
    if kind == "exists":
        red_code = _exists_exit(cwd, ABSENT)
        red_ok = red_code == 1
        green_code = _exists_exit(cwd, str(item.get("path") or "")) if red_ok else None
        green_ok = green_code == 0
    elif kind == "hash":
        pin = str(item.get("pin") or "")
        red_code = _hash_exit(cwd, ABSENT, pin)
        red_ok = red_code == 1
        green_code = _hash_exit(cwd, str(item.get("path") or ""), pin) if red_ok else None
        green_ok = green_code == 0
    else:
        red_code = _run([str(x) for x in item["red_argv"]], cwd)
        red_ok = red_code == int(item["red_expect_exit"])
        green_code = _run([str(x) for x in item["argv"]], cwd) if red_ok else None
        green_ok = green_code == int(item["expect_exit"]) if red_ok else False
    last = {
        "red_exit": red_code,
        "red_ok": red_ok,
        "green_exit": green_code,
        "green_ok": green_ok,
        "trusted": bool(red_ok and green_ok),
        "skipped": False,
    }
    item["last"] = last
    if not red_ok:
        raise ChainBroken(
            f"red chain failed for {item['id']}: exit {red_code} (cannot trust this fence)"
        )
    if not green_ok:
        raise ChainBroken(
            f"fence barred {item['id']}: green exit {green_code}"
        )
    return last


def _trust_rate(trusted: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(trusted / total, 4)


def run_queue(root: Path) -> dict[str, Any]:
    queue = load_queue(root)
    ordered = sorted(queue["items"], key=trust_rank)
    trusted: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    halt = False
    for item in ordered:
        if str(item.get("kind") or "") == "unknown":
            item["last"] = {
                "trusted": False,
                "skipped": False,
                "unverifiable": True,
                "reason": "declared-unknown",
            }
            unknown.append({"id": item.get("id"), "note": item.get("note"), "scope": item.get("scope")})
            continue
        if halt:
            item["last"] = {
                "trusted": False,
                "skipped": True,
                "reason": "halted-after-bar",
            }
            skipped.append({"id": item.get("id"), "kind": item.get("kind")})
            continue
        try:
            last = run_item(root, item)
            trusted.append({"id": item["id"], "kind": item.get("kind"), "last": last})
        except ChainBroken as exc:
            halt = True
            broken.append({"id": item.get("id"), "kind": item.get("kind"), "error": str(exc), "last": item.get("last")})
    queue["items"] = ordered
    total = len(ordered)
    rate = _trust_rate(len(trusted), total)
    run_id = uuid.uuid4().hex[:12]
    at = datetime.now(timezone.utc).isoformat()
    head = git_head(root)
    record = {
        "schema": "ag.run.v1",
        "run_id": run_id,
        "at": at,
        "root": str(root.resolve()),
        "git_head": head,
        "trust_rate": rate,
        "runnable": True,
        "reminder": "trust_rate is a reminder; green is only evidence for that fence's predicate on that git_head",
        "items": [_evidence(item) for item in ordered],
    }
    log = runs_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    queue["last_run"] = {"run_id": run_id, "at": at, "git_head": head, "trust_rate": rate}
    save_queue(root, queue)
    return {
        "schema": "ag.queue-run.v1",
        "run_id": run_id,
        "at": at,
        "git_head": head,
        "root": str(root.resolve()),
        "runnable": True,
        "trust_rate": rate,
        "reminder": record["reminder"],
        "ok": not broken and not skipped,
        "trusted": trusted,
        "broken": broken,
        "skipped": skipped,
        "unknown": unknown,
        "evidence": str(log),
    }
