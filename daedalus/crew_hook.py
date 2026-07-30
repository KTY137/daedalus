"""crew_hook.py — keep the fleet busy, and make idleness visible.

THE RULE THIS ENFORCES
----------------------
The operator's standing instruction is that at least four agents should be
working in parallel. Serial work by one agent is the slow, expensive default an
orchestration system exists to replace, and the failure is silent: nothing about
working alone feels wrong from the inside.

WHY THIS MEASURES INSTEAD OF NAGGING
------------------------------------
A hook that prints "remember to parallelise" every turn becomes wallpaper within
five turns -- the same habituation that made the architecture block worth
reducing to a delta. So this counts what is ACTUALLY running and says the number.
A count is checkable, a slogan is not, and a number that says 0 is an
instruction nobody can read past.

It also names WHERE to send work when the fleet is idle, because "you should
parallelise" without a target is an obligation without an action.

Counting is best-effort by construction: a subagent's liveness is the harness's
business, not this repo's, so the count comes from the task transcript directory
and is reported as approximate. An approximate number that is honest about being
approximate beats an exact one that is wrong.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

MIN_PARALLEL = 4

#: How recently a task file must have been touched to count as live. Long enough
#: that a thinking agent is not called dead, short enough that yesterday's run is
#: not called alive.
LIVE_WINDOW_S = 180.0


def _task_dir() -> Path | None:
    """The harness's task transcript directory for this session, if reachable."""
    base = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
    root = base / "claude"
    if not root.is_dir():
        return None
    candidates = [p for p in root.rglob("tasks") if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def live_agents() -> tuple[int, list[str]]:
    """(count, names) of agent transcripts touched inside the live window."""
    d = _task_dir()
    if d is None:
        return 0, []
    now = time.time()
    live = []
    try:
        for f in d.glob("*.output"):
            try:
                if now - f.stat().st_mtime <= LIVE_WINDOW_S:
                    live.append(f.stem)
            except OSError:
                continue
    except OSError:
        return 0, []
    return len(live), sorted(live)


#: Where work can go when the fleet is idle. Named concretely, because an
#: instruction without a target is a mood.
TARGETS = (
    "DeepSeek (advisory, reads daedalus/ since the 2026-07-30 egress decision) "
    "-- reviews, adversarial audits, research questions with paths=[]",
    "haiku delegates (argus read-only recon, kadmos mechanical edits, "
    "metron gate runs, mnemosyne docs)",
    "background Bash -- test suites, receipt runs, index builds",
)


def main() -> int:
    n, names = live_agents()
    if n >= MIN_PARALLEL:
        print(f"CREW: {n} agents live -- at or above the standing minimum of {MIN_PARALLEL}")
        return 0
    shown = ", ".join(x[:8] for x in names[:6]) if names else "none"
    print(f"CREW: {n} live (approx), minimum is {MIN_PARALLEL} -- [{shown}]")
    print("  Dispatch before continuing serially. Where work goes:")
    for t in TARGETS:
        print(f"    - {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
