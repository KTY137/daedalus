# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.gates.guard_implementation_manifest import (
    GuardImplementationManifest,
    GuardImplementationManifestBindingError,
    GuardImplementationManifestError,
    GuardImplementationManifestSignatureError,
    GuardImplementationRecord,
    issue_guard_implementation_manifest,
    parse_guard_implementation_manifest,
    verify_guard_implementation_manifest,
)
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
CLASSIFICATION_DIGEST = "b" * 64
SECRET = b"guard-manifest-authority-secret-" * 2
ISSUED = datetime(2026, 8, 4, 17, 0, tzinfo=timezone.utc)


def _entries() -> tuple[GuardImplementationRecord, ...]:
    return (
        GuardImplementationRecord(
            contract="containment.attempt",
            implementation_target=(
                "daedalus.kernel.attempt_workspace:"
                "IsolatedAttemptCoordinator.prepare"
            ),
            implementation_sha256="c" * 64,
        ),
        GuardImplementationRecord(
            contract="spine.intent_ledger",
            implementation_target=(
                "daedalus.kernel.attempt_ledger:AttemptLedger.begin"
            ),
            implementation_sha256="d" * 64,
        ),
    )


def _manifest(**overrides: object) -> GuardImplementationManifest:
    arguments = {
        "entries": _entries(),
        "manifest_id": "guard.manifest.1",
        "authority_id": "gate.guard_registry",
        "authority_key_id": "guard.key.1",
        "authority_secret": SECRET,
        "source_revision": REVISION,
        "classification_digest": CLASSIFICATION_DIGEST,
        "issued_at": ISSUED,
        "expires_at": ISSUED + timedelta(hours=1),
    }
    arguments.update(overrides)
    return issue_guard_implementation_manifest(**arguments)


def _verify(manifest: GuardImplementationManifest, **overrides: object):
    arguments = {
        "keyring": {("gate.guard_registry", "guard.key.1"): SECRET},
        "expected_authority_id": "gate.guard_registry",
        "current_revision": REVISION,
        "expected_classification_digest": CLASSIFICATION_DIGEST,
        "now": ISSUED + timedelta(minutes=1),
    }
    arguments.update(overrides)
    return verify_guard_implementation_manifest(manifest, **arguments)


def test_issue_parse_verify_is_deterministic_and_honestly_open() -> None:
    manifest = _manifest()
    wire = canonical_json(manifest.to_dict()).encode("ascii")
    parsed = parse_guard_implementation_manifest(wire)
    assert parsed == manifest

    report = _verify(parsed)
    payload = report.to_dict()
    assert payload["guard_manifest_authenticated"] is True
    assert payload["guard_contract_semantics_verified"] is False
    assert payload["semantic_receipts_verified"] is False
    assert payload["evidence_authenticated"] is False
    assert payload["gate_report_bound"] is False
    assert payload["closed"] is False
    assert payload["entry_count"] == 2
    assert payload["blockers"] == [
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-semantic-replay-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
        "source-anchor-chain-binding-missing",
    ]
    assert report.to_dict() == _verify(parsed).to_dict()


def test_entries_are_sorted_and_contracts_are_unique() -> None:
    manifest = issue_guard_implementation_manifest(
        tuple(reversed(_entries())),
        manifest_id="guard.manifest.1",
        authority_id="gate.guard_registry",
        authority_key_id="guard.key.1",
        authority_secret=SECRET,
        source_revision=REVISION,
        classification_digest=CLASSIFICATION_DIGEST,
        issued_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )
    assert manifest.entries == _entries()
    duplicate = dataclasses.replace(
        _entries()[1],
        implementation_target=(
            "daedalus.kernel.attempt_ledger:AttemptLedger.complete"
        ),
    )
    with pytest.raises(
        GuardImplementationManifestError,
        match="contract identities must be unique",
    ):
        issue_guard_implementation_manifest(
            (_entries()[1], duplicate),
            manifest_id="guard.manifest.duplicate",
            authority_id="gate.guard_registry",
            authority_key_id="guard.key.1",
            authority_secret=SECRET,
            source_revision=REVISION,
            classification_digest=CLASSIFICATION_DIGEST,
            issued_at=ISSUED,
            expires_at=ISSUED + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    "entries",
    [
        (),
        ("not-a-record",),
    ],
)
def test_empty_or_untyped_entries_fail_inside_domain_boundary(entries) -> None:
    with pytest.raises(GuardImplementationManifestError):
        issue_guard_implementation_manifest(
            entries,
            manifest_id="guard.manifest.invalid",
            authority_id="gate.guard_registry",
            authority_key_id="guard.key.1",
            authority_secret=SECRET,
            source_revision=REVISION,
            classification_digest=CLASSIFICATION_DIGEST,
            issued_at=ISSUED,
            expires_at=ISSUED + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract", "Bad Contract"),
        ("implementation_target", "outside.module:call"),
        ("implementation_target", "daedalus.module"),
        ("implementation_sha256", "C" * 64),
    ],
)
def test_record_shape_is_strict(field: str, value: str) -> None:
    arguments = {
        "contract": "containment.attempt",
        "implementation_target": (
            "daedalus.kernel.attempt_workspace:"
            "IsolatedAttemptCoordinator.prepare"
        ),
        "implementation_sha256": "c" * 64,
    }
    arguments[field] = value
    with pytest.raises(GuardImplementationManifestError):
        GuardImplementationRecord(**arguments)


def test_signature_is_checked_before_expected_binding_projection() -> None:
    forged = dataclasses.replace(
        _manifest(),
        source_revision="e" * 40,
        classification_digest="f" * 64,
    )
    with pytest.raises(
        GuardImplementationManifestSignatureError,
        match="signature is invalid",
    ):
        _verify(
            forged,
            current_revision="e" * 40,
            expected_classification_digest="f" * 64,
        )


def test_unknown_and_wrong_authority_keys_fail() -> None:
    manifest = _manifest()
    with pytest.raises(
        GuardImplementationManifestSignatureError,
        match="unknown",
    ):
        _verify(manifest, keyring={})
    with pytest.raises(
        GuardImplementationManifestSignatureError,
        match="signature is invalid",
    ):
        _verify(
            manifest,
            keyring={
                ("gate.guard_registry", "guard.key.1"):
                    b"wrong-guard-manifest-secret-" * 2
            },
        )


def test_stale_revision_and_classification_fail_after_authentication() -> None:
    manifest = _manifest()
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="source revision is stale",
    ):
        _verify(manifest, current_revision="e" * 40)
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="classification digest is stale",
    ):
        _verify(
            manifest,
            expected_classification_digest="f" * 64,
        )


def test_expected_authority_is_exact() -> None:
    manifest = _manifest()
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="authority differs",
    ):
        _verify(
            manifest,
            expected_authority_id="gate.other_registry",
        )


def test_future_expired_and_overlong_manifests_fail() -> None:
    manifest = _manifest()
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="not yet valid",
    ):
        _verify(manifest, now=ISSUED - timedelta(microseconds=1))
    with pytest.raises(
        GuardImplementationManifestBindingError,
        match="expired",
    ):
        _verify(manifest, now=ISSUED + timedelta(hours=1))
    with pytest.raises(
        GuardImplementationManifestError,
        match="must not exceed 24 hours",
    ):
        _manifest(expires_at=ISSUED + timedelta(hours=24, microseconds=1))


def test_signed_entry_or_subject_substitution_fails() -> None:
    manifest = _manifest()
    changed_entry = dataclasses.replace(
        manifest.entries[0],
        implementation_sha256="e" * 64,
    )
    entries = tuple(
        sorted(
            (changed_entry, manifest.entries[1]),
            key=GuardImplementationRecord.sort_key,
        )
    )
    entry_set = hashlib.sha256(
        canonical_json([entry.to_dict() for entry in entries]).encode("ascii")
    ).hexdigest()
    forged = dataclasses.replace(
        manifest,
        entries=entries,
        entry_set_sha256=entry_set,
    )
    with pytest.raises(
        GuardImplementationManifestSignatureError,
        match="signature is invalid",
    ):
        _verify(forged)


@pytest.mark.parametrize(
    "wire",
    [
        b"\xef\xbb\xbf{}",
        b'{"a":1,"a":2}',
        b'{"value":NaN}',
        b'{"schema":"x"}\x00',
    ],
)
def test_malformed_wire_fails_closed(wire: bytes) -> None:
    with pytest.raises(GuardImplementationManifestError):
        parse_guard_implementation_manifest(wire)


def test_noncanonical_wire_is_rejected_before_schema_projection() -> None:
    manifest = _manifest()
    canonical = canonical_json(manifest.to_dict())
    noncanonical = ("{ " + canonical[1:]).encode("ascii")
    with pytest.raises(
        GuardImplementationManifestError,
        match="not canonical JSON",
    ):
        parse_guard_implementation_manifest(noncanonical)


def test_oversized_wire_is_bounded() -> None:
    with pytest.raises(
        GuardImplementationManifestError,
        match="bounded wire size",
    ):
        parse_guard_implementation_manifest(b"x" * 1_048_577)


def test_wire_requires_exact_schema_and_no_extra_keys() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["unexpected"] = True
    with pytest.raises(
        GuardImplementationManifestError,
        match="exact schema",
    ):
        parse_guard_implementation_manifest(
            canonical_json(payload).encode("ascii")
        )
