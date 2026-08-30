# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""`python -m daedalus.loop` is a console door, and it must open like one.

The codex round-2 security seat named the exact opening: ``daedalus/loop.py``
ends with ``if __name__ == "__main__": raise SystemExit(main())``, which is
reachable directly and never passes through ``daedalus.cli:main``'s dispatch --
the place where every other console entrypoint installs the process-wide spend
guard.  ``loop.main`` did install it by hand, which is the right effect and the
wrong evidence: nothing mechanically required the line to still be there, so
deleting it would have left the single entrypoint that spends the most per
invocation running unpriced, silently.

The instrument here is ``sys.addaudithook``, not a mock.  A mock proves that a
particular call was made; the audit hook proves an ORDER over every write,
spawn and connect the interpreter performs, whichever module performs them.
It runs in a child process because an audit hook cannot be removed once added.

NOTE: adding a ``daedalus loop`` subcommand to ``cli.py`` would NOT have closed
this door -- the module tail stays reachable either way -- which is why the
boundary belongs inside ``main()``, where every caller passes it.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Effect, Wiring

ROOT = Path(__file__).resolve().parents[1]
MARKER = "AUDIT-TRACE:"

# Runs in a child interpreter. Wraps the two guard calls with audit events of
# their own so their position is comparable with the real effect events, then
# drives loop.main down a path that returns before doing any work: a
# non-positive bound is refused by LoopBounds AFTER the guard and boundary and
# BEFORE the driver exists.
CHILD = f'''
import json, os, sys

events = []

import daedalus.budget as budget
import daedalus.spine.effect_boundary as boundary

_real_guard = budget.install_process_guard
_real_begin = boundary.begin_effect


def _traced_guard():
    sys.audit("daedalus.trace.guard_installed")
    return _real_guard()


def _traced_begin(*args, **kwargs):
    receipt = _real_begin(*args, **kwargs)
    sys.audit("daedalus.trace.effect_started", str(args[0]))
    return receipt


budget.install_process_guard = _traced_guard
boundary.begin_effect = _traced_begin


def hook(event, args):
    if event == "daedalus.trace.guard_installed":
        events.append(["guard", ""])
    elif event == "daedalus.trace.effect_started":
        events.append(["boundary", str(args[0])])
    elif event in ("subprocess.Popen", "os.exec", "os.posix_spawn"):
        events.append(["spawn", str(args[0])])
    elif event in ("socket.connect", "socket.getaddrinfo", "urllib.Request"):
        events.append(["network", event])
    elif event == "open":
        path, mode, flags = args
        writing = False
        if isinstance(mode, str):
            writing = any(flag in mode for flag in "wax+")
        elif mode is None:
            writing = bool(
                int(flags)
                & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
            )
        if writing:
            events.append(["write", str(path)])


import daedalus.loop as loop

sys.addaudithook(hook)
code = loop.main(["--max-iterations", "0"])
snapshot = list(events)
sys.stdout.write("\\n{MARKER}" + json.dumps({{"code": code, "events": snapshot}}) + "\\n")
'''

EFFECT_KINDS = {"write", "spawn", "network"}


@pytest.fixture(scope="module")
def traced_run():
    completed = subprocess.run(
        [sys.executable, "-c", CHILD],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    line = next(
        (
            row[len(MARKER):]
            for row in completed.stdout.splitlines()
            if row.startswith(MARKER)
        ),
        None,
    )
    assert line is not None, (
        "the traced child produced no audit trace. "
        f"exit={completed.returncode} stdout={completed.stdout} "
        f"stderr={completed.stderr}"
    )
    return json.loads(line)


def test_the_spend_guard_precedes_every_effect_in_the_module_tail(traced_run):
    kinds = [kind for kind, _ in traced_run["events"]]
    assert "guard" in kinds, (
        "no guard-install event was recorded before the loop entrypoint ran; "
        "if the exit code is 2 with no events at all, `.env` was refused "
        "before the guard, which is a different (and correct) refusal"
    )

    guard_at = kinds.index("guard")
    effects_before = [
        (index, traced_run["events"][index])
        for index, kind in enumerate(kinds)
        if kind in EFFECT_KINDS and index < guard_at
    ]
    assert effects_before == [], (
        f"{len(effects_before)} effect(s) happened before the spend guard was "
        f"installed: {effects_before}"
    )


def test_the_module_tail_starts_at_the_canonical_boundary(traced_run):
    kinds = [kind for kind, _ in traced_run["events"]]
    assert "boundary" in kinds, (
        "`python -m daedalus.loop` reached its work without a canonical effect "
        "start; it is a second console door into cli.daedalus's effects"
    )
    started = [
        subject for kind, subject in traced_run["events"] if kind == "boundary"
    ]
    assert "cli.loop" in started

    guard_at = kinds.index("guard")
    boundary_at = kinds.index("boundary")
    assert guard_at < boundary_at, (
        "the boundary receipt must be able to name a guard that already ran"
    )
    effects_before_boundary = [
        traced_run["events"][index]
        for index, kind in enumerate(kinds)
        if kind in EFFECT_KINDS and index < boundary_at
    ]
    assert effects_before_boundary == [], (
        f"effects preceded the effect start: {effects_before_boundary}"
    )


def test_the_bounds_refusal_is_what_stopped_this_run(traced_run):
    """Pin the path the trace took, so a silently-succeeding loop is visible."""

    assert traced_run["code"] == 2, (
        "the traced run was supposed to stop at LoopBounds with exit 2; a "
        "different code means the trace covered a different code path"
    )


def test_loop_main_is_registered_and_anchored():
    row = REGISTRY_BY_ID["cli.loop"]

    assert row.target == "daedalus.loop:main"
    assert row.wiring is Wiring.CENTRAL
    assert row.guard_contracts == ("budget.process_guard",)
    assert Effect.SPEND in row.effects
    assert Effect.NETWORK_EGRESS in row.effects
    assert {(anchor.target, anchor.call) for anchor in row.anchors} == {
        ("daedalus.loop:main", "begin_effect")
    }


def test_the_boundary_start_precedes_argument_parsing_in_the_source():
    """Ordering the runtime trace cannot see on every future code path.

    ``begin_effect`` sitting above ``parse_args`` is what makes the guard
    unconditional: no ``--help``, no parse error, and no future subcommand
    branch can reach an effect around it.
    """

    module = ast.parse((ROOT / "daedalus" / "loop.py").read_text(encoding="utf-8"))
    main = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    lines: dict[str, int] = {}
    for node in ast.walk(main):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name and name not in lines:
                lines[name] = node.lineno

    assert "install_process_guard" in lines
    assert "begin_effect" in lines
    assert "parse_args" in lines
    assert lines["install_process_guard"] < lines["parse_args"]
    assert lines["begin_effect"] < lines["parse_args"]
