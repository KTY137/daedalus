# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""CLI for Daedalus chip-design support.

Installed entry point: ``daedalus-chip``.
It is also available as ``python -m daedalus.chip_design``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .executor import execute_argv
from .sources import classify_source, discover_sources
from .toolchains import all_tool_status, build_rtl_lint_argv, build_tcl_argv


def _print_result(result, *, as_json: bool) -> int:
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"{payload['status'].upper()}  {payload['duration_s']}s")
        print("argv:", " ".join(payload["argv"]))
        if payload["stdout"]:
            print(payload["stdout"])
        if payload["stderr"]:
            print(payload["stderr"])
    return 0 if result.status in {"ok", "planned"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daedalus-chip",
        description="RTL/EDA/Tcl support for Daedalus (dry-run by default).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="probe known EDA tools")
    status.add_argument("--timeout", type=float, default=5.0)
    status.add_argument("--json", action="store_true")

    scan = sub.add_parser("scan", help="classify RTL, constraints and EDA scripts")
    scan.add_argument("root", nargs="?", default=".")
    scan.add_argument("--max-files", type=int, default=20_000)
    scan.add_argument("--json", action="store_true")

    classify = sub.add_parser("classify", help="classify explicit paths by extension")
    classify.add_argument("paths", nargs="+")
    classify.add_argument("--json", action="store_true")

    tcl = sub.add_parser("tcl", help="plan or run a Tcl script through a registered EDA backend")
    tcl.add_argument("tool", choices=("tclsh", "vivado", "quartus", "yosys", "openroad"))
    tcl.add_argument("script")
    tcl.add_argument("--arg", dest="script_args", action="append", default=[],
                     help="argument passed to the Tcl script (repeatable)")
    tcl.add_argument("--repo-root", default=".")
    tcl.add_argument("--timeout", type=float, default=3600.0)
    tcl.add_argument("--live", action="store_true", help="actually start the external EDA tool")
    tcl.add_argument("--json", action="store_true")

    lint = sub.add_parser("lint", help="plan or run Verilog/SystemVerilog lint")
    lint.add_argument("sources", nargs="+")
    lint.add_argument("--tool", choices=("verilator", "verible"), default="verilator")
    lint.add_argument("--repo-root", default=".")
    lint.add_argument("--top")
    lint.add_argument("-I", "--include", action="append", default=[])
    lint.add_argument("-D", "--define", action="append", default=[])
    lint.add_argument("--timeout", type=float, default=300.0)
    lint.add_argument("--live", action="store_true", help="actually start the linter")
    lint.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        rows = all_tool_status(timeout_s=args.timeout)
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            for row in rows:
                state = "READY" if row["available"] else "MISSING"
                detail = row.get("version") or row.get("last_error") or ""
                detail = str(detail).splitlines()[0] if detail else ""
                print(f"{state:<7} {row['id']:<10} {row['label']}: {detail}")
        return 0

    if args.command == "scan":
        try:
            rows = [s.to_dict() for s in discover_sources(args.root, max_files=args.max_files)]
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row['kind']:<13} {row['language']:<13} {row['path']}")
        return 0

    if args.command == "classify":
        rows = []
        for path in args.paths:
            spec = classify_source(path)
            rows.append(spec.to_dict() if spec else {"path": path, "kind": "unknown"})
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row.get('kind', 'unknown'):<13} {row.get('language', ''):<13} {row['path']}")
        return 0

    if args.command == "tcl":
        root = Path(args.repo_root).resolve()
        script_args = list(args.script_args)
        try:
            argv2 = build_tcl_argv(args.tool, args.script, repo_root=root, script_args=script_args)
            result = execute_argv(argv2, cwd=root, timeout_s=args.timeout, dry_run=not args.live)
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))
        return _print_result(result, as_json=args.json)

    if args.command == "lint":
        root = Path(args.repo_root).resolve()
        try:
            argv2 = build_rtl_lint_argv(
                args.tool, args.sources, repo_root=root, top=args.top,
                include_dirs=args.include, defines=args.define,
            )
            result = execute_argv(argv2, cwd=root, timeout_s=args.timeout, dry_run=not args.live)
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))
        return _print_result(result, as_json=args.json)

    parser.error(f"unknown command: {args.command}")
    return 2
