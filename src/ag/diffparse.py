"""Unified diff parsing with hunk counts as the boundary between content and metadata."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterator

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Line:
    raw: str
    kind: str
    path: str = ""
    old: int = 0
    new: int = 0
    old_count: int = 0
    new_count: int = 0


def _path(raw: str) -> str:
    # Git may still quote paths containing tabs/quotes even with quotePath=false.
    value = raw.split("\t", 1)[0]
    if value.startswith('"'):
        value = json.loads(value)
    if value == "/dev/null":
        return ""
    return value[2:] if value.startswith(("a/", "b/")) else value


def parse(text: str) -> Iterator[Line]:
    """Yield every input line; add/delete/context consume the two hunk counts.

    Paths refer to the new file, or the old file for a deletion. Metadata and
    no-newline markers never advance line numbers. No file header is inspected
    while there are hunk lines left to consume.
    """
    path = old_path = ""
    old = new = old_left = new_left = 0
    for raw in str(text or "").splitlines():
        if raw.startswith("\\ No newline at end of file"):
            yield Line(raw, "meta", path)
            continue
        if old_left or new_left:
            prefix = raw[:1]
            if prefix == "+" and new_left:
                yield Line(raw, "add", path, old, new)
                new += 1
                new_left -= 1
                continue
            if prefix == "-" and old_left:
                yield Line(raw, "delete", path, old, new)
                old += 1
                old_left -= 1
                continue
            if prefix == " " and old_left and new_left:
                yield Line(raw, "context", path, old, new)
                old += 1
                new += 1
                old_left -= 1
                new_left -= 1
                continue
            # Truncated/malformed hunks do not license new file-header parsing.
            yield Line(raw, "meta", path)
            continue
        if raw.startswith("diff --git "):
            path = old_path = ""
        elif raw.startswith("--- "):
            old_path = _path(raw[4:])
        elif raw.startswith("+++ "):
            path = _path(raw[4:]) or old_path
            yield Line(raw, "file", path)
            continue
        match = _HUNK.match(raw)
        if match:
            old, new = int(match[1]), int(match[3])
            old_left = int(match[2]) if match[2] is not None else 1
            new_left = int(match[4]) if match[4] is not None else 1
            yield Line(raw, "hunk", path, old, new, old_left, new_left)
        else:
            yield Line(raw, "meta", path)


def added_lines(text: str) -> list[tuple[str, int, str]]:
    return [(line.path, line.new, line.raw[1:]) for line in parse(text) if line.kind == "add" and line.path]


def annotate(text: str, max_chars: int = 48_000) -> tuple[str, dict[str, list[int]]]:
    touched: dict[str, list[int]] = {}
    output = []
    for line in parse(text):
        if line.path and line.kind in {"add", "delete", "context"}:
            number = line.old if line.kind == "delete" else line.new
            output.append(f"{line.path}:{number} | {line.raw}")
            bucket = touched.setdefault(line.path, [])
            target = max(1, line.new) if line.kind == "delete" else line.new
            if target > 0 and target not in bucket:
                bucket.append(target)
        else:
            output.append(line.raw)
    result = "\n".join(output)
    if text.endswith("\n") and result:
        result += "\n"
    return (result[:max_chars] if max_chars > 0 else result), touched
