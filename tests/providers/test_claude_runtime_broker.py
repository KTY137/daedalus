"""Claude provider behind the exact persisted runtime-provider broker.

Since G0-RTC-07A the broker refuses duck-typed or subclassed authority objects,
so every brokered scenario here composes the real persisted stack: an admitted
runtime trust record, a signed runtime-bound Effect Lease, the SQLite effect
ledger, and the signed provider-observation authority with its binding ledger.
Refusals are asserted against durable state (no persisted lease, no execution
row) instead of spy counters on a fake authority.
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import dataclasses
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.claude_bridge as bridge
import daedalus.providers.claude_cli as claude_provider
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.providers.claude_cli import (
    ClaudeCLIProvider,
    ClaudeInvocationBindingMismatch,
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    ClaudeProviderWorkspaceMismatch,
    ClaudeWorkspaceGrant,
    claude_idempotency_key,
    claude_invocation_sha256,
)
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
    run_runtime_provider,
)
from daedalus.limit_policy import ExecutionLimitPolicy, MODE_UNBOUNDED_EXECUTION
from daedalus.runtimes.provider_executable_object_registry import (
    ProviderExecutableObjectRegistry,
)
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_abi import (
    issue_provider_invocation_abi_contract,
)
from daedalus.runtimes.provider_invocation_authority import (
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_payload import (
    build_provider_invocation_payload,
)
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_sha


ENTRYPOINT = "provider.claude"
RUNTIME = "claude_code_cli"
REVISION = "a" * 40
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
POLICY_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
IDENTITY_SHA = "4" * 64
RECEIPT_SHA = "5" * 64
ENVELOPE_SHA = "6" * 64
TRUST_KEY = b"claude-broker-trust-integrity-key-material-32-bytes"
LEASE_KEY = b"claude-broker-effect-lease-secret-material-32-bytes"
AUTHORITY_KEY = b"claude-broker-runtime-authority-key-material-32-bytes"
OBS_AUTHORITY_KEY_ID = "claude-observation-authority-key"
OBS_AUTHORITY_KEY = b"claude-observation-authority-key-material-32-bytes"
OBS_KEY_ID = "claude-observation-issuer-key"
OBS_KEY = b"claude-observation-issuer-key-material-at-least-32b"
RECORD_KEY = b"claude-observation-record-key-material-32-bytes"
ADAPTER_ID = "adapter.claude-cli"
IMPLEMENTATION_ID = "implementation.claude-cli-v1"
PAYLOAD_SCHEMA_ID = "claude-cli-invocation-v1"
REPORT = {
    "status": "needs_review",
    "summary": "bounded review",
    "files_changed": [],
    "tests_run": [],
    "risks": [],
    "todos": [],
    "handoff": {},
}
OUTPUT = {
    "agent": "reviewer",
    "prompt_sha256": "b" * 64,
    "report_sha256": canonical_sha(REPORT),
    "report": REPORT,
}
REPORT_JSON = json.dumps(REPORT)
INVALID_REPORT_JSON = json.dumps({"status": "done"})
UNBOUNDED_SUMMARY = "detail-" * 120
UNBOUNDED_REPORT_JSON = json.dumps({**REPORT, "summary": UNBOUNDED_SUMMARY})


def _successful_subprocess_run(*args, **kwargs):
    del args, kwargs
    return SimpleNamespace(returncode=0, stdout=REPORT_JSON, stderr="")


def _normalized_paths_subprocess_run(*args, **kwargs):
    if '[\n  "src/a.py"\n]' not in args[0][2]:
        raise AssertionError("sealed Claude prompt lost normalized paths")
    return SimpleNamespace(returncode=0, stdout=REPORT_JSON, stderr="")


def _invalid_report_subprocess_run(*args, **kwargs):
    del args, kwargs
    return SimpleNamespace(returncode=0, stdout=INVALID_REPORT_JSON, stderr="")


def _unbounded_subprocess_run(*args, **kwargs):
    if kwargs.get("timeout") is not None:
        raise AssertionError("unbounded sealed invocation retained a timeout")
    prompt = args[0][2]
    if "docs/note-19.md" not in prompt or "Minimize tokens:" in prompt:
        raise AssertionError("unbounded sealed invocation retained bounded prompt caps")
    if "unabridged detail" not in prompt:
        raise AssertionError("unbounded sealed invocation lost detail handoff")
    return SimpleNamespace(returncode=0, stdout=UNBOUNDED_REPORT_JSON, stderr="")


def _spec(*, wiring: Wiring = Wiring.CENTRAL) -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.CLAUDE,
        target="daedalus.providers.claude_cli:ClaudeCLIProvider.run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=(
            "budget.process_guard",
            "provider.write_policy",
            "runtime.adapter_profile",
        ),
        wiring=wiring,
        runtime_id=RUNTIME,
    )


def _registry(*, wiring: Wiring = Wiring.CENTRAL) -> dict[str, EntrypointSpec]:
    row = _spec(wiring=wiring)
    return {row.id: row}


def _agent() -> dict[str, object]:
    return {
        "name": "reviewer",
        "call_name": "Mary",
        "model_tier": "sonnet",
        "must_read": [],
    }


def _scope(
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> EffectScope:
    policy = execution_limit_policy or ExecutionLimitPolicy()
    return EffectScope(
        read_only=False,
        writable_paths=(".",),
        egress_endpoints=("https://api.anthropic.com",),
        tools=("claude",),
        max_cost_microusd=(1000 if policy.enforces("mission_spend") else None),
        max_concurrency=(1 if policy.enforces("concurrency") else None),
        timeout_s=(600 if policy.enforces("wall_time") else None),
        kill_switch_ref="mission-kill",
    )


def _request(
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="claude-broker-request-1",
        mission_id="mission-claude-1",
        attempt_id="attempt-claude-1",
        entrypoint_id=ENTRYPOINT,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=_scope(execution_limit_policy),
        idempotency_namespace="mission-claude-1-attempt-claude-1",
        kill_switch_generation=3,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=RECEIPT_SHA,
        provenance=ContractProvenance(
            origin="tests.claude-runtime-broker",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(MANIFEST_SHA, RECEIPT_SHA),
            trace_id="mission-claude-1",
        ),
    )


REQUEST_SHA = _request().digest


def _policy(request: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="claude-broker-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-17",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded brokered claude provider test",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.claude-runtime-broker-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-claude-1",
        ),
    )


def _trust_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ledger = RuntimeTrustLedger(
        tmp_path / "claude-runtime-trust.sqlite3",
        integrity_key=TRUST_KEY,
    )
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: None,
    )
    manifest = SimpleNamespace(
        runtime_id=RUNTIME,
        digest=MANIFEST_SHA,
        source_revision=REVISION,
    )
    identity = SimpleNamespace(digest=IDENTITY_SHA)
    receipt = SimpleNamespace(
        digest=RECEIPT_SHA,
        finished_at=(NOW - timedelta(minutes=10)).isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id=RUNTIME,
        runtime_manifest_sha256=MANIFEST_SHA,
        probe_identity_sha256=IDENTITY_SHA,
        conformance_receipt_sha256=RECEIPT_SHA,
        source_revision=REVISION,
        digest=ENVELOPE_SHA,
    )
    ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(ENVELOPE_SHA,),
        admitted_at=NOW - timedelta(minutes=9),
        expires_at=NOW + timedelta(hours=2),
    )
    return ledger


def _authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> RuntimeBoundEffectAuthorization:
    trust_ledger = _trust_ledger(tmp_path, monkeypatch)
    request = _request(execution_limit_policy)
    policy = _policy(request)
    registry = _registry()
    capability = issue_runtime_bound_effect_lease(
        request,
        policy,
        lease_id="claude-broker-lease-1",
        lease_issuer_key_id="claude-lease-key-1",
        lease_issuer_secret=LEASE_KEY,
        runtime_envelope_sha256=ENVELOPE_SHA,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="claude-runtime-authority-key-1",
        runtime_authority_secret=AUTHORITY_KEY,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        registry=registry,
    )
    return RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "claude-effect-leases.sqlite3"),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"claude-lease-key-1": LEASE_KEY},
        runtime_authority_keyring={
            "claude-runtime-authority-key-1": AUTHORITY_KEY
        },
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "a" * 64,
            ),
            GuardDecision(
                "provider.write_policy",
                True,
                "artifact-locator:sha256:" + "b" * 64,
            ),
            GuardDecision(
                "runtime.adapter_profile",
                True,
                "artifact-locator:sha256:" + "c" * 64,
            ),
        ),
        current_kill_switch_generation=3,
        registry=registry,
    )


def _observation(
    tmp_path: Path,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
):
    ledger = ProviderObservationBindingLedger(
        tmp_path / "claude-provider-observation.sqlite3",
        authority_id="authority.claude-provider-observation",
        authority_keyring={OBS_AUTHORITY_KEY_ID: OBS_AUTHORITY_KEY},
        observation_keyring={OBS_KEY_ID: OBS_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.claude-provider-observation",
        authority_key_id=OBS_AUTHORITY_KEY_ID,
        authority_secret=OBS_AUTHORITY_KEY,
        binding_id="claude-provider-binding-1",
        provider_id="provider.claude-cli",
        observation_keyring={OBS_KEY_ID: OBS_KEY},
        entrypoint_id=ENTRYPOINT,
        runtime_id=RUNTIME,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    return authority, ledger


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _attach_invocation_stack(
    ledger: ProviderObservationBindingLedger,
    observation,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
    worktree: Path,
    *,
    objective: str,
    paths: list[str],
    timeout_s: int | float | None = 300,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
) -> None:
    subject = ProviderInvocationSubject(
        provider_id=observation.provider_id,
        adapter_id=ADAPTER_ID,
        adapter_artifact_sha256=_sha("claude-adapter-artifact"),
        adapter_config_sha256=_sha("claude-adapter-config"),
        entrypoint_id=ENTRYPOINT,
        runtime_id=RUNTIME,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=REVISION,
    )
    authority = issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=subject,
        invocation_contract_id="claude-provider-invocation-contract-v1",
        invocation_registry_sha256=_sha("claude-invocation-registry"),
        authority_secret=OBS_AUTHORITY_KEY,
    )
    effective_timeout = (
        None
        if execution_limit_policy is not None
        and not execution_limit_policy.enforces("wall_time")
        else (300 if timeout_s is None else timeout_s)
    )
    payload_paths = list(dict.fromkeys(paths))
    if (
        execution_limit_policy is None
        or execution_limit_policy.enforces("work_scope")
    ):
        payload_paths = payload_paths[:12]
    invocation_sha = _invocation_sha(
        worktree,
        objective=objective,
        paths=payload_paths,
        timeout_s=effective_timeout,
        execution_limit_policy=execution_limit_policy,
        request_sha256=authorization.request.digest,
    )
    body = {
        "objective": objective,
        "worktree": str(worktree.resolve()),
        "paths": payload_paths,
        "agent": _agent(),
        "model": "sonnet",
        "timeout_s": effective_timeout,
        "invocation_sha256": invocation_sha,
    }
    if execution_limit_policy is not None:
        body["execution_limit_policy"] = execution_limit_policy.as_dict()
        body["execution_limit_policy_sha256"] = (
            execution_limit_policy.fingerprint_sha256
        )
    payload = build_provider_invocation_payload(
        subject,
        payload_schema_id=PAYLOAD_SCHEMA_ID,
        body=body,
    )
    source_path = Path(bridge.__file__).resolve()
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    output_source_sha = hashlib.sha256(
        Path(claude_provider.__file__).resolve().read_bytes()
    ).hexdigest()
    pre_admission = ProviderExecutablePreAdmissionReceipt(
        source_revision=REVISION,
        resolution_sha256=_sha("claude-resolution"),
        verification_sha256=_sha("claude-verification"),
        structure_sha256=_sha("claude-structure"),
        completed_retention_sha256=_sha("claude-retention"),
        retention_effect_terminal_sha256=_sha("claude-retention-terminal"),
        repository_head_sha256=_sha("claude-repository-head"),
        provider_id=subject.provider_id,
        adapter_id=subject.adapter_id,
        implementation_id=IMPLEMENTATION_ID,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution_id=subject.execution_id,
        idempotency_key=subject.idempotency_key,
        invocation_authority_sha256=authority.digest,
        invocation_contract_sha256=authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        invocation_identity_projection_sha256=_sha("claude-identity-projection"),
        identity_registry_sha256=authority.invocation_registry_sha256,
        identity_descriptor_sha256=_sha("claude-identity-descriptor"),
        target_authority_sha256=_sha("claude-target-authority"),
        target_projection_sha256=_sha("claude-target-projection"),
        target_manifest_sha256=_sha("claude-target-manifest"),
        target_descriptor_sha256=_sha("claude-target-descriptor"),
        adapter_artifact_sha256=subject.adapter_artifact_sha256,
        adapter_config_sha256=subject.adapter_config_sha256,
        lease_sha256=subject.lease_sha256,
        invoke_target="daedalus.claude_bridge:_invoke_claude_payload",
        invoke_source_sha256=source_sha,
        output_digests_target="daedalus.providers.claude_cli:_output_digests",
        output_digests_source_sha256=output_source_sha,
    )
    registry = ProviderExecutableObjectRegistry(Path(__file__).resolve().parents[2])
    executable_admission = registry.register(
        pre_admission,
        invoke=bridge._invoke_claude_payload,
        output_digests=claude_provider._output_digests,
    )
    abi = issue_provider_invocation_abi_contract(
        authority,
        payload,
        pre_admission,
        dependency_manifest_sha256=(
            executable_admission.dependency_manifest_sha256
        ),
        authority_id="authority.claude-provider-observation",
        authority_keyring={OBS_AUTHORITY_KEY_ID: OBS_AUTHORITY_KEY},
        observation_keyring={OBS_KEY_ID: OBS_KEY},
        execution=execution,
        at=NOW,
    )
    ledger._test_observation = observation
    ledger._test_invocation_authority = authority
    ledger._test_invocation_payload = payload
    ledger._test_invocation_abi = abi
    ledger._test_executable_registry = registry
    ledger._test_pre_admission = pre_admission


def _set_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: NOW,
    )
    monkeypatch.setattr(
        "daedalus.kernel.effects._utc_now",
        lambda: NOW + timedelta(seconds=3),
    )
    monkeypatch.setattr(
        "daedalus.runtimes.broker._utc_now",
        lambda: NOW + timedelta(seconds=2),
    )


def _invocation_sha(
    worktree: Path,
    *,
    objective: str = "review",
    paths: list[str] | None = None,
    agent: dict[str, object] | None = None,
    model: str = "sonnet",
    timeout_s: int | float | None = 300,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
    request_sha256: str = REQUEST_SHA,
) -> str:
    return claude_invocation_sha256(
        objective=objective,
        worktree=str(worktree),
        paths=list(paths or []),
        agent=agent or _agent(),
        model=model,
        timeout_s=timeout_s,
        attempt_id="attempt-claude-1",
        source_revision=REVISION,
        request_sha256=request_sha256,
        execution_limit_policy=execution_limit_policy,
    )


def _execution(
    worktree: Path,
    *,
    objective: str = "review",
    paths: list[str] | None = None,
    agent: dict[str, object] | None = None,
    model: str = "sonnet",
    timeout_s: int | float | None = 300,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
    request_sha256: str = REQUEST_SHA,
    **changes,
) -> EffectExecutionRequest:
    invocation_sha = _invocation_sha(
        worktree,
        objective=objective,
        paths=paths,
        agent=agent,
        model=model,
        timeout_s=timeout_s,
        execution_limit_policy=execution_limit_policy,
        request_sha256=request_sha256,
    )
    values = dict(
        execution_id="claude-execution-1",
        idempotency_key=claude_idempotency_key(invocation_sha),
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        writable_paths=(".",),
        egress_endpoints=("https://api.anthropic.com",),
        tools=("claude",),
        max_cost_microusd=(
            1000
            if execution_limit_policy is None
            or execution_limit_policy.enforces("mission_spend")
            else None
        ),
        kill_switch_ref="mission-kill",
        kill_switch_generation=3,
    )
    values.update(changes)
    return EffectExecutionRequest(**values)


def _grant(
    worktree: Path,
    execution: EffectExecutionRequest,
    *,
    attempt_id: str = "attempt-claude-1",
    request_sha256: str = REQUEST_SHA,
    source_revision: str = REVISION,
) -> ClaudeWorkspaceGrant:
    return ClaudeWorkspaceGrant(
        attempt_id=attempt_id,
        source_revision=source_revision,
        request_sha256=request_sha256,
        execution_sha256=execution.digest,
        worktree=str(worktree),
    )


def _stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    objective: str = "review",
    paths: list[str] | None = None,
    execution: EffectExecutionRequest | None = None,
    timeout_s: int | float | None = 300,
    execution_limit_policy: ExecutionLimitPolicy | None = None,
    subprocess_run=None,
):
    authorization = _authorization(
        tmp_path,
        monkeypatch,
        execution_limit_policy=execution_limit_policy,
    )
    if execution is None:
        execution = _execution(
            tmp_path,
            objective=objective,
            paths=paths,
            timeout_s=timeout_s,
            execution_limit_policy=execution_limit_policy,
            request_sha256=authorization.request.digest,
        )
    authority, ledger = _observation(tmp_path, authorization, execution)
    if subprocess_run is not None:
        monkeypatch.setattr(bridge.subprocess, "run", subprocess_run)
    _attach_invocation_stack(
        ledger,
        authority,
        authorization,
        execution,
        tmp_path,
        objective=objective,
        paths=list(paths or []),
        timeout_s=timeout_s,
        execution_limit_policy=execution_limit_policy,
    )
    _set_clocks(monkeypatch)
    return authorization, execution, authority, ledger


def _run_kwargs(
    tmp_path: Path,
    authorization,
    execution,
    authority,
    ledger,
    **overrides,
):
    kwargs = dict(
        objective="review",
        repo_root=str(tmp_path),
        paths=[],
        agent=_agent(),
        runtime_authorization=authorization,
        effect_execution=execution,
        workspace_grant=_grant(
            tmp_path,
            execution,
            request_sha256=authorization.request.digest,
        ),
        invocation_authority=(
            ledger._test_invocation_authority
            if authority is ledger._test_observation
            else dataclasses.replace(
                ledger._test_invocation_authority,
                observation_authority=authority,
            )
        ),
        invocation_payload=ledger._test_invocation_payload,
        invocation_abi=ledger._test_invocation_abi,
        observation_binding_ledger=ledger,
        executable_registry=ledger._test_executable_registry,
        pre_admission=ledger._test_pre_admission,
    )
    kwargs.update(overrides)
    return kwargs


def _lease_rows(tmp_path: Path) -> int:
    db = tmp_path / "claude-effect-leases.sqlite3"
    if not db.exists():
        return 0
    with contextlib.closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT COUNT(*) FROM effect_leases").fetchone()[0]


def _execution_row(tmp_path: Path, execution_id: str):
    db = tmp_path / "claude-effect-leases.sqlite3"
    with contextlib.closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT state, terminal_receipt_json FROM effect_executions "
            "WHERE execution_id=?",
            (execution_id,),
        ).fetchone()


def test_public_provider_refuses_missing_authority_before_private_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("invoked"),
    )

    with pytest.raises(ClaudeProviderAuthorizationRequired):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
        )

    assert called == []


def test_missing_observation_authority_refuses_before_any_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("invoked"),
    )

    for overrides in (
        {"invocation_authority": None},
        {"observation_binding_ledger": None},
    ):
        with pytest.raises(
            ClaudeProviderAuthorizationRequired,
            match="authenticated invocation ABI",
        ):
            ClaudeCLIProvider().run(
                **_run_kwargs(
                    tmp_path,
                    authorization,
                    execution,
                    authority,
                    ledger,
                    **overrides,
                )
            )
    assert called == []
    assert _lease_rows(tmp_path) == 0


def test_exact_workspace_request_execution_attempt_and_revision_are_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs: None)
    other = tmp_path / "other"
    other.mkdir()

    cases = [
        ("exact bound", _grant(other, execution)),
        ("different attempt", _grant(tmp_path, execution, attempt_id="attempt-other")),
        ("source revision", _grant(tmp_path, execution, source_revision="f" * 40)),
        ("lease request", _grant(tmp_path, execution, request_sha256="e" * 64)),
        (
            "execution request",
            _grant(
                tmp_path,
                _execution(tmp_path, execution_id="claude-execution-other"),
            ),
        ),
    ]
    for match, grant in cases:
        with pytest.raises(ClaudeProviderWorkspaceMismatch, match=match):
            ClaudeCLIProvider().run(
                **_run_kwargs(
                    tmp_path,
                    authorization,
                    execution,
                    authority,
                    ledger,
                    workspace_grant=grant,
                )
            )
        assert _lease_rows(tmp_path) == 0


def test_execution_scope_must_honestly_cover_agentic_workspace_and_spend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs: None)

    narrowed = _execution(tmp_path, paths=["src/a.py"], writable_paths=("src",))
    authorization, _, authority, ledger = _stack(
        tmp_path, monkeypatch, execution=narrowed
    )
    with pytest.raises(ClaudeProviderScopeMismatch, match="worktree root"):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                narrowed,
                authority,
                ledger,
                paths=["src/a.py"],
            )
        )

    no_spend = _execution(tmp_path, max_cost_microusd=0)
    with pytest.raises(ClaudeProviderScopeMismatch, match="spend ceiling"):
        ClaudeCLIProvider().run(
            **_run_kwargs(tmp_path, authorization, no_spend, authority, ledger)
        )
    assert _lease_rows(tmp_path) == 0


def test_unbounded_execution_shape_requires_explicit_null_spend(
    tmp_path: Path,
) -> None:
    policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    execution = _execution(
        tmp_path,
        timeout_s=None,
        execution_limit_policy=policy,
        max_cost_microusd=None,
    )

    assert claude_provider._validate_execution_shape(
        execution,
        [],
        policy,
    ) == []

    with pytest.raises(ClaudeProviderScopeMismatch, match="must carry null cost"):
        claude_provider._validate_execution_shape(
            dataclasses.replace(execution, max_cost_microusd=1),
            [],
            policy,
        )


@pytest.mark.parametrize(
    "malformed_path",
    ["../primary/secret.py", "/etc/passwd", "C:/repo/file.py", "bad\x00path"],
)
def test_malformed_path_refuses_before_broker_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    malformed_path: str,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("invoked"),
    )

    with pytest.raises(ClaudeProviderScopeMismatch):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                execution,
                authority,
                ledger,
                paths=[malformed_path],
            )
        )
    assert called == []
    assert _lease_rows(tmp_path) == 0


@pytest.mark.parametrize(
    ("changed_field", "value"),
    [
        ("objective", "different objective"),
        ("paths", ["different.py"]),
        ("model", "opus"),
        ("timeout_s", 301),
    ],
)
def test_invocation_change_cannot_reuse_execution_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_field: str,
    value,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("invoked"),
    )
    call = {
        "objective": "review",
        "paths": [],
        "model": "sonnet",
        "timeout_s": 300,
    }
    call[changed_field] = value

    with pytest.raises(ClaudeInvocationBindingMismatch, match="exact invocation"):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                execution,
                authority,
                ledger,
                objective=call["objective"],
                paths=call["paths"],
                model=call["model"],
                timeout_s=call["timeout_s"],
            )
        )
    assert called == []
    assert _lease_rows(tmp_path) == 0


def test_invalid_invocation_metadata_refuses_before_broker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("invoked"),
    )

    with pytest.raises(ValueError, match="objective"):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                execution,
                authority,
                ledger,
                objective=" ",
            )
        )
    with pytest.raises(ValueError, match="timeout_s"):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                execution,
                authority,
                ledger,
                timeout_s=0,
            )
        )
    assert called == []
    assert _lease_rows(tmp_path) == 0


def test_brokered_provider_invokes_once_and_releases_only_after_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    objective = "review exact diff"
    paths = ["src/a.py", "src/a.py"]
    normalized_paths = ["src/a.py"]
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        objective=objective,
        paths=normalized_paths,
        subprocess_run=_normalized_paths_subprocess_run,
    )
    invocation_sha = _invocation_sha(
        tmp_path,
        objective=objective,
        paths=normalized_paths,
    )

    result = ClaudeCLIProvider().run(
        **_run_kwargs(
            tmp_path,
            authorization,
            execution,
            authority,
            ledger,
            objective=objective,
            paths=paths,
        )
    )

    expected_output = canonical_sha(
        {
            "provider": "claude_cli",
            "agent": "reviewer",
            "invocation_sha256": invocation_sha,
            "prompt_sha256": result["prompt_sha256"],
            "report_sha256": result["report_sha256"],
            "report": result["report"],
        }
    )
    row = _execution_row(tmp_path, execution.execution_id)
    assert row is not None
    assert row["state"] == "COMPLETED"
    terminal = json.loads(row["terminal_receipt_json"])
    assert terminal["outcome"] == "COMPLETED"
    assert terminal["output_digests"] == [expected_output]
    binding = ledger.load(execution.execution_id)
    assert binding is not None
    assert binding.authority == authority
    assert result["provider"] == "claude_cli"
    assert result["report"] == OUTPUT["report"]
    assert result["runtime_receipt"]["executed"] is True
    assert result["runtime_receipt"]["invocation_sha256"] == invocation_sha
    assert (
        result["runtime_receipt"]["terminal_receipt_sha256"]
        == terminal["receipt_sha256"]
    )


def test_invalid_provider_report_is_terminally_failed_and_withholds_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_invalid_report_subprocess_run,
    )

    with pytest.raises(ValueError, match="Invalid Claude report"):
        ClaudeCLIProvider().run(
            **_run_kwargs(tmp_path, authorization, execution, authority, ledger)
        )

    row = _execution_row(tmp_path, execution.execution_id)
    assert row is not None
    assert row["state"] == "FAILED"
    assert json.loads(row["terminal_receipt_json"])["outcome"] == "FAILED"


def test_exact_replay_is_inert_and_does_not_extract_output_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    run_kwargs = _run_kwargs(
        tmp_path,
        authorization,
        execution,
        authority,
        ledger,
    )

    first = ClaudeCLIProvider().run(**run_kwargs)
    assert first["runtime_receipt"]["executed"] is True
    replay_trap: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: replay_trap.append("invoked"),
    )

    result = ClaudeCLIProvider().run(**run_kwargs)

    assert replay_trap == []
    assert result["replay"] is True
    assert result["runtime_receipt"]["executed"] is False
    assert result["runtime_receipt"]["terminal_receipt_sha256"] is None


def test_registered_adapter_cannot_be_redirected_by_later_global_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    run_kwargs = _run_kwargs(
        tmp_path,
        authorization,
        execution,
        authority,
        ledger,
    )
    redirected: list[str] = []
    monkeypatch.setattr(
        bridge,
        "_invoke_claude_payload",
        lambda payload: redirected.append("bridge") or OUTPUT,
    )
    assert not hasattr(claude_provider, "_invoke_claude_payload")
    result = ClaudeCLIProvider().run(**run_kwargs)

    assert redirected == []
    assert result["runtime_receipt"]["executed"] is True


@pytest.mark.parametrize(
    ("module_name", "member_name"),
    [
        ("subprocess", "run"),
        ("json", "dumps"),
        ("json", "loads"),
        ("json", "JSONDecodeError"),
        ("hashlib", "sha256"),
    ],
)
def test_post_admission_dependency_substitution_refuses_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_name: str,
    member_name: str,
) -> None:
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    traps: list[str] = []

    def substituted_dependency(*args, **kwargs):
        del args, kwargs
        traps.append(f"{module_name}.{member_name}")
        raise AssertionError("post-admission dependency executed")

    module = getattr(bridge, module_name)
    with monkeypatch.context() as mutation:
        mutation.setattr(module, member_name, substituted_dependency)
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=ledger._test_pre_admission,
            )

    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


def test_in_place_popen_mutation_refuses_on_normal_claude_path_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    traps: list[str] = []

    def substituted_init(*args, **kwargs):
        del args, kwargs
        traps.append("Popen.__init__")
        raise AssertionError("post-admission Popen.__init__ executed")

    with monkeypatch.context() as mutation:
        mutation.setattr(bridge.subprocess.Popen, "__init__", substituted_init)
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            ClaudeCLIProvider().run(
                **_run_kwargs(
                    tmp_path,
                    authorization,
                    execution,
                    authority,
                    ledger,
                )
            )

    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


@pytest.mark.parametrize(
    ("target_name", "member_name"),
    [
        ("JSONEncoder", "encode"),
        ("JSONDecoder", "decode"),
        ("JSONDecodeError", "__init__"),
        ("_default_encoder", "encode"),
        ("_default_decoder", "decode"),
    ],
)
def test_in_place_json_dependency_mutation_refuses_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_name: str,
    member_name: str,
) -> None:
    authorization, execution, _authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    traps: list[str] = []

    def substituted_member(*args, **kwargs):
        del args, kwargs
        traps.append(f"{target_name}.{member_name}")
        raise AssertionError("post-admission JSON dependency executed")

    target = getattr(bridge.json, target_name)
    with monkeypatch.context() as mutation:
        mutation.setattr(target, member_name, substituted_member)
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=ledger._test_pre_admission,
            )

    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


def test_equal_reconstructed_receipt_cannot_bypass_dependency_precheck(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, _authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    reconstructed = ProviderExecutablePreAdmissionReceipt.from_dict(
        ledger._test_pre_admission.to_dict()
    )
    assert reconstructed == ledger._test_pre_admission
    assert reconstructed is not ledger._test_pre_admission
    traps: list[str] = []

    class EncoderTrap:
        def encode(self, value):
            del value
            traps.append("json._default_encoder.encode")
            raise AssertionError("ambient canonical encoder executed")

    with monkeypatch.context() as mutation:
        mutation.setattr(bridge.json, "_default_encoder", EncoderTrap())
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=reconstructed,
            )

    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


@pytest.mark.parametrize("builtin_name", ["dict", "getattr", "type"])
def test_post_admission_verifier_builtin_mutation_refuses_without_calling_trap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    builtin_name: str,
) -> None:
    authorization, execution, _authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    traps: list[str] = []

    def builtin_trap(*args, **kwargs):
        del args, kwargs
        traps.append(builtin_name)
        raise AssertionError(f"ambient builtin {builtin_name} executed")

    original = builtins.__dict__[builtin_name]
    caught = None
    builtins.__dict__[builtin_name] = builtin_trap
    try:
        try:
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=ledger._test_pre_admission,
            )
        except BaseException as exc:
            caught = exc
    finally:
        builtins.__dict__[builtin_name] = original

    assert isinstance(caught, RuntimeProviderBindingMismatch)
    assert "verifier environment changed" in str(caught)
    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


@pytest.mark.parametrize("module_name", ["subprocess", "json", "hashlib"])
def test_post_admission_sys_modules_substitution_refuses_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_name: str,
) -> None:
    authorization, execution, _authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    with monkeypatch.context() as mutation:
        mutation.setitem(sys.modules, module_name, SimpleNamespace())
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=ledger._test_pre_admission,
            )

    assert authorization.effect_ledger.execution_state(execution.execution_id) is None
    assert _lease_rows(tmp_path) == 0


def test_post_admission_importer_substitution_refuses_before_effect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, _authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        subprocess_run=_successful_subprocess_run,
    )
    traps: list[str] = []

    def import_trap(*args, **kwargs):
        del args, kwargs
        traps.append("import")
        raise AssertionError("ambient importer executed")

    with monkeypatch.context() as mutation:
        mutation.setattr(builtins, "__import__", import_trap)
        with pytest.raises(
            RuntimeProviderBindingMismatch,
            match="sealed provider invocation did not authenticate before effect start",
        ):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=execution,
                invocation_authority=ledger._test_invocation_authority,
                invocation_payload=ledger._test_invocation_payload,
                invocation_abi=ledger._test_invocation_abi,
                observation_binding_ledger=ledger,
                executable_registry=ledger._test_executable_registry,
                pre_admission=ledger._test_pre_admission,
            )

    assert traps == []
    assert authorization.effect_ledger.execution_state(execution.execution_id) is None


def test_unbounded_policy_removes_cli_timeout_token_and_path_hint_caps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    objective = "review every supplied documentation file"
    paths = [f"docs/note-{index}.md" for index in range(20)]
    limit_policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        objective=objective,
        paths=paths,
        timeout_s=1,
        execution_limit_policy=limit_policy,
        subprocess_run=_unbounded_subprocess_run,
    )
    result = ClaudeCLIProvider().run(
        **_run_kwargs(
            tmp_path,
            authorization,
            execution,
            authority,
            ledger,
            objective=objective,
            paths=paths,
            timeout_s=1,
            execution_limit_policy=limit_policy,
        )
    )

    assert result["report"]["summary"] == UNBOUNDED_SUMMARY[:600]
    assert (
        result["report"]["handoff"]["unabridged_summary"]
        == UNBOUNDED_SUMMARY
    )
    assert result["execution_limit_policy"] == limit_policy.as_dict()
    assert (
        result["execution_limit_policy_sha256"]
        == limit_policy.fingerprint_sha256
    )


def test_bound_policy_snapshot_cannot_be_swapped_before_cli_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    admitted = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    authorization, execution, authority, ledger = _stack(
        tmp_path,
        monkeypatch,
        timeout_s=1,
        execution_limit_policy=admitted,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: calls.append("spawned"),
    )

    with pytest.raises((ClaudeInvocationBindingMismatch, ClaudeProviderScopeMismatch)):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                authorization,
                execution,
                authority,
                ledger,
                timeout_s=1,
                execution_limit_policy=ExecutionLimitPolicy(),
            )
        )

    assert calls == []


def test_legacy_bridge_name_is_fail_closed_without_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("subprocess"),
    )

    with pytest.raises(ClaudeProviderAuthorizationRequired):
        bridge.ask_claude("review", str(tmp_path), [])

    assert called == []


def test_subprocess_effect_is_private_and_has_one_provider_caller() -> None:
    bridge_path = Path(bridge.__file__).resolve()
    provider_path = Path(claude_provider.__file__).resolve()
    bridge_tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    provider_tree = ast.parse(provider_path.read_text(encoding="utf-8"))

    subprocess_owners: list[str] = []
    for node in ast.walk(bridge_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id in {"subprocess", "local_subprocess"}
                and child.func.attr == "run"
            ):
                subprocess_owners.append(node.name)
    assert subprocess_owners == ["_invoke_claude_payload"]

    private_calls = 0
    for node in ast.walk(provider_tree):
        if not isinstance(node, ast.Call):
            continue
        direct = isinstance(node.func, ast.Name) and node.func.id == "_invoke_claude_payload"
        qualified = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "_invoke_claude_payload"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "claude_cli"
        )
        if direct or qualified:
            private_calls += 1
    assert private_calls == 0


def test_sealed_output_evidence_has_no_envelope_global_dependency() -> None:
    provider_path = Path(claude_provider.__file__).resolve()
    tree = ast.parse(provider_path.read_text(encoding="utf-8"))
    output_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_output_digests"
    )
    imported_modules = {
        alias.name
        for node in ast.walk(output_function)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(output_function)
        if isinstance(node, ast.ImportFrom)
    }
    names = {
        node.id
        for node in ast.walk(output_function)
        if isinstance(node, ast.Name)
    }

    assert imported_modules == {"hashlib", "json"}
    assert not imported_from
    assert "canonical_sha" not in names


def test_noncentral_registry_still_refuses_provider_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    authorization, execution, authority, ledger = _stack(tmp_path, monkeypatch)
    demoted = dataclasses.replace(
        authorization,
        registry=_registry(wiring=Wiring.INVENTORY_ONLY),
    )

    with pytest.raises(RuntimeProviderBindingMismatch, match="not centrally wired"):
        ClaudeCLIProvider().run(
            **_run_kwargs(
                tmp_path,
                demoted,
                execution,
                authority,
                ledger,
            )
            )
    assert _lease_rows(tmp_path) == 0
