from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.runtimes.provider_target_receipt_retention_admission as admission_module
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effect_replay import EffectExecutionReplaySnapshot
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.source_trees import SourceTreeStore
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
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import GuardDecision
from daedalus.spine.ledger import SpineLedger

REVISION = "1" * 40
EVENT_SCOPE = "state/spine.sqlite3"
CAS_SCOPE = "cas/receipts"
DIGESTS = tuple(f"{index:x}" * 64 for index in range(1, 13))
NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)


class _DigestSubject:
    def __init__(self, digest: str) -> None:
        self.digest = digest


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="retention-execution",
        idempotency_key="retention-idempotency",
        requested_effects=("filesystem_write",),
        writable_paths=(EVENT_SCOPE, CAS_SCOPE),
        kill_switch_ref="retention-kill-switch",
        kill_switch_generation=3,
    )


def _lease_subjects() -> tuple[EffectLeaseRequest, PolicyDecision, EffectLease]:
    scope = EffectScope(
        read_only=False,
        writable_paths=(CAS_SCOPE, EVENT_SCOPE),
        max_cost_microusd=0,
        timeout_s=300,
        max_concurrency=1,
        kill_switch_ref="retention-kill-switch",
    )
    request = EffectLeaseRequest(
        request_id="retention-request",
        mission_id="retention-mission",
        attempt_id="retention-attempt",
        entrypoint_id=RETENTION_ENTRYPOINT,
        requested_effects=("filesystem_write",),
        effect_scope=scope,
        idempotency_namespace="provider-target-receipt-retention",
        kill_switch_generation=3,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.retention-admission-request",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=2)).isoformat(timespec="microseconds"),
            input_digests=(DIGESTS[0],),
            trace_id="retention-admission-trace",
        ),
    )
    policy = PolicyDecision(
        decision_id="retention-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-05",
        policy_sha256=DIGESTS[1],
        verdict="allow",
        reasons=("bounded receipt retention",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.retention-admission-policy",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
            input_digests=(request.digest, DIGESTS[1]),
            trace_id="retention-admission-trace",
        ),
    )
    lease = EffectLease(
        lease_id="retention-lease",
        request_id=request.request_id,
        request_sha256=request.digest,
        policy_decision_id=policy.decision_id,
        policy_decision_sha256=policy.digest,
        registry_sha256=DIGESTS[2],
        entrypoint_id=RETENTION_ENTRYPOINT,
        requested_effects=("filesystem_write",),
        effect_scope=scope,
        idempotency_namespace=request.idempotency_namespace,
        kill_switch_generation=3,
        runtime_id="",
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        issuer_key_id="retention-lease-key",
        issued_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
        expires_at=(NOW + timedelta(minutes=30)).isoformat(timespec="microseconds"),
        signature_sha256=DIGESTS[3],
        provenance=ContractProvenance(
            origin="tests.retention-admission-lease",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
            input_digests=(request.digest, policy.digest, DIGESTS[2]),
            trace_id="retention-admission-trace",
        ),
    )
    return request, policy, lease


def _preflight(
    execution: EffectExecutionRequest,
    lease: EffectLease,
) -> ProviderTargetReceiptRetentionPreflightReceipt:
    return ProviderTargetReceiptRetentionPreflightReceipt(
        source_revision=REVISION,
        repository_head_receipt_sha256=DIGESTS[4],
        provider_target_receipt_sha256=DIGESTS[5],
        retention_inventory_sha256=DIGESTS[6],
        retention_inventory_source_sha256=DIGESTS[7],
        retention_inventory_source_size=4096,
        retention_inventory_surface_count=7,
        retention_authority_sha256=DIGESTS[8],
        retention_subject_sha256=DIGESTS[9],
        retention_execution_request_sha256=execution.digest,
        retention_effect_lease_sha256=lease.digest,
        guard_contract=RETENTION_GUARD_CONTRACT,
        guard_evidence=(
            f"authority_sha256={DIGESTS[8]};subject_sha256={DIGESTS[9]}"
        ),
        event_store_scope_path=EVENT_SCOPE,
        receipt_cas_scope_path=CAS_SCOPE,
    )


def _subjects(tmp_path: Path) -> SimpleNamespace:
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

    spine = object.__new__(SpineLedger)
    spine.path = event
    source_store = object.__new__(SourceTreeStore)
    source_store.root = cas
    ledger = object.__new__(ProviderTargetReceiptLedger)
    ledger.primary_checkout = repository
    ledger.spine = spine
    ledger.source_store = source_store

    execution = _execution()
    request, policy, lease = _lease_subjects()
    preflight = _preflight(execution, lease)
    receipt = _DigestSubject(preflight.provider_target_receipt_sha256)
    inventory = _DigestSubject(preflight.retention_inventory_sha256)
    authority = _DigestSubject(preflight.retention_authority_sha256)

    effect_ledger = object.__new__(EffectLeaseLedger)
    effect_ledger.path = effect_store
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=effect_ledger,
        lease_keyring={"retention-lease-key": b"x" * 32},
        guard_decisions=(
            GuardDecision(
                RETENTION_GUARD_CONTRACT,
                True,
                preflight.guard_evidence,
            ),
        ),
        kill_switch_generation_reader=lambda: 3,
        registry={},
    )
    return SimpleNamespace(
        repository=repository,
        retention_root=retention_root,
        event=event,
        cas=cas,
        effect_store=effect_store,
        spine=spine,
        source_store=source_store,
        ledger=ledger,
        preflight=preflight,
        receipt=receipt,
        inventory=inventory,
        authority=authority,
        execution=execution,
        authorization=authorization,
    )


def _install_preflight(
    monkeypatch: pytest.MonkeyPatch,
    subjects: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )


def _call(
    subjects: SimpleNamespace,
    *,
    event_scope: str = EVENT_SCOPE,
    cas_scope: str = CAS_SCOPE,
) -> ProviderTargetReceiptRetentionAdmissionReceipt:
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
    replay: EffectExecutionReplaySnapshot | None = None,
) -> tuple[ProviderTargetReceiptRetentionAdmissionReceipt, SimpleNamespace]:
    subjects = _subjects(tmp_path)
    _install_preflight(monkeypatch, subjects)
    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: replay,
    )
    return _call(subjects), subjects


def _start_receipt(subjects: SimpleNamespace) -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=subjects.authorization.lease.digest,
        execution_id=subjects.execution.execution_id,
        idempotency_key=subjects.execution.idempotency_key,
        execution_request_sha256=subjects.execution.digest,
        boundary_receipt_sha256=DIGESTS[10],
        started_at="2026-08-05T08:00:00.000000+00:00",
        receipt_sha256=DIGESTS[11],
    )


def test_not_started_admission_round_trip_is_non_executing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, subjects = _verify(tmp_path, monkeypatch)
    payload = result.to_dict()

    assert result.execution_state == "not_started"
    assert result.primary_checkout_path == os.fspath(subjects.repository.resolve())
    assert result.retention_root_path == os.fspath(subjects.retention_root.resolve())
    assert payload["persisted_effect_lease_verified"] is True
    assert payload["primary_checkout_disjointness_verified"] is True
    assert payload["retention_effect_started"] is False
    assert payload["retention_write_performed"] is False
    assert payload["automatic_reexecution_allowed"] is False
    assert payload["canonical_entrypoint_registered"] is False
    assert payload["gate_transition_authorized"] is False
    assert payload["closed"] is False
    assert ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload) == result


def test_started_replay_is_reported_without_terminal_or_reexecution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    replay = EffectExecutionReplaySnapshot(_start_receipt(subjects), "STARTED", None)
    _install_preflight(monkeypatch, subjects)
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
    start = _start_receipt(subjects)
    terminal = EffectTerminalReceipt(
        lease_sha256=subjects.authorization.lease.digest,
        execution_id=subjects.execution.execution_id,
        start_receipt_sha256=DIGESTS[11],
        outcome="COMPLETED",
        output_digests=(),
        detail_sha256=None,
        finished_at="2026-08-05T08:01:00.000000+00:00",
        receipt_sha256="a" * 64,
    )
    replay = EffectExecutionReplaySnapshot(start, "COMPLETED", terminal)
    _install_preflight(monkeypatch, subjects)
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


def test_final_preflight_refusal_fences_stale_revision_after_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    calls = {"preflight": 0, "replay": 0}

    def preflight(*args, **kwargs):
        calls["preflight"] += 1
        if calls["preflight"] == 2:
            raise ProviderTargetReceiptRetentionPreflightBindingError("HEAD moved")
        return subjects.preflight

    def replay(*args, **kwargs):
        calls["replay"] += 1
        return None

    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        preflight,
    )
    monkeypatch.setattr(admission_module, "inspect_effect_execution", replay)

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="preflight did not reverify",
    ):
        _call(subjects)
    assert calls == {"preflight": 2, "replay": 1}


def test_same_path_cas_identity_replacement_during_replay_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    _install_preflight(monkeypatch, subjects)
    displaced = tmp_path / "displaced-cas"

    def replace_identity(*args, **kwargs):
        subjects.cas.rename(displaced)
        subjects.cas.mkdir()
        return None

    monkeypatch.setattr(
        admission_module,
        "inspect_effect_execution",
        replace_identity,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="topology identity changed during persisted replay",
    ):
        _call(subjects)


def test_concrete_cas_scope_substitution_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    foreign_cas = tmp_path / "foreign-cas"
    foreign_cas.mkdir()
    subjects.source_store.root = foreign_cas
    _install_preflight(monkeypatch, subjects)
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
    _install_preflight(monkeypatch, subjects)

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
    _install_preflight(monkeypatch, subjects)

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


def test_detached_lease_request_refuses_before_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    object.__setattr__(subjects.authorization.lease, "request_id", "foreign-request")
    calls: list[str] = []

    def unexpected(*args, **kwargs):
        calls.append("preflight")
        raise AssertionError("preflight ran after detached lease request")

    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        unexpected,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="authority components are detached",
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
    _install_preflight(monkeypatch, subjects)
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
    subjects.spine.path = nested_event
    subjects.source_store.root = nested_cas
    _install_preflight(monkeypatch, subjects)
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


def test_non_exact_inner_ledger_and_replay_types_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    subjects.ledger.spine = SimpleNamespace(path=subjects.event)
    _install_preflight(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="spine must be exact SpineLedger",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "second")
    _install_preflight(monkeypatch, subjects)
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


def test_wire_claim_escalation_extra_fields_and_malformed_values_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _ = _verify(tmp_path, monkeypatch)

    for field in (
        "retention_write_performed",
        "automatic_reexecution_allowed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        payload = result.to_dict()
        payload[field] = True
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

    for field, value in (
        ("execution_state", []),
        ("source_revision", "f" * 64),
        ("guard_evidence", "detached"),
        ("event_store_path", "bad\npath"),
        ("event_store_path", "x" * 4097),
    ):
        payload = result.to_dict()
        payload[field] = value
        with pytest.raises(ProviderTargetReceiptRetentionAdmissionShapeError):
            ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload)
