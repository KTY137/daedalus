"""An attempt that declares no ``target_paths`` is refused, never unfenced.

THE DEFECT, MEASURED 2026-08-24 (docs/inventory/2026-08-24/DENY_FLOOR_CORPUS.md).
``TaskAttempt._run_with_ledger`` guarded its target-scope check with
``if self.task.target_paths:``. A task that declared nothing was therefore
compared against nothing, every changed path passed, and the patch went straight
to ``_run_gates``.

That check is not bookkeeping. It runs BEFORE the gate, and it is the thing
standing between a candidate and its own evaluator: the gate is
``python -m pytest ... tests/test_event_field.py`` with cwd set to the candidate
worktree, so a ``conftest.py`` in that worktree is loaded into the evaluator
process before any test body runs. Measured, end to end, on a real
``prepare_ignition_repo`` tree:

    base, no conftest (must FAIL)      passed=False
    candidate adds one conftest.py     passed=True

with the whole patch being ``def pytest_sessionfinish(session, exitstatus):
session.exitstatus = 0``. Under the old truthiness guard, any task that named no
scope handed a candidate that path.

Empty is not "declare nothing"; it is "fence nothing".

WHAT THESE TESTS PIN, and why there are two. The first is behavioural and is the
mutation anchor: restore the truthiness guard and it goes red, because the
attempt comes back ``clean`` instead of refused. The second pins the REASON
string, because a refusal that reports "you wrote outside your declared
target_paths" when nothing was declared sends the reader looking for a
declaration that does not exist.

Deliberately NOT pinned: that the refusal happens at patch time rather than
before the runner. Refusing earlier is the stronger form and is a separate
question; what matters for the evaluator boundary is that the refusal precedes
``_run_gates``, which the state assertion below establishes.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from daedalus.spine.attempt import (
    STATE_CLEAN,
    STATE_GATES_FAILED,
    GateResult,
    RunnerContext,
    TaskAttempt,
    TaskSpec,
)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir(parents=True)
    (root / "keep.txt").write_text("base\n", encoding="utf-8")
    for args in (
        ["init", "--quiet", "-b", "base"],
        ["config", "user.name", "t"],
        ["config", "user.email", "t@example.com"],
        ["add", "-A"],
        ["commit", "--quiet", "-m", "base"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True,
                       capture_output=True)
    return root


def _writing_runner(rel: str):
    """A runner that writes exactly one file inside the candidate worktree."""

    def runner(ctx: RunnerContext) -> str:
        target = ctx.worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("written by the candidate\n", encoding="utf-8")
        return rel

    return runner


def _green_gate(ctx: RunnerContext) -> GateResult:
    """A gate that would pass. It must never be reached in these tests."""

    return GateResult(passed=True, name="unreachable", command=(),
                      returncode=0, output="")


def _run(tmp_path: Path, target_paths, rel="conftest.py"):
    repo = _repo(tmp_path)
    task = TaskSpec(
        task_id="undeclared-scope",
        instruction="write one file",
        target_paths=target_paths,
    )
    return TaskAttempt(
        task,
        runner=_writing_runner(rel),
        gate=_green_gate,
        repo_root=repo,
        ledger_path=tmp_path / "spine.sqlite3",
    ).run()


def test_an_undeclared_scope_refuses_the_attempt(tmp_path):
    """THE MUTATION ANCHOR. Restore ``if self.task.target_paths:`` and the
    attempt comes back ``clean`` with the gate having run, and this fails."""

    result = _run(tmp_path, ())
    assert result.state == STATE_GATES_FAILED, (
        f"an attempt that declared no target_paths came back {result.state!r}; "
        "an undeclared scope must be refused, not skipped"
    )
    assert result.state != STATE_CLEAN
    # The refusal precedes the gate: the gate that would have passed never ran.
    assert result.gates is not None
    assert result.gates.name == "target-scope"
    assert result.gates.passed is False


def test_the_refusal_says_there_was_no_scope_rather_than_that_one_was_escaped(
    tmp_path,
):
    """A refusal naming a declaration that does not exist sends the reader
    looking for it. The two cases must read differently."""

    undeclared = _run(tmp_path / "a", ())
    assert "declared no target_paths at all" in (undeclared.error or "")
    assert "refused, never skipped" in (undeclared.error or "")

    # The pre-existing case still reads as it did: a real declaration, escaped.
    escaped = _run(tmp_path / "b", ("keep.txt",))
    assert escaped.state == STATE_GATES_FAILED
    assert "outside declared target_paths" in (escaped.error or "")
    assert "declared no target_paths at all" not in (escaped.error or "")


def test_a_declared_scope_that_covers_the_write_still_passes_the_check(tmp_path):
    """The fix must not turn every attempt into a refusal: a task that declares
    the path it writes reaches its gate exactly as before."""

    result = _run(tmp_path, ("conftest.py",))
    assert result.state == STATE_CLEAN, result.error
    assert result.gates is not None and result.gates.name == "unreachable"


@pytest.mark.parametrize("declared", [None, (), []])
def test_every_spelling_of_no_declaration_is_refused(tmp_path, declared):
    """``None``, ``()`` and ``[]`` are one fact, and a guard that catches only
    some of them is a guard with a spelling-shaped hole."""

    result = _run(tmp_path / str(declared).replace("[]", "empty-list"), declared)
    assert result.state == STATE_GATES_FAILED
    assert "declared no target_paths at all" in (result.error or "")
