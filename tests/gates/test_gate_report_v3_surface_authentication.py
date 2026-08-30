# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The reporter counts unauthenticated surfaces, not a module-wide flag."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from daedalus.gates import report_v3
from daedalus.gates.repository_write_classification import (
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    _compose_authenticated_surfaces,
    authenticate_repository_write_surfaces,
    project_repository_write_classifications,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


REVISION = "a" * 40
SCAN = "b" * 64


def _surface(path: str, line: int) -> RepositoryWriteSurface:
    return RepositoryWriteSurface(
        path=path,
        line=line,
        column=4,
        origin="base_v1",
        kind="open_write",
        callee="open",
        operation="mode='wb'",
        blocking=True,
    )


def _inventory(*surfaces: RepositoryWriteSurface) -> RepositoryWriteInventoryV2:
    return RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256=SCAN,
        files_scanned=3,
        base_inventory_digest="c" * 64,
        stdlib_delta_digest="d" * 64,
        surfaces=tuple(sorted(surfaces)),
    )


def _evidence(
    kind: EvidenceKind, digit: str, surface: RepositoryWriteSurface
) -> EvidenceBinding:
    return EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        sha256=digit * 64,
        locator=f"cas:sha256:{digit * 64}",
    )


def _cleared(surface: RepositoryWriteSurface) -> SurfaceClassification:
    evidence = tuple(
        sorted(
            (
                _evidence(EvidenceKind.RETIREMENT_RECEIPT, "5", surface),
                _evidence(
                    EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT, "4", surface
                ),
            ),
            key=EvidenceBinding.sort_key,
        )
    )
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.RETIRED,
        production_reachable=False,
        guard_contracts=(),
        evidence=evidence,
        notes="cleared fixture",
    )


def _blocked(surface: RepositoryWriteSurface) -> SurfaceClassification:
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.PRIMARY_CHECKOUT,
        guard=GuardDisposition.INVENTORY_ONLY,
        production_reachable=True,
        guard_contracts=(),
        evidence=(),
        notes="blocked fixture",
    )


def _document(inventory: RepositoryWriteInventoryV2, *rows: SurfaceClassification):
    payload = []
    for row in rows:
        value = row.to_dict()
        value.pop("candidate_blockers")
        payload.append(value)
    return {
        "schema": "daedalus-gate0-repository-write-classification-input/1",
        "source_revision": inventory.source_revision,
        "inventory_digest": inventory.digest,
        "classifications": payload,
    }


def _classify(inventory, document):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "classification.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return report_v3._classify_repository_write_surfaces(inventory, path)


def test_unauthenticated_count_is_per_surface_not_a_module_flag() -> None:
    cleared_surface = _surface("daedalus/cleared.py", 7)
    blocked_surface = _surface("daedalus/blocked.py", 11)
    inventory = _inventory(cleared_surface, blocked_surface)
    document = _document(
        inventory, _cleared(cleared_surface), _blocked(blocked_surface)
    )

    failures, verdicts, schema = _classify(inventory, document)

    # One surface cleared, none authenticated: the count is 1, not 2, and not
    # the report-wide surface count.
    assert "classification:evidence-unauthenticated:1" in failures
    assert "classification:evidence-unauthenticated:2" not in failures
    assert "classification:gate-report-binding-missing" in failures
    assert schema == "daedalus-gate0-repository-write-classification/2"
    assert "cleared:retired:1" in verdicts
    # The blocked surface is still named in full; clearing never hides it.
    assert any(row.startswith("daedalus/blocked.py:11:4") for row in failures)
    # The count never travels alone: the cleared surface is named, with the
    # stages it still owes.  A stage that does not apply is not named.
    named = [
        row
        for row in failures
        if row.startswith("classification:surface-unauthenticated:")
    ]
    assert named == [
        "classification:surface-unauthenticated:daedalus/cleared.py:7:4:"
        "stages=anchor,conformity,materialization,origin"
    ]
    assert "guard" not in named[0]
    assert "lease" not in named[0]


def test_a_report_with_no_cleared_surface_carries_no_classification_row() -> None:
    blocked_surface = _surface("daedalus/blocked.py", 11)
    inventory = _inventory(blocked_surface)
    document = _document(inventory, _blocked(blocked_surface))

    failures, _, _ = _classify(inventory, document)

    assert not any(row.startswith("classification:") for row in failures)


def test_classification_payload_no_longer_names_a_module_wide_flag() -> None:
    surface = _surface("daedalus/cleared.py", 7)
    payload = project_repository_write_classifications(
        _inventory(surface), (_cleared(surface),)
    ).to_dict()
    assert "evidence_authenticated" not in payload


def test_forged_stage_payload_with_a_correct_classification_digest_clears_nothing() -> None:
    cleared_surface = _surface("daedalus/cleared.py", 7)
    inventory = _inventory(cleared_surface)
    row = _cleared(cleared_surface)
    projection = project_repository_write_classifications(inventory, (row,))

    # A hand-written result carrying the REAL classification digest and every
    # verified key a stage report could name.
    forged = {
        "schema": "daedalus-gate0-repository-write-classification/2",
        "source_revision": REVISION,
        "classification_digest": projection.digest,
        "materialization_digest": "1" * 64,
        "evidence_authenticated": True,
        "origin_authenticated": True,
        "source_anchor_semantics_verified": True,
        "guard_contract_structure_verified": True,
        "runtime_conformance_semantics_verified": True,
        "effect_lease_semantics_verified": True,
        "guard_contract_semantics_verified": True,
        "primary_checkout_disjointness_verified": True,
        "retirement_semantics_verified": True,
        "semantic_receipts_verified": True,
        "gate_report_bound": True,
        "closed": True,
        "records": [
            {
                "surface_sha256": surface_binding_sha256(REVISION, cleared_surface),
                "kind": "retirement_receipt",
            }
        ],
        "materialization_complete": True,
    }

    # There is no stage key it can enter through: the composition takes typed
    # objects, and every stage refuses a mapping.
    for stage in AuthenticationStage:
        with pytest.raises(RepositoryWriteClassificationError):
            _compose_authenticated_surfaces(projection, {stage: forged})

    # And the public entry has no parameter for one at all, under any name.
    for keyword in ("stage_reports", "reports", "stages"):
        with pytest.raises(TypeError):
            authenticate_repository_write_surfaces(
                projection, **{keyword: {AuthenticationStage.MATERIALIZATION: forged}}
            )

    # And there is no reporter locator for it either: handed in where a
    # declaration goes, it is refused and clears nothing.
    failures, _, _ = _classify(inventory, forged)
    assert "classification:input-refused" in failures
    assert any(row.startswith("daedalus/cleared.py:7:4") for row in failures)
    assert not any(
        row.startswith("classification:evidence-unauthenticated") for row in failures
    )
