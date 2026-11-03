"""Durable JSONL facts, bounded journals, and verified legacy reclamation."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken
from .store import project_dir

SCHEMA = "ag.history.record.v1"
MAX_VOLUME_BYTES = 1024 * 1024


def _encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(_encode(value)).hexdigest()


def history_dir(root: Path) -> Path:
    return project_dir(root) / "history"


def record(kind: str, task_id: str, payload: dict[str, Any], *, identity: str = "") -> dict[str, Any]:
    body = {"kind": kind, "task_id": str(task_id), "payload": payload}
    checksum = digest(body)
    return {"schema": SCHEMA, **body, "id": identity or checksum, "sha256": checksum}


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        rows = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("schema") != SCHEMA or not isinstance(row.get("payload"), dict):
                raise ValueError(f"unknown record at line {number}")
            body = {name: row[name] for name in ("kind", "task_id", "payload")}
            if not row.get("id") or digest(body) != row.get("sha256"):
                raise ValueError(f"checksum mismatch at line {number}")
            rows.append(row)
        return rows
    except (OSError, ValueError, KeyError) as exc:
        raise ChainBroken(f"history-source-error: {path}: {exc}") from exc


def read_records(root: Path, *, kind: str = "", task_id: str = "") -> list[dict[str, Any]]:
    folder = history_dir(root)
    current_path = folder / "current.jsonl"
    current = [{**row, "_source": str(current_path)} for row in _read(current_path)]
    rows = []
    for path in sorted(folder.glob("volume-*.jsonl")):
        rows.extend({**row, "_source": str(path)} for row in _read(path))
    rows.extend(current)
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        prior = found.get(row["id"])
        if prior and prior["sha256"] != row["sha256"]:
            raise ChainBroken(f"history-identity-conflict: {row['id']}")
        found[row["id"]] = row
    return [row for row in found.values() if (not kind or row["kind"] == kind) and (not task_id or row["task_id"] == task_id)]


def _publish(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as handle:
            for row in rows:
                handle.write(_encode(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        verified = _read(temporary)
        if verified != rows:
            raise ChainBroken(f"history-write-mismatch: {temporary}")
        os.replace(temporary, path)
        if _read(path) != rows:
            raise ChainBroken(f"history-publish-mismatch: {path}")
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _writer(root: Path):
    folder = history_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "writer.lock").open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ChainBroken("history-writer-busy: retry after the current writer")
                time.sleep(0.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_UN)


def _volume(root: Path, rows: list[dict[str, Any]]) -> Path:
    checksum = digest(rows)
    stamp = datetime.now(timezone.utc).strftime("%Y%m")
    path = history_dir(root) / f"volume-{stamp}-{checksum}.jsonl"
    if path.exists():
        if _read(path) != rows:
            raise ChainBroken(f"history-volume-conflict: {path}")
    else:
        _publish(path, rows)
    return path


def append_fact(root: Path, kind: str, task_id: str, payload: dict[str, Any], *, number_prefix: str = "", floor: int = 0) -> str:
    with _writer(root):
        path = history_dir(root) / "current.jsonl"
        rows = _read(path)
        if number_prefix:
            numbers = [floor]
            for prior in read_records(root, kind=kind):
                suffix = str(prior["payload"].get("report_id") or "").removeprefix(number_prefix + "-")
                if suffix.isdigit():
                    numbers.append(int(suffix))
            payload["report_id"] = f"{number_prefix}-{max(numbers) + 1}"
        incoming = record(kind, task_id, payload)
        if any(row["id"] == incoming["id"] for row in rows):
            return f"{path}#{incoming['id']}"
        month = datetime.now(timezone.utc).strftime("%Y%m")
        if rows and (sum(len(_encode(row)) + 1 for row in rows) + len(_encode(incoming)) > MAX_VOLUME_BYTES or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y%m") != month):
            _volume(root, rows)
            rows = []
        _publish(path, rows + [incoming])
        return f"{path}#{incoming['id']}"


def publish_archive(root: Path, records: list[dict[str, Any]]) -> list[str]:
    with _writer(root):
        known = {row["id"]: row["sha256"] for row in read_records(root)}
        pending = []
        for row in records:
            if row["id"] in known:
                if known[row["id"]] != row["sha256"]:
                    raise ChainBroken(f"history-identity-conflict: {row['id']}")
                continue
            pending.append(row)
            known[row["id"]] = row["sha256"]
        paths = []
        batch = []
        size = 0
        for row in pending:
            length = len(_encode(row)) + 1
            if batch and size + length > MAX_VOLUME_BYTES:
                paths.append(str(_volume(root, batch)))
                batch, size = [], 0
            batch.append(row)
            size += length
        if batch:
            paths.append(str(_volume(root, batch)))
        actual = {row["id"]: row["sha256"] for row in read_records(root)}
        if any(actual.get(row["id"]) != row["sha256"] for row in records):
            raise ChainBroken("history-archive-incomplete: originals retained")
        return paths


def rebuild_index(root: Path) -> dict[str, Any]:
    rows = read_records(root)
    tasks: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row["task_id"]:
            continue
        entry = tasks.setdefault(row["task_id"], {"count": 0, "kinds": []})
        entry["count"] += 1
        if row["kind"] not in entry["kinds"]:
            entry["kinds"].append(row["kind"])
    result = {"schema": "ag.history.index.v1", "count": len(rows), "tasks": tasks, "sha256": digest(rows)}
    path = history_dir(root) / "index.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return result


def _migration_source(path: Path, base: Path) -> bool:
    try:
        relative = path.relative_to(base)
        parts = relative.parts
        allowed = (
            len(parts) == 2 and parts[0] == "tasks" and path.suffix == ".json"
            or len(parts) == 2 and parts[0] == "tickets" and path.suffix == ".md"
            or len(parts) == 3 and parts[:2] == ("knowledge", "sessions") and path.suffix == ".json"
            or len(parts) == 1 and path.name in {"ticket.jsonl", "switch.jsonl", "critic.jsonl"}
        )
        if not allowed:
            return False
        current = base
        for part in relative.parts:
            current = current / part
            attributes = current.lstat()
            if current.is_symlink() or getattr(attributes, "st_file_attributes", 0) & 0x400:
                return False
        return path.is_file() and path.resolve(strict=True) == base.resolve(strict=True) / relative
    except (OSError, ValueError):
        return False


def migrate_closed(root: Path, active_id: str = "") -> dict[str, Any]:
    base = project_dir(root)
    records = []
    sources: dict[Path, bytes] = {}
    retained = []
    closed = set()
    for path in sorted((base / "knowledge" / "sessions").glob("*.json")):
        try:
            if not _migration_source(path, base):
                raise ValueError("linked or unavailable session source")
            raw = path.read_bytes()
            blob = json.loads(raw)
            if not isinstance(blob, dict) or blob.get("schema") != "ag.knowledge.session.v1" or blob.get("task_id") != path.stem or blob.get("process") not in {"completed", "abandoned"}:
                raise ValueError("unknown session")
            if path.stem != active_id:
                closed.add(path.stem)
                records.append(record("session", path.stem, blob))
                sources[path] = raw
        except (OSError, ValueError):
            retained.append(str(path))
    for row in read_records(root, kind="task-step"):
        if row["payload"].get("phase") in {"finish", "abandon"} and row["task_id"] != active_id:
            closed.add(row["task_id"])
    for path in sorted((base / "tasks").glob("*.json")):
        if path.stem == active_id or path.name == "task.json":
            continue
        try:
            if not _migration_source(path, base):
                raise ValueError("linked or unavailable timeline source")
            raw = path.read_bytes()
            blob = json.loads(raw)
            if not isinstance(blob, dict) or blob.get("task_id") != path.stem:
                raise ValueError("ambiguous task identity")
            steps = blob.get("steps")
            if isinstance(steps, list) and any(not isinstance(step, dict) or step.get("task_id", path.stem) != path.stem for step in steps):
                raise ValueError("ambiguous step identity")
            ended = isinstance(steps, list) and any(step.get("phase", step.get("step")) in {"finish", "abandon"} for step in steps)
            if not ended and path.stem not in closed and not (blob.get("compacted") is True and blob.get("process") in {"finish", "abandon", "completed", "abandoned"}):
                raise ValueError("task not closed")
            closed.add(path.stem)
            records.append(record("timeline", path.stem, blob))
            sources[path] = raw
        except (OSError, ValueError):
            retained.append(str(path))
    for path in sorted((base / "tickets").glob("*.md")):
        if path.stem not in closed or path.stem == active_id:
            continue
        try:
            if not _migration_source(path, base):
                raise ValueError("linked or unavailable ticket source")
            raw = path.read_bytes()
            # Keep `raw` for the immutable source comparison below. Only the
            # derived ticket text uses Path.read_text()'s universal-newline
            # semantics, so LF, CRLF and CR have the same history identity.
            text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if f"task: {path.stem}" not in text.splitlines():
                raise ValueError("ambiguous ticket identity")
            records.append(record("ticket", path.stem, {"task_id": path.stem, "text": text}))
            sources[path] = raw
        except (OSError, ValueError):
            retained.append(str(path))
    replacements = {}
    for table, name in (("ticket_event", "ticket.jsonl"), ("switch_event", "switch.jsonl"), ("critic_event", "critic.jsonl")):
        path = base / name
        if not path.is_file():
            continue
        try:
            if not _migration_source(path, base):
                raise ValueError("linked review source")
            raw = path.read_bytes()
            events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            if not all(isinstance(event, dict) and event.get("report_id") and event.get("task_id") for event in events):
                raise ValueError("unknown review event")
            keep = []
            for event in events:
                if event["task_id"] in closed and event["task_id"] != active_id:
                    records.append(record(table, event["task_id"], event))
                else:
                    keep.append(event)
            if len(keep) < len(events):
                sources[path] = raw
                replacements[path] = b"".join(_encode(event) + b"\n" for event in keep)
        except (OSError, ValueError):
            retained.append(str(path))
    volumes = publish_archive(root, records)
    removed = []
    freed = 0
    for path, original in sources.items():
        if not _migration_source(path, base) or path.read_bytes() != original:
            raise ChainBroken(f"history-source-changed: retained {path}")
        replacement = replacements.get(path)
        if replacement:
            temporary = path.with_suffix(".migrating")
            try:
                with temporary.open("wb") as handle:
                    handle.write(replacement)
                    handle.flush()
                    os.fsync(handle.fileno())
                if temporary.read_bytes() != replacement:
                    raise ChainBroken(f"history-remainder-mismatch: {path}")
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            freed += len(original) - len(replacement)
        else:
            path.unlink()
            removed.append(str(path.relative_to(base)))
            freed += len(original)
    index = rebuild_index(root)
    return {"volumes": volumes, "removed": removed, "retained": retained, "freed_bytes": freed, "indexed_records": index["count"]}
