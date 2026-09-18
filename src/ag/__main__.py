from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .loop import abandon, enroll, finish, hook_main, start, status, unenroll, verify
from .gui import write_dashboard
from .heal import run as heal_run
from .lift import run as lift_run
from .see import run as see_run
from .see import usage
from .catalog import plug, plug_list
from .managed import ChainBroken


def _probe_main(args: argparse.Namespace) -> int:
    from .probe import insert, list_probes, run

    root = Path(args.root)
    if args.probe_cmd == "insert":
        print(
            json.dumps(
                insert(
                    root,
                    observation=args.observation,
                    exam_fragment=args.exam_fragment,
                    evidence=args.evidence,
                    area=args.area,
                    id=args.id,
                    ttl_quiet_loops=args.ttl_quiet_loops,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.probe_cmd == "run":
        print(
            json.dumps(
                run(root, paths=args.path, awaken=bool(args.awaken)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.probe_cmd == "list":
        print(json.dumps(list_probes(root, full=bool(args.full)), ensure_ascii=False, indent=2))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ag")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp", help="stdio MCP server — main entry")
    enroll_p = sub.add_parser("enroll", help="register a git checkout and install the hook")
    enroll_p.add_argument("root")
    enroll_p.add_argument("--test", nargs=argparse.REMAINDER, dest="test_argv")
    enroll_p.add_argument("--note", default="")
    sub.add_parser("status", help="hook / dirty / process vs product").add_argument("root")
    start_p = sub.add_parser(
        "start",
        help="open a worktree; tracked canonical files are read-only until finish or abandon",
    )
    start_p.add_argument("root")
    start_p.add_argument("--portrait", default="")
    sub.add_parser("verify", help="run enrolled tests and pin the tree").add_argument("root")
    sub.add_parser("finish", help="ff-only if digest matches").add_argument("root")
    sub.add_parser("abandon", help="drop the open worktree").add_argument("root")
    sub.add_parser("unenroll", help="remove the hook and restore previous hooksPath").add_argument("root")
    sub.add_parser("usage", help="see lane: help/block counts per ship item").add_argument("root")
    sub.add_parser("lift", help="lift advice; does not refuse finish").add_argument("root")
    sub.add_parser("heal", help="heal findings; does not refuse finish").add_argument("root")
    sub.add_parser("see", help="see snapshot; does not refuse finish").add_argument("root")
    gui_p = sub.add_parser("gui", help="open HTML table of critic sqlite rows")
    gui_p.add_argument("root")
    plug_p = sub.add_parser("plug", help="list/on/off a pluggable strategy by lane-seq")
    plug_p.add_argument("action", choices=["list", "on", "off"])
    plug_p.add_argument("root")
    plug_p.add_argument("code", nargs="?")
    probe_p = sub.add_parser("probe", help="out-of-tree observation probes (see lane)")
    probe_sub = probe_p.add_subparsers(dest="probe_cmd", required=True)
    insert_p = probe_sub.add_parser(
        "insert",
        help="insert a probe; duplicate id is refused and the store is left unchanged",
    )
    insert_p.add_argument("root")
    insert_p.add_argument(
        "--observation",
        required=True,
        help="JSON object; kind=command (argv, expect_exit, optional stdout_contains/stderr_contains) or kind=text_in_file (path, must_include and/or must_exclude)",
    )
    insert_p.add_argument("--exam-fragment", required=True, help="the exam sentence this probe pins")
    insert_p.add_argument(
        "--evidence",
        required=True,
        help="already-seen observation text, at least 20 characters; missing or short evidence refuses and writes nothing",
    )
    insert_p.add_argument("--area", action="append", required=True, help="repository-relative path; repeatable")
    insert_p.add_argument("--id", help="optional id; omitted id is content-addressed; duplicate id is refused")
    insert_p.add_argument("--ttl-quiet-loops", type=int, default=10)
    run_p = probe_sub.add_parser("run", help="run armed probes; no LLM; archived stay cold unless --awaken and --path hits")
    run_p.add_argument("root")
    run_p.add_argument("--path", action="append", help="only run probes whose area hits these paths")
    run_p.add_argument("--awaken", action="store_true", help="also run archived probes whose area hits --path")
    list_p = probe_sub.add_parser(
        "list",
        help="list armed and archived probes; default hides observation and evidence",
    )
    list_p.add_argument("root")
    list_p.add_argument(
        "--full",
        action="store_true",
        help="include observation and evidence; for a person or critic, not a worker channel",
    )
    pack_p = sub.add_parser("critic-pack", help="read-only exam pack JSON; not a worker ticket")
    pack_p.add_argument("root")
    pack_exam = pack_p.add_mutually_exclusive_group(required=True)
    pack_exam.add_argument("--exam", help="exam text (user words + portrait)")
    pack_exam.add_argument("--exam-file", help="path to exam text")
    pack_p.add_argument("--base", default="", help="diff base ref; default is working tree vs HEAD")
    pack_p.add_argument("--head", default="", help="diff head ref; requires --base")
    run_c = sub.add_parser(
        "critic-run",
        help="one read-only critic chat; does not refuse finish",
        description=(
            "One read-only critic chat; does not refuse finish. "
            "Config file: AG_HOME/projects/<key>/critic.json "
            "(enabled, endpoint, model, api_key_env, timeout, worker_model, allow_same_family). "
            "Env overrides: AG_CRITIC_ENABLED, AG_CRITIC_ENDPOINT, AG_CRITIC_MODEL, "
            "AG_CRITIC_API_KEY_ENV, AG_CRITIC_TIMEOUT, AG_CRITIC_WORKER_MODEL, "
            "AG_CRITIC_ALLOW_SAME_FAMILY. "
            "Missing file is not-configured. Report: AG_HOME/projects/<key>/critic-last.json"
        ),
    )
    run_c.add_argument("root")
    run_exam = run_c.add_mutually_exclusive_group(required=True)
    run_exam.add_argument("--exam", help="exam text (user words + portrait)")
    run_exam.add_argument("--exam-file", help="path to exam text")
    run_c.add_argument("--base", default="", help="diff base ref; default is working tree vs HEAD")
    run_c.add_argument("--head", default="", help="diff head ref; requires --base")
    log_c = sub.add_parser(
        "critic-log",
        help="read-only critic audit log; newest last",
        description="Read-only. Newest last. Default --limit 20. SQLite AG_HOME/projects/<key>/ag.sqlite plus jsonl backup.",
    )
    log_c.add_argument("root")
    log_c.add_argument("--limit", type=int, default=20, help="newest last; default 20")
    sub.add_parser("critic-prompt", help="print the read-only critic startup prompt")
    sub.add_parser("hook", help="git pre-commit helper")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "mcp":
            from .mcp import serve

            serve()
            return 0
        if args.cmd == "hook":
            return hook_main()
        if args.cmd == "gui":
            path = write_dashboard(Path(args.root), browse=True)
            print(str(path))
            return 0
        if args.cmd == "plug":
            root = Path(args.root)
            if args.action == "list":
                print(json.dumps(plug_list(root), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(plug(root, str(args.code or ""), on=args.action == "on"), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "critic-prompt":
            from .critic import prompt_text

            text = prompt_text()
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
            return 0
        if args.cmd == "critic-pack":
            from .critic import pack

            print(
                json.dumps(
                    pack(
                        Path(args.root),
                        exam=args.exam,
                        exam_file=args.exam_file,
                        base=args.base,
                        head=args.head,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.cmd == "critic-run":
            from .critic import critic_run

            print(
                json.dumps(
                    critic_run(
                        Path(args.root),
                        exam=args.exam,
                        exam_file=args.exam_file,
                        base=args.base,
                        head=args.head,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.cmd == "critic-log":
            from .critic import list_log

            print(json.dumps(list_log(Path(args.root), limit=args.limit), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "probe":
            return _probe_main(args)
        root = Path(args.root)
        if args.cmd == "enroll":
            print(json.dumps(enroll(root, test_argv=args.test_argv, note=args.note), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "status":
            print(json.dumps(status(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "start":
            print(json.dumps(start(root, portrait=args.portrait), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "verify":
            result = verify(root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("verified_tree") else 1
        if args.cmd == "finish":
            print(json.dumps(finish(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "abandon":
            print(json.dumps(abandon(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "unenroll":
            print(json.dumps(unenroll(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "usage":
            print(json.dumps(usage(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "lift":
            print(json.dumps(lift_run(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "heal":
            print(json.dumps(heal_run(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "see":
            print(json.dumps(see_run(root), ensure_ascii=False, indent=2))
            return 0
    except ChainBroken as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
