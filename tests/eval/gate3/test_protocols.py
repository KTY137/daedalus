"""Independent adversarial acceptance tests for daedalus/eval/gate3/protocols.py.

Packet G3-BASE-01, work-packet acceptance matrix §5b (B2, B4) and §5e (E1, E2,
E5). E3 (`test_stale_base_revision_refused`) and E6 (`test_no_network_in_
deterministic_arms`) are declared out of reach here: both need a real runner
and real arms that other agents in this session are still building (there is
no revision-check call site and no network-boundary enforcement point
anywhere in contracts.py/protocols.py to exercise) -- they are left as
explicit skips below rather than faked against nothing.

This file was written WITHOUT writing protocols.py -- that is deliberate.
Tests named ``*_BUG`` or ``*_SERIOUS_FINDING`` document real, executed,
reproduced defects via ``pytest.mark.xfail(strict=True, ...)`` or (where the
finding IS the exploit succeeding) a plain passing test that demonstrates the
successful breach. Nothing here fixes protocols.py.
"""
from __future__ import annotations

import copy

import pytest

from daedalus.eval.gate3.contracts import ArmBudget, FreezeError
from daedalus.eval.gate3.protocols import (
    ArmOutcome,
    SealedEvaluator,
    Task,
    run_arm_over_tasks,
    run_trial,
)


def _task(task_id: str = "t1") -> Task:
    return Task(task_id=task_id, repo_root="/repo", question="q", target="tgt",
                label_plane="code")


def _evaluator(fn=None, max_calls=None) -> SealedEvaluator:
    if fn is None:
        fn = lambda candidate, task: 1.0  # noqa: E731
    return SealedEvaluator("scorer", fn, max_calls=max_calls)


class _Arm:
    """A minimal, fully-controllable Arm implementation for exercising
    run_trial / run_arm_over_tasks without depending on any real baseline
    arm (those belong to other test files owned by other agents)."""

    def __init__(self, name="test_arm", stochastic=False, behavior=None):
        self.name = name
        self.stochastic = stochastic
        self._behavior = behavior or (lambda task, budget, evaluator, seed: ArmOutcome(
            candidate="c", score=1.0, success=True, tokens_used=1))

    def run(self, task, budget, evaluator, seed):
        return self._behavior(task, budget, evaluator, seed)


# --------------------------------------------------------------------------- #
# E1 -- an arm cannot read its evaluator                                     #
# --------------------------------------------------------------------------- #
def test_arm_cannot_read_evaluator():
    calls = {"n": 0}

    def fn(candidate, task):
        calls["n"] += 1
        return 3.0

    ev = _evaluator(fn=fn, max_calls=5)

    # The two capabilities that MUST work:
    assert ev.score("candidate", _task()) == 3.0
    assert ev.calls == 1
    assert calls["n"] == 1

    # Reads of anything else must be refused, LOUDLY -- and prove the refusal
    # actually fires for more than one made-up name (guard against a
    # hardcoded single-string check).
    for attr in ("_fn", "labels", "gold", "internal_state", "score_fn"):
        with pytest.raises(FreezeError, match="sealed"):
            getattr(ev, attr)

    # Writes must be refused.
    with pytest.raises(FreezeError, match="immutable"):
        ev.score = None
    with pytest.raises(FreezeError, match="immutable"):
        ev.calls = 999
    with pytest.raises(FreezeError, match="immutable"):
        del ev.score

    # copy.copy must be refused (explicit __copy__ override).
    with pytest.raises(FreezeError, match="not copyable"):
        copy.copy(ev)


def test_dunder_probes_miss_cleanly_instead_of_raising_freezeerror():
    """protocols.py explicitly carves out dunder lookups so Python's own
    optional-protocol probing (__copy__, __reduce__, hasattr checks, ...)
    gets a plain AttributeError/miss instead of turning an ordinary probe
    into a loud contract violation. Verify that carve-out actually works."""
    ev = _evaluator()
    assert hasattr(ev, "__len__") is False  # must miss quietly, not raise
    with pytest.raises(AttributeError):
        getattr(ev, "__some_totally_made_up_dunder__")


def test_evaluator_call_budget_is_enforced_and_cannot_be_reset_by_copying():
    def fn(candidate, task):
        return 1.0

    ev = _evaluator(fn=fn, max_calls=2)
    ev.score("a", _task())
    ev.score("b", _task())
    with pytest.raises(FreezeError, match="call budget exhausted"):
        ev.score("c", _task())

    # An arm cannot escape the exhausted budget by copying its handle either.
    with pytest.raises(FreezeError):
        copy.copy(ev)


def test_vars_does_not_expose_a_dict_for_a_sealed_evaluator():
    ev = _evaluator()
    with pytest.raises(TypeError):
        vars(ev)


# FIXED 2026-09-06: this defect was repaired in the integration pass;
# the xfail(strict=True) marker was removed so the test now guards the fix.
def test_private_slots_are_not_readable_via_plain_attribute_access_BUG():
    def fn(candidate, task):
        return 1.0

    ev = _evaluator(fn=fn)
    with pytest.raises(FreezeError):
        ev._score_impl  # noqa: B018 - deliberate attribute-read probe


# FIXED 2026-09-06: this defect was repaired in the integration pass;
# the xfail(strict=True) marker was removed so the test now guards the fix.
def test_deepcopy_is_refused_with_the_documented_freezeerror_BUG():
    ev = _evaluator()
    with pytest.raises(FreezeError, match="not copyable"):
        copy.deepcopy(ev)


# --------------------------------------------------------------------------- #
# E2 -- an arm never receives a FrozenTaskSet at all (structural, not just    #
# a runtime check) -- verify the Task/Arm contract shape enforces this.       #
# --------------------------------------------------------------------------- #
def test_arm_cannot_mutate_taskset():
    """An Arm's run() signature takes a Task (one item, no gold labels, no
    reference back to the FrozenTaskSet it came from) -- not the frozen set
    itself. Verify Task carries none of FrozenTaskSet's identity or the gold
    label, so there is nothing arm-reachable to mutate in the first place."""
    task = _task()
    assert not hasattr(task, "task_ids")
    assert not hasattr(task, "label_plane_census")
    assert not hasattr(task, "must_include")
    # Task itself is a frozen dataclass: even the one object an arm DOES
    # receive cannot be rewritten out from under the runner mid-trial.
    with pytest.raises(Exception):
        task.question = "rewritten by the arm"


# --------------------------------------------------------------------------- #
# B2 -- a composite arm declares its internal budget split                   #
# --------------------------------------------------------------------------- #
def test_composite_arm_declares_internal_split():
    """A composite arm (e.g. four separate indices, C8) must give each
    component the FULL budget (R1) and DECLARE the arrangement in its result
    row rather than hide it. ArmOutcome.notes / TrialResult.notes is exactly
    that declaration channel -- verify it survives run_trial unmodified."""
    split_declaration = {
        "components": ["code_index", "type_index", "data_index", "knowledge_index"],
        "per_component_budget": {"max_tokens": 1000, "max_calls": 8},
        "arrangement": "each component receives the full declared budget (R1)",
    }

    def behavior(task, budget, evaluator, seed):
        return ArmOutcome(candidate="c", score=1.0, success=True,
                          tokens_used=4000, notes=dict(split_declaration))

    arm = _Arm(name="four_separate_indices", behavior=behavior)
    result = run_trial(arm, _task(), ArmBudget(max_tokens=1000, max_calls=8),
                       _evaluator(max_calls=8), seed=1)

    assert result.error is None
    assert result.notes["components"] == split_declaration["components"]
    assert result.notes["per_component_budget"] == {"max_tokens": 1000, "max_calls": 8}


# FIXED 2026-09-06: this defect was repaired in the integration pass;
# the xfail(strict=True) marker was removed so the test now guards the fix.
def test_composite_arm_notes_are_a_copy_not_a_live_reference_BUG():
    """run_trial does `notes=dict(outcome.notes)` -- verify the TrialResult's
    notes are actually decoupled from the ArmOutcome's, so a caller mutating
    one cannot retroactively rewrite an already-recorded result row."""
    live_notes = {"per_component_budget": {"max_tokens": 100}}

    def behavior(task, budget, evaluator, seed):
        return ArmOutcome(candidate="c", success=True, score=1.0, notes=live_notes)

    arm = _Arm(behavior=behavior)
    result = run_trial(arm, _task(), ArmBudget(max_tokens=100), _evaluator(), seed=1)

    live_notes["per_component_budget"]["max_tokens"] = 999999
    assert result.notes["per_component_budget"]["max_tokens"] == 100, (
        "TrialResult.notes changed after the fact because it shares a nested "
        "dict with the ArmOutcome's notes -- run_trial's dict(outcome.notes) "
        "is only a shallow copy")


# --------------------------------------------------------------------------- #
# B4 -- budget overrun is reported, never clipped                            #
# --------------------------------------------------------------------------- #
def test_budget_overrun_is_reported_not_clipped():
    def behavior(task, budget, evaluator, seed):
        return ArmOutcome(candidate="c", success=True, score=1.0, tokens_used=50_000)

    arm = _Arm(behavior=behavior)
    tiny_budget = ArmBudget(max_tokens=10)
    result = run_trial(arm, _task(), tiny_budget, _evaluator(), seed=1)

    assert result.error is None
    assert result.budget_exceeded is True
    assert result.tokens_used == 50_000, (
        "an overrun must be reported at its true size, not silently clamped "
        "down to the declared budget")


def test_budget_overrun_is_detected_on_every_axis_independently():
    """Hunt for a vacuum: does budget_exceeded actually depend on EACH axis,
    or only on tokens? Check wall-time and calls independently."""
    slow = _Arm(behavior=lambda task, budget, evaluator, seed: (
        __import__("time").sleep(0.05) or ArmOutcome(success=True, score=1.0)))
    result = run_trial(slow, _task(), ArmBudget(max_wall_seconds=0.001), _evaluator(), seed=1)
    assert result.budget_exceeded is True

    def calls_heavy(task, budget, evaluator, seed):
        for _ in range(5):
            evaluator.score("x", task)
        return ArmOutcome(success=True, score=1.0)

    heavy = _Arm(behavior=calls_heavy)
    result2 = run_trial(heavy, _task(), ArmBudget(max_calls=1), _evaluator(max_calls=None), seed=1)
    assert result2.budget_exceeded is True
    assert result2.calls == 5, "calls must be the true count, not clipped to max_calls"


def test_within_budget_is_not_falsely_flagged_exceeded():
    """The other side of B4: an arm that stays within budget must not be
    reported as exceeded (guards against an inverted or always-True check)."""
    arm = _Arm(behavior=lambda task, budget, evaluator, seed: ArmOutcome(
        success=True, score=1.0, tokens_used=5))
    result = run_trial(arm, _task(), ArmBudget(max_tokens=1000, max_calls=10),
                       _evaluator(max_calls=10), seed=1)
    assert result.budget_exceeded is False


# --------------------------------------------------------------------------- #
# E5 -- a partial (killed) run is not reported as complete                   #
# --------------------------------------------------------------------------- #
def test_partial_run_is_not_reported_as_complete():
    """Simulate an external kill (a BaseException that is NOT a plain
    Exception, e.g. KeyboardInterrupt) partway through a multi-task batch.
    run_arm_over_tasks must not swallow it into a result list that LOOKS
    like a complete run -- it must propagate, so no caller can mistake a cut
    -short batch for a finished one."""
    progress = {"n": 0}

    def behavior(task, budget, evaluator, seed):
        progress["n"] += 1
        if progress["n"] == 2:
            raise KeyboardInterrupt("simulated external kill")
        return ArmOutcome(candidate="c", success=True, score=1.0, tokens_used=1)

    arm = _Arm(behavior=behavior)
    tasks = [_task(f"t{i}") for i in range(4)]

    with pytest.raises(KeyboardInterrupt):
        run_arm_over_tasks(arm, tasks, ArmBudget(max_tokens=10),
                           lambda: _evaluator(), seeds=[1])

    assert progress["n"] == 2, "the kill must interrupt mid-batch, not after it"


def test_ordinary_arm_failure_is_not_treated_as_a_kill():
    """The counterpart check: an ORDINARY exception (a real Exception
    subclass, not a kill signal) from one task must become an errored
    TrialResult and let the batch continue -- distinguishing 'this task
    failed' from 'the run was killed' is the whole point of E5."""
    def behavior(task, budget, evaluator, seed):
        if task.task_id == "t1":
            raise RuntimeError("ordinary failure on this task only")
        return ArmOutcome(candidate="c", success=True, score=1.0, tokens_used=1)

    arm = _Arm(behavior=behavior)
    tasks = [_task("t0"), _task("t1"), _task("t2")]
    results = run_arm_over_tasks(arm, tasks, ArmBudget(max_tokens=10),
                                  lambda: _evaluator(), seeds=[1])

    assert len(results) == 3, "an ordinary per-task failure must not abort the batch"
    by_task = {r.task_id: r for r in results}
    assert by_task["t1"].error is not None
    assert by_task["t1"].success is None
    assert by_task["t0"].error is None and by_task["t0"].success is True
    assert by_task["t2"].error is None and by_task["t2"].success is True


def test_freezeerror_from_an_arm_is_never_swallowed_into_a_result_row():
    """A contract violation (e.g. an arm calling budget.split()) must be
    loud -- run_trial must re-raise FreezeError, never launder it into an
    ordinary errored TrialResult that looks like a mundane failure."""
    def behavior(task, budget, evaluator, seed):
        budget.split(4)  # the exact s08 defect, attempted from inside an arm
        return ArmOutcome(success=True, score=1.0)

    arm = _Arm(behavior=behavior)
    with pytest.raises(FreezeError, match="refused"):
        run_trial(arm, _task(), ArmBudget(max_tokens=10), _evaluator(), seed=1)


# --------------------------------------------------------------------------- #
# run_trial / run_arm_over_tasks: additional contract exercises              #
# --------------------------------------------------------------------------- #
def test_run_trial_requires_an_explicit_verdict_or_error():
    """An ArmOutcome with neither success nor error must be refused loudly,
    not silently defaulted to success or failure."""
    arm = _Arm(behavior=lambda task, budget, evaluator, seed: ArmOutcome())
    with pytest.raises(FreezeError, match="neither success nor error"):
        run_trial(arm, _task(), ArmBudget(max_tokens=10), _evaluator(), seed=1)


def test_arm_outcome_rejects_negative_tokens():
    with pytest.raises(FreezeError, match="negative"):
        ArmOutcome(success=True, score=1.0, tokens_used=-1)


def test_run_arm_over_tasks_rejects_empty_seed_list():
    arm = _Arm()
    with pytest.raises(FreezeError, match="no seeds"):
        run_arm_over_tasks(arm, [_task()], ArmBudget(max_tokens=10), lambda: _evaluator(), seeds=[])


def test_run_arm_over_tasks_uses_a_fresh_evaluator_per_trial():
    """The docstring claims a FRESH evaluator per (task, seed) pair so call
    budgets cannot leak across trials. Verify it directly: count how many
    times the factory is invoked and confirm no trial inherits another
    trial's call count."""
    built = {"n": 0}

    def factory():
        built["n"] += 1
        return _evaluator(max_calls=1)

    def behavior(task, budget, evaluator, seed):
        evaluator.score("c", task)  # exactly one call per trial
        return ArmOutcome(success=True, score=1.0)

    arm = _Arm(behavior=behavior)
    tasks = [_task("t0"), _task("t1")]
    results = run_arm_over_tasks(arm, tasks, ArmBudget(max_calls=1), factory, seeds=[1, 2])

    assert built["n"] == len(tasks) * 2, "one fresh evaluator per (task, seed) pair"
    assert all(r.calls == 1 for r in results), (
        "a leaked call count would show up as >1 for a later trial")


def test_run_arm_over_tasks_covers_the_full_task_by_seed_cross_product():
    arm = _Arm()
    tasks = [_task("t0"), _task("t1"), _task("t2")]
    seeds = [10, 20]
    results = run_arm_over_tasks(arm, tasks, ArmBudget(max_tokens=10), lambda: _evaluator(), seeds)

    assert len(results) == len(tasks) * len(seeds) == 6
    pairs = {(r.task_id, r.seed) for r in results}
    assert pairs == {(t.task_id, s) for t in tasks for s in seeds}


# --------------------------------------------------------------------------- #
# E3 / E6 -- explicitly out of reach in this file (see module docstring)     #
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason=(
    "E3 needs a runner that compares a RunManifest.base_revision against the "
    "live tree's actual git revision. contracts.py/protocols.py have no such "
    "call site (RunManifest.base_revision is an opaque, caller-supplied "
    "string with only a non-blank check -- see test_manifest_requires_non_"
    "blank_revision_and_plan_digest in test_contracts.py). That comparison "
    "belongs to whichever module runs a real Mission against a real repo; it "
    "does not exist yet in the two files this test suite owns."
))
def test_stale_base_revision_refused():
    ...


@pytest.mark.skip(reason=(
    "E6 needs a real network-boundary enforcement point (e.g. a monkeypatched "
    "socket/urllib guard around a deterministic arm's run()). protocols.py's "
    "Arm/run_trial contract does not itself open or forbid network access -- "
    "that is a property of each concrete arm implementation (BM25, embeddings, "
    "...), which other agents in this session own. Nothing in the two files "
    "this suite covers can be exercised for this claim without importing a "
    "concrete arm module out of scope here."
))
def test_no_network_in_deterministic_arms():
    ...
