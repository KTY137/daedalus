# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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


def _payload(kind: EvidenceKind, guard: str = "") -> dict[str, object]:
    values: dict[EvidenceKind, dict[str, object]] = {
        EvidenceKind.SOURCE_ANCHOR: {
            "path": "daedalus/example.py",
            "line": 1,
            "column": 0,
            "source_sha256": SHA,
        },
        EvidenceKind.GUARD_CONTRACT: {
            "contract": guard,
            "implementation_target": "daedalus.guard:verify",
            "implementation_sha256": SHA,
        },
        EvidenceKind.EFFECT_LEASE_RECEIPT: {
            "receipt_schema": "daedalus-effect-lease-receipt/1",
            "receipt_sha256": SHA,
            "entrypoint_id": "runtime.example",
            "terminal_state": "completed",
        },
        EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT: {
            "receipt_schema": "daedalus-runtime-conformance/1",
            "receipt_sha256": SHA,
            "runtime_id": "runtime-example",
            "conformant": True,
        },
        EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT: {
            "receipt_schema": "daedalus-checkout-disjointness/1",
            "receipt_sha256": SHA,
            "primary_checkout_sha256": "b" * 64,
            "target_root_sha256": "c" * 64,
            "disjoint": True,
        },
        EvidenceKind.RETIREMENT_RECEIPT: {
            "receipt_schema": "daedalus-retirement-receipt/1",
            "receipt_sha256": SHA,
            "retired_target": "daedalus.example:write",
            "production_reachable": False,
        },
    }
    return values[kind]


def _binding_document(
    kind: EvidenceKind,
    surface: RepositoryWriteSurface,
    *,
    payload: dict[str, object] | None = None,
    guard: str = "",
) -> tuple[EvidenceBinding, bytes, dict[str, object]]:
    surface_sha = surface_binding_sha256(REVISION, surface)
    provisional = EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_sha,
        sha256="0" * 64,
        locator="cas:sha256:" + "0" * 64,
        guard_contract=guard,
    )
    payload = _payload(kind, guard) if payload is None else payload
    document: dict[str, object] = {
        "schema": "daedalus-gate0-repository-write-evidence-object/1",
        "kind": kind.value,
        "source_revision": REVISION,
        "surface_sha256": surface_sha,
        "guard_contract": guard,
        "subject_sha256": evidence_subject_sha256(provisional),
        "payload_sha256": hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest(),
        "payload": payload,
    }
    return _rebind(provisional, document) + (document,)


def _rebind(
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


def _row(
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


def _report(*rows: SurfaceClassification) -> RepositoryWriteClassificationReport:
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
    guard: str = "",
) -> tuple[
    RepositoryWriteClassificationReport,
    EvidenceBinding,
    bytes,
    dict[str, object],
]:
    surface = _surface()
    binding, raw, document = _binding_document(
        kind, surface, payload=payload, guard=guard
    )
    return _report(_row(surface, (binding,))), binding, raw, document


def test_materializes_exact_canonical_blob_without_trust_escalation() -> None:
    report, binding, raw, _ = _one()
    result = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )
    assert result.materialization_complete is True
    assert result.records[0].blob_sha256 == binding.sha256
    assert result.records[0].subject_sha256 == evidence_subject_sha256(binding)
    material = result.to_dict()
    assert material["content_addressed"] is True
    assert material["canonical_bytes_verified"] is True
    assert material["binding_verified"] is True
    for field in (
        "origin_authenticated",
        "semantic_receipts_verified",
        "evidence_authenticated",
        "gate_report_bound",
        "closed",
    ):
        assert material[field] is False


@pytest.mark.parametrize("kind", list(EvidenceKind))
def test_all_evidence_kinds_have_strict_envelopes(kind: EvidenceKind) -> None:
    guard = "runtime.guard" if kind is EvidenceKind.GUARD_CONTRACT else ""
    report, binding, raw, _ = _one(kind, guard=guard)
    result = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )
    assert result.records[0].kind is kind


def test_missing_and_empty_binding_sets_remain_blocking() -> None:
    report, binding, _, _ = _one()
    missing = materialize_repository_write_evidence(report, {})
    assert missing.materialization_complete is False
    assert missing.missing_locators == (binding.locator,)
    missing_material = missing.to_dict()
    assert "evidence-blobs-missing" in missing_material["blockers"]
    assert missing_material["canonical_bytes_verified"] is False
    assert missing_material["binding_verified"] is False

    surface = _surface()
    empty = materialize_repository_write_evidence(
        _report(_row(surface, ())), {}
    )
    assert empty.binding_count == 0
    assert empty.materialization_complete is False
    assert "evidence-bindings-empty" in empty.to_dict()["blockers"]


def test_unexpected_locator_non_bytes_and_raw_digest_mismatch_refuse() -> None:
    report, binding, raw, _ = _one()
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            report,
            {
                binding.locator: raw,
                "cas:sha256:" + "f" * 64: b"{}",
            },
        )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            report, {binding.locator: raw.decode()}  # type: ignore[dict-item]
        )
    with pytest.raises(
        RepositoryWriteEvidenceMaterializationError, match="digest differs"
    ):
        materialize_repository_write_evidence(
            report, {binding.locator: raw + b" "}
        )


def test_noncanonical_and_duplicate_key_json_refuse_after_digest_rebinding() -> None:
    _, binding, _, document = _one()
    pretty = json.dumps(document, indent=2).encode()
    digest = hashlib.sha256(pretty).hexdigest()
    pretty_binding = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=digest,
        locator="cas:sha256:" + digest,
    )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (pretty_binding,))),
            {pretty_binding.locator: pretty},
        )

    duplicate = (
        b'{"schema":"daedalus-gate0-repository-write-evidence-object/1",'
        b'"schema":"duplicate"}'
    )
    digest = hashlib.sha256(duplicate).hexdigest()
    duplicate_binding = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=digest,
        locator="cas:sha256:" + digest,
    )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (duplicate_binding,))),
            {duplicate_binding.locator: duplicate},
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
    rebound, raw = _rebind(binding, mutated)
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (rebound,))),
            {rebound.locator: raw},
        )


def test_payload_digest_and_false_semantics_refuse() -> None:
    _, binding, _, document = _one()
    mutated = deepcopy(document)
    mutated["payload_sha256"] = "9" * 64
    rebound, raw = _rebind(binding, mutated)
    with pytest.raises(RepositoryWriteEvidenceMaterializationError):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (rebound,))),
            {rebound.locator: raw},
        )

    cases = (
        (
            EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
            {**_payload(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT), "conformant": False},
        ),
        (
            EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            {
                **_payload(EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT),
                "disjoint": False,
            },
        ),
        (
            EvidenceKind.RETIREMENT_RECEIPT,
            {
                **_payload(EvidenceKind.RETIREMENT_RECEIPT),
                "production_reachable": True,
            },
        ),
        (
            EvidenceKind.SOURCE_ANCHOR,
            {**_payload(EvidenceKind.SOURCE_ANCHOR), "path": "../escape.py"},
        ),
    )
    for index, (kind, payload) in enumerate(cases, start=2):
        surface = _surface(index)
        bad_binding, bad_raw, _ = _binding_document(
            kind, surface, payload=payload
        )
        with pytest.raises(RepositoryWriteEvidenceMaterializationError):
            materialize_repository_write_evidence(
                _report(_row(surface, (bad_binding,))),
                {bad_binding.locator: bad_raw},
            )


def test_nonfinite_and_oversized_json_refuse_inside_domain_boundary() -> None:
    report, binding, _, document = _one()
    canonical = canonical_json(document)
    nonfinite = canonical.replace(
        '"line":1', '"line":NaN', 1
    ).encode("ascii")
    digest = hashlib.sha256(nonfinite).hexdigest()
    rebound = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=digest,
        locator="cas:sha256:" + digest,
    )
    with pytest.raises(
        RepositoryWriteEvidenceMaterializationError,
        match="strict canonical JSON",
    ):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (rebound,))),
            {rebound.locator: nonfinite},
        )

    oversized = b" " * 1_048_577
    digest = hashlib.sha256(oversized).hexdigest()
    rebound = EvidenceBinding(
        kind=binding.kind,
        source_revision=binding.source_revision,
        surface_sha256=binding.surface_sha256,
        sha256=digest,
        locator="cas:sha256:" + digest,
    )
    with pytest.raises(
        RepositoryWriteEvidenceMaterializationError,
        match="bounded materialization size",
    ):
        materialize_repository_write_evidence(
            _report(_row(_surface(), (rebound,))),
            {rebound.locator: oversized},
        )


def test_reused_blob_digest_across_distinct_surfaces_refuses() -> None:
    first_surface = _surface()
    first, raw, _ = _binding_document(
        EvidenceKind.SOURCE_ANCHOR, first_surface
    )
    second_surface = _surface(2)
    forged = EvidenceBinding(
        kind=EvidenceKind.SOURCE_ANCHOR,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, second_surface),
        sha256=first.sha256,
        locator=first.locator,
    )
    report = _report(
        _row(first_surface, (first,)),
        _row(second_surface, (forged,)),
    )
    with pytest.raises(RepositoryWriteEvidenceMaterializationError, match="reused"):
        materialize_repository_write_evidence(
            report, {first.locator: raw}
        )


def test_report_digest_is_deterministic_and_classification_bound() -> None:
    report, binding, raw, _ = _one()
    first = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )
    second = materialize_repository_write_evidence(
        report, {binding.locator: raw}
    )
    assert first == second
    assert first.digest == second.digest
    assert first.classification_digest == report.digest
