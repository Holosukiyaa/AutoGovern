from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .loop import abandon, enroll, finish, hook_main, start, status, unenroll, verify
from .gui import write_dashboard
from .see import usage
from .managed import ChainBroken


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ag")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp", help="stdio MCP server — main entry")
    enroll_p = sub.add_parser("enroll", help="register a git checkout and install the hook")
    enroll_p.add_argument("root")
    enroll_p.add_argument("--test", nargs=argparse.REMAINDER, dest="test_argv")
    enroll_p.add_argument("--note", default="")
    sub.add_parser("status", help="hook / dirty / process vs product").add_argument("root")
    start_p = sub.add_parser("start", help="open a worktree")
    start_p.add_argument("root")
    start_p.add_argument("--portrait", default="")
    sub.add_parser("verify", help="run enrolled tests and pin the tree").add_argument("root")
    sub.add_parser("finish", help="ff-only if digest matches").add_argument("root")
    sub.add_parser("abandon", help="drop the open worktree").add_argument("root")
    sub.add_parser("unenroll", help="remove the hook and restore previous hooksPath").add_argument("root")
    sub.add_parser("usage", help="see lane: help/block counts per ship item").add_argument("root")
    gui_p = sub.add_parser("gui", help="write a read-only HTML dashboard and open it")
    gui_p.add_argument("root", nargs="?")
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
            path = write_dashboard(Path(args.root) if args.root else None, browse=True)
            print(str(path))
            return 0
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
    except ChainBroken as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
