from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .queue import ChainBroken, add_exists, add_hash, add_item, add_unknown, load_queue, run_queue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ag")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp", help="stdio MCP server")
    run = sub.add_parser("run", help="run the probe queue")
    run.add_argument("root")
    add = sub.add_parser("add", help="add a probe")
    add.add_argument("root")
    add.add_argument("--argv", nargs="+", required=True)
    add.add_argument("--expect-exit", type=int, default=0)
    add.add_argument("--red-argv", nargs="+", required=True)
    add.add_argument("--red-expect-exit", type=int, required=True)
    add.add_argument("--note", default="")
    ex = sub.add_parser("add-exists", help="add a high-trust exists fence")
    ex.add_argument("root")
    ex.add_argument("path")
    ex.add_argument("--note", default="")
    hx = sub.add_parser("add-hash", help="pin file bytes with sha256")
    hx.add_argument("root")
    hx.add_argument("path")
    hx.add_argument("--note", default="")
    unk = sub.add_parser("add-unknown", help="declare something that cannot be verified")
    unk.add_argument("root")
    unk.add_argument("note")
    manage = sub.add_parser("manage", help="register another project")
    manage.add_argument("root")
    manage.add_argument("--note", default="")
    sub.add_parser("projects", help="list managed projects")
    sub.add_parser("gui", help="open local GUI for others' probes")
    lst = sub.add_parser("list", help="print queue json")
    lst.add_argument("root")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "mcp":
            from .mcp import serve

            serve()
            return 0
        if args.cmd == "gui":
            from .gui import serve as serve_gui

            serve_gui()
            return 0
        if args.cmd == "manage":
            from .managed import add_project

            item = add_project(Path(args.root), note=args.note)
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "projects":
            from .managed import load_managed, project_snapshot

            blob = load_managed()
            rows = []
            for item in blob.get("projects") or []:
                if not isinstance(item, dict):
                    continue
                snap = project_snapshot(Path(str(item.get("root") or "")))
                rows.append(snap)
            print(json.dumps({"schema": "ag.projects.v1", "projects": rows}, ensure_ascii=False, indent=2))
            return 0
        root = Path(args.root)
        if args.cmd == "list":
            print(json.dumps(load_queue(root), ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "add":
            item = add_item(
                root,
                argv=list(args.argv),
                expect_exit=args.expect_exit,
                red_argv=list(args.red_argv),
                red_expect_exit=args.red_expect_exit,
                note=args.note,
            )
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "add-exists":
            item = add_exists(root, args.path, note=args.note)
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "add-hash":
            item = add_hash(root, args.path, note=args.note)
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "add-unknown":
            item = add_unknown(root, note=args.note)
            print(json.dumps(item, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "run":
            result = run_queue(root)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except ChainBroken as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
