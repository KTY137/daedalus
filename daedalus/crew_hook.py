"""crew_hook.py \u2014 keep the fleet busy, and make idleness visible.

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

import contextlib
import io
import os
import sys
import tempfile
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


def _run_tests() -> int:
    """Run self-tests; returns 0 if all pass, else the number of failures."""
    @contextlib.contextmanager
    def _set_env(key: str, value: str | None) -> None:
        old = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        try:
            yield
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    failures = 0

    def test_missing_task_dir() -> None:
        """No task directory -> (0, [])."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                n, names = live_agents()
        if n != 0 or names != []:
            print(f"FAIL: test_missing_task_dir: expected (0, []), got ({n}, {names})")
            failures += 1
        else:
            print("PASS: test_missing_task_dir")

    def test_unreadable_task_dir() -> None:
        """Unreadable task directory -> OSError caught, returns (0, [])."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True, exist_ok=True)
                (tasks / "unreachable.output").touch()
                try:
                    os.chmod(tasks, 0o000)
                except OSError as e:
                    print(f"SKIP: test_unreadable_task_dir: cannot chmod to 000 ({e})")
                    return
                try:
                    n, names = live_agents()
                finally:
                    # Restore permissions so the temp dir can be cleaned up.
                    os.chmod(tasks, 0o755)
                if n != 0 or names != []:
                    print(f"FAIL: test_unreadable_task_dir: expected (0, []), got ({n}, {names})")
                    failures += 1
                else:
                    print("PASS: test_unreadable_task_dir")

    def test_empty_window() -> None:
        """All transcripts older than LIVE_WINDOW_S -> count = 0."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True)
                old = tasks / "stale.output"
                old.touch()
                old_mtime = time.time() - 2 * LIVE_WINDOW_S
                os.utime(old, (old_mtime, old_mtime))
                n, names = live_agents()
                if n != 0 or names != []:
                    print(f"FAIL: test_empty_window: expected (0, []), got ({n}, {names})")
                    failures += 1
                else:
                    print("PASS: test_empty_window")

    def test_future_mtime() -> None:
        """Transcript with future mtime (clock skew) is counted as live."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True)
                fname = "future.output"
                future = tasks / fname
                future.touch()
                fut_time = time.time() + 1000
                os.utime(future, (fut_time, fut_time))
                n, names = live_agents()
                expected_name = Path(fname).stem
                if n != 1 or names != [expected_name]:
                    print(f"FAIL: test_future_mtime: expected (1, ['{expected_name}']), got ({n}, {names})")
                    failures += 1
                else:
                    print("PASS: test_future_mtime")

    def test_at_minimum() -> None:
        """Exactly MIN_PARALLEL live -> main prints 'at or above'."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True)
                now = time.time()
                for i in range(MIN_PARALLEL):
                    f = tasks / f"agent_{i}.output"
                    f.touch()
                    os.utime(f, (now, now))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    main()
                output = buf.getvalue()
                if "at or above" not in output or str(MIN_PARALLEL) not in output:
                    print(f"FAIL: test_at_minimum: unexpected output: {output!r}")
                    failures += 1
                else:
                    print("PASS: test_at_minimum")

    def test_above_minimum() -> None:
        """More than MIN_PARALLEL live -> main prints 'at or above'."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True)
                now = time.time()
                for i in range(MIN_PARALLEL + 2):
                    f = tasks / f"agent_{i}.output"
                    f.touch()
                    os.utime(f, (now, now))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    main()
                output = buf.getvalue()
                if "at or above" not in output:
                    print(f"FAIL: test_above_minimum: missing 'at or above' in output: {output!r}")
                    failures += 1
                else:
                    print("PASS: test_above_minimum")

    def test_below_minimum() -> None:
        """Fewer than MIN_PARALLEL live -> main prints the dispatch message."""
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmpdir:
            with _set_env("TEMP", tmpdir):
                tasks = Path(tmpdir) / "claude" / "tasks"
                tasks.mkdir(parents=True)
                now = time.time()
                for i in range(MIN_PARALLEL - 1):
                    f = tasks / f"agent_{i}.output"
                    f.touch()
                    os.utime(f, (now, now))
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    main()
                output = buf.getvalue()
                if "minimum is" not in output or "Dispatch" not in output:
                    print(f"FAIL: test_below_minimum: unexpected output: {output!r}")
                    failures += 1
                else:
                    print("PASS: test_below_minimum")

    tests = [
        test_missing_task_dir,
        test_unreadable_task_dir,
        test_empty_window,
        test_future_mtime,
        test_at_minimum,
        test_above_minimum,
        test_below_minimum,
    ]
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"FAIL: {test.__name__} raised {e}")
            failures += 1
    if failures == 0:
        print("All tests passed.")
    else:
        print(f"{failures} test(s) failed.")
    return failures


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(_run_tests())
    raise SystemExit(main())
