"""The Effect-Lease consumer against the /2 runtime-conformance shape.

One production surface, zero runtime-conformance receipts, and a verified
``NonRuntimeConformityBinding`` in their place.  The retained execution is real
-- granted, started and terminalised in an on-disk effect ledger -- because the
row will not admit the binding until that execution has actually been replayed,
so these bodies need pytest's ``tmp_path`` and run under the pytest runner.
"""
from __future__ import annotations

import hashlib
import importlib.util
import pathlib

import pytest

from daedalus.gates.repository.write_classification import (
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    NonRuntimeConformityAdmission,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    issue_non_runtime_conformity_binding,
    surface_binding_sha256,
)
from daedalus.gates.repository.write_effect_lease import (
    EffectLeaseReplaySubject,
    RepositoryWriteEffectLeaseBindingError,
)
from daedalus.gates.repository.write_evidence_materialization import (
    materialize_repository_write_evidence,
)
from daedalus.gates.repository.write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceReport,
)
from daedalus.spine.envelope import canonical_json


def _load(name: str, relative: str):
    path = pathlib.Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lease = _load(
    "_b5_effect_lease_v2_fixtures",
    "gates/test_repository_write_effect_lease.py",
)

REVISION = _lease.REVISION
SECRET = b"collector-secret-that-is-long-enough-for-hmac"
ISSUED = "2026-08-23T12:00:00.000000+00:00"
SURFACE = _lease._surface()
SURFACE_SHA = surface_binding_sha256(REVISION, SURFACE)


def _non_runtime_classification(terminal_sha: str, admission):
    """The /2 row: central, production reachable, and no runtime receipt."""

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
                "entrypoint_id": _lease.ENTRYPOINT,
                "terminal_state": "completed",
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
        binding, raw = _lease._binding(kind, payload, guard_contract=guard)
        bindings.append(binding)
        blobs[binding.locator] = raw
    row = SurfaceClassification(
        source_revision=REVISION,
        surface=SURFACE,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("containment.attempt",),
        evidence=tuple(sorted(bindings, key=EvidenceBinding.sort_key)),
        notes="b5 non-runtime effect fixture",
        non_runtime_conformity=admission,
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


def _excused_runtime_report(classification, blobs, *, excused=(SURFACE_SHA,)):
    materialization = materialize_repository_write_evidence(classification, blobs)
    return RepositoryWriteRuntimeConformanceReport(
        source_revision=REVISION,
        classification_digest=classification.digest,
        materialization_digest=materialization.digest,
        guard_structure_report_digest="f" * 64,
        origin_attestation_digest=_lease.ORIGIN_SHA,
        production_classification_count=1,
        runtime_subject_count=0,
        runtime_binding_count=0,
        runtime_set_sha256=hashlib.sha256(
            canonical_json([]).encode("ascii")
        ).hexdigest(),
        records=(),
        non_runtime_surfaces=tuple(excused),
    )


def _fixture(tmp_path, *, excused=(SURFACE_SHA,)):
    authorization, execution, terminal = _lease._terminal_fixture(tmp_path)
    subject = EffectLeaseReplaySubject(authorization, execution)
    admission = NonRuntimeConformityAdmission(
        binding=issue_non_runtime_conformity_binding(
            source_revision=REVISION,
            surface_sha256=SURFACE_SHA,
            execution_id=execution.execution_id,
            collector_id="collector.1",
            collector_key_id="key.1",
            issued_at=ISSUED,
            secret=SECRET,
        ),
        subject=subject,
        collector_secrets={"key.1": SECRET},
    )
    classification, blobs = _non_runtime_classification(
        terminal.receipt_sha256, admission
    )
    return classification, blobs, subject, terminal, excused


def _install(monkeypatch, classification, blobs, *, excused):
    report = _excused_runtime_report(classification, blobs, excused=excused)
    monkeypatch.setattr(
        _lease.effect_module,
        "verify_repository_write_runtime_conformance",
        lambda *args, **kwargs: report,
    )


def test_zero_receipts_with_a_binding_verifies_and_records_a_null_digest(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    classification, blobs, subject, terminal, excused = _fixture(tmp_path)
    _install(monkeypatch, classification, blobs, excused=excused)

    report = _lease._verify(
        classification, blobs, {terminal.receipt_sha256: subject}
    )

    assert len(report.records) == 1
    record = report.records[0]
    assert record.surface_sha256 == SURFACE_SHA
    assert record.runtime_bound is False
    # No conformance receipt exists for this surface, and none is invented.
    assert record.runtime_conformance_receipt_sha256 is None
    assert record.to_dict()["runtime_conformance_receipt_sha256"] is None
    assert report.to_dict()["schema"] == (
        "daedalus-gate0-repository-write-effect-lease/2"
    )
    # The relaxation is bounded: nothing else about the report moved.
    for field in ("evidence_authenticated", "gate_report_bound", "closed"):
        assert report.to_dict()[field] is False


def test_excused_set_must_match_the_rows_that_admit_a_binding(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A predecessor that excuses a different set than the rows do is refused."""

    classification, blobs, subject, terminal, _excused = _fixture(tmp_path)
    _install(monkeypatch, classification, blobs, excused=("9" * 64,))
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="surface set differs from production classifications",
    ):
        _lease._verify(classification, blobs, {terminal.receipt_sha256: subject})

    # Excusing nothing while replaying nothing never reaches this consumer at
    # all: the predecessor report refuses to exist.  Recorded here so the gap
    # is visible rather than assumed.
    with pytest.raises(ValueError, match="must name its non-runtime surfaces"):
        _excused_runtime_report(classification, blobs, excused=())


def test_a_row_without_an_admission_cannot_be_excused_by_the_predecessor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The excuse must come from the row, not from the predecessor alone."""

    _authorization, execution, terminal = _lease._terminal_fixture(tmp_path)
    subject = EffectLeaseReplaySubject(_authorization, execution)
    ordinary, blobs = _lease._classification(terminal.receipt_sha256)
    _install(monkeypatch, ordinary, blobs, excused=(SURFACE_SHA,))
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="excuses a different surface set than the rows admit",
    ):
        _lease._verify(ordinary, blobs, {terminal.receipt_sha256: subject})
