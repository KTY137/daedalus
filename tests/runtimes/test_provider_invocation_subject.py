from __future__ import annotations

import dataclasses

import pytest

from daedalus.runtimes.provider.invocation import (
    ProviderInvocationSubject,
    ProviderInvocationSubjectError,
)


REVISION = "1" * 40


def _subject() -> ProviderInvocationSubject:
    return ProviderInvocationSubject(
        provider_id="provider.external-fixture",
        adapter_id="adapter.external-fixture-v1",
        adapter_artifact_sha256="2" * 64,
        adapter_config_sha256="3" * 64,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution_id="provider-invocation-execution",
        idempotency_key="provider-invocation-idempotency",
        execution_request_sha256="4" * 64,
        lease_sha256="5" * 64,
        source_revision=REVISION,
    )


def test_provider_invocation_subject_has_stable_exact_round_trip() -> None:
    subject = _subject()
    payload = subject.to_dict()
    rebuilt = ProviderInvocationSubject.from_dict(payload)
    assert rebuilt == subject
    assert rebuilt.digest == subject.digest
    assert len(subject.digest) == 64


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("provider_id", "provider.foreign"),
        ("adapter_id", "adapter.foreign-v2"),
        ("adapter_artifact_sha256", "6" * 64),
        ("adapter_config_sha256", "7" * 64),
        ("entrypoint_id", "provider.foreign-entrypoint"),
        ("runtime_id", "runtime-foreign"),
        ("execution_id", "provider-invocation-foreign-execution"),
        ("idempotency_key", "provider-invocation-foreign-idempotency"),
        ("execution_request_sha256", "8" * 64),
        ("lease_sha256", "9" * 64),
        ("source_revision", "a" * 40),
    ],
)
def test_every_subject_dimension_changes_digest(field: str, replacement: str) -> None:
    subject = _subject()
    changed = dataclasses.replace(subject, **{field: replacement})
    assert changed.digest != subject.digest


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {**_subject().to_dict(), "extra": "forbidden"},
        {
            key: value
            for key, value in _subject().to_dict().items()
            if key != "provider_id"
        },
    ],
)
def test_subject_mapping_requires_exact_fields(payload) -> None:
    with pytest.raises(ProviderInvocationSubjectError, match="fields are not exact"):
        ProviderInvocationSubject.from_dict(payload)


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("provider_id", " provider.external-fixture "),
        ("adapter_id", ""),
        ("adapter_artifact_sha256", "not-a-digest"),
        ("adapter_config_sha256", "A" * 64),
        ("execution_request_sha256", "4" * 63),
        ("lease_sha256", "5" * 65),
        ("source_revision", "not-a-revision"),
    ],
)
def test_noncanonical_subject_values_refuse(field: str, replacement: str) -> None:
    with pytest.raises(ProviderInvocationSubjectError, match="malformed"):
        dataclasses.replace(_subject(), **{field: replacement})


def test_subject_is_identity_only_and_has_no_execution_method() -> None:
    subject = _subject()
    assert not hasattr(subject, "invoke")
    assert not hasattr(subject, "execute")
    assert not hasattr(subject, "callback")
