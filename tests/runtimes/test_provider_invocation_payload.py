from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from daedalus.runtimes.provider.invocation import ProviderInvocationSubject
from daedalus.runtimes.provider.invocation_payload import (
    ProviderInvocationPayload,
    ProviderInvocationPayloadError,
    build_provider_invocation_payload,
)


REVISION = "0c437da95838f34b0cc1eb038d6886aa614e7548"


def _subject(**changes: str) -> ProviderInvocationSubject:
    values = {
        "provider_id": "provider.claude",
        "adapter_id": "adapter.claude-cli",
        "adapter_artifact_sha256": "1" * 64,
        "adapter_config_sha256": "2" * 64,
        "entrypoint_id": "provider.claude",
        "runtime_id": "claude-code-cli",
        "execution_id": "exec-1",
        "idempotency_key": "idem-1",
        "execution_request_sha256": "3" * 64,
        "lease_sha256": "4" * 64,
        "source_revision": REVISION,
    }
    values.update(changes)
    return ProviderInvocationSubject(**values)


def _payload(body=None) -> ProviderInvocationPayload:
    return build_provider_invocation_payload(
        _subject(),
        payload_schema_id="claude.cli.invocation.v1",
        body=body
        if body is not None
        else {
            "objective": "repair the parser",
            "workspace": ".worktrees/attempt-1",
            "paths": ["daedalus/parser.py", "tests/test_parser.py"],
            "agent": {"name": "implementer", "model_tier": "sonnet"},
            "model": "sonnet",
            "timeout_s": 300,
        },
    )


def test_payload_round_trips_with_stable_subject_bound_identity() -> None:
    payload = _payload()
    restored = ProviderInvocationPayload.from_dict(payload.to_dict())

    assert restored.to_dict() == payload.to_dict()
    assert restored.digest == payload.digest
    assert restored.provider_id == "provider.claude"
    assert restored.adapter_id == "adapter.claude-cli"
    assert restored.invocation_subject_sha256 == _subject().digest
    assert list(restored.to_dict()["body"]) == [
        "agent",
        "model",
        "objective",
        "paths",
        "timeout_s",
        "workspace",
    ]


def test_semantically_relevant_per_call_changes_change_payload_identity() -> None:
    baseline = _payload()
    for field, value in (
        ("objective", "repair the scheduler"),
        ("workspace", ".worktrees/attempt-2"),
        ("paths", ["daedalus/scheduler.py"]),
        ("agent", {"name": "critic", "model_tier": "opus"}),
        ("model", "opus"),
        ("timeout_s", 301),
    ):
        body = baseline.to_dict()["body"]
        body[field] = value
        changed = _payload(body)
        assert changed.digest != baseline.digest, field


def test_payload_is_structurally_immutable_and_does_not_retain_input_aliases() -> None:
    source = {"nested": {"values": ["a", "b"]}}
    payload = _payload(source)
    source["nested"]["values"].append("mutated")

    assert payload.to_dict()["body"] == {"nested": {"values": ["a", "b"]}}
    with pytest.raises(TypeError):
        payload.body["new"] = "value"  # type: ignore[index]
    nested = payload.body["nested"]
    with pytest.raises(TypeError):
        nested["new"] = "value"  # type: ignore[index]
    assert isinstance(nested["values"], tuple)
    with pytest.raises(FrozenInstanceError):
        payload.provider_id = "provider.foreign"  # type: ignore[misc]


def test_payload_schema_and_subject_are_part_of_identity() -> None:
    body = _payload().to_dict()["body"]
    baseline = _payload(body)
    other_schema = build_provider_invocation_payload(
        _subject(),
        payload_schema_id="claude.cli.invocation.v2",
        body=body,
    )
    other_subject = build_provider_invocation_payload(
        _subject(adapter_config_sha256="5" * 64),
        payload_schema_id="claude.cli.invocation.v1",
        body=body,
    )

    assert other_schema.digest != baseline.digest
    assert other_subject.digest != baseline.digest
    assert other_subject.invocation_subject_sha256 != baseline.invocation_subject_sha256


@pytest.mark.parametrize(
    "body",
    [
        {"float": 1.5},
        {"bytes": b"ambient"},
        {"tuple": ("not", "canonical")},
        {"set": {"not", "canonical"}},
        {"callable": lambda: None},
        {1: "non-string-key"},
        {"": "empty-key"},
        {"nul": "bad\x00value"},
        {"integer": 2**63},
    ],
)
def test_ambient_or_nondeterministic_payload_values_fail_closed(body) -> None:
    with pytest.raises(ProviderInvocationPayloadError):
        _payload(body)


def test_container_subclasses_fail_closed_at_public_boundary() -> None:
    class PayloadDict(dict):
        pass

    with pytest.raises(ProviderInvocationPayloadError):
        build_provider_invocation_payload(
            _subject(),
            payload_schema_id="claude.cli.invocation.v1",
            body=PayloadDict(objective="x"),
        )


def test_nested_subclass_fails_closed_without_running_custom_iteration() -> None:
    class PayloadList(list):
        pass

    with pytest.raises(ProviderInvocationPayloadError):
        _payload({"paths": PayloadList(["a"])} )


def test_depth_node_and_string_resource_fences_are_enforced() -> None:
    nested = {"root": []}
    cursor = nested["root"]
    for _ in range(10):
        child = []
        cursor.append(child)
        cursor = child
    with pytest.raises(ProviderInvocationPayloadError, match="depth"):
        _payload(nested)

    with pytest.raises(ProviderInvocationPayloadError, match="node"):
        _payload({"many": list(range(2050))})

    with pytest.raises(ProviderInvocationPayloadError, match="too long"):
        _payload({"text": "x" * 16_385})


def test_from_dict_rejects_shape_schema_and_authority_claim_escalation() -> None:
    payload = _payload()

    candidate = payload.to_dict()
    candidate["unexpected"] = True
    with pytest.raises(ProviderInvocationPayloadError):
        ProviderInvocationPayload.from_dict(candidate)

    candidate = payload.to_dict()
    candidate["schema"] = "foreign-schema"
    with pytest.raises(ProviderInvocationPayloadError):
        ProviderInvocationPayload.from_dict(candidate)

    for claim in (
        "provider_execution_allowed",
        "effect_start_authorized",
        "callback_seam_removed",
    ):
        candidate = payload.to_dict()
        candidate[claim] = True
        with pytest.raises(ProviderInvocationPayloadError, match="escalated"):
            ProviderInvocationPayload.from_dict(candidate)


def test_exact_subject_type_is_required() -> None:
    class SubjectSubclass(ProviderInvocationSubject):
        pass

    subject = SubjectSubclass(**_subject().to_dict())
    with pytest.raises(ProviderInvocationPayloadError, match="exact"):
        build_provider_invocation_payload(
            subject,
            payload_schema_id="claude.cli.invocation.v1",
            body={"objective": "x"},
        )
