"""Canonical terminal artifact for the repository-write verifier chain."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_write_chain_result as chain
from daedalus.gates.repository_write_classification import (
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteAuthenticationInputs,
    SurfaceClassification,
    SurfaceEvidenceAuthentication,
    TargetDisposition,
    project_repository_write_classifications,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


REVISION = "a" * 40
SCAN = "b" * 64


def _surface(path: str, line: int = 7) -> RepositoryWriteSurface:
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


def _binding(
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


def _central(surface: RepositoryWriteSurface) -> SurfaceClassification:
    evidence = tuple(
        sorted(
            (
                _binding(
                    surface,
                    EvidenceKind.GUARD_CONTRACT,
                    "1",
                    guard_contract="containment.attempt",
                ),
                _binding(surface, EvidenceKind.EFFECT_LEASE_RECEIPT, "2"),
                _binding(surface, EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "3"),
                _binding(
                    surface,
                    EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                    "4",
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
        notes="chain-result central fixture",
    )


def _inventory_only(surface: RepositoryWriteSurface) -> SurfaceClassification:
    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.INVENTORY_ONLY,
        production_reachable=True,
        guard_contracts=(),
        evidence=(
            _binding(
                surface,
                EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                "4",
            ),
        ),
        notes="chain-result blocked fixture",
    )


def _inputs() -> RepositoryWriteAuthenticationInputs:
    return RepositoryWriteAuthenticationInputs(
        blobs={},
        origin_attestation=object(),
        guard_manifest=object(),
        runtime_subjects={},
        runtime_trust_ledgers={},
        effect_subjects={},
        collector_keyring={},
        expected_collector_id="collector.1",
        guard_keyring={},
        expected_guard_authority_id="guard.1",
        current_revision=REVISION,
        now=object(),
        repository_root=Path("."),
    )


def _authentication(
    row: SurfaceClassification,
    *,
    authenticated: bool = True,
) -> SurfaceEvidenceAuthentication:
    return SurfaceEvidenceAuthentication(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, row.surface),
        path=row.surface.path,
        line=row.surface.line,
        column=row.surface.column,
        origin=row.surface.origin,
        applicable=frozenset(AuthenticationStage),
        verdicts=tuple(
            sorted(
                (stage.value, STAGE_VERDICT_VERIFIED)
                for stage in AuthenticationStage
            )
        ),
        authenticated=authenticated,
    )


def _patch_verified_chain(
    monkeypatch: pytest.MonkeyPatch,
    rows: tuple[SurfaceClassification, ...],
) -> None:
    stage_reports = {
        stage: SimpleNamespace(digest=str(index) * 64)
        for index, stage in enumerate(AuthenticationStage, start=1)
    }
    authentications = {row.surface: _authentication(row) for row in rows}
    monkeypatch.setattr(
        chain,
        "_run_stage_verifiers",
        lambda report, inputs: stage_reports,
    )
    monkeypatch.setattr(
        chain,
        "_compose_authenticated_surfaces",
        lambda report, reports, **kwargs: authentications,
    )


def test_build_retains_all_stage_digests_and_round_trips_canonically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface("daedalus/attempt.py")
    row = _central(surface)
    report = project_repository_write_classifications(_inventory(surface), (row,))
    _patch_verified_chain(monkeypatch, (row,))

    result = chain.build_repository_write_chain_result(
        report,
        inputs=_inputs(),
    )

    assert tuple(name for name, _ in result.stage_digests) == tuple(
        sorted(stage.value for stage in AuthenticationStage)
    )
    assert result.authenticated_surface_count == 1
    assert result.evidence_authenticated is True
    assert chain.RepositoryWriteChainResult.from_dict(result.to_dict()) == result


def test_candidate_blocker_cannot_authenticate_even_when_stages_claim_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface("daedalus/unguarded.py")
    row = _inventory_only(surface)
    report = project_repository_write_classifications(_inventory(surface), (row,))
    _patch_verified_chain(monkeypatch, (row,))

    result = chain.build_repository_write_chain_result(
        report,
        inputs=_inputs(),
    )

    assert result.surfaces[0].candidate_blockers == (
        "production-write-inventory_only",
    )
    assert result.surfaces[0].authenticated is False
    assert result.authenticated_surface_count == 0
    assert result.evidence_authenticated is False


def test_missing_inventory_surface_keeps_aggregate_authentication_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classified = _surface("daedalus/classified.py")
    missing = _surface("daedalus/missing.py", line=11)
    row = _central(classified)
    report = project_repository_write_classifications(
        _inventory(classified, missing),
        (row,),
    )
    _patch_verified_chain(monkeypatch, (row,))

    result = chain.build_repository_write_chain_result(
        report,
        inputs=_inputs(),
    )

    assert result.authenticated_surface_count == 1
    assert result.missing_surface_count == 1
    assert result.evidence_authenticated is False


def test_derived_counts_boolean_and_digest_cannot_be_forged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface("daedalus/attempt.py")
    row = _central(surface)
    report = project_repository_write_classifications(_inventory(surface), (row,))
    _patch_verified_chain(monkeypatch, (row,))
    payload = chain.build_repository_write_chain_result(
        report,
        inputs=_inputs(),
    ).to_dict()

    for key, replacement in (
        ("authenticated_surface_count", 0),
        ("evidence_authenticated", False),
        ("digest", "f" * 64),
    ):
        tampered = dict(payload)
        tampered[key] = replacement
        with pytest.raises(chain.RepositoryWriteChainResultError):
            chain.RepositoryWriteChainResult.from_dict(tampered)

    forged_surface = json.loads(json.dumps(payload))
    forged_surface["surfaces"][0]["authenticated"] = False
    with pytest.raises(chain.RepositoryWriteChainResultError):
        chain.RepositoryWriteChainResult.from_dict(forged_surface)


def test_builder_refuses_a_missing_stage_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = _surface("daedalus/attempt.py")
    row = _central(surface)
    report = project_repository_write_classifications(_inventory(surface), (row,))
    stage_reports = {
        stage: SimpleNamespace(digest=str(index) * 64)
        for index, stage in enumerate(AuthenticationStage, start=1)
        if stage is not AuthenticationStage.LEASE
    }
    monkeypatch.setattr(
        chain,
        "_run_stage_verifiers",
        lambda subject, inputs: stage_reports,
    )

    with pytest.raises(chain.RepositoryWriteChainResultError):
        chain.build_repository_write_chain_result(report, inputs=_inputs())


def test_stage_digest_omission_and_duplicate_json_keys_are_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    surface = _surface("daedalus/attempt.py")
    row = _central(surface)
    report = project_repository_write_classifications(_inventory(surface), (row,))
    _patch_verified_chain(monkeypatch, (row,))
    payload = chain.build_repository_write_chain_result(
        report,
        inputs=_inputs(),
    ).to_dict()

    missing_stage = json.loads(json.dumps(payload))
    missing_stage["stage_digests"].pop(AuthenticationStage.LEASE.value)
    with pytest.raises(chain.RepositoryWriteChainResultError):
        chain.RepositoryWriteChainResult.from_dict(missing_stage)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(chain.RepositoryWriteChainResultError):
        chain.load_repository_write_chain_result(duplicate)
