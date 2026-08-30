# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_write_effect_lease as effect_module
from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_effect_lease import (
    EffectLeaseReplaySubject,
    RepositoryWriteEffectLeaseBindingError,
    RepositoryWriteEffectLeaseError,
    verify_repository_write_effect_leases,
)
from daedalus.gates.repository_write_evidence_materialization import (
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.gates.repository_write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceReport,
    RuntimeConformanceReplayRecord,
)
from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
POLICY_SHA = "b" * 64
SECRET = b"repository-write-effect-replay-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
ENTRYPOINT = "python.repository_write_fixture"
RUNTIME_RECEIPT_SHA = "c" * 64
RUNTIME_ID = "runtime-effect-fixture"
ORIGIN_SHA = "d" * 64


def _surface() -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path="daedalus/fixture.py",
        line=1,
        column=0,
        origin="base_v1",
        kind="call",
        callee="fixture.write",
        operation="write",
        blocking=True,
    )


def _authorization(tmp_path):
    registry = {
        ENTRYPOINT: EntrypointSpec(
            id=ENTRYPOINT,
            surface=Surface.PYTHON,
            target="daedalus.fixture:write",
            effects=(Effect.FILESYSTEM_WRITE,),
            guard_contracts=("containment.attempt",),
            wiring=Wiring.CENTRAL,
        )
    }
    scope = EffectScope(
        read_only=False,
        writable_paths=("candidate",),
        max_cost_microusd=0,
        timeout_s=60,
        max_concurrency=1,
        kill_switch_ref="fixture-kill",
    )
    request = EffectLeaseRequest(
        request_id="repository-write-effect-request",
        mission_id="repository-write-effect-mission",
        attempt_id="repository-write-effect-attempt",
        entrypoint_id=ENTRYPOINT,
        requested_effects=(Effect.FILESYSTEM_WRITE.value,),
        effect_scope=scope,
        idempotency_namespace="repository-write-effect",
        kill_switch_generation=3,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.repository-write-effect-lease",
            source_revision=REVISION,
            created_at=NOW.isoformat(timespec="microseconds"),
            input_digests=("e" * 64,),
            trace_id="repository-write-effect-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id="repository-write-effect-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded repository-write fixture",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.repository-write-effect-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(timespec="microseconds"),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="repository-write-effect-mission",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="repository-write-effect-lease",
        issuer_key_id="repository-write-effect-key",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
        registry=registry,
    )
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effects.sqlite3"),
        lease_keyring={"repository-write-effect-key": SECRET},
        guard_decisions=(
            GuardDecision(
                "containment.attempt",
                True,
                "artifact:sha256:" + "f" * 64,
            ),
        ),
        kill_switch_generation_reader=lambda: 3,
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id="repository-write-effect-execution",
        idempotency_key="repository-write-effect-idempotency",
        requested_effects=(Effect.FILESYSTEM_WRITE.value,),
        writable_paths=("candidate/output.json",),
        kill_switch_ref="fixture-kill",
        kill_switch_generation=3,
    )
    return authorization, execution


def _binding(
    kind: EvidenceKind,
    payload: dict[str, object],
    *,
    guard_contract: str = "",
) -> tuple[EvidenceBinding, bytes]:
    surface = _surface()
    surface_sha = surface_binding_sha256(REVISION, surface)
    provisional = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
        guard_contract=guard_contract,
    )
    document = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": kind.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha,
        "guard_contract": guard_contract,
        "subject_sha256": evidence_subject_sha256(provisional),
        "payload_sha256": hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest(),
        "payload": payload,
    }
    raw = canonical_json(document).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=kind,
            source_revision=REVISION,
            surface_sha256=surface_sha,
            sha256=digest,
            locator="cas:sha256:" + digest,
            guard_contract=guard_contract,
        ),
        raw,
    )


def _classification(
    terminal_sha: str,
    *,
    entrypoint_id: str = ENTRYPOINT,
    terminal_state: str = "completed",
):
    specs = (
        (
            EvidenceKind.SOURCE_ANCHOR,
            {
                "path": "daedalus/fixture.py",
                "line": 1,
                "column": 0,
                "source_sha256": "1" * 64,
            },
            "",
        ),
        (
            EvidenceKind.GUARD_CONTRACT,
            {
                "contract": "containment.attempt",
                "implementation_target": "daedalus.fixture:guard",
                "implementation_sha256": "2" * 64,
            },
            "containment.attempt",
        ),
        (
            EvidenceKind.EFFECT_LEASE_RECEIPT,
            {
                "receipt_schema": "daedalus-effect-lease-receipt/1",
                "receipt_sha256": terminal_sha,
                "entrypoint_id": entrypoint_id,
                "terminal_state": terminal_state,
            },
            "",
        ),
        (
            EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
            {
                "receipt_schema": "daedalus-runtime-conformance/1",
                "receipt_sha256": RUNTIME_RECEIPT_SHA,
                "runtime_id": RUNTIME_ID,
                "conformant": True,
            },
            "",
        ),
        (
            EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            {
                "receipt_schema": "daedalus-checkout-disjointness/1",
                "receipt_sha256": "3" * 64,
                "primary_checkout_sha256": "4" * 64,
                "target_root_sha256": "5" * 64,
                "disjoint": True,
            },
            "",
        ),
    )
    bindings: list[EvidenceBinding] = []
    blobs: dict[str, bytes] = {}
    for kind, payload, guard in specs:
        binding, raw = _binding(kind, payload, guard_contract=guard)
        bindings.append(binding)
        blobs[binding.locator] = raw
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=_surface(),
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("containment.attempt",),
        evidence=tuple(sorted(bindings, key=EvidenceBinding.sort_key)),
        notes="effect replay fixture",
    )
    report = RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="6" * 64,
        scan_input_sha256="7" * 64,
        inventory_surface_count=1,
        classifications=(row,),
        missing_surfaces=(),
    )
    return report, blobs


def _runtime_report(classification, blobs, *, materialization_digest=None):
    payload = {
        "surface_sha256": surface_binding_sha256(REVISION, _surface()),
        "locator": "cas:sha256:" + "8" * 64,
        "runtime_id": RUNTIME_ID,
        "envelope_sha256": "9" * 64,
        "trust_record_sha256": "a" * 64,
        "probe_identity_sha256": "b" * 64,
        "conformance_receipt_sha256": RUNTIME_RECEIPT_SHA,
        "runtime_manifest_sha256": "d" * 64,
        "observed_at": NOW.isoformat(timespec="microseconds"),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(timespec="microseconds"),
        "check_set_sha256": "e" * 64,
    }
    replay_sha = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    record = RuntimeConformanceReplayRecord(**payload, replay_sha256=replay_sha)
    runtime_set_sha = hashlib.sha256(
        canonical_json([record.to_dict()]).encode("ascii")
    ).hexdigest()
    materialization = materialize_repository_write_evidence(classification, blobs)
    return RepositoryWriteRuntimeConformanceReport(
        source_revision=REVISION,
        classification_digest=classification.digest,
        materialization_digest=(
            materialization.digest
            if materialization_digest is None
            else materialization_digest
        ),
        guard_structure_report_digest="f" * 64,
        origin_attestation_digest=ORIGIN_SHA,
        production_classification_count=1,
        runtime_subject_count=1,
        runtime_binding_count=1,
        runtime_set_sha256=runtime_set_sha,
        records=(record,),
    )


def _install_predecessor(monkeypatch, classification, blobs, **kwargs):
    report = _runtime_report(classification, blobs, **kwargs)
    monkeypatch.setattr(
        effect_module,
        "verify_repository_write_runtime_conformance",
        lambda *args, **call_kwargs: report,
    )


def _verify(classification, blobs, subjects, *, revision=REVISION):
    return verify_repository_write_effect_leases(
        classification,
        blobs,
        SimpleNamespace(digest=ORIGIN_SHA),
        object(),
        {},
        {},
        subjects,
        collector_keyring={},
        expected_collector_id="collector",
        guard_keyring={},
        expected_guard_authority_id="guard-authority",
        current_revision=revision,
        now=NOW,
        repository_root=SimpleNamespace(),
    )


def _terminal_fixture(tmp_path, outcome="completed"):
    authorization, execution = _authorization(tmp_path)
    authorization.grant()
    start = authorization.begin_effect(execution).receipt
    terminal = authorization.finish_effect(start, outcome=outcome)
    return authorization, execution, terminal


def test_exact_terminal_replay_does_not_claim_gate_closure(tmp_path, monkeypatch):
    authorization, execution, terminal = _terminal_fixture(tmp_path)
    classification, blobs = _classification(terminal.receipt_sha256)
    _install_predecessor(monkeypatch, classification, blobs)
    report = _verify(
        classification,
        blobs,
        {
            terminal.receipt_sha256: EffectLeaseReplaySubject(
                authorization,
                execution,
            )
        },
    )
    assert report.records[0].terminal_receipt_sha256 == terminal.receipt_sha256
    material = report.to_dict()
    assert material["effect_lease_semantics_verified"] is True
    for field in (
        "guard_contract_semantics_verified",
        "primary_checkout_disjointness_verified",
        "retirement_semantics_verified",
        "semantic_receipts_verified",
        "evidence_authenticated",
        "gate_report_bound",
        "closed",
    ):
        assert material[field] is False


def test_missing_start_refuses_automatic_reexecution(tmp_path, monkeypatch):
    authorization, execution = _authorization(tmp_path)
    authorization.grant()
    digest = "1" * 64
    classification, blobs = _classification(digest)
    _install_predecessor(monkeypatch, classification, blobs)
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="no durable start; automatic re-execution is forbidden",
    ):
        _verify(
            classification,
            blobs,
            {digest: EffectLeaseReplaySubject(authorization, execution)},
        )


def test_started_execution_refuses_automatic_reexecution(tmp_path, monkeypatch):
    authorization, execution = _authorization(tmp_path)
    authorization.grant()
    authorization.begin_effect(execution)
    digest = "2" * 64
    classification, blobs = _classification(digest)
    _install_predecessor(monkeypatch, classification, blobs)
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="not terminal; automatic re-execution is forbidden",
    ):
        _verify(
            classification,
            blobs,
            {digest: EffectLeaseReplaySubject(authorization, execution)},
        )


def test_terminal_digest_entrypoint_and_state_substitution_refuse(
    tmp_path, monkeypatch
):
    authorization, execution, terminal = _terminal_fixture(tmp_path)
    subject = EffectLeaseReplaySubject(authorization, execution)

    substituted = "3" * 64
    classification, blobs = _classification(substituted)
    _install_predecessor(monkeypatch, classification, blobs)
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="terminal receipt"):
        _verify(classification, blobs, {substituted: subject})

    classification, blobs = _classification(
        terminal.receipt_sha256,
        entrypoint_id="python.substituted",
    )
    _install_predecessor(monkeypatch, classification, blobs)
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="entrypoint"):
        _verify(classification, blobs, {terminal.receipt_sha256: subject})

    classification, blobs = _classification(
        terminal.receipt_sha256,
        terminal_state="failed",
    )
    _install_predecessor(monkeypatch, classification, blobs)
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="terminal state"):
        _verify(classification, blobs, {terminal.receipt_sha256: subject})


def test_exact_subject_set_and_revision_are_required(tmp_path, monkeypatch):
    authorization, execution, terminal = _terminal_fixture(tmp_path)
    classification, blobs = _classification(terminal.receipt_sha256)
    _install_predecessor(monkeypatch, classification, blobs)
    subject = EffectLeaseReplaySubject(authorization, execution)
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="subject set"):
        _verify(classification, blobs, {})
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="subject set"):
        _verify(
            classification,
            blobs,
            {terminal.receipt_sha256: subject, "4" * 64: subject},
        )
    with pytest.raises(RepositoryWriteEffectLeaseBindingError, match="stale"):
        _verify(
            classification,
            blobs,
            {terminal.receipt_sha256: subject},
            revision="0" * 40,
        )


def test_predecessor_detachment_refuses_before_effect_inspection(
    tmp_path, monkeypatch
):
    authorization, execution, terminal = _terminal_fixture(tmp_path)
    classification, blobs = _classification(terminal.receipt_sha256)
    _install_predecessor(
        monkeypatch,
        classification,
        blobs,
        materialization_digest="0" * 64,
    )
    inspected = {"value": False}

    def forbidden(*args, **kwargs):
        inspected["value"] = True
        raise AssertionError("effect replay ran after detached predecessor")

    monkeypatch.setattr(effect_module, "inspect_effect_execution", forbidden)
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="predecessor chain mismatch",
    ):
        _verify(
            classification,
            blobs,
            {
                terminal.receipt_sha256: EffectLeaseReplaySubject(
                    authorization,
                    execution,
                )
            },
        )
    assert inspected["value"] is False


def test_success_path_has_no_effect_writer_authority(tmp_path, monkeypatch):
    authorization, execution, terminal = _terminal_fixture(tmp_path)
    classification, blobs = _classification(terminal.receipt_sha256)
    _install_predecessor(monkeypatch, classification, blobs)

    def forbidden(*args, **kwargs):
        raise AssertionError("semantic replay invoked effect writer authority")

    for name in ("grant", "begin", "finish", "revoke"):
        monkeypatch.setattr(authorization.effect_ledger, name, forbidden)
    report = _verify(
        classification,
        blobs,
        {
            terminal.receipt_sha256: EffectLeaseReplaySubject(
                authorization,
                execution,
            )
        },
    )
    assert report.effect_binding_count == 1


def test_malformed_subject_mapping_and_one_shot_snapshot(tmp_path, monkeypatch):
    with pytest.raises(RepositoryWriteEffectLeaseError):
        effect_module._snapshot_subjects([])  # type: ignore[arg-type]
    with pytest.raises(RepositoryWriteEffectLeaseError):
        effect_module._snapshot_subjects({"not-a-digest": object()})  # type: ignore[dict-item]
    with pytest.raises(ValueError):
        EffectLeaseReplaySubject(object(), object())  # type: ignore[arg-type]

    authorization, execution, terminal = _terminal_fixture(tmp_path)
    classification, blobs = _classification(terminal.receipt_sha256)
    _install_predecessor(monkeypatch, classification, blobs)

    class OneShot(dict):
        calls = 0

        def items(self):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("effect subject mapping was read twice")
            return super().items()

    subjects = OneShot(
        {
            terminal.receipt_sha256: EffectLeaseReplaySubject(
                authorization,
                execution,
            )
        }
    )
    assert _verify(classification, blobs, subjects).effect_subject_count == 1
    assert subjects.calls == 1
