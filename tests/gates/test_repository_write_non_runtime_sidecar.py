"""Cross-process reconstruction of signed non-runtime conformity."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_INPUT_SCHEMA,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    issue_non_runtime_conformity_binding,
    project_classification_input,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.gates.repository_write_non_runtime_sidecar import (
    BINDING_SET_SCHEMA,
    RepositoryWriteNonRuntimeBindingSet,
    RepositoryWriteNonRuntimeSidecarError,
    load_repository_write_non_runtime_binding_set,
    project_classification_input_with_non_runtime_sidecar,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
SCAN = "b" * 64
SECRET = b"non-runtime-sidecar-secret-at-least-32-bytes"
ISSUED = "2026-08-29T14:20:00.000000+00:00"


def _surface(*, path: str = "daedalus/example.py") -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path=path,
        line=7,
        column=4,
        origin="base_v1",
        kind="open_write",
        callee="open",
        operation="mode='wb'",
        blocking=True,
    )


def _inventory(surface: RepositoryWriteSurface) -> RepositoryWriteInventoryV2:
    return RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256=SCAN,
        files_scanned=3,
        base_inventory_digest="c" * 64,
        stdlib_delta_digest="d" * 64,
        surfaces=(surface,),
    )


def _evidence(
    surface: RepositoryWriteSurface,
    kind: EvidenceKind,
    digit: str,
    *,
    guard_contract: str = "",
) -> EvidenceBinding:
    return EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        sha256=digit * 64,
        locator=f"cas:sha256:{digit * 64}",
        guard_contract=guard_contract,
    )


def _row_document(
    surface: RepositoryWriteSurface,
    *,
    runtime_receipt: bool,
) -> dict[str, object]:
    evidence = [
        _evidence(
            surface,
            EvidenceKind.GUARD_CONTRACT,
            "1",
            guard_contract="containment.attempt",
        ),
        _evidence(surface, EvidenceKind.EFFECT_LEASE_RECEIPT, "2"),
        _evidence(
            surface,
            EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
            "3",
        ),
    ]
    if runtime_receipt:
        evidence.append(
            _evidence(surface, EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "4")
        )
    evidence = sorted(evidence, key=EvidenceBinding.sort_key)
    return {
        "source_revision": REVISION,
        "surface": surface.to_dict(),
        "target": TargetDisposition.CHECKOUT_EXTERNAL.value,
        "guard": GuardDisposition.CENTRAL.value,
        "production_reachable": True,
        "guard_contracts": ["containment.attempt"],
        "evidence": [item.to_dict() for item in evidence],
        "notes": "signed non-runtime sidecar fixture",
    }


def _document(
    inventory: RepositoryWriteInventoryV2,
    row: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": CLASSIFICATION_INPUT_SCHEMA,
        "source_revision": REVISION,
        "inventory_digest": inventory.digest,
        "classifications": [row],
    }


def _binding(surface: RepositoryWriteSurface, *, execution_id: str = "execution.1"):
    return issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        execution_id=execution_id,
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED,
        secret=SECRET,
    )


def _set(
    inventory: RepositoryWriteInventoryV2,
    *bindings,
) -> RepositoryWriteNonRuntimeBindingSet:
    return RepositoryWriteNonRuntimeBindingSet(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        bindings=tuple(
            sorted(bindings, key=lambda item: (item.surface_sha256, item.execution_id))
        ),
    )


def _patch_replay(monkeypatch: pytest.MonkeyPatch):
    import daedalus.gates.repository_write_effect_lease as effect_lease

    seen: list[tuple[object, str]] = []

    def replay(subject, *, expected_execution_id: str):
        seen.append((subject, expected_execution_id))
        return object()

    monkeypatch.setattr(effect_lease, "replay_non_runtime_effect_subject", replay)
    return seen


def test_binding_set_round_trip_and_exact_canonical_loader(tmp_path: Path) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    binding_set = _set(inventory, _binding(surface))
    payload = binding_set.to_dict()

    assert payload["schema"] == BINDING_SET_SCHEMA
    assert payload["binding_count"] == 1
    assert RepositoryWriteNonRuntimeBindingSet.from_dict(payload) == binding_set

    path = tmp_path / "bindings.json"
    path.write_bytes(canonical_json(payload).encode("ascii"))
    assert load_repository_write_non_runtime_binding_set(path) == binding_set

    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="non-canonical",
    ):
        load_repository_write_non_runtime_binding_set(path)


def test_signed_sidecar_allows_runtime_receipt_to_be_absent_only_after_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = _binding(surface)
    binding_set = _set(inventory, binding)
    subject = object()
    seen = _patch_replay(monkeypatch)

    with pytest.raises(RepositoryWriteClassificationError):
        project_classification_input(inventory, document)

    projection = project_classification_input_with_non_runtime_sidecar(
        inventory,
        document,
        binding_set,
        subjects={binding.execution_id: subject},
        collector_secrets={binding.collector_key_id: SECRET},
    )

    assert len(projection.classifications) == 1
    row = projection.classifications[0]
    assert type(row) is SurfaceClassification
    assert row.non_runtime_conformity is not None
    assert row.non_runtime_conformity.execution_id == binding.execution_id
    assert seen == [(subject, binding.execution_id)]
    assert all(
        item.kind is not EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT
        for item in row.evidence
    )


def test_tampered_binding_signature_is_refused_before_row_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = dataclasses.replace(_binding(surface), signature_sha256="0" * 64)
    binding_set = _set(inventory, binding)
    seen = _patch_replay(monkeypatch)

    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="signature or retained replay was refused",
    ):
        project_classification_input_with_non_runtime_sidecar(
            inventory,
            document,
            binding_set,
            subjects={binding.execution_id: object()},
            collector_secrets={binding.collector_key_id: SECRET},
        )
    assert seen == []


def test_missing_retained_execution_subject_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = _binding(surface)
    binding_set = _set(inventory, binding)
    _patch_replay(monkeypatch)

    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="no retained execution subject",
    ):
        project_classification_input_with_non_runtime_sidecar(
            inventory,
            document,
            binding_set,
            subjects={},
            collector_secrets={binding.collector_key_id: SECRET},
        )


def test_runtime_and_non_runtime_claims_cannot_satisfy_same_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    binding = _binding(surface)
    binding_set = _set(inventory, binding)
    _patch_replay(monkeypatch)

    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="sidecar-admitted surface classification is invalid",
    ):
        project_classification_input_with_non_runtime_sidecar(
            inventory,
            document,
            binding_set,
            subjects={binding.execution_id: object()},
            collector_secrets={binding.collector_key_id: SECRET},
        )


def test_binding_set_is_exactly_bound_to_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=False))
    binding = _binding(surface)
    foreign = dataclasses.replace(
        _set(inventory, binding),
        inventory_digest="f" * 64,
    )
    _patch_replay(monkeypatch)

    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="another inventory",
    ):
        project_classification_input_with_non_runtime_sidecar(
            inventory,
            document,
            foreign,
            subjects={binding.execution_id: object()},
            collector_secrets={binding.collector_key_id: SECRET},
        )


def test_unused_sidecar_binding_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    # The ordinary row is valid on its own, so failure must come from the
    # foreign/unused sidecar rather than from the row parser.
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    foreign_surface = _surface(path="daedalus/foreign.py")
    binding = _binding(foreign_surface, execution_id="execution.foreign")
    binding_set = _set(inventory, binding)
    _patch_replay(monkeypatch)

    with pytest.raises(
        RepositoryWriteNonRuntimeSidecarError,
        match="surface absent from classification",
    ):
        project_classification_input_with_non_runtime_sidecar(
            inventory,
            document,
            binding_set,
            subjects={binding.execution_id: object()},
            collector_secrets={binding.collector_key_id: SECRET},
        )


def test_empty_sidecar_preserves_existing_classification_projection() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    document = _document(inventory, _row_document(surface, runtime_receipt=True))
    binding_set = _set(inventory)

    ordinary = project_classification_input(inventory, document)
    sidecar = project_classification_input_with_non_runtime_sidecar(
        inventory,
        document,
        binding_set,
        subjects={},
        collector_secrets={},
    )
    assert sidecar.to_dict() == ordinary.to_dict()
