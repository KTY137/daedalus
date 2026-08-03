from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import daedalus.kernel.attempts as leased_attempts
from daedalus.kernel import (
    EffectLeaseBindingMismatch,
    EffectLeaseLedger,
    EffectLeaseStateError,
    issue_effect_lease,
)
from daedalus.kernel.attempts import LeasedAttemptBindingError
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.schemas import (
    AttemptContract,
    ContractProvenance,
    EffectScope,
    PolicyDecision,
    ResourceBudget,
)
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    STATE_CANCELLED,
    STATE_CLEAN,
    TaskSpec,
)
from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    REGISTRY_BY_ID,
    Effect,
    GuardDecision,
    Wiring,
)

REVISION = "a" * 40
MANIFEST_SHA = "b" * 64
CONFORMANCE_SHA = "c" * 64
POLICY_SHA = "d" * 64
SECRET = b"leased-attempt-issuer-secret-material-32-bytes"
NOW = datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc)


def provenance(*inputs: str) -> ContractProvenance:
    return ContractProvenance(
        origin="tests.leased-attempt",
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        input_digests=tuple(inputs),
        trace_id="mission-leased-attempt",
    )


def task() -> TaskSpec:
    return TaskSpec(
        task_id="work-1",
        instruction="Change src/value.py without touching the primary checkout.",
        base_revision=REVISION,
        target_paths=("src/value.py",),
        gate_paths=("tests/test_value.py",),
    )


def request() -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="lease-request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id=leased_attempts.LEASED_ATTEMPT_ENTRYPOINT,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.REPOSITORY_MUTATION.value,
        ),
        effect_scope=EffectScope(
            read_only=False,
            writable_paths=("src/value.py",),
            tools=("git", "python"),
            max_cost_microusd=0,
            max_concurrency=1,
            timeout_s=60,
            kill_switch_ref="mission-1-kill",
        ),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=4,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=CONFORMANCE_SHA,
        provenance=provenance(MANIFEST_SHA, CONFORMANCE_SHA),
    )


def policy(req: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="policy-1",
        subject_id=req.request_id,
        subject_sha256=req.digest,
        policy_version="2026-08-03",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("isolated bounded candidate attempt",),
        effect_scope=req.effect_scope,
        provenance=provenance(req.digest, POLICY_SHA),
    )


def attempt(selected_task: TaskSpec, selected_policy: PolicyDecision) -> AttemptContract:
    return AttemptContract.from_task_spec(
        selected_task,
        attempt_id="attempt-1",
        mission_id="mission-1",
        runtime_manifest_sha256=MANIFEST_SHA,
        policy_decision_sha256=selected_policy.digest,
        budget=ResourceBudget(
            max_tokens=1000,
            max_cost_microusd=0,
            max_wall_time_s=60,
            max_attempts=1,
        ),
        provenance=provenance(
            selected_task.digest,
            MANIFEST_SHA,
            selected_policy.digest,
        ),
    )


def guards() -> tuple[GuardDecision, ...]:
    return (
        GuardDecision(
            "containment.attempt",
            True,
            "artifact-locator:sha256:" + "e" * 64,
        ),
        GuardDecision(
            "spine.intent_ledger",
            True,
            "artifact-locator:sha256:" + "f" * 64,
        ),
    )


def clean_result(selected_task: TaskSpec) -> AttemptResult:
    diff = b"diff --git a/src/value.py b/src/value.py\n"
    artifact = PatchArtifact(
        task_id=selected_task.task_id,
        branch="daedalus-attempt-work-1",
        base_revision=REVISION,
        diff_bytes=diff,
        diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("src/value.py",),
        created_ts=(NOW + timedelta(seconds=1)).isoformat(),
    )
    gate = GateResult(
        passed=True,
        name="pytest",
        command=("python", "-m", "pytest"),
        returncode=0,
        output="1 passed",
        duration_s=0.1,
    )
    return AttemptResult(
        state=STATE_CLEAN,
        task_id=selected_task.task_id,
        started_ts=NOW.isoformat(),
        finished_ts=(NOW + timedelta(seconds=1)).isoformat(),
        duration_s=1.0,
        effect_key="daedalus-attempt-work-1",
        branch="daedalus-attempt-work-1",
        base_revision=REVISION,
        artifact=artifact,
        gates=gate,
        worktree_removed=True,
        artifact_locator={
            "uri": f"sha256:{artifact.diff_sha256}",
            "locator_uri": "artifact-locator:sha256:" + "9" * 64,
        },
    )


def setup_lease(tmp_path):
    selected_task = task()
    req = request()
    selected_policy = policy(req)
    selected_attempt = attempt(selected_task, selected_policy)
    value = issue_effect_lease(
        req,
        selected_policy,
        lease_id="lease-1",
        issuer_key_id="kernel-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
        registry=REGISTRY_BY_ID,
    )
    ledger = EffectLeaseLedger(tmp_path / "effect-leases.sqlite3")
    ledger.grant(
        value,
        request=req,
        policy_decision=selected_policy,
        keyring={"kernel-key-1": SECRET},
        current_kill_switch_generation=4,
        granted_at=NOW + timedelta(milliseconds=1),
        registry=REGISTRY_BY_ID,
    )
    return selected_task, req, selected_policy, selected_attempt, value, ledger


def execute(
    tmp_path,
    monkeypatch,
    *,
    selected_task,
    req,
    selected_policy,
    selected_attempt,
    lease,
    effect_ledger,
    fake_result=None,
    calls=None,
):
    result = fake_result or clean_result(selected_task)
    call_log = calls if calls is not None else []

    def fake_run_attempt(*args, **kwargs):
        call_log.append((args, kwargs))
        return result

    monkeypatch.setattr(leased_attempts, "run_attempt", fake_run_attempt)
    output = leased_attempts.run_leased_attempt(
        selected_task,
        attempt=selected_attempt,
        lease_request=req,
        policy_decision=selected_policy,
        lease=lease,
        effect_ledger=effect_ledger,
        keyring={"kernel-key-1": SECRET},
        guard_decisions=guards(),
        current_kill_switch_generation=4,
        runner=lambda _ctx: None,
        artifact_dir=tmp_path / "cas",
        repo_root=tmp_path / "repo",
        started_at=NOW + timedelta(seconds=1),
        finished_at=NOW + timedelta(seconds=2),
        registry=REGISTRY_BY_ID,
    )
    return output, call_log


def test_registry_has_one_central_leased_attempt_without_upgrading_legacy() -> None:
    row = REGISTRY_BY_ID[leased_attempts.LEASED_ATTEMPT_ENTRYPOINT]
    assert row.target == "daedalus.kernel.attempts:run_leased_attempt"
    assert row.wiring is Wiring.CENTRAL
    assert row.runtime_id == "isolated_attempt"
    assert set(row.guard_contracts) == {
        "containment.attempt",
        "spine.intent_ledger",
    }
    assert REGISTRY_BY_ID["python.attempt"].wiring is Wiring.LOCAL_GUARDS
    assert len([item for item in ENTRYPOINTS if item.id == row.id]) == 1


def test_first_start_persists_and_exact_replay_never_runs_again(
    tmp_path, monkeypatch
) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    calls = []
    first, calls = execute(
        tmp_path,
        monkeypatch,
        selected_task=selected_task,
        req=req,
        selected_policy=selected_policy,
        selected_attempt=selected_attempt,
        lease=lease,
        effect_ledger=ledger,
        calls=calls,
    )
    second, calls = execute(
        tmp_path,
        monkeypatch,
        selected_task=selected_task,
        req=req,
        selected_policy=selected_policy,
        selected_attempt=selected_attempt,
        lease=lease,
        effect_ledger=ledger,
        calls=calls,
    )

    assert first.execute is True
    assert first.attempt is not None
    assert first.terminal_receipt is not None
    assert first.terminal_receipt.outcome == "COMPLETED"
    assert second.execute is False
    assert second.attempt is None
    assert second.start_receipt == first.start_receipt
    assert second.terminal_receipt == first.terminal_receipt
    assert len(calls) == 1
    assert ledger.execution_state("attempt-1:run") == "COMPLETED"


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("task_digest", "task_sha256"),
        ("base_revision", "base_revision"),
        ("mission", "mission_id"),
        ("runtime", "runtime_manifest_sha256"),
        ("conformance", "runtime_conformance"),
    ],
)
def test_contract_and_stale_revision_mutations_refuse_before_execution(
    tmp_path, monkeypatch, mutation, expected
) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    if mutation == "task_digest":
        selected_task = dataclasses.replace(
            selected_task, instruction="A different task with a different digest."
        )
    elif mutation == "base_revision":
        selected_task = dataclasses.replace(selected_task, base_revision="2" * 40)
    elif mutation == "mission":
        selected_attempt = dataclasses.replace(
            selected_attempt, mission_id="mission-other"
        )
    elif mutation == "runtime":
        selected_attempt = dataclasses.replace(
            selected_attempt,
            runtime_manifest_sha256="3" * 64,
            provenance=provenance(
                selected_task.digest,
                "3" * 64,
                selected_policy.digest,
            ),
        )
    elif mutation == "conformance":
        req = dataclasses.replace(
            req,
            runtime_conformance_sha256="4" * 64,
            provenance=provenance(MANIFEST_SHA, "4" * 64),
        )
        selected_policy = policy(req)
        selected_attempt = attempt(selected_task, selected_policy)

    called = []
    monkeypatch.setattr(
        leased_attempts,
        "run_attempt",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )
    with pytest.raises(LeasedAttemptBindingError, match=expected):
        leased_attempts.run_leased_attempt(
            selected_task,
            attempt=selected_attempt,
            lease_request=req,
            policy_decision=selected_policy,
            lease=lease,
            effect_ledger=ledger,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=4,
            runner=lambda _ctx: None,
            artifact_dir=tmp_path / "cas",
            registry=REGISTRY_BY_ID,
        )
    assert not called
    assert ledger.execution_state("attempt-1:run") is None


def test_changed_registry_and_scope_escape_fail_closed(tmp_path) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    changed = dict(REGISTRY_BY_ID)
    changed_row = dataclasses.replace(
        changed[leased_attempts.LEASED_ATTEMPT_ENTRYPOINT],
        notes="changed after lease issue",
    )
    changed[changed_row.id] = changed_row
    with pytest.raises(EffectLeaseBindingMismatch, match="registry changed"):
        leased_attempts.run_leased_attempt(
            selected_task,
            attempt=selected_attempt,
            lease_request=req,
            policy_decision=selected_policy,
            lease=lease,
            effect_ledger=ledger,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=4,
            runner=lambda _ctx: None,
            artifact_dir=tmp_path / "cas",
            registry=changed,
        )

    escaped_task = dataclasses.replace(
        selected_task, target_paths=("src/value.py", "../outside")
    )
    with pytest.raises((ValueError, LeasedAttemptBindingError)):
        leased_attempts.run_leased_attempt(
            escaped_task,
            attempt=selected_attempt,
            lease_request=req,
            policy_decision=selected_policy,
            lease=lease,
            effect_ledger=ledger,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=4,
            runner=lambda _ctx: None,
            artifact_dir=tmp_path / "cas",
            registry=REGISTRY_BY_ID,
        )


def test_unbound_cas_locator_and_changed_path_end_in_failed_terminal(
    tmp_path, monkeypatch
) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    bad = clean_result(selected_task)
    assert bad.artifact is not None
    bad = dataclasses.replace(
        bad,
        artifact=dataclasses.replace(bad.artifact, changed_paths=("src/other.py",)),
        artifact_locator={
            "uri": "sha256:" + "0" * 64,
            "locator_uri": "artifact-locator:sha256:" + "9" * 64,
        },
    )
    output, calls = execute(
        tmp_path,
        monkeypatch,
        selected_task=selected_task,
        req=req,
        selected_policy=selected_policy,
        selected_attempt=selected_attempt,
        lease=lease,
        effect_ledger=ledger,
        fake_result=bad,
    )
    assert len(calls) == 1
    assert output.execute is True
    assert output.attempt is None
    assert output.error is not None
    assert "artifact.changed_paths" in output.error
    assert output.terminal_receipt is not None
    assert output.terminal_receipt.outcome == "FAILED"


def test_cancelled_attempt_is_terminal_and_not_success(tmp_path, monkeypatch) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    cancelled = dataclasses.replace(
        clean_result(selected_task),
        state=STATE_CANCELLED,
        artifact=None,
        gates=None,
        artifact_locator=None,
        error="cancelled",
    )
    output, _calls = execute(
        tmp_path,
        monkeypatch,
        selected_task=selected_task,
        req=req,
        selected_policy=selected_policy,
        selected_attempt=selected_attempt,
        lease=lease,
        effect_ledger=ledger,
        fake_result=cancelled,
    )
    assert output.error is None
    assert output.attempt == cancelled
    assert output.terminal_receipt is not None
    assert output.terminal_receipt.outcome == "CANCELLED"


def test_corrupt_persisted_terminal_receipt_is_refused_on_replay(
    tmp_path, monkeypatch
) -> None:
    selected_task, req, selected_policy, selected_attempt, lease, ledger = setup_lease(
        tmp_path
    )
    first, _calls = execute(
        tmp_path,
        monkeypatch,
        selected_task=selected_task,
        req=req,
        selected_policy=selected_policy,
        selected_attempt=selected_attempt,
        lease=lease,
        effect_ledger=ledger,
    )
    assert first.terminal_receipt is not None
    with sqlite3.connect(ledger.path) as conn:
        conn.execute(
            "UPDATE effect_executions SET terminal_receipt_json=? WHERE execution_id=?",
            ('{"corrupt":true}', "attempt-1:run"),
        )
    with pytest.raises(EffectLeaseStateError, match="terminal receipt"):
        execute(
            tmp_path,
            monkeypatch,
            selected_task=selected_task,
            req=req,
            selected_policy=selected_policy,
            selected_attempt=selected_attempt,
            lease=lease,
            effect_ledger=ledger,
        )
