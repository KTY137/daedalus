# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Authority is the operator's; the subject is the caller's. They are two roots.

THE DEFECT THIS SUITE PINS, and it was mine. ``acquire_effect_lease`` took one
``repo_root`` and used it for three unrelated things: the control root (permit,
issuer key, lease ledger, evidence store), the write fence, and the checkout the
containment contracts MEASURE. While only ``python.offload`` was issuable its
caller was always the installation, so the three coincided and nothing showed.
Parameterising the ROW (6cf056e2, shipped in main as part of 21f21f2a) made the
divergence reachable without splitting the ROOTS.

What it cost while it stood: for every door whose subject is not the
installation -- every ``TaskAttempt``, whose repo is a fresh candidate checkout
-- the issuer derived a control root that had never been armed and raised
``WaveLeaseKillSwitchEngaged``. That is a ``LoopHalted`` subclass, so the issuer
HALTED THE RUN instead of denying the request. Worse than the halt: a candidate
that chooses where it works would have been choosing which control root judges
it, which is the evidence boundary inverted.

Each test below fails if one half of the split is removed:

* let the subject pick the control root -> ``test_the_subject_root_never...``
* ask the default manager anyway       -> ``test_containment_is_measured_over...``
* forget the authority checkout        -> ``test_a_planned_root_inside_the_authority...``
* let the record and the guard drift   -> ``test_the_disjointness_record_names...``
"""
from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel.offload_lease import (
    ENTRYPOINT_ID,
    WaveLeaseDenied,
    WaveLeaseKillSwitchEngaged,
    WaveOffloadLease,
    acquire_effect_lease,
    control_root,
    derive_wave_containment,
    issuer_keyring,
    kill_switch_generation,
    lease_ledger_path,
    wave_containment_roots,
)
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[2])
REVISION = "e" * 40
MECHANISM = "split test: the caller's own manager root"


@pytest.fixture
def switch(tmp_path, monkeypatch):
    """An armed permit for the INSTALLATION, and only for it."""
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    sw = KillSwitch(repo_root=REPO_ROOT)
    sw.arm(note="authority/subject split test")
    assert control_root(REPO_ROOT) == tmp_path
    return sw


def _candidate(tmp_path):
    """A checkout the operator never armed -- what a TaskAttempt really has."""
    root = tmp_path / "candidate-checkout"
    root.mkdir()
    return root


def _planned(tmp_path):
    """A planned isolation root, disjoint from both checkouts."""
    return tmp_path / "isolation" / "wt-1"


def _acquire(sw, **overrides):
    kwargs = dict(
        entrypoint_id=ENTRYPOINT_ID,
        source_revision=REVISION,
        mission_id="split-test",
        attempt_id="s-1",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=sw,
    )
    kwargs.update(overrides)
    return acquire_effect_lease(REPO_ROOT, **kwargs)


# --------------------------------------------------------------------------- #
# the blast radius, as a test rather than as a claim                           #
# --------------------------------------------------------------------------- #
def test_a_candidate_checkout_has_no_permit_of_its_own(tmp_path, monkeypatch):
    """WHAT THE DEFECT COST. Passing the candidate as the authority root -- the
    only thing a caller could do before the split -- halts the run.

    Not a deny receipt about a request: ``WaveLeaseKillSwitchEngaged`` is a
    ``LoopHalted`` subclass, which ``LoopDriver.run`` classifies as an
    operator's stop. Every attempt-shaped door hit this.
    """

    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    candidate = _candidate(tmp_path)
    assert control_root(str(candidate)) != control_root(REPO_ROOT)
    with pytest.raises(WaveLeaseKillSwitchEngaged, match="not armed"):
        kill_switch_generation(KillSwitch(repo_root=str(candidate)))


# --------------------------------------------------------------------------- #
# authority never follows the subject                                          #
# --------------------------------------------------------------------------- #
def test_the_subject_root_never_chooses_the_control_root(switch, tmp_path):
    """The whole point. A caller naming any subject it likes still gets the
    operator's permit, key, ledger and evidence store -- and a grant, because
    the installation IS armed."""

    candidate = _candidate(tmp_path)
    granted = _acquire(
        switch, subject_root=str(candidate), worktree_root=str(_planned(tmp_path))
    )
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    # The authority artifacts are the installation's, not the candidate's.
    assert Path(granted.ledger_path) == lease_ledger_path(REPO_ROOT)
    assert Path(granted.control_root_path) == control_root(REPO_ROOT)
    assert granted.lease.issuer_key_id in issuer_keyring(REPO_ROOT)
    # NOT asserted here: that the candidate resolves to a different control
    # root. `DAEDALUS_KILLSWITCH` is a process-global override, so under this
    # fixture every root resolves to the same directory -- which is exactly
    # what makes the fixture usable. The divergence is measured without the
    # env var in `test_a_candidate_checkout_has_no_permit_of_its_own`.


def test_the_write_fence_stays_the_operators(switch, tmp_path):
    """A candidate that carried its own .agentenv would otherwise clear its own
    paths. The fence is resolved from the authority root, so an empty candidate
    tree does not become an unconfined one."""

    candidate = _candidate(tmp_path)
    granted = _acquire(
        switch, subject_root=str(candidate), worktree_root=str(_planned(tmp_path))
    )
    assert isinstance(granted, WaveOffloadLease)
    assert granted.write_policy is not None
    assert granted.write_policy.usable
    assert str(candidate) not in str(granted.write_policy.origin)


# --------------------------------------------------------------------------- #
# the second face: whose worktree root is measured                             #
# --------------------------------------------------------------------------- #
def test_containment_is_measured_over_the_callers_planned_worktree_root(
    switch, tmp_path
):
    """A caller with an injected manager writes under a root the default
    manager never names. Measuring the default was a measurement wearing the
    wrong name, and its allow rode into the disjointness record."""

    candidate = _candidate(tmp_path)
    planned = _planned(tmp_path)
    granted = _acquire(
        switch, subject_root=str(candidate), worktree_root=str(planned)
    )
    assert isinstance(granted, WaveOffloadLease)
    evidence = next(
        d.evidence
        for d in granted.authorization.guard_decisions
        if d.contract == "containment.attempt"
    )
    assert str(planned) in evidence
    assert str(candidate) in evidence


def test_the_roots_helper_returns_the_callers_pair(tmp_path):
    candidate = _candidate(tmp_path)
    planned = _planned(tmp_path)
    primary, target = wave_containment_roots(str(candidate), str(planned))
    assert Path(primary) == candidate.resolve()
    assert Path(target) == planned.resolve()


# --------------------------------------------------------------------------- #
# the hole the split would otherwise open                                      #
# --------------------------------------------------------------------------- #
def test_a_planned_root_inside_the_authority_checkout_is_refused(switch, tmp_path):
    """THE ADVERSARIAL CASE FOR THIS COMMIT. Name a throwaway subject, then aim
    the isolation root at the operator's own tree. Disjoint from the subject,
    catastrophic against the authority -- so both are checked."""

    candidate = _candidate(tmp_path)
    inside = Path(REPO_ROOT) / "runs" / "split-test-would-be-inside"
    granted = _acquire(
        switch, subject_root=str(candidate), worktree_root=str(inside)
    )
    assert isinstance(granted, WaveLeaseDenied), "a write into the operator's tree was leased"
    assert any("AUTHORITY checkout" in reason for reason in granted.reasons)


def test_the_same_pair_is_allowed_when_the_authority_is_the_subject(tmp_path):
    """The check only fires when the two roots really are different, so the
    wave path -- where they are the same directory -- is untouched."""

    ok, evidence = derive_wave_containment(
        REPO_ROOT, str(_planned(tmp_path)), authority_root=REPO_ROOT
    )
    assert ok, evidence
    assert "AUTHORITY" not in evidence


# --------------------------------------------------------------------------- #
# the two containment contracts are not one condition                          #
# --------------------------------------------------------------------------- #
def test_the_two_containment_contracts_diverge_on_the_caller_mechanism(
    switch, tmp_path
):
    """REPORTED AS "two contracts, one measurement". Measured, it is not.

    Both quote the same derivation over the same planned root -- which is why
    their ALLOW evidence looks identical, and why the report was reasonable.
    But ``containment.attempt`` is that derivation AND the caller's
    ``contained`` flag AND a named mechanism, so it refuses where
    ``containment.worktree`` allows. The relation is SUBSUMPTION, not
    duplication: attempt implies worktree.

    This is the tripwire against collapsing them. ``containment.worktree`` is
    declared ALONE by five rows (``worktree.reap``, ``worktree.create``,
    ``worktree.commit``, ``worktree.cleanup``, ``python.promote_candidates``),
    where it is the only containment check there is.
    """

    candidate = _candidate(tmp_path)
    denied = _acquire(
        switch,
        entrypoint_id="python.attempt",
        effect_key="daedalus/attempt/split-probe",
        containment_evidence="",  # the caller names no mechanism
        subject_root=str(candidate),
        worktree_root=str(_planned(tmp_path)),
    )
    decisions = {d.contract: d for d in denied.guard_decisions}
    assert decisions["containment.attempt"].allowed is False
    assert "no containment mechanism" in decisions["containment.attempt"].evidence
    # Same roots, same derivation, opposite verdict.
    assert decisions["containment.worktree"].allowed is True
    assert decisions["containment.worktree"].evidence.startswith("topology only")
    assert (
        decisions["containment.worktree"].evidence
        != decisions["containment.attempt"].evidence
    )


def test_the_worktree_contract_is_the_sole_check_for_the_rows_that_declare_it_alone():
    """Why it is not deleted as decoration."""

    from daedalus.spine.effect_boundary import REGISTRY_BY_ID

    alone = {
        row.id
        for row in REGISTRY_BY_ID.values()
        if "containment.worktree" in row.guard_contracts
        and "containment.attempt" not in row.guard_contracts
    }
    assert "worktree.reap" in alone
    assert "python.promote_candidates" in alone
    both = {
        row.id
        for row in REGISTRY_BY_ID.values()
        if "containment.worktree" in row.guard_contracts
        and "containment.attempt" in row.guard_contracts
    }
    # The subsumption is confined to exactly one row; everywhere else the
    # worktree contract is doing work nothing else does.
    assert both == {"python.attempt"}


# --------------------------------------------------------------------------- #
# the record cannot drift from the guard                                       #
# --------------------------------------------------------------------------- #
def test_the_disjointness_record_names_the_pair_the_contract_measured(
    switch, tmp_path
):
    """``record_primary_checkout_disjointness`` never re-decides, so it has to
    be handed the two roots the contract just judged. Handing it the authority
    root instead would retain a receipt about a comparison nobody made."""

    from daedalus.kernel.offload_lease import write_root_identity_sha256

    candidate = _candidate(tmp_path)
    planned = _planned(tmp_path)
    granted = _acquire(
        switch, subject_root=str(candidate), worktree_root=str(planned)
    )
    assert isinstance(granted, WaveOffloadLease)
    assert granted.evidence_errors == [], granted.evidence_errors
    store = Path(granted.evidence_root) / "disjointness"
    records = sorted(store.glob("*.json"))
    assert len(records) == 1
    import json

    body = json.loads(records[0].read_text(encoding="utf-8"))
    assert body["primary_checkout_sha256"] == write_root_identity_sha256(candidate)
    assert body["target_root_sha256"] == write_root_identity_sha256(planned)


# --------------------------------------------------------------------------- #
# the default is the old behaviour                                             #
# --------------------------------------------------------------------------- #
def test_omitting_both_keywords_leaves_the_wave_path_alone(switch):
    """Byte-identity is proved separately against 11dc0195 by
    ``runs/lease-split-probe/identity_probe.py``; this pins the shape."""

    granted = _acquire(switch)
    assert isinstance(granted, WaveOffloadLease), getattr(granted, "reasons", None)
    evidence = next(
        d.evidence
        for d in granted.authorization.guard_decisions
        if d.contract == "containment.attempt"
    )
    # The subject defaulted to the authority root, so the evidence names the
    # installation and says nothing about a second checkout.
    assert REPO_ROOT in evidence
    assert "AUTHORITY checkout" not in evidence
