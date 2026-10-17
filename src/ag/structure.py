"""结构体检：发现孤岛 / 假装配 / 反向引用。只出事实，不拦截。

语言规则全部来自用户填的适配器配置（<AG_HOME>/projects/<key>/adapter.json）。
内核不认识任何具体语言；抽不出引用的文件如实计入「未识别」，绝不谎报。
只读：永不写产品树；结果只许由调用方持久化到 plug_dir(root, "see", 16)。
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import deque
from pathlib import Path
from typing import Any

from .managed import ChainBroken, project_key, real_root
from .store import ag_home

ADAPTER_NAME = "adapter.json"


def _detect_languages(root: Path, adapters: dict[str, Any]) -> list[str]:
    """Return the languages whose source files actually exist in the repo.

    A language is only checked when the repo really uses it; absent languages are skipped.
    """
    repo = real_root(root)
    hits: list[str] = []
    for lang, cfg in adapters.items():
        if not isinstance(cfg, dict):
            continue
        exts = {str(e).lower() for e in (cfg.get("source_exts") or [])}
        if not exts:
            continue
        if _tracked_source_files(repo, sorted(exts)):
            hits.append(lang)
    return hits


def adapter_path(root: Path) -> Path:
    return ag_home() / "projects" / project_key(real_root(root)) / ADAPTER_NAME


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return (p.stdout or "").strip()


def load_adapter(root: Path) -> dict[str, Any]:
    """读适配器配置。返回 {ok, errors, config}。不存在 → ok=False, errors 说明未配置。

    单入口：优先读 config.json 的 structure 段；老项目只有 adapter.json 时回落兼容。"""
    from . import settings as _settings

    cfg = None
    sec = _settings.get_section(root, "structure")
    if sec:
        # multi-language table: {enabled, adapters: {lang: cfg}} -> hand back the table
        if isinstance(sec.get("adapters"), dict):
            adapters = {lang: c for lang, c in sec["adapters"].items() if isinstance(c, dict)}
            if not sec.get("enabled", True):
                return {"ok": True, "errors": [], "config": None, "configured": True, "multi": True, "adapters": {}, "languages": []}
            return {"ok": True, "errors": [], "config": None, "configured": True, "multi": True,
                    "adapters": adapters, "languages": _detect_languages(root, adapters)}
        cfg = sec
    else:
        path = adapter_path(root)
        if not path.is_file():
            return {"ok": False, "errors": ["未配置适配器"], "config": None, "configured": False}
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "errors": [f"适配器读不了或不是合法 JSON：{exc}"], "config": None, "configured": True}
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return {"ok": False, "errors": ["适配器必须是 JSON 对象"], "config": None, "configured": True}

    repo = real_root(root)
    entries = cfg.get("entry_files")
    if not isinstance(entries, list) or not entries:
        errors.append("entry_files 必须是非空数组（入口门文件，仓内相对路径）")
    else:
        for rel in entries:
            if not (repo / str(rel)).is_file():
                errors.append(f"入口文件不存在：{rel}")

    patterns = cfg.get("ref_patterns")
    if not isinstance(patterns, list) or not patterns:
        errors.append("ref_patterns 必须是非空数组（从源码文件抽出引用路径的正则）")
    else:
        for i, pat in enumerate(patterns):
            if not str(pat).strip():
                errors.append(f"ref_patterns[{i}] 是空正则")
                continue
            try:
                re.compile(str(pat))
            except re.error as exc:
                errors.append(f"ref_patterns[{i}] 编译失败：{exc}")

    manifest = cfg.get("dep_manifest")
    if manifest is not None:
        if not str(manifest).strip():
            errors.append("dep_manifest 若是字符串则不许为空（不需要依赖检测就删掉这个键）")
        elif not (repo / str(manifest)).is_file():
            errors.append(f"依赖清单不可读：{manifest}")
        dep_pattern = cfg.get("dep_pattern")
        if not str(dep_pattern or "").strip():
            errors.append("配了 dep_manifest 就必须给 dep_pattern（从清单里抽出依赖名的正则）")
        else:
            try:
                re.compile(str(dep_pattern))
            except re.error as exc:
                errors.append(f"dep_pattern 编译失败：{exc}")

    return {"ok": not errors, "errors": errors, "config": cfg, "configured": True}


def _tracked_source_files(root: Path, source_exts: list[str]) -> list[str]:
    names = _git(root, "ls-files").splitlines()
    exts = {e.lower() for e in source_exts}
    out = []
    for rel in names:
        rel = rel.strip()
        if not rel:
            continue
        if Path(rel).suffix.lower() in exts:
            out.append(rel.replace("\\", "/"))
    return out


def _extract_refs(root: Path, rel: str, compiled: list[re.Pattern[str]]) -> tuple[list[str], bool]:
    """从一个文件抽引用。返回 (仓内相对路径列表, 是否认出至少一条)。"""
    path = root / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], False
    refs: list[str] = []
    for cre in compiled:
        for m in cre.finditer(text):
            cand = next((g for g in m.groups() if g), None) or m.group(0)
            cand = str(cand).strip().strip('\'"')
            if not cand:
                continue
            refs.append(cand)
    return refs, bool(refs)


def _resolve_ref(root: Path, from_rel: str, cand: str, known: set[str]) -> str | None:
    """把抽到的引用解析成仓内相对路径。只接受仓内真实存在的文件。"""
    # 相对 import（.loop / ..loop）：相对当前文件解析
    if cand.startswith("."):
        dots = len(cand) - len(cand.lstrip("."))
        mod = cand.lstrip(".").replace(".", "/")
        base_dir = str(Path(from_rel).parent).replace("\\", "/")
        # Python 相对 import：1 点=当前目录，2 点=上一级，依此类推
        for _ in range(dots - 1):
            base_dir = str(Path(base_dir).parent).replace("\\", "/")
        cand = (base_dir + "/" + mod).strip("/")
        # 已是完整仓内路径，补后缀后直接返回，不再拼 base
        for ext in (".py",):
            if cand + ext in known:
                return cand + ext
            if (cand + "/__init__.py") in known:
                return cand + "/__init__.py"
        return None
    # 点分模块名（ag.loop / com.foo.Bar）：转成路径再找，可能带包前缀目录
    elif "." in cand and "/" not in cand:
        dotted = cand.replace(".", "/")
        for pre in ("", "src/"):
            for ext in (".py", ".java", ".kt"):
                for form in (pre + dotted + ext, pre + dotted + "/__init__.py", pre + dotted + "/index" + ext):
                    if form in known:
                        return form
    cand = cand.replace("\\", "/").lstrip("./")
    if cand in known:
        return cand
    base = str(Path(from_rel).parent).replace("\\", "/")
    joined = (base + "/" + cand).replace("\\", "/")
    # 规整 a/b/../c
    parts: list[str] = []
    for seg in joined.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    norm = "/".join(parts)
    if norm in known:
        return norm
    # 尝试补后缀（import './x' → x.ts）
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs"):
        if norm + ext in known:
            return norm + ext
        if (norm + "/index" + ext) in known:
            return norm + "/index" + ext
    return None


def _depth(rel: str) -> int:
    return rel.count("/")


def check(root: Path) -> dict[str, Any]:
    """跑一次结构体检。返回只读事实字典；不拦截、不写产品树。

    多语言：structure.adapters 表存在时，对仓里实际存在的每种语言各跑一遍再合并；
    单语言（老单适配器或只命中一种语言）行为与升级前完全一致。"""
    root = real_root(root)
    adapter = load_adapter(root)
    if not adapter["configured"]:
        return {"configured": False, "detail": "未配置适配器", "errors": adapter["errors"]}
    if not adapter["ok"]:
        return {"configured": True, "ok": False, "errors": adapter["errors"], "detail": "适配器配置不合法"}

    # multi-language table: run each detected language with its own adapter, then merge
    if adapter.get("multi"):
        languages = adapter.get("languages") or []
        if not languages:
            return {"configured": True, "ok": True, "multi": True, "languages": [], "detail": "仓里未检测到受支持语言的源文件"}
        per_lang: dict[str, Any] = {}
        all_islands: list[str] = []
        all_phantom: set[str] = set()
        all_reverse: list[dict[str, str]] = []
        tracked_total = 0
        reachable_total = 0
        unrec_total = 0
        for lang in languages:
            cfg = adapter["adapters"][lang]
            r = _check_with_cfg(root, cfg)
            r["language"] = lang
            per_lang[lang] = r
            tracked_total += r.get("tracked_source_files", 0)
            reachable_total += r.get("reachable", 0)
            unrec_total += r.get("unrecognized_files", 0)
            all_islands.extend(r.get("islands") or [])
            all_phantom.update(r.get("phantom_deps") or [])
            all_reverse.extend(r.get("reverse_edges") or [])
        result = {
            "configured": True,
            "ok": True,
            "multi": True,
            "languages": languages,
            "per_language": per_lang,
            "tracked_source_files": tracked_total,
            "reachable": reachable_total,
            "unrecognized_files": unrec_total,
            "islands": sorted(set(all_islands)),
            "island_count": len(set(all_islands)),
            "phantom_deps": sorted(all_phantom),
            "phantom_dep_count": len(all_phantom),
            "reverse_edges": all_reverse,
            "reverse_edge_count": len(all_reverse),
        }
        result["detail"] = (
            f"语言 {len(languages)}({", ".join(languages)}) · "
            f"可达 {reachable_total}/{tracked_total} · 孤岛 {len(set(all_islands))} · "
            f"假装配 {len(all_phantom)} · 反向引用 {len(all_reverse)}"
        )
        return result

    # single-language legacy path: unchanged behavior
    return _check_with_cfg(root, adapter["config"])


def _check_with_cfg(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Run the single-language checkup with one adapter config. Read-only."""
    source_exts = [str(e) for e in (cfg.get("source_exts") or [".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"])]
    compiled = [re.compile(str(p)) for p in cfg["ref_patterns"]]

    tracked = _tracked_source_files(root, source_exts)
    known = set(tracked)
    entries = [str(e).replace("\\", "/") for e in cfg["entry_files"]]

    # 引用图
    edges: dict[str, set[str]] = {rel: set() for rel in tracked}
    unrecognized = 0
    for rel in tracked:
        refs, any_ref = _extract_refs(root, rel, compiled)
        if not any_ref:
            unrecognized += 1
        for cand in refs:
            tgt = _resolve_ref(root, rel, cand, known)
            if tgt and tgt != rel:
                edges[rel].add(tgt)

    # 可达性 BFS
    reachable: set[str] = set()
    dq: deque[str] = deque()
    for e in entries:
        if e in known and e not in reachable:
            reachable.add(e)
            dq.append(e)
    while dq:
        cur = dq.popleft()
        for nxt in edges.get(cur, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                dq.append(nxt)

    islands = sorted(rel for rel in tracked if rel not in reachable)

    # 假装配：只被孤岛引用的依赖不算真用（孤岛不进产物，连带它的依赖也是假装配）
    phantom_deps: list[str] = []
    manifest = cfg.get("dep_manifest")
    if manifest:
        mpath = root / str(manifest)
        try:
            mtext = mpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            mtext = ""
        # 可选 dep_section：只扫清单里某个段落（如 dependencies，跳过 devDependencies）
        section = str(cfg.get("dep_section") or "").strip()
        if section:
            sec_re = re.compile(r'"?' + re.escape(section) + r'"?\s*:\s*\{([^}]*)\}', re.DOTALL)
            sm = sec_re.search(mtext)
            scan_text = sm.group(1) if sm else ""
        else:
            scan_text = mtext
        dep_cre = re.compile(str(cfg.get("dep_pattern") or ""), re.MULTILINE)
        # 只收集「可达文件」引用文本里的包名（含 @scope/name 全名）；孤岛的引用不算
        used_dep_names: set[str] = set()
        for rel in reachable:
            refs, _ = _extract_refs(root, rel, compiled)
            for cand in refs:
                cand_norm = cand.replace("\\", "/").lstrip("./")
                used_dep_names.add(cand_norm)                 # 全名 @flowgram.ai/free-layout-editor
                used_dep_names.add(cand_norm.split("/")[-1])  # 短名 free-layout-editor
        for m in dep_cre.finditer(scan_text):
            name = next((g for g in m.groups() if g), None) or m.group(0)
            name = str(name).strip().strip("\'\"")
            if not name or name == "version":
                continue
            short = name.split("/")[-1]
            if name not in used_dep_names and short not in used_dep_names:
                phantom_deps.append(name)

    # 反向引用：深度更大 → 引用了深度更小
    reverse_edges: list[dict[str, str]] = []
    for src, tgts in edges.items():
        for t in tgts:
            if _depth(src) > _depth(t):
                reverse_edges.append({"from": src, "to": t})

    result = {
        "configured": True,
        "ok": True,
        "doors": entries,
        "tracked_source_files": len(tracked),
        "reachable": len(reachable),
        "unrecognized_files": unrecognized,
        "islands": islands,
        "island_count": len(islands),
        "phantom_deps": sorted(set(phantom_deps)),
        "phantom_dep_count": len(set(phantom_deps)),
        "reverse_edges": reverse_edges,
        "reverse_edge_count": len(reverse_edges),
    }
    result["detail"] = (
        f"门 {len(entries)} · 可达 {len(reachable)}/{len(tracked)} · "
        f"孤岛 {len(islands)} · 假装配 {len(set(phantom_deps))} · "
        f"反向引用 {len(reverse_edges)} · 未识别 {unrecognized}"
    )
    return result
