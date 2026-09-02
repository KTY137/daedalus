"""Every test-side sqlite3 connection opened by a ``with`` is closed.

``with sqlite3.connect(path) as conn`` is a TRANSACTION scope, not a closing
scope: it commits, it does not close. The connection then survives as
unreachable garbage inside a reference cycle, so refcounting never finalises it
at block exit and only the generational collector does, at a moment decided by
unrelated allocation elsewhere in the process. While it lives it holds an OS
handle on the database and, for the stores that set ``journal_mode=WAL``, keeps
the ``-wal``/``-shm`` companions on disk.

The product side of this defect class was closed at thirteen sites (e9254e12,
dc321950). This guard covers the test side, which kept the population. It
matters here for a reason that does not apply to product code: pytest-xdist
puts unrelated tests in one worker process, so a fixture leaking a connection
can make a *different* test's product assertion about companion files or handle
availability flap, and the failure surfaces nowhere near its cause.

WHY AST AND NOT GREP. Two of the textual matches in this tree are not code:
``tests/gates/test_provider_observation_persistence_inventory.py`` embeds a
synthetic ``FIXTURE`` source string containing this exact pattern, and feeds it
to a static scanner that asserts an exact number of connect calls in it.
Rewriting that string would break the scanner's own tests while fixing nothing.
Parsing rather than grepping excludes string literals and comments by
construction, so the guard cannot demand an edit to something that never runs.

WHY THE ``wrapped`` FLOOR. An "assert nothing matches" test passes just as
happily when the detector has stopped matching anything at all. The floor makes
the walker prove it can still recognise a connection before its silence means
anything.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

# Measured on this tree at the closing revision of Work Packet G1-TESTFIX-01.
# A floor, not an answer: new correctly-closed sites may push it up.
MINIMUM_WRAPPED_SITES = 36
MINIMUM_FILES_PARSED = 100


def _is_connection_call(func: ast.expr) -> bool:
    """``sqlite3.connect(...)`` or any ``<something>._connect(...)``."""
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "_connect":
        return True
    return (
        func.attr == "connect"
        and isinstance(func.value, ast.Name)
        and func.value.id == "sqlite3"
    )


def _is_closing_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr == "closing"
    return isinstance(func, ast.Name) and func.id == "closing"


def _scan() -> tuple[list[str], int, int]:
    unclosed: list[str] = []
    wrapped = 0
    parsed = 0
    for path in sorted(TESTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_bytes(), filename=str(path))
        parsed += 1
        rel = path.relative_to(TESTS.parent).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                expr = item.context_expr
                if not isinstance(expr, ast.Call):
                    # ``with connection:`` on an already-bound name is a bare
                    # transaction scope whose close() is someone else's job;
                    # tests/fixtures/runtime_trust_contention_fault_executor.py
                    # deliberately uses that shape and closes in a finally.
                    continue
                if _is_connection_call(expr.func):
                    unclosed.append(f"{rel}:{node.lineno}")
                elif (
                    _is_closing_call(expr.func)
                    and expr.args
                    and isinstance(expr.args[0], ast.Call)
                    and _is_connection_call(expr.args[0].func)
                ):
                    wrapped += 1
    return unclosed, wrapped, parsed


def test_no_test_side_sqlite_connection_is_left_to_the_collector() -> None:
    unclosed, _, _ = _scan()
    assert unclosed == [], (
        "`with sqlite3.connect(...)` / `with ..._connect()` commits but never "
        "closes; wrap the call in contextlib.closing(...) and, if the block "
        "writes on a connection that is not in autocommit, add an explicit "
        "connection.commit() before it closes -- close() alone discards the "
        "open transaction. Offending sites: " + ", ".join(unclosed)
    )


def test_the_detector_can_still_see_connections() -> None:
    """Guards the guard: silence above must mean absence, not blindness."""
    unclosed, wrapped, parsed = _scan()
    assert parsed >= MINIMUM_FILES_PARSED, (
        f"only parsed {parsed} test modules; the walker is not reaching the "
        "suite and its silence proves nothing"
    )
    assert wrapped + len(unclosed) >= MINIMUM_WRAPPED_SITES, (
        f"found only {wrapped + len(unclosed)} sqlite connection sites under "
        f"a `with`, expected at least {MINIMUM_WRAPPED_SITES}; the detector "
        "has stopped recognising connections"
    )
