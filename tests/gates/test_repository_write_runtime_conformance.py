from __future__ import annotations

import contextlib
import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.gates.repository_write_runtime_conformance as runtime_replay
from daedalus.gates.guard_implementation_manifest import (
    GuardImplementationRecord,
    issue_guard_implementation_manifest,
)
from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_evidence_materialization import (
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_evidence_origin import (
    issue_repository_write_evidence_origin_attestation,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.gates.repository_write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceBindingError,
    RepositoryWriteRuntimeConformanceError,
    RuntimeConformanceSubject,
    verify_repository_write_runtime_conformance,
)
from daedalus.runtimes.profiles import (
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ConformanceCheck,
    ContractProvenance,
    ResourceUsage,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeManifest,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
COLLECTOR_SECRET = b"runtime-replay-collector-secret-" * 2
GUARD_SECRET = b"runtime-replay-guard-secret-" * 2
TRUST_SECRET = b"runtime-replay-ledger-secret-" * 2
ISSUED = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)
NOW = ISSUED + timedelta(minutes=2)
CONTRACT = "containment.attempt"
RUNTIME_ID = "fixture_runtime"
SURFACE_PATH = "daedalus/example.py"
SURFACE_SOURCE = b"def write_event(path):\n    path.write_text('event')\n"
IMPLEMENTATION_PATH = "daedalus/guard_impl.py"
IMPLEMENTATION_TARGET = "daedalus.guard_impl:Guard.check"
IMPLEMENTATION_SOURCE = (
    b"class Guard:\n"
    b"    def check(self, value):\n"
    b"        return bool(value)\n"
)
COMPONENTS = {
    "profile": "1" * 64,
    "adapter": "2" * 64,
    "executable": "3" * 64,
    "environment": "4" * 64,
    "fixture": "5" * 64,
}


def _surface() -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path=SURFACE_PATH,
        line=2,
        column=4,
        origin="base_v1",
        kind="path_method",
        callee="write_text",
        operation="write_text",
        blocking=True,
    )


def _evidence(
    surface: RepositoryWriteSurface,
    *,
    kind: EvidenceKind,
    payload: dict[str, object],
    contract: str = "",
) -> tuple[EvidenceBinding, bytes]:
    surface_sha256 = surface_binding_sha256(REVISION, surface)
    placeholder = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
        guard_contract=contract,
    )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    envelope = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": kind.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha256,
        "guard_contract": contract,
        "subject_sha256": evidence_subject_sha256(placeholder),
        "payload_sha256": payload_sha256,
        "payload": payload,
    }
    raw = canonical_json(envelope).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=kind,
            source_revision=REVISION,
            surface_sha256=surface_sha256,
            sha256=digest,
            locator=f"cas:sha256:{digest}",
            guard_contract=contract,
        ),
        raw,
    )


def _runtime_subject() -> RuntimeConformanceSubject:
    created = (ISSUED - timedelta(minutes=10)).isoformat(timespec="microseconds")
    component_digests = tuple(sorted(COMPONENTS.values()))
    manifest = RuntimeManifest(
        runtime_id=RUNTIME_ID,
        runtime_version="fixture-1",
        adapter_id="fixture_adapter",
        adapter_version="fixture-adapter-1",
        source_revision=REVISION,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            streaming=True,
            tool_events=True,
            structured_output=True,
            timeout=True,
            cancellation=True,
            cost_reporting=True,
        ),
        declared_tools=(),
        egress_transports=(),
        workspace_modes=("read-only",),
        cost_model="integer-microusd",
        provenance=ContractProvenance(
            origin="tests.runtime-manifest",
            source_revision=REVISION,
            created_at=created,
            input_digests=component_digests,
            trace_id="runtime-fixture",
        ),
    )
    identity = RuntimeProbeIdentity(
        probe_id="runtime-probe-1",
        runtime_id=RUNTIME_ID,
        authority="live-runtime",
        runtime_manifest_sha256=manifest.digest,
        profile_sha256=COMPONENTS["profile"],
        adapter_sha256=COMPONENTS["adapter"],
        executable_sha256=COMPONENTS["executable"],
        environment_sha256=COMPONENTS["environment"],
        fixture_suite_sha256=COMPONENTS["fixture"],
        source_revision=REVISION,
        collected_at=(ISSUED - timedelta(minutes=5)).isoformat(
            timespec="microseconds"
        ),
        provenance=ContractProvenance(
            origin="tests.runtime-probe",
            source_revision=REVISION,
            created_at=(ISSUED - timedelta(minutes=5)).isoformat(
                timespec="microseconds"
            ),
            input_digests=tuple(
                sorted((manifest.digest, *component_digests))
            ),
            trace_id="runtime-probe-1",
        ),
    )
    checks: list[ConformanceCheck] = []
    for name in sorted(RUNTIME_CONFORMANCE_CHECKS):
        digest = hashlib.sha256(f"runtime-check:{name}".encode("ascii")).hexdigest()
        checks.append(
            ConformanceCheck(
                name=name,
                passed=True,
                evidence_sha256=digest,
                evidence_locator=f"artifact-locator:sha256:{digest}",
                detail=f"fixture {name} passed",
            )
        )
    check_digests = tuple(check.evidence_sha256 for check in checks)
    receipt = RuntimeConformanceReceipt(
        receipt_id="runtime-receipt-1",
        runtime_manifest_sha256=manifest.digest,
        source_revision=REVISION,
        status="passed",
        checks=tuple(checks),
        started_at=(ISSUED - timedelta(minutes=4)).isoformat(
            timespec="microseconds"
        ),
        finished_at=ISSUED.isoformat(timespec="microseconds"),
        usage=ResourceUsage(wall_time_ms=100),
        provenance=ContractProvenance(
            origin="tests.runtime-receipt",
            source_revision=REVISION,
            created_at=ISSUED.isoformat(timespec="microseconds"),
            input_digests=tuple(
                sorted({manifest.digest, identity.digest, *check_digests})
            ),
            trace_id="runtime-receipt-1",
        ),
    )
    envelope = RuntimeConformanceEnvelope(
        envelope_id="runtime-envelope-1",
        runtime_id=RUNTIME_ID,
        authority="live-runtime",
        status="passed",
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256=receipt.digest,
        source_revision=REVISION,
        created_at=(ISSUED + timedelta(minutes=1)).isoformat(
            timespec="microseconds"
        ),
        provenance=ContractProvenance(
            origin="tests.runtime-envelope",
            source_revision=REVISION,
            created_at=(ISSUED + timedelta(minutes=1)).isoformat(
                timespec="microseconds"
            ),
            input_digests=tuple(
                sorted((manifest.digest, identity.digest, receipt.digest))
            ),
            trace_id="runtime-envelope-1",
        ),
    )
    return RuntimeConformanceSubject(
        envelope=envelope,
        identity=identity,
        receipt=receipt,
        manifest=manifest,
    )


def _classification(
    subject: RuntimeConformanceSubject,
    *,
    guard: GuardDisposition = GuardDisposition.CENTRAL,
    runtime_payload_runtime_id: str = RUNTIME_ID,
    runtime_payload_receipt_sha256: str | None = None,
    extra_runtime_binding: bool = False,
) -> tuple[RepositoryWriteClassificationReport, dict[str, bytes]]:
    surface = _surface()
    items: list[tuple[EvidenceBinding, bytes]] = [
        _evidence(
            surface,
            kind=EvidenceKind.SOURCE_ANCHOR,
            payload={
                "path": SURFACE_PATH,
                "line": 2,
                "column": 4,
                "source_sha256": hashlib.sha256(SURFACE_SOURCE).hexdigest(),
            },
        ),
        _evidence(
            surface,
            kind=EvidenceKind.GUARD_CONTRACT,
            contract=CONTRACT,
            payload={
                "contract": CONTRACT,
                "implementation_target": IMPLEMENTATION_TARGET,
                "implementation_sha256": hashlib.sha256(
                    IMPLEMENTATION_SOURCE
                ).hexdigest(),
            },
        ),
        _evidence(
            surface,
            kind=EvidenceKind.EFFECT_LEASE_RECEIPT,
            payload={
                "receipt_schema": "daedalus.effect-terminal-receipt",
                "receipt_sha256": "6" * 64,
                "entrypoint_id": "runtime.provider",
                "terminal_state": "completed",
            },
        ),
        _evidence(
            surface,
            kind=EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            payload={
                "receipt_schema": "daedalus.checkout-disjointness",
                "receipt_sha256": "7" * 64,
                "primary_checkout_sha256": "8" * 64,
                "target_root_sha256": "9" * 64,
                "disjoint": True,
            },
        ),
    ]
    runtime_payload = {
        "receipt_schema": RuntimeConformanceReceipt.CONTRACT_TYPE,
        "receipt_sha256": (
            subject.receipt.digest
            if runtime_payload_receipt_sha256 is None
            else runtime_payload_receipt_sha256
        ),
        "runtime_id": runtime_payload_runtime_id,
        "conformant": True,
    }
    items.append(
        _evidence(
            surface,
            kind=EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
            payload=runtime_payload,
        )
    )
    if extra_runtime_binding:
        items.append(
            _evidence(
                surface,
                kind=EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
                payload={**runtime_payload, "runtime_id": "other_runtime"},
            )
        )
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=guard,
        production_reachable=True,
        guard_contracts=(CONTRACT,),
        evidence=tuple(
            sorted(
                (binding for binding, _ in items),
                key=EvidenceBinding.sort_key,
            )
        ),
        notes="runtime semantic replay fixture",
    )
    report = RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="b" * 64,
        scan_input_sha256="c" * 64,
        inventory_surface_count=1,
        classifications=(row,),
        missing_surfaces=(),
    )
    return report, {binding.locator: raw for binding, raw in items}


def _guard_manifest(classification: RepositoryWriteClassificationReport):
    return issue_guard_implementation_manifest(
        (
            GuardImplementationRecord(
                contract=CONTRACT,
                implementation_target=IMPLEMENTATION_TARGET,
                implementation_sha256=hashlib.sha256(
                    IMPLEMENTATION_SOURCE
                ).hexdigest(),
            ),
        ),
        manifest_id="runtime-replay-guard-manifest",
        authority_id="gate.guard_registry",
        authority_key_id="guard.key.1",
        authority_secret=GUARD_SECRET,
        source_revision=REVISION,
        classification_digest=classification.digest,
        issued_at=ISSUED - timedelta(minutes=1),
        expires_at=ISSUED + timedelta(hours=1),
    )


def _attestation(
    classification: RepositoryWriteClassificationReport,
    blobs: dict[str, bytes],
):
    return issue_repository_write_evidence_origin_attestation(
        materialize_repository_write_evidence(classification, blobs),
        attestation_id="runtime-replay-origin-1",
        collector_id="gate.collector",
        collector_key_id="collector.key.1",
        collector_secret=COLLECTOR_SECRET,
        issued_at=ISSUED - timedelta(minutes=1),
        expires_at=ISSUED + timedelta(hours=1),
    )


def _write_tree(root: Path) -> None:
    surface_path = root / SURFACE_PATH
    surface_path.parent.mkdir(parents=True, exist_ok=True)
    surface_path.write_bytes(SURFACE_SOURCE)
    implementation_path = root / IMPLEMENTATION_PATH
    implementation_path.parent.mkdir(parents=True, exist_ok=True)
    implementation_path.write_bytes(IMPLEMENTATION_SOURCE)


def _trust_ledger(
    root: Path,
    subject: RuntimeConformanceSubject,
    *,
    expires_at: datetime | None = None,
) -> RuntimeTrustLedger:
    ledger = RuntimeTrustLedger(
        root / "runtime-trust.sqlite",
        integrity_key=TRUST_SECRET,
    )
    ledger.admit(
        subject.envelope,
        subject.identity,
        subject.receipt,
        subject.manifest,
        trusted_envelope_sha256s=(subject.envelope.digest,),
        admitted_at=ISSUED + timedelta(minutes=1),
        expires_at=expires_at or (ISSUED + timedelta(days=1)),
    )
    return ledger


def _verify(
    classification,
    blobs,
    attestation,
    manifest,
    subjects,
    ledgers,
    root: Path,
    **overrides: object,
):
    arguments = {
        "collector_keyring": {
            ("gate.collector", "collector.key.1"): COLLECTOR_SECRET
        },
        "expected_collector_id": "gate.collector",
        "guard_keyring": {
            ("gate.guard_registry", "guard.key.1"): GUARD_SECRET
        },
        "expected_guard_authority_id": "gate.guard_registry",
        "current_revision": REVISION,
        "now": NOW,
        "repository_root": root,
    }
    arguments.update(overrides)
    return verify_repository_write_runtime_conformance(
        classification,
        blobs,
        attestation,
        manifest,
        subjects,
        ledgers,
        **arguments,
    )


def _fixture(tmp_path: Path):
    _write_tree(tmp_path)
    subject = _runtime_subject()
    classification, blobs = _classification(subject)
    attestation = _attestation(classification, blobs)
    manifest = _guard_manifest(classification)
    ledger = _trust_ledger(tmp_path, subject)
    return subject, classification, blobs, attestation, manifest, ledger


def test_runtime_conformance_is_replayed_against_active_persisted_trust(
    tmp_path: Path,
) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    report = _verify(
        classification,
        blobs,
        attestation,
        manifest,
        {subject.receipt.digest: subject},
        {RUNTIME_ID: ledger},
        tmp_path,
    )
    payload = report.to_dict()
    assert payload["origin_authenticated"] is True
    assert payload["source_anchor_semantics_verified"] is True
    assert payload["guard_contract_structure_verified"] is True
    assert payload["runtime_conformance_semantics_verified"] is True
    assert payload["guard_contract_semantics_verified"] is False
    assert payload["effect_lease_semantics_verified"] is False
    assert payload["primary_checkout_disjointness_verified"] is False
    assert payload["retirement_semantics_verified"] is False
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert payload["production_classification_count"] == 1
    assert payload["runtime_subject_count"] == 1
    assert payload["runtime_binding_count"] == 1
    record = payload["records"][0]
    assert record["runtime_id"] == RUNTIME_ID
    assert record["envelope_sha256"] == subject.envelope.digest
    assert record["conformance_receipt_sha256"] == subject.receipt.digest
    assert record["runtime_manifest_sha256"] == subject.manifest.digest
    assert payload["blockers"] == [
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-behavioral-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
    ]
    assert report.to_dict() == _verify(
        classification,
        blobs,
        attestation,
        manifest,
        {subject.receipt.digest: subject},
        {RUNTIME_ID: ledger},
        tmp_path,
    ).to_dict()


def test_stale_revision_fails_before_runtime_projection(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="classification source revision is stale",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
            current_revision="d" * 40,
        )


def test_every_production_row_must_be_central(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    subject = _runtime_subject()
    classification, blobs = _classification(
        subject,
        guard=GuardDisposition.LOCAL_GUARDS,
    )
    ledger = _trust_ledger(tmp_path, subject)
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="must be centrally guarded",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _guard_manifest(classification),
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_duplicate_runtime_bindings_fail_before_subject_selection(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    subject = _runtime_subject()
    classification, blobs = _classification(
        subject,
        extra_runtime_binding=True,
    )
    ledger = _trust_ledger(tmp_path, subject)
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="exactly one runtime receipt",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _guard_manifest(classification),
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_runtime_subject_set_must_equal_retained_receipts(
    tmp_path: Path,
    mode: str,
) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    subjects = {} if mode == "missing" else {
        subject.receipt.digest: subject,
        "f" * 64: dataclasses.replace(subject),
    }
    with pytest.raises(
        RepositoryWriteRuntimeConformanceError,
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            subjects,
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_runtime_subject_key_must_equal_receipt_digest(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="key differs",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {"f" * 64: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_runtime_payload_identity_must_match_typed_manifest(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    subject = _runtime_subject()
    classification, blobs = _classification(
        subject,
        runtime_payload_runtime_id="other_runtime",
    )
    ledger = _trust_ledger(tmp_path, subject)
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="identity differs",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _guard_manifest(classification),
            {subject.receipt.digest: subject},
            {"other_runtime": ledger},
            tmp_path,
        )


def test_runtime_receipt_reference_must_have_exact_subject(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    subject = _runtime_subject()
    classification, blobs = _classification(
        subject,
        runtime_payload_receipt_sha256="f" * 64,
    )
    ledger = _trust_ledger(tmp_path, subject)
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="subject set differs",
    ):
        _verify(
            classification,
            blobs,
            _attestation(classification, blobs),
            _guard_manifest(classification),
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_trust_ledger_set_is_exact(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    for ledgers in ({}, {RUNTIME_ID: ledger, "extra_runtime": ledger}):
        with pytest.raises(
            RepositoryWriteRuntimeConformanceBindingError,
            match="ledger set differs",
        ):
            _verify(
                classification,
                blobs,
                attestation,
                manifest,
                {subject.receipt.digest: subject},
                ledgers,
                tmp_path,
            )


def test_unadmitted_quarantined_and_expired_trust_fail(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    empty = RuntimeTrustLedger(
        tmp_path / "empty-trust.sqlite",
        integrity_key=TRUST_SECRET,
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="exactly one persisted trust record",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: empty},
            tmp_path,
        )

    ledger.quarantine(
        runtime_id=RUNTIME_ID,
        envelope_sha256=subject.envelope.digest,
        reason="adversarial-test",
        quarantined_at=NOW,
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="persisted runtime trust binding mismatch",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )

    # The origin attestations expire at ISSUED+1h and are checked earlier, so a
    # trust record that outlives them can never reach the trust-expiry check.
    # Expire the trust record first and evaluate while the attestation is still
    # valid, so this case really exercises the trust binding.
    fresh = _trust_ledger(
        tmp_path / "fresh-ledger",
        subject,
        expires_at=ISSUED + timedelta(minutes=30),
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="trust record is expired",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: fresh},
            tmp_path,
            now=ISSUED + timedelta(minutes=45),
        )


def test_corrupt_persisted_trust_authentication_fails(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    with contextlib.closing(ledger._connect()) as connection:  # noqa: SLF001 - adversarial fixture
        connection.execute(
            "UPDATE runtime_trust_records SET record_hmac_sha256=?",
            ("f" * 64,),
        )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="audit projection failed authentication",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_predecessor_report_cannot_be_detached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    real = runtime_replay.verify_repository_write_guard_structure

    def detached(*args, **kwargs):
        report = real(*args, **kwargs)
        return dataclasses.replace(report, materialization_digest="f" * 64)

    monkeypatch.setattr(
        runtime_replay,
        "verify_repository_write_guard_structure",
        detached,
    )
    with pytest.raises(
        RepositoryWriteRuntimeConformanceBindingError,
        match="predecessor chain mismatch",
    ):
        _verify(
            classification,
            blobs,
            attestation,
            manifest,
            {subject.receipt.digest: subject},
            {RUNTIME_ID: ledger},
            tmp_path,
        )


def test_all_caller_mappings_are_snapshotted_once(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )

    class OneShot(dict):
        calls = 0

        def items(self):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("mapping was reread")
            return super().items()

    blob_map = OneShot(blobs)
    subject_map = OneShot({subject.receipt.digest: subject})
    ledger_map = OneShot({RUNTIME_ID: ledger})
    report = _verify(
        classification,
        blob_map,
        attestation,
        manifest,
        subject_map,
        ledger_map,
        tmp_path,
    )
    assert report.runtime_binding_count == 1
    assert blob_map.calls == subject_map.calls == ledger_map.calls == 1


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("blobs", []),
        ("runtime_subjects", []),
        ("runtime_trust_ledgers", []),
    ],
)
def test_malformed_mapping_inputs_fail_in_domain_boundary(
    tmp_path: Path,
    argument: str,
    value,
) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    values = {
        "classification": classification,
        "blobs": blobs,
        "origin_attestation": attestation,
        "guard_manifest": manifest,
        "runtime_subjects": {subject.receipt.digest: subject},
        "runtime_trust_ledgers": {RUNTIME_ID: ledger},
        "collector_keyring": {
            ("gate.collector", "collector.key.1"): COLLECTOR_SECRET
        },
        "expected_collector_id": "gate.collector",
        "guard_keyring": {
            ("gate.guard_registry", "guard.key.1"): GUARD_SECRET
        },
        "expected_guard_authority_id": "gate.guard_registry",
        "current_revision": REVISION,
        "now": NOW,
        "repository_root": tmp_path,
    }
    values[argument] = value
    with pytest.raises(RepositoryWriteRuntimeConformanceError):
        verify_repository_write_runtime_conformance(**values)


def test_report_record_set_cannot_be_detached(tmp_path: Path) -> None:
    subject, classification, blobs, attestation, manifest, ledger = _fixture(
        tmp_path
    )
    report = _verify(
        classification,
        blobs,
        attestation,
        manifest,
        {subject.receipt.digest: subject},
        {RUNTIME_ID: ledger},
        tmp_path,
    )
    with pytest.raises(ValueError, match="does not bind records"):
        dataclasses.replace(report, runtime_set_sha256="f" * 64)
