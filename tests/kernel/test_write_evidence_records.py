# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""What a granted, terminalised wave lease is allowed to leave behind.

Every test here needs a REAL granted lease -- a signed capability, a durable
ledger row, and for the terminal half a durable start and terminal receipt --
because the whole point of these records is that they are read back out of the
effect ledger rather than asserted. Building one forces pytest's ``tmp_path``
and ``monkeypatch`` (the control root has to move off the operator's real one),
so this module runs under the pytest runner rather than by executing its bodies
directly.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from daedalus.kernel import offload_lease as ol
from daedalus.kernel.effects import EffectLeaseStateError
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.envelope import canonical_json
from daedalus.spine.killswitch import KillSwitch

REPO_ROOT = str(Path(__file__).resolve().parents[2])
REVISION = "0" * 40
MECHANISM = "gated_writes.run_write_wave: one TaskAttempt worktree per write task"


@pytest.fixture
def control(tmp_path, monkeypatch):
    """An armed permit in a throwaway control root; the ledger, the issuer key
    and the write-evidence store land beside it."""

    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    switch = KillSwitch(repo_root=REPO_ROOT)
    switch.arm(note="write-evidence test")
    return switch


def _lease(switch, attempt_id="a1", **kw):
    body = dict(
        source_revision=REVISION,
        mission_id="write-evidence-test",
        positions=1,
        lanes=("ollama",),
        max_spend_usd=0.25,
        timeout_s=900,
        writable_paths=("docs/x.md",),
        contained=True,
        containment_evidence=MECHANISM,
        switch=switch,
    )
    body.update(kw)
    return ol.acquire_wave_offload_lease(REPO_ROOT, attempt_id=attempt_id, **body)


def _store():
    return ol.write_evidence_root(REPO_ROOT, REVISION)


def _records(kind):
    return sorted((_store() / kind).glob("*.json"))


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# the fingerprint definition                                                    #
# --------------------------------------------------------------------------- #
def test_two_producers_agree_on_one_root_and_it_is_not_a_path_digest(tmp_path):
    """The definition is pinned, not "any 64-hex the verifier will accept".

    The chain shape-checks ``primary_checkout_sha256`` and
    ``target_root_sha256`` as 64-hex and nothing more, so two producers that
    each invented a digest would disagree undetected (Momus F4). These are the
    two properties that make one definition: the same root fingerprints the
    same through a different path spelling, and the digest is not the digest of
    the path.
    """

    root = tmp_path / "Checkout"
    root.mkdir()
    spelled_differently = tmp_path / "." / "Checkout"
    assert ol.write_root_identity_sha256(root) == ol.write_root_identity_sha256(
        spelled_differently
    )
    assert ol.write_root_identity_sha256(root) != hashlib.sha256(
        str(root).encode("utf-8")
    ).hexdigest()
    other = tmp_path / "other"
    other.mkdir()
    assert ol.write_root_identity_sha256(root) != ol.write_root_identity_sha256(other)


def test_a_root_that_does_not_exist_yet_still_has_an_identity(tmp_path):
    """``planned_overlap_reason`` asks about a directory the manager creates
    afterwards, so the fingerprint must survive one that is not there."""

    planned = tmp_path / "worktrees" / "attempt-1"
    first = ol.write_root_identity_sha256(planned)
    assert first == ol.write_root_identity_sha256(planned)
    assert first != ol.write_root_identity_sha256(tmp_path / "worktrees" / "attempt-2")


# --------------------------------------------------------------------------- #
# the disjointness recorder: it records, it never decides                       #
# --------------------------------------------------------------------------- #
def test_the_recorder_never_reaches_the_predicate(tmp_path, monkeypatch):
    """Recording a decision must not be able to reach a different answer."""

    import daedalus.primary_tree as primary_tree

    calls: list[tuple] = []

    def _tripwire(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("the recorder re-ran the containment predicate")

    monkeypatch.setattr(primary_tree, "planned_overlap_reason", _tripwire)
    monkeypatch.setattr(primary_tree, "overlap_reason", _tripwire)
    decision = GuardDecision(
        ol.WORKTREE_CONTAINMENT_CONTRACT, True, "planned_overlap_reason(...) is None"
    )
    record = ol.record_primary_checkout_disjointness(
        decision,
        primary_checkout=tmp_path / "checkout",
        target_root=tmp_path / "worktrees",
        source_revision=REVISION,
        evidence_root=tmp_path / "store",
        control_root_path=tmp_path,
    )
    assert calls == []
    # And what it recorded IS the decision it was handed, not a restatement.
    assert record["decision_sha256"] == ol.guard_decision_sha256(decision)
    assert record["evidence"] == decision.evidence
    assert record["contract"] == ol.WORKTREE_CONTAINMENT_CONTRACT
    assert record["disjoint"] is True


def test_a_refused_decision_is_not_a_disjointness_receipt(tmp_path):
    refused = GuardDecision(
        ol.WORKTREE_CONTAINMENT_CONTRACT, False, "the root overlaps the checkout"
    )
    with pytest.raises(ValueError, match="not a disjointness receipt"):
        ol.record_primary_checkout_disjointness(
            refused,
            primary_checkout=tmp_path / "checkout",
            target_root=tmp_path / "worktrees",
            source_revision=REVISION,
            evidence_root=tmp_path / "store",
            control_root_path=tmp_path,
        )


def test_two_roots_with_one_identity_contradict_the_recorded_decision(tmp_path):
    """A decision that said "disjoint" over two names for one directory is
    wrong about one of the two, and the record may not carry both."""

    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(ValueError, match="share one identity"):
        ol.record_primary_checkout_disjointness(
            GuardDecision(ol.WORKTREE_CONTAINMENT_CONTRACT, True, "evidence"),
            primary_checkout=root,
            target_root=tmp_path / "." / "checkout",
            source_revision=REVISION,
            evidence_root=tmp_path / "store",
            control_root_path=tmp_path,
        )


def test_another_contract_cannot_be_recorded_as_disjointness(tmp_path):
    with pytest.raises(ValueError, match="containment.worktree"):
        ol.record_primary_checkout_disjointness(
            GuardDecision("budget.process_guard", True, "spend net installed"),
            primary_checkout=tmp_path / "a",
            target_root=tmp_path / "b",
            source_revision=REVISION,
            evidence_root=tmp_path / "store",
            control_root_path=tmp_path,
        )


def test_the_issuer_records_the_containment_decision_it_was_issued_under(control):
    lease = _lease(control, "a-disjoint")
    assert lease.granted and not lease.evidence_errors
    records = _records("disjointness")
    assert len(records) == 1
    body = _read(records[0])
    assert body["record_sha256"] == lease.evidence_records["disjointness"]
    assert body["contract"] == ol.WORKTREE_CONTAINMENT_CONTRACT
    # The evidence is the derivation's own sentence, not a new one.
    derived_ok, derived_evidence = ol.derive_wave_containment(REPO_ROOT)
    assert derived_ok is True
    assert body["evidence"] == derived_evidence
    assert body["decision_sha256"] == ol.guard_decision_sha256(
        GuardDecision(ol.WORKTREE_CONTAINMENT_CONTRACT, True, derived_evidence)
    )
    primary, target = ol.wave_containment_roots(REPO_ROOT)
    assert body["primary_checkout_sha256"] == ol.write_root_identity_sha256(primary)
    assert body["target_root_sha256"] == ol.write_root_identity_sha256(target)


# --------------------------------------------------------------------------- #
# the terminal record: terminal state, or nothing                               #
# --------------------------------------------------------------------------- #
def test_a_granted_only_lease_produces_no_terminal_record(control):
    lease = _lease(control, "a-granted")
    assert lease.granted
    keyring = ol.issuer_keyring(REPO_ROOT)
    records, refusals = ol.harvest_effect_lease_terminal_records(
        _store(), control_root_path=ol.control_root(REPO_ROOT), keyring=keyring
    )
    assert records == ()
    assert any(
        "no execution identity was ever derived under it" in reason
        for reason in refusals
    )
    assert not (_store() / "lease-terminal").exists()

    # And once an identity IS derived without being begun, the harvest reaches
    # the producer and refuses there: a derived execution with no durable start
    # is not a terminal receipt.
    execution = lease.execution_for(0, ("docs/x.md",))
    records, refusals = ol.harvest_effect_lease_terminal_records(
        _store(), control_root_path=ol.control_root(REPO_ROOT), keyring=keyring
    )
    assert records == ()
    assert any("no durable start" in reason for reason in refusals)
    subject = _read(_records("lease-subject")[0])
    with pytest.raises(EffectLeaseStateError, match="no durable start"):
        ol.emit_effect_lease_terminal_record(
            subject,
            execution,
            evidence_root=_store(),
            control_root_path=ol.control_root(REPO_ROOT),
            keyring=keyring,
        )


def test_a_started_only_execution_produces_no_terminal_record(control):
    lease = _lease(control, "a-started")
    execution = lease.execution_for(0, ("docs/x.md",))
    lease.authorization.begin_effect(execution)
    keyring = ol.issuer_keyring(REPO_ROOT)
    records, refusals = ol.harvest_effect_lease_terminal_records(
        _store(), control_root_path=ol.control_root(REPO_ROOT), keyring=keyring
    )
    assert records == ()
    assert any("started-only execution" in reason for reason in refusals)

    # And the direct producer refuses it with the same fact, not a shrug.
    subject = _read(_records("lease-subject")[0])
    with pytest.raises(EffectLeaseStateError, match="started-only execution"):
        ol.emit_effect_lease_terminal_record(
            subject,
            execution,
            evidence_root=_store(),
            control_root_path=ol.control_root(REPO_ROOT),
            keyring=keyring,
        )


def test_a_terminal_execution_is_recorded_in_lowercase(control):
    lease = _lease(control, "a-terminal")
    execution = lease.execution_for(0, ("docs/x.md",))
    start = lease.authorization.begin_effect(execution)
    terminal = lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")
    keyring = ol.issuer_keyring(REPO_ROOT)
    records, refusals = ol.harvest_effect_lease_terminal_records(
        _store(), control_root_path=ol.control_root(REPO_ROOT), keyring=keyring
    )
    assert refusals == ()
    assert len(records) == 1
    body = records[0]
    # The kernel stores the upper-case outcome; the chain compares
    # ``replay.state.lower()`` against the retained payload, so the record
    # carries the case the consumer compares.
    assert terminal.outcome == "COMPLETED"
    assert body["terminal_state"] == "completed"
    assert body["receipt_sha256"] == terminal.receipt_sha256
    assert body["execution_id"] == execution.execution_id
    assert body["lease_sha256"] == lease.lease.digest
    assert body["entrypoint_id"] == "python.offload"
    assert body["receipt_schema"] == ol.EFFECT_LEASE_RECEIPT_SCHEMA
    assert set(body["requested_effects"]) & {"filesystem_write", "repository_mutation"}


def test_the_lease_sweeps_its_own_executions_and_names_the_ones_that_did_not_run(
        control):
    """The wave-shaped consumer, and the discrimination that makes it useful.

    ``harvest_effect_lease_terminal_records`` sweeps the WHOLE store; a wave
    holds one lease and wants its OWN issued set, because that is the set it
    can say something true about. This probe issues two execution identities
    and terminalises exactly one, so a sweep that reported both -- or that
    quietly dropped the one it could not replay -- fails here rather than in a
    receipt somebody reads later.

    The refusal is asserted by CONTENT ("no durable start"), not by count: a
    sweep that refused the finished execution for some unrelated reason would
    also produce "one record, one refusal".
    """
    lease = _lease(control, "a-sweep")
    ran = lease.execution_for(0, ("docs/x.md",))
    never = lease.execution_for(1, ("docs/y.md",))
    start = lease.authorization.begin_effect(ran)
    lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")

    records, refusals = lease.retain_terminal_records()

    assert [body["execution_id"] for body in records] == [ran.execution_id]
    assert len(refusals) == 1
    assert never.execution_id in refusals[0]
    assert "no durable start" in refusals[0]
    # Keyed by execution: a single "lease_terminal" key would have kept only
    # whichever position happened to be swept last.
    assert lease.evidence_records[f"lease_terminal:{ran.execution_id}"] == (
        records[0]["record_sha256"]
    )
    assert f"lease_terminal:{never.execution_id}" not in lease.evidence_records
    # And the sweep is idempotent, because the store is content-addressed:
    # re-running it republishes the same bytes instead of accumulating a
    # near-identical record per sweep.
    again, _ = lease.retain_terminal_records()
    assert [body["record_sha256"] for body in again] == [
        body["record_sha256"] for body in records
    ]
    assert len(_records("lease-terminal")) == 1


def test_a_terminal_record_names_a_ledger_row_that_still_exists(control, tmp_path):
    """The record is a replay result, not a memory of one: point the rebuild at
    an empty ledger and the same subject stops producing anything."""

    lease = _lease(control, "a-empty-ledger")
    execution = lease.execution_for(0, ("docs/x.md",))
    start = lease.authorization.begin_effect(execution)
    lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")
    subject = _read(_records("lease-subject")[0])
    with pytest.raises(
        EffectLeaseStateError, match="effect lease is not uniquely persisted"
    ):
        ol.emit_effect_lease_terminal_record(
            subject,
            execution,
            evidence_root=_store(),
            control_root_path=ol.control_root(REPO_ROOT),
            keyring=ol.issuer_keyring(REPO_ROOT),
            ledger_path=tmp_path / "empty-ledger.sqlite3",
        )


def test_the_issuer_key_survives_its_own_write(tmp_path, monkeypatch):
    """MEASURED, and the reason this suite was flaky before the fix.

    ``os.open`` on Windows without ``O_BINARY`` opens in TEXT mode and turns
    every ``0x0A`` into ``0x0D 0x0A``, so a random 32-byte key containing a
    newline byte -- about 12% of them -- landed on disk as different bytes than
    the ones the issuing process signed with.  Every lease that process issued
    then failed verification forever after it exited, reporting the honest but
    useless ``effect lease signature mismatch``.  Reproduced 1-in-7 over 8
    fresh control roots; 0-in-40 after.

    The key here is not random: it contains ``0x0A`` deliberately, so the test
    is a fact rather than a coin flip.
    """

    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    poisoned = bytes([0x0A, 0x0D] * 16)
    monkeypatch.setattr(ol.os, "urandom", lambda n: poisoned[:n])
    keyring = ol.issuer_keyring(REPO_ROOT)
    on_disk = (ol.control_root(REPO_ROOT) / "effect-lease-issuer.key").read_bytes()
    assert keyring[ol.ISSUER_KEY_ID] == poisoned
    assert on_disk == poisoned
    # And a second reader gets the same bytes the signer used.
    assert ol.issuer_keyring(REPO_ROOT)[ol.ISSUER_KEY_ID] == poisoned


def test_the_retained_issuer_target_resolves_to_a_real_function(control):
    """The guard-contract evidence a row carries names this implementation, so
    the name has to be one that exists."""

    import importlib

    lease = _lease(control, "a-target")
    subject = _read(_records("lease-subject")[0])
    module_name, _, function_name = subject["issuer_target"].partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, function_name))
    assert (
        Path(REPO_ROOT) / subject["issuer_module_path"]
    ).resolve() == Path(module.__file__).resolve()
    assert lease.granted


# --------------------------------------------------------------------------- #
# what a reader of the store refuses                                            #
# --------------------------------------------------------------------------- #
def _load_generator():
    import importlib.util
    import sys

    path = Path(REPO_ROOT) / "scripts" / "declare_write_surfaces.py"
    spec = importlib.util.spec_from_file_location("declare_write_surfaces", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_write_surfaces"] = module
    spec.loader.exec_module(module)
    return module


def test_a_tampered_record_is_refused_by_its_own_digest(control):
    lease = _lease(control, "a-tamper")
    execution = lease.execution_for(0, ("docs/x.md",))
    start = lease.authorization.begin_effect(execution)
    lease.authorization.finish_effect(start.receipt, outcome="COMPLETED")
    ol.harvest_effect_lease_terminal_records(
        _store(),
        control_root_path=ol.control_root(REPO_ROOT),
        keyring=ol.issuer_keyring(REPO_ROOT),
    )
    generator = _load_generator()
    control_sha = ol.write_root_identity_sha256(ol.control_root(REPO_ROOT))

    clean = generator.load_retained_write_evidence(
        _store(), source_revision=REVISION, control_root_sha256=control_sha
    )
    assert len(clean.terminals) == 1 and clean.refusals == ()

    path = _records("lease-terminal")[0]
    body = _read(path)
    body["terminal_state"] = "failed"
    path.write_bytes(canonical_json(body).encode("ascii"))
    tampered = generator.load_retained_write_evidence(
        _store(), source_revision=REVISION, control_root_sha256=control_sha
    )
    assert tampered.terminals == ()
    assert any("does not bind the body" in reason for reason in tampered.refusals)


def test_a_record_from_another_control_root_is_refused(control):
    """Momus F8: evidence produced under one control root and verified under
    another is two machines' facts in one report."""

    lease = _lease(control, "a-control-root")
    assert lease.granted
    generator = _load_generator()
    foreign = generator.load_retained_write_evidence(
        _store(),
        source_revision=REVISION,
        control_root_sha256="f" * 64,
    )
    assert foreign.subjects == {} and foreign.disjointness == ()
    assert any("retained under control root" in r for r in foreign.refusals)


def test_a_record_bound_to_another_revision_is_refused(control):
    lease = _lease(control, "a-revision")
    assert lease.granted
    generator = _load_generator()
    other = generator.load_retained_write_evidence(
        _store(),
        source_revision="a" * 40,
        control_root_sha256=ol.write_root_identity_sha256(ol.control_root(REPO_ROOT)),
    )
    assert other.subjects == {}
    assert any("bound to revision" in reason for reason in other.refusals)
