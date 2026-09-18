"""Read-only critic pack and one-shot critic chat.

Not a worker ticket. Does not write product files or refuse finish.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .managed import ChainBroken, ag_home, project_key, real_root
from .probe import evaluate as evaluate_probes

PACK_SCHEMA = "ag.critic-pack.v1"
RUN_SCHEMA = "ag.critic-run.v1"
MAX_FILE_CHARS = 100_000
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

TOOLS = [
    {
        "name": "ag_critic_pack",
        "description": (
            "Build a read-only exam pack: exam, diff, changed files, one-hop imports, matching probe tails. "
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
            "Does not refuse finish. Unconfigured or void verdict is unavailable."
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
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []
    source = repo / rel
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


def pack(
    root: Path,
    *,
    exam: str | None = None,
    exam_file: str | None = None,
    base: str = "",
    head: str = "",
    tree: Path | None = None,
) -> dict[str, Any]:
    store = real_root(root)
    repo = real_root(Path(tree)) if tree is not None else store
    exam_text = _read_exam(exam, exam_file)
    diff_text, names = _changed_names(repo, str(base or "").strip(), str(head or "").strip())
    changed = [_file_entry(repo, rel) for rel in names]
    hops = neighbors(repo, changed)
    probe_run = (
        evaluate_probes(store, paths=names or None, awaken=False, tree=repo) if names else {"results": []}
    )
    results = probe_run.get("results") if isinstance(probe_run, dict) else []
    if not isinstance(results, list):
        results = []
    return {
        "schema": PACK_SCHEMA,
        "exam": exam_text,
        "diff": diff_text,
        "changed_files": changed,
        "neighbors": hops,
        "probes": results,
    }


def config_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / CONFIG_NAME


def report_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / REPORT_NAME


def log_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / LOG_NAME


def _truthy(raw: str) -> bool:
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def load_config(root: Path) -> dict[str, Any]:
    """Merge critic.json with AG_CRITIC_* env. Missing file is not an error."""
    cfg: dict[str, Any] = {
        "enabled": False,
        "endpoint": "",
        "model": "",
        "api_key_env": DEFAULT_API_KEY_ENV,
        "timeout": DEFAULT_TIMEOUT,
        "path": str(config_path(root)),
    }
    path = config_path(root)
    if path.is_file():
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
    return cfg


def _configured(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("enabled") and str(cfg.get("endpoint") or "").strip() and str(cfg.get("model") or "").strip())


def complete_chat(config: dict[str, Any], messages: list[dict[str, str]]) -> str:
    url = str(config["endpoint"]).rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(str(config.get("api_key_env") or DEFAULT_API_KEY_ENV), "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = json.dumps(
        {"model": config["model"], "messages": messages, "temperature": 0},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    timeout = int(config.get("timeout") or DEFAULT_TIMEOUT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"failed: {exc}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("failed: response has no message content") from exc
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("failed: empty message")
    return content


def parse_verdict(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.S)
    if fence:
        candidate = fence.group(1)
    elif not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("critic output is not JSON")
        candidate = candidate[start : end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"critic output is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("critic output must be a JSON object")
    return value


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
    elif raw in {"reject", "rejected"}:
        outcome = "reject"
    else:
        problems.append(f"verdict must be pass|reject, got {raw!r}")
        outcome = ""
    items = verdict.get("items")
    if not isinstance(items, list) or not items:
        problems.append("items must be a non-empty list")
        items = [] if not isinstance(items, list) else items
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


def _write_report(root: Path, blob: dict[str, Any]) -> str:
    path = report_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _trim_items(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "evidence": str(item.get("evidence") or ""),
                "comment": str(item.get("comment") or ""),
            }
        )
    return out


def append_log(
    root: Path,
    *,
    outcome: str,
    reason: str,
    configured: bool,
    prompt_version: str = PROMPT_VERSION,
    store: str = "",
    exam: str = "",
    pack: dict[str, Any] | None = None,
    items: Any = None,
    task_id: str = "",
    model: str = "",
    probe_red: list[str] | None = None,
) -> None:
    try:
        row: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outcome": outcome,
            "reason": reason,
            "configured": bool(configured),
            "prompt_version": prompt_version or PROMPT_VERSION,
            "store": store,
            "exam_sha256": _sha256_text(exam),
            "pack_sha256": _sha256_text(json.dumps(pack, ensure_ascii=False, sort_keys=True)) if pack is not None else "",
            "items": _trim_items(items),
        }
        if task_id:
            row["task_id"] = task_id
        if model:
            row["model"] = model
        if probe_red:
            row["probe_red"] = [str(item) for item in probe_red if str(item)]
        path = log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        return


def list_log(root: Path, limit: int = DEFAULT_LOG_LIMIT) -> dict[str, Any]:
    repo = real_root(root)
    path = log_path(repo)
    entries: list[dict[str, Any]] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                entries.append(row)
    cap = int(limit) if limit else DEFAULT_LOG_LIMIT
    if cap > 0:
        entries = entries[-cap:]
    return {"schema": LOG_SCHEMA, "root": str(repo), "entries": entries}


def _result(
    root: Path,
    *,
    outcome: str,
    reason: str,
    pack: dict[str, Any],
    items: list[Any] | None = None,
    summary: str = "",
    model: str | None = None,
    configured: bool = False,
    exam: str = "",
    task_id: str = "",
    probe_red: list[str] | None = None,
) -> dict[str, Any]:
    blob: dict[str, Any] = {
        "schema": RUN_SCHEMA,
        "outcome": outcome,
        "reason": reason,
        "items": list(items or []),
        "summary": summary,
        "prompt_version": PROMPT_VERSION,
        "pack": pack,
        "store": "",
        "configured": bool(configured),
    }
    if model:
        blob["model"] = model
    try:
        blob["store"] = _write_report(root, blob)
    except OSError:
        blob["store"] = ""
    append_log(
        root,
        outcome=outcome,
        reason=reason,
        configured=bool(configured),
        prompt_version=PROMPT_VERSION,
        store=str(blob.get("store") or ""),
        exam=exam,
        pack=pack,
        items=items,
        task_id=task_id,
        model=str(model or ""),
        probe_red=probe_red,
    )
    return blob


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
) -> dict[str, Any]:
    packed = pack(root, exam=exam, exam_file=exam_file, base=base, head=head, tree=tree)
    cfg = load_config(root)
    configured = bool(cfg.get("error") or _configured(cfg))
    extra = {
        "configured": configured,
        "exam": str(packed.get("exam") or ""),
        "task_id": task_id,
        "probe_red": probe_red,
    }
    if cfg.get("error"):
        return _result(root, outcome="unavailable", reason=str(cfg["error"]), pack=packed, **extra)
    if not _configured(cfg):
        return _result(root, outcome="unavailable", reason="not-configured", pack=packed, **extra)
    messages = [
        {"role": "system", "content": prompt_text()},
        {"role": "user", "content": json.dumps(packed, ensure_ascii=False)},
    ]
    try:
        raw = complete_chat(cfg, messages)
        verdict = parse_verdict(raw)
    except RuntimeError as exc:
        return _result(
            root,
            outcome="unavailable",
            reason=str(exc),
            pack=packed,
            model=str(cfg.get("model") or ""),
            **extra,
        )
    except ValueError as exc:
        return _result(
            root,
            outcome="unavailable",
            reason=f"void: {exc} (作废)",
            pack=packed,
            model=str(cfg.get("model") or ""),
            **extra,
        )
    problems = verdict_problems(verdict)
    items = verdict.get("items") if isinstance(verdict.get("items"), list) else []
    summary = str(verdict.get("summary") or "")
    model = str(cfg.get("model") or "")
    if problems:
        return _result(
            root,
            outcome="unavailable",
            reason="void: " + "; ".join(problems),
            pack=packed,
            items=items,
            summary=summary,
            model=model,
            **extra,
        )
    raw_verdict = str(verdict.get("verdict") or verdict.get("outcome") or "").strip().casefold()
    outcome = "passed" if raw_verdict in {"pass", "passed"} else "rejected"
    return _result(
        root,
        outcome=outcome,
        reason="",
        pack=packed,
        items=items,
        summary=summary,
        model=model,
        **extra,
    )


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

