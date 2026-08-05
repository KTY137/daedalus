from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.runtimes.provider_target_receipt_retention_admission as admission_module
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effect_replay import EffectExecutionReplaySnapshot
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.provider_target_receipt_ledger import ProviderTargetReceiptLedger
from daedalus.runtimes.provider_target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionBindingError,
    ProviderTargetReceiptRetentionAdmissionReceipt,
    ProviderTargetReceiptRetentionAdmissionShapeError,
    verify_provider_target_receipt_retention_admission,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider_target_receipt_retention_preflight import (
    ProviderTargetReceiptRetentionPreflightBindingError,
    ProviderTargetReceiptRetentionPreflightReceipt,
)
from daedalus.spine.effect_boundary import GuardDecision

REVISION = "1" * 40
EVENT_SCOPE = "state/spine.sqlite3"
CAS_SCOPE = "cas/receipts"
DIGESTS = tuple(f"{index:x}" * 64 for index in range(1, 13))


class _DigestSubject:
    def __init__(self, digest: str) -> None:
        self.digest = digest


class _Lease(_DigestSubject):
    entrypoint_id = RETENTION_ENTRYPOINT


class _Request(_DigestSubject):
    entrypoint_id = RETENTION_ENTRYPOINT


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="retention-execution",
        idempotency_key="retention-idempotency",
        requested_effects=("filesystem_write",),
        writable_paths=(EVENT_SCOPE, CAS_SCOPE),
        kill_switch_ref="retention-kill-switch",
        kill_switch_generation=3,
    )


def _preflight(execution: EffectExecutionRequest) -> ProviderTargetReceiptRetentionPreflightReceipt:
    return ProviderTargetReceiptRetentionPreflightReceipt(
        source_revision=REVISION,
        repository_head_receipt_sha256=DIGESTS[0],
        provider_target_receipt_sha256=DIGESTS[1],
        retention_inventory_sha256=DIGESTS[2],
        retention_inventory_source_sha256=DIGESTS[3],
        retention_inventory_source_size=4096,
        retention_inventory_surface_count=7,
        retention_authority_sha256=DIGESTS[4],
        retention_subject_sha256=DIGESTS[5],
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=DIGESTS[7],
        guard_contract=RETENTION_GUARD_CONTRACT,
        guard_evidence=(
            f"authority_sha256={DIGESTS[4]};subject_sha256={DIGESTS[5]}"
        ),
        event_store_scope_path=EVENT_SCOPE,
        receipt_cas_scope_path=CAS_SCOPE,
    )


def _subjects(tmp_path: Path):
    repository = tmp_path / "repository"
    repository.mkdir()
    retention_root = tmp_path / "retention"
    event = retention_root / "state" / "spine.sqlite3"
    event.parent.mkdir(parents=True)
    event.write_bytes(b"event-store")
    cas = retention_root / "cas" / "receipts"
    cas.mkdir(parents=True)
    effect_store = tmp_path / "effect-leases.sqlite3"
    effect_store.write_bytes(b"effect-store")

    ledger = object.__new__(ProviderTargetReceiptLedger)
    ledger.primary_checkout = repository
    ledger.spine = SimpleNamespace(path=event)
    ledger.source_store = SimpleNamespace(root=cas)

    execution = _execution()
    preflight = _preflight(execution)
    receipt = _DigestSubject(preflight.provider_target_receipt_sha256)
    inventory = _DigestSubject(preflight.retention_inventory_sha256)
    authority = _DigestSubject(preflight.retention_authority_sha256)

    authorization = object.__new__(NonRuntimeEffectAuthorization)
    object.__setattr__(
        authorization,
        "lease",
        _Lease(preflight.retention_effect_lease_sha256),
    )
    object.__setattr__(authorization, "request", _Request(DIGESTS[8]))
    object.__setattr__(
        authorization,
        "policy_decision",
        _DigestSubject(DIGESTS[9]),
    )
    object.__setattr__(
        authorization,
        "effect_ledger",
        SimpleNamespace(path=effect_store),
    )
    object.__setattr__(
        authorization,
        "guard_decisions",
        (
            GuardDecision(
                RETENTION_GUARD_CONTRACT,
                True,
                preflight.guard_evidence,
            ),
        ),
    )
    return SimpleNamespace(
        repository=repository,
        retention_root=retention_root,
        event=event,
        cas=cas,
        effect_store=effect_store,
        ledger=ledger,
        preflight=preflight,
        receipt=receipt,
        inventory=inventory,
        authority=authority,
        execution=execution,
        authorization=authorization,
    )


def _call(subjects, *, event_scope: str = EVENT_SCOPE, cas_scope: str = CAS_SCOPE):
    return verify_provider_target_receipt_retention_admission(
        subjects.repository,
        subjects.retention_root,
        object(),
        subjects.receipt,
        subjects.inventory,
        subjects.authority,
        subjects.execution,
        subjects.authorization,
        subjects.ledger,
        expected_authority_id="retention-authority",
        authority_keyring={"retention-key": b"x" * 32},
        event_store_scope_path=event_scope,
        receipt_cas_scope_path=cas_scope,
        at=object(),
    )


def _verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay=None,
):
    subjects = _subjects(tmp_path)
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: replay,
    )
    return _call(subjects), subjects


def _start_receipt(execution: EffectExecutionRequest) -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=DIGESTS[7],
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        boundary_receipt_sha256=DIGESTS[10],
        started_at="2026-08-05T08:00:00.000000+00:00",
        receipt_sha256=DIGESTS[11],
    )


def test_not_started_admission_round_trip_is_non_executing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _verify(tmp_path, monkeypatch)
    payload = result.to_dict()

    assert result.execution_state == "not_started"
    assert payload["persisted_effect_lease_verified"] is True
    assert payload["primary_checkout_disjointness_verified"] is True
    assert payload["retention_effect_started"] is False
    assert payload["retention_write_performed"] is False
    assert payload["automatic_reexecution_allowed"] is False
    assert payload["canonical_entrypoint_registered"] is False
    assert payload["closed"] is False
    assert ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload) == result


def test_started_replay_is_reported_without_terminal_or_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    replay = EffectExecutionReplaySnapshot(
        _start_receipt(subjects.execution),
        "STARTED",
        None,
    )
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: replay,
    )
    result = _call(subjects)

    assert result.execution_state == "started"
    assert result.start_receipt_sha256 == DIGESTS[11]
    assert result.terminal_receipt_sha256 is None
    assert result.to_dict()["retention_effect_started"] is True
    assert result.to_dict()["retention_effect_terminal"] is False
    assert result.to_dict()["automatic_reexecution_allowed"] is False


def test_terminal_replay_retains_both_receipt_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    start = _start_receipt(subjects.execution)
    terminal = EffectTerminalReceipt(
        lease_sha256=DIGESTS[7],
        execution_id=subjects.execution.execution_id,
        start_receipt_sha256=DIGESTS[11],
        outcome="COMPLETED",
        output_digests=(),
        detail_sha256=None,
        finished_at="2026-08-05T08:01:00.000000+00:00",
        receipt_sha256="a" * 64,
    )
    replay = EffectExecutionReplaySnapshot(start, "COMPLETED", terminal)
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: replay,
    )
    result = _call(subjects)

    assert result.execution_state == "COMPLETED"
    assert result.start_receipt_sha256 == DIGESTS[11]
    assert result.terminal_receipt_sha256 == "a" * 64
    assert result.to_dict()["retention_effect_terminal"] is True


def test_preflight_refusal_happens_before_topology_or_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    calls: list[str] = []

    def refuse(*args, **kwargs):
        calls.append("preflight")
        raise ProviderTargetReceiptRetentionPreflightBindingError("stale revision")

    def unexpected(*args, **kwargs):
        calls.append("replay")
        raise AssertionError("replay ran after failed preflight")

    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        refuse,
    )
    monkeypatch.setattr(admission_module, "inspect_effect_execution", unexpected)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="preflight did not reverify",
    ):
        _call(subjects)
    assert calls == ["preflight"]


def test_concrete_cas_scope_substitution_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    foreign_cas = tmp_path / "foreign-cas"
    foreign_cas.mkdir()
    subjects.ledger.source_store.root = foreign_cas
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="receipt_cas_scope_path does not bind the concrete receipt CAS",
    ):
        _call(subjects)


def test_noncanonical_scope_refuses_before_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )

    def unexpected(*args, **kwargs):
        calls.append("replay")
        raise AssertionError("replay ran after malformed topology")

    monkeypatch.setattr(admission_module, "inspect_effect_execution", unexpected)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="canonical non-root repository-relative POSIX",
    ):
        _call(subjects, cas_scope="cas//receipts")
    assert calls == []


def test_guard_detachment_refuses_before_topology_or_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    object.__setattr__(
        subjects.authorization,
        "guard_decisions",
        (GuardDecision(RETENTION_GUARD_CONTRACT, True, "detached"),),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )

    def unexpected(*args, **kwargs):
        calls.append("replay")
        raise AssertionError("replay ran after detached guard")

    monkeypatch.setattr(admission_module, "inspect_effect_execution", unexpected)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="guard is detached",
    ):
        _call(subjects)
    assert calls == []


def test_effect_store_hard_link_alias_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    alias = tmp_path / "effect-leases-alias.sqlite3"
    try:
        os.link(subjects.effect_store, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="Effect-Lease store must have one filesystem identity",
    ):
        _call(subjects)


def test_retention_root_inside_primary_checkout_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    nested_root = subjects.repository / "retention"
    nested_event = nested_root / EVENT_SCOPE
    nested_event.parent.mkdir(parents=True)
    nested_event.write_bytes(b"nested-event")
    nested_cas = nested_root / CAS_SCOPE
    nested_cas.mkdir(parents=True)
    subjects.retention_root = nested_root
    subjects.ledger.spine.path = nested_event
    subjects.ledger.source_store.root = nested_cas
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="retention_root must be outside the Primary Checkout",
    ):
        _call(subjects)


def test_non_exact_replay_snapshot_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: SimpleNamespace(state="STARTED"),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="non-exact snapshot",
    ):
        _call(subjects)


def test_wire_claim_escalation_extra_fields_and_malformed_state_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _verify(tmp_path, monkeypatch)
    payload = result.to_dict()
    payload["retention_write_performed"] = True
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="unsupported claim",
    ):
        ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload)

    payload = result.to_dict()
    payload["unexpected"] = False
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="fields are not exact",
    ):
        ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload)

    payload = result.to_dict()
    payload["execution_state"] = []
    with pytest.raises(ProviderTargetReceiptRetentionAdmissionShapeError):
        ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload)
