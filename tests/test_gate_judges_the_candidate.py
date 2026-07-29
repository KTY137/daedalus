"""The gate must run the CANDIDATE'S code, not the primary checkout's.

WHY THIS FILE EXISTS. A sibling module in this repo -- `daedalus/kairos/evolution.py`,
the Best-of-N candidate runner -- invokes a bare `pytest` with `cwd=<worktree>`.
That was measured tonight and it does not do what it looks like it does:

  * bare `pytest` does NOT put cwd on `sys.path` (`sys.path[0]` is `<wt>/tests`),
  * the editable install pins `daedalus` to the primary checkout by ABSOLUTE path,
  * so pytest COLLECTS the candidate's `tests/` and runs them against the
    PRIMARY checkout's code.

The score is then constant with respect to the candidate. Every candidate gets
the same verdict, the fitness signal has no gradient, and the whole selection is
noise wearing a number. Measured on this box, both horns:

    attempt.py gate argv (sys.executable -m pytest)  exit=0  -> CANDIDATE
    bare pytest                                      exit=1  -> IMPORTED FROM:
                                                        C:\\...\\agent_env\\daedalus

`daedalus/spine/attempt.py` gets this right, and the entire difference is the
`-m`. That is a one-token property, invisible on review, and exactly the kind of
thing someone "simplifies" while tidying an argv. So it is pinned here by
EXECUTION rather than by asserting on the string: a test that only checked for
"-m" in the tuple would still pass if some future sys.path change made the flag
insufficient.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from daedalus.spine.attempt import pytest_gate_argv

MARKER_TEST = (
    "import daedalus, pathlib\n"
    "def test_marker():\n"
    "    got = getattr(daedalus, 'CANDIDATE_MARKER', False)\n"
    "    assert got, f'gate imported {pathlib.Path(daedalus.__file__).parent}'\n"
)


@pytest.fixture
def candidate_worktree():
    """A worktree holding a `daedalus` package the primary checkout does not have.

    The marker is the whole instrument: if the gate imports this package the
    test inside passes, and if it reaches past it to the real installed
    `daedalus` the marker is absent and the test fails. No mocking -- the
    question is which code a real subprocess actually imports.
    """
    wt = Path(tempfile.gettempdir()) / f"gatejudge-{uuid.uuid4().hex[:8]}"
    (wt / "daedalus").mkdir(parents=True)
    (wt / "tests").mkdir()
    (wt / "daedalus" / "__init__.py").write_text(
        "CANDIDATE_MARKER = True\n", encoding="utf-8")
    (wt / "tests" / "test_marker.py").write_text(MARKER_TEST, encoding="utf-8")
    try:
        yield wt
    finally:
        shutil.rmtree(wt, ignore_errors=True)


def _run(argv, cwd) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in argv], cwd=str(cwd),
                          capture_output=True, text=True, timeout=180)


def test_the_gate_imports_the_candidates_code(candidate_worktree):
    """The property the whole loop rests on.

    If this fails, every gate verdict in this repo describes the primary
    checkout and no candidate can ever be distinguished from any other.
    """
    proc = _run(pytest_gate_argv(["tests/test_marker.py"]), candidate_worktree)
    assert proc.returncode == 0, (
        "the gate did not import the candidate's code:\n"
        + (proc.stdout or "")[-1200:])


def test_bare_pytest_does_NOT__which_is_why_the_argv_is_shaped_this_way(
        candidate_worktree):
    """The control. Without it the test above proves nothing.

    A gate that passed for some unrelated reason would look identical to a
    working one, so the failing case is measured too: the same worktree, the
    same test file, only the invocation differs.

    If this ever starts PASSING, bare `pytest` became safe on this platform --
    good news, but the reasoning in `pytest_gate_argv` would then be stale and
    should be re-derived rather than left as folklore.
    """
    if shutil.which("pytest") is None:
        pytest.skip("no bare `pytest` on PATH to contrast against")
    proc = _run(["pytest", "tests/test_marker.py", "-q"], candidate_worktree)
    assert proc.returncode != 0, (
        "bare pytest now imports the candidate too -- the -m in "
        "pytest_gate_argv may no longer be load-bearing; re-derive the comment")


def test_the_gate_argv_is_built_from_this_interpreter():
    """`sys.executable`, not the string "python".

    A hardcoded "python" resolves through PATH, which in this environment can be
    a different interpreter than the one running the harness -- a different
    version, a different venv, a different set of installed packages. The gate
    would then judge the candidate under an environment nobody chose.
    """
    argv = pytest_gate_argv([])
    assert argv[0] == sys.executable
    assert argv[1:3] == ("-m", "pytest")
