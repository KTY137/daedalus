"""test_arm_random_search.py -- acceptance test C1 (G3-BASE-01 §5c).

Offline, no model calls. Verifies ``RandomSearchArm`` against the binding
rules in the packet: full budget only (no ``budget.split()``), determinism
given a seed, real stochasticity across seeds, never exceeding
``max_calls``, honest token-budget reporting (never a silent clip), and the
``error`` xor ``success``/``score`` contract for an ordinary failure.
"""
from __future__ import annotations

from daedalus.eval.gate3.arms.random_search import RandomSearchArm
from daedalus.eval.gate3.contracts import ArmBudget
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial


def _write_repo(tmp_path) -> str:
    (tmp_path / "alpha.py").write_text(
        "def alpha():\n"
        "    return 'alpha body carries the ALPHA_MARKER token'\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        "def beta():\n"
        "    return 'beta body carries the BETA_MARKER token'\n\n"
        "def beta_helper():\n"
        "    return 'helper body carries no marker at all'\n",
        encoding="utf-8",
    )
    (tmp_path / "gamma.py").write_text(
        "class Gamma:\n"
        "    def method(self):\n"
        "        return 'gamma body is plain, unmarked text'\n",
        encoding="utf-8",
    )
    return str(tmp_path)


def _score_fn(candidate: str, task: Task) -> float:
    # Gold marker held in this closure, never on the Task or the arm (plan §4
    # invariant 3: an arm cannot read its evaluator's internals).
    return float(candidate.count("BETA_MARKER"))


def _evaluator(max_calls: int | None = None) -> SealedEvaluator:
    return SealedEvaluator("beta_marker_count", _score_fn, max_calls=max_calls)


def _task(repo_root: str) -> Task:
    return Task(task_id="t-random-search", repo_root=repo_root,
                question="find the beta marker", target="beta.py",
                label_plane="code")


def test_arm_random_search_runs_and_produces_trial_result(tmp_path):
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_tokens=2000, max_calls=8)

    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=8), seed=1)

    assert result.error is None
    assert result.arm == "random_search"
    assert result.success is True
    assert result.score is not None
    assert result.tokens_used > 0


def test_arm_random_search_same_seed_is_deterministic(tmp_path):
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_tokens=2000, max_calls=8)

    r1 = run_trial(arm, _task(repo), budget, _evaluator(max_calls=8), seed=42)
    r2 = run_trial(arm, _task(repo), budget, _evaluator(max_calls=8), seed=42)

    assert r1.error is None and r2.error is None
    assert r1.score == r2.score
    assert r1.tokens_used == r2.tokens_used
    assert r1.calls == r2.calls


def test_arm_random_search_different_seeds_actually_differ(tmp_path):
    """Proves stochasticity is real, not a flag that lies: a fixed set of
    seeds must not collapse to one identical outcome."""
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_tokens=2000, max_calls=8)

    outcomes = set()
    for seed in range(1, 13):
        r = run_trial(arm, _task(repo), budget, _evaluator(max_calls=8), seed=seed)
        assert r.error is None
        outcomes.add((r.score, r.tokens_used))

    assert len(outcomes) > 1, (
        "random_search produced the identical outcome for every seed in "
        "1..12 -- it is not actually stochastic")


def test_arm_random_search_never_exceeds_max_calls(tmp_path):
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_calls=3)

    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=3), seed=7)

    assert result.error is None
    assert result.calls <= 3
    assert result.budget_exceeded is False


def test_arm_random_search_over_budget_is_reported_not_clipped(tmp_path):
    """A token budget too small for even one chunk must not be silently
    satisfied by truncating text mid-chunk -- it must show up as an honest
    overage that ``run_trial`` flags (packet rule R1 / test B4)."""
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_tokens=5, max_calls=6)

    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=6), seed=3)

    assert result.error is None
    assert result.tokens_used > 5
    assert result.budget_exceeded is True


def test_arm_random_search_errors_when_repo_has_no_chunks(tmp_path):
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    arm = RandomSearchArm()
    budget = ArmBudget(max_calls=4)

    result = run_trial(arm, _task(str(empty_repo)), budget, _evaluator(max_calls=4), seed=1)

    assert result.error is not None
    assert result.success is None
    assert result.score is None


def test_arm_random_search_never_calls_budget_split(tmp_path):
    """R1: an arm's own search never divides its budget across internal
    components. ``ArmBudget.split`` already raises unconditionally by
    contract (contracts.py) -- a normal run simply never triggers it."""
    repo = _write_repo(tmp_path)
    arm = RandomSearchArm()
    budget = ArmBudget(max_tokens=1000, max_calls=5)

    result = run_trial(arm, _task(repo), budget, _evaluator(max_calls=5), seed=9)

    assert result.error is None
