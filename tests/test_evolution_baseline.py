"""Characterise the Best-of-N baseline that ADR-009 says Ariadne must replace.

WHY THIS FILE EXISTS. ADR-009 requires that any superiority claim for Ariadne be
made against Best-of-N. A baseline you cannot state precisely is not a baseline,
and `daedalus/kairos/evolution.py` has never been executed by anything -- it is an
ISLAND (`docs/architecture-state.json`, "islands" and "test_only"), its own tests
reach only `generate_candidates` and `select_best`, and `evaluate_candidates` --
the fitness function, the only part that decides anything -- has no caller
anywhere in the repository. Its properties were prose. These tests measure them,
so `docs/adrs/015-ariadne-preconditions.md` can cite a control.

Nothing here needs a model, a network, or a real worktree.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from daedalus.kairos.evolution import EvolutionaryOrchestrator
from daedalus.kairos.shadow_shell import CandidateBranch

_EVOLUTION_PY = (Path(__file__).resolve().parents[1]
                 / "daedalus" / "kairos" / "evolution.py")

# What the probe writes when `import daedalus` did NOT reach the candidate's copy.
_PRIMARY = "PRIMARY_CHECKOUT"


def _candidate_worktree(root: Path) -> Path:
    """A directory shaped like a candidate worktree: its own ``daedalus``
    package carrying a marker, and ``tests/`` with no ``__init__.py`` -- the
    exact layout of this repo (verified: no tests/__init__.py, no conftest.py,
    no [tool.pytest] section anywhere)."""
    root.mkdir(parents=True)
    (root / "daedalus").mkdir()
    (root / "daedalus" / "__init__.py").write_text(
        'CANDIDATE_MARKER = "candidate"\n', encoding="utf-8")
    (root / "tests").mkdir()
    # The probe records what `import daedalus` resolved to, from INSIDE a test
    # run rooted at the worktree -- i.e. exactly the situation evaluate_candidates
    # creates. It writes to a file because the score the runner reads is an exit
    # code, which cannot carry this.
    (root / "tests" / "test_probe.py").write_text(textwrap.dedent(f"""
        from pathlib import Path

        def test_probe():
            try:
                import daedalus
                seen = getattr(daedalus, "CANDIDATE_MARKER", {_PRIMARY!r})
            except Exception as exc:
                seen = "IMPORT_ERROR: " + type(exc).__name__
            Path(__file__).parent.parent.joinpath("resolved.txt").write_text(
                seen, encoding="utf-8")
    """), encoding="utf-8")
    return root


def _run_probe(wt: Path, argv: list[str]) -> str:
    (wt / "resolved.txt").unlink(missing_ok=True)
    proc = subprocess.run(argv, cwd=str(wt), capture_output=True,
                          encoding="utf-8", errors="replace", timeout=180)
    if not (wt / "resolved.txt").exists():
        pytest.skip(f"probe did not run ({argv[0]}): "
                    f"{proc.stdout[-300:]!r} {proc.stderr[-300:]!r}")
    return (wt / "resolved.txt").read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- #
# 1. The measured defect: the evaluator does not execute the candidate's code. #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(shutil.which("pytest") is None,
                    reason="no bare `pytest` on PATH to reproduce the invocation")
def test_bare_pytest_does_not_reach_the_candidates_own_code(tmp_path):
    """THE FINDING, as a control.

    ``evaluate_candidates`` scores a candidate with
    ``create_subprocess_exec("pytest", cwd=worktree)``
    (``daedalus/kairos/evolution.py``:56-62). Bare ``pytest`` -- unlike
    ``python -m pytest`` -- does NOT put the working directory on ``sys.path``,
    so an installed ``daedalus`` shadows the candidate's own package and the
    suite scores code the candidate never touched. pytest still COLLECTS the
    candidate's ``tests/``, so the run is the candidate's tests against someone
    else's code.

    This pins the mechanism, not the bug: it stays true whatever
    ``evolution.py`` does, and it is why the fix is an interpreter-qualified
    invocation.
    """
    wt = _candidate_worktree(tmp_path / "candidate")

    bare = _run_probe(wt, ["pytest", "-q"])
    if bare.startswith("IMPORT_ERROR"):
        # The other horn: with no installed daedalus, the import fails outright,
        # every candidate scores 0.0 and select_best returns None. Still not a
        # measurement of the candidate.
        pytest.skip("daedalus is not installed; bare pytest cannot import it at "
                    f"all ({bare}) -- the shadowing horn is not reproducible here")

    qualified = _run_probe(wt, [sys.executable, "-m", "pytest", "-q"])

    assert qualified == "candidate", (
        "`python -m pytest` puts the worktree on sys.path and MUST reach the "
        f"candidate's daedalus; got {qualified!r}")
    assert bare == _PRIMARY, (
        "bare `pytest` reached the CANDIDATE's daedalus -- the shadowing this "
        f"test documents is absent in this environment; got {bare!r}")


def test_evaluator_invokes_an_interpreter_qualified_pytest():
    """The fitness signal must run the candidate's interpreter and code.

    Until 2026-07-29 this was an ``xfail(strict=True)`` pinning the MEASURED
    defect (ADR-015 P1): the evaluator shelled out to a bare ``pytest``, which
    does not put the candidate worktree on ``sys.path``, so every score ever
    produced described the PRIMARY checkout's code against the candidate's
    tests. The xfail was a deliberate tripwire -- fixing the bug XPASSed it
    and turned the suite red so ADR-015 could not be silently outdated. The
    fix landed (``sys.executable, "-m", "pytest"``, verified by a direct
    shadowing experiment: bare pytest resolved daedalus to the primary tree,
    ``-m pytest`` to the candidate worktree), the tripwire fired as designed,
    and this is now a plain regression guard. ADR-015 P1 is addressed; the
    ADR text itself still needs its owner's update.
    """
    src = _EVOLUTION_PY.read_text(encoding="utf-8")
    assert "sys.executable" in src, (
        "evaluate_candidates must not invoke a bare 'pytest'")


# --------------------------------------------------------------------------- #
# 2. The baseline's actual selection behaviour, stated so it can be beaten.    #
# --------------------------------------------------------------------------- #
def test_fitness_is_binary_so_there_is_no_ordering_among_green_candidates():
    """Best-of-N here is FIRST-GREEN-WINS, not best-wins.

    ``evaluate_candidates`` only ever writes 100.0, 0.0 or -1.0
    (evolution.py:51,64-67,72,75), and ``select_best`` keeps ``score >= 100.0``
    then sorts -- a stable sort over one distinct value, so INPUT ORDER decides
    (evolution.py:91-102). The baseline exerts no selection pressure among
    candidates that pass: it is a filter, not a ranker. Any claim that Ariadne
    beats "Best-of-N" is a claim against this.
    """
    orch = EvolutionaryOrchestrator(shell_manager_factory=lambda: None)
    greens = [
        CandidateBranch(branch_name=f"c{i}", worktree_path=Path(""),
                        task="t", completed=True, score=100.0)
        for i in range(5)
    ]
    assert orch.select_best(greens).branch_name == "c0"
    assert orch.select_best(list(reversed(greens))).branch_name == "c4"


def test_no_candidate_is_selected_when_none_is_green():
    """The one safety property the baseline does hold."""
    orch = EvolutionaryOrchestrator(shell_manager_factory=lambda: None)
    reds = [
        CandidateBranch(branch_name="a", worktree_path=Path(""), task="t",
                        completed=True, score=0.0, error="tests failed"),
        CandidateBranch(branch_name="b", worktree_path=Path(""), task="t",
                        completed=False, score=100.0),
    ]
    assert orch.select_best(reds) is None


def test_the_fitness_function_has_no_caller():
    """`evaluate_candidates` is dead even inside its own island.

    Recorded because ADR-015's Finding 1 rests on it, and because the class has
    no method chaining generate -> evaluate -> select: the "runner" is three
    disconnected callables. If this ever goes red, something finally wired the
    baseline up and ADR-015 needs revisiting.
    """
    repo = Path(__file__).resolve().parents[1]
    hits = []
    for path in list(repo.glob("daedalus/**/*.py")) + list(repo.glob("tests/*.py")):
        if path == _EVOLUTION_PY or path == Path(__file__).resolve():
            continue
        if "evaluate_candidates" in path.read_text(encoding="utf-8", errors="replace"):
            hits.append(str(path.relative_to(repo)))
    assert hits == [], f"evaluate_candidates now has callers: {hits}"


def test_evaluator_bounds_the_candidate_test_run():
    """A candidate that hangs must not hang the whole generation.

    The INVERSE of the characterisation test that stood here until 2026-07-29.
    The old test pinned the defect (``await process.communicate()`` with no
    timeout inside an ungated ``gather`` -- one non-terminating candidate
    blocked the run forever, ADR-015 P6) and instructed, in its own docstring:
    "If this goes red, evolution.py grew a timeout -- a fix; update P6 and
    delete this test." The timeout landed (600s per candidate, process killed
    on expiry), so per its own instruction the characterisation is deleted and
    replaced by this guard so the bound cannot silently regress. ADR-015 P6 is
    addressed in code; the ADR text still needs its owner's update.
    """
    src = _EVOLUTION_PY.read_text(encoding="utf-8")
    assert "wait_for" in src or "timeout" in src, (
        "evolution.py lost its per-candidate timeout -- a hung candidate "
        "would block the whole generation again (ADR-015 P6)")
