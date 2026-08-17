"""Terminal trust fence stays read-only on the runtime trust ledger.

Since G0-RTC-07A the broker refuses duck-typed or subclassed authority
objects, so this scenario composes the real persisted stack — an admitted
runtime trust record, a signed runtime-bound Effect Lease, the SQLite effect
ledger, and the signed provider-observation authority with its binding
ledger — and then arms a COMMIT tripwire on the trust ledger's connections:
after admission, every explicit COMMIT on the trust store raises. A run that
still completes, returns a terminal receipt, and leaves the trust-record rows
byte-identical proves the terminal fence's plain verify is read-only where
the old spy-based fake could only count calls.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.runtimes.broker import run_runtime_provider
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

ENTRYPOINT = "provider.release-fence"
RUNTIME = "release_fence_runtime"
REVISION = "a" * 40
NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
OUTPUT_SHA = "a" * 64
POLICY_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
IDENTITY_SHA = "4" * 64
RECEIPT_SHA = "5" * 64
ENVELOPE_SHA = "6" * 64
TRUST_KEY = b"release-fence-trust-integrity-key-material-32-bytes"
LEASE_KEY = b"release-fence-effect-lease-secret-material-32-bytes"
AUTHORITY_KEY = b"release-fence-runtime-authority-key-material-32-b"
OBS_AUTHORITY_KEY_ID = "release-fence-observation-authority-key"
OBS_AUTHORITY_KEY = b"release-fence-observation-authority-key-material-32b"
OBS_KEY_ID = "release-fence-observation-issuer-key"
OBS_KEY = b"release-fence-observation-issuer-key-material-32-b"
RECORD_KEY = b"release-fence-observation-record-key-material-32b"


class _NoCommitConnection:
    """Connection proxy that refuses persisting any change to the trust store.

    The start-phase lookup legitimately runs ``BEGIN IMMEDIATE`` so an
    expired record can be quarantined atomically; on the happy path its
    COMMIT persists nothing and passes. Any COMMIT — explicit statement,
    ``commit()`` call, or implicit ``with``-block exit — that would persist
    actual row changes raises instead.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._changes_at_begin = connection.total_changes

    def _refuse_dirty_commit(self) -> None:
        if self._connection.total_changes != self._changes_at_begin:
            self._connection.rollback()
            raise sqlite3.OperationalError("read-only fence COMMIT refused")

    def execute(self, statement: str, parameters=()):
        upper = statement.strip().upper()
        if upper.startswith("BEGIN"):
            self._changes_at_begin = self._connection.total_changes
        if upper == "COMMIT":
            self._refuse_dirty_commit()
        return self._connection.execute(statement, parameters)

    def commit(self) -> None:
        self._refuse_dirty_commit()
        self._connection.commit()

    def __enter__(self) -> "_NoCommitConnection":
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._refuse_dirty_commit()
        return self._connection.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.PYTHON,
        target="tests.fake_release_provider:run",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        runtime_id=RUNTIME,
    )


def _registry() -> dict[str, EntrypointSpec]:
    row = _spec()
    return {row.id: row}


def _scope() -> EffectScope:
    return EffectScope(
        read_only=True,
        writable_paths=(),
        egress_endpoints=(),
        tools=(RUNTIME,),
        max_cost_microusd=1000,
        max_concurrency=1,
        timeout_s=600,
        kill_switch_ref="mission-kill",
    )


def _request() -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="release-fence-request-1",
        mission_id="mission-release-1",
        attempt_id="attempt-release-1",
        entrypoint_id=ENTRYPOINT,
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        effect_scope=_scope(),
        idempotency_namespace="mission-release-1-attempt-release-1",
        kill_switch_generation=1,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=RECEIPT_SHA,
        provenance=ContractProvenance(
            origin="tests.runtime-terminal-fence-release",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(MANIFEST_SHA, RECEIPT_SHA),
            trace_id="mission-release-1",
        ),
    )


def _policy(request: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="release-fence-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-17",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded read-only terminal-fence release test",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.runtime-terminal-fence-release-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-release-1",
        ),
    )


def _trust_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimeTrustLedger:
    ledger = RuntimeTrustLedger(
        tmp_path / "release-runtime-trust.sqlite3",
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


def _arm_no_commit_tripwire(ledger: RuntimeTrustLedger) -> None:
    """Every trust-store connection opened from here on refuses COMMIT."""

    original_connect = ledger._connect
    ledger._connect = lambda: _NoCommitConnection(original_connect())  # type: ignore[method-assign]


def _authorization(
    tmp_path: Path,
    trust_ledger: RuntimeTrustLedger,
) -> RuntimeBoundEffectAuthorization:
    request = _request()
    policy = _policy(request)
    registry = _registry()
    capability = issue_runtime_bound_effect_lease(
        request,
        policy,
        lease_id="release-fence-lease-1",
        lease_issuer_key_id="release-fence-lease-key-1",
        lease_issuer_secret=LEASE_KEY,
        runtime_envelope_sha256=ENVELOPE_SHA,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="release-fence-authority-key-1",
        runtime_authority_secret=AUTHORITY_KEY,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        registry=registry,
    )
    return RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "release-effect-leases.sqlite3"),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"release-fence-lease-key-1": LEASE_KEY},
        runtime_authority_keyring={"release-fence-authority-key-1": AUTHORITY_KEY},
        guard_decisions=(
            GuardDecision(
                "runtime.adapter_profile",
                True,
                "artifact-locator:sha256:" + "c" * 64,
            ),
        ),
        current_kill_switch_generation=1,
        registry=registry,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="release-execution",
        idempotency_key="release-idempotency",
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        tools=(RUNTIME,),
        kill_switch_ref="mission-kill",
        kill_switch_generation=1,
    )


def _observation(
    tmp_path: Path,
    authorization: RuntimeBoundEffectAuthorization,
    execution: EffectExecutionRequest,
):
    ledger = ProviderObservationBindingLedger(
        tmp_path / "release-provider-observation.sqlite3",
        authority_id="authority.release-fence-observation",
        authority_keyring={OBS_AUTHORITY_KEY_ID: OBS_AUTHORITY_KEY},
        observation_keyring={OBS_KEY_ID: OBS_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.release-fence-observation",
        authority_key_id=OBS_AUTHORITY_KEY_ID,
        authority_secret=OBS_AUTHORITY_KEY,
        binding_id="release-fence-binding-1",
        provider_id="provider.release-fence-runtime",
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


def _trust_rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT * FROM runtime_trust_records ORDER BY envelope_sha256"
        ).fetchall()
    finally:
        connection.close()


def test_read_only_trust_fence_does_not_commit_after_effect_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_clocks(monkeypatch)
    trust_ledger = _trust_ledger(tmp_path, monkeypatch)
    authorization = _authorization(tmp_path, trust_ledger)
    execution = _execution()
    authority, binding_ledger = _observation(tmp_path, authorization, execution)

    trust_db = tmp_path / "release-runtime-trust.sqlite3"
    rows_before = _trust_rows(trust_db)
    assert rows_before, "admission must have persisted a trust record"

    _arm_no_commit_tripwire(trust_ledger)

    result = run_runtime_provider(
        ENTRYPOINT,
        authorization=authorization,
        execution=execution,
        invoke=lambda: {"answer": 42},
        output_digests=lambda value: (OUTPUT_SHA,),
        observation_authority=authority,
        observation_binding_ledger=binding_ledger,
    )

    assert result.executed is True
    assert result.value == {"answer": 42}
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"
    # The tripwire proves no explicit COMMIT reached the trust store, and the
    # byte-identical rows prove the fence changed nothing durable there.
    assert _trust_rows(trust_db) == rows_before
