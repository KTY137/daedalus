#!/usr/bin/env python3
"""Linux-only process-tree fixture for host fault injection.

The parent and child intentionally remain in the same new session/process group
created by the caller. ``--ignore-sigterm`` installs the same SIGTERM behavior
in both processes so the collector must escalate to SIGKILL. The parent does
not publish readiness until the child confirms that its signal policy is active.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time

_SCHEMA = "daedalus-linux-process-tree-fixture/1"
_SLEEP_SECONDS = 60
_MAX_CHILD_READY_BYTES = 1024


def _sleep_forever() -> None:
    time.sleep(_SLEEP_SECONDS)


def _child(*, ignore_sigterm: bool) -> int:
    if ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    payload = {
        "schema": _SCHEMA,
        "child_pid": os.getpid(),
        "ignore_sigterm": ignore_sigterm,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)
    _sleep_forever()
    return 0


def _parent(*, ignore_sigterm: bool) -> int:
    if ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    command = [sys.executable, __file__, "--child"]
    if ignore_sigterm:
        command.append("--ignore-sigterm")
    child = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        close_fds=True,
    )
    if child.stdout is None:
        raise RuntimeError("child readiness pipe is unavailable")
    line = child.stdout.readline()
    if not line or len(line.encode("utf-8")) > _MAX_CHILD_READY_BYTES:
        raise RuntimeError("child readiness record is unavailable")
    child_ready = json.loads(line)
    expected = {"schema", "child_pid", "ignore_sigterm"}
    if not isinstance(child_ready, dict) or set(child_ready) != expected:
        raise RuntimeError("child readiness record fields are invalid")
    if child_ready["schema"] != _SCHEMA:
        raise RuntimeError("child readiness schema mismatch")
    if type(child_ready["child_pid"]) is not int or child_ready["child_pid"] != child.pid:
        raise RuntimeError("child readiness PID mismatch")
    if type(child_ready["ignore_sigterm"]) is not bool:
        raise RuntimeError("child readiness signal policy is invalid")
    if child_ready["ignore_sigterm"] is not ignore_sigterm:
        raise RuntimeError("child readiness signal policy mismatch")
    payload = {
        "schema": _SCHEMA,
        "parent_pid": os.getpid(),
        "process_group_id": os.getpgrp(),
        "child_pids": [child.pid],
        "ignore_sigterm": ignore_sigterm,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)
    _sleep_forever()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--ignore-sigterm", action="store_true")
    args = parser.parse_args(argv)
    if args.child:
        return _child(ignore_sigterm=args.ignore_sigterm)
    return _parent(ignore_sigterm=args.ignore_sigterm)


if __name__ == "__main__":
    raise SystemExit(main())
