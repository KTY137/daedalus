from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseConcurrencyError,
    EffectLeaseExpired,
    EffectLeaseLedger,
    EffectLeaseReplay,
    EffectLeaseScopeError,
    EffectLeaseSignatureError,
    EffectLeaseStateError,
    issue_effect_lease,
    verify_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EffectStartRefused,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.ledger import SpineLedger
from daedalus.spine.envelope import canonical_json, canonical_sha

REVISION = "a" * 40
POLICY_SHA = "b" * 64
SECRET = b"effect-lease-kernel-secret-material-32-bytes-minimum"
NOW = datetime(2026, 8, 1, 21, 0, tzinfo=timezone.utc)


def central_spec(*, runtime_id: str = "") -> EntrypointSpec:
    return EntrypointSpec(
        id="python.central-attempt",
        surface=Surface.PYTHON,
        target="tests.fake:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id=runtime_id,
    )


def registry(*, runtime_id: str = ""):
    spec = central_spec(runtime_id=runtime_id)
    return {spec.id: spec}


def scope(*, max_concurrency: int = 1) -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("python",),
        max_cost_microusd=100,
        max_concurrency=max_concurrency,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )


def request(*, effect_scope: EffectScope | None = None, runtime: bool = False) -> EffectLeaseRequest:
    runtime_manifest = "c" * 64 if runtime else None
    runtime_conformance = "d" * 64 if runtime else None
    inputs = tuple(x for x in (runtime_manifest, runtime_conformance) if x)
    return EffectLeaseRequest(
        request_id="lease-request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id="python.central-attempt",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=effect_scope or scope(),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=7,
        runtime_manifest_sha256=runtime_manifest,
        runtime_conformance_sha256=runtime_conformance,
        provenance=ContractProvenance(
            origin="tests.effect-lease-request",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=inputs,
            trace_id="mission-1",
        ),
    )


def decision(req: EffectLeaseRequest, *, verdict: str = "allow", effect_scope: EffectScope | None = None) -> PolicyDecision:
    chosen_scope = effect_scope if effect_scope is not None else req.effect_scope
    return PolicyDecision(
        decision_id="policy-decision-1",
        subject_id=req.request_id,
        subject_sha256=req.digest,
        policy_version="2026-08-01",
        policy_sha256=POLICY_SHA,
        verdict=verdict,
        reasons=("bounded central effect",),
        effect_scope=chosen_scope,
        provenance=ContractProvenance(
            origin="tests.effect-lease-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(req.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )


def lease(*, req: EffectLeaseRequest | None = None, policy: PolicyDecision | None = None, reg=None):
    req = req or request()
    policy = policy or decision(req)
    return issue_effect_lease(
        req,
        policy,
        lease_id="lease-1",
        issuer_key_id="kernel-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
        registry=registry() if reg is None else reg,
    )


def execution(*, execution_id: str = "execution-1", idempotency_key: str = "idem-1", path: str = "workspace/out.txt"):
    return EffectExecutionRequest(
        execution_id=execution_id,
        idempotency_key=idempotency_key,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        writable_paths=(path,),
        tools=("python",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )


def guards():
    return (GuardDecision("budget.process_guard", True, "artifact-locator:sha256:" + "e" * 64),)



def grant(ledger: EffectLeaseLedger, lease_value: EffectLease, req: EffectLeaseRequest, policy: PolicyDecision, reg=None, granted_at=None):
    return ledger.grant(
        lease_value,
        request=req,
        policy_decision=policy,
        keyring={"kernel-key-1": SECRET},
        current_kill_switch_generation=7,
        granted_at=granted_at or (NOW + timedelta(milliseconds=500)),
        registry=registry() if reg is None else reg,
    )

def begin(ledger: EffectLeaseLedger, lease_value: EffectLease, req: EffectLeaseRequest, policy: PolicyDecision, execution_value=None, reg=None, started_at=None):
    return ledger.begin(
        lease_value,
        execution_value or execution(),
        request=req,
        policy_decision=policy,
        keyring={"kernel-key-1": SECRET},
        guard_decisions=guards(),
        current_kill_switch_generation=7,
        started_at=started_at or (NOW + timedelta(seconds=1)),
        registry=registry() if reg is None else reg,
    )


def test_contract_round_trip_signature_and_exact_bindings() -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    assert EffectLease.from_dict(value.to_dict()) == value
    assert value.signature_sha256 != "0" * 64
    verify_effect_lease(
        value,
        request=req,
        policy_decision=policy,
        keyring={"kernel-key-1": SECRET},
        current_kill_switch_generation=7,
        now=NOW + timedelta(seconds=1),
        registry=registry(),
    )


def test_execution_plan_binding_is_explicit_and_legacy_wire_stays_stable() -> None:
    plan_sha = "f" * 64
    legacy = request()
    legacy_execution = execution()
    assert "execution_plan_sha256" not in legacy.to_dict()
    assert "execution_plan_sha256" not in legacy_execution.to_dict()

    with pytest.raises(ValueError, match="provenance"):
        dataclasses.replace(legacy, execution_plan_sha256=plan_sha)

    planned = dataclasses.replace(
        legacy,
        execution_plan_sha256=plan_sha,
        provenance=dataclasses.replace(
            legacy.provenance,
            input_digests=(*legacy.provenance.input_digests, plan_sha),
        ),
    )
    planned_execution = dataclasses.replace(
        legacy_execution, execution_plan_sha256=plan_sha
    )

    assert planned.to_dict()["execution_plan_sha256"] == plan_sha
    assert planned_execution.to_dict()["execution_plan_sha256"] == plan_sha
    assert planned.digest != legacy.digest
    assert planned_execution.digest != legacy_execution.digest
    assert EffectLeaseRequest.from_dict(planned.to_dict()) == planned


def test_lease_refuses_noncentral_and_undeclared_entrypoints() -> None:
    req = request()
    policy = decision(req)
    unguarded = dataclasses.replace(central_spec(), wiring=Wiring.UNGUARDED)
    with pytest.raises(EffectLeaseBindingMismatch, match="not central"):
        lease(req=req, policy=policy, reg={unguarded.id: unguarded})
    with pytest.raises(EffectLeaseBindingMismatch, match="unknown entrypoint"):
        lease(req=req, policy=policy, reg={})


def test_policy_request_scope_and_subject_are_exact() -> None:
    req = request()
    wrong_subject = dataclasses.replace(decision(req), subject_id="other")
    with pytest.raises(EffectLeaseBindingMismatch, match="subject_id"):
        lease(req=req, policy=wrong_subject)
    widened = scope(max_concurrency=2)
    wrong_scope = dataclasses.replace(decision(req), effect_scope=widened)
    with pytest.raises(EffectLeaseBindingMismatch, match="scope"):
        lease(req=req, policy=wrong_scope)


def test_signature_tampering_unknown_key_expiry_and_kill_switch_are_refused() -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    tampered = dataclasses.replace(value, requested_effects=(Effect.SPEND.value,))
    with pytest.raises(EffectLeaseSignatureError, match="signature"):
        verify_effect_lease(
            tampered,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=1),
            registry=registry(),
        )
    with pytest.raises(EffectLeaseSignatureError, match="unknown"):
        verify_effect_lease(
            value,
            request=req,
            policy_decision=policy,
            keyring={},
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=1),
            registry=registry(),
        )
    with pytest.raises(EffectLeaseExpired, match="expired"):
        verify_effect_lease(
            value,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=7,
            now=NOW + timedelta(minutes=10),
            registry=registry(),
        )
    with pytest.raises(EffectLeaseBindingMismatch, match="kill-switch"):
        verify_effect_lease(
            value,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=8,
            now=NOW + timedelta(seconds=1),
            registry=registry(),
        )


def test_registry_revision_is_bound() -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    changed = dataclasses.replace(central_spec(), notes="changed registry content")
    with pytest.raises(EffectLeaseBindingMismatch, match="registry changed"):
        verify_effect_lease(
            value,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=1),
            registry={changed.id: changed},
        )


def test_runtime_entrypoint_requires_manifest_and_conformance() -> None:
    req = request(runtime=False)
    with pytest.raises(EffectLeaseBindingMismatch, match="runtime entrypoints"):
        lease(req=req, policy=decision(req), reg=registry(runtime_id="claude"))
    runtime_req = request(runtime=True)
    value = lease(req=runtime_req, policy=decision(runtime_req), reg=registry(runtime_id="claude"))
    assert value.runtime_id == "claude"


def test_grant_must_precede_start_and_is_idempotent(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    with pytest.raises(EffectLeaseStateError, match="not persisted"):
        begin(ledger, value, req, policy)
    grant(ledger, value, req, policy)
    grant(ledger, value, req, policy)
    result = begin(ledger, value, req, policy)
    assert result.execute is True
    assert ledger.execution_state("execution-1") == "STARTED"


def test_restart_recovers_authenticated_grant_from_the_shared_spine_database(
    tmp_path,
) -> None:
    """Intent and effect recovery use one SQLite authority, never a sidecar."""

    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "canonical-spine.sqlite3"
    with SpineLedger(path) as spine:
        intent = spine.record_intent(
            "attempt.candidate", {"task_id": "task-1"}, effect_key="branch-1"
        )

    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    restarted = EffectLeaseLedger(path)
    recovered = restarted.load_grant(
        value.digest,
        keyring={"kernel-key-1": SECRET},
        current_kill_switch_generation=7,
        now=NOW + timedelta(seconds=1),
        registry=registry(),
    )

    assert recovered.lease == value
    assert recovered.request == req
    assert recovered.policy_decision == policy
    assert recovered.revoked_at is None
    with SpineLedger(path, read_only=True) as spine:
        assert spine.get(intent.id).effect_key == "branch-1"
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"intents", "intent_events", "effect_leases", "effect_executions"} <= tables
    assert SECRET not in path.read_bytes()


def test_restart_distinguishes_started_and_terminal_execution_receipts(
    tmp_path,
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "canonical-spine.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    started = begin(ledger, value, req, policy)

    restarted = EffectLeaseLedger(path)
    open_record = restarted.execution_record("execution-1")
    assert open_record is not None
    assert open_record.request == execution()
    assert open_record.start_receipt == started.receipt
    assert open_record.state == "STARTED"
    assert open_record.terminal_receipt is None

    terminal = restarted.finish(
        open_record.start_receipt,
        outcome="completed",
        output_digests=("e" * 64,),
        finished_at=NOW + timedelta(seconds=2),
    )
    terminal_record = EffectLeaseLedger(path).execution_record("execution-1")
    assert terminal_record is not None
    assert terminal_record.state == "COMPLETED"
    assert terminal_record.terminal_receipt == terminal


def test_recovery_refuses_tampered_persisted_contract_and_receipt_bytes(
    tmp_path,
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "canonical-spine.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    begin(ledger, value, req, policy)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE effect_leases SET request_json=request_json || ' '"
        )
    with pytest.raises(EffectLeaseStateError, match="canonical identity"):
        ledger.load_grant(
            value.digest,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=1),
            registry=registry(),
        )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE effect_executions SET start_receipt_json=start_receipt_json || ' '"
        )
    with pytest.raises(EffectLeaseStateError, match="start identity"):
        ledger.execution_record("execution-1")


def test_execution_recovery_refuses_coherently_rehashed_malformed_receipt(
    tmp_path,
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "canonical-spine.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    begin(ledger, value, req, policy)

    with sqlite3.connect(path) as connection:
        raw = connection.execute(
            "SELECT start_receipt_json FROM effect_executions"
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["boundary_receipt_sha256"] = "not-a-digest"
        digest_body = dict(payload)
        digest_body.pop("receipt_sha256")
        payload["receipt_sha256"] = canonical_sha(digest_body)
        connection.execute(
            """
            UPDATE effect_executions
            SET start_receipt_json=?, start_receipt_sha256=?
            """,
            (canonical_json(payload), payload["receipt_sha256"]),
        )

    with pytest.raises(EffectLeaseStateError, match="invalid start bytes"):
        ledger.execution_record("execution-1")


def test_replay_returns_existing_receipt_without_second_effect(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    first = begin(ledger, value, req, policy)
    second = begin(ledger, value, req, policy)
    assert first.execute is True
    assert second.execute is False
    assert second.receipt == first.receipt


@pytest.mark.parametrize(
    ("current_veto", "expected_new_error"),
    (
        ("expired", EffectLeaseExpired),
        ("revoked", EffectLeaseStateError),
        ("kill_switch", EffectLeaseBindingMismatch),
        ("guards", EffectStartRefused),
        ("registry", EffectLeaseBindingMismatch),
    ),
)
def test_restart_exact_replay_is_inert_despite_current_start_vetos(
    tmp_path, current_veto, expected_new_error
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / f"{current_veto}.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    first = begin(ledger, value, req, policy)

    restarted = EffectLeaseLedger(path)
    started_at = NOW + timedelta(seconds=3)
    current_generation = 7
    current_guards = guards()
    current_registry = registry()
    if current_veto == "expired":
        started_at = NOW + timedelta(minutes=10)
    elif current_veto == "revoked":
        restarted.revoke(
            value.digest,
            reason="owner cancelled mission",
            revoked_at=NOW + timedelta(seconds=2),
        )
    elif current_veto == "kill_switch":
        current_generation = 8
    elif current_veto == "guards":
        current_guards = (
            GuardDecision("budget.process_guard", False, "budget exhausted"),
        )
    elif current_veto == "registry":
        changed = dataclasses.replace(central_spec(), notes="changed registry")
        current_registry = {changed.id: changed}

    replay = restarted.begin(
        value,
        execution(),
        request=req,
        policy_decision=policy,
        keyring={"kernel-key-1": SECRET},
        guard_decisions=current_guards,
        current_kill_switch_generation=current_generation,
        started_at=started_at,
        registry=current_registry,
    )
    assert replay.execute is False
    assert replay.receipt == first.receipt

    new_execution = execution(
        execution_id="execution-2", idempotency_key="idem-2"
    )
    with pytest.raises(expected_new_error):
        restarted.begin(
            value,
            new_execution,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=current_guards,
            current_kill_switch_generation=current_generation,
            started_at=started_at,
            registry=current_registry,
        )
    assert restarted.execution_state("execution-2") is None


def test_restart_replay_still_authenticates_key_signature_identity_and_scope(
    tmp_path,
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "leases.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    first = begin(ledger, value, req, policy)
    restarted = EffectLeaseLedger(path)

    common = {
        "request": req,
        "policy_decision": policy,
        "guard_decisions": guards(),
        "current_kill_switch_generation": 8,
        "started_at": NOW + timedelta(minutes=10),
        "registry": registry(),
    }
    with pytest.raises(EffectLeaseSignatureError, match="unknown"):
        restarted.begin(value, execution(), keyring={}, **common)
    with pytest.raises(EffectLeaseSignatureError, match="signature"):
        restarted.begin(
            value,
            execution(),
            keyring={"kernel-key-1": b"wrong-key-material-at-least-32-bytes"},
            **common,
        )
    tampered = dataclasses.replace(value, signature_sha256="0" * 64)
    with pytest.raises(EffectLeaseSignatureError, match="signature"):
        restarted.begin(
            tampered,
            execution(),
            keyring={"kernel-key-1": SECRET},
            **common,
        )

    changed_request = dataclasses.replace(req, mission_id="mission-2")
    with pytest.raises(EffectLeaseBindingMismatch, match="request_sha256"):
        restarted.begin(
            value,
            execution(),
            request=changed_request,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=8,
            started_at=NOW + timedelta(minutes=10),
            registry=registry(),
        )
    changed_policy = dataclasses.replace(policy, reasons=("different policy",))
    with pytest.raises(EffectLeaseBindingMismatch, match="policy_decision_sha256"):
        restarted.begin(
            value,
            execution(),
            request=req,
            policy_decision=changed_policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=8,
            started_at=NOW + timedelta(minutes=10),
            registry=registry(),
        )

    changed_scope = execution(path="workspace/other.txt")
    with pytest.raises(EffectLeaseReplay, match="different lease or scope"):
        restarted.begin(
            value,
            changed_scope,
            keyring={"kernel-key-1": SECRET},
            **common,
        )
    changed_execution_id = execution(
        execution_id="execution-2", idempotency_key="idem-1"
    )
    with pytest.raises(EffectLeaseReplay, match="different lease or scope"):
        restarted.begin(
            value,
            changed_execution_id,
            keyring={"kernel-key-1": SECRET},
            **common,
        )
    changed_idempotency = execution(idempotency_key="idem-2")
    with pytest.raises(EffectLeaseReplay, match="different lease or scope"):
        restarted.begin(
            value,
            changed_idempotency,
            keyring={"kernel-key-1": SECRET},
            **common,
        )
    assert restarted.execution_record("execution-1").start_receipt == first.receipt


@pytest.mark.parametrize(
    ("table", "column", "expected_error"),
    (
        ("effect_leases", "lease_json", EffectLeaseStateError),
        ("effect_leases", "request_json", EffectLeaseStateError),
        ("effect_leases", "policy_decision_json", EffectLeaseStateError),
        ("effect_executions", "request_json", EffectLeaseStateError),
        ("effect_executions", "request_sha256", EffectLeaseReplay),
        ("effect_executions", "start_receipt_json", EffectLeaseStateError),
        ("effect_executions", "start_receipt_sha256", EffectLeaseStateError),
    ),
)
def test_restart_replay_refuses_tampered_persisted_identity_bytes(
    tmp_path, table, column, expected_error
) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / f"{table}-{column}.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    begin(ledger, value, req, policy)

    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            f"SELECT {column} FROM {table}"
        ).fetchone()[0]
        tampered = "0" * 64 if column.endswith("sha256") else stored + " "
        connection.execute(f"UPDATE {table} SET {column}=?", (tampered,))

    with pytest.raises(expected_error):
        EffectLeaseLedger(path).begin(
            value,
            execution(),
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=8,
            started_at=NOW + timedelta(minutes=10),
            registry=registry(),
        )


def test_concurrent_revoked_restart_replays_are_serialized_and_inert(
    tmp_path,
) -> None:
    import concurrent.futures

    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    path = tmp_path / "leases.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    first = begin(ledger, value, req, policy)
    ledger.revoke(
        value.digest,
        reason="owner cancelled mission",
        revoked_at=NOW + timedelta(seconds=2),
    )

    def replay(_index):
        return EffectLeaseLedger(path).begin(
            value,
            execution(),
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=(
                GuardDecision("budget.process_guard", False, "budget exhausted"),
            ),
            current_kill_switch_generation=8,
            started_at=NOW + timedelta(minutes=10),
            registry=registry(),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(replay, range(8)))
    assert all(result.execute is False for result in results)
    assert all(result.receipt == first.receipt for result in results)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM effect_executions"
        ).fetchone()[0] == 1


def test_reused_idempotency_or_execution_identity_cannot_change_scope(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    begin(ledger, value, req, policy)
    changed = execution(execution_id="execution-2", idempotency_key="idem-1", path="workspace/other.txt")
    with pytest.raises(EffectLeaseReplay, match="different lease or scope"):
        begin(ledger, value, req, policy, changed)


def test_path_containment_uses_components_not_prefix_strings(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    with pytest.raises(EffectLeaseScopeError, match="outside"):
        begin(ledger, value, req, policy, execution(path="workspace-evil/out.txt"))
    with pytest.raises(ValueError, match="inside"):
        execution(path="workspace/../escape.txt")


def test_scope_escalation_is_refused(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    over_cost = dataclasses.replace(execution(), max_cost_microusd=101)
    with pytest.raises(EffectLeaseScopeError, match="cost"):
        begin(ledger, value, req, policy, over_cost)
    extra_tool = dataclasses.replace(execution(), tools=("git",))
    with pytest.raises(EffectLeaseScopeError, match="tool"):
        begin(ledger, value, req, policy, extra_tool)
    extra_effect = dataclasses.replace(
        execution(), requested_effects=execution().requested_effects + (Effect.NETWORK_EGRESS.value,)
    )
    with pytest.raises(EffectLeaseScopeError, match="outside lease"):
        begin(ledger, value, req, policy, extra_effect)


def test_concurrency_ceiling_is_enforced_and_terminal_releases_slot(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    first = begin(ledger, value, req, policy)
    second_request = execution(execution_id="execution-2", idempotency_key="idem-2")
    with pytest.raises(EffectLeaseConcurrencyError):
        begin(ledger, value, req, policy, second_request)
    ledger.finish(first.receipt, outcome="completed", output_digests=("f" * 64,), finished_at=NOW + timedelta(seconds=2))
    second = begin(ledger, value, req, policy, second_request)
    assert second.execute is True


def test_revocation_refuses_new_starts(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    ledger.revoke(value.digest, reason="owner cancelled mission", revoked_at=NOW + timedelta(seconds=1))
    with pytest.raises(EffectLeaseStateError, match="revoked"):
        begin(ledger, value, req, policy)


def test_terminal_receipt_is_bound_and_duplicate_terminal_is_refused(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    started = begin(ledger, value, req, policy)
    terminal = ledger.finish(
        started.receipt,
        outcome="failed",
        detail_sha256="1" * 64,
        finished_at=NOW + timedelta(seconds=2),
    )
    assert terminal.start_receipt_sha256 == started.receipt.receipt_sha256
    assert ledger.execution_state("execution-1") == "FAILED"
    with pytest.raises(EffectLeaseStateError, match="terminal"):
        ledger.finish(started.receipt, outcome="failed")


def test_expiry_is_rechecked_after_verification_before_start(tmp_path, monkeypatch) -> None:
    req = request()
    policy = decision(req)
    value = issue_effect_lease(
        req,
        policy,
        lease_id="lease-short",
        issuer_key_id="kernel-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=2),
        secret=SECRET,
        registry=registry(),
    )
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    from daedalus.kernel import effects as effects_module

    instants = iter((NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
    monkeypatch.setattr(effects_module, "_utc_now", lambda: next(instants))
    with pytest.raises(EffectLeaseExpired, match="expired before start"):
        ledger.begin(
            value,
            execution(),
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=guards(),
            current_kill_switch_generation=7,
            registry=registry(),
        )


def test_corrupt_ledger_fails_closed(tmp_path) -> None:
    path = tmp_path / "leases.sqlite3"
    path.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        EffectLeaseLedger(path)


def test_lease_ttl_is_bounded() -> None:
    req = request()
    policy = decision(req)
    with pytest.raises(ValueError, match="24-hour"):
        issue_effect_lease(
            req,
            policy,
            lease_id="lease-long",
            issuer_key_id="kernel-key-1",
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=25),
            secret=SECRET,
            registry=registry(),
        )


def test_grant_authenticates_before_persisting(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    tampered = dataclasses.replace(value, signature_sha256="0" * 64)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    with pytest.raises(EffectLeaseSignatureError):
        grant(ledger, tampered, req, policy)
    with sqlite3.connect(tmp_path / "leases.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM effect_leases").fetchone()[0] == 0


def test_deny_policy_cannot_issue_a_lease() -> None:
    req = request()
    denied = decision(req, verdict="deny", effect_scope=EffectScope())
    with pytest.raises(EffectLeaseBindingMismatch, match="deny"):
        lease(req=req, policy=denied)


def test_guard_denial_happens_before_execution_persistence(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    with pytest.raises(Exception, match="denied"):
        ledger.begin(
            value,
            execution(),
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            guard_decisions=(GuardDecision("budget.process_guard", False, "budget exhausted"),),
            current_kill_switch_generation=7,
            started_at=NOW + timedelta(seconds=1),
            registry=registry(),
        )
    assert ledger.execution_state("execution-1") is None


def test_concurrent_starts_cannot_exceed_one_active_slot(tmp_path) -> None:
    import concurrent.futures

    req = request(effect_scope=scope(max_concurrency=1))
    policy = decision(req)
    value = lease(req=req, policy=policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)

    def start(index: int) -> str:
        candidate = execution(
            execution_id=f"execution-{index}",
            idempotency_key=f"idem-{index}",
        )
        try:
            begin(ledger, value, req, policy, candidate)
            return "started"
        except EffectLeaseConcurrencyError:
            return "refused"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(start, range(8)))
    assert results.count("started") == 1
    assert results.count("refused") == 7


def test_execution_id_cannot_be_replayed_across_leases(tmp_path) -> None:
    req = request()
    policy = decision(req)
    first_lease = lease(req=req, policy=policy)
    second_lease = issue_effect_lease(
        req,
        policy,
        lease_id="lease-2",
        issuer_key_id="kernel-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        secret=SECRET,
        registry=registry(),
    )
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, first_lease, req, policy)
    grant(ledger, second_lease, req, policy)
    begin(ledger, first_lease, req, policy)
    with pytest.raises(EffectLeaseReplay, match="different lease"):
        begin(ledger, second_lease, req, policy)


def test_resigned_but_revision_inconsistent_lease_is_refused() -> None:
    req = request()
    policy = decision(req)
    value = lease(req=req, policy=policy)
    foreign_provenance = dataclasses.replace(
        value.provenance,
        source_revision="c" * 40,
    )
    placeholder = dataclasses.replace(
        value,
        provenance=foreign_provenance,
        signature_sha256="0" * 64,
    )
    from daedalus.kernel import effects as effects_module

    resigned = dataclasses.replace(
        placeholder,
        signature_sha256=effects_module._signature(placeholder.signing_digest, SECRET),
    )
    with pytest.raises(EffectLeaseBindingMismatch, match="source_revision"):
        verify_effect_lease(
            resigned,
            request=req,
            policy_decision=policy,
            keyring={"kernel-key-1": SECRET},
            current_kill_switch_generation=7,
            now=NOW + timedelta(seconds=1),
            registry=registry(),
        )


def test_effect_lease_json_schemas_are_closed_and_complete() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    request_schema = json.loads(
        (root / "configs/schemas/effect-lease-request-v1.schema.json").read_text()
    )
    lease_schema = json.loads(
        (root / "configs/schemas/effect-lease-v1.schema.json").read_text()
    )
    assert request_schema["additionalProperties"] is False
    assert lease_schema["additionalProperties"] is False
    assert request_schema["properties"]["contract_type"] == {
        "const": "daedalus.effect-lease-request"
    }
    assert lease_schema["properties"]["contract_type"] == {
        "const": "daedalus.effect-lease"
    }
    assert set(request().to_dict()) == set(request_schema["required"])
    assert request_schema["properties"]["execution_plan_sha256"] == {
        "$ref": "#/$defs/sha256"
    }
    assert set(lease().to_dict()) == set(lease_schema["required"])
