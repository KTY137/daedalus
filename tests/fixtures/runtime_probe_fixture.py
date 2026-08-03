#!/usr/bin/env python3
"""Deterministic provider-neutral runtime fixture used only by tests."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def emit_protocol() -> int:
    _emit({"event": "start", "protocol": "daedalus-runtime-fixture/1"})
    _emit({"event": "delta", "text": "hel"})
    _emit({"event": "delta", "text": "lo"})
    _emit(
        {
            "event": "tool",
            "name": "read_file",
            "arguments": {"path": "fixture.txt"},
            "result": {"sha256": "a" * 64},
        }
    )
    _emit(
        {
            "event": "final",
            "value": {
                "status": "done",
                "summary": "fixture complete",
                "files_changed": [],
            },
        }
    )
    _emit(
        {
            "event": "usage",
            "input_tokens": 11,
            "output_tokens": 7,
            "cost_microusd": 0,
        }
    )
    return 0


def bounded_write(workspace: str, target: str) -> int:
    root = Path(workspace).resolve()
    destination = Path(target).resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        _emit({"event": "refused", "reason": "target-outside-workspace"})
        return 23
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("fixture-output\n", encoding="utf-8")
    _emit(
        {
            "event": "written",
            "relative_path": destination.relative_to(root).as_posix(),
        }
    )
    return 0


def spawn_child() -> int:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _emit({"event": "child-started", "pid": child.pid})
    time.sleep(60)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("emit")
    sleeper = sub.add_parser("sleep")
    sleeper.add_argument("--seconds", type=float, default=60)
    writer = sub.add_parser("write")
    writer.add_argument("--workspace", required=True)
    writer.add_argument("--target", required=True)
    sub.add_parser("spawn-child")
    args = parser.parse_args(argv)
    if args.command == "emit":
        return emit_protocol()
    if args.command == "sleep":
        time.sleep(args.seconds)
        return 0
    if args.command == "write":
        return bounded_write(args.workspace, args.target)
    if args.command == "spawn-child":
        return spawn_child()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
