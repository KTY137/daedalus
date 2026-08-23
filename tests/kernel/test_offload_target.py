"""Full-chain publication tests over Git, SQLite, CAS, parsing, and real I/O."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from daedalus.kairos.worktree import GitWorktreeManager
from daedalus.kernel.contracts import (
    OFFLOAD_EXECUTION_EFFECTS,
    EffectLeaseRequest,
    OffloadExecutionPlan,
    derive_offload_recovery_path,
    derive_offload_staging_path,
    offload_recovery_path_sha256,
    offload_staging_path_sha256,
)
from daedalus.kernel.effects import (
    CompletionCapability,
    EffectExecutionClaim,
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectLeaseStateError,
    EffectStartResult,
    LeasedEffectAuthorization,
    issue_effect_lease,
)
from daedalus.kernel.offload_authority import (
    AuthorizedOffloadExecution,
    authorize_offload_execution,
    derive_offload_execution_ids,
)
from daedalus.kernel.offload_observations import (
    BASE_SOURCE_ARTIFACT_KIND,
    OFFLOAD_CANDIDATE_TARGET_ARTIFACT_KIND,
    OLLAMA_CHAT_RESPONSE_ARTIFACT_KIND,
    OLLAMA_METADATA_ARTIFACT_KIND,
    SOURCE_FINGERPRINT_ARTIFACT_KIND,
    OffloadWorkspaceObservation,
    OllamaChatObservation,
    OllamaModelObservation,
    TargetBeforeObservation,
    TaskAttemptWorkspaceAttestation,
)
from daedalus.kernel.offload_protocol import (
    freeze_offload_protocol,
    parse_offload_chat_response,
)
from daedalus.kernel.offload_target import (
    OffloadTargetEffectCommitment,
    OffloadTargetMetadataProfile,
    OffloadTargetPublicationResult,
    OffloadTargetWriteError,
    OffloadTargetWriteIndeterminate,
    TargetAfterObservation,
    _publish_authorized_candidate,
    _swap_candidate_into_target,
)
from daedalus.kernel.resolved_kill_switch import (
    ResolvedKillSwitch,
    kill_switch_ref_for_path,
)
from daedalus.kernel.runtime_tools import RuntimeToolBinding
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    ResourceBudget,
)
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision
from daedalus.spine.envelope import canonical_json
from daedalus.spine.killswitch import KillSwitch
from daedalus.spine.source_state import fingerprint_source
from daedalus.storage import ArtifactLocator, ArtifactStore


TARGET = "src/module.py"
BEFORE = b"def value():\n    return 7\n"
CANDIDATE = b"def value():\n    return 8\n"
MODEL_ID = "qwen2.5-coder:7b"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
NOW_TEXT = NOW.isoformat(timespec="microseconds")
SECRET = b"offload-target-chain-secret-material-32-bytes"


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ("git", *args),
        cwd=repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=True,
    )
    return result.stdout


@dataclass(frozen=True)
class _PublicationChain:
    repo: Path
    workspace: Path
    manager: GitWorktreeManager
    store: ArtifactStore
    authorized: AuthorizedOffloadExecution
    start: EffectStartResult
    claim: EffectExecutionClaim
    resolved_kill_switch: ResolvedKillSwitch
    model: OllamaModelObservation
    chat: OllamaChatObservation

    @property
    def target(self) -> Path:
        return self.workspace.joinpath(*TARGET.split("/"))

    @property
    def stage(self) -> Path:
        return self.workspace.joinpath(*self.authorized.plan.staging_path.split("/"))

    @property
    def recovery(self) -> Path:
        return self.workspace.joinpath(*self.authorized.plan.recovery_path.split("/"))


def _put_workspace_observation(
    *,
    repo: Path,
    workspace: Path,
    manager: GitWorktreeManager,
    attestation: TaskAttemptWorkspaceAttestation,
    target: TargetBeforeObservation,
    store: ArtifactStore,
    revision: str,
) -> OffloadWorkspaceObservation:
    fingerprint = fingerprint_source(workspace).require_exact()
    fingerprint_raw = canonical_json(fingerprint.to_dict()).encode("ascii")
    fingerprint_locator = store.put_bytes(
        fingerprint_raw,
        expected_sha256=_sha(fingerprint_raw),
        media_type="application/vnd.daedalus.source-fingerprint+json",
        metadata={
            "kind": SOURCE_FINGERPRINT_ARTIFACT_KIND,
            "source_fingerprint_sha256": fingerprint.fingerprint_sha256,
            "source_revision": revision,
            "workspace_attestation_sha256": attestation.digest,
        },
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(attestation.digest, fingerprint.fingerprint_sha256),
            trace_id="trace-target",
        ).to_dict(),
    )
    base_locator = store.put_bytes(
        _git_bytes(repo, "archive", "--format=tar", revision),
        media_type="application/x-tar",
        metadata={
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": revision,
        },
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(_sha("source-fetch-receipt"),),
            trace_id="trace-target",
        ).to_dict(),
    )
    return OffloadWorkspaceObservation.capture(
        manager=manager,
        workspace_path=workspace,
        workspace_attestation=attestation,
        target_before=target,
        base_source_artifact_locator=base_locator,
        source_fingerprint=fingerprint,
        source_fingerprint_locator=fingerprint_locator,
        artifact_store=store,
        origin="tests.offload-target",
        created_at=NOW_TEXT,
        trace_id="trace-target",
    )


def _build_chain(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate: bytes = CANDIDATE,
) -> _PublicationChain:
    root.mkdir()
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(root / "worktrees"))
    monkeypatch.setenv("DAEDALUS_MIN_FREE_GIB", "0")
    switch = KillSwitch(
        root / "control" / "permit",
        sweep_managed=False,
    )
    switch_state = switch.arm(force=True)
    assert switch_state.running is True
    assert switch_state.generation is not None
    kill_switch_ref = kill_switch_ref_for_path(switch.path)
    resolved_kill_switch = ResolvedKillSwitch.resolve(
        switch,
        expected_kill_switch_ref=kill_switch_ref,
        expected_generation=switch_state.generation,
    )
    repo = root / "primary"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Target Chain Test")
    _git(repo, "config", "user.email", "target-chain@example.test")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "src").mkdir()
    (repo / TARGET).write_bytes(BEFORE)
    _git(repo, "add", "--", TARGET)
    _git(repo, "commit", "-m", "base")
    revision = _git(repo, "rev-parse", "HEAD")

    task_sha = _sha("target-task")
    runtime_sha = _sha("target-runtime")
    attempt_policy_sha = _sha("attempt-policy")
    attempt = AttemptContract(
        attempt_id="attempt-target",
        mission_id="mission-target",
        task_id="task-target",
        instruction="Change value() from seven to eight and preserve the API.",
        base_revision=revision,
        task_sha256=task_sha,
        runtime_manifest_sha256=runtime_sha,
        policy_decision_sha256=attempt_policy_sha,
        budget=ResourceBudget(
            max_tokens=4096,
            max_cost_microusd=0,
            max_wall_time_s=120,
            max_attempts=1,
        ),
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(task_sha, runtime_sha, attempt_policy_sha),
            trace_id="trace-target",
        ),
        writable_paths=(TARGET,),
        gate_names=("command",),
    )
    manager = GitWorktreeManager(repo)
    workspace = manager.create_worktree(revision, "target-chain")
    attestation = TaskAttemptWorkspaceAttestation.capture(
        manager=manager,
        workspace_path=workspace,
        workspace_id="workspace-target",
        spine_intent_id=101,
        spine_intent_sha256=_sha("spine-intent"),
        task_id=attempt.task_id,
        task_sha256=attempt.task_sha256,
        source_revision=revision,
        origin="tests.offload-target",
        created_at=NOW_TEXT,
        trace_id="trace-target",
    )
    target = TargetBeforeObservation.capture(
        manager=manager,
        workspace_path=workspace,
        workspace_attestation=attestation,
        target_path=TARGET,
        origin="tests.offload-target",
        created_at=NOW_TEXT,
        trace_id="trace-target",
    )
    store = ArtifactStore(root / "cas", min_free_gib=0)
    workspace_observation = _put_workspace_observation(
        repo=repo,
        workspace=workspace,
        manager=manager,
        attestation=attestation,
        target=target,
        store=store,
        revision=revision,
    )

    tool_executable_sha = _sha("exact-test-runner")
    tool_path_sha = _sha("exact-test-runner-path")
    tool = RuntimeToolBinding(
        tool_id="python.test-runner",
        runtime_manifest_sha256=runtime_sha,
        source_revision=revision,
        executable_sha256=tool_executable_sha,
        executable_size=12345,
        executable_path_sha256=tool_path_sha,
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(runtime_sha, tool_executable_sha, tool_path_sha),
            trace_id="trace-target",
        ),
    )
    protocol = freeze_offload_protocol(
        attempt=attempt,
        target_before=target,
        target_before_bytes=BEFORE,
        model_id=MODEL_ID,
        num_ctx=4096,
        num_predict=512,
        seed=17,
        temperature_milli=0,
        keep_alive="0",
    )
    staging_path = derive_offload_staging_path(
        attempt_id=attempt.attempt_id,
        workspace_id=attestation.workspace_id,
        target_path=TARGET,
    )
    staging_sha = offload_staging_path_sha256(staging_path)
    recovery_path = derive_offload_recovery_path(
        attempt_id=attempt.attempt_id,
        workspace_id=attestation.workspace_id,
        target_path=TARGET,
    )
    recovery_sha = offload_recovery_path_sha256(recovery_path)
    plan_digests = {
        "spine_intent_sha256": attestation.spine_intent_sha256,
        "attempt_contract_sha256": attempt.digest,
        "task_sha256": attempt.task_sha256,
        "base_source_artifact_sha256": workspace_observation.base_source_artifact_sha256,
        "workspace_attestation_sha256": attestation.digest,
        "workspace_observation_sha256": workspace_observation.digest,
        "target_before_sha256": target.content_sha256,
        "expected_model_sha256": _sha("qwen-model-bytes"),
        "prompt_template_sha256": protocol.prompt_template_sha256,
        "prompt_sha256": protocol.prompt_sha256,
        "response_schema_sha256": protocol.response_schema_sha256,
        "ollama_request_sha256": protocol.ollama_request_sha256,
        "attempt_policy_decision_sha256": attempt.policy_decision_sha256,
        "runtime_manifest_sha256": attempt.runtime_manifest_sha256,
        "runtime_conformance_sha256": _sha("runtime-conformance"),
        "runtime_tool_binding_sha256": tool.digest,
    }
    scope = EffectScope(
        read_only=False,
        writable_paths=tuple(sorted((TARGET, staging_path, recovery_path))),
        egress_endpoints=("http://127.0.0.1:11434",),
        tools=(tool.tool_id,),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref=kill_switch_ref,
    )
    plan = OffloadExecutionPlan(
        spine_intent_id=attestation.spine_intent_id,
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        task_id=attempt.task_id,
        **plan_digests,
        source_revision=revision,
        workspace_id=attestation.workspace_id,
        target_path=TARGET,
        target_kind=target.target_kind,
        target_before_size=target.byte_length,
        target_git_mode=target.git_mode,
        provider_id="ollama",
        runtime_id="ollama_http",
        provider_endpoint="http://127.0.0.1:11434",
        model_id=MODEL_ID,
        num_ctx=4096,
        num_predict=512,
        seed=17,
        temperature_milli=0,
        keep_alive="0",
        max_response_bytes=2_000_000,
        max_metadata_calls=1,
        max_model_calls=1,
        verifier_argv=(tool.tool_id, "-q", "tests/test_module.py"),
        verifier_timeout_s=30,
        requested_effects=OFFLOAD_EXECUTION_EFFECTS,
        effect_scope=scope,
        kill_switch_generation=switch_state.generation,
        total_timeout_s=120,
        max_cost_microusd=0,
        staging_path=staging_path,
        staging_path_sha256=staging_sha,
        recovery_path=recovery_path,
        recovery_path_sha256=recovery_sha,
        artifact_store_root_sha256=store.root_sha256,
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(
                *plan_digests.values(),
                staging_sha,
                recovery_sha,
                store.root_sha256,
            ),
            trace_id="trace-target",
        ),
    )

    request = EffectLeaseRequest(
        request_id="request-target",
        mission_id=attempt.mission_id,
        attempt_id=attempt.attempt_id,
        entrypoint_id="python.offload",
        requested_effects=plan.requested_effects,
        effect_scope=plan.effect_scope,
        idempotency_namespace=f"{attempt.mission_id}/{attempt.attempt_id}",
        kill_switch_generation=plan.kill_switch_generation,
        runtime_manifest_sha256=plan.runtime_manifest_sha256,
        runtime_conformance_sha256=plan.runtime_conformance_sha256,
        execution_plan_sha256=plan.digest,
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(
                plan.digest,
                plan.runtime_manifest_sha256,
                plan.runtime_conformance_sha256,
            ),
            trace_id="trace-target",
        ),
    )
    effect_policy_sha = _sha("effect-policy")
    policy = PolicyDecision(
        decision_id="policy-target",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=effect_policy_sha,
        verdict="allow",
        reasons=("exact bounded target-chain test",),
        effect_scope=plan.effect_scope,
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(request.digest, effect_policy_sha),
            trace_id="trace-target",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="lease-target",
        issuer_key_id="kernel-target-key",
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
    )
    ledger = EffectLeaseLedger(root / "effects.sqlite3")
    ledger.grant(
        lease,
        request=request,
        policy_decision=policy,
        keyring={"kernel-target-key": SECRET},
        current_kill_switch_generation=plan.kill_switch_generation,
        granted_at=NOW,
    )
    specification = REGISTRY_BY_ID["python.offload"]
    authorization = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        keyring={"kernel-target-key": SECRET},
        guard_decisions=tuple(
            GuardDecision(
                contract,
                True,
                f"artifact-locator:sha256:{_sha(contract)}",
            )
            for contract in specification.guard_contracts
        ),
        current_kill_switch_generation=plan.kill_switch_generation,
    )
    execution_id, idempotency_key = derive_offload_execution_ids(plan)
    execution = EffectExecutionRequest(
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        requested_effects=plan.requested_effects,
        writable_paths=plan.effect_scope.writable_paths,
        egress_endpoints=plan.effect_scope.egress_endpoints,
        tools=plan.effect_scope.tools,
        secret_refs=plan.effect_scope.secret_refs,
        max_cost_microusd=plan.max_cost_microusd,
        kill_switch_ref=plan.effect_scope.kill_switch_ref,
        kill_switch_generation=plan.kill_switch_generation,
        execution_plan_sha256=plan.digest,
    )
    authorized = authorize_offload_execution(
        plan=plan,
        attempt=attempt,
        workspace_attestation=attestation,
        target_before=target,
        workspace_observation=workspace_observation,
        runtime_tool_binding=tool,
        authorization=authorization,
        execution=execution,
    )
    start = authorization.begin_effect(execution, started_at=NOW)
    claim = authorization.claim_execution(
        start,
        execution,
        claimed_at=NOW + timedelta(microseconds=1),
    )
    authorization.require_live_claim(claim, execution)

    metadata_request_sha = _sha("GET /api/tags")
    metadata_raw = canonical_json(
        {
            "models": [
                {
                    "name": MODEL_ID,
                    "model": MODEL_ID,
                    "modified_at": "2026-08-01T12:34:56.123456Z",
                    "size": 4_683_087_561,
                    "digest": f"sha256:{plan.expected_model_sha256}",
                    "details": {
                        "family": "qwen2",
                        "parameter_size": "7.6B",
                        "quantization_level": "Q4_K_M",
                    },
                }
            ]
        }
    ).encode("ascii")
    metadata_locator = store.put_bytes(
        metadata_raw,
        expected_sha256=_sha(metadata_raw),
        media_type="application/json",
        metadata={
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": execution.digest,
            "claim_receipt_sha256": claim.claim_receipt.receipt_sha256,
            "kind": OLLAMA_METADATA_ARTIFACT_KIND,
            "metadata_request_sha256": metadata_request_sha,
            "start_receipt_sha256": start.receipt.receipt_sha256,
        },
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=(
                plan.digest,
                execution.digest,
                start.receipt.receipt_sha256,
                claim.claim_receipt.receipt_sha256,
                metadata_request_sha,
            ),
            trace_id="trace-target",
        ).to_dict(),
    )
    model = OllamaModelObservation.capture_from_response_bytes(
        execution_request=execution,
        execution_claim=claim,
        authorization=authorization,
        execution_plan=plan,
        metadata_request_sha256=metadata_request_sha,
        raw_response_bytes=metadata_raw,
        raw_response_locator=metadata_locator,
        artifact_store=store,
        origin="tests.offload-target",
        created_at=NOW_TEXT,
        trace_id="trace-target",
    )

    assistant_content = canonical_json(
        {"content": candidate.decode("utf-8"), "target_path": TARGET}
    )
    chat_raw = canonical_json(
        {
            "done": True,
            "done_reason": "stop",
            "message": {"content": assistant_content, "role": "assistant"},
            "model": MODEL_ID,
        }
    ).encode("ascii")
    parsed = parse_offload_chat_response(
        raw_response_bytes=chat_raw,
        plan=plan,
        target_before=target,
    )
    raw_inputs = (
        execution.digest,
        start.receipt.receipt_sha256,
        claim.claim_receipt.receipt_sha256,
        plan.digest,
        model.digest,
        plan.ollama_request_sha256,
    )
    chat_raw_locator = store.put_bytes(
        chat_raw,
        expected_sha256=parsed.raw_response_sha256,
        media_type="application/json",
        metadata={
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": execution.digest,
            "claim_receipt_sha256": claim.claim_receipt.receipt_sha256,
            "kind": OLLAMA_CHAT_RESPONSE_ARTIFACT_KIND,
            "model_observation_sha256": model.digest,
            "ollama_request_sha256": plan.ollama_request_sha256,
            "raw_response_sha256": parsed.raw_response_sha256,
            "start_receipt_sha256": start.receipt.receipt_sha256,
        },
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=raw_inputs,
            trace_id="trace-target",
        ).to_dict(),
    )
    candidate_inputs = tuple(
        sorted(
            {
                *raw_inputs,
                parsed.raw_response_sha256,
                chat_raw_locator.locator_sha256,
                target.digest,
                target.content_sha256,
                parsed.assistant_content_sha256,
            }
        )
    )
    candidate_locator = store.put_bytes(
        parsed.content_bytes,
        expected_sha256=parsed.content_sha256,
        media_type="text/plain; charset=utf-8",
        metadata={
            "assistant_content_sha256": parsed.assistant_content_sha256,
            "candidate_sha256": parsed.content_sha256,
            "candidate_size": len(parsed.content_bytes),
            "changes_target": parsed.content_sha256 != target.content_sha256,
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": execution.digest,
            "claim_receipt_sha256": claim.claim_receipt.receipt_sha256,
            "kind": OFFLOAD_CANDIDATE_TARGET_ARTIFACT_KIND,
            "model_observation_sha256": model.digest,
            "ollama_request_sha256": plan.ollama_request_sha256,
            "raw_response_artifact_locator": chat_raw_locator.locator_uri,
            "raw_response_sha256": parsed.raw_response_sha256,
            "start_receipt_sha256": start.receipt.receipt_sha256,
            "target_before_observation_sha256": target.digest,
            "target_before_sha256": target.content_sha256,
            "target_path": TARGET,
        },
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=revision,
            created_at=NOW_TEXT,
            input_digests=candidate_inputs,
            trace_id="trace-target",
        ).to_dict(),
    )
    chat = OllamaChatObservation.capture_from_response_bytes(
        execution_request=execution,
        execution_claim=claim,
        authorization=authorization,
        execution_plan=plan,
        model_observation=model,
        target_before=target,
        parsed_candidate=parsed,
        raw_response_bytes=chat_raw,
        raw_response_locator=chat_raw_locator,
        candidate_locator=candidate_locator,
        artifact_store=store,
        origin="tests.offload-target",
        created_at=NOW_TEXT,
        trace_id="trace-target",
    )
    return _PublicationChain(
        repo=repo,
        workspace=workspace,
        manager=manager,
        store=store,
        authorized=authorized,
        start=start,
        claim=claim,
        resolved_kill_switch=resolved_kill_switch,
        model=model,
        chat=chat,
    )


def _publish(
    chain: _PublicationChain,
    *,
    origin: str = "tests.offload-target",
) -> OffloadTargetPublicationResult:
    return _publish_authorized_candidate(
        authorized=chain.authorized,
        start_result=chain.start,
        execution_claim=chain.claim,
        model_observation=chain.model,
        chat_observation=chain.chat,
        artifact_store=chain.store,
        manager=chain.manager,
        workspace_path=chain.workspace,
        resolved_kill_switch=chain.resolved_kill_switch,
        deadline_monotonic=time.monotonic() + 30,
        origin=origin,
    )


def _schema(name: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "configs" / "schemas" / name).read_text("utf-8"))


def test_real_authority_cas_parse_and_atomic_publication_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_chain(tmp_path / "happy", monkeypatch)
    for schema_name in (
        "target-after-observation-v1.schema.json",
        "offload-target-effect-commitment-v1.schema.json",
        "offload-target-metadata-profile-v1.schema.json",
    ):
        jsonschema.Draft202012Validator.check_schema(_schema(schema_name))
    if os.name == "nt":
        with pytest.raises(OffloadTargetWriteError, match="Linux renameat2"):
            _publish(chain)
        assert chain.target.read_bytes() == BEFORE
        assert not chain.stage.exists()
        assert not chain.recovery.exists()
        assert (
            chain.authorized.authorization.ledger.execution_state(
                chain.authorized.execution.execution_id
            )
            == "EXECUTING"
        )
        return

    result = _publish(chain)
    after = result.after_observation

    assert chain.target.read_bytes() == CANDIDATE
    assert not chain.stage.exists()
    assert not chain.recovery.exists()
    assert _git(chain.workspace, "diff", "--name-only") == TARGET
    assert _git(chain.workspace, "diff", "--cached", "--name-only") == ""
    assert _git(chain.workspace, "ls-files", "--others", "--exclude-standard") == ""
    assert after.execution_plan_sha256 == chain.authorized.plan.digest
    assert after.execution_request_sha256 == chain.authorized.execution.digest
    assert after.start_receipt_sha256 == chain.start.receipt.receipt_sha256
    assert after.claim_receipt_sha256 == chain.claim.claim_receipt.receipt_sha256
    assert after.effect_commitment_sha256 == result.effect_commitment.digest
    assert after.publication_commit_receipt_sha256 == (
        result.finalization.commit_receipt.receipt_sha256
    )
    assert after.publication_outcome_receipt_sha256 == (
        result.finalization.outcome_receipt.receipt_sha256
    )
    assert after.ollama_chat_observation_sha256 == chain.chat.digest
    assert after.content_sha256 == _sha(CANDIDATE)
    assert after.filesystem_mode == stat.S_IMODE(os.lstat(chain.target).st_mode)
    assert chain.store.get_bytes(after.digest) == after.to_json().encode("ascii")
    assert chain.store.get_bytes(result.effect_commitment.digest) == (
        result.effect_commitment.to_json().encode("ascii")
    )

    schema = _schema("target-after-observation-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(after.to_dict(), schema)
    assert TargetAfterObservation.from_dict(after.to_dict()) == after
    assert set(after.to_dict()) == set(schema["properties"]) == set(schema["required"])
    for record, schema_name, record_type in (
        (
            result.effect_commitment,
            "offload-target-effect-commitment-v1.schema.json",
            OffloadTargetEffectCommitment,
        ),
        (
            result.metadata_profile,
            "offload-target-metadata-profile-v1.schema.json",
            OffloadTargetMetadataProfile,
        ),
    ):
        record_schema = _schema(schema_name)
        jsonschema.Draft202012Validator.check_schema(record_schema)
        jsonschema.validate(record.to_dict(), record_schema)
        assert record_type.from_dict(record.to_dict()) == record
        assert set(record.to_dict()) == set(record_schema["properties"]) == set(
            record_schema["required"]
        )
    after.verify_current(
        authorized=chain.authorized,
        chat_observation=chain.chat,
        effect_commitment=result.effect_commitment,
        effect_commitment_artifact_locator=(
            result.effect_commitment_artifact_locator
        ),
        metadata_profile=result.metadata_profile,
        finalization=result.finalization,
        artifact_store=chain.store,
        manager=chain.manager,
        workspace_path=chain.workspace,
    )
    terminal = chain.authorized.authorization.finish_committed_effect(
        result.finalization,
        outcome="completed",
        output_digests=(after.digest, result.effect_commitment.digest),
    )
    assert terminal.outcome == "COMPLETED"
    assert (
        chain.authorized.authorization.ledger.execution_state(
            chain.authorized.execution.execution_id
        )
        == "COMPLETED"
    )

    replacement = chain.target.with_name("byte-identical-replacement.py")
    replacement.write_bytes(CANDIDATE)
    os.chmod(replacement, after.filesystem_mode)
    os.replace(replacement, chain.target)
    with pytest.raises(Exception, match="file_identity_sha256"):
        after.verify_current(
            authorized=chain.authorized,
            chat_observation=chain.chat,
            effect_commitment=result.effect_commitment,
            effect_commitment_artifact_locator=(
                result.effect_commitment_artifact_locator
            ),
            metadata_profile=result.metadata_profile,
            finalization=result.finalization,
            artifact_store=chain.store,
            manager=chain.manager,
            workspace_path=chain.workspace,
        )


def test_authority_cas_and_mode_tamper_matrix_is_zero_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _build_chain(tmp_path / "authority", monkeypatch)
    with pytest.raises(EffectLeaseStateError, match="only be minted"):
        CompletionCapability(
            start_receipt=chain.start.receipt,
            secret=b"attacker-selected-capability-secret",
        )

    empty_ledger = EffectLeaseLedger(tmp_path / "authority" / "empty.sqlite3")
    empty_ledger.grant(
        chain.authorized.authorization.lease,
        request=chain.authorized.authorization.request,
        policy_decision=chain.authorized.authorization.policy_decision,
        keyring=chain.authorized.authorization.keyring,
        current_kill_switch_generation=chain.authorized.plan.kill_switch_generation,
        granted_at=NOW,
    )
    empty_authorization = replace(chain.authorized.authorization, ledger=empty_ledger)
    empty_bound = authorize_offload_execution(
        plan=chain.authorized.plan,
        attempt=chain.authorized.attempt,
        workspace_attestation=chain.authorized.workspace_attestation,
        target_before=chain.authorized.target_before,
        workspace_observation=chain.authorized.workspace_observation,
        runtime_tool_binding=chain.authorized.runtime_tool_binding,
        authorization=empty_authorization,
        execution=chain.authorized.execution,
    )
    with pytest.raises(OffloadTargetWriteError, match="canonical ledger"):
        _publish_authorized_candidate(
            authorized=empty_bound,
            start_result=chain.start,
            execution_claim=chain.claim,
            model_observation=chain.model,
            chat_observation=chain.chat,
            artifact_store=chain.store,
            manager=chain.manager,
            workspace_path=chain.workspace,
            resolved_kill_switch=chain.resolved_kill_switch,
            deadline_monotonic=time.monotonic() + 30,
            origin="tests.offload-target",
        )
    assert chain.target.read_bytes() == BEFORE
    assert not chain.stage.exists()
    assert not chain.recovery.exists()

    wrong_store = ArtifactStore(tmp_path / "authority" / "other-cas", min_free_gib=0)
    with pytest.raises(OffloadTargetWriteError, match="store root"):
        _publish_authorized_candidate(
            authorized=chain.authorized,
            start_result=chain.start,
            execution_claim=chain.claim,
            model_observation=chain.model,
            chat_observation=chain.chat,
            artifact_store=wrong_store,
            manager=chain.manager,
            workspace_path=chain.workspace,
            resolved_kill_switch=chain.resolved_kill_switch,
            deadline_monotonic=time.monotonic() + 30,
            origin="tests.offload-target",
        )
    assert chain.target.read_bytes() == BEFORE
    assert not chain.stage.exists()
    assert not chain.recovery.exists()

    wrong_locator = chain.store.put_bytes(
        CANDIDATE,
        media_type="text/plain; charset=utf-8",
        metadata={"kind": "daedalus.wrong-candidate/1"},
        provenance=ContractProvenance(
            origin="tests.offload-target",
            source_revision=chain.authorized.plan.source_revision,
            created_at=NOW_TEXT,
            input_digests=(_sha("wrong-candidate-input"),),
        ).to_dict(),
    )
    old_locator_sha = chain.chat.candidate_artifact_locator.rsplit(":", 1)[1]
    forged_chat = replace(
        chain.chat,
        candidate_artifact_locator=wrong_locator.locator_uri,
        provenance=replace(
            chain.chat.provenance,
            input_digests=tuple(
                wrong_locator.locator_sha256 if value == old_locator_sha else value
                for value in chain.chat.provenance.input_digests
            ),
        ),
    )
    with pytest.raises(OffloadTargetWriteError, match="CAS observation chain"):
        _publish_authorized_candidate(
            authorized=chain.authorized,
            start_result=chain.start,
            execution_claim=chain.claim,
            model_observation=chain.model,
            chat_observation=forged_chat,
            artifact_store=chain.store,
            manager=chain.manager,
            workspace_path=chain.workspace,
            resolved_kill_switch=chain.resolved_kill_switch,
            deadline_monotonic=time.monotonic() + 30,
            origin="tests.offload-target",
        )
    assert chain.target.read_bytes() == BEFORE
    assert not chain.stage.exists()
    assert not chain.recovery.exists()

    os.chmod(chain.target, 0o444)
    with pytest.raises(Exception, match="filesystem_mode"):
        _publish(chain)
    assert chain.target.read_bytes() == BEFORE
    assert not chain.stage.exists()
    assert not chain.recovery.exists()


def test_committing_fault_chain_retains_evidence_and_never_restores(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name == "nt":
        pytest.skip("canonical publication is intentionally Linux-only")

    kill_chain = _build_chain(tmp_path / "kill-after-commit", monkeypatch)
    real_require_live_commit = LeasedEffectAuthorization.require_live_commit

    def stop_after_commit(self, commit, execution):
        record = real_require_live_commit(self, commit, execution)
        if execution.execution_id == kill_chain.authorized.execution.execution_id:
            KillSwitch(
                kill_chain.resolved_kill_switch.path,
                sweep_managed=False,
            ).stop("test stop immediately after durable commit")
        return record

    with monkeypatch.context() as scoped:
        scoped.setattr(
            LeasedEffectAuthorization,
            "require_live_commit",
            stop_after_commit,
        )
        with pytest.raises(OffloadTargetWriteIndeterminate) as stopped:
            _publish(kill_chain)
    assert stopped.value.after_observation is None
    assert kill_chain.target.read_bytes() == BEFORE
    assert not kill_chain.stage.exists()
    assert not kill_chain.recovery.exists()
    assert (
        kill_chain.authorized.authorization.ledger.execution_state(
            kill_chain.authorized.execution.execution_id
        )
        == "COMMITTING"
    )

    stage_chain = _build_chain(tmp_path / "stage-fault", monkeypatch)

    def partial_stage_write(descriptor: int, _candidate: bytes) -> None:
        os.write(descriptor, b"partial-stage-evidence")
        raise OSError("injected real staging write failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "daedalus.kernel.offload_target._write_all",
            partial_stage_write,
        )
        with pytest.raises(OffloadTargetWriteIndeterminate) as stage_fault:
            _publish(stage_chain)
    assert stage_fault.value.after_observation is None
    assert stage_chain.target.read_bytes() == BEFORE
    assert stage_chain.stage.read_bytes() == b"partial-stage-evidence"
    assert not stage_chain.recovery.exists()
    assert (
        stage_chain.authorized.authorization.ledger.execution_state(
            stage_chain.authorized.execution.execution_id
        )
        == "COMMITTING"
    )
    with pytest.raises(EffectLeaseStateError, match="promot"):
        stage_chain.authorized.authorization.finish_claimed_effect(
            stage_chain.claim,
            outcome="failed",
            detail_sha256=_sha("must remain committing"),
        )

    post_swap_chain = _build_chain(tmp_path / "post-swap-writer", monkeypatch)
    newest_bytes = b"def value():\n    return 101\n"
    real_swap = _swap_candidate_into_target

    def write_newest_after_swap(**kwargs: Any) -> None:
        real_swap(**kwargs)
        post_swap_chain.target.write_bytes(newest_bytes)

    with monkeypatch.context() as scoped:
        scoped.setattr(
            "daedalus.kernel.offload_target._swap_candidate_into_target",
            write_newest_after_swap,
        )
        with pytest.raises(OffloadTargetWriteIndeterminate) as post_swap_fault:
            _publish(post_swap_chain)
    assert post_swap_fault.value.after_observation is None
    assert post_swap_chain.target.read_bytes() == newest_bytes
    assert post_swap_chain.recovery.read_bytes() == BEFORE
    assert not post_swap_chain.stage.exists()
    assert post_swap_chain.store.get_bytes(
        post_swap_chain.chat.candidate_sha256
    ) == CANDIDATE
    assert (
        post_swap_chain.authorized.authorization.ledger.execution_state(
            post_swap_chain.authorized.execution.execution_id
        )
        == "COMMITTING"
    )
