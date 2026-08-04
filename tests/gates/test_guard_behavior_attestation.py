from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.gates.guard_behavior_attestation import (
    GuardBehaviorAttestationBindingError,
    GuardBehaviorAttestationError,
    GuardBehaviorAttestationSignatureError,
    GuardBehaviorCaseResult,
    issue_guard_behavior_attestation,
    parse_guard_behavior_attestation,
    verify_guard_behavior_attestation,
)
from daedalus.gates.repository_write_guard_structure import (
    GuardStructureRecord,
    RepositoryWriteGuardStructureReport,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
SECRET = b"guard-behavior-authority-secret-0001"
NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _record(
    contract: str = "guard.one",
    *,
    surface_sha256: str | None = None,
    locator_digest: str | None = None,
) -> GuardStructureRecord:
    payload = {
        "contract": contract,
        "implementation_target": "daedalus.policy:check_guard",
        "implementation_sha256": _sha("implementation-" + contract),
        "source_path": "daedalus/policy.py",
        "source_size": 128,
        "definition_kind": "function",
        "line": 10,
        "column": 0,
        "end_line": 20,
        "end_column": 1,
    }
    structure_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    return GuardStructureRecord(
        surface_sha256=surface_sha256 or _sha("surface-" + contract),
        locator="cas:sha256:" + (locator_digest or _sha("locator-" + contract)),
        structure_sha256=structure_sha256,
        **payload,
    )


def _structure_report(
    contracts: tuple[str, ...] = ("guard.one",),
) -> RepositoryWriteGuardStructureReport:
    records = tuple(
        sorted(
            (_record(contract) for contract in contracts),
            key=GuardStructureRecord.sort_key,
        )
    )
    record_set_sha256 = hashlib.sha256(
        canonical_json([record.to_dict() for record in records]).encode(
            "ascii"
        )
    ).hexdigest()
    return RepositoryWriteGuardStructureReport(
        source_revision=REVISION,
        classification_digest=_sha("classification"),
        materialization_digest=_sha("materialization"),
        source_anchor_report_digest=_sha("source-anchor"),
        origin_attestation_digest=_sha("origin"),
        guard_manifest_report_digest=_sha("manifest-report"),
        guard_manifest_digest=_sha("manifest"),
        classification_count=1,
        production_classification_count=1,
        guard_contract_count=len(contracts),
        guard_binding_count=len(records),
        record_set_sha256=record_set_sha256,
        records=records,
    )


def _case(
    contract: str,
    case_id: str,
    expected: str,
    observed: str | None = None,
) -> GuardBehaviorCaseResult:
    return GuardBehaviorCaseResult.create(
        contract=contract,
        case_id=case_id,
        vector_sha256=_sha("vector-" + contract + "-" + case_id),
        expected_outcome=expected,
        observed_outcome=observed or expected,
        transcript_sha256=_sha("transcript-" + contract + "-" + case_id),
    )


def _cases(
    contracts: tuple[str, ...] = ("guard.one",),
) -> tuple[GuardBehaviorCaseResult, ...]:
    result = []
    for contract in contracts:
        result.extend(
            (
                _case(contract, "allow.nominal", "allow"),
                _case(contract, "refuse.adversarial", "refuse"),
            )
        )
    return tuple(result)


def _issue(
    report: RepositoryWriteGuardStructureReport | None = None,
    *,
    cases: tuple[GuardBehaviorCaseResult, ...] | None = None,
    source_revision: str = REVISION,
):
    report = report or _structure_report()
    return issue_guard_behavior_attestation(
        cases or _cases(tuple(sorted({row.contract for row in report.records}))),
        attestation_id="guard.behavior.1",
        authority_id="guard.behavior.authority",
        authority_key_id="key.1",
        authority_secret=SECRET,
        source_revision=source_revision,
        classification_digest=report.classification_digest,
        guard_structure_report_digest=report.digest,
        guard_structure_record_set_sha256=report.record_set_sha256,
        harness_id="guard.harness.1",
        harness_sha256=_sha("harness"),
        runtime_manifest_digest=_sha("runtime-manifest"),
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def _verify(attestation, report=None, **overrides):
    report = report or _structure_report()
    arguments = {
        "keyring": {
            ("guard.behavior.authority", "key.1"): SECRET,
        },
        "expected_authority_id": "guard.behavior.authority",
        "current_revision": REVISION,
        "expected_harness_id": "guard.harness.1",
        "expected_harness_sha256": _sha("harness"),
        "expected_runtime_manifest_digest": _sha("runtime-manifest"),
        "now": NOW + timedelta(minutes=1),
    }
    arguments.update(overrides)
    return verify_guard_behavior_attestation(
        attestation, report, **arguments
    )


def test_issue_parse_verify_is_deterministic_and_honestly_open():
    report = _structure_report()
    first = _issue(report)
    second = _issue(report)
    assert first == second
    raw = canonical_json(first.to_dict()).encode("ascii")
    assert parse_guard_behavior_attestation(raw) == first

    verified = _verify(first, report)
    payload = verified.to_dict()
    assert payload["guard_behavior_attestation_authenticated"] is True
    assert payload["positive_and_negative_vectors_complete"] is True
    assert payload["guard_execution_replayed"] is False
    assert payload["guard_contract_semantics_verified"] is False
    assert payload["runtime_conformance_verified"] is False
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert verified.contract_count == 1
    assert verified.case_count == 2


def test_multiple_contracts_require_exact_positive_and_negative_coverage():
    contracts = ("guard.one", "guard.two")
    report = _structure_report(contracts)
    verified = _verify(_issue(report), report)
    assert verified.contract_count == 2
    assert verified.case_count == 4

    incomplete = _issue(
        report,
        cases=(
            _case("guard.one", "allow.nominal", "allow"),
            _case("guard.one", "refuse.adversarial", "refuse"),
            _case("guard.two", "allow.nominal", "allow"),
        ),
    )
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="lacks allow/refuse coverage",
    ):
        _verify(incomplete, report)


def test_failed_case_refuses_authenticated_projection():
    report = _structure_report()
    attestation = _issue(
        report,
        cases=(
            _case("guard.one", "allow.nominal", "allow", "refuse"),
            _case("guard.one", "refuse.adversarial", "refuse"),
        ),
    )
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="failed case",
    ):
        _verify(attestation, report)


def test_contract_set_substitution_refuses():
    report = _structure_report()
    attestation = _issue(
        report,
        cases=(
            _case("other.guard", "allow.nominal", "allow"),
            _case("other.guard", "refuse.adversarial", "refuse"),
        ),
    )
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="contract set differs",
    ):
        _verify(attestation, report)


def test_signature_is_checked_before_subject_bindings():
    report = _structure_report()
    attestation = _issue(report)
    forged = dataclasses.replace(
        attestation,
        classification_digest=_sha("forged"),
    )
    with pytest.raises(GuardBehaviorAttestationSignatureError):
        _verify(forged, report)


def test_unknown_and_wrong_keys_refuse():
    report = _structure_report()
    attestation = _issue(report)
    with pytest.raises(
        GuardBehaviorAttestationSignatureError,
        match="unknown",
    ):
        _verify(attestation, report, keyring={})
    with pytest.raises(
        GuardBehaviorAttestationSignatureError,
        match="invalid",
    ):
        _verify(
            attestation,
            report,
            keyring={
                ("guard.behavior.authority", "key.1"): b"z" * 32,
            },
        )


@pytest.mark.parametrize(
    "override,match",
    [
        ({"current_revision": "b" * 40}, "source_revision"),
        ({"expected_authority_id": "other.authority"}, "authority_id"),
        ({"expected_harness_id": "other.harness"}, "harness_id"),
        ({"expected_harness_sha256": _sha("other-harness")}, "harness_sha256"),
        (
            {"expected_runtime_manifest_digest": _sha("other-runtime")},
            "runtime_manifest_digest",
        ),
    ],
)
def test_stale_expected_bindings_refuse(override, match):
    report = _structure_report()
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match=match,
    ):
        _verify(_issue(report), report, **override)


def test_stale_structure_report_and_record_set_refuse():
    report = _structure_report()
    attestation = _issue(report)
    changed = _structure_report(("guard.two",))
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="classification_digest|guard_structure",
    ):
        _verify(attestation, changed)


def test_future_expired_and_excessive_ttl_refuse():
    report = _structure_report()
    attestation = _issue(report)
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="not yet valid",
    ):
        _verify(attestation, report, now=NOW - timedelta(seconds=1))
    with pytest.raises(
        GuardBehaviorAttestationBindingError,
        match="expired",
    ):
        _verify(attestation, report, now=NOW + timedelta(hours=1))

    with pytest.raises(
        GuardBehaviorAttestationError,
        match="24 hours",
    ):
        issue_guard_behavior_attestation(
            _cases(),
            attestation_id="guard.behavior.1",
            authority_id="guard.behavior.authority",
            authority_key_id="key.1",
            authority_secret=SECRET,
            source_revision=REVISION,
            classification_digest=report.classification_digest,
            guard_structure_report_digest=report.digest,
            guard_structure_record_set_sha256=report.record_set_sha256,
            harness_id="guard.harness.1",
            harness_sha256=_sha("harness"),
            runtime_manifest_digest=_sha("runtime-manifest"),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=25),
        )


def test_duplicate_case_identity_refuses():
    case = _case("guard.one", "allow.nominal", "allow")
    report = _structure_report()
    with pytest.raises(
        GuardBehaviorAttestationError,
        match="unique",
    ):
        _issue(report, cases=(case, case))


def test_noncanonical_valid_wire_is_rejected_before_schema_projection():
    raw = canonical_json(_issue().to_dict()).encode("ascii") + b"\n"
    with pytest.raises(
        GuardBehaviorAttestationError,
        match="not canonical JSON",
    ):
        parse_guard_behavior_attestation(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"{} ",
        b"\xef\xbb\xbf{}",
        b'{"x":"\\u0000"}',
        b'{"x":NaN}',
        b'{"schema":1,"schema":2}',
        b"\xff",
    ],
)
def test_malformed_or_noncanonical_wire_refuses(raw):
    with pytest.raises(GuardBehaviorAttestationError):
        parse_guard_behavior_attestation(raw)


def test_case_digest_and_outcome_substitution_refuse():
    case = _case("guard.one", "allow.nominal", "allow")
    with pytest.raises(GuardBehaviorAttestationError):
        dataclasses.replace(case, observed_outcome="refuse")
    with pytest.raises(GuardBehaviorAttestationError):
        dataclasses.replace(case, result_sha256=_sha("forged-result"))
    with pytest.raises(GuardBehaviorAttestationError):
        GuardBehaviorCaseResult.create(
            contract="guard.one",
            case_id="bad",
            vector_sha256=_sha("v"),
            expected_outcome="error",
            observed_outcome="error",
            transcript_sha256=_sha("t"),
        )


def test_malformed_types_and_short_secret_refuse():
    report = _structure_report()
    with pytest.raises(GuardBehaviorAttestationError):
        issue_guard_behavior_attestation(
            "not-cases",
            attestation_id="guard.behavior.1",
            authority_id="guard.behavior.authority",
            authority_key_id="key.1",
            authority_secret=SECRET,
            source_revision=REVISION,
            classification_digest=report.classification_digest,
            guard_structure_report_digest=report.digest,
            guard_structure_record_set_sha256=report.record_set_sha256,
            harness_id="guard.harness.1",
            harness_sha256=_sha("harness"),
            runtime_manifest_digest=_sha("runtime-manifest"),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    with pytest.raises(GuardBehaviorAttestationError, match="32 bytes"):
        issue_guard_behavior_attestation(
            _cases(),
            attestation_id="guard.behavior.1",
            authority_id="guard.behavior.authority",
            authority_key_id="key.1",
            authority_secret=b"short",
            source_revision=REVISION,
            classification_digest=report.classification_digest,
            guard_structure_report_digest=report.digest,
            guard_structure_record_set_sha256=report.record_set_sha256,
            harness_id="guard.harness.1",
            harness_sha256=_sha("harness"),
            runtime_manifest_digest=_sha("runtime-manifest"),
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
