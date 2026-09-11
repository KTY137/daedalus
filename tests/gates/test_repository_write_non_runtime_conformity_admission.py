"""The row contract: what a ``central`` surface may hold instead of a receipt.

Every test here needs a REAL retained execution -- a granted lease, a durable
start and a terminal receipt in an on-disk effect ledger -- because the whole
point of the admission is that a replay ran.  Building one forces pytest's
``tmp_path`` (and, for the runtime-bound direction, ``monkeypatch``), so this
module is run under the pytest runner rather than by executing its bodies
directly.  The fixture builders are loaded from the two suites that already own
them rather than copied, so a drift in the kernel fixtures shows up here too.
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
    NonRuntimeConformityBinding,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    applicable_authentication_stages,
    AuthenticationStage,
    issue_non_runtime_conformity_binding,
    surface_binding_sha256,
)
from daedalus.gates.repository.write_effect_lease import (
    EffectLeaseReplaySubject,
    RepositoryWriteEffectLeaseBindingError,
    RepositoryWriteEffectLeaseError,
    replay_non_runtime_effect_subject,
)
from daedalus.gates.repository.write_runtime_conformance import (
    RepositoryWriteRuntimeConformanceReport,
    RuntimeConformanceReplayRecord,
)
from daedalus.spine.envelope import canonical_json


def _load(name: str, relative: str):
    path = pathlib.Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lease = _load(
    "_b5_effect_lease_fixtures",
    "gates/test_repository_write_effect_lease.py",
)
_runtime = _load(
    "_b5_runtime_bound_fixtures",
    "kernel/test_runtime_effect_replay_projection.py",
)

REVISION = _lease.REVISION
SECRET = b"collector-secret-that-is-long-enough-for-hmac"
ISSUED = "2026-08-23T12:00:00.000000+00:00"
SURFACE = _lease._surface()
SURFACE_SHA = surface_binding_sha256(REVISION, SURFACE)


def _evidence(kind: EvidenceKind, digit: str, *, guard_contract: str = ""):
    return EvidenceBinding(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=SURFACE_SHA,
        sha256=digit * 64,
        locator=f"cas:sha256:{digit * 64}",
        guard_contract=guard_contract,
    )


def _central_evidence(*, with_runtime_receipt: bool):
    items = [
        _evidence(
            EvidenceKind.GUARD_CONTRACT,
            "1",
            guard_contract="containment.attempt",
        ),
        _evidence(EvidenceKind.EFFECT_LEASE_RECEIPT, "2"),
        _evidence(EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT, "4"),
    ]
    if with_runtime_receipt:
        items.append(_evidence(EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, "3"))
    return tuple(sorted(items, key=EvidenceBinding.sort_key))


def _central_row(admission, *, with_runtime_receipt=False):
    return SurfaceClassification(
        source_revision=REVISION,
        surface=SURFACE,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("containment.attempt",),
        evidence=_central_evidence(with_runtime_receipt=with_runtime_receipt),
        notes="b5 non-runtime admission fixture",
        non_runtime_conformity=admission,
    )


def _signed(execution_id: str, *, secret=SECRET, surface_sha256=None):
    return issue_non_runtime_conformity_binding(
        source_revision=REVISION,
        surface_sha256=surface_sha256 or SURFACE_SHA,
        execution_id=execution_id,
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED,
        secret=secret,
    )


def _terminal_subject(tmp_path):
    authorization, execution, terminal = _lease._terminal_fixture(tmp_path)
    return EffectLeaseReplaySubject(authorization, execution), execution, terminal


def test_central_row_admits_a_verified_binding_instead_of_the_runtime_receipt(
    tmp_path,
) -> None:
    subject, execution, _terminal = _terminal_subject(tmp_path)
    admission = NonRuntimeConformityAdmission(
        binding=_signed(execution.execution_id),
        subject=subject,
        collector_secrets={"key.1": SECRET},
    )
    row = _central_row(admission)

    # It is central, it is production reachable, it clears, and it holds no
    # runtime-conformance receipt at all.
    assert row.guard is GuardDisposition.CENTRAL
    assert row.candidate_blockers == ()
    assert EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT not in {
        item.kind for item in row.evidence
    }
    # ... and the conformity stage is therefore not owed for this surface.
    assert AuthenticationStage.CONFORMITY not in applicable_authentication_stages(row)

    # The same evidence without the admission is the old refusal, unchanged.
    with pytest.raises(ValueError, match="lacks required evidence kinds"):
        _central_row(None)

    # Excused AND carrying a receipt is claiming both things at once.
    with pytest.raises(ValueError, match="retains a runtime receipt"):
        _central_row(admission, with_runtime_receipt=True)

    # The admission is in process only.  There is no wire shape for it, so no
    # declaration document can ever produce a row that holds one.
    assert "non_runtime_conformity" not in row.to_dict()
    with pytest.raises(RepositoryWriteClassificationError):
        SurfaceClassification.from_dict(
            {**row.to_dict(), "non_runtime_conformity": {"execution_id": "x"}}
        )


def test_the_admission_excuses_the_runtime_receipt_and_nothing_else(
    tmp_path,
) -> None:
    """One kind, one disposition.  Everything else the row owed, it still owes."""

    subject, execution, _terminal = _terminal_subject(tmp_path)
    admission = NonRuntimeConformityAdmission(
        binding=_signed(execution.execution_id),
        subject=subject,
        collector_secrets={"key.1": SECRET},
    )

    # Drop the Effect-Lease receipt: it is required by the same set the
    # runtime receipt was discarded from, and it is still required.
    without_lease = tuple(
        item
        for item in _central_evidence(with_runtime_receipt=False)
        if item.kind is not EvidenceKind.EFFECT_LEASE_RECEIPT
    )
    with pytest.raises(ValueError, match="lacks required evidence kinds"):
        SurfaceClassification(
            source_revision=REVISION,
            surface=SURFACE,
            target=TargetDisposition.CHECKOUT_EXTERNAL,
            guard=GuardDisposition.CENTRAL,
            production_reachable=True,
            guard_contracts=("containment.attempt",),
            evidence=without_lease,
            notes="b5 non-runtime admission fixture",
            non_runtime_conformity=admission,
        )

    # And the admission means nothing on a disposition that never owed a
    # runtime receipt: one shape, one meaning.
    with pytest.raises(ValueError, match="requires central disposition"):
        SurfaceClassification(
            source_revision=REVISION,
            surface=SURFACE,
            target=TargetDisposition.CHECKOUT_EXTERNAL,
            guard=GuardDisposition.RETIRED,
            production_reachable=False,
            guard_contracts=(),
            evidence=tuple(
                sorted(
                    (
                        _evidence(EvidenceKind.RETIREMENT_RECEIPT, "5"),
                        _evidence(
                            EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT,
                            "4",
                        ),
                    ),
                    key=EvidenceBinding.sort_key,
                )
            ),
            notes="b5 retired row carrying an admission",
            non_runtime_conformity=admission,
        )


def test_unsigned_or_wrong_key_binding_is_refused_at_construction(tmp_path) -> None:
    subject, execution, _terminal = _terminal_subject(tmp_path)
    unsigned = NonRuntimeConformityBinding(
        source_revision=REVISION,
        surface_sha256=SURFACE_SHA,
        execution_id=execution.execution_id,
        authorization_class="NonRuntimeEffectAuthorization",
        collector_id="collector.1",
        collector_key_id="key.1",
        issued_at=ISSUED,
        signature_sha256="0" * 64,
    )
    with pytest.raises(RepositoryWriteClassificationError, match="does not verify"):
        NonRuntimeConformityAdmission(
            binding=unsigned,
            subject=subject,
            collector_secrets={"key.1": SECRET},
        )

    wrong_key = _signed(
        execution.execution_id,
        secret=b"a-different-collector-secret-of-sufficient-length",
    )
    with pytest.raises(RepositoryWriteClassificationError, match="does not verify"):
        NonRuntimeConformityAdmission(
            binding=wrong_key,
            subject=subject,
            collector_secrets={"key.1": SECRET},
        )

    with pytest.raises(RepositoryWriteClassificationError, match="unknown collector"):
        NonRuntimeConformityAdmission(
            binding=_signed(execution.execution_id),
            subject=subject,
            collector_secrets={},
        )

    # And an untyped stand-in for the binding is not a binding.
    with pytest.raises(ValueError, match="exact typed binding"):
        NonRuntimeConformityAdmission(
            binding={"execution_id": execution.execution_id},
            subject=subject,
            collector_secrets={"key.1": SECRET},
        )


def test_a_signature_is_not_a_replay(tmp_path) -> None:
    """A correctly signed binding still needs the execution behind it."""

    subject, execution, _terminal = _terminal_subject(tmp_path)

    # Signed for another execution: the replay names a different one.
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="names another execution",
    ):
        NonRuntimeConformityAdmission(
            binding=_signed("some-other-execution"),
            subject=subject,
            collector_secrets={"key.1": SECRET},
        )

    # Signed over an execution that never terminalized.
    authorization, pending = _lease._authorization(tmp_path / "pending")
    authorization.grant()
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="no durable start",
    ):
        NonRuntimeConformityAdmission(
            binding=_signed(pending.execution_id),
            subject=EffectLeaseReplaySubject(authorization, pending),
            collector_secrets={"key.1": SECRET},
        )

    # A subject that is not a subject at all.
    with pytest.raises(RepositoryWriteEffectLeaseError, match="exact typed subject"):
        NonRuntimeConformityAdmission(
            binding=_signed(execution.execution_id),
            subject={"execution_id": execution.execution_id},
            collector_secrets={"key.1": SECRET},
        )

    # The admission binds one surface and one revision.
    other_surface_admission = NonRuntimeConformityAdmission(
        binding=_signed(execution.execution_id, surface_sha256="9" * 64),
        subject=subject,
        collector_secrets={"key.1": SECRET},
    )
    with pytest.raises(ValueError, match="binds another surface"):
        _central_row(other_surface_admission)


def test_binding_whose_execution_replays_as_runtime_is_refused(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, _record = _runtime._authorization(tmp_path, monkeypatch)
    runtime_subject = EffectLeaseReplaySubject(authorization, _runtime._execution())
    assert runtime_subject.runtime_bound is True

    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="replays as a runtime-bound authorization",
    ):
        replay_non_runtime_effect_subject(
            runtime_subject,
            expected_execution_id=runtime_subject.execution.execution_id,
        )

    # And the same refusal reaches the row: a runtime writer cannot buy its way
    # out of the conformity stage with a signature.
    with pytest.raises(
        RepositoryWriteEffectLeaseBindingError,
        match="replays as a runtime-bound authorization",
    ):
        NonRuntimeConformityAdmission(
            binding=issue_non_runtime_conformity_binding(
                source_revision=_runtime.REVISION,
                surface_sha256=SURFACE_SHA,
                execution_id=runtime_subject.execution.execution_id,
                collector_id="collector.1",
                collector_key_id="key.1",
                issued_at=ISSUED,
                secret=SECRET,
            ),
            subject=runtime_subject,
            collector_secrets={"key.1": SECRET},
        )


def _conformance_report(*, records, non_runtime_surfaces):
    runtime_set_sha = hashlib.sha256(
        canonical_json([record.to_dict() for record in records]).encode("ascii")
    ).hexdigest()
    return RepositoryWriteRuntimeConformanceReport(
        source_revision=REVISION,
        classification_digest="a" * 64,
        materialization_digest="b" * 64,
        guard_structure_report_digest="c" * 64,
        origin_attestation_digest="d" * 64,
        production_classification_count=1,
        runtime_subject_count=len({r.conformance_receipt_sha256 for r in records}),
        runtime_binding_count=len(records),
        runtime_set_sha256=runtime_set_sha,
        records=records,
        non_runtime_surfaces=non_runtime_surfaces,
    )


def _replay_record(surface_sha256: str):
    payload = {
        "surface_sha256": surface_sha256,
        "locator": "cas:sha256:" + "8" * 64,
        "runtime_id": _lease.RUNTIME_ID,
        "envelope_sha256": "9" * 64,
        "trust_record_sha256": "a" * 64,
        "probe_identity_sha256": "b" * 64,
        "conformance_receipt_sha256": _lease.RUNTIME_RECEIPT_SHA,
        "runtime_manifest_sha256": "d" * 64,
        "observed_at": _lease.NOW.isoformat(timespec="microseconds"),
        "expires_at": _lease.NOW.isoformat(timespec="microseconds"),
        "check_set_sha256": "e" * 64,
    }
    return RuntimeConformanceReplayRecord(
        **payload,
        replay_sha256=hashlib.sha256(
            canonical_json(payload).encode("ascii")
        ).hexdigest(),
    )


def test_conformance_v2_accepts_zero_plus_binding_and_refuses_zero_without() -> None:
    # Exactly zero receipts, WITH a named excused surface: the /2 shape.
    excused = _conformance_report(records=(), non_runtime_surfaces=(SURFACE_SHA,))
    assert excused.to_dict()["schema"] == (
        "daedalus-gate0-repository-write-runtime-conformance/2"
    )
    assert excused.to_dict()["non_runtime_surfaces"] == [SURFACE_SHA]
    assert excused.runtime_binding_count == 0

    # Exactly zero receipts and nothing excused: a report that verified nothing
    # while claiming runtime conformance was verified.
    with pytest.raises(ValueError, match="must name its non-runtime surfaces"):
        _conformance_report(records=(), non_runtime_surfaces=())

    # Both replayed and excused for one surface is the runtime writer wearing a
    # non-runtime label.
    with pytest.raises(ValueError, match="cannot also retain a runtime replay"):
        _conformance_report(
            records=(_replay_record(SURFACE_SHA),),
            non_runtime_surfaces=(SURFACE_SHA,),
        )

    # /1 still holds where it always did: one receipt, one replayed surface.
    replayed = _conformance_report(
        records=(_replay_record(SURFACE_SHA),),
        non_runtime_surfaces=(),
    )
    assert replayed.runtime_binding_count == 1
    assert replayed.to_dict()["non_runtime_surfaces"] == []
