# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    parse_inventory_v2,
    project_classification_input,
    project_repository_write_classifications,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from scripts.report_repository_write_classification import main


REVISION = "a" * 40
SCAN = "b" * 64


def _surface(
    path: str = "daedalus/example.py",
    line: int = 7,
) -> RepositoryWriteSurface:
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
    kind: EvidenceKind,
    digit: str,
    surface: RepositoryWriteSurface,
    *,
    guard_contract: str = "",
) -> EvidenceBinding:
    return EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        sha256=digit * 64,
        locator=f"evidence/{kind.value}.json",
        guard_contract=guard_contract,
    )


def _central(surface: RepositoryWriteSurface) -> SurfaceClassification:
    evidence = tuple(
        sorted(
            (
                _evidence(
                    EvidenceKind.GUARD_CONTRACT,
                    "1",
                    surface,
                    guard_contract="containment.attempt",
                ),
                _evidence(EvidenceKind.EFFECT_LEASE_RECEIPT, "2", surface),
                _evidence(
                    EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT,
                    "3",
                    surface,
                ),
                _evidence(
                    EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                    "4",
                    surface,
                ),
            ),
            key=EvidenceBinding.sort_key,
        )
    )
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("containment.attempt",),
        evidence=evidence,
        notes="synthetic contract fixture",
    )


def _input(
    inventory: RepositoryWriteInventoryV2,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema": "daedalus-gate0-repository-write-classification-input/1",
        "source_revision": inventory.source_revision,
        "inventory_digest": inventory.digest,
        "classifications": rows,
    }


def _input_row(row: SurfaceClassification) -> dict[str, object]:
    value = row.to_dict()
    value.pop("candidate_blockers")
    return value


def test_missing_surface_remains_explicit_and_report_never_closes() -> None:
    surface = _surface()
    report = project_repository_write_classifications(_inventory(surface), ())

    material = report.to_dict()
    assert material["classification_ready"] is False
    assert material["closed"] is False
    # Revision 2 does not carry the key at all: authentication is per
    # surface and was never a property of this report.
    assert "evidence_authenticated" not in material
    assert material["primary_checkout_target_proven"] is False
    assert material["gate_report_bound"] is False
    assert material["missing_surfaces"] == [surface.to_dict()]
    assert "unclassified-production-write-surfaces" in material["blockers"]
    assert "authenticated-evidence-verification-missing" in material["blockers"]
    assert "gate-report-binding-missing" in material["blockers"]


def test_complete_candidate_classification_is_still_not_gate_evidence() -> None:
    surface = _surface()
    report = project_repository_write_classifications(
        _inventory(surface),
        (_central(surface),),
    )

    material = report.to_dict()
    assert material["classification_ready"] is True
    assert material["classification_count"] == 1
    assert material["closed"] is False
    assert material["primary_checkout_target_proven"] is False
    assert material["blockers"] == [
        "authenticated-evidence-verification-missing",
        "gate-report-binding-missing",
    ]
    assert report.digest == report.digest


def test_primary_checkout_and_noncentral_rows_remain_candidate_blockers() -> None:
    surface = _surface()
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.PRIMARY_CHECKOUT,
        guard=GuardDisposition.UNGUARDED,
        production_reachable=True,
        guard_contracts=(),
        evidence=(),
    )
    report = project_repository_write_classifications(_inventory(surface), (row,))

    assert report.classification_ready is False
    assert report.candidate_blockers == (
        "primary-checkout-write-target",
        "production-write-unguarded",
    )


def test_central_requires_exact_evidence_families() -> None:
    surface = _surface()
    row = _central(surface)
    for missing in row.evidence:
        with pytest.raises(
            ValueError,
            match=(
                "disjointness receipt|required evidence kinds|"
                "guard evidence does not match"
            ),
        ):
            replace(
                row,
                evidence=tuple(item for item in row.evidence if item != missing),
            )


def test_disjoint_target_requires_disjointness_receipt() -> None:
    surface = _surface()
    with pytest.raises(ValueError, match="disjointness receipt"):
        SurfaceClassification(
            source_revision=REVISION,
            surface=surface,
            target=TargetDisposition.NON_REPOSITORY,
            guard=GuardDisposition.INVENTORY_ONLY,
            production_reachable=True,
            guard_contracts=(),
            evidence=(),
        )


def test_retired_requires_nonreachable_and_retirement_receipt() -> None:
    surface = _surface()
    retirement = (
        _evidence(EvidenceKind.RETIREMENT_RECEIPT, "5", surface),
    )
    with pytest.raises(ValueError, match="production reachable"):
        SurfaceClassification(
            source_revision=REVISION,
            surface=surface,
            target=TargetDisposition.UNKNOWN,
            guard=GuardDisposition.RETIRED,
            production_reachable=True,
            guard_contracts=(),
            evidence=retirement,
        )
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.UNKNOWN,
        guard=GuardDisposition.RETIRED,
        production_reachable=False,
        guard_contracts=(),
        evidence=retirement,
    )
    assert row.candidate_blockers == ("write-target-unknown",)


def test_duplicate_and_absent_surfaces_refuse() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _central(surface)
    with pytest.raises(RepositoryWriteClassificationError, match="duplicated"):
        project_repository_write_classifications(inventory, (row, row))
    other = _surface("daedalus/other.py", 9)
    with pytest.raises(RepositoryWriteClassificationError, match="absent"):
        project_repository_write_classifications(inventory, (_central(other),))


def test_stale_revision_and_inventory_digest_refuse() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    row = _input_row(_central(surface))
    stale_revision = _input(inventory, [row])
    stale_revision["source_revision"] = "e" * 40
    with pytest.raises(RepositoryWriteClassificationError, match="revision is stale"):
        project_classification_input(inventory, stale_revision)

    stale_digest = _input(inventory, [row])
    stale_digest["inventory_digest"] = "f" * 64
    with pytest.raises(RepositoryWriteClassificationError, match="digest is stale"):
        project_classification_input(inventory, stale_digest)


def test_classification_evidence_revision_is_bound() -> None:
    row = _central(_surface())
    stale = replace(row.evidence[0], source_revision="e" * 40)
    evidence = tuple(
        sorted((stale, *row.evidence[1:]), key=EvidenceBinding.sort_key)
    )
    with pytest.raises(ValueError, match="evidence revision differs"):
        replace(row, evidence=evidence)


def test_strict_parsers_reject_extra_keys_and_boolean_integer() -> None:
    surface = _surface()
    inventory = _inventory(surface)
    material = inventory.to_dict()
    material["unexpected"] = True
    with pytest.raises(RepositoryWriteClassificationError, match="keys are invalid"):
        parse_inventory_v2(material)

    material = inventory.to_dict()
    material["files_scanned"] = True
    with pytest.raises(RepositoryWriteClassificationError, match="must be an integer"):
        parse_inventory_v2(material)

    row = _input_row(_central(surface))
    row["unknown"] = "value"
    with pytest.raises(RepositoryWriteClassificationError, match="keys are invalid"):
        project_classification_input(inventory, _input(inventory, [row]))


def test_tampered_inventory_derived_fields_and_digest_refuse() -> None:
    surface = _surface()
    material = _inventory(surface).to_dict()
    material["surface_count"] = 99
    with pytest.raises(RepositoryWriteClassificationError, match="derived fields"):
        parse_inventory_v2(material)


def test_evidence_cannot_be_substituted_across_surfaces() -> None:
    source = _surface()
    other = _surface("daedalus/other.py", 9)
    row = _central(source)
    foreign = replace(
        row.evidence[0],
        surface_sha256=surface_binding_sha256(REVISION, other),
    )
    evidence = tuple(
        sorted((foreign, *row.evidence[1:]), key=EvidenceBinding.sort_key)
    )
    with pytest.raises(ValueError, match="surface binding differs"):
        replace(row, evidence=evidence)


def test_guard_evidence_must_cover_exact_declared_contracts() -> None:
    row = _central(_surface())
    with pytest.raises(ValueError, match="guard evidence does not match"):
        replace(
            row,
            guard_contracts=("containment.attempt", "runtime.adapter_profile"),
        )


def test_schema_required_fields_match_report() -> None:
    surface = _surface()
    material = project_repository_write_classifications(
        _inventory(surface),
        (_central(surface),),
    ).to_dict()
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "configs/schemas/repository-write-classification.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(material)
    assert set(schema["required"]) == set(material)
    assert schema["properties"]["schema"]["const"] == material["schema"]
    assert schema["properties"]["closed"]["const"] is False
    assert "evidence_authenticated" not in schema["properties"]
    assert "evidence_authenticated" not in schema["required"]
    assert schema["properties"]["primary_checkout_target_proven"]["const"] is False
    assert schema["properties"]["gate_report_bound"]["const"] is False


def test_approved_guard_vocabulary_and_input_schema_are_pinned() -> None:
    assert tuple(item.value for item in GuardDisposition) == (
        "central",
        "local_guards",
        "inventory_only",
        "unguarded",
        "retired",
    )
    inventory = _inventory(_surface())
    unsupported = _input(inventory, [])
    unsupported["schema"] = (
        "daedalus-gate0-repository-write-classification-input/2"
    )
    with pytest.raises(RepositoryWriteClassificationError, match="unsupported"):
        project_classification_input(inventory, unsupported)


def test_cli_emits_report_and_scoped_ready_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    surface = _surface()
    inventory = _inventory(surface)
    inventory_path = tmp_path / "inventory.json"
    input_path = tmp_path / "classifications.json"
    inventory_path.write_text(json.dumps(inventory.to_dict()), encoding="utf-8")
    input_path.write_text(
        json.dumps(_input(inventory, [_input_row(_central(surface))])),
        encoding="utf-8",
    )

    assert main(
        [
            str(inventory_path),
            str(input_path),
            "--require-classification-ready",
        ]
    ) == 0
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["classification_ready"] is True
    assert emitted["closed"] is False

    input_path.write_text(json.dumps(_input(inventory, [])), encoding="utf-8")
    assert main(
        [
            str(inventory_path),
            str(input_path),
            "--require-classification-ready",
        ]
    ) == 3


def test_untyped_classification_refuses_without_attribute_error() -> None:
    inventory = _inventory(_surface())
    with pytest.raises(RepositoryWriteClassificationError, match="type is invalid"):
        project_repository_write_classifications(
            inventory,
            (object(),),  # type: ignore[arg-type]
        )


def test_report_projection_count_and_partition_are_invariant() -> None:
    surface = _surface()
    report = project_repository_write_classifications(
        _inventory(surface),
        (_central(surface),),
    )
    with pytest.raises(ValueError, match="surface count"):
        replace(report, inventory_surface_count=2)
    with pytest.raises(ValueError, match="disjoint"):
        replace(report, missing_surfaces=(surface,))


def test_nonreachable_route_requires_retired_evidence_state() -> None:
    surface = _surface()
    with pytest.raises(ValueError, match="requires retired disposition"):
        SurfaceClassification(
            source_revision=REVISION,
            surface=surface,
            target=TargetDisposition.PRIMARY_CHECKOUT,
            guard=GuardDisposition.UNGUARDED,
            production_reachable=False,
            guard_contracts=(),
            evidence=(),
        )


def test_noniterable_classification_input_refuses_cleanly() -> None:
    with pytest.raises(RepositoryWriteClassificationError, match="must be iterable"):
        project_repository_write_classifications(
            _inventory(_surface()),
            None,  # type: ignore[arg-type]
        )
