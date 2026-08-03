from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
from pathlib import Path

import jsonschema
import pytest

from daedalus.kernel.contracts import (
    OFFLOAD_EXECUTION_EFFECTS,
    OFFLOAD_MAX_METADATA_CALLS,
    OFFLOAD_MAX_MODEL_CALLS,
    OFFLOAD_MAX_RESPONSE_BYTES,
    OffloadExecutionPlan,
    OffloadExecutionPlanV1,
    OffloadExecutionPlanV2,
    OffloadExecutionPlanV3,
    decode_offload_execution_plan,
    derive_offload_recovery_path,
    derive_offload_staging_path,
    offload_recovery_path_sha256,
    offload_staging_path_sha256,
)
from daedalus.kernel.runtime_tools import RuntimeToolBinding, RuntimeToolBindingError
from daedalus.schemas import ContractProvenance, EffectScope
from daedalus.spine.effect_boundary import REGISTRY_BY_ID
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "a" * 40
NOW = "2026-08-03T00:00:00+00:00"
TARGET = "src/package/module.py"
TOOL_ID = "python.test-runner"
ATTEMPT_ID = "attempt-1"
WORKSPACE_ID = "task-attempt-task-1-deadbeef-a1b2c3"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _digest_fields() -> dict[str, str]:
    return {
        name: _sha(name)
        for name in (
            "spine_intent_sha256",
            "attempt_contract_sha256",
            "task_sha256",
            "base_source_artifact_sha256",
            "workspace_attestation_sha256",
            "workspace_observation_sha256",
            "target_before_sha256",
            "expected_model_sha256",
            "prompt_template_sha256",
            "prompt_sha256",
            "response_schema_sha256",
            "ollama_request_sha256",
            "attempt_policy_decision_sha256",
            "runtime_manifest_sha256",
            "runtime_conformance_sha256",
            "runtime_tool_binding_sha256",
        )
    }


def _scope(
    *,
    target_path: str = TARGET,
    staging_path: str | None = None,
    recovery_path: str | None = None,
    endpoint: str = "http://127.0.0.1:11434",
    tool_id: str = TOOL_ID,
    timeout_s: int = 120,
) -> EffectScope:
    exact_staging = staging_path or derive_offload_staging_path(
        attempt_id=ATTEMPT_ID,
        workspace_id=WORKSPACE_ID,
        target_path=target_path,
    )
    exact_recovery = recovery_path or derive_offload_recovery_path(
        attempt_id=ATTEMPT_ID,
        workspace_id=WORKSPACE_ID,
        target_path=target_path,
    )
    return EffectScope(
        read_only=False,
        writable_paths=tuple(sorted((target_path, exact_staging, exact_recovery))),
        egress_endpoints=(endpoint,),
        tools=(tool_id,),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=timeout_s,
        kill_switch_ref="mission-1-kill",
    )


def _plan(**overrides: object) -> OffloadExecutionPlan:
    digests = _digest_fields()
    attempt_id = str(overrides.get("attempt_id", ATTEMPT_ID))
    workspace_id = str(overrides.get("workspace_id", WORKSPACE_ID))
    target_path = str(overrides.get("target_path", TARGET))
    staging_path = str(
        overrides.get(
            "staging_path",
            derive_offload_staging_path(
                attempt_id=attempt_id,
                workspace_id=workspace_id,
                target_path=target_path,
            ),
        )
    )
    staging_sha = offload_staging_path_sha256(staging_path)
    recovery_path = str(
        overrides.get(
            "recovery_path",
            derive_offload_recovery_path(
                attempt_id=attempt_id,
                workspace_id=workspace_id,
                target_path=target_path,
            ),
        )
    )
    recovery_sha = offload_recovery_path_sha256(recovery_path)
    store_root_sha = str(
        overrides.get("artifact_store_root_sha256", _sha("artifact-store-root"))
    )
    values: dict[str, object] = {
        "spine_intent_id": 1,
        "mission_id": "mission-1",
        "attempt_id": attempt_id,
        "task_id": "task-1",
        **digests,
        "source_revision": REVISION,
        "workspace_id": workspace_id,
        "target_path": target_path,
        "target_kind": "existing-regular-utf8-file",
        "target_before_size": 23,
        "target_git_mode": "100644",
        "provider_id": "ollama",
        "runtime_id": "ollama_http",
        "provider_endpoint": "http://127.0.0.1:11434",
        "model_id": "qwen2.5-coder:7b",
        "num_ctx": 8192,
        "num_predict": 2048,
        "seed": 7,
        "temperature_milli": 0,
        "keep_alive": "0",
        "max_response_bytes": OFFLOAD_MAX_RESPONSE_BYTES,
        "max_metadata_calls": OFFLOAD_MAX_METADATA_CALLS,
        "max_model_calls": OFFLOAD_MAX_MODEL_CALLS,
        "verifier_argv": (TOOL_ID, "-q", "tests/test_module.py"),
        "verifier_timeout_s": 30,
        "requested_effects": OFFLOAD_EXECUTION_EFFECTS,
        "effect_scope": _scope(
            target_path=target_path,
            staging_path=staging_path,
            recovery_path=recovery_path,
        ),
        "kill_switch_generation": 3,
        "total_timeout_s": 120,
        "max_cost_microusd": 0,
        "provenance": ContractProvenance(
            origin="tests.offload-plan-v4",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(
                *digests.values(),
                staging_sha,
                recovery_sha,
                store_root_sha,
            ),
            trace_id="mission-1",
        ),
        "staging_path": staging_path,
        "staging_path_sha256": staging_sha,
        "recovery_path": recovery_path,
        "recovery_path_sha256": recovery_sha,
        "artifact_store_root_sha256": store_root_sha,
    }
    values.update(overrides)
    return OffloadExecutionPlan(**values)


def _v1_payload() -> dict[str, object]:
    digest_names = (
        "intent_sha256",
        "attempt_contract_sha256",
        "task_sha256",
        "source_artifact_sha256",
        "worktree_fingerprint_sha256",
        "model_sha256",
        "attempt_policy_decision_sha256",
        "availability_sha256",
        "routing_index_sha256",
        "routing_decision_sha256",
        "runtime_manifest_sha256",
        "runtime_conformance_sha256",
    )
    digests = {name: _sha(f"v1-{name}") for name in digest_names}
    return {
        "contract_type": "daedalus.offload-execution-plan",
        "contract_version": "1.0.0",
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
        "target_paths": [TARGET],
        "requested_effects": list(OFFLOAD_EXECUTION_EFFECTS),
        "effect_scope": {
            "read_only": False,
            "writable_paths": [TARGET],
            "egress_endpoints": ["http://127.0.0.1:11434"],
            "tools": ["python"],
            "secret_refs": [],
            "max_cost_microusd": 0,
            "max_concurrency": 1,
            "timeout_s": 120,
            "kill_switch_ref": "mission-1-kill",
        },
        "kill_switch_generation": 3,
        "max_model_calls": 1,
        "timeout_s": 120,
        "max_cost_microusd": 0,
        "tool_argv": ["python", "-m", "daedalus.tools.vet", TARGET],
        "verifier_argv": ["python", "-m", "pytest", "-q"],
        "metrics_enabled": False,
        "drafts_enabled": False,
        "auto_mint_enabled": False,
        "provenance": {
            "origin": "tests.offload-plan-v1",
            "source_revision": REVISION,
            "created_at": "2026-08-03T00:00:00.000000+00:00",
            "input_digests": sorted(digests.values()),
            "trace_id": "mission-1",
        },
    }


def test_v4_plan_is_frozen_canonical_closed_and_roundtrips() -> None:
    argv = [TOOL_ID, "-q", "tests/test_module.py"]
    plan = _plan(
        provider_endpoint="http://127.0.0.1:11434/",
        effect_scope=_scope(endpoint="http://127.0.0.1:11434/"),
        verifier_argv=argv,
    )
    digest = plan.digest
    argv.append("--unsafe")

    assert plan.CONTRACT_VERSION == "4.0.0"
    assert plan.provider_endpoint == "http://127.0.0.1:11434"
    assert plan.verifier_argv == (TOOL_ID, "-q", "tests/test_module.py")
    assert plan.digest == digest == canonical_sha(plan.to_dict())
    assert plan.to_json() == canonical_json(plan.to_dict())
    assert OffloadExecutionPlan.from_dict(json.loads(plan.to_json())) == plan
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.workspace_id = "other"  # type: ignore[misc]

    unknown = plan.to_dict()
    unknown["untracked_option"] = True
    with pytest.raises(ValueError, match="unknown field"):
        OffloadExecutionPlan.from_dict(unknown)
    missing = plan.to_dict()
    missing.pop("runtime_tool_binding_sha256")
    with pytest.raises(ValueError, match="missing field"):
        OffloadExecutionPlan.from_dict(missing)


def test_historical_v3_wire_remains_decodable_but_is_not_current_authority() -> None:
    current = _plan()
    payload = current.to_dict()
    payload["contract_version"] = "3.0.0"
    payload.pop("recovery_path")
    recovery_sha = payload.pop("recovery_path_sha256")
    store_root_sha = payload.pop("artifact_store_root_sha256")
    payload["effect_scope"] = {
        **payload["effect_scope"],
        "writable_paths": sorted((TARGET, current.staging_path)),
    }
    payload["provenance"] = {
        **payload["provenance"],
        "origin": "tests.offload-plan-v3",
        "input_digests": [
            value
            for value in payload["provenance"]["input_digests"]
            if value not in {recovery_sha, store_root_sha}
        ],
    }

    decoded = decode_offload_execution_plan(payload)
    assert isinstance(decoded, OffloadExecutionPlanV3)
    assert not isinstance(decoded, OffloadExecutionPlan)
    assert decoded.to_dict() == payload
    with pytest.raises(ValueError, match="contract_version"):
        OffloadExecutionPlan.from_dict(payload)


def test_historical_v2_wire_remains_decodable_but_is_not_current_authority() -> None:
    current = _plan()
    payload = current.to_dict()
    payload["contract_version"] = "2.0.0"
    payload.pop("recovery_path")
    recovery_sha = payload.pop("recovery_path_sha256")
    store_root_sha = payload.pop("artifact_store_root_sha256")
    payload.pop("staging_path")
    staging_sha = payload.pop("staging_path_sha256")
    payload["effect_scope"] = {
        **payload["effect_scope"],
        "writable_paths": [TARGET],
    }
    payload["provenance"] = {
        **payload["provenance"],
        "origin": "tests.offload-plan-v2",
        "input_digests": [
            value
            for value in payload["provenance"]["input_digests"]
            if value not in {staging_sha, recovery_sha, store_root_sha}
        ],
    }

    decoded = decode_offload_execution_plan(payload)
    assert isinstance(decoded, OffloadExecutionPlanV2)
    assert not isinstance(decoded, OffloadExecutionPlan)
    assert decoded.to_dict() == payload
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "configs/schemas/offload-execution-plan-v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(payload, schema)
    with pytest.raises(ValueError, match="contract_version"):
        OffloadExecutionPlan.from_dict(payload)


def test_historical_v1_wire_remains_decodable_without_fake_v2_migration() -> None:
    payload = _v1_payload()
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "configs/schemas/offload-execution-plan-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(payload) == set(schema["required"]) == set(schema["properties"])
    decoded = decode_offload_execution_plan(payload)
    assert isinstance(decoded, OffloadExecutionPlanV1)
    assert decoded.to_dict() == payload
    with pytest.raises(ValueError, match="contract_version"):
        OffloadExecutionPlan.from_dict(payload)


@pytest.mark.parametrize("field", tuple(_digest_fields()))
def test_every_referenced_digest_is_provenance_bound(field: str) -> None:
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


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        (lambda body: body.update(provider_id="remote"), "provider_id"),
        (lambda body: body.update(runtime_id="shell"), "runtime_id"),
        (lambda body: body.update(provider_endpoint="http://localhost:11434"), "numeric loopback"),
        (lambda body: body.update(provider_endpoint="http://127.0.0.1:0"), "explicit port"),
        (lambda body: body.update(provider_endpoint="http://127.0.0.2:11434"), "canonical loopback"),
        (lambda body: body.update(target_kind="file"), "target_kind"),
        (lambda body: body.update(target_before_size=-1), "target_before_size"),
        (lambda body: body.update(target_git_mode="120000"), "target_git_mode"),
        (lambda body: body.update(num_ctx=1024), "num_ctx"),
        (lambda body: body.update(num_predict=9000), "num_predict"),
        (lambda body: body.update(seed=-1), "seed"),
        (lambda body: body.update(temperature_milli=1), "temperature_milli"),
        (lambda body: body.update(keep_alive="5m"), "keep_alive"),
        (lambda body: body.update(max_response_bytes=2_000_001), "max_response_bytes"),
        (lambda body: body.update(max_metadata_calls=2), "max_metadata_calls"),
        (lambda body: body.update(max_model_calls=2), "max_model_calls"),
        (lambda body: body.update(max_cost_microusd=1), "max_cost_microusd"),
        (lambda body: body.update(verifier_timeout_s=121), "verifier_timeout_s"),
        (lambda body: body.update(verifier_argv="python -m pytest"), "argv sequence"),
        (
            lambda body: body["verifier_argv"].__setitem__(
                0, "C:\\Python\\python.exe"
            ),
            r"verifier_argv\[0\]",
        ),
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
        (lambda body: body["effect_scope"].update(tools=["other.tool"]), "tools"),
        (lambda body: body["effect_scope"].update(secret_refs=["token"]), "secret_refs"),
        (lambda body: body["effect_scope"].update(max_cost_microusd=1), "max_cost"),
        (lambda body: body["effect_scope"].update(max_concurrency=2), "max_concurrency"),
        (lambda body: body["effect_scope"].update(timeout_s=119), "timeout"),
        (lambda body: body.update(requested_effects=["filesystem_write"]), "requested_effects"),
        (lambda body: body.update(kill_switch_generation=-1), "kill_switch_generation"),
    ),
)
def test_plan_rejects_scope_runtime_and_budget_widening(mutation, error: str) -> None:
    payload = _plan().to_dict()
    mutation(payload)
    with pytest.raises(ValueError, match=error):
        OffloadExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    "target_path",
    (
        "src\\module.py",
        "../module.py",
        "/src/module.py",
        "C:/src/module.py",
        "src//module.py",
        "src/./module.py",
        "src/NUL.txt",
        "src/module.py.",
        "src/module.py ",
        "src/mod:ule.py",
        "src/LONGFI~1.PY",
        "src/e\u0301.py",
    ),
)
def test_target_path_is_strictly_portable(target_path: str) -> None:
    with pytest.raises(ValueError, match="target_path"):
        _plan(target_path=target_path)


def test_v4_json_schema_is_closed_complete_and_matches_constants() -> None:
    plan = _plan()
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "configs/schemas/offload-execution-plan-v4.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_type"] == {
        "const": "daedalus.offload-execution-plan"
    }
    assert schema["properties"]["contract_version"] == {"const": "4.0.0"}
    assert schema["properties"]["provider_id"] == {"const": "ollama"}
    assert schema["properties"]["runtime_id"] == {"const": "ollama_http"}
    assert schema["properties"]["temperature_milli"] == {"const": 0}
    assert schema["properties"]["max_metadata_calls"] == {"const": 1}
    assert schema["properties"]["max_model_calls"] == {"const": 1}
    assert schema["properties"]["max_cost_microusd"] == {"const": 0}
    assert schema["properties"]["requested_effects"] == {
        "const": list(OFFLOAD_EXECUTION_EFFECTS)
    }
    assert schema["$defs"]["effectScope"]["properties"]["writable_paths"][
        "minItems"
    ] == 3
    assert schema["$defs"]["effectScope"]["properties"]["writable_paths"][
        "maxItems"
    ] == 3
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(plan.to_dict(), schema)
    assert tuple(
        sorted(effect.value for effect in REGISTRY_BY_ID["python.offload"].effects)
    ) == OFFLOAD_EXECUTION_EFFECTS
    assert set(plan.to_dict()) == set(schema["required"]) == set(schema["properties"])
    assert not {
        "plan_id",
        "tool_argv",
        "write_mode",
        "metrics_enabled",
        "drafts_enabled",
        "auto_mint_enabled",
        "model_sha256",
        "model_observation_sha256",
        "availability_sha256",
        "routing_index_sha256",
        "routing_decision_sha256",
    } & set(schema["properties"])
    endpoint_pattern = schema["$defs"]["loopbackEndpoint"]["pattern"]
    assert re.fullmatch(endpoint_pattern, "http://127.0.0.1:11434")
    assert re.fullmatch(endpoint_pattern, "http://[::1]:65535")
    assert not re.fullmatch(endpoint_pattern, "http://127.999.999.999:11434")
    assert not re.fullmatch(endpoint_pattern, "http://127.0.0.1:99999")
    portable_patterns = schema["$defs"]["portableTargetPath"]["allOf"]
    for invalid in ("src/NUL.txt", "src/LONGFI~1.PY"):
        assert any(
            re.search(rule["not"]["pattern"], invalid)
            for rule in portable_patterns
            if "not" in rule
        )


def test_runtime_tool_binding_captures_roundtrips_and_detects_byte_drift(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "test-runner.exe"
    executable.write_bytes(b"exact-runtime-tool-v1\n")
    binding = RuntimeToolBinding.capture(
        tool_id=TOOL_ID,
        runtime_manifest_sha256=_sha("runtime-manifest"),
        source_revision=REVISION,
        executable_path=executable.resolve(),
        origin="tests.runtime-tool-binding",
        created_at=NOW,
        trace_id="mission-1",
    )

    assert binding.executable_sha256 == hashlib.sha256(
        b"exact-runtime-tool-v1\n"
    ).hexdigest()
    assert binding.executable_size == len(b"exact-runtime-tool-v1\n")
    with binding.verify_executable(executable.resolve()) as verified:
        assert verified.executable_sha256 == binding.executable_sha256
        assert verified.executable_size == binding.executable_size
        assert verified.executable_path_sha256 == binding.executable_path_sha256
        assert verified.fileno() >= 0
    assert verified.closed
    assert RuntimeToolBinding.from_dict(json.loads(binding.to_json())) == binding

    copy = tmp_path / "copied-test-runner.exe"
    copy.write_bytes(executable.read_bytes())
    with pytest.raises(RuntimeToolBindingError, match="executable_path_sha256"):
        binding.verify_executable(copy.resolve())

    link = tmp_path / "linked-test-runner.exe"
    try:
        link.symlink_to(executable)
    except OSError:
        pass  # Windows may deny unprivileged symlink creation.
    else:
        with pytest.raises(RuntimeToolBindingError, match="link or reparse point"):
            binding.verify_executable(link.absolute())

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "configs/schemas/runtime-tool-binding-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(binding.to_dict()) == set(schema["required"]) == set(schema["properties"])

    executable.write_bytes(b"different-runtime-tool-v2\n")
    with pytest.raises(RuntimeToolBindingError, match="executable_(?:sha256|size)"):
        binding.verify_executable(executable.resolve())


def test_runtime_tool_binding_rejects_relative_empty_and_unbound_inputs(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeToolBindingError, match="absolute"):
        RuntimeToolBinding.capture(
            tool_id=TOOL_ID,
            runtime_manifest_sha256=_sha("runtime-manifest"),
            source_revision=REVISION,
            executable_path="relative-runner.exe",
            origin="tests.runtime-tool-binding",
            created_at=NOW,
        )

    empty = tmp_path / "empty.exe"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeToolBindingError, match="must not be empty"):
        RuntimeToolBinding.capture(
            tool_id=TOOL_ID,
            runtime_manifest_sha256=_sha("runtime-manifest"),
            source_revision=REVISION,
            executable_path=empty.resolve(),
            origin="tests.runtime-tool-binding",
            created_at=NOW,
        )

    binding = RuntimeToolBinding(
        tool_id=TOOL_ID,
        runtime_manifest_sha256=_sha("runtime-manifest"),
        source_revision=REVISION,
        executable_sha256=_sha("tool"),
        executable_size=4,
        executable_path_sha256=_sha("path"),
        provenance=ContractProvenance(
            origin="tests.runtime-tool-binding",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(
                _sha("runtime-manifest"),
                _sha("tool"),
                _sha("path"),
            ),
        ),
    )
    payload = binding.to_dict()
    payload["executable_sha256"] = _sha("other-tool")
    with pytest.raises(ValueError, match="provenance"):
        RuntimeToolBinding.from_dict(payload)


def test_runtime_tool_verification_retains_identity_across_path_swap(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "race-tool.exe"
    replacement = tmp_path / "replacement.exe"
    original = b"@echo SAFE\r\n"
    changed = b"@echo EVIL\r\n"
    executable.write_bytes(original)
    replacement.write_bytes(changed)
    binding = RuntimeToolBinding.capture(
        tool_id=TOOL_ID,
        runtime_manifest_sha256=_sha("runtime-manifest"),
        source_revision=REVISION,
        executable_path=executable.resolve(),
        origin="tests.runtime-tool-binding",
        created_at=NOW,
    )

    with binding.verify_executable(executable.resolve()) as verified:
        if os.name == "nt":
            with pytest.raises(PermissionError):
                replacement.replace(executable)
            with pytest.raises(PermissionError):
                executable.write_bytes(changed)
        else:
            replacement.replace(executable)
        os.lseek(verified.fileno(), 0, os.SEEK_SET)
        assert os.read(verified.fileno(), len(original)) == original

    if os.name == "nt":
        replacement.replace(executable)
    assert executable.read_bytes() == changed


@pytest.mark.parametrize(
    "field",
    (
        "spine_intent_id",
        "target_before_size",
        "num_ctx",
        "num_predict",
        "seed",
        "temperature_milli",
        "max_response_bytes",
        "max_metadata_calls",
        "max_model_calls",
        "verifier_timeout_s",
        "kill_switch_generation",
        "total_timeout_s",
        "max_cost_microusd",
    ),
)
def test_v2_plan_rejects_boolean_integer_aliases(field: str) -> None:
    payload = _plan().to_dict()
    payload[field] = True
    with pytest.raises(ValueError, match=field):
        OffloadExecutionPlan.from_dict(payload)
