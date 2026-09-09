"""Tests for daedalus.eval.gate3.runner (packet G3-BASE-01).

Uses small fake arms defined entirely in this file -- never the real arms
under ``daedalus/eval/gate3/arms/``, which are being built concurrently by
other work in this packet. Fast, offline, deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import pytest

from daedalus.eval.gate3.contracts import (
    ArmBudget,
    EvaluatorVersion,
    FreezeError,
    FrozenTaskSet,
    RunEnvironment,
    RunManifest,
    SeedPolicy,
)
from daedalus.eval.gate3.protocols import ArmOutcome, SealedEvaluator, Task
from daedalus.eval.gate3.runner import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    run_comparison,
    verify_base_revision,
)


# --------------------------------------------------------------------------- #
# fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #

def _tasks(n: int = 2) -> list[Task]:
    return [
        Task(task_id=f"t{i}", repo_root=".", question=f"q{i}", target=f"target{i}")
        for i in range(n)
    ]


def _env() -> RunEnvironment:
    return RunEnvironment(tokenizer="cl100k_base", os_name="test-os", cpu="test-cpu", ram_gb=16.0)


def _taskset(n: int = 2) -> FrozenTaskSet:
    ids = tuple(f"t{i}" for i in range(n))
    return FrozenTaskSet(
        name="fixture-set", task_ids=ids, counting_rule="count all tasks",
        label_plane_census={"code": n},
    )


def _evaluator_version() -> EvaluatorVersion:
    return EvaluatorVersion(name="fixture-eval", version="0.0.1", code_digest="a" * 64)


def _manifest(
    budgets: Mapping[str, ArmBudget],
    seed_policy: SeedPolicy | None = None,
    base_revision: str = "0123456789abcdef",
    n_tasks: int = 2,
) -> RunManifest:
    return RunManifest(
        task_set=_taskset(n_tasks),
        evaluator=_evaluator_version(),
        budgets=dict(budgets),
        environment=_env(),
        seed_policy=seed_policy or SeedPolicy(seeds=(1,), deterministic=True),
        base_revision=base_revision,
        plan_digest="f" * 64,
    )


def _evaluator_factory():
    def _make() -> SealedEvaluator:
        return SealedEvaluator("fixture", lambda candidate, task: 1.0)
    return _make


@dataclass
class FakeArm:
    """A minimal Arm: succeeds every call, scores via the evaluator."""

    name: str
    stochastic: bool = False
    calls: list[tuple[str, int]] = field(default_factory=list)

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator, seed: int) -> ArmOutcome:
        self.calls.append((task.task_id, seed))
        score = evaluator.score("candidate", task)
        return ArmOutcome(candidate="candidate", score=score, success=True, tokens_used=1)


@dataclass
class DyingArm:
    """Raises on its very first invocation -- simulates an arm dying mid-run."""

    name: str
    stochastic: bool = False
    exc: BaseException = None  # type: ignore[assignment]

    def run(self, task: Task, budget: ArmBudget, evaluator: SealedEvaluator, seed: int) -> ArmOutcome:
        raise self.exc


# --------------------------------------------------------------------------- #
# budget equality (R1 / B1)                                                   #
# --------------------------------------------------------------------------- #

def test_unequal_budgets_refused_at_manifest_construction():
    """A comparison between unequally-budgeted arms measures the budget, not
    the method (plan §4 invariant 9), so it must never be constructible."""
    with pytest.raises(FreezeError):
        _manifest({"a": ArmBudget(max_calls=5), "b": ArmBudget(max_calls=99)})


def test_manifest_budgets_cannot_be_mutated_after_construction():
    """FIXED 2026-09-06. This test previously mutated ``manifest.budgets``
    after construction to simulate the gap ``run_comparison`` had to re-check
    independently. ``RunManifest`` now defensively copies the mapping behind a
    read-only proxy, so the gap is closed at the contract instead of being
    patched over by every consumer: the mutation itself is refused.
    """
    budgets = {"a": ArmBudget(max_calls=5), "b": ArmBudget(max_calls=5)}
    manifest = _manifest(budgets)

    with pytest.raises(TypeError):
        manifest.budgets["b"] = ArmBudget(max_calls=99)  # type: ignore[index]

    # mutating the caller's ORIGINAL dict must not reach the manifest either
    budgets["b"] = ArmBudget(max_calls=99)
    assert manifest.budgets["b"].max_calls == 5
    assert manifest.arms == ("a", "b")

    arm_a = FakeArm(name="a")
    run_comparison([arm_a], _tasks(), manifest, _evaluator_factory())
    assert arm_a.calls, "an equal-budget comparison must still run normally"


def test_arm_without_declared_budget_refused_before_running():
    manifest = _manifest({"a": ArmBudget(max_calls=5)})
    stray = FakeArm(name="not-in-manifest")
    with pytest.raises(FreezeError):
        run_comparison([stray], _tasks(), manifest, _evaluator_factory())
    assert stray.calls == []


# --------------------------------------------------------------------------- #
# stochastic vs deterministic seed handling                                   #
# --------------------------------------------------------------------------- #

def test_stochastic_arm_runs_every_seed_deterministic_arm_runs_once():
    seeds = (1, 2, 3, 4, 5)
    budgets = {"det": ArmBudget(max_calls=10), "stoch": ArmBudget(max_calls=10)}
    manifest = _manifest(budgets, seed_policy=SeedPolicy(seeds=seeds, deterministic=False), n_tasks=2)

    det = FakeArm(name="det", stochastic=False)
    stoch = FakeArm(name="stoch", stochastic=True)

    result = run_comparison([det, stoch], _tasks(2), manifest, _evaluator_factory())

    assert result.status == STATUS_COMPLETE
    # deterministic arm: one seed x 2 tasks = 2 trials, using the policy's
    # first seed only
    assert len(result.trials_by_arm["det"]) == 2
    assert {t.seed for t in result.trials_by_arm["det"]} == {seeds[0]}
    # stochastic arm: every seed x 2 tasks = 10 trials
    assert len(result.trials_by_arm["stoch"]) == 2 * len(seeds)
    assert {t.seed for t in result.trials_by_arm["stoch"]} == set(seeds)


def test_stochastic_arm_refused_when_seed_policy_has_too_few_seeds():
    # A manifest-level deterministic SeedPolicy (one seed) paired with an arm
    # that itself claims to be stochastic is exactly the mismatch that must
    # not be silently downgraded to a single-seed run.
    manifest = _manifest({"stoch": ArmBudget(max_calls=10)},
                         seed_policy=SeedPolicy(seeds=(7,), deterministic=True))
    stoch = FakeArm(name="stoch", stochastic=True)
    with pytest.raises(FreezeError):
        run_comparison([stoch], _tasks(), manifest, _evaluator_factory())
    assert stoch.calls == []


# --------------------------------------------------------------------------- #
# E3: stale base revision refused                                             #
# --------------------------------------------------------------------------- #

def test_stale_base_revision_refused(tmp_path: Path):
    manifest = _manifest({"a": ArmBudget(max_calls=1)},
                         base_revision="deadbeefdeadbeefdeadbeef")
    # This test file's own directory is inside the git worktree checkout, so
    # `git rev-parse HEAD` here resolves the tree's real current revision --
    # which cannot equal the fabricated "deadbeef..." value above.
    with pytest.raises(FreezeError):
        verify_base_revision(manifest, Path(__file__).resolve().parent)


def test_matching_base_revision_is_accepted():
    import subprocess
    repo_dir = Path(__file__).resolve().parent
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir),
                          capture_output=True, text=True, check=True)
    current = proc.stdout.strip()
    manifest = _manifest({"a": ArmBudget(max_calls=1)}, base_revision=current)
    verify_base_revision(manifest, repo_dir)  # must not raise


def test_stale_base_revision_refused_cleanly_for_non_git_dir(tmp_path: Path):
    manifest = _manifest({"a": ArmBudget(max_calls=1)}, base_revision="0123456789ab")
    with pytest.raises(FreezeError):
        verify_base_revision(manifest, tmp_path)


# --------------------------------------------------------------------------- #
# E5: partial run is not reported as complete                                 #
# --------------------------------------------------------------------------- #

def test_partial_run_is_not_reported_as_complete():
    budgets = {"aaa_ok": ArmBudget(max_calls=5),
              "bbb_dies": ArmBudget(max_calls=5),
              "ccc_never_starts": ArmBudget(max_calls=5)}
    manifest = _manifest(budgets, n_tasks=2)

    ok = FakeArm(name="aaa_ok")
    dies = DyingArm(name="bbb_dies", exc=KeyboardInterrupt())
    never = FakeArm(name="ccc_never_starts")

    result = run_comparison([never, dies, ok], _tasks(2), manifest, _evaluator_factory())

    assert result.status == STATUS_PARTIAL
    assert result.partial_reason is not None and "KeyboardInterrupt" in result.partial_reason

    # arm sorted first ("aaa_ok") completed all of its cells before the death
    assert len(result.trials_by_arm["aaa_ok"]) == 2
    # the dying arm produced no TrialResult at all
    assert result.trials_by_arm["bbb_dies"] == ()
    # the arm sorted after the dying one never even started
    assert result.trials_by_arm["ccc_never_starts"] == ()
    assert never.calls == []

    # every cell belonging to the dying arm and the never-started arm is
    # explicitly named as unrun -- 2 tasks x 1 seed each = 4 cells
    unrun_arms = {cell[0] for cell in result.unrun_cells}
    assert unrun_arms == {"bbb_dies", "ccc_never_starts"}
    assert len(result.unrun_cells) == 4
    assert "aaa_ok" not in unrun_arms

    # evidence_status is still carried on a partial result
    assert "UNSEALED" in result.evidence_status


def test_partial_result_cannot_be_constructed_as_complete_with_unrun_cells():
    from daedalus.eval.gate3.runner import ComparisonResult
    manifest = _manifest({"a": ArmBudget(max_calls=1)})
    with pytest.raises(FreezeError):
        ComparisonResult(
            manifest=manifest, trials_by_arm={"a": ()},
            status=STATUS_COMPLETE, evidence_status=manifest.evidence_status(),
            unrun_cells=(("a", "t0", 1),),
        )


def test_freeze_error_from_arm_also_produces_partial():
    # A FreezeError (contract breach) must escape run_trial just like
    # KeyboardInterrupt does, and must also be reported as partial, not
    # raised out of run_comparison.
    budgets = {"dies": ArmBudget(max_calls=5)}
    manifest = _manifest(budgets, n_tasks=1)
    dies = DyingArm(name="dies", exc=FreezeError("sealed evaluator breach"))
    result = run_comparison([dies], _tasks(1), manifest, _evaluator_factory())
    assert result.status == STATUS_PARTIAL
    assert "FreezeError" in result.partial_reason
    assert len(result.unrun_cells) == 1


# --------------------------------------------------------------------------- #
# evidence status propagation                                                 #
# --------------------------------------------------------------------------- #

def test_unsealed_manifest_result_carries_unsealed_evidence_status():
    manifest = _manifest({"a": ArmBudget(max_calls=5)})
    assert manifest.owner_seal_ref is None
    arm = FakeArm(name="a")
    result = run_comparison([arm], _tasks(1), manifest, _evaluator_factory())
    assert result.status == STATUS_COMPLETE
    assert result.evidence_status == manifest.evidence_status()
    assert result.evidence_status.startswith("UNSEALED")


def test_seal_claim_is_reported_as_unverified_never_as_sealed():
    manifest = RunManifest(
        task_set=_taskset(1), evaluator=_evaluator_version(),
        budgets={"a": ArmBudget(max_calls=5)}, environment=_env(),
        seed_policy=SeedPolicy(seeds=(1,), deterministic=True),
        base_revision="0123456789abcdef", plan_digest="f" * 64,
        owner_seal_ref="owner-approved-2026-09-06",
    )
    arm = FakeArm(name="a")
    result = run_comparison([arm], _tasks(1), manifest, _evaluator_factory())
    # FIXED 2026-09-06: a manifest can no longer report itself as sealed. This
    # test used to assert that a bare owner_seal_ref string produced a "sealed
    # run" status -- i.e. it encoded the forgery. Sealing requires an
    # authenticated one-use OwnerApproval that this package cannot reach, so
    # the honest status is UNSEALED with the claim reported as unverified.
    assert result.evidence_status.startswith("UNSEALED run")
    assert "UNVERIFIED seal claim" in result.evidence_status
    assert "NOT Gate-3 baseline evidence" in result.evidence_status


# --------------------------------------------------------------------------- #
# fresh evaluator per trial                                                   #
# --------------------------------------------------------------------------- #

def test_fresh_evaluator_per_trial_call_counts_do_not_leak():
    created: list[SealedEvaluator] = []

    def factory() -> SealedEvaluator:
        ev = SealedEvaluator("fixture", lambda candidate, task: 1.0)
        created.append(ev)
        return ev

    budgets = {"a": ArmBudget(max_calls=1)}
    manifest = _manifest(budgets, n_tasks=3, seed_policy=SeedPolicy(seeds=(1,), deterministic=True))
    arm = FakeArm(name="a")

    result = run_comparison([arm], _tasks(3), manifest, factory)

    assert result.status == STATUS_COMPLETE
    n_trials = len(result.trials_by_arm["a"])
    assert n_trials == 3
    # one fresh evaluator instance created per trial, no sharing
    assert len(created) == n_trials
    assert len({id(e) for e in created}) == n_trials
    # each evaluator was called exactly once (the arm calls .score() once)
    assert all(ev.calls == 1 for ev in created)


# --------------------------------------------------------------------------- #
# deterministic arm ordering                                                  #
# --------------------------------------------------------------------------- #

def test_arm_output_order_is_sorted_by_name():
    budgets = {"zeta": ArmBudget(max_calls=5), "alpha": ArmBudget(max_calls=5)}
    manifest = _manifest(budgets, n_tasks=1)
    zeta = FakeArm(name="zeta")
    alpha = FakeArm(name="alpha")
    result = run_comparison([zeta, alpha], _tasks(1), manifest, _evaluator_factory())
    assert list(result.all_trials)[0].arm == "alpha"
    assert list(result.all_trials)[-1].arm == "zeta"


# --------------------------------------------------------------------------- #
# optional prepare() hook: called once, untimed, before an arm's trials       #
# --------------------------------------------------------------------------- #

def test_optional_prepare_hook_called_once_before_trials():
    prep_calls: list[int] = []

    @dataclass
    class ArmWithPrepare:
        name: str = "with-prepare"
        stochastic: bool = False

        def prepare(self, tasks) -> None:
            prep_calls.append(len(list(tasks)))

        def run(self, task, budget, evaluator, seed) -> ArmOutcome:
            assert prep_calls, "prepare() must run before any trial"
            return ArmOutcome(success=True, score=1.0, tokens_used=1)

    manifest = _manifest({"with-prepare": ArmBudget(max_calls=5)}, n_tasks=3)
    result = run_comparison([ArmWithPrepare()], _tasks(3), manifest, _evaluator_factory())
    assert result.status == STATUS_COMPLETE
    assert prep_calls == [3]  # called exactly once, with all 3 tasks
