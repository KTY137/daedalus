"""Read-only PCB inspection CLI: ``python -m daedalus.pcb_design``.

Four subcommands, all effect-free:

``status``  which PCB toolchains this host has, without probing any of them.
``scan``    find KiCad projects under a directory and bind byte identities.
``inspect`` parse one board or schematic and report what it contains.
``plan``    describe the later effectful packet, and why it cannot run.

Exit codes (``2`` stays argparse's own usage error):

``0``  the command produced its answer.
``1``  the answer is incomplete: an unsupported format was force-parsed, a scan
       hit its file bound, or a plan is inadmissible.
``3``  a typed refusal: malformed input, an oversized file, an unsupported
       suffix or an unexpected root. The refusal is printed as JSON.

``plan`` returns ``1`` on every host, on purpose. This package has no effect
path, so no plan it produces is admissible; a zero would be a lie.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Sequence

from .inspection import canonical_json, inspect_artifact
from .plan import build_plan
from .sexpr import ABSOLUTE_MAX_BYTES, DEFAULT_MAX_BYTES, PcbRefusal
from .sources import DEFAULT_MAX_FILES, DEFAULT_MAX_HASH_BYTES, discover_projects
from .toolchains import all_tool_status

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2
EXIT_REFUSED = 3


def _print(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(canonical_json(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _print_refusal(refusal: PcbRefusal, *, as_json: bool) -> int:
    _print(refusal.to_dict(), as_json=as_json)
    return EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daedalus-pcb",
        description=(
            "Read-only KiCad inspection. Isolated EXPERIMENT (packet G1-HW-01): "
            "no product wiring, no tool execution, no promotion."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser(
        "status", help="report registered PCB toolchains without probing them"
    )
    status.add_argument("--json", action="store_true", help="canonical single-line JSON")

    scan = sub.add_parser("scan", help="find KiCad projects and bind byte identities")
    scan.add_argument("root", nargs="?", default=".")
    scan.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    scan.add_argument("--max-hash-bytes", type=int, default=DEFAULT_MAX_HASH_BYTES)
    scan.add_argument("--json", action="store_true", help="canonical single-line JSON")

    inspect = sub.add_parser(
        "inspect", help="parse one .kicad_pcb or .kicad_sch and report its contents"
    )
    inspect.add_argument("artifact")
    inspect.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help=f"refuse inputs larger than this (absolute ceiling {ABSOLUTE_MAX_BYTES})",
    )
    inspect.add_argument(
        "--allow-unknown-version",
        action="store_true",
        help="parse an unsupported format version anyway and report it as incomplete",
    )
    inspect.add_argument("--json", action="store_true", help="canonical single-line JSON")

    plan = sub.add_parser(
        "plan", help="describe the later effectful packet; never runs anything"
    )
    plan.add_argument(
        "--step",
        dest="steps",
        action="append",
        default=[],
        help="restrict the plan to these step ids (repeatable)",
    )
    plan.add_argument("--json", action="store_true", help="canonical single-line JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        rows = all_tool_status()
        if args.json:
            _print(rows, as_json=True)
        else:
            for row in rows:
                state = "PRESENT" if row["available"] else "ABSENT "
                detail = str(row["command_path"] or row["last_error"])
                series = row.get("install_series") or ""
                suffix = f"  [install series {series}, not a probed version]" if series else ""
                print(f"{state} {str(row['id']):<10} {row['label']}: {detail}{suffix}")
        return EXIT_OK

    if args.command == "scan":
        try:
            payload = discover_projects(
                args.root,
                max_files=args.max_files,
                max_hash_bytes=args.max_hash_bytes,
            )
        except ValueError as exc:
            parser.error(str(exc))
        _print(payload, as_json=args.json)
        return EXIT_INCOMPLETE if payload["truncated"] else EXIT_OK

    if args.command == "inspect":
        try:
            report = inspect_artifact(
                args.artifact,
                max_bytes=args.max_bytes,
                allow_unknown_version=args.allow_unknown_version,
            )
        except PcbRefusal as refusal:
            return _print_refusal(refusal, as_json=args.json)
        _print(report, as_json=args.json)
        return EXIT_OK if report["complete"] else EXIT_INCOMPLETE

    if args.command == "plan":
        payload = build_plan(step_ids=tuple(args.steps))
        _print(payload, as_json=args.json)
        return EXIT_OK if payload["admissible"] else EXIT_INCOMPLETE

    parser.error(f"unhandled command {args.command!r}")
    return EXIT_USAGE
