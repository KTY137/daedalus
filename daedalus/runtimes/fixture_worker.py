"""Deterministic subprocess used by the vendor-neutral runtime conformance suite.

This module is a test fixture, not a model runtime. It exercises the same
start/stream/tool/structured-output/timeout/cancellation/workspace/cost surface
that real runtime adapters must expose without network access or paid calls.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any


_CANCELLED = False


def _cancel(_signum: int, _frame: Any) -> None:
    global _CANCELLED
    _CANCELLED = True


def _emit(kind: str, sequence: int, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"kind": kind, "sequence": sequence, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=("normal", "hang"), required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--outside-canary", required=True)
    parser.add_argument("--escape", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace).resolve(strict=True)
    canary = Path(args.outside_canary).resolve(strict=True)
    if not workspace.is_dir():
        raise RuntimeError("fixture workspace must be a directory")
    if workspace in canary.parents or canary in workspace.parents:
        raise RuntimeError("outside canary must be outside the fixture workspace")

    signal.signal(signal.SIGTERM, _cancel)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _cancel)

    _emit("started", 0, {"pid": os.getpid()})
    if args.mode == "hang":
        while not _CANCELLED:
            time.sleep(0.02)
        _emit("cancelled", 1, {"reason": "external-cancel"})
        return 130

    _emit("stream.delta", 1, {"text": "fixture"})
    _emit("tool.started", 2, {"tool": "fixture.write", "call_id": "call-1"})
    (workspace / "fixture-output.txt").write_text("fixture\n", encoding="utf-8")
    if args.escape:
        canary.write_text("modified\n", encoding="utf-8")
    _emit(
        "tool.finished",
        3,
        {"tool": "fixture.write", "call_id": "call-1", "status": "ok"},
    )
    _emit(
        "structured-output",
        4,
        {"value": {"ok": True, "value": "fixture"}},
    )
    _emit(
        "usage",
        5,
        {
            "input_tokens": 3,
            "output_tokens": 2,
            "cost_microusd": 0,
            "wall_time_ms": 1,
        },
    )
    _emit("finished", 6, {"status": "passed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
