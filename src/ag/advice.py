"""Run lift/see strategies. Advice only. Probes bind to lane-seq.

Handlers may persist only under catalog.plug_dir(root, lane, seq).
Never write the product tree; unplug deletes that folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .catalog import enabled, list_lane, plug_dir
from .managed import load_managed, lookup_project, project_key, real_root
from .see import note

_CSS_CLASS = re.compile(r"""(?<![0-9A-Za-z_-])\.([A-Za-z_][\w-]{2,})""")
_SKIP_DIR = {"node_modules", "dist", "__pycache__", ".git"}
_DOOR_SUFFIX = {".css", ".py", ".js", ".mjs", ".ts", ".tsx"}


def _git(cwd: Path, *args: str) -> str:
    ran = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return (ran.stdout or "").strip()


def _task(root: Path) -> dict[str, Any] | None:
    from .loop import load_task

    item = lookup_project(root)
    if item is None:
        return None
    return load_task(str(item.get("key") or project_key(root)))


def _wt(root: Path) -> Path | None:
    task = _task(root)
    if not task:
        return None
    path = Path(str(task.get("worktree") or ""))
    return path if path.is_dir() else None


def _repo(root: Path) -> Path:
    return real_root(root)


def _touched(root: Path) -> list[str]:
    cwd = _wt(root) or _repo(root)
    names = _git(cwd, "diff", "--name-only", "HEAD").splitlines()
    extra = _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines()
    out = []
    for name in names + extra:
        name = name.strip()
        if name and name not in out:
            out.append(name)
        if len(out) >= 24:
            break
    return out


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, blob: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lift_1(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    hits = []
    for rel in _touched(root):
        stem = Path(rel).stem
        if len(stem) < 3:
            continue
        found = [f for f in _git(repo, "grep", "-l", "-I", stem).splitlines() if f.replace("\\", "/") != rel.replace("\\", "/")]
        if found:
            hits.append({"file": rel, "also": found[:5]})
    return {"hits": hits}


def lift_2(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    cwd = _wt(root) or repo
    cmd: list[str] | None = None
    if (repo / "ruff.toml").is_file() or (repo / ".ruff.toml").is_file():
        cmd = ["ruff", "check", "."]
    elif (repo / "pyrightconfig.json").is_file():
        cmd = ["pyright"]
    if not cmd:
        return {"detail": "no repo linter config"}
    ran = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    return {"exit": ran.returncode, "tail": ((ran.stdout or "") + (ran.stderr or ""))[-1500:]}


def lift_3(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    task = _task(root) or {}
    return {"portrait": str(task.get("portrait") or "")}


def lift_4(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cmd = os.environ.get("AG_LIFT_CMD")
    if not cmd:
        return {"detail": "no AG_LIFT_CMD, skipped"}
    cwd = _wt(root) or _repo(root)
    ran = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True, text=True, check=False)
    return {"exit": ran.returncode, "tail": ((ran.stdout or "") + (ran.stderr or ""))[-1500:]}


def lift_5(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    logs = []
    for rel in _touched(root)[:8]:
        logs.append({"file": rel, "log": _git(repo, "log", "-3", "--oneline", "--", rel)})
    return {"logs": logs}


def lift_6(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    near = []
    for rel in _touched(root)[:8]:
        stem = Path(rel).stem
        found = _git(repo, "grep", "-l", "-I", stem, "--", "tests", "test").splitlines()[:6]
        named = [f for f in _git(repo, "ls-files").splitlines() if "test" in f.lower() and stem in Path(f).name][:6]
        files = list(dict.fromkeys(found + named))
        if files:
            near.append({"file": rel, "tests": files})
    return {"near": near}


def lift_7(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    verify = ((_task(root) or {}).get("verify") or {}) if _task(root) else {}
    if not isinstance(verify, dict):
        verify = {}
    return {"exit": verify.get("exit"), "stderr": str(verify.get("stderr") or "")[-1500:]}


def lift_8(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    cwd = _wt(root) or repo
    tracked = _git(repo, "ls-files").splitlines()
    names = {Path(f).name: f for f in tracked}
    clash = []
    for rel in _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines():
        name = Path(rel).name
        if name in names and names[name].replace("\\", "/") != rel.replace("\\", "/"):
            clash.append({"new": rel, "existing": names[name]})
    return {"clash": clash}


def lift_9(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    return {"suggest": [f"empty input / missing file for {rel}" for rel in _touched(root)[:6]]}


def lift_10(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _wt(root) or _repo(root)
    return {"stat": _git(cwd, "diff", "--stat", "HEAD")[:1500]}


def lift_11(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    return lift_4(root, item)


def _anchors(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows = task.get("anchors") if isinstance(task.get("anchors"), list) else []
    anchors = []
    for index, item in enumerate(rows, 1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            anchors.append({"id": str(item.get("id") or f"a{index}"), "text": text, "kind": str(item.get("kind") or ("hard" if item.get("hard") else "soft"))})
    return anchors


def _lift_signal(root: Path) -> dict[str, Any]:
    task = _task(root) or {}
    cwd = _wt(root) or _repo(root)
    touched = _touched(root)
    verify = task.get("verify") if isinstance(task.get("verify"), dict) else {}
    return {
        "portrait_sha": hashlib.sha256(str(task.get("portrait") or "").encode("utf-8")).hexdigest()[:16],
        "touched_sha": hashlib.sha256("\n".join(touched).encode("utf-8")).hexdigest()[:16],
        "tree": _git(cwd, "rev-parse", "HEAD"),
        "verify_exit": verify.get("exit"),
        "touched": touched,
    }


def lift_12(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    task = _task(root) or {}
    anchors = _anchors(task)
    return {
        "anchors": anchors,
        "reminder": "Keep attention on anchors; do not turn them into fixed steps unless hard.",
    }


def lift_13(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    task = _task(root) or {}
    signal = _lift_signal(root)
    path = plug_dir(root, "lift", 13) / "signal.json"
    previous = _read_json(path, {})
    changed = previous != signal
    if changed:
        _write_json(path, signal)
    return {"changed": changed, "signal": signal}


def lift_14(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    path = plug_dir(root, "lift", 14) / "notes.jsonl"
    payload = {
        "t": time.time(),
        "portrait": str((_task(root) or {}).get("portrait") or ""),
        "touched": _touched(root)[:24],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"note": "raw task snapshot stored out-of-tree; discarded on unplug/task end"}


def _tree(root: Path) -> Path:
    return _wt(root) or _repo(root)


def _rel_posix(rel: str) -> str:
    return rel.replace("\\", "/").strip()


def _skip_rel(rel: str) -> bool:
    parts = {p.lower() for p in _rel_posix(rel).split("/")}
    return bool(parts & _SKIP_DIR)


def _scan_files(cwd: Path) -> list[str]:
    names = _git(cwd, "ls-files").splitlines() + _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        rel = _rel_posix(raw)
        if not rel or rel in seen or _skip_rel(rel):
            continue
        if Path(rel).suffix.lower() not in _DOOR_SUFFIX:
            continue
        seen.add(rel)
        out.append(rel)
        if len(out) >= 400:
            break
    return out


def see_1(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    from .see import usage

    report = usage(root, "ship")
    return {"never_used": report.get("never_used"), "top": [x for x in report.get("items") or [] if x.get("hits")][:8]}


def see_2(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    tracked = _git(repo, "ls-files").splitlines()
    tests = [p for p in tracked if "test" in p.replace("\\", "/").lower()]
    body = []
    for rel in tests[:40]:
        try:
            body.append((repo / rel).read_text(encoding="utf-8", errors="ignore")[:4000])
        except OSError:
            continue
    blob = "\n".join(body)
    undeclared = [
        p
        for p in tracked
        if p.endswith((".py", ".ts", ".js", ".tsx"))
        and "test" not in p.replace("\\", "/").lower()
        and Path(p).name not in blob
        and Path(p).stem not in blob
    ]
    _write_json(plug_dir(root, "see", 2) / "zone.json", {"undeclared_n": len(undeclared), "t": time.time()})
    return {"count": len(undeclared), "files": undeclared[:40]}


def see_3(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _wt(root) or _repo(root)
    return {"porcelain": _git(cwd, "status", "--porcelain")[:2000], "worktree": str(_wt(root) or "")}


def see_4(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    from .see import _usage_path

    path = _usage_path(project_key(root))
    blocks = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines()[::-1]:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "block":
                blocks.append(row)
            if len(blocks) >= 5:
                break
    return {"blocks": blocks}


def _hook_ok(root: Path) -> bool:
    configured = _git(root, "config", "--local", "--get", "core.hooksPath")
    if not configured:
        return False
    key = _git(root, "config", "--local", "--get", "ag.key") or project_key(root)
    folder = Path(os.environ.get("AG_HOME") or Path.home() / ".ag") / "hooks" / key
    return (
        Path(configured).resolve() == folder.resolve()
        and (folder / "pre-commit").is_file()
        and (folder / "prepare-commit-msg").is_file()
    )


def see_5(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    u = see_1(root, _item)
    last = (see_4(root, _item).get("blocks") or [{}])[0]
    dirty = False
    for line in _git(repo, "status", "--porcelain").splitlines():
        path = line[3:].replace("\\", "/").strip().strip('"')
        if path == ".ag" or path.startswith(".ag/"):
            continue
        dirty = True
        break
    hook = _hook_ok(repo)
    return {
        "hook_ok": hook,
        "dirty": dirty,
        "never_used_n": len(u.get("never_used") or []),
        "last_block": last,
    }


def see_6(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    item = lookup_project(root) or {}
    wt = _wt(root)
    porcelain = _git(wt, "status", "--porcelain") if wt else ""
    return {"last_product": item.get("last_product") or "", "last_process": item.get("last_process") or "", "worktree_dirty": bool(porcelain)}


def see_7(_root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = load_managed()
    rows = []
    for proj in blob.get("projects") or []:
        if isinstance(proj, dict):
            rows.append({"root": proj.get("root"), "real": proj.get("real"), "key": proj.get("key")})
    return {"projects": rows}


def see_8(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    prev = _read_json(plug_dir(root, "see", 2) / "zone.json", {})
    now = see_2(root, _item)
    old = int(prev.get("undeclared_n") or now["count"])
    return {"was": old, "now": now["count"], "delta": now["count"] - old}


def see_9(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    repo = _repo(root)
    chain = []
    for rel in _touched(root)[:8]:
        chain.append({"file": rel, "head": _git(repo, "log", "-1", "--format=%h %s", "--", rel)})
    return {"chain": chain}



def _css_symptoms(root: Path) -> list[dict[str, Any]]:
    """Record repeated CSS selectors as symptoms; this is not a diagnosis."""
    cwd = _tree(root)
    owners: dict[str, list[str]] = {}
    file_details: dict[str, list[dict[str, int]]] = {}
    consumers: dict[str, list[str]] = {}
    for rel in _scan_files(cwd):
        path = cwd / rel
        suffix = Path(rel).suffix.lower()
        if suffix not in {".css", ".tsx", ".ts", ".js", ".mjs"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if suffix == ".css":
            lines = text.splitlines()
            for name in dict.fromkeys(_CSS_CLASS.findall(text)):
                selectors = sum(1 for line in lines if name in line)
                important = sum(1 for line in lines if name in line and "!important" in line)
                owners.setdefault(name, []).append(rel)
                file_details.setdefault(name, []).append(
                    {"file": rel, "selectors": selectors, "important": important}
                )
        else:
            for name in dict.fromkeys(_CSS_CLASS.findall(text)):
                consumers.setdefault(name, []).append(rel)

    rows: list[dict[str, Any]] = []
    for name, files in owners.items():
        details = file_details.get(name) or []
        important = sum(int(item.get("important") or 0) for item in details)
        selectors = sum(int(item.get("selectors") or 0) for item in details)
        if len(files) < 2 or (important == 0 and len(files) < 3):
            continue
        commit_sets = []
        for rel in files[:8]:
            commit_sets.append(set(_git(cwd, "log", "--format=%H", "--", rel).splitlines()))
        co_change = 0
        if len(commit_sets) > 1:
            pairs = [left & right for left, right in zip(commit_sets, commit_sets[1:])]
            co_change = len(set().union(*pairs)) if pairs else 0
        rows.append(
            {
                "kind": "css-selector",
                "locator": f".{name}",
                "files": files,
                "file_details": details,
                "important": important,
                "selectors": selectors,
                "consumers": list(dict.fromkeys(consumers.get(name) or [])),
                "co_change": co_change,
            }
        )
    rows.sort(key=lambda row: (len(row["files"]), row["important"], row["selectors"]), reverse=True)
    return rows[:12]


def see_10(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    symptoms = _css_symptoms(root)
    _write_json(
        plug_dir(root, "see", 10) / "symptoms.json",
        {"t": time.time(), "symptoms": symptoms},
    )
    return {"symptoms": symptoms[:8]}


def see_11(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _read_json(plug_dir(root, "see", 10) / "symptoms.json", {})
    symptoms = blob.get("symptoms") if isinstance(blob, dict) else []
    if not isinstance(symptoms, list) or not symptoms:
        symptoms = _css_symptoms(root)
        _write_json(
            plug_dir(root, "see", 10) / "symptoms.json",
            {"t": time.time(), "symptoms": symptoms},
        )
    rows = []
    for symptom in symptoms[:8]:
        if not isinstance(symptom, dict):
            continue
        details = symptom.get("file_details") or []
        owners = [str(item.get("file") or "") for item in details if item.get("file")]
        modifiers = [
            str(item.get("file") or "")
            for item in details
            if int(item.get("selectors") or 0) > 1
        ]
        overriders = [
            str(item.get("file") or "")
            for item in details
            if int(item.get("important") or 0) > 0
        ]
        rows.append(
            {
                "locator": symptom.get("locator"),
                "definers": owners,
                "modifiers": list(dict.fromkeys(modifiers)),
                "overriders": list(dict.fromkeys(overriders)),
                "consumers": symptom.get("consumers") or [],
            }
        )
    return {"ownership": rows}


def _current_redlines(root: Path, task: dict[str, Any]) -> list[str]:
    from .ticket_doc import previous_redlines, section_lines, split_document, ticket_path

    lines = [str(x).strip() for x in (task.get("redlines") or []) if str(x).strip()]
    if lines:
        return lines
    repo = _repo(root)
    copied = previous_redlines(repo)
    if copied:
        return copied
    tpath = ticket_path(repo)
    if tpath.is_file():
        try:
            _, red_body = split_document(tpath.read_text(encoding="utf-8"))
            return section_lines(red_body)
        except OSError:
            return []
    return []


def lift_15(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    from .ticket_doc import dropped_redlines

    task = _task(root) or {}
    path = plug_dir(root, "lift", 15) / "redlines.json"
    prev_blob = _read_json(path, {})
    if isinstance(prev_blob, dict):
        prev_list = [str(x).strip() for x in (prev_blob.get("redlines") or []) if str(x).strip()]
    elif isinstance(prev_blob, list):
        prev_list = [str(x).strip() for x in prev_blob if str(x).strip()]
    else:
        prev_list = []
    current = _current_redlines(root, task)
    dropped = [str(x).strip() for x in (task.get("dropped_redlines") or []) if str(x).strip()]
    if not dropped and prev_list:
        dropped = dropped_redlines(prev_list, current)
    _write_json(
        path,
        {
            "t": time.time(),
            "redlines": current,
            "dropped_redlines": dropped,
        },
    )
    return {"dropped_redlines": dropped, "changed": bool(dropped)}


_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".rs", ".go"}
_SWALLOW_SINGLE_RE = re.compile(
    r"(?:\bex"
    + r"cept(?:\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|\.\.\.)\b|\bca"
    + r"tch\s*(?:\([^)]*\))?\s*\{\s*\})"
)
_EXCEPT_HEAD_RE = re.compile(
    r"^\s*ex" + r"cept(?:\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?)?\s*:\s*(?:#.*)?$"
)
_PASS_BODY_RE = re.compile(r"^\s*(?:pass|\.\.\.)\s*(?:#.*)?$")
_MOCK_PROD_RE = re.compile(
    r"(?:\b(?:mo"
    + r"ck|fix"
    + r"ture|fa"
    + r"ke_\w+|MagicMo"
    + r"ck|monkey"
    + r"patch|PYTEST_"
    + r"CURRENT_TEST)\b)",
    re.IGNORECASE,
)
_STUB_RE = re.compile(
    r"(?:\b(?:TO" + r"DO|FIX" + r"ME|NotImple" + r"mentedError)\b|\b(?:to" + r"do|unimple" + r"mented)!\s*\()"
)
_HUNK_LINE_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _is_non_prod_path(rel: str) -> bool:
    norm = _rel_posix(rel).lower()
    return (
        not norm
        or Path(norm).suffix.lower() not in _CODE_SUFFIXES
        or "test" in norm
        or norm.startswith(".ag-check/")
        or "/.ag-check/" in f"/{norm}"
        or norm.startswith(".data/")
        or _skip_rel(norm)
    )


def _classify_shortcut(line: str, prev_added: str) -> str:
    if _SWALLOW_SINGLE_RE.search(line) or (_EXCEPT_HEAD_RE.match(prev_added) and _PASS_BODY_RE.match(line)):
        return "swallow_exception"
    if _MOCK_PROD_RE.search(line):
        return "mock_or_fixture_in_prod"
    if _STUB_RE.search(line):
        return "placeholder_stub"
    return ""


def lift_16(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _tree(root)
    diff_text = _git(cwd, "diff", "-U0", "HEAD")
    hits: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    cur_file = ""
    line_no = 0
    prev_added = ""
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            cur_file = "" if target == "/dev/null" else _rel_posix(target)
            if cur_file:
                seen_files.add(cur_file)
            prev_added = ""
            continue
        if raw.startswith("@@ "):
            match = _HUNK_LINE_RE.search(raw)
            line_no = int(match.group(1)) if match else 1
            prev_added = ""
            continue
        if not cur_file or _is_non_prod_path(cur_file):
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added = raw[1:]
            kind = _classify_shortcut(added, prev_added)
            if kind:
                hits.append(
                    {
                        "file": cur_file,
                        "line": line_no,
                        "kind": kind,
                        "snippet": added.strip()[:160],
                    }
                )
            prev_added = added
            line_no += 1
        elif not raw.startswith("-"):
            prev_added = ""
            line_no += 1

    for raw_rel in _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines():
        rel = _rel_posix(raw_rel)
        if not rel or rel in seen_files or _is_non_prod_path(rel):
            continue
        fpath = cwd / rel
        if not fpath.is_file():
            continue
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        prev_added = ""
        for idx, line in enumerate(lines, 1):
            kind = _classify_shortcut(line, prev_added)
            if kind:
                hits.append(
                    {
                        "file": rel,
                        "line": idx,
                        "kind": kind,
                        "snippet": line.strip()[:160],
                    }
                )
            prev_added = line

    _write_json(
        plug_dir(root, "lift", 16) / "shortcuts.json",
        {"t": time.time(), "count": len(hits), "shortcuts": hits[:12]},
    )
    return {"shortcuts": hits[:12], "count": len(hits)}


def lift_17(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _tree(root)
    head_files = [
        _rel_posix(f)
        for f in _git(cwd, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        if f.strip()
    ]
    diff_added = [
        _rel_posix(f)
        for f in _git(cwd, "diff", "--name-only", "--diff-filter=A", "HEAD").splitlines()
        if f.strip()
    ]
    untracked = [
        _rel_posix(f)
        for f in _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines()
        if f.strip()
    ]
    added_files = [
        rel
        for rel in dict.fromkeys(diff_added + untracked)
        if rel
        and "/" in rel
        and not rel.startswith(".ag-check/")
        and not rel.startswith(".data/")
        and not _skip_rel(rel)
    ]
    new_dirs: dict[str, list[str]] = {}
    for rel in added_files:
        parts = Path(rel).parts
        if len(parts) < 2:
            continue
        chosen = ""
        max_depth = min(len(parts) - 1, 3)
        for depth in range(1, max_depth + 1):
            cand = "/".join(parts[:depth])
            prefix = cand + "/"
            if not any(existing.startswith(prefix) for existing in head_files):
                chosen = cand
                break
        if chosen:
            new_dirs.setdefault(chosen, []).append(rel)

    all_files = [
        _rel_posix(f)
        for f in dict.fromkeys(
            _git(cwd, "ls-files").splitlines()
            + _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines()
        )
        if f.strip()
    ]
    report: list[dict[str, Any]] = []
    for mod_dir, mod_files in sorted(new_dirs.items()):
        mod_name = Path(mod_dir).name
        if len(mod_name) < 2:
            continue
        pattern = re.compile(rf"\b{re.escape(mod_name)}\b")
        prefix = mod_dir + "/"
        touchpoints: list[str] = []
        for rel in all_files:
            if (
                rel.startswith(prefix)
                or rel.startswith(".ag-check/")
                or rel.startswith(".data/")
                or _skip_rel(rel)
            ):
                continue
            fpath = cwd / rel
            if not fpath.is_file():
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                touchpoints.append(rel)
        suggestion = (
            f"converge {mod_dir} references ({len(touchpoints)} touchpoints) into a single composition-root mount point"
            if len(touchpoints) > 1
            else ""
        )
        report.append(
            {
                "module": mod_name,
                "directory": mod_dir,
                "files": mod_files[:10],
                "touchpoints": touchpoints[:12],
                "touchpoint_count": len(touchpoints),
                "single_mount": len(touchpoints) <= 1,
                "suggestion": suggestion,
            }
        )
    _write_json(
        plug_dir(root, "lift", 17) / "plug_mount.json",
        {"t": time.time(), "new_modules": report},
    )
    return {"new_modules": report}


_THERM_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".css", ".rs", ".go"}
_SUPPRESS_RE = re.compile(
    r"(?:#\s*type:\s*"
    + r"ignore\b|#\s*no"
    + r"qa\b|@ts-"
    + r"(?:ignore|expect-error)\b|eslint-"
    + r"disable\b|!\s*impor"
    + r"tant\b|#\[allow\(|//\s*no"
    + r"lint\b|\bunsa"
    + r"fe\s*\{)"
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]+from\s+)?|export\s+[^'"]+from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""
)
_FOUNDATION_STEMS = {"ticket_doc", "catalog", "managed", "store", "schema", "types", "models"}
_ENTRY_STEMS = {"loop", "mcp", "cli", "main", "app", "server", "__main__"}


def _resolve_py_candidates(cwd: Path, dotted: str) -> list[Path]:
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return []
    rel_mod = Path(*parts).with_suffix(".py")
    out: list[Path] = []
    for cand in (rel_mod, Path("src") / rel_mod):
        if (cwd / cand).is_file():
            out.append(cand)
    return out


def _py_upward_imports(cwd: Path, rel: str, text: str) -> list[dict[str, str]]:
    import ast

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    src_parts = Path(rel).parent.parts
    src_stem = Path(rel).stem
    hits: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            level = int(node.level or 0)
            module = str(node.module or "")
            if level >= 2:
                target = "." * level + module
                hits.append({"file": rel, "target": target, "reason": "parent-relative-import"})
                continue
            candidates = (
                [module] + [f"{module}.{a.name}" for a in node.names if a.name != "*"]
                if module
                else [a.name for a in node.names if a.name != "*"]
            )
            for dotted in candidates:
                leaf = dotted.split(".")[-1]
                if src_stem in _FOUNDATION_STEMS and leaf in _ENTRY_STEMS:
                    hits.append({"file": rel, "target": dotted, "reason": "foundation-imports-entry"})
                    break
                if level == 0:
                    matched = False
                    for cand in _resolve_py_candidates(cwd, dotted):
                        if len(cand.parent.parts) < len(src_parts):
                            hits.append(
                                {
                                    "file": rel,
                                    "target": _rel_posix(str(cand)),
                                    "reason": "deeper-imports-shallower",
                                }
                            )
                            matched = True
                            break
                    if matched:
                        break
        elif isinstance(node, ast.Import):
            for alias in node.names:
                dotted = str(alias.name or "")
                leaf = dotted.split(".")[-1]
                if src_stem in _FOUNDATION_STEMS and leaf in _ENTRY_STEMS:
                    hits.append({"file": rel, "target": dotted, "reason": "foundation-imports-entry"})
                    continue
                for cand in _resolve_py_candidates(cwd, dotted):
                    if len(cand.parent.parts) < len(src_parts):
                        hits.append(
                            {
                                "file": rel,
                                "target": _rel_posix(str(cand)),
                                "reason": "deeper-imports-shallower",
                            }
                        )
                        break
    return hits


def _js_upward_imports(rel: str, text: str) -> list[dict[str, str]]:
    src_stem = Path(rel).stem
    hits: list[dict[str, str]] = []
    for match in _JS_IMPORT_RE.finditer(text):
        spec = match.group(1).strip()
        if spec.startswith("../"):
            hits.append({"file": rel, "target": spec, "reason": "parent-relative-import"})
        elif src_stem in _FOUNDATION_STEMS and Path(spec).stem in _ENTRY_STEMS:
            hits.append({"file": rel, "target": spec, "reason": "foundation-imports-entry"})
    return hits


def see_12(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _tree(root)
    diff_text = _git(cwd, "diff", "-U0", "HEAD")
    file_counts: dict[str, dict[str, int]] = {}
    seen_diff_files: set[str] = set()
    cur_file = ""
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            cur_file = "" if target == "/dev/null" else _rel_posix(target)
            if cur_file:
                seen_diff_files.add(cur_file)
            continue
        if not cur_file or Path(cur_file).suffix.lower() not in _THERM_SUFFIXES:
            continue
        if cur_file.startswith(".ag-check/") or _skip_rel(cur_file):
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            found = len(_SUPPRESS_RE.findall(raw[1:]))
            if found:
                slot = file_counts.setdefault(cur_file, {"added": 0, "removed": 0})
                slot["added"] += found
        elif raw.startswith("-") and not raw.startswith("---"):
            found = len(_SUPPRESS_RE.findall(raw[1:]))
            if found:
                slot = file_counts.setdefault(cur_file, {"added": 0, "removed": 0})
                slot["removed"] += found

    for raw_rel in _git(cwd, "ls-files", "-o", "--exclude-standard").splitlines():
        rel = _rel_posix(raw_rel)
        if not rel or rel in seen_diff_files or Path(rel).suffix.lower() not in _THERM_SUFFIXES:
            continue
        if rel.startswith(".ag-check/") or _skip_rel(rel):
            continue
        fpath = cwd / rel
        if not fpath.is_file():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found = len(_SUPPRESS_RE.findall(text))
        if found:
            slot = file_counts.setdefault(rel, {"added": 0, "removed": 0})
            slot["added"] += found

    by_file: list[dict[str, Any]] = []
    delta = 0
    for rel, counts in sorted(file_counts.items()):
        file_delta = counts["added"] - counts["removed"]
        delta += file_delta
        by_file.append(
            {
                "file": rel,
                "added": counts["added"],
                "removed": counts["removed"],
                "delta": file_delta,
            }
        )

    upward: list[dict[str, str]] = []
    for rel in _touched(root):
        rel = _rel_posix(rel)
        if not rel or rel.startswith(".ag-check/") or _skip_rel(rel):
            continue
        suffix = Path(rel).suffix.lower()
        if suffix not in {".py", ".ts", ".tsx", ".js", ".mjs"}:
            continue
        fpath = cwd / rel
        if not fpath.is_file():
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if suffix == ".py":
            upward.extend(_py_upward_imports(cwd, rel, text))
        else:
            upward.extend(_js_upward_imports(rel, text))

    result = {
        "suppression_delta": delta,
        "suppressions": by_file[:10],
        "upward_imports": upward[:10],
    }
    _write_json(plug_dir(root, "see", 12) / "thermometer.json", {"t": time.time(), **result})
    return result


def see_13(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    from .critic import MAX_CHECK_FILE_BYTES, _BINARY_CHECK_SUFFIXES
    from .managed import ag_home
    from .ticket_doc import copy_path, previous_redlines

    repo = _repo(root)
    cwd = _tree(root)
    proj_dir = ag_home() / "projects" / project_key(repo)
    critic_live = proj_dir / "critic-live.jsonl"
    switch_live = proj_dir / "switch-live.jsonl"
    critic_bytes = critic_live.stat().st_size if critic_live.is_file() else 0
    switch_bytes = switch_live.stat().st_size if switch_live.is_file() else 0

    task = _task(root) or {}
    sealed_list = [str(x).strip() for x in (task.get("redlines") or []) if str(x).strip()]
    if not sealed_list:
        sealed_list = previous_redlines(repo)
    redlines_sealed = bool(copy_path(repo).is_file() or ("redlines" in task))

    excluded: list[dict[str, Any]] = []
    check_dir = cwd / ".ag-check"
    if check_dir.is_dir():
        for path in sorted(check_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.resolve().relative_to(cwd.resolve()).as_posix()
                size = path.stat().st_size
            except (OSError, ValueError):
                continue
            if path.suffix.lower() in _BINARY_CHECK_SUFFIXES or "__pycache__" in path.parts:
                excluded.append({"path": rel, "reason": "binary", "bytes": size})
            elif size > MAX_CHECK_FILE_BYTES:
                excluded.append({"path": rel, "reason": "oversize", "bytes": size})

    summary = {
        "critic_live_bytes": critic_bytes,
        "switch_live_bytes": switch_bytes,
        "redlines_sealed": redlines_sealed,
        "redlines_count": len(sealed_list),
        "excluded_check_files": excluded[:20],
        "excluded_check_count": len(excluded),
    }
    _write_json(plug_dir(root, "see", 13) / "seat_health.json", {"t": time.time(), **summary})
    return summary


def see_14(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    from .ticket_doc import section_lines, split_document, ticket_path, tickets_dir

    repo = _repo(root)
    tdir = tickets_dir(repo)
    ticket_files: list[Path] = []
    if tdir.is_dir():
        ticket_files = sorted(
            (p for p in tdir.glob("*.md") if p.is_file()),
            key=lambda p: (p.stat().st_mtime, p.name),
            reverse=True,
        )
    recent: list[str] = []
    freq: dict[str, int] = {}
    seen_ids: set[str] = set()

    for path in ticket_files:
        tid = path.stem
        seen_ids.add(tid)
        recent.append(tid)
        try:
            _, red_body = split_document(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        for line in section_lines(red_body):
            freq[line] = freq.get(line, 0) + 1

    active_path = ticket_path(repo)
    if active_path.is_file():
        try:
            raw_active = active_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            raw_active = ""
        if raw_active:
            task_id = str((_task(root) or {}).get("id") or "active")
            if task_id not in seen_ids:
                seen_ids.add(task_id)
                recent.insert(0, task_id)
                _, red_body = split_document(raw_active)
                for line in section_lines(red_body):
                    freq[line] = freq.get(line, 0) + 1

    top_redlines = [
        {"redline": line, "text": line, "count": cnt}
        for line, cnt in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    ]
    summary = {
        "ticket_count": len(seen_ids),
        "recent_tickets": recent[:8],
        "top_redlines": top_redlines,
    }
    _write_json(plug_dir(root, "see", 14) / "trajectory.json", {"t": time.time(), **summary})
    return summary


HANDLERS = {
    ("lift", 1): lift_1,
    ("lift", 2): lift_2,
    ("lift", 3): lift_3,
    ("lift", 4): lift_4,
    ("lift", 5): lift_5,
    ("lift", 6): lift_6,
    ("lift", 7): lift_7,
    ("lift", 8): lift_8,
    ("lift", 9): lift_9,
    ("lift", 10): lift_10,
    ("lift", 11): lift_11,
    ("lift", 12): lift_12,
    ("lift", 13): lift_13,
    ("lift", 14): lift_14,
    ("lift", 15): lift_15,
    ("lift", 16): lift_16,
    ("lift", 17): lift_17,
    ("see", 1): see_1,
    ("see", 2): see_2,
    ("see", 3): see_3,
    ("see", 4): see_4,
    ("see", 5): see_5,
    ("see", 6): see_6,
    ("see", 7): see_7,
    ("see", 8): see_8,
    ("see", 9): see_9,
    ("see", 10): see_10,
    ("see", 11): see_11,
    ("see", 12): see_12,
    ("see", 13): see_13,
    ("see", 14): see_14,
}


def run_lane(lane: str, root: Path) -> dict[str, Any]:
    root = real_root(root)
    findings = []
    skipped = []
    for item in list_lane(lane):
        seq = int(item["seq"])
        code = str(item["code"])
        if not item.get("live"):
            continue
        if not enabled(root, lane, seq):
            skipped.append(code)
            continue
        fn = HANDLERS.get((lane, seq))
        if fn is None:
            continue
        try:
            payload = fn(root, item) or {}
        except Exception as exc:
            payload = {"error": str(exc)[:240]}
        kind = str(payload.get("kind") or "help")
        note(root, lane, seq, kind, str(payload.get("detail") or "")[:120])
        findings.append({"seq": seq, "code": code, "name": item["name"], **{k: v for k, v in payload.items() if k != "kind"}})
    return {
        "schema": f"ag.{lane}.v1",
        "lane": lane,
        "root": str(root),
        "findings": findings,
        "skipped": skipped,
        "reminder": "advice/findings only; cannot set product or refuse finish",
    }
