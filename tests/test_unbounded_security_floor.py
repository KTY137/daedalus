"""Revision-10 acceptance: uncapped execution never uncaps trust boundaries.

These tests deliberately select the canonical ``unbounded_execution`` mode and
then exercise existing effect, evidence, promotion, scheduling and containment
boundaries.  Resource ceilings may disappear; authority must not.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus import accelerators
from daedalus.config import resolve_write_wave_policy
from daedalus.kairos import gated_writes
from daedalus.kairos.scheduler import Assignment, KairosScheduler
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectLeaseReplay,
    EffectLeaseScopeError,
    EffectLeaseSignatureError,
    issue_effect_lease,
    verify_effect_lease,
)
from daedalus.kernel.sandbox import DockerSandboxPolicy, SandboxPolicyError
from daedalus.limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    LIMIT_AXES,
    MODE_UNBOUNDED_EXECUTION,
    ExecutionLimitPolicy,
    load_from_env,
)
from daedalus.schemas import (
    ContractProvenance,
    EffectScope,
    EvidenceItem,
    EvidencePacket,
    PolicyDecision,
    ResourceUsage,
)
from daedalus.spine.attempt import GateResult, TaskSpec
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.receipts import evaluator_assurance_detail


NOW = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)
REVISION = "a" * 40
LEASE_SECRET = b"revision-10-security-floor-lease-secret"
LEASE_KEY_ID = "revision-10-security-floor-key"
ALLOWED_ENDPOINTS = (
    "https://one.example.test",
    "https://two.example.test",
)
UNLEASED_ENDPOINT = "https://unleased.example.test"


@pytest.fixture
def unbounded_policy(monkeypatch: pytest.MonkeyPatch) -> ExecutionLimitPolicy:
    """Make every test run under the exact owner-selected exceptional mode."""

    policy = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    monkeypatch.setenv(ENV_EXECUTION_LIMIT_POLICY, policy.to_env_value())
    loaded = load_from_env()
    assert loaded == policy
    assert all(not loaded.enforces(axis) for axis in LIMIT_AXES)
    return loaded


def _egress_authority(policy: ExecutionLimitPolicy):
    spec = EntrypointSpec(
        id="python.revision-10-security-egress",
        surface=Surface.PYTHON,
        target="tests.security_floor:egress",
        effects=(Effect.NETWORK_EGRESS,),
        guard_contracts=("provider.egress_policy",),
        wiring=Wiring.CENTRAL,
    )
    scope = EffectScope(
        read_only=True,
        egress_endpoints=ALLOWED_ENDPOINTS,
        max_cost_microusd=None,
        timeout_s=None,
        max_concurrency=None,
        kill_switch_ref="revision-10-security-kill",
    )
    request = EffectLeaseRequest(
        request_id="revision-10-security-request",
        mission_id="revision-10-security-mission",
        attempt_id="revision-10-security-attempt",
        entrypoint_id=spec.id,
        requested_effects=(Effect.NETWORK_EGRESS.value,),
        effect_scope=scope,
        idempotency_namespace="revision-10-security-egress",
        kill_switch_generation=9,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.unbounded-security-floor.request",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            trace_id="revision-10-security-floor",
        ),
    )
    decision = PolicyDecision(
        decision_id="revision-10-security-decision",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="revision-10",
        policy_sha256=policy.fingerprint_sha256,
        verdict="allow",
        reasons=("only the two declared egress endpoints are authorized",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.unbounded-security-floor.policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, policy.fingerprint_sha256),
            trace_id="revision-10-security-floor",
        ),
    )
    lease = issue_effect_lease(
        request,
        decision,
        lease_id="revision-10-security-lease",
        issuer_key_id=LEASE_KEY_ID,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        secret=LEASE_SECRET,
        registry={spec.id: spec},
    )
    return spec, request, decision, lease


def _execution(
    endpoint: str,
    *,
    execution_id: str,
    idempotency_key: str,
) -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        requested_effects=(Effect.NETWORK_EGRESS.value,),
        egress_endpoints=(endpoint,),
        max_cost_microusd=None,
        kill_switch_ref="revision-10-security-kill",
        kill_switch_generation=9,
    )


def _grant(
    path: Path,
    spec: EntrypointSpec,
    request: EffectLeaseRequest,
    decision: PolicyDecision,
    lease,
) -> EffectLeaseLedger:
    ledger = EffectLeaseLedger(path)
    ledger.grant(
        lease,
        request=request,
        policy_decision=decision,
        keyring={LEASE_KEY_ID: LEASE_SECRET},
        current_kill_switch_generation=9,
        granted_at=NOW + timedelta(seconds=1),
        registry={spec.id: spec},
    )
    return ledger


def _begin(
    ledger: EffectLeaseLedger,
    spec: EntrypointSpec,
    request: EffectLeaseRequest,
    decision: PolicyDecision,
    lease,
    execution: EffectExecutionRequest,
    *,
    offset_s: int,
):
    return ledger.begin(
        lease,
        execution,
        request=request,
        policy_decision=decision,
        keyring={LEASE_KEY_ID: LEASE_SECRET},
        guard_decisions=(
            GuardDecision(
                "provider.egress_policy",
                True,
                "exact endpoint allow-list was evaluated",
            ),
        ),
        current_kill_switch_generation=9,
        started_at=NOW + timedelta(seconds=offset_s),
        registry={spec.id: spec},
    )


def test_unbounded_mode_still_refuses_an_unleased_egress_endpoint(
    tmp_path: Path,
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    spec, request, decision, lease = _egress_authority(unbounded_policy)
    assert lease.effect_scope.max_cost_microusd is None
    assert lease.effect_scope.timeout_s is None
    assert lease.effect_scope.max_concurrency is None
    ledger = _grant(tmp_path / "egress.sqlite3", spec, request, decision, lease)

    refused = _execution(
        UNLEASED_ENDPOINT,
        execution_id="revision-10-unleased-egress",
        idempotency_key="revision-10-unleased-egress",
    )
    with pytest.raises(
        EffectLeaseScopeError,
        match="unleased egress endpoint",
    ):
        _begin(
            ledger,
            spec,
            request,
            decision,
            lease,
            refused,
            offset_s=2,
        )
    assert ledger.execution_state(refused.execution_id) is None


def test_unbounded_mode_keeps_signature_authentication_and_replay_refusal(
    tmp_path: Path,
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    spec, request, decision, lease = _egress_authority(unbounded_policy)
    tampered = dataclasses.replace(lease, signature_sha256="0" * 64)
    with pytest.raises(EffectLeaseSignatureError, match="signature"):
        verify_effect_lease(
            tampered,
            request=request,
            policy_decision=decision,
            keyring={LEASE_KEY_ID: LEASE_SECRET},
            current_kill_switch_generation=9,
            now=NOW + timedelta(seconds=1),
            registry={spec.id: spec},
        )
    ledger = _grant(tmp_path / "replay.sqlite3", spec, request, decision, lease)
    first = _execution(
        ALLOWED_ENDPOINTS[0],
        execution_id="revision-10-first-egress",
        idempotency_key="revision-10-one-use-key",
    )
    assert _begin(
        ledger,
        spec,
        request,
        decision,
        lease,
        first,
        offset_s=2,
    ).execute

    substituted = _execution(
        ALLOWED_ENDPOINTS[1],
        execution_id="revision-10-substituted-egress",
        idempotency_key=first.idempotency_key,
    )
    with pytest.raises(EffectLeaseReplay, match="different lease or scope"):
        _begin(
            ledger,
            spec,
            request,
            decision,
            lease,
            substituted,
            offset_s=3,
        )
    assert ledger.execution_state(substituted.execution_id) is None


def test_unbounded_mode_keeps_secret_redaction_in_runtime_status(
    monkeypatch: pytest.MonkeyPatch,
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    password = "revision-10-password"
    token = "revision-10-bearer-token"
    query_secret = "revision-10-query-secret"
    monkeypatch.setenv(
        accelerators.RTX_OLLAMA_ENV,
        f"https://operator:{password}@example.test:11434/private?token={query_secret}",
    )
    monkeypatch.setenv(accelerators.RTX_TOKEN_ENV, token)

    report = accelerators._remote_rtx_status(probe=False)
    encoded = json.dumps(report, sort_keys=True)

    assert unbounded_policy.mode == MODE_UNBOUNDED_EXECUTION
    assert report["endpoint"] == "https://example.test:11434"
    for secret in (password, token, query_secret, "operator", "private"):
        assert secret not in encoded


def test_unbounded_mode_keeps_evaluator_isolation_and_the_evidence_gate(
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    task = TaskSpec(
        task_id="revision-10-evaluator-isolation",
        instruction="attempt to influence the evaluator",
        base_revision=REVISION,
        target_paths=("tests/conftest.py",),
        gate_criterion_paths=("tests/test_gate.py",),
    )
    result = SimpleNamespace(
        gates=GateResult(
            passed=True,
            name="candidate-gate",
            command=("pytest", "tests/test_gate.py"),
            returncode=0,
            output="candidate claims green",
        )
    )
    assurance, reason = evaluator_assurance_detail(
        result,
        task,
        criterion_present={"tests/test_gate.py": True},
        criterion_imports={"tests/test_gate.py": ()},
    )

    assert assurance == "unverified"
    assert "execution-influencing file" in reason

    output_sha = "1" * 64
    item = EvidenceItem(
        evidence_id="revision-10-untrusted-evaluator",
        evaluator="candidate-influenced-evaluator",
        assurance=assurance,
        verdict="passed",
        output_sha256=output_sha,
        evidence_locator=f"artifact-locator:sha256:{output_sha}",
        collected_at=NOW.isoformat(),
        provenance=ContractProvenance(
            origin="tests.unbounded-security-floor.evaluator",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(output_sha,),
        ),
        details={"reason": reason},
    )
    with pytest.raises(
        ValueError,
        match="conclusive packet cannot rely on unverified evidence",
    ):
        EvidencePacket(
            packet_id="revision-10-forged-green-packet",
            mission_id="revision-10-security-mission",
            attempt_id="revision-10-security-attempt",
            source_revision=REVISION,
            attempt_contract_sha256="2" * 64,
            subject_sha256="3" * 64,
            evaluation_status="passed",
            items=(item,),
            policy_decision_sha256="4" * 64,
            usage=ResourceUsage(wall_time_ms=1),
            provenance=ContractProvenance(
                origin="tests.unbounded-security-floor.packet",
                source_revision=REVISION,
                created_at=NOW.isoformat(),
                input_digests=(
                    output_sha,
                    "2" * 64,
                    "3" * 64,
                    "4" * 64,
                    unbounded_policy.fingerprint_sha256,
                ),
            ),
            candidate_artifact_sha256="3" * 64,
            candidate_artifact_locator="artifact-locator:sha256:" + "3" * 64,
            execution_limit_policy=unbounded_policy,
            execution_limit_policy_sha256=unbounded_policy.fingerprint_sha256,
        )


def test_unbounded_mode_does_not_enable_automatic_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    assert resolve_write_wave_policy({"write_wave_policy": "always"}) == "never"
    reached: list[str] = []

    def forbidden(*_args, **_kwargs):
        reached.append("effect")
        raise AssertionError("promotion infrastructure must not be reached")

    monkeypatch.setattr(gated_writes, "GitWorktreeManager", forbidden)
    monkeypatch.setattr(gated_writes, "_PromotionLock", forbidden)

    report = gated_writes.promote_candidates(
        str(tmp_path),
        [],
        project=None,
        availability={},
        consumed_approval=None,
        evidence_packet=None,
        target_ref="main",
    )

    assert unbounded_policy.mode == MODE_UNBOUNDED_EXECUTION
    assert reached == []
    assert report["promoted"] == []
    assert report["integration_branch"] is None
    assert report["authorization"] is None
    assert "persisted ApprovalLedger and owner keyring are mandatory" in (
        report["refused"][0]["reason"]
    )


def test_unbounded_mode_neither_parallelizes_shared_writes_nor_weakens_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unbounded_policy: ExecutionLimitPolicy,
) -> None:
    assignments = [
        Assignment(
            objective=f"write task {index}",
            paths=["src/shared.py"],
            owner="owner",
            lane="ollama",
            worker=f"worker-{index}",
            mode="write",
            accepted=True,
            reason="test assignment",
        )
        for index in range(2)
    ]
    scheduler = KairosScheduler(max_workers=8)
    monkeypatch.setattr(
        scheduler,
        "accept",
        lambda tasks, repo_root=None: assignments,
    )

    state = {"active": 0, "max_active": 0}
    lock = threading.Lock()

    def fake_offload(_objective, _root, paths, **_kwargs):
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.04)
        with lock:
            state["active"] -= 1
        return {"action": "offloaded", "wrote": list(paths)}

    monkeypatch.setattr("daedalus.offload.offload", fake_offload)
    rows = scheduler.dispatch(
        str(tmp_path),
        [{"objective": row.objective, "paths": row.paths} for row in assignments],
        dry_run=False,
        parallel=True,
        effect_authorization=object(),
        effect_executions={0: object(), 1: object()},
    )

    assert unbounded_policy.mode == MODE_UNBOUNDED_EXECUTION
    assert state["max_active"] == 1
    assert any(
        row.get("status") == "note"
        and row.get("objective") == "parallel disabled"
        for row in rows
    )

    workspace = tmp_path / "candidate"
    workspace.mkdir()
    with pytest.raises(SandboxPolicyError, match="proxy network"):
        DockerSandboxPolicy(
            image="daedalus-attempt@sha256:" + "5" * 64,
            candidate_workspace=workspace,
            network="host",
        )
