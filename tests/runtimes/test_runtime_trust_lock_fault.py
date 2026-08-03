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
from daedalus.runtimes.broker import (
    RuntimeProviderTrustFenceError,
    run_runtime_provider,
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


REVISION = "1" * 40
POLICY_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
IDENTITY_SHA = "4" * 64
RECEIPT_SHA = "5" * 64
ENVELOPE_SHA = "6" * 64
OUTPUT_SHA = "7" * 64
TRUST_KEY = b"runtime-trust-ledger-integrity-key-material-32-bytes"
LEASE_KEY = b"effect-lease-kernel-secret-material-32-bytes-minimum"
AUTHORITY_KEY = b"runtime-lease-authority-key-material-at-least-32-bytes"
ENTRYPOINT = "provider.test-runtime-lock"
RUNTIME = "codex_cli"
BUSY_TIMEOUT_MS = 125


class FastRuntimeTrustLedger(RuntimeTrustLedger):
    """Production trust schema with a bounded test-only writer timeout."""

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            return connection
        except BaseException:
            connection.close()
            raise


def _spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.CODEX,
        target="tests.fake_runtime_lock:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id=RUNTIME,
    )


def _scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("codex",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )


def _request(now: datetime) -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="runtime-lock-request-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        entrypoint_id=ENTRYPOINT,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=_scope(),
        idempotency_namespace="mission-1-attempt-1",
        kill_switch_generation=7,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=RECEIPT_SHA,
        provenance=ContractProvenance(
            origin="tests.runtime-trust-lock",
            source_revision=REVISION,
            created_at=(now - timedelta(minutes=1)).isoformat(),
            input_digests=(MANIFEST_SHA, RECEIPT_SHA),
            trace_id="mission-1",
        ),
    )


def _decision(request: EffectLeaseRequest, now: datetime) -> PolicyDecision:
    return PolicyDecision(
        decision_id="runtime-lock-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded trusted runtime",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.runtime-trust-lock-policy",
            source_revision=REVISION,
            created_at=(now - timedelta(minutes=1)).isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-1",
        ),
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="runtime-lock-execution-1",
        idempotency_key="runtime-lock-idempotency-1",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        writable_paths=("workspace/out.txt",),
        tools=("codex",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )


def _authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[RuntimeBoundEffectAuthorization, FastRuntimeTrustLedger]:
    now = datetime.now(timezone.utc)
    trust_ledger = FastRuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3",
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
        finished_at=(now - timedelta(minutes=10)).isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id=RUNTIME,
        runtime_manifest_sha256=MANIFEST_SHA,
        probe_identity_sha256=IDENTITY_SHA,
        conformance_receipt_sha256=RECEIPT_SHA,
        source_revision=REVISION,
        digest=ENVELOPE_SHA,
    )
    trust_ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(ENVELOPE_SHA,),
        admitted_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
    )

    request = _request(now)
    policy = _decision(request, now)
    registry = {ENTRYPOINT: _spec()}
    capability = issue_runtime_bound_effect_lease(
        request,
        policy,
        lease_id="runtime-lock-lease-1",
        lease_issuer_key_id="lease-key-1",
        lease_issuer_secret=LEASE_KEY,
        runtime_envelope_sha256=ENVELOPE_SHA,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="runtime-authority-1",
        runtime_authority_secret=AUTHORITY_KEY,
        issued_at=now - timedelta(seconds=30),
        expires_at=now + timedelta(minutes=20),
        registry=registry,
    )
    authorization = RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effect-leases.sqlite3"),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"lease-key-1": LEASE_KEY},
        runtime_authority_keyring={"runtime-authority-1": AUTHORITY_KEY},
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "8" * 64,
            ),
        ),
        current_kill_switch_generation=7,
        registry=registry,
    )
    return authorization, trust_ledger


def test_runtime_trust_writer_lock_cancels_durable_effect_and_withholds_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, trust_ledger = _authorization(tmp_path, monkeypatch)
    writer = trust_ledger._connect()
    writer.execute("BEGIN IMMEDIATE")
    assert writer.in_transaction is True
    provider_calls: list[str] = []
    evidence_calls: list[object] = []

    try:
        with pytest.raises(RuntimeProviderTrustFenceError) as caught:
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=_execution(),
                invoke=lambda: provider_calls.append("invoked")
                or {"must": "not be released"},
                output_digests=lambda value: evidence_calls.append(value)
                or (OUTPUT_SHA,),
            )
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert str(caught.value) == "runtime trust terminal fence could not be acquired"
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
    assert "locked" not in str(caught.value).lower()
    assert provider_calls == ["invoked"]
    assert evidence_calls == [{"must": "not be released"}]
    assert (
        authorization.effect_ledger.execution_state("runtime-lock-execution-1")
        == "CANCELLED"
    )


def test_runtime_trust_lock_regression_kills_raw_sqlite_escape_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing the sqlite-to-trust-fence translation makes this test fail."""

    authorization, trust_ledger = _authorization(tmp_path, monkeypatch)
    writer = trust_ledger._connect()
    writer.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RuntimeProviderTrustFenceError):
            run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,
                execution=_execution(),
                invoke=lambda: "unreleased-output",
                output_digests=lambda value: (OUTPUT_SHA,),
            )
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert (
        authorization.effect_ledger.execution_state("runtime-lock-execution-1")
        == "CANCELLED"
    )
