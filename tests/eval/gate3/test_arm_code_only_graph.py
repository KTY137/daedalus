"""Tests for the Gate-3 code-only-graph baseline arm (packet G3-BASE-01,
acceptance C7).

Deterministic, offline, no network, no model calls. Real temp-directory
repositories (not mocks), because this arm's whole point is structural graph
traversal over real files -- mocking the filesystem would test nothing.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.arms import code_only_graph as arm_module
from daedalus.eval.gate3.arms.code_only_graph import CodeOnlyGraphArm
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial


def _recall_evaluator(marker: str, max_calls: int | None = None) -> SealedEvaluator:
    def score_fn(candidate: str, task: Task) -> float:
        return 1.0 if marker in candidate else 0.0

    return SealedEvaluator("test-recall", score_fn, max_calls=max_calls)


def _task(repo: Path, target: str, question: str = "") -> Task:
    return Task(task_id="t1", repo_root=str(repo), question=question,
               target=target, label_plane="code")


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
def _write_graph_repo(tmp_path: Path) -> Path:
    """focus.py calls neighbor.helper() (a real, name-resolvable call edge) and
    imports it; distant.py shares no identifier with focus.py at all, so it
    stays graph-unreachable from focus. Also carries a markdown doc and a CSV
    data file -- neither may leak into a code-only arm's context."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "focus.py").write_text(
        "import neighbor\n\n"
        "def entry():\n"
        '    """Entry point, calls the neighbor module."""\n'
        "    return neighbor.helper()\n",
        encoding="utf-8",
    )
    (repo / "neighbor.py").write_text(
        "def helper():\n"
        '    """NEIGHBOR_MARKER: the directly-called/imported unit."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (repo / "distant.py").write_text(
        "def unrelated():\n"
        '    """DISTANT_MARKER: shares no name with focus.py or neighbor.py."""\n'
        "    return 2\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# MARKDOWN_SENTINEL\nThis document must never appear in a code-only context.\n",
        encoding="utf-8",
    )
    (repo / "data.csv").write_text("CSV_SENTINEL,value\n1,2\n", encoding="utf-8")
    return repo


def _write_inheritance_repo(tmp_path: Path) -> Path:
    """child.py's class inherits from base.py's class -- the one relation this
    arm resolves via a Python-syntax regex, not a shared import/call name."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "base.py").write_text(
        "class Base:\n"
        "    def greet(self):\n"
        '        """BASE_MARKER"""\n'
        "        return 'base'\n",
        encoding="utf-8",
    )
    (repo / "child.py").write_text(
        "from base import Base\n\n"
        "class Child(Base):\n"
        "    def specialize(self):\n"
        '        """CHILD_MARKER"""\n'
        "        return 'child'\n",
        encoding="utf-8",
    )
    (repo / "distant.py").write_text(
        "def unrelated():\n"
        '    """DISTANT_MARKER2"""\n'
        "    return 0\n",
        encoding="utf-8",
    )
    return repo


# --------------------------------------------------------------------------- #
# C7: produces a TrialResult via run_trial                                    #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_produces_trial_result(tmp_path: Path) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("NEIGHBOR_MARKER")
    task = _task(repo, "focus.py::entry")

    trial = run_trial(arm, task, budget, evaluator, seed=0)

    assert trial.arm == "code_only_graph"
    assert trial.error is None
    assert trial.success is True
    assert trial.measured is True


# --------------------------------------------------------------------------- #
# code-plane only: no markdown/CSV content ever reaches the context           #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_excludes_non_code_planes(tmp_path: Path) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=100_000)  # generous: include the whole corpus
    evaluator = _recall_evaluator("NEIGHBOR_MARKER")
    task = _task(repo, "focus.py::entry")

    outcome = arm.run(task, budget, evaluator, seed=0)

    assert outcome.error is None
    assert "MARKDOWN_SENTINEL" not in outcome.candidate
    assert "CSV_SENTINEL" not in outcome.candidate
    # sanity: the code files ARE in there, so the exclusion is a real filter,
    # not an accidentally empty candidate
    assert "NEIGHBOR_MARKER" in outcome.candidate
    assert "DISTANT_MARKER" in outcome.candidate


# --------------------------------------------------------------------------- #
# graph proximity actually orders results                                     #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_ranks_direct_neighbour_above_distant_file(
    tmp_path: Path,
) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    # A tight budget that fits the focus file + neighbor.py but not everything.
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("NEIGHBOR_MARKER")
    task = _task(repo, "focus.py::entry")

    outcome = arm.run(task, budget, evaluator, seed=0)

    assert outcome.error is None
    neighbor_pos = outcome.candidate.find("NEIGHBOR_MARKER")
    distant_pos = outcome.candidate.find("DISTANT_MARKER")
    assert neighbor_pos != -1, "directly-called neighbor must be included"
    if distant_pos == -1:
        return  # neighbor included, distant excluded -- proximity ordering held
    assert neighbor_pos < distant_pos, (
        "the directly-imported/called neighbour must rank (and therefore "
        "appear) before the unrelated distant file")


def test_arm_code_only_graph_ranks_inheritance_neighbour_above_distant_file(
    tmp_path: Path,
) -> None:
    repo = _write_inheritance_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("CHILD_MARKER")
    task = _task(repo, "child.py::specialize")

    outcome = arm.run(task, budget, evaluator, seed=0)

    assert outcome.error is None
    base_pos = outcome.candidate.find("BASE_MARKER")
    distant_pos = outcome.candidate.find("DISTANT_MARKER2")
    assert base_pos != -1, "the inherited base class's file must be included"
    if distant_pos == -1:
        return
    assert base_pos < distant_pos


# --------------------------------------------------------------------------- #
# determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_deterministic_across_seeds(tmp_path: Path) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    assert arm.stochastic is False
    budget = ArmBudget(max_tokens=10_000)

    out_a = arm.run(_task(repo, "focus.py::entry"), budget,
                    _recall_evaluator("NEIGHBOR_MARKER"), seed=1)
    out_b = arm.run(_task(repo, "focus.py::entry"), budget,
                    _recall_evaluator("NEIGHBOR_MARKER"), seed=999)

    assert out_a.candidate == out_b.candidate
    assert out_a.score == out_b.score
    assert out_a.success == out_b.success
    assert out_a.tokens_used == out_b.tokens_used
    assert out_a.notes == out_b.notes


def test_arm_code_only_graph_stable_ordering_across_repeated_runs(
    tmp_path: Path,
) -> None:
    """Same run, repeated in-process: byte-identical output regardless of
    dict/set iteration order (no PYTHONHASHSEED dependence)."""
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    task = _task(repo, "focus.py::entry")

    out_1 = arm.run(task, budget, _recall_evaluator("NEIGHBOR_MARKER"), seed=0)
    out_2 = arm.run(task, budget, _recall_evaluator("NEIGHBOR_MARKER"), seed=0)

    assert out_1.candidate == out_2.candidate
    assert out_1.notes == out_2.notes


# --------------------------------------------------------------------------- #
# budget                                                                       #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_respects_token_budget(tmp_path: Path) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    evaluator = _recall_evaluator("NEIGHBOR_MARKER")
    task = _task(repo, "focus.py::entry")

    tiny = arm.run(task, ArmBudget(max_tokens=1), evaluator, seed=0)
    assert tiny.error is None
    assert tiny.notes["n_units_used"] == 1  # budget of 1 admits only the top rank

    generous = arm.run(task, ArmBudget(max_tokens=100_000), evaluator, seed=0)
    assert generous.error is None
    assert generous.notes["n_units_used"] > tiny.notes["n_units_used"]
    assert generous.tokens_used >= tiny.tokens_used
    assert generous.notes["truncated"] is False
    assert tiny.notes["n_units_total"] == generous.notes["n_units_total"]


# --------------------------------------------------------------------------- #
# R1: never split the budget                                                   #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_never_splits_budget(tmp_path: Path) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    evaluator = _recall_evaluator("NEIGHBOR_MARKER")
    task = _task(repo, "focus.py::entry")

    class WatchedBudget(ArmBudget):
        def split(self, n):  # pragma: no cover - must never be called
            raise AssertionError("ArmBudget.split() must never be called (rule R1)")

    budget = WatchedBudget(max_tokens=10_000)
    outcome = arm.run(task, budget, evaluator, seed=0)
    assert outcome.error is None


# --------------------------------------------------------------------------- #
# does not import experiments.forest_v2                                       #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_does_not_import_forest_v2() -> None:
    source = inspect.getsource(arm_module)
    assert "forest_v2" not in source
    assert not any("forest_v2" in (getattr(m, "__name__", "") or "")
                  for m in vars(arm_module).values() if inspect.ismodule(m))


# --------------------------------------------------------------------------- #
# ordinary failure -> ArmOutcome(error=...), never a raised exception          #
# --------------------------------------------------------------------------- #
def test_arm_code_only_graph_missing_target_yields_error_outcome(
    tmp_path: Path,
) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    task = _task(repo, "does_not_exist.py::nope")

    outcome = arm.run(task, budget, _recall_evaluator("NEIGHBOR_MARKER"), seed=0)

    assert outcome.error is not None
    assert outcome.success is None
    assert outcome.score is None


def test_arm_code_only_graph_errored_trial_has_no_score_or_success(
    tmp_path: Path,
) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    task = _task(repo, "does_not_exist.py::nope")

    trial = run_trial(arm, task, budget, _recall_evaluator("NEIGHBOR_MARKER"), seed=0)

    assert trial.error is not None
    assert trial.success is None
    assert trial.score is None
    assert trial.measured is False


def test_arm_code_only_graph_empty_repo_yields_error_outcome(tmp_path: Path) -> None:
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# only docs here\n", encoding="utf-8")

    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    task = _task(repo, "README.md")

    outcome = arm.run(task, budget, _recall_evaluator("x"), seed=0)

    assert outcome.error is not None
    assert outcome.success is None


def test_arm_code_only_graph_evaluator_contract_violation_still_raises(
    tmp_path: Path,
) -> None:
    repo = _write_graph_repo(tmp_path)
    arm = CodeOnlyGraphArm()
    budget = ArmBudget(max_tokens=10_000)
    evaluator = _recall_evaluator("NEIGHBOR_MARKER", max_calls=0)
    task = _task(repo, "focus.py::entry")

    with pytest.raises(FreezeError):
        arm.run(task, budget, evaluator, seed=0)
