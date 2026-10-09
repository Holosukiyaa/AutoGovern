"""Run lift/heal/see strategies. Advice only. Probes bind to lane-seq.

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

TTL = 7 * 86400
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?['"]([^'"]+)['"]""", re.I)
_JS_BARREL = re.compile(r"""export\s+\*\s+from\s+['"]([^'"]+)['"]""")
_CSS_CLASS = re.compile(r"""(?<![0-9A-Za-z_-])\.([A-Za-z_][\w-]{2,})""")
_SKIP_DIR = {"node_modules", "dist", "__pycache__", ".git"}
_DOOR_SUFFIX = {".css", ".py", ".js", ".mjs", ".ts", ".tsx"}


def _git(cwd: Path, *args: str) -> str:
    ran = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False)
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


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


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


def _resolve_spec(rel_file: str, spec: str) -> str | None:
    spec = spec.split("?", 1)[0].split("#", 1)[0].strip()
    if not spec or spec.startswith(("http://", "https://", "data:")):
        return None
    parts: list[str] = []
    for piece in (_rel_posix(str(Path(rel_file).parent / spec))).split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if parts:
                parts.pop()
            continue
        parts.append(piece)
    return "/".join(parts) if parts else None


def _py_reexport(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return False
    return all(
        ln.startswith(("import ", "from ", "__all__")) or " import " in ln
        for ln in lines
    )


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


def _doors(root: Path) -> dict[str, Any]:
    cwd = _tree(root)
    doors: list[dict[str, Any]] = []
    guest_files: dict[str, list[str]] = {}
    for rel in _scan_files(cwd):
        path = cwd / rel
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        suffix = Path(rel).suffix.lower()
        if suffix == ".css":
            imported = []
            for spec in _CSS_IMPORT.findall(text):
                target = _resolve_spec(rel, spec)
                if target:
                    imported.append(target)
            if imported:
                doors.append({"kind": "css-import", "file": rel, "imports": imported[:24]})
            for name in dict.fromkeys(_CSS_CLASS.findall(text)):
                guest_files.setdefault(name, [])
                if rel not in guest_files[name] and len(guest_files[name]) < 12:
                    guest_files[name].append(rel)
        elif suffix in {".js", ".mjs", ".ts", ".tsx"}:
            barrels = []
            for spec in _JS_BARREL.findall(text):
                target = _resolve_spec(rel, spec)
                if target:
                    barrels.append(target)
            if barrels:
                doors.append({"kind": "js-barrel", "file": rel, "imports": barrels[:24]})
        elif suffix == ".py" and Path(rel).name != "__init__.py" and _py_reexport(text):
            doors.append({"kind": "py-reexport", "file": rel})
    stack = []
    for guest, files in guest_files.items():
        if len(files) < 2:
            continue
        stack.append({"guest": guest, "kind": "css-selector", "doors": files})
        if len(stack) >= 12:
            break
    for row in doors:
        if row.get("kind") == "py-reexport":
            rel = str(row["file"])
            stem = Path(rel).stem
            callers = [
                o
                for o in _git(cwd, "grep", "-l", "-I", stem).splitlines()
                if _rel_posix(o) != rel
            ][:8]
            if callers:
                stack.append({"guest": stem, "kind": "py-reexport", "doors": [rel], "callers": callers})
            if len(stack) >= 12:
                break
    return {"schema": "ag.heal.doors.v1", "doors": doors[:40], "stack": stack}


def heal_1(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _doors(root)
    _write_json(plug_dir(root, "heal", 1) / "findings.json", {"t": time.time(), **blob})
    return {"doors": len(blob["doors"]), "stack": len(blob["stack"]), "cases": blob["stack"][:8]}


def heal_2(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _read_json(plug_dir(root, "heal", 1) / "findings.json", {})
    stack = blob.get("stack") if isinstance(blob, dict) else None
    if not isinstance(stack, list) or not stack:
        stack = _doors(root).get("stack") or []
    case = stack[0] if stack else None
    return {"case": case, "next": "ag_start", "cut": False}


def heal_3(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _read_json(plug_dir(root, "heal", 1) / "findings.json", {})
    age = time.time() - float(blob.get("t") or 0) if isinstance(blob, dict) else TTL + 1
    return {"stale": age > TTL, "age_s": int(age), "ttl_s": TTL}


def heal_4(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    cwd = _tree(root)
    path = plug_dir(root, "heal", 4) / "probes.json"
    store = _read_json(path, {})
    if not isinstance(store, dict):
        store = {}
    if not store:
        blob = _read_json(plug_dir(root, "heal", 1) / "findings.json", {})
        stack = blob.get("stack") if isinstance(blob, dict) else []
        for case in (stack or [])[:4]:
            if not isinstance(case, dict):
                continue
            for rel in (case.get("doors") or [])[:6]:
                file_path = cwd / str(rel)
                if str(rel) and file_path.is_file():
                    store[str(rel)] = _sha(file_path)
        _write_json(path, store)
    red = []
    for rel, pin in list(store.items())[:20]:
        file_path = cwd / str(rel)
        if not file_path.is_file():
            red.append({"file": rel, "state": "missing"})
        elif _sha(file_path) != pin:
            red.append({"file": rel, "state": "changed"})
    return {"pinned": len(store), "red": red}


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


def _symptom_class(symptom: dict[str, Any]) -> dict[str, Any]:
    files = len(symptom.get("files") or [])
    important = int(symptom.get("important") or 0)
    co_change = int(symptom.get("co_change") or 0)
    consumers = len(symptom.get("consumers") or [])
    if files < 2:
        classification = "noise"
    elif important == 0:
        classification = "incident"
    elif co_change == 0:
        classification = "risk"
    elif files >= 3 and important >= 5 and co_change >= 3:
        classification = "confirmed"
    else:
        classification = "suspected"
    return {
        "locator": symptom.get("locator"),
        "classification": classification,
        "reason": {
            "files": files,
            "important": important,
            "co_change": co_change,
            "consumers": consumers,
        },
    }


def heal_5(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _read_json(plug_dir(root, "see", 10) / "symptoms.json", {})
    symptoms = blob.get("symptoms") if isinstance(blob, dict) else []
    if not isinstance(symptoms, list) or not symptoms:
        symptoms = _css_symptoms(root)
    classifications = [_symptom_class(item) for item in symptoms[:8] if isinstance(item, dict)]
    _write_json(
        plug_dir(root, "heal", 5) / "triage.json",
        {"t": time.time(), "items": classifications},
    )
    return {"items": classifications}


def heal_6(root: Path, _item: dict[str, Any]) -> dict[str, Any]:
    blob = _read_json(plug_dir(root, "see", 10) / "symptoms.json", {})
    symptoms = blob.get("symptoms") if isinstance(blob, dict) else []
    if not isinstance(symptoms, list) or not symptoms:
        symptoms = _css_symptoms(root)
    ticket = None
    for symptom in symptoms:
        if not isinstance(symptom, dict):
            continue
        if _symptom_class(symptom).get("classification") != "confirmed":
            continue
        details = symptom.get("file_details") or []
        if not details:
            continue
        keep = max(
            details,
            key=lambda item: (int(item.get("important") or 0), int(item.get("selectors") or 0)),
        )
        remove = [
            str(item.get("file") or "")
            for item in details
            if str(item.get("file") or "") != str(keep.get("file") or "")
        ]
        ticket = {
            "case": symptom.get("locator"),
            "keep": str(keep.get("file") or ""),
            "remove": remove,
            "observe": [
                "build passes",
                "visual regression snapshot unchanged",
                "duplicate selector count decreases",
                "!important count does not increase",
            ],
            "cut": False,
        }
        break
    if ticket is not None:
        _write_json(plug_dir(root, "heal", 6) / "ticket.json", {"t": time.time(), **ticket})
    return {"ticket": ticket}

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
    ("heal", 1): heal_1,
    ("heal", 2): heal_2,
    ("heal", 3): heal_3,
    ("heal", 4): heal_4,
    ("heal", 5): heal_5,
    ("heal", 6): heal_6,
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
