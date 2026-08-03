"""Focused real-I/O tests for the Gate-0 offload observation chain."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

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
    EffectExecutionClaim,
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectStartResult,
    LeasedEffectAuthorization,
    LeasedEffectStartReceipt,
    issue_effect_lease,
)
from daedalus.kernel.offload_observations import (
    BASE_SOURCE_ARTIFACT_KIND,
    OFFLOAD_CANDIDATE_TARGET_ARTIFACT_KIND,
    OLLAMA_CHAT_RESPONSE_ARTIFACT_KIND,
    OLLAMA_METADATA_ARTIFACT_KIND,
    SOURCE_FINGERPRINT_ARTIFACT_KIND,
    OffloadObservationError,
    OffloadWorkspaceObservation,
    OllamaChatObservation,
    OllamaChatObservationV1,
    OllamaModelObservation,
    OllamaModelObservationV1,
    TargetBeforeObservation,
    TaskAttemptWorkspaceAttestation,
    decode_ollama_chat_observation,
    decode_ollama_model_observation,
)
from daedalus.kernel.offload_protocol import (
    ParsedOffloadCandidate,
    parse_offload_chat_response,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision
from daedalus.spine.envelope import canonical_json
from daedalus.spine.source_state import SourceFingerprint, fingerprint_source
from daedalus.storage import ArtifactLocator, ArtifactStore


NOW = "2026-08-03T03:30:00.000000+00:00"
TARGET = "src/module.py"
MODEL_ID = "qwen2.5-coder:7b"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


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
class _ObservedWorkspace:
    repo: Path
    workspace: Path
    manager: GitWorktreeManager
    revision: str
    attestation: TaskAttemptWorkspaceAttestation
    target: TargetBeforeObservation


@pytest.fixture
def observed_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _ObservedWorkspace:
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "worktree-root"))
    monkeypatch.setenv("DAEDALUS_MIN_FREE_GIB", "0")
    repo = tmp_path / "primary"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Observation Test")
    _git(repo, "config", "user.email", "observation@example.test")
    # The bounded slice intentionally requires working-tree bytes to equal the
    # indexed blob bytes; repositories with clean/smudge or EOL transforms are
    # refused rather than silently observed under a second byte identity.
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "src").mkdir()
    (repo / TARGET).write_text("def value():\n    return 7\n", encoding="utf-8")
    _git(repo, "add", "--", TARGET)
    _git(repo, "commit", "-m", "base")
    revision = _git(repo, "rev-parse", "HEAD")

    manager = GitWorktreeManager(repo)
    workspace = manager.create_worktree(revision, "observe-offload")
    attestation = TaskAttemptWorkspaceAttestation.capture(
        manager=manager,
        workspace_path=workspace,
        workspace_id="task-attempt-1",
        spine_intent_id=17,
        spine_intent_sha256=_sha("spine-intent"),
        task_id="task-1",
        task_sha256=_sha("task"),
        source_revision=revision,
        origin="tests.offload-observations",
        created_at=NOW,
        trace_id="trace-1",
    )
    target = TargetBeforeObservation.capture(
        manager=manager,
        workspace_path=workspace,
        workspace_attestation=attestation,
        target_path=TARGET,
        origin="tests.offload-observations",
        created_at=NOW,
        trace_id="trace-1",
    )
    return _ObservedWorkspace(repo, workspace, manager, revision, attestation, target)


def _put_fingerprint(
    observed: _ObservedWorkspace, store: ArtifactStore
) -> tuple[SourceFingerprint, ArtifactLocator]:
    fingerprint = fingerprint_source(observed.workspace)
    raw = canonical_json(fingerprint.to_dict()).encode("ascii")
    locator = store.put_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/vnd.daedalus.source-fingerprint+json",
        metadata={
            "kind": SOURCE_FINGERPRINT_ARTIFACT_KIND,
            "source_fingerprint_sha256": fingerprint.fingerprint_sha256,
            "source_revision": observed.revision,
            "workspace_attestation_sha256": observed.attestation.digest,
        },
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=observed.revision,
            created_at=NOW,
            input_digests=(
                observed.attestation.digest,
                fingerprint.fingerprint_sha256,
            ),
            trace_id="trace-1",
        ).to_dict(),
    )
    return fingerprint, locator


def _capture_workspace_observation(
    observed: _ObservedWorkspace,
    store: ArtifactStore,
    *,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> OffloadWorkspaceObservation:
    fingerprint, locator = _put_fingerprint(observed, store)
    base_locator = store.put_bytes(
        _git_bytes(observed.repo, "archive", "--format=tar", observed.revision),
        media_type="application/x-tar",
        metadata={
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": observed.revision,
        },
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=observed.revision,
            created_at=NOW,
            input_digests=(_sha("source-fetch-receipt"),),
        ).to_dict(),
    )
    if monkeypatch is not None:
        def refuse_process_spawn(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("observation capture attempted a process spawn")

        monkeypatch.setattr(subprocess, "run", refuse_process_spawn)
    return OffloadWorkspaceObservation.capture(
        manager=observed.manager,
        workspace_path=observed.workspace,
        workspace_attestation=observed.attestation,
        target_before=observed.target,
        base_source_artifact_locator=base_locator,
        source_fingerprint=fingerprint,
        source_fingerprint_locator=locator,
        artifact_store=store,
        origin="tests.offload-observations",
        created_at=NOW,
        trace_id="trace-1",
    )


def _schema(name: str) -> dict[str, object]:
    root = Path(__file__).resolve().parents[2]
    return json.loads((root / "configs" / "schemas" / name).read_text(encoding="utf-8"))


def test_workspace_attestation_rejects_a_forged_git_common_directory(
    observed_workspace: _ObservedWorkspace,
    tmp_path: Path,
) -> None:
    fake_common = tmp_path / "fake-common"
    fake_admin = fake_common / "worktrees" / "forged"
    fake_admin.mkdir(parents=True)
    (fake_admin / "commondir").write_text("../..\n", encoding="utf-8")
    (fake_admin / "HEAD").write_text(
        "ref: refs/heads/observe-offload\n", encoding="utf-8"
    )
    fake_ref = fake_common / "refs" / "heads" / "observe-offload"
    fake_ref.parent.mkdir(parents=True)
    fake_ref.write_text(observed_workspace.revision + "\n", encoding="ascii")
    git_control = observed_workspace.workspace / ".git"
    os.chmod(git_control, 0o600)
    if os.name == "nt":
        subprocess.run(
            ["attrib", "-R", "-H", os.fspath(git_control)],
            check=True,
            capture_output=True,
        )
    git_control.write_text(
        f"gitdir: {fake_admin}\n", encoding="utf-8"
    )

    with pytest.raises(OffloadObservationError, match="primary checkout .git"):
        TaskAttemptWorkspaceAttestation.capture(
            manager=observed_workspace.manager,
            workspace_path=observed_workspace.workspace,
            workspace_id="task-attempt-forged",
            spine_intent_id=17,
            spine_intent_sha256=_sha("spine-intent"),
            task_id="task-1",
            task_sha256=_sha("task"),
            source_revision=observed_workspace.revision,
            origin="tests.offload-observations",
            created_at=NOW,
        )


def test_real_worktree_index_file_fingerprint_cas_chain_is_closed_and_round_trips(
    observed_workspace: _ObservedWorkspace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ArtifactStore(tmp_path / "cas", min_free_gib=0)
    workspace_observation = _capture_workspace_observation(
        observed_workspace, store, monkeypatch=monkeypatch
    )

    assert observed_workspace.target.content_sha256 == hashlib.sha256(
        (observed_workspace.workspace / TARGET).read_bytes()
    ).hexdigest()
    assert workspace_observation.workspace_attestation_sha256 == observed_workspace.attestation.digest
    assert workspace_observation.target_before_observation_sha256 == observed_workspace.target.digest
    assert workspace_observation.source_revision == observed_workspace.revision
    observed_workspace.attestation.verify_current(
        observed_workspace.manager, observed_workspace.workspace
    )
    observed_workspace.target.verify_current(
        manager=observed_workspace.manager,
        workspace_path=observed_workspace.workspace,
        workspace_attestation=observed_workspace.attestation,
    )

    contracts = (
        (
            observed_workspace.attestation,
            TaskAttemptWorkspaceAttestation,
            "task-attempt-workspace-attestation-v1.schema.json",
        ),
        (
            observed_workspace.target,
            TargetBeforeObservation,
            "target-before-observation-v2.schema.json",
        ),
        (
            workspace_observation,
            OffloadWorkspaceObservation,
            "offload-workspace-observation-v1.schema.json",
        ),
    )
    for contract, contract_type, schema_name in contracts:
        schema = _schema(schema_name)
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(contract.to_dict(), schema)
        restored = contract_type.from_dict(contract.to_dict())
        assert restored == contract
        assert restored.digest == contract.digest
        assert set(contract.to_dict()) == set(schema["properties"]) == set(schema["required"])

def test_target_and_live_allocation_tamper_are_detected_without_a_false_observation(
    observed_workspace: _ObservedWorkspace, tmp_path: Path
) -> None:
    store = ArtifactStore(tmp_path / "dirty-cas", min_free_gib=0)
    fingerprint, fingerprint_locator = _put_fingerprint(observed_workspace, store)
    bad_base_metadata = (
        {
            "kind": "daedalus.unrelated-artifact/1",
            "source_revision": observed_workspace.revision,
        },
        {
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": "f" * 40,
        },
        {
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": observed_workspace.revision,
            "unregistered": True,
        },
    )
    for index, metadata in enumerate(bad_base_metadata):
        wrong_base = store.put_bytes(
            f"not source archive {index}".encode("ascii"),
            metadata=metadata,
            provenance=ContractProvenance(
                origin="tests.offload-observations",
                source_revision=observed_workspace.revision,
                created_at=NOW,
                input_digests=(_sha(f"unrelated-input-{index}"),),
            ).to_dict(),
        )
        with pytest.raises(OffloadObservationError, match="base source CAS metadata"):
            OffloadWorkspaceObservation.capture(
                manager=observed_workspace.manager,
                workspace_path=observed_workspace.workspace,
                workspace_attestation=observed_workspace.attestation,
                target_before=observed_workspace.target,
                base_source_artifact_locator=wrong_base,
                source_fingerprint=fingerprint,
                source_fingerprint_locator=fingerprint_locator,
                artifact_store=store,
                origin="tests.offload-observations",
                created_at=NOW,
            )

    target_path = observed_workspace.workspace / TARGET
    original = target_path.read_bytes()
    target_path.write_bytes(original + b"# candidate tamper\n")
    with pytest.raises(OffloadObservationError, match="stage-0 Git blob OID"):
        TargetBeforeObservation.capture(
            manager=observed_workspace.manager,
            workspace_path=observed_workspace.workspace,
            workspace_attestation=observed_workspace.attestation,
            target_path=TARGET,
            origin="tests.offload-observations",
            created_at=NOW,
        )
    with pytest.raises(OffloadObservationError, match="stage-0 Git blob OID"):
        observed_workspace.target.verify_current(
            manager=observed_workspace.manager,
            workspace_path=observed_workspace.workspace,
            workspace_attestation=observed_workspace.attestation,
        )
    dirty_fingerprint = fingerprint_source(observed_workspace.workspace)
    dirty_raw = canonical_json(dirty_fingerprint.to_dict()).encode("ascii")
    dirty_locator = store.put_bytes(
        dirty_raw,
        metadata={
            "kind": SOURCE_FINGERPRINT_ARTIFACT_KIND,
            "source_fingerprint_sha256": dirty_fingerprint.fingerprint_sha256,
            "source_revision": observed_workspace.revision,
            "workspace_attestation_sha256": observed_workspace.attestation.digest,
        },
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=observed_workspace.revision,
            created_at=NOW,
            input_digests=(
                observed_workspace.attestation.digest,
                dirty_fingerprint.fingerprint_sha256,
            ),
        ).to_dict(),
    )
    dirty_base_locator = store.put_bytes(
        _git_bytes(
            observed_workspace.repo,
            "archive",
            "--format=tar",
            observed_workspace.revision,
        ),
        media_type="application/x-tar",
        metadata={
            "kind": BASE_SOURCE_ARTIFACT_KIND,
            "source_revision": observed_workspace.revision,
        },
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=observed_workspace.revision,
            created_at=NOW,
            input_digests=(_sha("source-fetch-receipt"),),
        ).to_dict(),
    )
    with pytest.raises(OffloadObservationError):
        OffloadWorkspaceObservation.capture(
            manager=observed_workspace.manager,
            workspace_path=observed_workspace.workspace,
            workspace_attestation=observed_workspace.attestation,
            target_before=observed_workspace.target,
            base_source_artifact_locator=dirty_base_locator,
            source_fingerprint=dirty_fingerprint,
            source_fingerprint_locator=dirty_locator,
            artifact_store=store,
            origin="tests.offload-observations",
            created_at=NOW,
        )

    target_path.write_bytes(original)
    allocation_path = observed_workspace.manager._alloc_file(observed_workspace.workspace)
    allocation = json.loads(allocation_path.read_text(encoding="utf-8"))
    allocation["branch"] = "forged-branch"
    allocation_path.write_text(json.dumps(allocation, indent=2), encoding="utf-8")
    with pytest.raises(RuntimeError, match="disk allocation disagrees"):
        observed_workspace.attestation.verify_current(
            observed_workspace.manager, observed_workspace.workspace
        )


def test_portable_aliases_and_a_real_symlink_target_are_refused(
    observed_workspace: _ObservedWorkspace,
) -> None:
    aliases = (
        "src\\module.py",
        "src/../src/module.py",
        "src/./module.py",
        "src//module.py",
        "C:/src/module.py",
        "src/MODULE~1.PY",
    )
    for alias in aliases:
        with pytest.raises(ValueError, match="target_path"):
            TargetBeforeObservation.capture(
                manager=observed_workspace.manager,
                workspace_path=observed_workspace.workspace,
                workspace_attestation=observed_workspace.attestation,
                target_path=alias,
                origin="tests.offload-observations",
                created_at=NOW,
            )

    target = observed_workspace.workspace / TARGET
    referent = observed_workspace.workspace / "src" / "referent.py"
    referent.write_text("def value():\n    return 8\n", encoding="utf-8")
    target.unlink()
    try:
        os.symlink(referent.name, target)
    except OSError as exc:
        pytest.skip(f"host does not permit an unprivileged real symlink: {exc}")
    with pytest.raises(OffloadObservationError, match="no-follow regular file"):
        TargetBeforeObservation.capture(
            manager=observed_workspace.manager,
            workspace_path=observed_workspace.workspace,
            workspace_attestation=observed_workspace.attestation,
            target_path=TARGET,
            origin="tests.offload-observations",
            created_at=NOW,
        )


def _plan(
    observed: _ObservedWorkspace,
    workspace: OffloadWorkspaceObservation,
    store: ArtifactStore,
) -> OffloadExecutionPlan:
    attempt_id = "attempt-1"
    staging_path = derive_offload_staging_path(
        attempt_id=attempt_id,
        workspace_id=observed.attestation.workspace_id,
        target_path=TARGET,
    )
    staging_sha = offload_staging_path_sha256(staging_path)
    recovery_path = derive_offload_recovery_path(
        attempt_id=attempt_id,
        workspace_id=observed.attestation.workspace_id,
        target_path=TARGET,
    )
    recovery_sha = offload_recovery_path_sha256(recovery_path)
    digest_fields = {
        "spine_intent_sha256": observed.attestation.spine_intent_sha256,
        "attempt_contract_sha256": _sha("attempt-contract"),
        "task_sha256": observed.attestation.task_sha256,
        "base_source_artifact_sha256": workspace.base_source_artifact_sha256,
        "workspace_attestation_sha256": observed.attestation.digest,
        "workspace_observation_sha256": workspace.digest,
        "target_before_sha256": observed.target.content_sha256,
        "expected_model_sha256": _sha("ollama-model-bytes"),
        "prompt_template_sha256": _sha("prompt-template"),
        "prompt_sha256": _sha("prompt"),
        "response_schema_sha256": _sha("response-schema"),
        "ollama_request_sha256": _sha("ollama-request"),
        "attempt_policy_decision_sha256": _sha("attempt-policy"),
        "runtime_manifest_sha256": _sha("runtime-manifest"),
        "runtime_conformance_sha256": _sha("runtime-conformance"),
        "runtime_tool_binding_sha256": _sha("runtime-tool-binding"),
    }
    scope = EffectScope(
        read_only=False,
        writable_paths=tuple(sorted((TARGET, staging_path, recovery_path))),
        egress_endpoints=("http://127.0.0.1:11434",),
        tools=("python.test-runner",),
        secret_refs=(),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=120,
        kill_switch_ref="mission-kill",
    )
    return OffloadExecutionPlan(
        spine_intent_id=observed.attestation.spine_intent_id,
        mission_id="mission-1",
        attempt_id=attempt_id,
        task_id=observed.attestation.task_id,
        **digest_fields,
        source_revision=observed.revision,
        workspace_id=observed.attestation.workspace_id,
        target_path=TARGET,
        target_kind=observed.target.target_kind,
        target_before_size=observed.target.byte_length,
        target_git_mode=observed.target.git_mode,
        provider_id="ollama",
        runtime_id="ollama_http",
        provider_endpoint="http://127.0.0.1:11434",
        model_id=MODEL_ID,
        num_ctx=8192,
        num_predict=1024,
        seed=7,
        temperature_milli=0,
        keep_alive="0",
        max_response_bytes=2_000_000,
        max_metadata_calls=1,
        max_model_calls=1,
        verifier_argv=("python.test-runner", "-q", "tests/test_module.py"),
        verifier_timeout_s=30,
        requested_effects=OFFLOAD_EXECUTION_EFFECTS,
        effect_scope=scope,
        kill_switch_generation=3,
        total_timeout_s=120,
        max_cost_microusd=0,
        staging_path=staging_path,
        staging_path_sha256=staging_sha,
        recovery_path=recovery_path,
        recovery_path_sha256=recovery_sha,
        artifact_store_root_sha256=store.root_sha256,
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=observed.revision,
            created_at=NOW,
            input_digests=(
                *digest_fields.values(),
                staging_sha,
                recovery_sha,
                store.root_sha256,
            ),
            trace_id="trace-1",
        ),
    )


def _execution_and_start(
    plan: OffloadExecutionPlan,
    ledger_path: Path,
    *,
    execution_id: str = "offload-execution-1",
    idempotency_key: str = "offload-idempotency-1",
) -> tuple[
    EffectExecutionRequest,
    EffectStartResult,
    EffectExecutionClaim,
    LeasedEffectAuthorization,
]:
    execution = EffectExecutionRequest(
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        requested_effects=plan.requested_effects,
        writable_paths=plan.effect_scope.writable_paths,
        egress_endpoints=plan.effect_scope.egress_endpoints,
        tools=plan.effect_scope.tools,
        secret_refs=plan.effect_scope.secret_refs,
        max_cost_microusd=0,
        kill_switch_ref=plan.effect_scope.kill_switch_ref,
        kill_switch_generation=plan.kill_switch_generation,
        execution_plan_sha256=plan.digest,
    )
    instant = datetime.fromisoformat(NOW)
    request = EffectLeaseRequest(
        request_id="offload-request-1",
        mission_id=plan.mission_id,
        attempt_id=plan.attempt_id,
        entrypoint_id="python.offload",
        requested_effects=plan.requested_effects,
        effect_scope=plan.effect_scope,
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=plan.kill_switch_generation,
        runtime_manifest_sha256=plan.runtime_manifest_sha256,
        runtime_conformance_sha256=plan.runtime_conformance_sha256,
        execution_plan_sha256=plan.digest,
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=(
                plan.digest,
                plan.runtime_manifest_sha256,
                plan.runtime_conformance_sha256,
            ),
            trace_id="trace-1",
        ),
    )
    policy_sha = _sha("effect-policy")
    policy = PolicyDecision(
        decision_id="offload-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=policy_sha,
        verdict="allow",
        reasons=("bounded observed Ollama call",),
        effect_scope=plan.effect_scope,
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=(request.digest, policy_sha),
            trace_id="trace-1",
        ),
    )
    secret = b"offload-observation-test-key-material-32-bytes"
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="offload-lease-1",
        issuer_key_id="kernel-key-1",
        issued_at=instant - timedelta(seconds=1),
        expires_at=instant + timedelta(minutes=10),
        secret=secret,
    )
    ledger = EffectLeaseLedger(ledger_path)
    ledger.grant(
        lease,
        request=request,
        policy_decision=policy,
        keyring={"kernel-key-1": secret},
        current_kill_switch_generation=plan.kill_switch_generation,
        granted_at=instant,
    )
    spec = REGISTRY_BY_ID["python.offload"]
    authorization = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        keyring={"kernel-key-1": secret},
        guard_decisions=tuple(
            GuardDecision(
                contract,
                True,
                f"artifact-locator:sha256:{_sha(contract)}",
            )
            for contract in spec.guard_contracts
        ),
        current_kill_switch_generation=plan.kill_switch_generation,
    )
    start = authorization.begin_effect(execution, started_at=instant)
    claim = authorization.claim_execution(
        start,
        execution,
        claimed_at=instant + timedelta(microseconds=1),
    )
    authorization.require_live_claim(claim, execution)
    return execution, start, claim, authorization


def _model_response(plan: OffloadExecutionPlan) -> dict[str, object]:
    return {
        "models": [
            {
                "name": plan.model_id,
                "model": plan.model_id,
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


def _put_model_response(
    *,
    store: ArtifactStore,
    plan: OffloadExecutionPlan,
    execution: EffectExecutionRequest,
    claim: EffectExecutionClaim,
    start: LeasedEffectStartReceipt,
    metadata_request_sha256: str,
    raw: bytes,
) -> ArtifactLocator:
    return store.put_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        metadata={
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": execution.digest,
            "claim_receipt_sha256": claim.claim_receipt.receipt_sha256,
            "kind": OLLAMA_METADATA_ARTIFACT_KIND,
            "metadata_request_sha256": metadata_request_sha256,
            "start_receipt_sha256": start.receipt_sha256,
        },
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=(
                plan.digest,
                execution.digest,
                start.receipt_sha256,
                claim.claim_receipt.receipt_sha256,
                metadata_request_sha256,
            ),
            trace_id="trace-1",
        ).to_dict(),
    )


def test_post_begin_raw_ollama_cas_parsing_binds_one_exact_model_and_refuses_ambiguity(
    observed_workspace: _ObservedWorkspace, tmp_path: Path
) -> None:
    store = ArtifactStore(tmp_path / "model-cas", min_free_gib=0)
    workspace = _capture_workspace_observation(observed_workspace, store)
    plan = _plan(observed_workspace, workspace, store)
    execution, start_result, claim, authorization = _execution_and_start(
        plan, tmp_path / "effects.sqlite3"
    )
    start = start_result.receipt
    request_sha = _sha("GET /api/tags")
    authorization.require_live_claim(claim, execution)
    response = _model_response(plan)
    raw = canonical_json(response).encode("ascii")
    locator = _put_model_response(
        store=store,
        plan=plan,
        execution=execution,
        claim=claim,
        start=start,
        metadata_request_sha256=request_sha,
        raw=raw,
    )
    observation = OllamaModelObservation.capture_from_response_bytes(
        execution_request=execution,
        execution_claim=claim,
        authorization=authorization,
        execution_plan=plan,
        metadata_request_sha256=request_sha,
        raw_response_bytes=raw,
        raw_response_locator=locator,
        artifact_store=store,
        origin="tests.offload-observations",
        created_at=NOW,
        trace_id="trace-1",
    )
    assert observation.model_sha256 == plan.expected_model_sha256
    assert observation.raw_response_sha256 == locator.artifact_sha256
    assert observation.start_receipt_sha256 == start.receipt_sha256
    assert observation.claim_receipt_sha256 == claim.claim_receipt.receipt_sha256
    schema = _schema("ollama-model-observation-v2.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(observation.to_dict(), schema)
    assert OllamaModelObservation.from_dict(observation.to_dict()) == observation
    assert set(observation.to_dict()) == set(schema["properties"]) == set(schema["required"])
    v1_payload = observation.to_dict()
    v1_payload["contract_version"] = "1.0.0"
    v1_payload.pop("claim_receipt_sha256")
    v1_payload["provenance"]["input_digests"].remove(
        claim.claim_receipt.receipt_sha256
    )
    v1_schema = _schema("ollama-model-observation-v1.schema.json")
    jsonschema.validate(v1_payload, v1_schema)
    historical_model = decode_ollama_model_observation(v1_payload)
    assert type(historical_model) is OllamaModelObservationV1
    assert historical_model.to_dict() == v1_payload
    assert OllamaModelObservationV1.from_dict(v1_payload).digest == (
        historical_model.digest
    )
    with pytest.raises(ValueError, match="contract_version"):
        OllamaModelObservation.from_dict(v1_payload)

    wrong_claim_sha = _sha("wrong-model-observation-claim")
    wrong_claim_metadata = store.put_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        metadata={**locator.metadata, "claim_receipt_sha256": wrong_claim_sha},
        provenance=locator.provenance,
    )
    missing_claim_provenance = store.put_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        metadata=locator.metadata,
        provenance=ContractProvenance(
            origin="tests.offload-observations",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=tuple(
                value
                for value in locator.provenance["input_digests"]
                if value != claim.claim_receipt.receipt_sha256
            ),
            trace_id="trace-1",
        ).to_dict(),
    )
    for tampered_locator in (
        wrong_claim_metadata,
        missing_claim_provenance,
    ):
        with pytest.raises(OffloadObservationError):
            OllamaModelObservation.capture_from_response_bytes(
                execution_request=execution,
                execution_claim=claim,
                authorization=authorization,
                execution_plan=plan,
                metadata_request_sha256=request_sha,
                raw_response_bytes=raw,
                raw_response_locator=tampered_locator,
                artifact_store=store,
                origin="tests.offload-observations",
                created_at=NOW,
            )

    selected = response["models"][0]
    bad_payloads = (
        {"models": [selected, dict(selected)]},
        {"models": [{**selected, "model": "alias:latest"}]},
        {"models": [{**selected, "digest": f"sha256:{_sha('wrong-model')}"}]},
    )
    for bad_payload in bad_payloads:
        authorization.require_live_claim(claim, execution)
        bad_raw = canonical_json(bad_payload).encode("ascii")
        bad_locator = _put_model_response(
            store=store,
            plan=plan,
            execution=execution,
            claim=claim,
            start=start,
            metadata_request_sha256=request_sha,
            raw=bad_raw,
        )
        with pytest.raises(OffloadObservationError):
            OllamaModelObservation.capture_from_response_bytes(
                execution_request=execution,
                execution_claim=claim,
                authorization=authorization,
                execution_plan=plan,
                metadata_request_sha256=request_sha,
                raw_response_bytes=bad_raw,
                raw_response_locator=bad_locator,
                artifact_store=store,
                origin="tests.offload-observations",
                created_at=NOW,
            )

    authorization.require_live_claim(claim, execution)
    duplicate_key_raw = b'{"models":[],"models":[]}'
    duplicate_locator = _put_model_response(
        store=store,
        plan=plan,
        execution=execution,
        claim=claim,
        start=start,
        metadata_request_sha256=request_sha,
        raw=duplicate_key_raw,
    )
    with pytest.raises(OffloadObservationError, match="duplicate key"):
        OllamaModelObservation.capture_from_response_bytes(
            execution_request=execution,
            execution_claim=claim,
            authorization=authorization,
            execution_plan=plan,
            metadata_request_sha256=request_sha,
            raw_response_bytes=duplicate_key_raw,
            raw_response_locator=duplicate_locator,
            artifact_store=store,
            origin="tests.offload-observations",
            created_at=NOW,
        )

    other_store = ArtifactStore(tmp_path / "other-model-cas", min_free_gib=0)
    other_locator = other_store.put_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        media_type="application/json",
        metadata=locator.metadata,
        provenance=locator.provenance,
    )
    with pytest.raises(OffloadObservationError, match="store root"):
        OllamaModelObservation.capture_from_response_bytes(
            execution_request=execution,
            execution_claim=claim,
            authorization=authorization,
            execution_plan=plan,
            metadata_request_sha256=request_sha,
            raw_response_bytes=raw,
            raw_response_locator=other_locator,
            artifact_store=other_store,
            origin="tests.offload-observations",
            created_at=NOW,
        )

    authorization.finish_claimed_effect(
        claim,
        outcome="failed",
        detail_sha256=_sha("model-observation-test-finished"),
        finished_at=datetime.fromisoformat(NOW) + timedelta(microseconds=2),
    )
    with pytest.raises(OffloadObservationError, match="EXECUTING claim"):
        OllamaModelObservation.capture_from_response_bytes(
            execution_request=execution,
            execution_claim=claim,
            authorization=authorization,
            execution_plan=plan,
            metadata_request_sha256=request_sha,
            raw_response_bytes=raw,
            raw_response_locator=locator,
            artifact_store=store,
            origin="tests.offload-observations",
            created_at=NOW,
        )


@dataclass(frozen=True)
class _ChatChain:
    store: ArtifactStore
    plan: OffloadExecutionPlan
    execution: EffectExecutionRequest
    start_result: EffectStartResult
    execution_claim: EffectExecutionClaim
    authorization: LeasedEffectAuthorization
    model_observation: OllamaModelObservation
    raw_response_bytes: bytes
    parsed_candidate: ParsedOffloadCandidate
    raw_response_locator: ArtifactLocator
    candidate_locator: ArtifactLocator
    observation: OllamaChatObservation


def _chat_response(plan: OffloadExecutionPlan, candidate_text: str) -> bytes:
    assistant_content = canonical_json(
        {"content": candidate_text, "target_path": TARGET}
    )
    return canonical_json(
        {
            "done": True,
            "done_reason": "stop",
            "message": {"content": assistant_content, "role": "assistant"},
            "model": plan.model_id,
        }
    ).encode("ascii")


def _raw_chat_metadata(
    *,
    plan: OffloadExecutionPlan,
    execution: EffectExecutionRequest,
    execution_claim: EffectExecutionClaim,
    start_result: EffectStartResult,
    model_observation: OllamaModelObservation,
    raw_sha256: str,
) -> dict[str, object]:
    return {
        "execution_plan_sha256": plan.digest,
        "execution_request_sha256": execution.digest,
        "claim_receipt_sha256": execution_claim.claim_receipt.receipt_sha256,
        "kind": OLLAMA_CHAT_RESPONSE_ARTIFACT_KIND,
        "model_observation_sha256": model_observation.digest,
        "ollama_request_sha256": plan.ollama_request_sha256,
        "raw_response_sha256": raw_sha256,
        "start_receipt_sha256": start_result.receipt.receipt_sha256,
    }


def _candidate_metadata(
    *,
    observed: _ObservedWorkspace,
    plan: OffloadExecutionPlan,
    execution: EffectExecutionRequest,
    execution_claim: EffectExecutionClaim,
    start_result: EffectStartResult,
    model_observation: OllamaModelObservation,
    parsed: ParsedOffloadCandidate,
    raw_locator: ArtifactLocator,
) -> dict[str, object]:
    return {
        "assistant_content_sha256": parsed.assistant_content_sha256,
        "candidate_sha256": parsed.content_sha256,
        "candidate_size": len(parsed.content_bytes),
        "changes_target": parsed.content_sha256 != observed.target.content_sha256,
        "execution_plan_sha256": plan.digest,
        "execution_request_sha256": execution.digest,
        "claim_receipt_sha256": execution_claim.claim_receipt.receipt_sha256,
        "kind": OFFLOAD_CANDIDATE_TARGET_ARTIFACT_KIND,
        "model_observation_sha256": model_observation.digest,
        "ollama_request_sha256": plan.ollama_request_sha256,
        "raw_response_artifact_locator": raw_locator.locator_uri,
        "raw_response_sha256": parsed.raw_response_sha256,
        "start_receipt_sha256": start_result.receipt.receipt_sha256,
        "target_before_observation_sha256": observed.target.digest,
        "target_before_sha256": observed.target.content_sha256,
        "target_path": observed.target.target_path,
    }


def _capture_chat_chain(
    observed: _ObservedWorkspace,
    tmp_path: Path,
    *,
    candidate_text: str,
) -> _ChatChain:
    store = ArtifactStore(tmp_path / "chat-cas", min_free_gib=0)
    workspace = _capture_workspace_observation(observed, store)
    plan = _plan(observed, workspace, store)
    execution, start_result, claim, authorization = _execution_and_start(
        plan, tmp_path / "chat-effects.sqlite3"
    )
    tags_request_sha = _sha("GET /api/tags chat-chain")
    tags_raw = canonical_json(_model_response(plan)).encode("ascii")
    tags_locator = _put_model_response(
        store=store,
        plan=plan,
        execution=execution,
        claim=claim,
        start=start_result.receipt,
        metadata_request_sha256=tags_request_sha,
        raw=tags_raw,
    )
    model_observation = OllamaModelObservation.capture_from_response_bytes(
        execution_request=execution,
        execution_claim=claim,
        authorization=authorization,
        execution_plan=plan,
        metadata_request_sha256=tags_request_sha,
        raw_response_bytes=tags_raw,
        raw_response_locator=tags_locator,
        artifact_store=store,
        origin="tests.offload-chat-observation",
        created_at=NOW,
        trace_id="trace-1",
    )

    authorization.require_live_claim(claim, execution)
    raw = _chat_response(plan, candidate_text)
    parsed = parse_offload_chat_response(
        raw_response_bytes=raw,
        plan=plan,
        target_before=observed.target,
    )
    raw_inputs = (
        execution.digest,
        start_result.receipt.receipt_sha256,
        claim.claim_receipt.receipt_sha256,
        plan.digest,
        model_observation.digest,
        plan.ollama_request_sha256,
    )
    raw_locator = store.put_bytes(
        raw,
        expected_sha256=parsed.raw_response_sha256,
        media_type="application/json",
        metadata=_raw_chat_metadata(
            plan=plan,
            execution=execution,
            execution_claim=claim,
            start_result=start_result,
            model_observation=model_observation,
            raw_sha256=parsed.raw_response_sha256,
        ),
        provenance=ContractProvenance(
            origin="tests.offload-chat-observation",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=raw_inputs,
            trace_id="trace-1",
        ).to_dict(),
    )
    candidate_inputs = tuple(
        sorted(
            {
                *raw_inputs,
                parsed.raw_response_sha256,
                raw_locator.locator_sha256,
                observed.target.digest,
                observed.target.content_sha256,
                parsed.assistant_content_sha256,
            }
        )
    )
    candidate_locator = store.put_bytes(
        parsed.content_bytes,
        expected_sha256=parsed.content_sha256,
        media_type="text/plain; charset=utf-8",
        metadata=_candidate_metadata(
            observed=observed,
            plan=plan,
            execution=execution,
            execution_claim=claim,
            start_result=start_result,
            model_observation=model_observation,
            parsed=parsed,
            raw_locator=raw_locator,
        ),
        provenance=ContractProvenance(
            origin="tests.offload-chat-observation",
            source_revision=plan.source_revision,
            created_at=NOW,
            input_digests=candidate_inputs,
            trace_id="trace-1",
        ).to_dict(),
    )
    observation = OllamaChatObservation.capture_from_response_bytes(
        execution_request=execution,
        execution_claim=claim,
        authorization=authorization,
        execution_plan=plan,
        model_observation=model_observation,
        target_before=observed.target,
        parsed_candidate=parsed,
        raw_response_bytes=raw,
        raw_response_locator=raw_locator,
        candidate_locator=candidate_locator,
        artifact_store=store,
        origin="tests.offload-chat-observation",
        created_at=NOW,
        trace_id="trace-1",
    )
    return _ChatChain(
        store=store,
        plan=plan,
        execution=execution,
        start_result=start_result,
        execution_claim=claim,
        authorization=authorization,
        model_observation=model_observation,
        raw_response_bytes=raw,
        parsed_candidate=parsed,
        raw_response_locator=raw_locator,
        candidate_locator=candidate_locator,
        observation=observation,
    )


def test_chat_observation_retains_a_real_no_change_candidate_as_negative_evidence(
    observed_workspace: _ObservedWorkspace, tmp_path: Path
) -> None:
    before_text = (observed_workspace.workspace / TARGET).read_bytes().decode("utf-8")
    chain = _capture_chat_chain(
        observed_workspace,
        tmp_path,
        candidate_text=before_text,
    )

    assert chain.observation.changes_target is False
    assert chain.observation.candidate_sha256 == observed_workspace.target.content_sha256
    assert chain.store.get_bytes(chain.observation.candidate_sha256) == before_text.encode(
        "utf-8"
    )
    assert chain.observation.claim_receipt_sha256 == (
        chain.execution_claim.claim_receipt.receipt_sha256
    )
    schema = _schema("ollama-chat-observation-v2.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(chain.observation.to_dict(), schema)
    restored = OllamaChatObservation.from_dict(chain.observation.to_dict())
    assert restored == chain.observation
    assert restored.digest == chain.observation.digest
    assert set(restored.to_dict()) == set(schema["properties"]) == set(schema["required"])
    v1_payload = chain.observation.to_dict()
    v1_payload["contract_version"] = "1.0.0"
    v1_payload.pop("claim_receipt_sha256")
    v1_payload["provenance"]["input_digests"].remove(
        chain.execution_claim.claim_receipt.receipt_sha256
    )
    v1_schema = _schema("ollama-chat-observation-v1.schema.json")
    jsonschema.validate(v1_payload, v1_schema)
    historical_chat = decode_ollama_chat_observation(v1_payload)
    assert type(historical_chat) is OllamaChatObservationV1
    assert historical_chat.to_dict() == v1_payload
    assert OllamaChatObservationV1.from_dict(v1_payload).digest == (
        historical_chat.digest
    )
    with pytest.raises(ValueError, match="contract_version"):
        OllamaChatObservation.from_dict(v1_payload)


def test_changed_chat_candidate_is_bound_and_tamper_matrix_fails_closed(
    observed_workspace: _ObservedWorkspace, tmp_path: Path
) -> None:
    chain = _capture_chat_chain(
        observed_workspace,
        tmp_path,
        candidate_text="def value():\n    return 8\n",
    )
    assert chain.observation.changes_target is True

    raw_metadata = _raw_chat_metadata(
        plan=chain.plan,
        execution=chain.execution,
        execution_claim=chain.execution_claim,
        start_result=chain.start_result,
        model_observation=chain.model_observation,
        raw_sha256=chain.parsed_candidate.raw_response_sha256,
    )
    candidate_metadata = _candidate_metadata(
        observed=observed_workspace,
        plan=chain.plan,
        execution=chain.execution,
        execution_claim=chain.execution_claim,
        start_result=chain.start_result,
        model_observation=chain.model_observation,
        parsed=chain.parsed_candidate,
        raw_locator=chain.raw_response_locator,
    )
    raw_inputs = tuple(chain.raw_response_locator.provenance["input_digests"])
    candidate_inputs = tuple(chain.candidate_locator.provenance["input_digests"])
    wrong_raw_metadata = chain.store.put_bytes(
        chain.raw_response_bytes,
        media_type="application/json",
        metadata={**raw_metadata, "kind": "daedalus.wrong-chat/1"},
        provenance=chain.raw_response_locator.provenance,
    )
    wrong_candidate_metadata = chain.store.put_bytes(
        chain.parsed_candidate.content_bytes,
        media_type="text/plain; charset=utf-8",
        metadata={**candidate_metadata, "changes_target": False},
        provenance=chain.candidate_locator.provenance,
    )
    wrong_raw_bytes = b'{"complete":false}'
    wrong_raw_bytes_locator = chain.store.put_bytes(
        wrong_raw_bytes,
        media_type="application/json",
        metadata=raw_metadata,
        provenance=ContractProvenance(
            origin="tests.offload-chat-observation",
            source_revision=chain.plan.source_revision,
            created_at=NOW,
            input_digests=raw_inputs,
        ).to_dict(),
    )
    wrong_candidate_bytes_locator = chain.store.put_bytes(
        b"different candidate bytes",
        media_type="text/plain; charset=utf-8",
        metadata=candidate_metadata,
        provenance=ContractProvenance(
            origin="tests.offload-chat-observation",
            source_revision=chain.plan.source_revision,
            created_at=NOW,
            input_digests=candidate_inputs,
        ).to_dict(),
    )
    other_store = ArtifactStore(tmp_path / "other-chat-cas", min_free_gib=0)
    other_raw_locator = other_store.put_bytes(
        chain.raw_response_bytes,
        expected_sha256=chain.parsed_candidate.raw_response_sha256,
        media_type="application/json",
        metadata=chain.raw_response_locator.metadata,
        provenance=chain.raw_response_locator.provenance,
    )
    other_candidate_locator = other_store.put_bytes(
        chain.parsed_candidate.content_bytes,
        expected_sha256=chain.parsed_candidate.content_sha256,
        media_type="text/plain; charset=utf-8",
        metadata=chain.candidate_locator.metadata,
        provenance=chain.candidate_locator.provenance,
    )
    wrong_model_sha = _sha("wrong-observed-model")
    wrong_model = replace(
        chain.model_observation,
        model_sha256=wrong_model_sha,
        provenance=replace(
            chain.model_observation.provenance,
            input_digests=tuple(
                wrong_model_sha if value == chain.model_observation.model_sha256 else value
                for value in chain.model_observation.provenance.input_digests
            ),
        ),
    )
    _, _, wrong_claim, _ = _execution_and_start(
        chain.plan,
        tmp_path / "wrong-chat-effects.sqlite3",
        execution_id="offload-execution-other",
        idempotency_key="offload-idempotency-other",
    )
    wrong_model_claim_sha = wrong_claim.claim_receipt.receipt_sha256
    wrong_claim_model = replace(
        chain.model_observation,
        claim_receipt_sha256=wrong_model_claim_sha,
        provenance=replace(
            chain.model_observation.provenance,
            input_digests=tuple(
                wrong_model_claim_sha
                if value == chain.model_observation.claim_receipt_sha256
                else value
                for value in chain.model_observation.provenance.input_digests
            ),
        ),
    )
    wrong_target = replace(observed_workspace.target, target_path="src/other.py")
    wrong_parsed = replace(
        chain.parsed_candidate,
        content_bytes=b"different candidate bytes",
    )

    common = {
        "execution_request": chain.execution,
        "execution_claim": chain.execution_claim,
        "authorization": chain.authorization,
        "execution_plan": chain.plan,
        "model_observation": chain.model_observation,
        "target_before": observed_workspace.target,
        "parsed_candidate": chain.parsed_candidate,
        "raw_response_bytes": chain.raw_response_bytes,
        "raw_response_locator": chain.raw_response_locator,
        "candidate_locator": chain.candidate_locator,
        "artifact_store": chain.store,
        "origin": "tests.offload-chat-observation",
        "created_at": NOW,
    }
    tamper_cases = (
        {"raw_response_locator": wrong_raw_metadata},
        {"candidate_locator": wrong_candidate_metadata},
        {"raw_response_locator": wrong_raw_bytes_locator},
        {"candidate_locator": wrong_candidate_bytes_locator},
        {
            "artifact_store": other_store,
            "raw_response_locator": other_raw_locator,
            "candidate_locator": other_candidate_locator,
        },
        {"model_observation": wrong_model},
        {"model_observation": wrong_claim_model},
        {"execution_claim": wrong_claim},
        {"target_before": wrong_target},
        {"parsed_candidate": wrong_parsed},
        {"raw_response_bytes": chain.raw_response_bytes + b" "},
    )
    for overrides in tamper_cases:
        with pytest.raises(OffloadObservationError):
            OllamaChatObservation.capture_from_response_bytes(
                **{**common, **overrides}
            )
