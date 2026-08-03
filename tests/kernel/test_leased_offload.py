from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from daedalus import metrics
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectReconciliationRequired,
    LeasedEffectAuthorization,
    issue_effect_lease,
)
from daedalus.kernel.reconciliation import issue_effect_reconciliation_decision
from daedalus.offload import offload
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import REGISTRY_BY_ID, GuardDecision
from daedalus.spine.envelope import canonical_sha

REVISION = "a" * 40
SECRET = b"leased-offload-test-secret-material-32-bytes"
OPERATOR_SECRET = b"leased-offload-operator-secret-material-32-bytes"
POLICY_SHA = "b" * 64
RUNTIME_MANIFEST_SHA = "c" * 64
RUNTIME_CONFORMANCE_SHA = "d" * 64


def authorization(tmp_path, *, suffix: str = "1"):
    now = datetime.now(timezone.utc)
    spec = REGISTRY_BY_ID["python.offload"]
    effects = tuple(sorted(effect.value for effect in spec.effects))
    scope = EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        egress_endpoints=("https://provider.example.test",),
        tools=("python",),
        max_cost_microusd=1000,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="global-kill",
    )
    request = EffectLeaseRequest(
        request_id=f"offload-request-{suffix}",
        mission_id="mission-1",
        attempt_id=f"attempt-{suffix}",
        entrypoint_id=spec.id,
        requested_effects=effects,
        effect_scope=scope,
        idempotency_namespace=f"mission-1-attempt-{suffix}",
        kill_switch_generation=3,
        runtime_manifest_sha256=RUNTIME_MANIFEST_SHA,
        runtime_conformance_sha256=RUNTIME_CONFORMANCE_SHA,
        provenance=ContractProvenance(
            origin="tests.leased-offload",
            source_revision=REVISION,
            created_at=now.isoformat(),
            input_digests=(RUNTIME_MANIFEST_SHA, RUNTIME_CONFORMANCE_SHA),
            trace_id="mission-1",
        ),
    )
    policy = PolicyDecision(
        decision_id=f"policy-{suffix}",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-02",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded leased offload",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.leased-offload-policy",
            source_revision=REVISION,
            created_at=now.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id=f"offload-lease-{suffix}",
        issuer_key_id="kernel-key",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        secret=SECRET,
    )
    ledger = EffectLeaseLedger(tmp_path / f"leases-{suffix}.sqlite3")
    ledger.grant(
        lease,
        request=request,
        policy_decision=policy,
        keyring={"kernel-key": SECRET},
        current_kill_switch_generation=3,
        granted_at=now,
    )
    auth = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        keyring={"kernel-key": SECRET},
        guard_decisions=tuple(
            GuardDecision(
                contract,
                True,
                "artifact-locator:sha256:" + (str(index + 1) * 64)[:64],
            )
            for index, contract in enumerate(spec.guard_contracts)
        ),
        current_kill_switch_generation=3,
    )
    execution = EffectExecutionRequest(
        execution_id=f"offload-execution-{suffix}",
        idempotency_key=f"offload-idempotency-{suffix}",
        requested_effects=effects,
        writable_paths=("workspace",),
        egress_endpoints=("https://provider.example.test",),
        tools=("python",),
        max_cost_microusd=1000,
        kill_switch_ref="global-kill",
        kill_switch_generation=3,
    )
    return auth, execution, ledger


def test_live_offload_refuses_before_any_impl_without_lease(tmp_path) -> None:
    with mock.patch("daedalus.offload._offload_impl") as impl:
        result = offload("change code", str(tmp_path), live=True)
    impl.assert_not_called()
    assert result["action"] == "effect_lease_required"
    assert result["wrote"] == []


@pytest.mark.parametrize(
    ("availability", "expected_action"),
    (
        (
            {
                "claude_cli": True,
                "ollama": True,
                "deepseek": False,
                "codex_cli": False,
            },
            "would_offload",
        ),
        (
            {
                "claude_cli": True,
                "ollama": False,
                "deepseek": False,
                "codex_cli": False,
            },
            "escalate_to_claude",
        ),
    ),
)
def test_dry_plan_is_filesystem_inert(
    tmp_path, monkeypatch, availability, expected_action
) -> None:
    """Both planning branches must leave no hidden metrics effect behind."""

    metrics_path = tmp_path / "missing" / "offload-metrics.jsonl"
    monkeypatch.setattr(metrics, "LOG", metrics_path)

    result = offload(
        "Draft docstrings for the helper",
        str(tmp_path),
        paths=["docs/helper.md"],
        live=False,
        availability=availability,
    )

    assert result["action"] == expected_action
    assert not metrics_path.exists()
    assert not metrics_path.parent.exists()


def test_valid_lease_executes_once_finishes_and_replay_is_inert(tmp_path) -> None:
    auth, execution, ledger = authorization(tmp_path)
    with mock.patch(
        "daedalus.offload._offload_impl",
        return_value={"action": "offloaded", "wrote": []},
    ) as impl:
        first = offload(
            "review code",
            str(tmp_path),
            live=True,
            effect_authorization=auth,
            effect_execution=execution,
        )
        second = offload(
            "review code",
            str(tmp_path),
            live=True,
            effect_authorization=auth,
            effect_execution=execution,
        )

    assert impl.call_count == 1
    assert first["effect_start_receipt"]["execution_id"] == execution.execution_id
    assert first["effect_terminal_receipt"]["outcome"] == "COMPLETED"
    assert ledger.execution_state(execution.execution_id) == "COMPLETED"
    assert second["action"] == "effect_replay"
    assert second["wrote"] == []


def test_wrong_effect_set_is_refused_before_persisted_start(tmp_path) -> None:
    auth, execution, ledger = authorization(tmp_path)
    narrowed = EffectExecutionRequest(
        execution_id="offload-execution-narrow",
        idempotency_key="offload-idempotency-narrow",
        requested_effects=("network_egress",),
        egress_endpoints=("https://provider.example.test",),
        kill_switch_ref="global-kill",
        kill_switch_generation=3,
    )
    with mock.patch("daedalus.offload._offload_impl") as impl:
        result = offload(
            "review code",
            str(tmp_path),
            live=True,
            effect_authorization=auth,
            effect_execution=narrowed,
        )
    impl.assert_not_called()
    assert result["action"] == "effect_lease_refused"
    assert ledger.execution_state(narrowed.execution_id) is None


def test_exception_is_recorded_failed_before_it_escapes(tmp_path) -> None:
    auth, execution, ledger = authorization(tmp_path, suffix="failed")
    with mock.patch(
        "daedalus.offload._offload_impl", side_effect=RuntimeError("provider exploded")
    ):
        with pytest.raises(RuntimeError, match="provider exploded"):
            offload(
                "review code",
                str(tmp_path),
                live=True,
                effect_authorization=auth,
                effect_execution=execution,
            )
    assert ledger.execution_state(execution.execution_id) == "FAILED"


def test_interrupt_is_recorded_cancelled_before_it_escapes(tmp_path) -> None:
    auth, execution, ledger = authorization(tmp_path, suffix="cancelled")
    with mock.patch(
        "daedalus.offload._offload_impl", side_effect=KeyboardInterrupt()
    ):
        with pytest.raises(KeyboardInterrupt):
            offload(
                "review code",
                str(tmp_path),
                live=True,
                effect_authorization=auth,
                effect_execution=execution,
            )
    assert ledger.execution_state(execution.execution_id) == "CANCELLED"


def test_noncanonical_provider_output_is_failed_and_cannot_replay(tmp_path) -> None:
    auth, execution, ledger = authorization(tmp_path, suffix="noncanonical")
    provider_ran = []

    def completed_external_effect(*_args, **_kwargs):
        provider_ran.append(execution.execution_id)
        return {"action": "offloaded", "opaque": object()}

    with mock.patch(
        "daedalus.offload._offload_impl", side_effect=completed_external_effect
    ) as impl:
        with pytest.raises(ValueError, match="JSON-serialisable"):
            offload(
                "review code",
                str(tmp_path),
                live=True,
                effect_authorization=auth,
                effect_execution=execution,
            )
        replay = offload(
            "review code",
            str(tmp_path),
            live=True,
            effect_authorization=auth,
            effect_execution=execution,
        )

    assert provider_ran == [execution.execution_id]
    assert impl.call_count == 1
    assert ledger.execution_state(execution.execution_id) == "FAILED"
    assert replay["action"] == "effect_replay"


def test_terminal_write_failure_requires_reconciliation_and_replay_is_inert(
    tmp_path,
) -> None:
    auth, execution, ledger = authorization(tmp_path, suffix="terminal-write")
    provider_ran = []

    def completed_external_effect(*_args, **_kwargs):
        provider_ran.append(execution.execution_id)
        return {"action": "offloaded", "wrote": []}

    with mock.patch(
        "daedalus.offload._offload_impl", side_effect=completed_external_effect
    ) as impl, mock.patch.object(
        ledger, "finish_receipt", side_effect=OSError("terminal store unavailable")
    ):
        with pytest.raises(EffectReconciliationRequired) as caught:
            offload(
                "review code",
                str(tmp_path),
                live=True,
                effect_authorization=auth,
                effect_execution=execution,
            )

    assert caught.value.execution_id == execution.execution_id
    assert caught.value.phase == "completed-terminal-write"
    pending = caught.value.pending_terminal_receipt
    assert pending.execution_id == execution.execution_id
    assert pending.outcome == "COMPLETED"
    assert pending.output_digests
    assert caught.value.execution_request_sha256 == execution.digest
    assert caught.value.to_dict()["pending_terminal_receipt"] == pending.to_dict()
    assert "capability" not in str(caught.value.to_dict()).lower()
    assert ledger.execution_state(execution.execution_id) == "STARTED"
    with pytest.raises(TypeError, match="authorization"):
        ledger.finish_receipt(pending)

    decision_at = datetime.now(timezone.utc)
    evidence_sha256 = canonical_sha(caught.value.to_dict())
    operator_decision = issue_effect_reconciliation_decision(
        pending,
        execution_request_sha256=caught.value.execution_request_sha256,
        evidence_sha256=evidence_sha256,
        decision_id="offload-terminal-reconciliation",
        operator_id="operator-1",
        key_id="operator-key-1",
        nonce="offload-terminal-nonce",
        issued_at=decision_at.isoformat(),
        expires_at=(decision_at + timedelta(minutes=5)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.leased-offload-reconciliation",
            source_revision=auth.lease.provenance.source_revision,
            created_at=decision_at.isoformat(),
            input_digests=(
                auth.lease.digest,
                execution.digest,
                pending.start_receipt_sha256,
                pending.receipt_sha256,
                evidence_sha256,
            ),
            trace_id=auth.request.mission_id,
        ),
        secret=OPERATOR_SECRET,
    )
    reconciled = EffectLeaseLedger(ledger.path).reconcile(
        pending,
        operator_decision,
        historical_keyring=auth.keyring,
        operator_keyring={("operator-1", "operator-key-1"): OPERATOR_SECRET},
        now=decision_at + timedelta(seconds=1),
    )
    assert reconciled.applied is True
    assert reconciled.terminal_receipt == pending
    assert ledger.execution_state(execution.execution_id) == "COMPLETED"

    with mock.patch("daedalus.offload._offload_impl") as replay_impl:
        replay = offload(
            "review code",
            str(tmp_path),
            live=True,
            effect_authorization=auth,
            effect_execution=execution,
        )

    assert provider_ran == [execution.execution_id]
    assert impl.call_count == 1
    replay_impl.assert_not_called()
    assert replay["action"] == "effect_replay"
    assert replay["effect_start_receipt"]["execution_id"] == execution.execution_id
