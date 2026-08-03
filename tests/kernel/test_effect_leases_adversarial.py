from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseExpired,
    EffectLeaseLedger,
    EffectLeaseStateError,
    issue_effect_lease,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)

REVISION = "8" * 40
POLICY_SHA = "9" * 64
SECRET = b"adversarial-effect-lease-secret-material-32-bytes"
NOW = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)


def spec(*, notes: str = "") -> EntrypointSpec:
    return EntrypointSpec(
        id="python.adversarial-attempt",
        surface=Surface.PYTHON,
        target="tests.fake:run",
        effects=(Effect.FILESYSTEM_WRITE,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        notes=notes,
    )


def registry(*, notes: str = "") -> dict[str, EntrypointSpec]:
    row = spec(notes=notes)
    return {row.id: row}


def scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )


def request() -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="request-adversarial",
        mission_id="mission-adversarial",
        attempt_id="attempt-adversarial",
        entrypoint_id="python.adversarial-attempt",
        requested_effects=(Effect.FILESYSTEM_WRITE.value,),
        effect_scope=scope(),
        idempotency_namespace="mission-adversarial-attempt-adversarial",
        kill_switch_generation=3,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.effect-lease-adversarial-request",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            trace_id="mission-adversarial",
        ),
    )


def decision(req: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="decision-adversarial",
        subject_id=req.request_id,
        subject_sha256=req.digest,
        policy_version="2026-08-03",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded fixture",),
        effect_scope=req.effect_scope,
        provenance=ContractProvenance(
            origin="tests.effect-lease-adversarial-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(req.digest, POLICY_SHA),
            trace_id="mission-adversarial",
        ),
    )


def lease(
    req: EffectLeaseRequest,
    policy: PolicyDecision,
    *,
    expires_at: datetime | None = None,
) -> EffectLease:
    return issue_effect_lease(
        req,
        policy,
        lease_id="lease-adversarial",
        issuer_key_id="issuer-adversarial",
        issued_at=NOW,
        expires_at=expires_at or (NOW + timedelta(minutes=10)),
        secret=SECRET,
        registry=registry(),
    )


def execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="execution-adversarial",
        idempotency_key="idempotency-adversarial",
        requested_effects=(Effect.FILESYSTEM_WRITE.value,),
        writable_paths=("workspace/out.txt",),
        kill_switch_ref="mission-kill",
        kill_switch_generation=3,
    )


def guards() -> tuple[GuardDecision, ...]:
    return (
        GuardDecision(
            "budget.process_guard",
            True,
            "artifact-locator:sha256:" + "a" * 64,
        ),
    )


def grant(
    ledger: EffectLeaseLedger,
    value: EffectLease,
    req: EffectLeaseRequest,
    policy: PolicyDecision,
) -> None:
    ledger.grant(
        value,
        request=req,
        policy_decision=policy,
        keyring={"issuer-adversarial": SECRET},
        current_kill_switch_generation=3,
        granted_at=NOW + timedelta(milliseconds=500),
        registry=registry(),
    )


def begin(
    ledger: EffectLeaseLedger,
    value: EffectLease,
    req: EffectLeaseRequest,
    policy: PolicyDecision,
    *,
    registry_value: Mapping[str, EntrypointSpec] | None = None,
):
    return ledger.begin(
        value,
        execution(),
        request=req,
        policy_decision=policy,
        keyring={"issuer-adversarial": SECRET},
        guard_decisions=guards(),
        current_kill_switch_generation=3,
        started_at=NOW + timedelta(seconds=1),
        registry=registry_value or registry(),
    )


class FlippingRegistry(Mapping[str, EntrypointSpec]):
    """Return a different immutable snapshot on successive materializations."""

    def __init__(self, snapshots: tuple[dict[str, EntrypointSpec], ...]):
        self._snapshots = snapshots
        self._index = 0
        self._active = snapshots[0]

    def __iter__(self) -> Iterator[str]:
        self._active = self._snapshots[min(self._index, len(self._snapshots) - 1)]
        self._index += 1
        return iter(self._active)

    def __len__(self) -> int:
        return len(self._active)

    def __getitem__(self, key: str) -> EntrypointSpec:
        return self._active[key]


def test_registry_flip_between_verification_and_boundary_is_refused(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)

    changing = FlippingRegistry(
        (registry(), registry(notes="changed after verification"))
    )
    with pytest.raises(EffectLeaseBindingMismatch, match="registry changed"):
        begin(
            ledger,
            value,
            req,
            policy,
            registry_value=changing,
        )
    assert ledger.execution_state(execution().execution_id) is None


def test_corrupt_persisted_replay_receipt_fails_closed(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    path = tmp_path / "leases.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    assert begin(ledger, value, req, policy).execute is True

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE effect_executions SET start_receipt_json=? WHERE execution_id=?",
            ("{", execution().execution_id),
        )
    with pytest.raises(EffectLeaseStateError, match="receipt is corrupt"):
        begin(ledger, value, req, policy)


def test_self_consistent_but_row_mismatched_replay_receipt_fails_closed(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    path = tmp_path / "leases.sqlite3"
    ledger = EffectLeaseLedger(path)
    grant(ledger, value, req, policy)
    started = begin(ledger, value, req, policy)

    payload = started.receipt.payload_dict()
    payload["execution_id"] = "execution-other"
    payload["receipt_sha256"] = __import__(
        "daedalus.spine.envelope", fromlist=["canonical_sha"]
    ).canonical_sha({key: value for key, value in payload.items() if key != "receipt_sha256"})
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE effect_executions SET start_receipt_json=?, start_receipt_sha256=? "
            "WHERE execution_id=?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                payload["receipt_sha256"],
                execution().execution_id,
            ),
        )
    with pytest.raises(EffectLeaseStateError, match="does not match"):
        begin(ledger, value, req, policy)


def test_grant_expiry_is_rechecked_inside_transaction(tmp_path, monkeypatch) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy, expires_at=NOW + timedelta(seconds=2))
    path = tmp_path / "leases.sqlite3"
    ledger = EffectLeaseLedger(path)

    from daedalus.kernel import effects as effects_module

    instants = iter((NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)))
    monkeypatch.setattr(effects_module, "_utc_now", lambda: next(instants))
    with pytest.raises(EffectLeaseExpired, match="grant persistence"):
        ledger.grant(
            value,
            request=req,
            policy_decision=policy,
            keyring={"issuer-adversarial": SECRET},
            current_kill_switch_generation=3,
            registry=registry(),
        )
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effect_leases").fetchone()[0] == 0


def test_terminal_receipt_cannot_precede_start(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    started = begin(ledger, value, req, policy)

    with pytest.raises(EffectLeaseStateError, match="before it started"):
        ledger.finish(
            started.receipt,
            outcome="failed",
            finished_at=NOW,
        )
    assert ledger.execution_state(execution().execution_id) == "STARTED"


def test_revocation_cannot_precede_lease_issue(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)

    with pytest.raises(EffectLeaseStateError, match="before it was issued"):
        ledger.revoke(
            value.digest,
            reason="invalid clock",
            revoked_at=NOW - timedelta(seconds=1),
        )


def test_start_receipt_digest_is_structurally_validated(tmp_path) -> None:
    req = request()
    policy = decision(req)
    value = lease(req, policy)
    ledger = EffectLeaseLedger(tmp_path / "leases.sqlite3")
    grant(ledger, value, req, policy)
    started = begin(ledger, value, req, policy)

    with pytest.raises(ValueError, match="digest mismatch"):
        dataclasses.replace(
            started.receipt,
            boundary_receipt_sha256="b" * 64,
        )
