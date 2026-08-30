"""The issuer's refusal is a predicate now, not a constant. What it lets past.

Before this suite, ``acquire_wave_offload_lease`` read
``spec = REGISTRY_BY_ID[ENTRYPOINT_ID]`` with ``ENTRYPOINT_ID`` spelled once at
module scope, and the docstring's reason was "a helper that can issue for
whichever entrypoint you name is a general-purpose capability minter". The
worry is real and unchanged. What the constant could not say is WHICH rows are
safe and why -- so 46 of the 47 central registry rows were refused with no
statement of what was wrong with them, and the Gate-0 write classification had
exactly one door that could ever hold a lease.

The predicate that replaced it (:func:`daedalus.kernel.offload_lease.issuable_row`)
states the real requirement: this issuer may issue for a row only when it can
run every contract that row declares, itself, in process, and bound every effect
that row declares in the scope it builds. Each test below fails if one conjunct
is removed:

* accept a row whose contracts it cannot run -> ``test_a_row_whose_contracts...``
* accept a runtime-bearing row               -> ``test_a_runtime_bearing_row...``
* accept an effect the scope cannot bound    -> ``test_a_row_whose_effects...``
* run offload's contracts for another row    -> ``test_the_lease_carries_exactly...``
* grant what the row never declared          -> ``test_a_row_without_egress...``
* let the wave wrapper name a row            -> ``test_the_wave_wrapper_refuses...``
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel.offload_lease import (
    CONTAINMENT_CONTRACTS,
    ENTRYPOINT_ID,
    ISSUER_CONTRACTS,
    ISSUER_EFFECTS,
    WaveLeaseDenied,
    WaveOffloadLease,
    acquire_effect_lease,
    acquire_wave_offload_lease,
    control_root,
    issuable_row,
)
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Wiring
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[2])
REVISION = "c" * 40
MECHANISM = "test: the isolation root is the manager's own worktree root"

#: The second row the rule admits. MEASURED, not chosen: with the predicate in
#: place exactly four of the 97 registry rows are issuable -- ``python.offload``,
#: ``cli.eval_ceiling``, ``tools.funnel_report`` and ``tools.run_gate_checks``
#: -- and the three new ones all declare ``process_spawn`` alone under
#: ``budget.process_guard`` alone. Named rather than discovered, so a registry
#: edit that widens this row fails here instead of silently widening a lease.
SECOND_DOOR = "cli.eval_ceiling"

#: A row this issuer must never be able to run, used wherever the "contracts I
#: cannot run" conjunct needs a subject. ``promotion.owner_approval`` is chosen
#: rather than found: sealed promotion means no automatic path may mint that
#: capability, so unlike every other unrunnable contract this one must stay
#: unrunnable forever.
UNRUNNABLE_ROW = "python.promote_candidates"

#: The door the handoff aimed at, and the one the rule refuses for a reason
#: that is NOT the one the handoff expected. See
#: ``test_the_gate_door_is_refused_for_an_unfenced_write``.
GATE_DOOR = "python.command_gate"

#: A CENTRAL, non-runtime-bearing row declaring a contract this issuer has no
#: in-process implementation of. DERIVED, never named: this file used to spell
#: ``python.attempt`` here, 11dc0195 implemented that row's two contracts, and
#: three tests then asserted a refusal that no longer happens. Deriving the row
#: means implementing the NEXT contract retargets these tests instead of
#: reddening them. At 11dc0195 it is ``adapter.subprocess``, which declares
#: ``runtime.adapter_profile``.
UNRUNNABLE_DOOR = next(
    row_id
    for row_id in sorted(REGISTRY_BY_ID)
    if REGISTRY_BY_ID[row_id].wiring is Wiring.CENTRAL
    and not REGISTRY_BY_ID[row_id].runtime_id
    and set(REGISTRY_BY_ID[row_id].guard_contracts) - ISSUER_CONTRACTS
)


@pytest.fixture
def switch(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="issuer rule test")
    assert control_root(REPO_ROOT) == tmp_path
    return sw


def _acquire(sw, entrypoint_id, **overrides):
    kwargs = dict(
        source_revision=REVISION,
        mission_id="rule-test",
        attempt_id=f"a-{entrypoint_id.replace('.', '-')}",
        positions=1,
        lanes=("ollama",),
        tools=("pytest",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=sw,
    )
    kwargs.update(overrides)
    return acquire_effect_lease(REPO_ROOT, entrypoint_id=entrypoint_id, **kwargs)


# --------------------------------------------------------------------------- #
# the predicate                                                                #
# --------------------------------------------------------------------------- #
def test_the_row_the_wave_pins_is_issuable():
    spec, reasons = issuable_row(ENTRYPOINT_ID)
    assert reasons == ()
    assert spec is not None and spec.id == ENTRYPOINT_ID


def test_the_second_door_the_rule_admits_declares_one_contract():
    """The rule is a rule because it admits a row nobody wrote it for."""

    spec, reasons = issuable_row(SECOND_DOOR)
    assert reasons == ()
    assert spec is not None
    assert set(spec.guard_contracts) <= ISSUER_CONTRACTS
    assert {effect.value for effect in spec.effects} <= ISSUER_EFFECTS


def test_the_gate_door_is_refused_for_an_unfenced_write():
    """``python.command_gate`` declares a write and no fence for it.

    It is the only door in the tree that declares a blocking write surface AND
    has an in-process caller that could honestly hold its lease -- which is why
    the handoff aimed at this file. The rule still refuses it, and the reason
    is the one that matters: this issuer's only way to bound a filesystem write
    is ``sensitivity.path_write_blocked`` over the declared roots, which is the
    ``provider.write_policy`` contract, and this row does not declare it.
    Issuing anyway would put roots in a receipt that no fence judged -- the
    exact defect ``WritePolicySource`` was written to record.
    """

    spec, reasons = issuable_row(GATE_DOOR)
    assert spec is None
    assert len(reasons) == 1
    assert "issuer.effect_bounds" in reasons[0]
    assert "filesystem_write (needs provider.write_policy)" in reasons[0]


def test_a_row_whose_contracts_this_issuer_cannot_run_is_refused_by_name():
    """A contract with no in-process implementation is refused BY NAME.

    THIS TEST USED TO NAME ``python.attempt``, and 11dc0195 implemented that
    row's two contracts, so the assertion became a statement about history
    rather than about the rule. The rule is unchanged and is what matters: the
    only two ways past an unimplemented contract are defects -- skip it (an
    unrun guard recorded as a passed one) or take the caller's word for it
    (which ``WritePolicySource`` already measured) -- so the issuer refuses and
    says which contract it could not run.

    The row is DERIVED from the registry rather than named, so implementing the
    next contract retargets this test instead of turning it red. At 11dc0195 it
    resolves to ``adapter.subprocess`` and ``runtime.adapter_profile``.
    """

    spec, reasons = issuable_row(UNRUNNABLE_DOOR)
    assert spec is None
    contracts = [r for r in reasons if r.startswith("issuer.contracts")]
    assert len(contracts) == 1
    for contract in sorted(
        set(REGISTRY_BY_ID[UNRUNNABLE_DOOR].guard_contracts) - ISSUER_CONTRACTS
    ):
        assert contract in contracts[0]


def test_the_attempt_and_chip_rows_are_deliberately_issuable():
    """Pin every row the shared issuer may mint, including the Gate-1 EDA door.

    ``python.attempt`` declared ``spine.intent_ledger`` and
    ``containment.worktree``; the issuer now runs both itself and the row also
    declares ``provider.write_policy``, without which ``issuer.effect_bounds``
    would still refuse its two write effects. The set of issuable rows is
    enumerated rather than spot-checked: a registry or issuer edit that admits a
    newly admitted row fails here instead of silently minting a capability for it.

    IT DID EXACTLY THAT, 2026-08-26, and the widening is recorded here rather
    than absorbed. Registering ``tools.docs_reference_check`` -- a docs reporter
    that was running as an unregistered effectful door -- made it the SIXTH
    issuable row. The set is enumerated so that consequence has to be argued,
    and the argument is that the row is issuable for the same reason its two
    neighbours in this list already are: ``tools.funnel_report`` and
    ``tools.run_gate_checks`` are CENTRAL rows declaring PROCESS_SPAWN alone
    under ``budget.process_guard``, and so is this one. A capability the issuer
    could mint for it authorises spawning ``git`` and nothing else -- no write
    root, no egress, no credential -- so admitting it neither widens the
    issuer's contract surface nor puts a write behind a reporter. Refusing it
    while admitting the identical two would have been an accident of order, not
    a rule.
    G1-EDA-01 adds ``cli.daedalus_chip`` deliberately. It declares exactly
    filesystem write, process spawn and process control, and the issuer runs
    the corresponding write, containment and process-budget contracts. It has
    no network, secret, spend or promotion effect.
    """

    spec, reasons = issuable_row("python.attempt")
    assert reasons == ()
    assert spec is not None and spec.id == "python.attempt"
    assert "provider.write_policy" in spec.guard_contracts
    issuable = tuple(
        row_id for row_id in sorted(REGISTRY_BY_ID) if issuable_row(row_id)[0]
    )
    assert issuable == (
        "cli.daedalus_chip",
        "cli.eval_ceiling",
        "python.attempt",
        "python.offload",
        "tools.docs_reference_check",
        "tools.funnel_report",
        "tools.run_gate_checks",
    ), issuable


def test_the_promotion_contract_must_never_become_implementable_here():
    """``python.promote_candidates`` declares a contract this issuer must never run.

    THE SUBJECT MOVED, and the move is the point. This test used to name
    ``python.attempt`` for ``spine.intent_ledger`` and ``containment.worktree``;
    11dc0195 implemented both in this issuer, so that row became issuable and
    the assertion became false. The conjunct it tests did not change, only a
    row that satisfies it -- which is what a rule looks like when it is a rule
    and not a list.

    ``promotion.owner_approval`` is the better subject anyway: sealed promotion
    (plan invariant 5) means no automatic path may mint that capability, so
    this is the one refusal that must never become implementable HERE. If some
    future edit adds it to ``ISSUER_CONTRACTS``, this test is the tripwire.
    """

    spec, reasons = issuable_row(UNRUNNABLE_ROW)
    assert spec is None
    contracts = [r for r in reasons if r.startswith("issuer.contracts")]
    assert len(contracts) == 1
    assert "promotion.owner_approval" in contracts[0]
    assert "promotion.owner_approval" not in ISSUER_CONTRACTS


def test_an_unregistered_row_is_refused_before_anything_else():
    spec, reasons = issuable_row("python.not_a_row")
    assert spec is None
    assert reasons == (
        "registry.row: 'python.not_a_row' is not a registered entrypoint, so it "
        "declares no contracts to run and no effects to bound",
    )


def test_a_non_central_row_is_refused():
    non_central = next(
        row for row in REGISTRY_BY_ID.values() if row.wiring is not Wiring.CENTRAL
    )
    spec, reasons = issuable_row(non_central.id)
    assert spec is None
    assert any("registry.wiring" in reason for reason in reasons)


def test_a_runtime_bearing_row_is_refused():
    """A ``runtime_id`` needs RuntimeBoundEffectAuthorization's live rechecks.

    ``NonRuntimeEffectAuthorization`` raises on such a lease in
    ``__post_init__``. Refusing here turns that raise -- which would happen
    mid-wave, after the kill switch and every contract had been evaluated --
    into a deny receipt about a request.
    """

    runtime_row = next(
        row
        for row in REGISTRY_BY_ID.values()
        if row.runtime_id and row.wiring is Wiring.CENTRAL
    )
    spec, reasons = issuable_row(runtime_row.id)
    assert spec is None
    assert any("registry.runtime" in reason for reason in reasons)


def test_a_row_whose_effects_the_scope_cannot_bound_is_refused():
    """``secrets`` has no field in the scope this issuer builds.

    ``_scope_requirements`` refuses a secrets effect without ``secret_refs``,
    and this module names none -- so the row could never have been issued
    anyway. The difference is that it now fails as a named deny receipt instead
    of an ``EffectLeaseScopeError`` raised out of ``issue_effect_lease``.
    """

    row = next(
        r
        for r in REGISTRY_BY_ID.values()
        if r.wiring is Wiring.CENTRAL
        and not r.runtime_id
        and set(r.guard_contracts) <= ISSUER_CONTRACTS
        and not {e.value for e in r.effects} <= ISSUER_EFFECTS
    )
    spec, reasons = issuable_row(row.id)
    assert spec is None
    assert any("issuer.effects" in reason for reason in reasons)


# --------------------------------------------------------------------------- #
# what the refusal produces                                                    #
# --------------------------------------------------------------------------- #
def test_an_unissuable_row_denies_and_persists_nothing(switch, tmp_path):
    denied = _acquire(switch, UNRUNNABLE_DOOR)
    assert isinstance(denied, WaveLeaseDenied)
    assert denied.granted is False
    assert denied.policy_decision.verdict == "deny"
    # The receipt names the row that was refused, not the row this module was
    # once hard-coded to.
    assert denied.receipt()["entrypoint_id"] == UNRUNNABLE_DOOR
    assert denied.receipt()["lease_id"] is None
    # Refused BEFORE any contract ran: no guard decision exists to report.
    assert denied.guard_decisions == ()
    # And nothing reached the ledger or the issuer key.
    assert not (tmp_path / "effect-leases.sqlite3").exists()


def test_the_refusal_happens_before_the_kill_switch_is_consulted(tmp_path, monkeypatch):
    """A row this issuer may never issue for is not a question about a permit.

    With a STOPPED permit, an issuable row raises ``WaveLeaseKillSwitchEngaged``.
    An unissuable one still returns a deny receipt, because the registry's
    answer does not depend on this machine's permit state.
    """

    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="issuer rule test")
    sw.stop("stopped for this test")
    denied = _acquire(sw, UNRUNNABLE_DOOR)
    assert isinstance(denied, WaveLeaseDenied)
    assert any("issuer.contracts" in reason for reason in denied.reasons)


# --------------------------------------------------------------------------- #
# what the grant carries for a row that is NOT python.offload                  #
# --------------------------------------------------------------------------- #
def test_the_lease_carries_exactly_the_contracts_the_row_declares(switch):
    """Not offload's four. ``begin_effect`` refuses both a missing decision and
    an undeclared one, so a lease carrying four decisions could never START for
    a row that declares one -- the grant would be legal and unusable."""

    granted = _acquire(switch, SECOND_DOOR)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    contracts = tuple(sorted(d.contract for d in granted.authorization.guard_decisions))
    assert contracts == tuple(sorted(REGISTRY_BY_ID[SECOND_DOOR].guard_contracts))
    assert contracts == ("budget.process_guard",)


def test_the_grant_can_really_start_an_execution(switch):
    """The proof that the decision set is the right one: the kernel accepts it.

    ``EffectLeaseLedger.begin`` runs the registry's own ``begin_effect`` over
    these exact decisions. A lease whose decisions did not match the row's
    declaration would be refused here, not at issuance.
    """

    granted = _acquire(switch, SECOND_DOOR)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    # No path: the row declares no write effect, so the lease grants no root
    # and the kernel refuses an execution that names one -- which is the
    # backstop under this issuer's narrowing, tested below.
    execution = granted.execution_for(0)
    start = granted.authorization.begin_effect(execution)
    assert start.execute is True
    terminal = granted.authorization.finish_effect(
        start.receipt, outcome="COMPLETED"
    )
    assert terminal.receipt_sha256


def test_an_execution_cannot_name_a_root_the_narrowed_scope_never_granted(switch):
    """The narrowing is not decoration: the kernel enforces it one layer down.

    ``execution_for`` will happily carry whatever paths a caller names, so the
    proof that ``writable_paths=()`` means something is that
    ``_validate_narrowed_scope`` refuses the start.
    """

    from daedalus.kernel.effects import EffectLeaseScopeError

    granted = _acquire(switch, SECOND_DOOR)
    assert isinstance(granted, WaveOffloadLease)
    execution = granted.execution_for(1, ("docs/x.md",))
    with pytest.raises(EffectLeaseScopeError, match="outside the leased roots"):
        granted.authorization.begin_effect(execution)


def test_a_row_without_egress_or_spend_is_granted_neither(switch):
    """The caller asked for a lane and a spend ceiling. The row declares
    neither effect, so the scope carries neither -- a scope that grants what
    the row never declared is a widening nobody asked for, and it would ride
    into the receipt as a bound somebody set."""

    granted = _acquire(switch, SECOND_DOOR, lanes=("ollama",), max_spend_usd=5.0)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    scope = granted.lease.effect_scope
    assert scope.egress_endpoints == ()
    assert scope.max_cost_microusd == 0
    # It declares no write effect, so it is granted no writable root -- and the
    # scope says so in the field a reader checks first.
    assert scope.writable_paths == ()
    assert scope.read_only is True
    # It DOES declare process_spawn, so the tools it needs survive.
    assert "git" in scope.tools


def test_offload_still_gets_every_bound_it_declares(switch):
    """The rule must not have narrowed the row it was written around."""

    granted = _acquire(switch, ENTRYPOINT_ID)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    scope = granted.lease.effect_scope
    assert scope.egress_endpoints  # network_egress is declared
    assert scope.max_cost_microusd == 250_000  # spend is declared
    assert "pytest" in scope.tools  # process_spawn is declared
    assert scope.writable_paths == ("docs/x.md",)
    contracts = tuple(sorted(d.contract for d in granted.authorization.guard_decisions))
    assert contracts == tuple(sorted(REGISTRY_BY_ID[ENTRYPOINT_ID].guard_contracts))


# --------------------------------------------------------------------------- #
# what a grant may and may not leave behind                                    #
# --------------------------------------------------------------------------- #
def test_a_row_with_no_containment_contract_retains_no_disjointness_record(switch):
    """The disjointness record IS the containment decision, re-typed.

    A row that never took one must not retain one: the write-classification
    chain reads that record as "this door's writes land outside the primary
    checkout", and it would be resting on THIS issuer's measurement of the
    attempt isolation root -- a pair of roots that row's writes never touch.
    """

    row = next(
        r
        for r in REGISTRY_BY_ID.values()
        if issuable_row(r.id)[0] is not None
        and not set(r.guard_contracts) & CONTAINMENT_CONTRACTS
    )
    granted = _acquire(switch, row.id)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    assert "disjointness" not in granted.evidence_records
    # THE EXACT MESSAGE, and it is exact on purpose. A looser assertion here
    # survived the "retain-a-disjointness-record-for-a-row-that-took-no-
    # decision" mutant: with the gate disabled the recorder still refuses (the
    # decision it would record is not an allow), and its ValueError quotes the
    # same "declares no containment contract" evidence string -- so the test
    # passed on a message about a raised exception rather than about a
    # deliberate refusal to retain. This phrase belongs to the gate alone.
    assert granted.evidence_errors == [
        f"disjointness: {row.id} declares no containment contract, so this "
        "grant retains no primary-checkout disjointness record"
    ]
    # The lease-subject record is still retained: it is about the lease, not
    # about a pair of roots.
    assert "lease_subject" in granted.evidence_records


def test_a_containment_bearing_row_still_retains_one(switch):
    granted = _acquire(switch, ENTRYPOINT_ID)
    assert isinstance(granted, WaveOffloadLease)
    assert granted.evidence_records.get("disjointness")
    assert granted.evidence_errors == []


# --------------------------------------------------------------------------- #
# the wave wrapper still pins its row                                          #
# --------------------------------------------------------------------------- #
def test_the_wave_wrapper_refuses_to_be_told_which_row(switch):
    """The wave starter names no entrypoint, and a keyword this wrapper
    silently ignored would read at the call site as a request that had been
    honoured."""

    with pytest.raises(TypeError, match="python.offload only"):
        acquire_wave_offload_lease(
            REPO_ROOT,
            entrypoint_id=SECOND_DOOR,
            source_revision=REVISION,
            mission_id="rule-test",
            attempt_id="a-wrapper",
            positions=1,
            switch=switch,
        )


def test_the_wave_wrapper_issues_the_pinned_row(switch):
    granted = acquire_wave_offload_lease(
        REPO_ROOT,
        source_revision=REVISION,
        mission_id="rule-test",
        attempt_id="a-pinned",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=switch,
    )
    assert isinstance(granted, WaveOffloadLease)
    assert granted.lease.entrypoint_id == ENTRYPOINT_ID
