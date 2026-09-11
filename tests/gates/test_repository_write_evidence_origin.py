from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.gates.repository.write_classification import EvidenceKind
from daedalus.gates.repository.write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
)
from daedalus.gates.repository.write_evidence_origin import (
    RepositoryWriteEvidenceOriginAttestation,
    RepositoryWriteEvidenceOriginBindingError,
    RepositoryWriteEvidenceOriginError,
    RepositoryWriteEvidenceOriginSignatureError,
    issue_repository_write_evidence_origin_attestation,
    parse_repository_write_evidence_origin_attestation,
    verify_repository_write_evidence_origin,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
CLASSIFICATION = "b" * 64
SECRET = b"collector-secret-" * 4
ISSUED = datetime(2026, 8, 4, 15, 0, tzinfo=timezone.utc)
EXPIRES = ISSUED + timedelta(hours=1)


def _record(
    *,
    kind: EvidenceKind,
    surface: str,
    blob: str,
    payload: str,
    subject: str,
    guard: str = "",
) -> MaterializedEvidenceRecord:
    return MaterializedEvidenceRecord(
        kind=kind,
        source_revision=REVISION,
        surface_sha256=surface,
        guard_contract=guard,
        locator=f"cas:sha256:{blob}",
        blob_sha256=blob,
        payload_sha256=payload,
        subject_sha256=subject,
    )


def _materialization() -> RepositoryWriteEvidenceMaterializationReport:
    records = (
        _record(
            kind=EvidenceKind.SOURCE_ANCHOR,
            surface="1" * 64,
            blob="2" * 64,
            payload="3" * 64,
            subject="4" * 64,
        ),
        _record(
            kind=EvidenceKind.GUARD_CONTRACT,
            surface="5" * 64,
            blob="6" * 64,
            payload="3" * 64,
            subject="7" * 64,
            guard="spine.effect_lease",
        ),
    )
    return RepositoryWriteEvidenceMaterializationReport(
        source_revision=REVISION,
        classification_digest=CLASSIFICATION,
        binding_count=2,
        records=tuple(
            sorted(records, key=MaterializedEvidenceRecord.sort_key)
        ),
        missing_locators=(),
    )


def _issue(
    materialization: RepositoryWriteEvidenceMaterializationReport | None = None,
) -> RepositoryWriteEvidenceOriginAttestation:
    return issue_repository_write_evidence_origin_attestation(
        _materialization() if materialization is None else materialization,
        attestation_id="rwi.origin.1",
        collector_id="gate.collector",
        collector_key_id="collector.key.1",
        collector_secret=SECRET,
        issued_at=ISSUED,
        expires_at=EXPIRES,
    )


def _verify(
    attestation: RepositoryWriteEvidenceOriginAttestation,
    materialization: RepositoryWriteEvidenceMaterializationReport | None = None,
    **overrides: object,
):
    arguments = {
        "keyring": {("gate.collector", "collector.key.1"): SECRET},
        "expected_collector_id": "gate.collector",
        "current_revision": REVISION,
        "now": ISSUED + timedelta(minutes=1),
    }
    arguments.update(overrides)
    return verify_repository_write_evidence_origin(
        attestation,
        _materialization() if materialization is None else materialization,
        **arguments,
    )


def test_issue_parse_verify_round_trip_is_deterministic_and_non_authoritative() -> None:
    attestation = _issue()
    assert attestation == _issue()
    raw = canonical_json(attestation.to_dict()).encode("ascii")
    assert parse_repository_write_evidence_origin_attestation(raw) == attestation

    report = _verify(attestation)
    assert report.to_dict() == _verify(attestation).to_dict()
    payload = report.to_dict()
    assert payload["origin_authenticated"] is True
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert payload["blockers"] == [
        "external-evidence-semantic-verification-missing",
        "gate-report-binding-missing",
    ]
    assert payload["source_revision"] == REVISION
    assert payload["classification_digest"] == CLASSIFICATION
    assert payload["materialization_digest"] == _materialization().digest
    assert payload["attestation_digest"] == attestation.digest


def test_duplicate_payload_digests_are_allowed_but_subjects_and_blobs_stay_distinct() -> None:
    materialization = _materialization()
    assert len({row.payload_sha256 for row in materialization.records}) == 1
    attestation = _issue(materialization)
    assert attestation.payload_sha256s == ("3" * 64, "3" * 64)
    assert len(set(attestation.record_sha256s)) == 2
    assert len(set(attestation.blob_sha256s)) == 2
    assert _verify(attestation, materialization).binding_count == 2


def test_unknown_key_pair_refuses_before_live_projection() -> None:
    with pytest.raises(RepositoryWriteEvidenceOriginSignatureError):
        _verify(_issue(), keyring={})


def test_wrong_secret_and_signed_field_substitution_refuse() -> None:
    attestation = _issue()
    with pytest.raises(RepositoryWriteEvidenceOriginSignatureError):
        _verify(
            attestation,
            keyring={
                ("gate.collector", "collector.key.1"): b"wrong-secret-" * 4
            },
        )
    substituted = dataclasses.replace(
        attestation,
        classification_digest="c" * 64,
    )
    with pytest.raises(RepositoryWriteEvidenceOriginSignatureError):
        _verify(substituted)


def test_stale_revision_and_unexpected_collector_refuse() -> None:
    attestation = _issue()
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, current_revision="c" * 40)
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, expected_collector_id="other.collector")


def test_materialization_record_or_classification_substitution_refuses() -> None:
    attestation = _issue()
    materialization = _materialization()
    changed_record = dataclasses.replace(
        materialization.records[0],
        subject_sha256="d" * 64,
    )
    changed = dataclasses.replace(
        materialization,
        records=tuple(
            sorted(
                (changed_record, materialization.records[1]),
                key=MaterializedEvidenceRecord.sort_key,
            )
        ),
    )
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, changed)

    changed_classification = dataclasses.replace(
        materialization,
        classification_digest="e" * 64,
    )
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, changed_classification)


def test_incomplete_or_empty_materialization_cannot_be_attested() -> None:
    materialization = _materialization()
    partial = dataclasses.replace(
        materialization,
        records=(materialization.records[0],),
        missing_locators=(materialization.records[1].locator,),
    )
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _issue(partial)

    empty = RepositoryWriteEvidenceMaterializationReport(
        source_revision=REVISION,
        classification_digest=CLASSIFICATION,
        binding_count=0,
        records=(),
        missing_locators=(),
    )
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _issue(empty)


def test_future_expired_and_oversized_ttl_refuse() -> None:
    attestation = _issue()
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, now=ISSUED - timedelta(microseconds=1))
    with pytest.raises(RepositoryWriteEvidenceOriginBindingError):
        _verify(attestation, now=EXPIRES)
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        issue_repository_write_evidence_origin_attestation(
            _materialization(),
            attestation_id="rwi.origin.2",
            collector_id="gate.collector",
            collector_key_id="collector.key.1",
            collector_secret=SECRET,
            issued_at=ISSUED,
            expires_at=ISSUED + timedelta(hours=24, microseconds=1),
        )


def test_malformed_secret_time_and_keyring_refuse() -> None:
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        issue_repository_write_evidence_origin_attestation(
            _materialization(),
            attestation_id="rwi.origin.3",
            collector_id="gate.collector",
            collector_key_id="collector.key.1",
            collector_secret=b"short",
            issued_at=ISSUED,
            expires_at=EXPIRES,
        )
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        issue_repository_write_evidence_origin_attestation(
            _materialization(),
            attestation_id="rwi.origin.4",
            collector_id="gate.collector",
            collector_key_id="collector.key.1",
            collector_secret=SECRET,
            issued_at=ISSUED.replace(tzinfo=None),
            expires_at=EXPIRES,
        )
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        verify_repository_write_evidence_origin(
            _issue(),
            _materialization(),
            keyring=[],
            expected_collector_id="gate.collector",
            current_revision=REVISION,
            now=ISSUED,
        )


def test_parser_rejects_noncanonical_duplicate_nonfinite_and_encoding_inputs() -> None:
    attestation = _issue()
    canonical = canonical_json(attestation.to_dict()).encode("ascii")
    assert parse_repository_write_evidence_origin_attestation(canonical) == attestation

    with pytest.raises(RepositoryWriteEvidenceOriginError):
        parse_repository_write_evidence_origin_attestation(b" " + canonical)
    duplicate = canonical.replace(
        b'{"attestation_id":',
        b'{"attestation_id":"shadow","attestation_id":',
        1,
    )
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        parse_repository_write_evidence_origin_attestation(duplicate)
    nonfinite = canonical.replace(
        b'"binding_count":2',
        b'"binding_count":NaN',
        1,
    )
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        parse_repository_write_evidence_origin_attestation(nonfinite)
    for raw in (b"\xef\xbb\xbf" + canonical, canonical + b"\x00"):
        with pytest.raises(RepositoryWriteEvidenceOriginError):
            parse_repository_write_evidence_origin_attestation(raw)
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        parse_repository_write_evidence_origin_attestation(
            b"{" + b" " * 1_048_576 + b"}"
        )

    oversized = dataclasses.replace(
        attestation,
        attestation_id="a" * 1_048_576,
    )
    oversized_raw = canonical_json(oversized.to_dict()).encode("ascii")
    assert len(oversized_raw) > 1_048_576
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        parse_repository_write_evidence_origin_attestation(oversized_raw)


def test_from_dict_rejects_schema_shape_boolean_count_and_unsorted_sets() -> None:
    payload = _issue().to_dict()
    extra = {**payload, "unexpected": True}
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        RepositoryWriteEvidenceOriginAttestation.from_dict(extra)

    boolean_count = {**payload, "binding_count": True}
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        RepositoryWriteEvidenceOriginAttestation.from_dict(boolean_count)

    unsorted = {
        **payload,
        "record_sha256s": list(reversed(payload["record_sha256s"])),
    }
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        RepositoryWriteEvidenceOriginAttestation.from_dict(unsorted)


def test_record_set_digest_cannot_be_detached() -> None:
    with pytest.raises(RepositoryWriteEvidenceOriginError):
        dataclasses.replace(_issue(), record_set_sha256="f" * 64)
