from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

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
    RepositoryWriteEvidenceMaterializationError,
    evidence_subject_sha256,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.spine.envelope import canonical_json


REVISION = "1" * 40
SHA = "a" * 64


def _surface(index: int = 1) -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path=f"daedalus/example_{index}.py",
        line=index,
        column=0,
        origin="base_v1",
        kind="call",
        callee=f"example_{index}.write",
        operation="write",
        blocking=True,
    )


def _payload(kind: EvidenceKind, *, guard_contract: str = "") -> dict[str, object]:
    if kind is EvidenceKind.SOURCE_ANCHOR:
        return {
            "path": "daedalus/example.py",
            "line": 1,
            "column": 0,
            "source_sha256": SHA,
        }
    if kind is EvidenceKind.GUARD_CONTRACT:
        return {
            "contract": guard_contract,
            "implementation_target": "daedalus.guard:verify",
            "implementation_sha256": SHA,
        }
    if kind is EvidenceKind.EFFECT_LEASE_RECEIPT:
        return {
            "receipt_schema": "daedalus-effect-lease-receipt/1",
            "receipt_sha256": SHA,
            "entrypoint_id": "runtime.example",
            "terminal_state": "completed",
        }
    if kind is EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT:
        return {
            "receipt_schema": "daedalus-runtime-conformance/1",
            "receipt_sha256": SHA,
            "runtime_id": "runtime-example",
            "conformant": True,
        }
    if kind is EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT:
        return {
            "receipt_schema": "daedalus-checkout-disjointness/1",
            "receipt_sha256": SHA,
            "primary_checkout_sha256": "b" * 64,
            "target_root_sha256": "c" * 64,
            "disjoint": True,
        }
    if kind is EvidenceKind.RETIREMENT_RECEIPT:
        return {
            "receipt_schema": "daedalus-retirement-receipt/1",
            "receipt_sha256": SHA,
            "retired_target": "daedalus.example:write",
            "production_reachable": False,
        }
    raise AssertionError(kind)


def _binding_and_blob(
    kind: EvidenceKind,
    surface: RepositoryWriteSurface,
    *,
    payload: dict[str, object] | None = None,
    guard_contract: str = "",
) -> tuple[EvidenceBinding, bytes, dict[str, object]]:
    surface_sha256 = surface_binding_sha256(REVISION, surface)
    provisional = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
        guard_contract=guard_contract,
    )
    material = payload if payload is not None else _payload(
        kind, guard_contract=guard_contract
    )
    payload_sha256 = hashlib.sha256(
        canonical_json(material).encode("ascii")
    ).hexdigest()
    document: dict[str, object] = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": kind.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha256,
        "guard_contract": guard_contract,
        "subject_sha256": evidence_subject_sha256(provisional),
        "payload_sha256": payload_sha256,
        "payload": material,
    }
    raw = canonical_json(document).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    binding = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        sha256=digest,
        locator="cas:sha256:" + digest,
        guard_contract=guard_contract,
    )
    return binding, raw, document


def _binding_for_document(
    template: EvidenceBinding, document: dict[str, object]
) -> tuple[EvidenceBinding, bytes]:
    raw = canonical_json(document).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    return (
        EvidenceBinding(
            kind=template.kind,
            source_revision=template.source_revision,
            surface_sha256=template.surface_sha256,
            sha256=digest,
            locator="cas:sha256:" + digest,
            guard_contract=template.guard_contract,
        ),
        raw,
    )


def _classification(
    surface: RepositoryWriteSurface,
    evidence: tuple[EvidenceBinding, ...],
) -> SurfaceClassification:
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.UNKNOWN,
        guard=GuardDisposition.INVENTORY_ONLY,
        production_reachable=True,
        guard_contracts=(),
        evidence=tuple(sorted(evidence, key=EvidenceBinding.sort_key)),
        notes="materialization fixture",
    )


def _report(
    rows: tuple[SurfaceClassification, ...],
) -> RepositoryWriteClassificationReport:
    return RepositoryWriteClassificationReport(
        source_revision=REVISION,
        inventory_digest="d" * 64,
        scan_input_sha256="e" * 64,
        inventory_surface_count=len(rows),
        classifications=tuple(sorted(rows, key=SurfaceClassification.sort_key)),
        missing_surfaces=(),
    )


def _one(
    kind: EvidenceKind = EvidenceKind.SOURCE_ANCHOR,
    *,
    payload: dict[str, object] | None = None,
    guard_contract: str = "",
) -> tuple[RepositoryWriteClassificationReport, EvidenceBinding, bytes, dict[str, object]]:
    surface = _surface()
    binding, raw, document = _binding_and_blob(
        kind,
        surface,
        payload=payload,
        guard_contract=guard_contract,
    )
    return _report((_classification(surface, (binding,)),)), binding, raw, document


def test_materializes_exact_canonical_source_anchor() -> None:
    report, binding, raw, _ = _one()

    result = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )

    assert result.materialization_complete is True
    assert result.binding_count == 1
    assert result.records[0].blob_sha256 == binding.sha256
    assert result.records[0].subject_sha256 == evidence_subject_sha256(binding)
    material = result.to_dict()
    assert material["content_addressed"] is True
    assert material["canonical_bytes_verified"] is True
    assert material["binding_verified"] is True
    assert material["origin_authenticated"] is False
    assert material["semantic_receipts_verified"] is False
    assert material["evidence_authenticated"] is False
    assert material["gate_report_bound"] is False
    assert material["closed"] is False


@pytest.mark.parametrize("kind", list(EvidenceKind))
def test_accepts_every_typed_evidence_envelope(kind: EvidenceKind) -> None:
    guard = "runtime.guard" if kind is EvidenceKind.GUARD_CONTRACT else ""
    report, binding, raw, _ = _one(kind, guard_contract=guard)

    result = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )

    assert result.records[0].kind is kind


def test_missing_blob_is_reported_without_false_completeness() -> None:
    report, binding, _, _ = _one()

    result = materialize_repository_write_evidence(report, {})

    assert result.materialization_complete is False
    assert result.missing_locators == (binding.locator,)
    assert "evidence-blobs-missing" in result.to_dict()["blockers"]


def test_empty_binding_set_is_not_vacuously_complete() -> None:
    surface = _surface()
    report = _report((_classification(surface, ()),))

    result = materialize_repository_write_evidence(report, {})

    assert result.binding_count == 0
    assert result.materialization_complete is False
    assert "evidence-bindings-empty" in result.to_dict()["blockers"]


def test_unexpected_locator_and_non_bytes_refuse() -> None:
    report, binding, raw, _ = _one()
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            report, {binding.locator: raw, "cas:sha256:" + "f" * 64: b"{}"}
        )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(report, {binding.locator: raw.decode()})  # type: ignore[dict-item]


def test_raw_digest_mismatch_refuses_before_parsing() -> None:
    report, binding, raw, _ = _one()
    with pytest.raises(
        RepositoryWriteEvidenceMaterializationError,
        match="digest differs",
    ):
        materialize_repository_write_evidence(
            report, {binding.locator: raw + b" "}
        )


def test_noncanonical_and_duplicate_key_json_refuse_with_rebound_digest() -> None:
    report, binding, _, document = _one()
    pretty = json.dumps(document, indent=2).encode()
    pretty_digest = hashlib.sha256(pretty).hexdigest()
    pretty_binding = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=pretty_digest,
        locator="cas:sha256:" + pretty_digest,
    )
    pretty_report = _report((_classification(_surface(), (pretty_binding,)),))
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            pretty_report, {pretty_binding.locator: pretty}
        )

    duplicate = (
        b'{"schema":"daedalus-gate0-repository-write-evidence-object/1",'
        b'"schema":"duplicate"}'
    )
    duplicate_digest = hashlib.sha256(duplicate).hexdigest()
    duplicate_binding = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=duplicate_digest,
        locator="cas:sha256:" + duplicate_digest,
    )
    duplicate_report = _report((_classification(_surface(), (duplicate_binding,)),))
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            duplicate_report, {duplicate_binding.locator: duplicate}
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("kind", EvidenceKind.RETIREMENT_RECEIPT.value),
        ("source_revision", "2" * 40),
        ("surface_sha256", "3" * 64),
        ("guard_contract", "substituted.guard"),
        ("subject_sha256", "4" * 64),
    ],
)
def test_envelope_substitution_refuses_after_exact_blob_rebinding(
    field: str, replacement: str
) -> None:
    _, binding, _, document = _one()
    mutated = deepcopy(document)
    mutated[field] = replacement
    rebound, raw = _binding_for_document(binding, mutated)
    report = _report((_classification(_surface(), (rebound,)),))

    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(report, {rebound.locator: raw})


def test_payload_digest_and_kind_semantics_refuse() -> None:
    _, binding, _, document = _one()
    mutated = deepcopy(document)
    mutated["payload_sha256"] = "9" * 64
    rebound, raw = _binding_for_document(binding, mutated)
    report = _report((_classification(_surface(), (rebound,)),))
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(report, {rebound.locator: raw})

    cases = [
        (EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, {**_payload(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT), "conformant": False}),
        (EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT, {**_payload(EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT), "disjoint": False}),
        (EvidenceKind.RETIREMENT_RECEIPT, {**_payload(EvidenceKind.RETIREMENT_RECEIPT), "production_reachable": True}),
        (EvidenceKind.SOURCE_ANCHOR, {**_payload(EvidenceKind.SOURCE_ANCHOR), "path": "../escape.py"}),
    ]
    for index, (kind, payload) in enumerate(cases, start=2):
        surface = _surface(index)
        bad_binding, bad_raw, _ = _binding_and_blob(kind, surface, payload=payload)
        bad_report = _report((_classification(surface, (bad_binding,)),))
        with pytest.raises(RepositoryWriteEvidenceMaterializationError):
            materialize_repository_write_evidence(
                bad_report, {bad_binding.locator: bad_raw}
            )


def test_reused_blob_or_locator_across_bindings_refuses() -> None:
    surface = _surface()
    binding, raw, _ = _binding_and_blob(EvidenceKind.SOURCE_ANCHOR, surface)
    report = _report((_classification(surface, (binding, binding)),))
    with pytest.raises(ValueError, match="evidence must be unique"):
        _ = report

    surface_two = _surface(2)
    forged = EvidenceBinding(
        kind=EvidenceKind.SOURCE_ANCHOR,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface_two),
        sha256=binding.sha256,
        locator=binding.locator,
    )
    rows = (
        _classification(surface, (binding,)),
        _classification(surface_two, (forged,)),
    )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError, match="reused"):
        materialize_repository_write_evidence(
            _report(rows), {binding.locator: raw}
        )


def test_report_digest_is_deterministic_and_classification_bound() -> None:
    report, binding, raw, _ = _one()
    first = materialize_repository_write_evidence(report, {binding.locator: raw})
    second = materialize_repository_write_evidence(report, {binding.locator: raw})

    assert first == second
    assert first.digest == second.digest
    assert first.classification_digest == report.digest
