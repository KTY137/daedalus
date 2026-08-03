from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from daedalus.kernel import OFFLOAD_EXECUTION_EFFECTS, OffloadExecutionPlan
from daedalus.schemas import ContractProvenance, EffectScope
from daedalus.spine.effect_boundary import REGISTRY_BY_ID
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "a" * 40


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _plan(**overrides: object) -> OffloadExecutionPlan:
    digests = {
        "intent_sha256": _sha("intent"),
        "task_sha256": _sha("task"),
        "source_artifact_sha256": _sha("source-artifact"),
        "worktree_fingerprint_sha256": _sha("worktree-fingerprint"),
        "model_sha256": _sha("ollama-model"),
        "policy_decision_sha256": _sha("policy"),
        "availability_sha256": _sha("availability"),
        "routing_decision_sha256": _sha("routing"),
        "runtime_manifest_sha256": _sha("runtime"),
        "runtime_conformance_sha256": _sha("conformance"),
    }
    values: dict[str, object] = {
        "plan_id": "offload-plan-1",
        "spine_intent_id": 1,
        **digests,
        "task_id": "task-1",
        "source_revision": REVISION,
        "worktree_id": "attempt-worktree-1",
        "provider_id": "ollama",
        "model_id": "qwen2.5-coder:7b",
        "provider_endpoint": "http://127.0.0.1:11434",
        "write_mode": "write",
        "target_paths": ("src/package/module.py",),
        "requested_effects": OFFLOAD_EXECUTION_EFFECTS,
        "effect_scope": EffectScope(
            read_only=False,
            writable_paths=("src/package/module.py",),
            egress_endpoints=("http://127.0.0.1:11434",),
            tools=("python",),
            secret_refs=(),
            max_cost_microusd=0,
            max_concurrency=1,
            timeout_s=120,
            kill_switch_ref="mission-1-kill",
        ),
        "kill_switch_generation": 3,
        "max_model_calls": 1,
        "timeout_s": 120,
        "max_cost_microusd": 0,
        "tool_argv": ("python", "-m", "daedalus.tools.vet", "src/package/module.py"),
        "verifier_argv": ("python", "-m", "pytest", "-q", "tests/test_module.py"),
        "metrics_enabled": False,
        "drafts_enabled": False,
        "auto_mint_enabled": False,
        "provenance": ContractProvenance(
            origin="tests.offload-plan",
            source_revision=REVISION,
            created_at="2026-08-03T00:00:00+00:00",
            input_digests=tuple(digests.values()),
            trace_id="mission-1",
        ),
    }
    values.update(overrides)
    return OffloadExecutionPlan(**values)


def test_plan_is_immutable_canonical_and_roundtrips_without_type_drift() -> None:
    target_paths = ["src\\package\\module.py"]
    tool_argv = ["python", "-m", "daedalus.tools.vet", "src/package/module.py"]
    scope = EffectScope(
        read_only=False,
        writable_paths=target_paths,
        egress_endpoints=("http://127.0.0.1:11434/",),
        tools=("python",),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref="mission-1-kill",
    )
    plan = _plan(
        target_paths=target_paths,
        provider_endpoint="http://127.0.0.1:11434/",
        effect_scope=scope,
        tool_argv=tool_argv,
    )
    before = plan.digest

    target_paths.append("src/late-mutation.py")
    tool_argv.append("--unsafe")

    assert plan.target_paths == ("src/package/module.py",)
    assert plan.provider_endpoint == "http://127.0.0.1:11434"
    assert plan.tool_argv == (
        "python",
        "-m",
        "daedalus.tools.vet",
        "src/package/module.py",
    )
    assert plan.digest == before == canonical_sha(plan.to_dict())
    assert plan.to_json() == canonical_json(plan.to_dict())
    assert OffloadExecutionPlan.from_dict(json.loads(plan.to_json())) == plan
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.plan_id = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    (
        "intent_sha256",
        "task_sha256",
        "source_artifact_sha256",
        "worktree_fingerprint_sha256",
        "model_sha256",
        "policy_decision_sha256",
        "availability_sha256",
        "routing_decision_sha256",
        "runtime_manifest_sha256",
        "runtime_conformance_sha256",
    ),
)
def test_digest_tampering_requires_provenance_rebinding_and_breaks_sealed_digest(
    field: str,
) -> None:
    original = _plan()
    payload = original.to_dict()
    old_digest = payload[field]
    new_digest = _sha(f"tampered-{field}")
    payload[field] = new_digest

    with pytest.raises(ValueError, match="provenance"):
        OffloadExecutionPlan.from_dict(payload)

    provenance = dict(payload["provenance"])
    provenance["input_digests"] = [
        new_digest if value == old_digest else value
        for value in provenance["input_digests"]
    ]
    payload["provenance"] = provenance
    rebound = OffloadExecutionPlan.from_dict(payload)

    assert rebound.digest != original.digest
    assert rebound.to_dict()[field] == new_digest


@pytest.mark.parametrize(
    "mutation, error",
    (
        (
            lambda body: body["effect_scope"].update(
                writable_paths=["src/other.py"]
            ),
            "writable_paths",
        ),
        (
            lambda body: body["effect_scope"].update(
                egress_endpoints=["http://127.0.0.1:11435"]
            ),
            "egress_endpoints",
        ),
        (
            lambda body: body["effect_scope"].update(timeout_s=121),
            "timeout",
        ),
        (
            lambda body: body["effect_scope"].update(tools=["python", "ruff"]),
            "tools",
        ),
        (
            lambda body: body["effect_scope"].update(secret_refs=["token"]),
            "secret_refs",
        ),
        (
            lambda body: body.update(provider_endpoint="http://localhost:11434"),
            "numeric loopback",
        ),
        (
            lambda body: body.update(target_paths=["../primary-checkout"]),
            "workspace",
        ),
        (
            lambda body: body.update(
                requested_effects=["filesystem_write", "network_egress"]
            ),
            "requested_effects",
        ),
        (
            lambda body: body.update(metrics_enabled=True),
            "metrics_enabled",
        ),
        (
            lambda body: body.update(max_model_calls=2),
            "max_model_calls",
        ),
        (
            lambda body: body.update(
                target_paths=["src/package/module.py", "docs/guide.md"]
            ),
            "exactly one",
        ),
    ),
)
def test_scope_endpoint_budget_and_hidden_side_effect_tampering_fail_closed(
    mutation,
    error: str,
) -> None:
    payload = _plan().to_dict()
    mutation(payload)

    with pytest.raises(ValueError, match=error):
        OffloadExecutionPlan.from_dict(payload)


def test_identity_and_argv_tampering_is_digest_visible_and_wire_is_closed() -> None:
    original = _plan()
    payload = original.to_dict()
    payload["spine_intent_id"] = 2
    payload["tool_argv"] = [*payload["tool_argv"], "--strict"]
    changed = OffloadExecutionPlan.from_dict(payload)

    assert changed.digest != original.digest

    invalid_intent = original.to_dict()
    invalid_intent["spine_intent_id"] = 0
    with pytest.raises(ValueError, match="spine_intent_id"):
        OffloadExecutionPlan.from_dict(invalid_intent)

    stale_generation = original.to_dict()
    stale_generation["kill_switch_generation"] = -1
    with pytest.raises(ValueError, match="kill_switch_generation"):
        OffloadExecutionPlan.from_dict(stale_generation)

    unknown = original.to_dict()
    unknown["untracked_option"] = True
    with pytest.raises(ValueError, match="unknown field"):
        OffloadExecutionPlan.from_dict(unknown)

    missing = original.to_dict()
    missing.pop("routing_decision_sha256")
    with pytest.raises(ValueError, match="missing field"):
        OffloadExecutionPlan.from_dict(missing)

    command_string = original.to_dict()
    command_string["verifier_argv"] = "python -m pytest"
    with pytest.raises(ValueError, match="argv sequence"):
        OffloadExecutionPlan.from_dict(command_string)

    host_path = original.to_dict()
    host_path["tool_argv"][0] = "C:\\Python312\\python.exe"
    with pytest.raises(ValueError, match="argv executable"):
        OffloadExecutionPlan.from_dict(host_path)


def test_json_schema_is_closed_complete_and_matches_security_constants() -> None:
    plan = _plan()
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "configs/schemas/offload-execution-plan-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_type"] == {
        "const": "daedalus.offload-execution-plan"
    }
    assert schema["properties"]["requested_effects"] == {
        "const": list(OFFLOAD_EXECUTION_EFFECTS)
    }
    registered_effects = tuple(
        sorted(effect.value for effect in REGISTRY_BY_ID["python.offload"].effects)
    )
    assert OFFLOAD_EXECUTION_EFFECTS == registered_effects
    assert schema["properties"]["provider_id"] == {"const": "ollama"}
    assert schema["properties"]["write_mode"] == {"const": "write"}
    assert schema["properties"]["max_model_calls"] == {"const": 1}
    assert schema["properties"]["max_cost_microusd"] == {"const": 0}
    for flag in ("metrics_enabled", "drafts_enabled", "auto_mint_enabled"):
        assert schema["properties"][flag] == {"const": False}
    assert set(plan.to_dict()) == set(schema["required"]) == set(schema["properties"])
    assert set(plan.to_dict()["effect_scope"]) == set(
        schema["$defs"]["effectScope"]["required"]
    )
    assert set(plan.to_dict()["provenance"]) == set(
        schema["$defs"]["provenance"]["required"]
    )
