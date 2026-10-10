"""Generic subagent file contracts. Adapters are optional and vendor-neutral."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_SCHEMA = "ag.worker.task.v1"
RESULT_SCHEMA = "ag.worker.result.v1"
ALLOWED_STATUSES = {"done", "blocked", "partial"}
MAX_WORKERS = 3
LOG_SCHEMA = "ag.worker-log.v1"


def worker_count(worktree: Path) -> int:
    worker_root = worktree / ".ag-artifacts" / "workers"
    if not worker_root.is_dir():
        return 0
    return sum(1 for item in worker_root.iterdir() if item.is_dir())


def append_log(worktree: Path, worker_id: str, *, phase: str, **fields: Any) -> Path:
    path = worker_dir(worktree, worker_id) / "live.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "schema": LOG_SCHEMA,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "phase": str(phase),
    }
    row.update(fields)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
    return path


def _grok_executable(explicit: str = "") -> str:
    candidate = str(explicit or os.environ.get("AG_GROK_COMMAND") or "").strip() or "grok"
    if shutil.which(candidate):
        return candidate
    fallback = Path.home() / ".grok" / "bin" / ("grok.exe" if os.name == "nt" else "grok")
    if fallback.is_file():
        return str(fallback)
    raise FileNotFoundError("Grok CLI not found; set AG_GROK_COMMAND or install grok")


def _worker_proxy(worktree: Path, worker_id: str) -> Path:
    directory = worker_dir(worktree, worker_id)
    path = directory / "guard.py"
    if path.exists():
        path.unlink()
    code = r'''import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def resolve(path: str) -> Path:
    return Path(path) if Path(path).is_absolute() else (Path.cwd() / path).resolve()


def allowed(path: Path, roots: list[Path]) -> bool:
    try:
        return any(str(path.resolve()).startswith(str(root.resolve()) + os.sep) for root in roots)
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = list(args.argv)
    if argv and argv[0] == "python":
        argv[0] = sys.executable
    if not argv:
        return 2
    program = argv[0]
    lowered = program.lower()
    if program == "git" and len(argv) >= 2 and argv[1] in {"commit", "merge", "rebase", "push"}:
        print("AG worker guard: git commit/merge/rebase/push is forbidden", file=sys.stderr)
        return 126
    if lowered in {"ag", "ag.exe"} or (program.endswith("ag") and argv and argv[0] in {"start", "confirm-map", "verify", "finish", "abandon", "unenroll"}):
        print("AG worker guard: governance commands are forbidden", file=sys.stderr)
        return 126
    if program in {sys.executable, "python"} and len(argv) >= 2:
        script = argv[1]
        if script == "-m" and len(argv) >= 3 and argv[2] == "ag":
            print("AG worker guard: python -m ag is forbidden", file=sys.stderr)
            return 126
        if script.endswith("ag\\__main__.py") or script.endswith("ag/__main__.py"):
            print("AG worker guard: ag module is forbidden", file=sys.stderr)
            return 126
    roots = [Path(item).resolve() for item in json.loads(os.environ["AG_WORKER_WRITE_ROOTS"])]
    if program in {sys.executable, "python"} and argv and not (len(argv) >= 2 and argv[1] == "-c"):
        target = resolve(argv[1] if argv[1] != "-m" else argv[2])
        if not allowed(target, roots):
            print(f"AG worker guard: outside write roots: {target}", file=sys.stderr)
            return 126
    result = subprocess.run(argv, cwd=os.environ.get("AG_WORKER_CWD", os.getcwd()))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
'''
    path.write_text(code, encoding="utf-8")
    return path


def grok_argv(
    executable: str,
    *,
    worktree: Path,
    prompt_path: Path,
    guard_path: Path,
) -> list[str]:
    return [
        executable,
        "--cwd",
        str(worktree),
        "--verbatim",
        "--prompt-file",
        str(prompt_path),
        "--permission-mode",
        "acceptEdits",
        "--deny",
        "Bash(git commit*)",
        "--deny",
        "Bash(git merge*)",
        "--deny",
        "Bash(git rebase*)",
        "--deny",
        "Bash(git push*)",
        "--deny",
        "Bash(python -m ag*)",
        "--deny",
        "Bash(ag start*)",
        "--deny",
        "Bash(ag confirm-map*)",
        "--deny",
        "Bash(ag verify*)",
        "--deny",
        "Bash(ag finish*)",
        "--deny",
        "Bash(ag abandon*)",
        "--deny",
        "Bash(ag unenroll*)",
        "--no-subagents",
        "--tools",
        f"shell:{guard_path}",
        "--output-format",
        "plain",
    ]


def run_task(
    worktree: Path,
    worker_id: str,
    *,
    provider: str = "grok",
    command: str = "",
    timeout: float = 0,
    echo: bool = True,
) -> dict[str, Any]:
    if provider != "grok":
        raise ValueError(f"unsupported provider: {provider}")
    directory = worker_dir(worktree, worker_id)
    task_path = directory / "task.json"
    task_blob = json.loads(task_path.read_text(encoding="utf-8"))
    write_allow = [str(item) for item in task_blob.get("write_allow") or []]
    prompt_path = directory / "TASK.md"
    if not task_path.is_file() or not prompt_path.is_file():
        raise FileNotFoundError(f"worker dossier not found: {directory}")
    executable = _grok_executable(command)
    guard_path = _worker_proxy(worktree, worker_id)
    log_path = append_log(worktree, worker_id, phase="start", provider=provider, command=executable)
    environment = os.environ.copy()
    environment["AG_WORKER_WRITE_ROOTS"] = json.dumps(
        [str((worktree / item).resolve()) for item in write_allow]
    )
    environment["AG_WORKER_CWD"] = str(worktree)
    argv = grok_argv(executable, worktree=worktree, prompt_path=prompt_path, guard_path=guard_path)

    try:
        process = subprocess.Popen(
            argv,
            cwd=str(worktree),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
        )
    except OSError as exc:
        append_log(worktree, worker_id, phase="failed", error=str(exc), exit=127)
        raise

    output: list[str] = []

    def consume(stream: Any, phase: str) -> None:
        assert stream is not None
        for line in iter(stream.readline, ""):
            line = line.rstrip("\r\n")
            if not line:
                continue
            output.append(line)
            append_log(worktree, worker_id, phase=phase, text=line)
            if echo:
                print(f"[{worker_id}:{phase}] {line}", flush=True)

    threads = [
        threading.Thread(target=consume, args=(process.stdout, "stdout"), daemon=True),
        threading.Thread(target=consume, args=(process.stderr, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        if timeout > 0:
            process.wait(timeout=timeout)
        else:
            process.wait()
        for thread in threads:
            thread.join(timeout=5)
        exit_code = int(process.returncode)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        append_log(worktree, worker_id, phase="timeout", timeout=timeout)
        raise TimeoutError(f"Grok worker timed out after {timeout} seconds") from exc
    result_path = directory / "result.json"
    delivery_ok = result_path.is_file()
    if exit_code == 0 and not delivery_ok:
        append_log(
            worktree,
            worker_id,
            phase="failed",
            reason="result.json is missing after provider exit",
            exit=exit_code,
        )
    else:
        append_log(worktree, worker_id, phase="exit", exit=exit_code)
    return {
        "schema": "ag.worker-run.v1",
        "task_id": worker_id,
        "provider": provider,
        "exit": exit_code,
        "status": "done" if delivery_ok and exit_code == 0 else "failed",
        "reason": (
            ""
            if delivery_ok and exit_code == 0
            else (
                "result.json is missing after provider exit"
                if exit_code == 0
                else "provider exited with a non-zero code"
            )
        ),
        "log_path": str(log_path.resolve()),
        "result_path": str(result_path.resolve()),
        "output_tail": "\n".join(output[-200:]),
    }




def worker_dir(worktree: Path, worker_id: str = "") -> Path:
    worker_id = worker_id.strip() or f"w-{uuid.uuid4().hex[:8]}"
    return worktree / ".ag-artifacts" / "workers" / worker_id


def create_task(
    *,
    worktree: Path,
    portrait: str,
    anchors: list[dict[str, Any]],
    write_allow: list[str] | None = None,
    worker_id: str = "",
    intent_map_path: str = "",
    anchor_preview: str = "",
    guards: list[str] | None = None,
    defaults: list[str] | None = None,
) -> dict[str, Any]:
    if not str(portrait or "").strip():
        raise ValueError("worker task requires a portrait")
    if not anchors:
        raise ValueError("worker task requires task anchors")

    directory = worker_dir(worktree, worker_id)
    task_id = directory.name
    dossier: dict[str, Any] = {
        "schema": TASK_SCHEMA,
        "task_id": task_id,
        "worktree": str(worktree.resolve()),
        "portrait": str(portrait),
        "anchors": [dict(item) for item in anchors if isinstance(item, dict)],
        "write_allow": [str(item) for item in (write_allow or []) if str(item).strip()],
        "do_not": [
            "run ag finish",
            "merge into canonical",
            "modify anchors or verification gates",
            "claim acceptance",
        ],
        "intent_map_path": intent_map_path,
        "anchor_preview": anchor_preview,
        "guards": [str(item) for item in (guards or []) if str(item).strip()],
        "defaults": [str(item) for item in (defaults or []) if str(item).strip()],
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "task.json").write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = [
        "# AG Worker Task",
        "",
        f"Work only in: `{worktree}`",
        "",
        "## Portrait",
        portrait.strip(),
        "",
        "## Intent map",
        f"- Unicode map: `{intent_map_path}`",
        "",
        "```text",
        anchor_preview.strip(),
        "```",
        "",
        "## Anchors",
        *[f"- `{item.get('id')}` [{item.get('kind', 'soft')}]: {item.get('text')}" for item in dossier["anchors"]],
        "## Guards",
        *[f"- {item}" for item in dossier["guards"]],
        "## Defaults",
        *[f"- {item}" for item in dossier["defaults"]],
        "",
        "## Boundaries",
        *[f"- Do not {item.removeprefix('run ')}." for item in dossier["do_not"]],
        "",
        "## Delivery",
        "Write `result.json` beside `task.json` using schema `ag.worker.result.v1`.",
        "Report evidence and open questions; do not claim AG acceptance.",
    ]
    (directory / "TASK.md").write_text("\n".join(prompt) + "\n", encoding="utf-8")
    return {**dossier, "task_path": str((directory / "task.json").resolve()), "prompt_path": str((directory / "TASK.md").resolve())}


def read_result(worktree: Path, worker_id: str) -> dict[str, Any]:
    path = worker_dir(worktree, worker_id) / "result.json"
    if not path.is_file():
        raise FileNotFoundError(f"worker result not found: {path}")
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid worker result JSON: {path}") from exc
    if not isinstance(blob, dict):
        raise ValueError(f"worker result must be a JSON object: {path}")

    errors: list[str] = []
    if blob.get("schema") != RESULT_SCHEMA:
        errors.append("schema must be ag.worker.result.v1")
    if blob.get("task_id") != worker_id:
        errors.append("task_id does not match worker directory")
    if blob.get("status") not in ALLOWED_STATUSES:
        errors.append("status must be done, blocked, or partial")
    for field in ("changed_files", "evidence", "anchor_receipt", "open_questions"):
        if not isinstance(blob.get(field), list):
            errors.append(f"{field} must be a list")
    if errors:
        raise ValueError("; ".join(errors))

    blob["result_path"] = str(path.resolve())
    return blob
