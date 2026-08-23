"""The attempt spine's ``target-scope`` containment, and what a declaration MEANS.

WHAT WAS WRONG. ``TaskAttempt.run`` normalised each declared ``target_path``
with a bare ``.replace("\\\\", "/").removeprefix("./")`` and then tested exact
string membership against git's canonical ``changed_paths``. Two things followed
from that, and no test pinned either:

* a declaration naming a DIRECTORY matched nothing at all, so a task that
  scoped ``tests`` had its entire patch rejected as escaped -- while
  ``receipts._criterion_seal``, reading the SAME field through
  ``_inside_scope``, already treated ``tests`` as covering ``tests/test_gate.py``
  and refused the criterion a seal on exactly that ground. One field, two
  meanings, and the receipt was written by the generous one;
* a declaration git could never match (``C:/x``, ``../x``) failed closed by
  accident rather than by decision, and reported "changed path outside
  target_paths" for a patch that was inside the boundary the operator meant.

THE DECISION. Directories are the accepted shape, on BOTH sides, normalised by
``receipts._normalise_tree_path`` (posixpath.normpath + this host's case
semantics, absolute and root-escaping declarations refused outright) and
compared on path SEGMENT boundaries. That is the shape the seal already assumed,
the shape ``picker._queue_repo_path`` already admits, and a superset of the
file-only shape ``ignition.gate1`` passes -- so every existing producer keeps
working and the two halves of the boundary finally say the same thing. The
alternative -- refusing a directory declaration at TaskSpec validation -- would
have made the seal's own documented example illegal and broken the work-queue
source, for no gain the segment-boundary comparison does not already give.
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.schemas import ResourceBudget  # noqa: E402
from daedalus.spine.attempt import (  # noqa: E402
    STATE_CLEAN,
    STATE_GATES_FAILED,
    GateResult,
    TaskAttempt,
    TaskSpec,
)
from daedalus.spine.receipts import containment_escapes  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A base revision with a ``tests`` directory AND a ``tests_evil.py`` sibling."""
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "containment@example.com")
    _git(root, "config", "user.name", "containment")
    (root / "src" / "foo.py").write_text("VALUE = 0\n", encoding="utf-8")
    (root / "tests" / "test_gate.py").write_text("assert True\n", encoding="utf-8")
    # The string-prefix trap: `tests` must not cover this file.
    (root / "tests_evil.py").write_text("EVIL = 0\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _base(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _writer(*names):
    def _runner(ctx):
        for name in names:
            path = ctx.worktree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# candidate\n", encoding="utf-8")
    return _runner


def _green(ctx):
    return GateResult(passed=True, name="probe-gate", returncode=0,
                      command=("python", "-m", "pytest"), output="green\n",
                      duration_s=0.1)


def _run(repo, tmp_path, label, *, target_paths, runner):
    spec = TaskSpec(task_id=f"scope-{label}", instruction="write",
                    base_revision=_base(repo), target_paths=target_paths,
                    gate_timeout_s=60.0)
    attempt = TaskAttempt(spec, runner=runner, gate=_green, repo_root=repo,
                          ledger_path=tmp_path / f"spine-{label}.sqlite3",
                          artifact_dir=tmp_path / f"store-{label}",
                          mission_id=f"mission-{label}", reap=False,
                          budget=ResourceBudget(max_wall_time_s=120))
    return attempt.run()


# --------------------------------------------------------------------------- #
# 1. a declared DIRECTORY is a boundary, not a filename that never matches      #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("declaration", ["tests", "tests/", "./tests"])
def test_a_declared_directory_covers_the_files_under_it(
        repo, tmp_path, declaration):
    """The bug: this used to reject the whole patch as escaped.

    Every spelling of the same declaration is one boundary, because both sides
    are put through one normal form before they are compared.
    """
    result = _run(repo, tmp_path, f"dir-{declaration.strip('./')}-in",
                  target_paths=(declaration,),
                  runner=_writer("tests/test_new.py"))

    assert result.state == STATE_CLEAN, result.error
    assert list(result.artifact.changed_paths) == ["tests/test_new.py"]


def test_a_declared_directory_stops_at_a_path_segment_boundary(repo, tmp_path):
    """``tests`` must not cover ``tests_evil.py``.

    A string-prefix containment would admit it, and admitting it is how a
    declaration meant to scope a directory silently widens to its siblings.
    """
    result = _run(repo, tmp_path, "sibling", target_paths=("tests",),
                  runner=_writer("tests_evil.py"))

    assert result.state == STATE_GATES_FAILED
    assert result.gates.name == "target-scope"
    assert "tests_evil.py" in result.error
    assert list(result.artifact.changed_paths) == ["tests_evil.py"]


def test_a_declared_file_still_means_that_one_file(repo, tmp_path):
    result = _run(repo, tmp_path, "file", target_paths=("tests/test_gate.py",),
                  runner=_writer("src/foo.py"))

    assert result.state == STATE_GATES_FAILED
    assert "src/foo.py" in result.error


def test_an_unusable_declaration_refuses_the_patch_and_says_why(repo, tmp_path):
    """Fail-closed BY DECISION, with the declaration named.

    An absolute declaration used to fail closed only because git's spelling
    could never equal it, so the operator was told the changed path was outside
    a boundary rather than that the boundary itself was unusable.
    """
    # Since 7d67d305 TaskSpec validates its declaration at construction
    # (TaskSpecInvalid), so the unusable boundary is refused BEFORE an attempt
    # exists -- earlier than the gate, with the same words.
    from daedalus.spine.attempt import TaskSpecInvalid

    with pytest.raises(TaskSpecInvalid) as refused:
        _run(repo, tmp_path, "absolute", target_paths=("C:/evil",),
             runner=_writer("src/foo.py"))

    assert "no normal form inside the tree" in str(refused.value)
    assert "'C:/evil'" in str(refused.value)


def test_no_declaration_leaves_the_attempt_unconstrained(repo, tmp_path):
    """The legacy/manual harness, unchanged: an empty scope binds nothing here.

    ``receipts.canonicalise_attempt`` is what refuses to mint a contract set for
    an unbounded scope; the containment gate itself must not start rejecting the
    manual path that never declared one.
    """
    result = _run(repo, tmp_path, "unbound", target_paths=(),
                  runner=_writer("anywhere.py"))

    assert result.state == STATE_CLEAN, result.error


# --------------------------------------------------------------------------- #
# 2. the comparison itself, on the spellings a repository can produce           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("changed,scope,escaped", [
    # the directory boundary, both ways
    ("tests/test_new.py", "tests", False),
    ("tests/deep/test_new.py", "tests", False),
    ("tests_evil.py", "tests", True),
    ("tests/ab.py", "tests/a", True),
    ("tests/a/b.py", "tests/a", False),
    # the declaration's own spellings settle to one form
    ("src/foo.py", "./src/foo.py", False),
    ("src/foo.py", "src\\foo.py", False),
    ("src/foo.py", "src/../src/foo.py", False),
    # A CHANGED path that is spelled oddly still fails closed. git does not
    # produce these today; a future producer that did must not walk out of the
    # boundary by spelling itself unrepresentably.
    ("../outside.py", "tests", True),
    ("C:/evil.py", "tests", True),
    ("/etc/passwd", "tests", True),
    ("tests/../tests_evil.py", "tests", True),
])
def test_containment_is_compared_on_segments_not_strings(changed, scope, escaped):
    result, declaration_error = containment_escapes((changed,), (scope,))

    assert declaration_error is None
    assert bool(result) is escaped
    if escaped:
        # Reported in the ORIGINAL spelling: that is what the operator has to
        # go and look at.
        assert result == (changed,)


@pytest.mark.parametrize("declaration", ["/abs/src", "C:/evil", "../outside"])
def test_a_declaration_with_no_normal_form_escapes_everything(declaration):
    escaped, declaration_error = containment_escapes(
        ("src/foo.py",), (declaration,))

    assert escaped == ("src/foo.py",)
    assert declaration_error is not None
    assert repr(declaration) in declaration_error


def test_the_containment_and_the_seal_read_one_declaration_the_same_way():
    """The asymmetry this file exists to remove, asserted as one statement.

    A directory declaration covering the criterion means the candidate MAY
    write the file that judges it. Containment must let that write through (it
    is inside the declared scope) and the seal must refuse it a
    ``deterministic`` verdict (it is inside the declared scope). Those are the
    same sentence about the same field, and before this change the first half
    said "escaped" while the second half said "inside".
    """
    from daedalus.spine.receipts import evaluator_assurance_detail

    escaped, declaration_error = containment_escapes(
        ("tests/test_gate.py",), ("tests",))
    assert escaped == () and declaration_error is None

    task = TaskSpec(task_id="both-halves", instruction="i",
                    base_revision="0" * 40, target_paths=("tests",),
                    gate_criterion_paths=("tests/test_gate.py",))
    result = type("R", (), {"gates": GateResult(
        passed=True, name="probe-gate",
        command=("pytest", "tests/test_gate.py"))})()

    verdict, why = evaluator_assurance_detail(
        result, task, criterion_present={"tests/test_gate.py": True},
        criterion_imports={"tests/test_gate.py": ()})

    assert verdict == "unverified"
    assert "INSIDE the declared write scope" in why
