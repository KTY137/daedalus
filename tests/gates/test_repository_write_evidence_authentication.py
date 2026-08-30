# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Per-surface evidence authentication: the conjunction and its refusals."""
from __future__ import annotations

import hashlib

import pytest

from daedalus.gates.repository_write_classification import (
    AUTHENTICATED_EVIDENCE_KINDS,
    STAGE_VERDICT_ABSENT,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    NonRuntimeConformityBinding,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    applicable_authentication_stages,
    _compose_authenticated_surfaces,
    authenticate_repository_write_surfaces,
    authenticated_over_stages,
    issue_non_runtime_conformity_binding,
    project_classification_input,
    project_repository_write_classifications,
    surface_binding_sha256,
    verify_non_runtime_conformity_binding,
)
from daedalus.gates.repository_write_effect_lease import (
    EffectLeaseReplayRecord,
    RepositoryWriteEffectLeaseReport,
)
from daedalus.gates.repository_write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
    evidence_subject_sha256,
)
from daedalus.gates.repository_write_evidence_origin import (
    RepositoryWriteEvidenceOriginReport,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.gates.repository_write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceReport,
    RuntimeConformanceReplayRecord,
)
from daedalus.gates.repository_write_source_anchor_semantics import (
    RepositoryWriteSourceAnchorSemanticsReport,
    SourceAnchorSemanticRecord,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
SCAN = "b" * 64
SECRET = b"collector-secret-that-is-long-enough-for-hmac"
ISSUED = "2026-08-23T12:00:00.000000+00:00"
EXPIRES = "2026-08-23T13:00:00.000000+00:00"


def _surface(path: str = "daedalus/example.py") -> RepositoryWriteSurface:
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
        locator=f"cas:sha256:{digit * 64}",
        guard_contract=guard_contract,
    )


def _retired(surface: RepositoryWriteSurface) -> SurfaceClassification:
    """A cleared row with no guard contracts and no production reach.

    Its applicable stage set is the three always-applicable stages plus
    conformity, which keeps the fixtures small without weakening the rule
    under test: the conjunction does not care which stages apply, only that
    every one of them replied ``verified``.
    """

    evidence = tuple(
        sorted(
            (
                _evidence(EvidenceKind.RETIREMENT_RECEIPT, "5", surface),
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
        guard=GuardDisposition.RETIRED,
        production_reachable=False,
        guard_contracts=(),
        evidence=evidence,
        notes="synthetic retired fixture",
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
                _evidence(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "3", surface),
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
        notes="synthetic central fixture",
    )


def _report(row: SurfaceClassification):
    return project_repository_write_classifications(
        _inventory(row.surface), (row,)
    )


def _materialization(report, row: SurfaceClassification):
    records = tuple(
        sorted(
            (
                MaterializedEvidenceRecord(
                    kind=binding.kind,
                    source_revision=binding.source_revision,
                    surface_sha256=binding.surface_sha256,
                    guard_contract=binding.guard_contract,
                    locator=binding.locator,
                    blob_sha256=binding.sha256,
                    payload_sha256=hashlib.sha256(
                        binding.locator.encode("ascii")
                    ).hexdigest(),
                    subject_sha256=evidence_subject_sha256(binding),
                )
                for binding in row.evidence
            ),
            key=MaterializedEvidenceRecord.sort_key,
        )
    )
    return RepositoryWriteEvidenceMaterializationReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        binding_count=len(records),
        records=records,
        missing_locators=(),
    )


def _origin(report, materialization):
    return RepositoryWriteEvidenceOriginReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        materialization_digest=materialization.digest,
        attestation_digest="e" * 64,
        attestation_id="attestation.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        binding_count=materialization.binding_count,
        record_set_sha256="f" * 64,
        issued_at=ISSUED,
        expires_at=EXPIRES,
    )


def _anchor(report, materialization, row: SurfaceClassification):
    record = SourceAnchorSemanticRecord(
        surface_sha256=surface_binding_sha256(REVISION, row.surface),
        locator=f"cas:sha256:{'6' * 64}",
        path=row.surface.path,
        line=row.surface.line,
        column=row.surface.column,
        source_sha256="7" * 64,
    )
    return RepositoryWriteSourceAnchorSemanticsReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        materialization_digest=materialization.digest,
        origin_report_digest="8" * 64,
        attestation_digest="e" * 64,
        classification_count=1,
        source_anchor_count=1,
        anchored_source_set_sha256=hashlib.sha256(
            canonical_json(
                [{"path": record.path, "source_sha256": record.source_sha256}]
            ).encode("ascii")
        ).hexdigest(),
        records=(record,),
    )


def _conformity_record(surface_sha256: str) -> RuntimeConformanceReplayRecord:
    payload = {
        "surface_sha256": surface_sha256,
        "locator": f"cas:sha256:{'9' * 64}",
        "runtime_id": "runtime.local",
        "envelope_sha256": "1" * 64,
        "trust_record_sha256": "2" * 64,
        "probe_identity_sha256": "3" * 64,
        "conformance_receipt_sha256": "4" * 64,
        "runtime_manifest_sha256": "5" * 64,
        "observed_at": ISSUED,
        "expires_at": EXPIRES,
        "check_set_sha256": "6" * 64,
    }
    return RuntimeConformanceReplayRecord(
        **payload,
        replay_sha256=hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest(),
    )


def _conformity(report, materialization, surface_sha256: str):
    record = _conformity_record(surface_sha256)
    return RepositoryWriteRuntimeConformanceReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        materialization_digest=materialization.digest,
        guard_structure_report_digest="a" * 64,
        origin_attestation_digest="e" * 64,
        production_classification_count=1,
        runtime_subject_count=1,
        runtime_binding_count=1,
        runtime_set_sha256=hashlib.sha256(
            canonical_json([record.to_dict()]).encode("ascii")
        ).hexdigest(),
        records=(record,),
    )


def _lease(
    report,
    materialization,
    surface_sha256: str,
    *,
    runtime_bound: bool,
    runtime_id: str | None,
    execution_id: str,
):
    payload = {
        "surface_sha256": surface_sha256,
        "locator": f"cas:sha256:{'2' * 64}",
        "entrypoint_id": "cli.loop",
        "execution_id": execution_id,
        "execution_request_sha256": "3" * 64,
        "lease_sha256": "4" * 64,
        "start_receipt_sha256": "5" * 64,
        "terminal_receipt_sha256": "6" * 64,
        "terminal_state": "completed",
        "runtime_bound": runtime_bound,
        "runtime_id": runtime_id,
        "runtime_trust_record_sha256": "7" * 64 if runtime_bound else None,
        "runtime_conformance_receipt_sha256": "8" * 64,
    }
    record = EffectLeaseReplayRecord(
        **payload,
        replay_sha256=hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest(),
    )
    return RepositoryWriteEffectLeaseReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        materialization_digest=materialization.digest,
        runtime_conformance_report_digest="a" * 64,
        origin_attestation_digest="e" * 64,
        production_classification_count=1,
        effect_subject_count=1,
        effect_binding_count=1,
        effect_set_sha256=hashlib.sha256(
            canonical_json([record.to_dict()]).encode("ascii")
        ).hexdigest(),
        records=(record,),
    )


def _binding(surface_sha256: str, *, secret: bytes | str = SECRET):
    return issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        execution_id="execution.1",
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED,
        secret=secret,
    )


# ---------------------------------------------------------------- conjunction


def test_conjunction_is_false_when_one_applicable_stage_is_absent() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    materialization = _materialization(report, row)
    surface_sha256 = surface_binding_sha256(REVISION, surface)

    full = {
        AuthenticationStage.MATERIALIZATION: materialization,
        AuthenticationStage.ORIGIN: _origin(report, materialization),
        AuthenticationStage.ANCHOR: _anchor(report, materialization, row),
        AuthenticationStage.CONFORMITY: _conformity(
            report, materialization, surface_sha256
        ),
    }
    complete = _compose_authenticated_surfaces(
        report, full
    )[surface]
    assert complete.authenticated is True
    assert complete.applicable == frozenset(
        {
            AuthenticationStage.MATERIALIZATION,
            AuthenticationStage.ORIGIN,
            AuthenticationStage.ANCHOR,
            AuthenticationStage.CONFORMITY,
        }
    )

    # Every applicable stage is load-bearing: drop any one and the surface is
    # unauthenticated, with that stage named ``absent``.
    for stage in sorted(complete.applicable, key=lambda item: item.value):
        partial = {key: value for key, value in full.items() if key is not stage}
        result = _compose_authenticated_surfaces(
            report, partial
        )[surface]
        assert result.authenticated is False
        assert dict(result.verdicts)[stage.value] == STAGE_VERDICT_ABSENT


def test_empty_applicable_set_is_not_vacuously_authenticated() -> None:
    # ``all(())`` is True; the conjunction must not be.
    assert authenticated_over_stages(frozenset(), {}) is False
    assert (
        authenticated_over_stages(
            frozenset(),
            {stage: STAGE_VERDICT_VERIFIED for stage in AuthenticationStage},
        )
        is False
    )
    assert (
        authenticated_over_stages(
            frozenset({AuthenticationStage.ANCHOR}),
            {AuthenticationStage.ANCHOR: STAGE_VERDICT_VERIFIED},
        )
        is True
    )
    assert (
        authenticated_over_stages(
            frozenset({AuthenticationStage.ANCHOR, AuthenticationStage.LEASE}),
            {AuthenticationStage.ANCHOR: STAGE_VERDICT_VERIFIED},
        )
        is False
    )


# --------------------------------------------------------------- applicability


def test_applicability_is_derived_from_the_row_not_declared() -> None:
    surface = _surface()
    central = _central(surface)
    retired = _retired(surface)

    assert applicable_authentication_stages(central) == frozenset(AuthenticationStage)
    assert AuthenticationStage.GUARD not in applicable_authentication_stages(retired)
    assert AuthenticationStage.LEASE not in applicable_authentication_stages(retired)


def test_applicability_cannot_be_minted_from_a_declaration() -> None:
    surface = _surface()
    row = _central(surface)
    inventory = _inventory(surface)
    declared = row.to_dict()
    declared.pop("candidate_blockers")

    # Every stage name, and the word applicability itself, is refused by the
    # exact-key contract on both the document and the row.
    for extra in (
        "applicable",
        "applicable_stages",
        "stages",
        "conformity",
        "not_applicable",
        "evidence_authenticated",
    ):
        document = {
            "schema": "daedalus-gate0-repository-write-classification-input/1",
            "source_revision": REVISION,
            "inventory_digest": inventory.digest,
            "classifications": [{**declared, extra: True}],
        }
        with pytest.raises(RepositoryWriteClassificationError):
            project_classification_input(inventory, document)
        with pytest.raises(RepositoryWriteClassificationError):
            project_classification_input(
                inventory,
                {
                    "schema": (
                        "daedalus-gate0-repository-write-classification-input/1"
                    ),
                    "source_revision": REVISION,
                    "inventory_digest": inventory.digest,
                    "classifications": [declared],
                    extra: True,
                },
            )


# ------------------------------------------------------- not_applicable / lies


def test_not_applicable_without_a_collector_signature_is_refused() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    materialization = _materialization(report, row)
    surface_sha256 = surface_binding_sha256(REVISION, surface)
    stage_reports = {
        AuthenticationStage.MATERIALIZATION: materialization,
        AuthenticationStage.ORIGIN: _origin(report, materialization),
        AuthenticationStage.ANCHOR: _anchor(report, materialization, row),
    }

    unsigned = NonRuntimeConformityBinding(
        source_revision=REVISION,
        surface_sha256=surface_sha256,
        execution_id="execution.1",
        authorization_class="NonRuntimeEffectAuthorization",
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED,
        signature_sha256="0" * 64,
    )
    with pytest.raises(RepositoryWriteClassificationError):
        _compose_authenticated_surfaces(
            report,
            stage_reports,
            non_runtime_bindings=(unsigned,),
            collector_secrets={"key.1": SECRET},
        )
    with pytest.raises(RepositoryWriteClassificationError):
        verify_non_runtime_conformity_binding(
            _binding(surface_sha256, secret=b"a-different-secret-of-sufficient-length"),
            collector_secrets={"key.1": SECRET},
        )
    with pytest.raises(RepositoryWriteClassificationError):
        verify_non_runtime_conformity_binding(
            _binding(surface_sha256), collector_secrets={}
        )

    # A binding without a class of its own cannot be built at all.
    with pytest.raises(ValueError):
        NonRuntimeConformityBinding(
            source_revision=REVISION,
            surface_sha256=surface_sha256,
            execution_id="execution.1",
            authorization_class="RuntimeBoundEffectAuthorization",
            collector_id="collector.1",
            collector_key_id="key.1",
            issued_at=ISSUED,
            signature_sha256="0" * 64,
        )

    # Signed, the same excuse removes conformity from the applicable set and
    # the remaining three stages authenticate the surface.
    excused = _compose_authenticated_surfaces(
        report,
        stage_reports,
        non_runtime_bindings=(_binding(surface_sha256),),
        collector_secrets={"key.1": SECRET},
    )[surface]
    assert excused.authenticated is True
    assert AuthenticationStage.CONFORMITY not in excused.applicable
    assert dict(excused.verdicts)["conformity"] == STAGE_VERDICT_NOT_APPLICABLE
    assert excused.not_applicable_binding == "execution.1"


def test_runtime_writer_declared_non_runtime_is_refused() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    materialization = _materialization(report, row)
    surface_sha256 = surface_binding_sha256(REVISION, surface)

    # The conformity stage retained a runtime replay for this exact surface,
    # so the signed non-runtime excuse is a lie about the same execution.
    with pytest.raises(RepositoryWriteClassificationError):
        _compose_authenticated_surfaces(
            report,
            {
                AuthenticationStage.MATERIALIZATION: materialization,
                AuthenticationStage.CONFORMITY: _conformity(
                    report, materialization, surface_sha256
                ),
            },
            non_runtime_bindings=(_binding(surface_sha256),),
            collector_secrets={"key.1": SECRET},
        )


def test_signed_binding_is_checked_against_the_retained_lease_replay() -> None:
    """A signature is not a replay: the lease record has the last word."""

    surface = _surface()
    row = _central(surface)
    report = _report(row)
    materialization = _materialization(report, row)
    surface_sha256 = surface_binding_sha256(REVISION, surface)

    for runtime_bound, runtime_id, execution_id in (
        (True, "runtime.local", "execution.1"),
        (False, None, "execution.other"),
    ):
        lease = _lease(
            report,
            materialization,
            surface_sha256,
            runtime_bound=runtime_bound,
            runtime_id=runtime_id,
            execution_id=execution_id,
        )
        with pytest.raises(RepositoryWriteClassificationError):
            _compose_authenticated_surfaces(
                report,
                {
                    AuthenticationStage.MATERIALIZATION: materialization,
                    AuthenticationStage.LEASE: lease,
                },
                non_runtime_bindings=(_binding(surface_sha256),),
                collector_secrets={"key.1": SECRET},
            )

    agreeing = _lease(
        report,
        materialization,
        surface_sha256,
        runtime_bound=False,
        runtime_id=None,
        execution_id="execution.1",
    )
    result = _compose_authenticated_surfaces(
        report,
        {
            AuthenticationStage.MATERIALIZATION: materialization,
            AuthenticationStage.LEASE: agreeing,
        },
        non_runtime_bindings=(_binding(surface_sha256),),
        collector_secrets={"key.1": SECRET},
    )[surface]
    assert dict(result.verdicts)["conformity"] == STAGE_VERDICT_NOT_APPLICABLE
    assert dict(result.verdicts)["lease"] == STAGE_VERDICT_VERIFIED
    # Still unauthenticated: origin, anchor and guard never replied.
    assert result.authenticated is False


# ------------------------------------------------------------- stage integrity


def test_stage_report_must_be_the_exact_typed_report() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    materialization = _materialization(report, row)

    for forged in (
        materialization.to_dict(),
        {"classification_digest": report.digest, "source_revision": REVISION},
        _origin(report, materialization),
    ):
        with pytest.raises(RepositoryWriteClassificationError):
            _compose_authenticated_surfaces(
                report,
                {AuthenticationStage.MATERIALIZATION: forged},
            )
    with pytest.raises(RepositoryWriteClassificationError):
        _compose_authenticated_surfaces(
            report, {"materialization": materialization}
        )


def test_stage_report_bound_to_a_foreign_classification_is_refused() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    other = _report(_retired(_surface("daedalus/other.py")))
    foreign = _materialization(other, _retired(_surface("daedalus/other.py")))

    with pytest.raises(RepositoryWriteClassificationError):
        _compose_authenticated_surfaces(
            report, {AuthenticationStage.MATERIALIZATION: foreign}
        )


def test_materialization_speaks_only_for_the_kinds_it_retained() -> None:
    surface = _surface()
    row = _retired(surface)
    report = _report(row)
    full = _materialization(report, row)
    # All six kinds are authenticable; the row's own kinds must all be present.
    assert AUTHENTICATED_EVIDENCE_KINDS == frozenset(EvidenceKind)

    partial = RepositoryWriteEvidenceMaterializationReport(
        source_revision=REVISION,
        classification_digest=report.digest,
        binding_count=1,
        records=full.records[:1],
        missing_locators=(),
    )
    result = _compose_authenticated_surfaces(
        report, {AuthenticationStage.MATERIALIZATION: partial}
    )[surface]
    assert dict(result.verdicts)["materialization"] == STAGE_VERDICT_ABSENT
    assert result.authenticated is False
