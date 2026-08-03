from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timezone

import pytest

from daedalus.kernel.contracts import (
    OFFLOAD_EXECUTION_EFFECTS,
    OffloadExecutionPlan,
    derive_offload_staging_path,
    offload_staging_path_sha256,
)
from daedalus.kernel.offload_observations import TargetBeforeObservation
from daedalus.kernel.offload_protocol import (
    OffloadProtocolError,
    freeze_offload_protocol,
    parse_offload_chat_response,
    verify_offload_protocol,
)
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EffectScope,
    ResourceBudget,
)


REVISION = "a" * 40
NOW = datetime(2026, 8, 3, tzinfo=timezone.utc).isoformat()
TARGET = "src/module.py"
BEFORE = b"def value():\n    return 7\n"


def _sha(label: str | bytes) -> str:
    raw = label if isinstance(label, bytes) else label.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _attempt() -> AttemptContract:
    task_sha = _sha("task")
    runtime_sha = _sha("runtime")
    policy_sha = _sha("policy")
    return AttemptContract(
        attempt_id="attempt-1",
        mission_id="mission-1",
        task_id="task-1",
        instruction="Replace the magic number with a named constant.",
        base_revision=REVISION,
        task_sha256=task_sha,
        runtime_manifest_sha256=runtime_sha,
        policy_decision_sha256=policy_sha,
        budget=ResourceBudget(
            max_tokens=4096,
            max_cost_microusd=0,
            max_wall_time_s=120,
            max_attempts=1,
        ),
        provenance=ContractProvenance(
            origin="tests.offload-protocol",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(task_sha, runtime_sha, policy_sha),
        ),
        writable_paths=(TARGET,),
        gate_names=("command",),
    )


def _target() -> TargetBeforeObservation:
    inputs = (
        _sha("attestation"),
        _sha(BEFORE),
        _sha("file-identity"),
        _sha("parent-chain"),
    )
    return TargetBeforeObservation(
        workspace_attestation_sha256=inputs[0],
        source_revision=REVISION,
        target_path=TARGET,
        target_kind="existing-regular-utf8-file",
        content_sha256=inputs[1],
        byte_length=len(BEFORE),
        git_mode="100644",
        encoding="utf-8",
        file_identity_sha256=inputs[2],
        parent_chain_sha256=inputs[3],
        provenance=ContractProvenance(
            origin="tests.offload-protocol",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=inputs,
        ),
    )


def _plan(attempt: AttemptContract, target: TargetBeforeObservation):
    bundle = freeze_offload_protocol(
        attempt=attempt,
        target_before=target,
        target_before_bytes=BEFORE,
        model_id="qwen2.5-coder:7b",
        num_ctx=4096,
        num_predict=512,
        seed=17,
        temperature_milli=0,
        keep_alive="0",
    )
    digests = {
        "spine_intent_sha256": _sha("intent"),
        "attempt_contract_sha256": attempt.digest,
        "task_sha256": attempt.task_sha256,
        "base_source_artifact_sha256": _sha("base-source"),
        "workspace_attestation_sha256": target.workspace_attestation_sha256,
        "workspace_observation_sha256": _sha("workspace-observation"),
        "target_before_sha256": target.content_sha256,
        "expected_model_sha256": _sha("model"),
        "prompt_template_sha256": bundle.prompt_template_sha256,
        "prompt_sha256": bundle.prompt_sha256,
        "response_schema_sha256": bundle.response_schema_sha256,
        "ollama_request_sha256": bundle.ollama_request_sha256,
        "attempt_policy_decision_sha256": attempt.policy_decision_sha256,
        "runtime_manifest_sha256": attempt.runtime_manifest_sha256,
        "runtime_conformance_sha256": _sha("conformance"),
        "runtime_tool_binding_sha256": _sha("tool-binding"),
    }
    workspace_id = "workspace-1"
    staging_path = derive_offload_staging_path(
        attempt_id=attempt.attempt_id,
        workspace_id=workspace_id,
        target_path=TARGET,
    )
    staging_sha = offload_staging_path_sha256(staging_path)
    scope = EffectScope(
        read_only=False,
        writable_paths=tuple(sorted((TARGET, staging_path))),
        egress_endpoints=("http://127.0.0.1:11434",),
        tools=("python.test-runner",),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref="mission-1-kill",
    )
    plan = OffloadExecutionPlan(
        spine_intent_id=1,
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        task_id=attempt.task_id,
        **digests,
        source_revision=REVISION,
        workspace_id=workspace_id,
        target_path=TARGET,
        target_kind=target.target_kind,
        target_before_size=target.byte_length,
        target_git_mode=target.git_mode,
        provider_id="ollama",
        runtime_id="ollama_http",
        provider_endpoint="http://127.0.0.1:11434",
        model_id="qwen2.5-coder:7b",
        num_ctx=4096,
        num_predict=512,
        seed=17,
        temperature_milli=0,
        keep_alive="0",
        max_response_bytes=100_000,
        max_metadata_calls=1,
        max_model_calls=1,
        verifier_argv=("python.test-runner", "-q"),
        verifier_timeout_s=30,
        requested_effects=OFFLOAD_EXECUTION_EFFECTS,
        effect_scope=scope,
        kill_switch_generation=1,
        total_timeout_s=120,
        max_cost_microusd=0,
        staging_path=staging_path,
        staging_path_sha256=staging_sha,
        provenance=ContractProvenance(
            origin="tests.offload-protocol",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(*digests.values(), staging_sha),
        ),
    )
    return plan, bundle


def test_protocol_freezes_the_complete_request_and_rejects_any_byte_drift() -> None:
    attempt = _attempt()
    target = _target()
    plan, bundle = _plan(attempt, target)

    verify_offload_protocol(
        plan=plan,
        attempt=attempt,
        target_before=target,
        target_before_bytes=BEFORE,
        bundle=bundle,
    )
    request = json.loads(bundle.ollama_request_bytes)
    assert request["model"] == plan.model_id
    assert request["messages"] == json.loads(bundle.prompt_bytes)
    assert request["format"] == json.loads(bundle.response_schema_bytes)
    assert request["options"] == {
        "num_ctx": 4096,
        "num_predict": 512,
        "seed": 17,
        "temperature": 0.0,
    }
    assert request["stream"] is False
    assert request["keep_alive"] == "0"

    fields = (
        "prompt_template_bytes",
        "prompt_bytes",
        "response_schema_bytes",
        "ollama_request_bytes",
    )
    for field in fields:
        tampered = dataclasses.replace(bundle, **{field: getattr(bundle, field) + b" "})
        with pytest.raises(OffloadProtocolError, match="binding mismatch"):
            verify_offload_protocol(
                plan=plan,
                attempt=attempt,
                target_before=target,
                target_before_bytes=BEFORE,
                bundle=tampered,
            )
    with pytest.raises(OffloadProtocolError, match="digest mismatches"):
        freeze_offload_protocol(
            attempt=attempt,
            target_before=target,
            target_before_bytes=BEFORE + b"# drift\n",
            model_id=plan.model_id,
            num_ctx=plan.num_ctx,
            num_predict=plan.num_predict,
            seed=plan.seed,
            temperature_milli=0,
            keep_alive="0",
        )


def test_native_chat_response_yields_exact_candidate_and_refuses_shape_drift() -> None:
    attempt = _attempt()
    target = _target()
    plan, _ = _plan(attempt, target)
    candidate_text = "VALUE = 7\n\ndef value():\n    return VALUE\n"
    assistant = json.dumps(
        {"target_path": TARGET, "content": candidate_text},
        separators=(",", ":"),
    )
    response = json.dumps(
        {
            "model": plan.model_id,
            "created_at": "2026-08-03T00:00:00Z",
            "message": {"role": "assistant", "content": assistant},
            "done": True,
            "done_reason": "stop",
            "eval_count": 42,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    parsed = parse_offload_chat_response(
        raw_response_bytes=response,
        plan=plan,
        target_before=target,
    )
    assert parsed.target_path == TARGET
    assert parsed.content_bytes == candidate_text.encode("utf-8")
    assert parsed.raw_response_sha256 == _sha(response)

    invalid_responses = (
        response.replace(plan.model_id.encode(), b"other-model", 1),
        response.replace(b'"done":true', b'"done":false', 1),
        response.replace(b'"done_reason":"stop"', b'"done_reason":"length"', 1),
        response.replace(
            b'"role":"assistant","content":',
            b'"role":"assistant","tool_calls":[],"content":',
            1,
        ),
        response.replace(TARGET.encode(), b"src/other.py", 1),
        b'{"model":"qwen2.5-coder:7b","model":"qwen2.5-coder:7b"}',
    )
    for invalid in invalid_responses:
        with pytest.raises(OffloadProtocolError):
            parse_offload_chat_response(
                raw_response_bytes=invalid,
                plan=plan,
                target_before=target,
            )


def test_prompt_budget_and_plan_context_reserve_fail_closed() -> None:
    attempt = _attempt()
    target = _target()
    with pytest.raises(OffloadProtocolError, match="input-token budget"):
        freeze_offload_protocol(
            attempt=attempt,
            target_before=target,
            target_before_bytes=BEFORE,
            model_id="qwen2.5-coder:7b",
            num_ctx=600,
            num_predict=599,
            seed=1,
            temperature_milli=0,
            keep_alive="0",
        )

    plan, _ = _plan(attempt, target)
    with pytest.raises(ValueError, match="smaller than num_ctx"):
        dataclasses.replace(plan, num_predict=plan.num_ctx)
