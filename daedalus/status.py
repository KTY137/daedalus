"""`daedalus status` -- what is WORKING, what is merely PRESENT, what nobody ran.

WHAT CHANGED AND WHY. This file used to print six numbers and a git diff:

    Repo / Branch / Outbox: 1 pending / Inbox: 61 reports / Memory: 166 events

Every one of those lines was true tonight, and together they described a
machine that was quietly broken. The outbox held a task and the watcher had
been dead for twelve days -- "1 pending" is the same string in both worlds. The
map described a tree thirty commits behind. The planner weighted a memory index
that has never existed. None of it was reachable from this screen, because a
counter cannot say *nobody is going to pick that up*.

So the counters stay (:func:`collect_status` is consumed by ``daedalus.core``
and by the VS Code extension, and its keys are unchanged) but they are no
longer the answer. The answer is :mod:`daedalus.health`, which reports each
subsystem as one of five things -- ``working``, ``present``, ``degraded``,
``absent``, ``unknown`` -- and can never render the last two as a pass.

    python -m daedalus.status                # the glance
    python -m daedalus.status --counters     # only the old six numbers
    python -m daedalus.status --json         # legacy payload + a "health" key
    python -m daedalus.status --probe-remote # also exercise the bench embedder

EXIT CODES, and the one exception. The human path exits 0 only when every
subsystem was exercised and held; 1 when something is degraded or missing; 2
when nothing that ran is broken but not everything ran. ``--json`` always exits
0, because the VS Code extension shells out with ``execFile`` and treats a
non-zero exit as a crashed command -- turning a truthful "degraded" into a
broken status bar would push the operator back to a surface that lies. The
verdict is in the payload either way.

RELATION TO tools/system_check.py. That harness clones the tree and RUNS the
product; it answers "does the pipeline execute end to end". This reads the live
artefacts in the tree you are standing in. Neither replaces the other, and this
one is the one you run at a glance.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from . import health
from .file_bridge import INBOX, OUTBOX
from .memory import TODO_PATH, load_events
from .foundation.projects import resolve_repo_root


ROOT = Path(__file__).resolve().parents[1]


def _git(repo_root: str, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        return completed.stderr.strip()
    return completed.stdout.strip()


def _count_open_todos(events: list[dict[str, Any]]) -> int:
    open_keys: set[str] = set()
    done_keys: set[str] = set()
    for event in events:
        status = event.get("status")
        for todo in event.get("todos", []):
            key = todo.strip().lower()
            if not key:
                continue
            if status == "done":
                done_keys.add(key)
            else:
                open_keys.add(key)
    return len(open_keys - done_keys)


def collect_status(repo_root: str) -> dict[str, Any]:
    """The six counters, unchanged.

    KEPT VERBATIM ON PURPOSE. ``daedalus.core`` feeds this to the web API and
    the VS Code status bar reads ``outbox_count``/``open_todos`` out of it; a
    key rename here breaks two surfaces for no gain. What changed is that this
    is no longer presented AS the status -- see :func:`main`.
    """
    events = load_events()
    return {
        "repo_root": repo_root,
        "git_branch": _git(repo_root, ["branch", "--show-current"]),
        "git_status": _git(repo_root, ["status", "--short"]),
        "outbox_count": len(list(OUTBOX.glob("*.json"))) if OUTBOX.exists() else 0,
        "inbox_count": len(list(INBOX.glob("*.report.json"))) if INBOX.exists() else 0,
        "memory_events": len(events),
        "open_todos": _count_open_todos(events),
        "todo_snapshot": str(TODO_PATH),
    }


def print_counters(status: dict[str, Any]) -> None:
    """The old output. Now labelled as what it is: counts, not health.

    Each line says what it does NOT prove, because "Outbox: 1 pending" read as
    "one task is being worked on" is precisely how a dead watcher stayed
    invisible for twelve days.
    """
    print(f"Repo: {status['repo_root']}")
    print(f"Branch: {status['git_branch']}")
    print(f"Outbox: {status['outbox_count']} pending   "
          f"(a count; whether anything consumes them is bridge.queue above)")
    print(f"Inbox: {status['inbox_count']} reports")
    print(f"Memory: {status['memory_events']} events, "
          f"{status['open_todos']} open TODOs")
    print(f"TODO snapshot: {status['todo_snapshot']}")
    lines = [l for l in str(status["git_status"]).splitlines() if l.strip()]
    if lines:
        # Truncated in the RENDER only; collect_status still returns the whole
        # string. Eighty lines of `??` push the health verdict off the screen,
        # and a verdict nobody scrolls to is a verdict nobody reads.
        print(f"\nGit status ({len(lines)} path(s)):")
        for line in lines[:10]:
            print(line)
        if len(lines) > 10:
            print(f"... and {len(lines) - 10} more (git status --short)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Subsystem health: working / present / degraded / absent / "
                    "unknown.")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true",
                        help="legacy counter payload plus a 'health' key; "
                             "always exits 0 for tool callers")
    parser.add_argument("--counters", action="store_true",
                        help="only the old six numbers, no health assessment")
    parser.add_argument("--only", help="substring filter on subsystem name")
    parser.add_argument("--quiet", action="store_true",
                        help="one line per subsystem, no evidence")
    parser.add_argument("--probe-remote", action="store_true",
                        help="also exercise the bench host's embedding backend")
    parser.add_argument("--deep", action="store_true",
                        help="also exercise the expensive paths (the latent "
                             "router); without it they report `present`")
    args = parser.parse_args(argv)
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.status",
        REGISTRY_BY_ID["cli.status"].effects,
        (process_guard_boundary_decision(),),
    )
    try:
        repo_root = resolve_repo_root(args.repo_root, args.project)
    except ValueError:
        # THE HARNESS ITSELF IS A LEGITIMATE SUBJECT. The old main() raised
        # here, so `python -m daedalus.status` with no arguments -- the command
        # anybody types first -- was a traceback. The subsystems below are the
        # harness's own, so defaulting to the harness root answers the question
        # that was asked instead of refusing it.
        repo_root = str(ROOT)
    status = collect_status(repo_root)

    if args.counters and not args.json:
        print_counters(status)
        return 0

    reports = health.assess(args.only, repo_root=repo_root,
                            probe_remote=args.probe_remote, deep=args.deep)
    code = health.verdict(reports)

    if args.json:
        # Legacy keys first and untouched, so every existing consumer keeps
        # working; the assessment rides along under one new key.
        payload = dict(status)
        payload["health"] = health.to_payload(reports)
        print(json.dumps(payload, indent=2, default=str))
        # ALWAYS 0 -- see the module docstring. The verdict lives in
        # payload["health"]["verdict"], where a program can branch on it
        # without a shell-out being reported as a crash.
        return 0

    print("daedalus status -- what is working, what is merely present\n")
    print(health.render(reports, verbose=not args.quiet))
    print()
    print_counters(status)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
