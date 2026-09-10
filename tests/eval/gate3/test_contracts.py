"""Independent adversarial acceptance tests for daedalus/eval/gate3/contracts.py.

Packet G3-BASE-01, work-packet acceptance matrix §5a (A1-A7), §5b (B1, B3),
and the §5e refusal E2/E4 that live in the contracts module (``FrozenTaskSet``
and ``SeedPolicy``). This file was written WITHOUT writing contracts.py --
that is deliberate (see the packet). It does not import anything from
``daedalus.eval.gate3.protocols`` on purpose: this file exercises the six
freeze-obligation dataclasses in isolation.

Any test named ``*_BUG`` documents a real, executed, reproduced defect in
contracts.py via ``pytest.mark.xfail(strict=True, ...)``. It does not fix the
defect (forbidden by the task); it makes the defect visible and durable: if
someone silently "fixes" the behaviour without removing the xfail marker,
``strict=True`` turns that into a loud failure (XPASS) instead of a silent
pass.
"""
from __future__ import annotations

import pytest

from daedalus.eval.gate3.contracts import (
    ArmBudget,
    EvaluatorVersion,
    FreezeError,
    FrozenTaskSet,
    RunEnvironment,
    RunManifest,
    SeedPolicy,
    require_equal_budgets,
)


def _taskset(**overrides) -> FrozenTaskSet:
    kwargs = dict(
        name="voltage-rename-v1",
        task_ids=("t1", "t2", "t3"),
        counting_rule="count(tasks where gold_label_found)",
        label_plane_census={"code": 2, "knowledge": 1},
    )
    kwargs.update(overrides)
    return FrozenTaskSet(**kwargs)


def _evaluator(**overrides) -> EvaluatorVersion:
    kwargs = dict(name="voltage_rename_scorer", version="1.0.0", code_digest="a" * 64)
    kwargs.update(overrides)
    return EvaluatorVersion(**kwargs)


def _environment(**overrides) -> RunEnvironment:
    kwargs = dict(tokenizer="cl100k_base", os_name="Windows-11", cpu="x86_64", ram_gb=32.0)
    kwargs.update(overrides)
    return RunEnvironment(**kwargs)


def _manifest(**overrides) -> RunManifest:
    kwargs = dict(
        task_set=_taskset(),
        evaluator=_evaluator(),
        budgets={"arm_a": ArmBudget(max_tokens=1000), "arm_b": ArmBudget(max_tokens=1000)},
        environment=_environment(),
        seed_policy=SeedPolicy(seeds=(1,), deterministic=True),
        base_revision="1ba5b66f",
        plan_digest="f" * 64,
    )
    kwargs.update(overrides)
    return RunManifest(**kwargs)


# --------------------------------------------------------------------------- #
# A1 -- digest stability                                                      #
# --------------------------------------------------------------------------- #
def test_frozen_taskset_digest_is_stable():
    a = _taskset()
    b = _taskset()
    assert a.digest == b.digest, "identical inputs must produce the identical digest"

    # Every field independently perturbs the digest -- prove each one actually
    # matters, not just that *some* combination differs (a vacuum risk: a
    # digest that ignores a field would still pass a single blunt comparison).
    assert _taskset(name="different-name").digest != a.digest
    assert _taskset(task_ids=("t1", "t2", "t3", "t4"),
                     label_plane_census={"code": 2, "knowledge": 2}).digest != a.digest
    assert _taskset(counting_rule="a different rule entirely").digest != a.digest
    assert _taskset(label_plane_census={"code": 3}).digest != a.digest


def test_frozen_taskset_digest_is_order_sensitive_on_task_ids():
    """task_ids is an ordered tuple, not a set -- reordering the same three
    ids must change the digest, or a shuffled task list would silently claim
    to be the same frozen set."""
    ordered = _taskset(task_ids=("t1", "t2", "t3"))
    shuffled = _taskset(task_ids=("t3", "t1", "t2"))
    assert ordered.digest != shuffled.digest


# FIXED 2026-09-06: this defect was repaired in the integration pass;
# the xfail(strict=True) marker was removed so the test now guards the fix.
def test_frozen_taskset_digest_is_stable_against_external_mutation_BUG():
    census = {"code": 2, "type": 1}
    ts = FrozenTaskSet(name="n", task_ids=("a", "b", "c"),
                        counting_rule="r", label_plane_census=census)
    digest_before = ts.digest
    census["code"] = 999999  # caller still owns this dict; ts never re-validated it
    assert ts.digest == digest_before, (
        "a frozen task set's digest changed because the caller mutated a dict "
        "it handed over at construction time -- the freeze is shallow")


# --------------------------------------------------------------------------- #
# A2 -- label-plane census                                                    #
# --------------------------------------------------------------------------- #
def test_taskset_reports_label_plane_census():
    ts = _taskset()
    assert ts.label_plane_census == {"code": 2, "knowledge": 1}
    assert sum(ts.label_plane_census.values()) == len(ts.task_ids)


def test_taskset_census_must_sum_to_task_count():
    """Prove the guard can actually fire, not just that a valid census passes."""
    with pytest.raises(FreezeError, match="sums to"):
        FrozenTaskSet(name="broken", task_ids=("t1", "t2"),
                      counting_rule="r", label_plane_census={"code": 1})


def test_taskset_census_rejects_unknown_plane_name():
    with pytest.raises(FreezeError, match="non-planes"):
        FrozenTaskSet(name="broken", task_ids=("t1",), counting_rule="r",
                      label_plane_census={"vibes": 1})


def test_taskset_rejects_duplicate_task_ids():
    with pytest.raises(FreezeError, match="repeats task ids"):
        FrozenTaskSet(name="dupe", task_ids=("t1", "t1"), counting_rule="r",
                      label_plane_census={"code": 2})


def test_taskset_rejects_empty_counting_rule():
    with pytest.raises(FreezeError, match="counting_rule"):
        FrozenTaskSet(name="n", task_ids=("t1",), counting_rule="   ",
                      label_plane_census={"code": 1})


# --------------------------------------------------------------------------- #
# A3 -- cross-plane refusal (R3 / the s08 defect made mechanical)             #
# --------------------------------------------------------------------------- #
def test_single_plane_taskset_refused_for_crossplane():
    single_plane = _taskset(task_ids=("t1", "t2"), label_plane_census={"code": 2})
    with pytest.raises(FreezeError, match="single-plane"):
        single_plane.require_cross_plane()


def test_multi_plane_taskset_is_not_refused_for_crossplane():
    """The refusal must actually be conditional -- prove the >=2-plane case
    passes, or the 'refusal' would just be an unconditional raise dressed up
    as a check (a vacuum test in the other direction)."""
    two_plane = _taskset(label_plane_census={"code": 2, "knowledge": 1})
    two_plane.require_cross_plane()  # must not raise


def test_zero_plane_census_is_also_refused_for_crossplane():
    """An empty label_plane_census (allowed only when task_ids is also
    empty -- but task_ids may not be empty -- so this path requires an
    all-zero census over known planes) must not silently look 'ok'."""
    with pytest.raises(FreezeError):
        FrozenTaskSet(name="n", task_ids=("t1",), counting_rule="r",
                      label_plane_census={"code": 0}).require_cross_plane()


# --------------------------------------------------------------------------- #
# A4 -- evaluator version binds a scoring-code digest                        #
# --------------------------------------------------------------------------- #
def test_evaluator_version_binds_scoring_code_digest():
    base = _evaluator(code_digest="a" * 64)
    changed = _evaluator(code_digest="b" * 64)
    assert base.digest != changed.digest, (
        "changing code_digest must change EvaluatorVersion.digest -- if it "
        "didn't, two different scorers could report as the same evaluator "
        "version")
    assert _evaluator(code_digest="a" * 64).digest == base.digest


def test_evaluator_version_rejects_non_sha256_shaped_digest():
    with pytest.raises(FreezeError, match="64 chars"):
        EvaluatorVersion(name="e", version="1", code_digest="not-a-real-digest")


def test_evaluator_version_rejects_blank_fields():
    with pytest.raises(FreezeError):
        EvaluatorVersion(name="", version="1", code_digest="a" * 64)
    with pytest.raises(FreezeError):
        EvaluatorVersion(name="e", version="  ", code_digest="a" * 64)


# --------------------------------------------------------------------------- #
# A5 -- unsealed runs are marked unsealed                                    #
# --------------------------------------------------------------------------- #
def test_unsealed_run_is_marked_unsealed():
    rm = _manifest()  # no owner_seal_ref supplied
    assert rm.owner_seal_ref is None
    assert rm.sealed is False
    status = rm.evidence_status()
    assert "NOT Gate-3 baseline evidence" in status
    assert "UNSEALED" in status


def test_blank_owner_seal_ref_is_still_unsealed():
    """Whitespace-only seal ref must not count as a seal -- otherwise a caller
    who forgets to fill it in but passes '' or ' ' would accidentally look
    sealed on some other code path that only checks 'is not None'."""
    rm = _manifest(owner_seal_ref="   ")
    assert rm.sealed is False


def test_owner_seal_ref_is_an_unverified_bare_string_SERIOUS_FINDING():
    """ADVERSARIAL OBLIGATION 4: try to construct a RunManifest that reports
    sealed=True without a genuine owner seal.

    This SUCCEEDS, and that is the finding. `RunManifest.owner_seal_ref` is a
    plain `str | None` field with only a non-empty/non-blank check
    (`bool(ref and ref.strip())`). Nothing in contracts.py verifies that the
    string corresponds to any real, authenticated, one-use `OwnerApproval`
    (plan §11 Gate 3 / §7.1's `OwnerApproval` binding candidate + EvidencePacket
    + revision + target). Any caller -- including a builder, not just an
    owner -- can set `sealed=True` by passing any non-blank string.

    FIXED 2026-09-06. The forgery above no longer works. `RunManifest.sealed`
    is now hard-wired to False: this package has no access to an authenticated
    one-use `OwnerApproval`, so the only honest answer it can give is "not
    sealed". A recorded reference is exposed separately as `seal_claim` and is
    reported as an UNVERIFIED CLAIM.

    This test now guards the fix: it asserts the forgery FAILS.
    """
    forged = _manifest(owner_seal_ref="i-typed-this-myself-nobody-approved-anything")
    assert forged.sealed is False, "a bare string must never seal a run"
    status = forged.evidence_status()
    assert "UNSEALED" in status
    assert "NOT Gate-3" in status
    assert "UNVERIFIED seal claim" in status
    # the claim is still recorded -- suppressing it would hide who asserted what
    assert forged.seal_claim == "i-typed-this-myself-nobody-approved-anything"


def test_sealing_does_not_change_the_run_digest():
    """The module docstring claims owner_seal_ref is deliberately outside the
    digest so sealing an existing run doesn't change its identity. Verify
    that claim directly rather than trusting the comment."""
    unsealed = _manifest()
    sealed = _manifest(owner_seal_ref="owner-approval-ref-001")
    assert unsealed.digest == sealed.digest


def test_manifest_requires_non_blank_revision_and_plan_digest():
    with pytest.raises(FreezeError, match="base_revision"):
        _manifest(base_revision="  ")
    with pytest.raises(FreezeError, match="plan_digest"):
        _manifest(plan_digest="")


# FIXED 2026-09-06: this defect was repaired in the integration pass;
# the xfail(strict=True) marker was removed so the test now guards the fix.
def test_manifest_budgets_are_immutable_after_construction_BUG():
    budgets = {"arm_a": ArmBudget(max_tokens=100), "arm_b": ArmBudget(max_tokens=100)}
    rm = _manifest(budgets=budgets)
    assert rm.arms == ("arm_a", "arm_b")

    budgets["arm_c"] = ArmBudget(max_tokens=999999)  # mutate the caller's own dict

    assert rm.arms == ("arm_a", "arm_b"), (
        "a RunManifest's arm set changed after construction because the "
        "caller mutated a dict it had already handed over -- the manifest "
        "did not defensively copy its budgets mapping")


# --------------------------------------------------------------------------- #
# A6 -- seed policy: independent repetitions                                 #
# --------------------------------------------------------------------------- #
def test_seed_policy_repeats_are_independent():
    seeds = tuple(range(5))
    sp = SeedPolicy(seeds=seeds)
    assert sp.n_repetitions == len(seeds) == 5
    assert len(set(sp.seeds)) == len(sp.seeds), "no seed may be reused"


def test_seed_policy_rejects_duplicate_seeds():
    """Prove the no-duplicates guard can actually fire."""
    with pytest.raises(FreezeError, match="repeats seeds"):
        SeedPolicy(seeds=(1, 2, 2, 3, 4))


def test_seed_policy_deterministic_requires_exactly_one_seed():
    SeedPolicy(seeds=(1,), deterministic=True)  # must not raise
    with pytest.raises(FreezeError, match="exactly one seed"):
        SeedPolicy(seeds=(1, 2), deterministic=True)


# --------------------------------------------------------------------------- #
# E4 -- missing seeds refused for a stochastic arm                           #
# --------------------------------------------------------------------------- #
def test_missing_seed_refused_for_stochastic_arm():
    with pytest.raises(FreezeError, match=r"needs >= 5"):
        SeedPolicy(seeds=(1, 2, 3, 4), deterministic=False)


def test_exactly_min_stochastic_seeds_is_accepted():
    """Boundary check: the refusal must be `< MIN`, not `<= MIN` -- prove the
    accept side of the boundary too, or a fencepost error could refuse a
    perfectly compliant 5-seed run."""
    sp = SeedPolicy(seeds=(1, 2, 3, 4, 5), deterministic=False)
    assert sp.n_repetitions == SeedPolicy.MIN_STOCHASTIC_SEEDS == 5


# --------------------------------------------------------------------------- #
# A7 -- environment records model and host                                   #
# --------------------------------------------------------------------------- #
def test_environment_records_model_and_host():
    env = _environment(model_id="claude-sonnet-5", provider="anthropic", host="build-box-01")
    assert env.model_id == "claude-sonnet-5"
    assert env.provider == "anthropic"
    assert env.host == "build-box-01"
    assert env.tokenizer and env.os_name and env.cpu
    assert env.ram_gb > 0


def test_environment_allows_none_model_for_model_free_arm():
    """A deterministic, model-free arm (Random Search, BM25, ...) has no
    model id -- recording None must be a legal, honest state, not forced into
    a fabricated model name."""
    env = _environment(model_id=None, provider=None, host=None)
    assert env.model_id is None
    env.digest  # must not raise just because optional fields are absent


def test_environment_rejects_blank_required_fields():
    with pytest.raises(FreezeError, match="tokenizer"):
        _environment(tokenizer="")
    with pytest.raises(FreezeError, match="os_name"):
        _environment(os_name="   ")
    with pytest.raises(FreezeError, match="cpu"):
        _environment(cpu="")


def test_environment_rejects_non_positive_ram():
    with pytest.raises(FreezeError, match="ram_gb"):
        _environment(ram_gb=0)
    with pytest.raises(FreezeError, match="ram_gb"):
        _environment(ram_gb=-4)


# --------------------------------------------------------------------------- #
# B1 -- every arm receives an equal budget (named offenders)                 #
# --------------------------------------------------------------------------- #
def test_every_arm_receives_equal_budget():
    equal = {"arm_a": ArmBudget(max_tokens=500, max_calls=4),
             "arm_b": ArmBudget(max_tokens=500, max_calls=4)}
    require_equal_budgets(equal)  # must not raise


def test_unequal_budgets_are_refused_and_offenders_are_named():
    budgets = {
        "arm_a": ArmBudget(max_tokens=500),
        "arm_b": ArmBudget(max_tokens=500),
        "arm_c": ArmBudget(max_tokens=999),
    }
    with pytest.raises(FreezeError) as excinfo:
        require_equal_budgets(budgets)
    message = str(excinfo.value)
    assert "arm_c" in message, "the offending arm must be named, not just detected"
    assert "arm_a" in message and "arm_b" in message, (
        "the majority group must also be named so the diagnosis is complete")


def test_require_equal_budgets_rejects_empty_map():
    with pytest.raises(FreezeError, match="at least one"):
        require_equal_budgets({})


def test_manifest_construction_enforces_equal_budgets():
    """RunManifest.__post_init__ calls require_equal_budgets -- prove the
    wiring, not just the underlying function in isolation."""
    with pytest.raises(FreezeError):
        _manifest(budgets={"arm_a": ArmBudget(max_tokens=100),
                            "arm_b": ArmBudget(max_tokens=200)})


# --------------------------------------------------------------------------- #
# B3 -- round-robin split is refused unconditionally (the exact s08 defect)  #
# --------------------------------------------------------------------------- #
def test_round_robin_split_is_refused():
    budget = ArmBudget(max_tokens=1000, max_calls=8)
    for n in (1, 2, 4, 100):
        with pytest.raises(FreezeError, match="refused"):
            budget.split(n)


def test_arm_budget_rejects_zero_and_negative_axes():
    """Zero is not '0 = unlimited' and not '0 = disabled' (contracts.py's own
    docstring rule, mirroring plan §4.1). Prove it can actually fire."""
    with pytest.raises(FreezeError, match="Zero is not"):
        ArmBudget(max_tokens=0)
    with pytest.raises(FreezeError):
        ArmBudget(max_calls=-1)


def test_arm_budget_none_means_uncapped_not_zero():
    b = ArmBudget()  # every axis None
    assert b.max_tokens is None and b.max_calls is None
    assert b.max_wall_seconds is None and b.max_usd is None
    b.digest  # must not raise on an all-uncapped budget


# --------------------------------------------------------------------------- #
# Structural-counter hunt (adversarial obligation 2)                         #
# --------------------------------------------------------------------------- #
def test_digest_actually_depends_on_every_top_level_field_of_manifest():
    """Hunt for a field silently excluded from RunManifest.digest (other than
    the deliberately-excluded owner_seal_ref, covered separately above)."""
    base = _manifest()
    assert _manifest(base_revision="deadbeef").digest != base.digest
    assert _manifest(plan_digest="0" * 64).digest != base.digest
    assert _manifest(environment=_environment(cpu="arm64")).digest != base.digest
    assert _manifest(seed_policy=SeedPolicy(seeds=(9,), deterministic=True)).digest != base.digest


def test_digest_moves_when_gold_labels_change_not_only_when_ids_do():
    """S6 from the 2026-09-10 adversarial pass, pinned.

    The digest hashed name / task_ids / counting_rule / census only. Rewriting
    the ``must_include`` of every task in the set left it BYTE-IDENTICAL, as did
    rewriting every ``minted_at_sha``. A "frozen" task set that cannot notice
    its own gold labels changing does not support the claim its name makes --
    and the commit that moved this digest cited its movement as proof the
    transition was auditable.
    """
    from daedalus.eval.gate3.contracts import canonical_digest

    ids = ("t1", "t2")
    census = {"code": 2, "type": 0, "data": 0, "knowledge": 0}
    same_ids_old_labels = FrozenTaskSet(
        name="n", task_ids=ids, counting_rule="r", label_plane_census=census,
        content_digest=canonical_digest([{"id": "t1", "must_include": ["a"]},
                                         {"id": "t2", "must_include": ["b"]}]))
    same_ids_new_labels = FrozenTaskSet(
        name="n", task_ids=ids, counting_rule="r", label_plane_census=census,
        content_digest=canonical_digest([{"id": "t1", "must_include": ["ZZZ"]},
                                         {"id": "t2", "must_include": ["b"]}]))
    assert same_ids_old_labels.digest != same_ids_new_labels.digest, (
        "identical ids and census, one changed gold label, same digest -- the "
        "set is not frozen against its own content")


def test_an_absent_content_digest_is_visible_rather_than_equivalent():
    """``None`` must not be silently equal to "content unchanged".

    A set built without content coverage is a genuinely different artifact from
    one built with it, and a reader comparing two digests has to be able to
    tell. Recording ``None`` in the hashed dict is what makes that true.
    """
    ids = ("t1",)
    census = {"code": 1, "type": 0, "data": 0, "knowledge": 0}
    without = FrozenTaskSet(name="n", task_ids=ids, counting_rule="r",
                            label_plane_census=census)
    with_content = FrozenTaskSet(name="n", task_ids=ids, counting_rule="r",
                                 label_plane_census=census,
                                 content_digest="deadbeef")
    assert without.content_digest is None
    assert without.digest != with_content.digest
