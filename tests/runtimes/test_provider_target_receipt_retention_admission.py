from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

import daedalus.runtimes.provider_target_receipt_retention_admission as admission_module
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effect_replay import EffectExecutionReplaySnapshot
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseError,
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
_OPEN_SPINES: list[SpineLedger] = []


@pytest.fixture(autouse=True)
def _close_spines_after_test():
    yield
    while _OPEN_SPINES:
        _OPEN_SPINES.pop().close()


class _DigestSubject:
    def __init__(self, digest: str) -> None:
        self.digest = digest


def _new_spine(path: Path) -> SpineLedger:
    spine = SpineLedger(path)
    _OPEN_SPINES.append(spine)
    return spine


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
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    repository.mkdir()
    retention_root = tmp_path / "retention"
    event = retention_root / EVENT_SCOPE
    event.parent.mkdir(parents=True)
    spine = _new_spine(event)
    source_store = SourceTreeStore(retention_root / CAS_SCOPE)
    effect_ledger = EffectLeaseLedger(tmp_path / "effect-leases.sqlite3")

    ledger = object.__new__(ProviderTargetReceiptLedger)
    ledger.primary_checkout = repository
    ledger.spine = spine
    ledger.source_store = source_store

    execution = _execution()
    request, policy, lease = _lease_subjects()
    preflight = _preflight(execution, lease)
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
        cas=source_store.root,
        objects=source_store.objects,
        effect_store=effect_ledger.path,
        spine=spine,
        source_store=source_store,
        ledger=ledger,
        preflight=preflight,
        receipt=_DigestSubject(preflight.provider_target_receipt_sha256),
        inventory=_DigestSubject(preflight.retention_inventory_sha256),
        authority=_DigestSubject(preflight.retention_authority_sha256),
        execution=execution,
        authorization=authorization,
    )


def _install(
    monkeypatch: pytest.MonkeyPatch,
    subjects: SimpleNamespace,
    *,
    replay: EffectExecutionReplaySnapshot | None | Callable[..., object] = None,
    verify: Callable[[NonRuntimeEffectAuthorization], None] | None = None,
) -> None:
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        lambda *args, **kwargs: subjects.preflight,
    )
    monkeypatch.setattr(
        NonRuntimeEffectAuthorization,
        "verify",
        verify or (lambda self: None),
    )
    replay_call = replay if callable(replay) else (lambda *args, **kwargs: replay)
    monkeypatch.setattr(admission_module, "inspect_effect_execution", replay_call)


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


def _start(subjects: SimpleNamespace) -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=subjects.authorization.lease.digest,
        execution_id=subjects.execution.execution_id,
        idempotency_key=subjects.execution.idempotency_key,
        execution_request_sha256=subjects.execution.digest,
        boundary_receipt_sha256=DIGESTS[10],
        started_at="2026-08-05T08:00:00.000000+00:00",
        receipt_sha256=DIGESTS[11],
    )


def test_not_started_is_double_read_live_verified_and_non_authorizing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    calls = {"verify": 0, "replay": 0}

    def verify(self) -> None:
        calls["verify"] += 1

    def replay(*args, **kwargs):
        calls["replay"] += 1
        return None

    _install(monkeypatch, subjects, replay=replay, verify=verify)
    result = _call(subjects)
    payload = result.to_dict()

    assert calls == {"verify": 2, "replay": 2}
    assert result.execution_state == "not_started"
    assert result.event_store_path == os.fspath(subjects.event.resolve())
    assert payload["persisted_effect_lease_verified"] is True
    assert payload["primary_checkout_disjointness_verified"] is True
    assert payload["retention_effect_started"] is False
    for field in (
        "retention_write_performed",
        "automatic_reexecution_allowed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert payload[field] is False
    assert ProviderTargetReceiptRetentionAdmissionReceipt.from_dict(payload) == result


def test_unstarted_live_authority_refusal_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)

    def refuse(self) -> None:
        raise EffectLeaseError("expired")

    _install(monkeypatch, subjects, verify=refuse)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="not live and authentic",
    ):
        _call(subjects)


def test_started_and_terminal_replay_do_not_use_current_lease_validity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started_subjects = _subjects(tmp_path / "started")
    started = EffectExecutionReplaySnapshot(_start(started_subjects), "STARTED", None)

    def unexpected(self) -> None:
        raise AssertionError("historical replay used live lease verification")

    _install(monkeypatch, started_subjects, replay=started, verify=unexpected)
    result = _call(started_subjects)
    assert result.execution_state == "started"
    assert result.start_receipt_sha256 == DIGESTS[11]
    assert result.terminal_receipt_sha256 is None

    terminal_subjects = _subjects(tmp_path / "terminal")
    start = _start(terminal_subjects)
    terminal = EffectTerminalReceipt(
        lease_sha256=terminal_subjects.authorization.lease.digest,
        execution_id=terminal_subjects.execution.execution_id,
        start_receipt_sha256=DIGESTS[11],
        outcome="COMPLETED",
        output_digests=(),
        detail_sha256=None,
        finished_at="2026-08-05T08:01:00.000000+00:00",
        receipt_sha256="a" * 64,
    )
    _install(
        monkeypatch,
        terminal_subjects,
        replay=EffectExecutionReplaySnapshot(start, "COMPLETED", terminal),
        verify=unexpected,
    )
    result = _call(terminal_subjects)
    assert result.execution_state == "COMPLETED"
    assert result.terminal_receipt_sha256 == "a" * 64


def test_initial_and_final_stale_preflight_refuse_at_ordered_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path / "initial")
    calls: list[str] = []

    def initial_refusal(*args, **kwargs):
        calls.append("preflight")
        raise ProviderTargetReceiptRetentionPreflightBindingError("stale revision")

    def unexpected(*args, **kwargs):
        calls.append("replay")
        raise AssertionError("replay ran after stale preflight")

    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        initial_refusal,
    )
    monkeypatch.setattr(admission_module, "inspect_effect_execution", unexpected)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="preflight did not reverify",
    ):
        _call(subjects)
    assert calls == ["preflight"]

    subjects = _subjects(tmp_path / "final")
    counts = {"preflight": 0, "replay": 0}

    def final_refusal(*args, **kwargs):
        counts["preflight"] += 1
        if counts["preflight"] == 2:
            raise ProviderTargetReceiptRetentionPreflightBindingError("HEAD moved")
        return subjects.preflight

    def replay(*args, **kwargs):
        counts["replay"] += 1
        return None

    monkeypatch.setattr(NonRuntimeEffectAuthorization, "verify", lambda self: None)
    monkeypatch.setattr(
        admission_module,
        "verify_provider_target_receipt_retention_preflight",
        final_refusal,
    )
    monkeypatch.setattr(admission_module, "inspect_effect_execution", replay)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="preflight did not reverify",
    ):
        _call(subjects)
    assert counts == {"preflight": 2, "replay": 1}


def test_persisted_execution_change_between_reads_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    values = iter((None, EffectExecutionReplaySnapshot(_start(subjects), "STARTED", None)))
    _install(monkeypatch, subjects, replay=lambda *args, **kwargs: next(values))

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="execution changed during admission",
    ):
        _call(subjects)


def test_same_path_cas_identity_replacement_during_replay_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path)
    displaced = tmp_path / "displaced-cas"

    def replace_identity(*args, **kwargs):
        subjects.cas.rename(displaced)
        subjects.objects.mkdir(parents=True)
        return None

    _install(monkeypatch, subjects, replay=replace_identity)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="topology identity changed during persisted replay",
    ):
        _call(subjects)


def test_spine_declared_path_must_match_live_sqlite_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path / "subjects")
    foreign = _new_spine(tmp_path / "foreign" / "spine.sqlite3")
    subjects.spine.path = foreign.path
    _install(monkeypatch, subjects)

    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="detached from its live SQLite connection",
    ):
        _call(subjects)


def test_cas_scope_object_target_spine_mode_and_primary_overlap_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path / "scope")
    foreign_store = SourceTreeStore(tmp_path / "foreign-cas")
    subjects.ledger.source_store = foreign_store
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="receipt_cas_scope_path does not bind",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "objects")
    subjects.source_store.objects = SourceTreeStore(
        tmp_path / "detached-object-store"
    ).objects
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="objects are detached",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "readonly")
    subjects.spine.read_only = True
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="spine must be writable",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "overlap")
    nested_root = subjects.repository / "retention"
    nested_spine = _new_spine(nested_root / EVENT_SCOPE)
    nested_store = SourceTreeStore(nested_root / CAS_SCOPE)
    subjects.retention_root = nested_root
    subjects.ledger.spine = nested_spine
    subjects.ledger.source_store = nested_store
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="retention_root must be outside the Primary Checkout",
    ):
        _call(subjects)


def test_hardlink_noncanonical_guard_authority_and_exact_type_bypasses_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _subjects(tmp_path / "hardlink")
    alias = tmp_path / "effect-leases-alias.sqlite3"
    try:
        os.link(subjects.effect_store, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {exc}")
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="Effect-Lease store must have one filesystem identity",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "scope-path")
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="canonical non-root repository-relative POSIX",
    ):
        _call(subjects, cas_scope="cas//receipts")

    subjects = _subjects(tmp_path / "guard")
    object.__setattr__(
        subjects.authorization,
        "guard_decisions",
        (GuardDecision(RETENTION_GUARD_CONTRACT, True, "detached"),),
    )
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="guard is detached",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "authority")
    object.__setattr__(subjects.authorization.lease, "request_id", "foreign-request")
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionBindingError,
        match="authority components are detached",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "inner")
    subjects.ledger.spine = SimpleNamespace(path=subjects.event)
    _install(monkeypatch, subjects)
    with pytest.raises(
        ProviderTargetReceiptRetentionAdmissionShapeError,
        match="spine must be exact SpineLedger",
    ):
        _call(subjects)

    subjects = _subjects(tmp_path / "replay")
    _install(
        monkeypatch,
        subjects,
        replay=lambda *args, **kwargs: SimpleNamespace(state="STARTED"),
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
    subjects = _subjects(tmp_path)
    _install(monkeypatch, subjects)
    result = _call(subjects)

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
